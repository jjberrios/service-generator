"""Synthetic checkpoint and runner concurrency; no pipeline, Maven or live data."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workspace as wsm
from artifact_integrity import service_lock


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve()
        for name in ('input', 'archetypes', 'output', '.opencode'):
            (self.repo / name).mkdir()
        self.ws = wsm.Workspace(self.repo, 'svc-test').ensure()
        self.script = self.repo / '.opencode/skills/probe/scripts/probe.py'
        self.script.parent.mkdir(parents=True)

    def probe(self, text):
        self.script.write_text(text, encoding='utf-8')
        return self.script

    def runs(self):
        return [json.loads(p.read_bytes()) for p in (self.ws.dir / 'runs').glob('*.json')]

    def test_checkpoint_parallel_merges_and_phase_completion_preserve_manual_metadata(self):
        self.ws.set_state(manual={'note': 'keep'}, reviewedDecisions={'sha256': 'keep'})
        barrier = threading.Barrier(12)

        def update(i):
            barrier.wait()
            self.ws.set_state(**{f'field{i}': i})
            self.ws.complete_phase(f'phase-{i}')

        with service_lock(self.repo, self.ws.service):
            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(update, range(12)))
        state = self.ws.state()
        self.assertEqual(state['manual'], {'note': 'keep'})
        self.assertEqual(state['reviewedDecisions'], {'sha256': 'keep'})
        self.assertEqual(set(state['completedPhases']), {f'phase-{i}' for i in range(12)})
        for i in range(12):
            self.assertEqual(state[f'field{i}'], i)
        self.assertFalse((self.ws.dir / '.checkpoint.lock').exists())

    def test_lock_is_not_deleted_or_stolen_on_timeout(self):
        target = self.ws.dir / '.checkpoint.lock'
        target.write_text('manual inspection required')
        with self.assertRaises(wsm.WorkspaceError):
            with self.ws._checkpoint_lock(timeout=0):
                self.fail('must not enter')
        self.assertEqual(target.read_text(), 'manual inspection required')

    def test_noncooperating_checkpoint_edit_is_not_overwritten(self):
        self.ws.set_state(status='before')

        def manual_edit(state):
            state['status'] = 'machine'
            self.ws.state_file.write_text('targetService: svc-test\nstatus: manual\n')

        with self.assertRaisesRegex(wsm.WorkspaceError, 'changed concurrently'):
            self.ws._update_state(manual_edit)
        self.assertEqual(self.ws.state()['status'], 'manual')

    def test_checkpoint_updates_from_separate_processes_are_merged(self):
        self.ws.set_state(manual='keep')
        code = ('import sys; from pathlib import Path; '
                f'sys.path.insert(0, {str(Path(wsm.__file__).parent)!r}); '
                'from workspace import Workspace; '
                'ws = Workspace(Path(sys.argv[1]), "svc-test"); '
                'ws.set_state(**{sys.argv[2]: True}); ws.complete_phase(sys.argv[2])')
        processes = [subprocess.Popen([sys.executable, '-c', code, str(self.repo), f'worker-{i}'],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
        try:
            for process in processes:
                _, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
        state = self.ws.state()
        self.assertEqual(state['manual'], 'keep')
        self.assertEqual(set(state['completedPhases']), {f'worker-{i}' for i in range(4)})
        self.assertTrue(all(state[f'worker-{i}'] for i in range(4)))

    def test_atomic_state_failure_preserves_original_and_removes_unique_temp(self):
        self.ws.set_state(status='before')
        before = self.ws.state_file.read_bytes()
        with patch('artifact_integrity.os.replace', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                self.ws.set_state(status='after')
        self.assertEqual(self.ws.state_file.read_bytes(), before)
        self.assertEqual(list(self.ws.dir.glob('*.tmp')), [])
        for invalid in ([], 'text', {'targetService': 'another-service'}):
            with self.assertRaises(wsm.WorkspaceError):
                self.ws.write_state(invalid)
        self.assertEqual(self.ws.state_file.read_bytes(), before)

    def test_concurrent_runs_have_unique_sandboxes_and_metadata_without_secrets(self):
        self.ws.set_state(currentPhase='target-authority')
        self.probe('import os, time\nprint(os.getcwd())\ntime.sleep(0.3)\n')
        sentinel = self.repo / wsm.SANDBOXES / self.ws.service / 'other-run'
        sentinel.mkdir(parents=True)
        (sentinel / 'keep').write_text('keep')
        telemetry_errors = []
        original_atomic = wsm.write_atomic
        original_safe = wsm.safe_path

        def checked(function):
            def call(*args, **kwargs):
                try:
                    return function(*args, **kwargs)
                except Exception as error:
                    telemetry_errors.append(repr(error))
                    raise
            return call

        with patch.object(wsm, 'write_atomic', side_effect=checked(original_atomic)), patch.object(wsm, 'safe_path', side_effect=checked(original_safe)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: wsm.run_script(self.ws, self.script, ['secret-token'], timeout=5), range(2)))
        boxes = [Path(r.stdout.strip()) for r in results]
        self.assertNotEqual(*boxes)
        self.assertTrue(all(p.parent == sentinel.parent and not p.exists() for p in boxes))
        self.assertEqual((sentinel / 'keep').read_text(), 'keep')
        records = self.runs()
        self.assertEqual(len(records), 2, telemetry_errors)
        for record in records:
            self.assertEqual(record['exitCode'], 0)
            self.assertEqual(record['phase'], 'target-authority')
            self.assertGreater(record['durationSeconds'], 0)
            encoded = json.dumps(record)
            self.assertNotIn('secret-token', encoded)
            self.assertNotIn(str(self.repo), encoded)
            self.assertNotIn('stdout', encoded)

    def test_nonzero_result_is_preserved_even_if_telemetry_fails(self):
        self.probe("import sys\nprint('secret-output')\nsys.exit(7)\n")
        original = wsm.write_atomic

        def fail_metadata(target, data):
            if Path(target).suffix == '.json':
                raise OSError('telemetry unavailable')
            return original(target, data)

        with patch.object(wsm, 'write_atomic', side_effect=fail_metadata):
            result = wsm.run_script(self.ws, self.script, [], timeout=5)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), 'secret-output')

    def test_spawn_failure_records_no_error_text_or_arguments(self):
        self.probe('pass')
        with patch.object(wsm, 'make_link'), patch.object(wsm.subprocess, 'Popen', side_effect=OSError('sensitive-path')):
            with self.assertRaisesRegex(OSError, 'sensitive-path'):
                wsm.run_script(self.ws, self.script, ['secret-token'], timeout=5)
        record = self.runs()[0]
        self.assertEqual(record['outcome'], 'error')
        self.assertIsNone(record['exitCode'])
        self.assertNotIn('sensitive-path', json.dumps(record))
        self.assertNotIn('secret-token', json.dumps(record))
        self.assertFalse((self.repo / wsm.SANDBOXES / self.ws.service).exists())

    def test_interruption_cancels_process_without_overriding_interrupt(self):
        self.probe('pass')
        from unittest.mock import Mock
        process = Mock(returncode=-9)
        process.communicate.side_effect = [KeyboardInterrupt(), ('', '')]
        with patch.object(wsm, 'make_link'), patch.object(wsm.subprocess, 'Popen', return_value=process), patch.object(wsm, '_cancel_process_tree') as cancel:
            with self.assertRaises(KeyboardInterrupt):
                wsm.run_script(self.ws, self.script, [], timeout=5)
        cancel.assert_called_once_with(process)
        self.assertEqual(self.runs()[0]['outcome'], 'cancelled')

    def test_timeout_is_bounded_and_cleans_ordinary_child_process(self):
        child_marker = self.repo / 'child-finished'
        child_code = f'import time; from pathlib import Path; time.sleep(3); Path({str(child_marker)!r}).touch()'
        self.probe(f'import subprocess, sys, time\nsubprocess.Popen([sys.executable, "-c", {child_code!r}])\ntime.sleep(30)\n')
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            wsm.run_script(self.ws, self.script, [], timeout=1)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(self.runs()[0]['outcome'], 'timeout')
        self.assertIsNotNone(self.runs()[0]['exitCode'])
        self.assertFalse((self.repo / wsm.SANDBOXES / self.ws.service).exists())
        time.sleep(3)
        self.assertFalse(child_marker.exists())

    def test_invalid_timeout_never_starts_or_records_a_run(self):
        self.probe('raise RuntimeError("must not execute")')
        for timeout in (0, -1, 86401, float('inf'), float('nan'), True, '5'):
            with self.assertRaises(wsm.WorkspaceError):
                wsm.run_script(self.ws, self.script, [], timeout=timeout)
        self.assertEqual(self.runs(), [])

    def test_link_cleanup_preserves_targets_and_broken_symlinks(self):
        box = self.repo / 'box'
        box.mkdir()
        target = self.repo / 'target'
        target.mkdir()
        (target / 'keep').write_text('keep')
        wsm.make_link(box / 'linked', target)
        wsm.drop_sandbox(box)
        self.assertEqual((target / 'keep').read_text(), 'keep')
        if os.name != 'nt':
            box.mkdir()
            (box / 'broken').symlink_to(self.repo / 'missing', target_is_directory=True)
            wsm.drop_sandbox(box)
            self.assertFalse(box.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows junction regression')
    def test_windows_junction_fallback_and_pre312_detection(self):
        box = self.repo / 'junction-box'
        box.mkdir()
        with patch.object(wsm.os, 'symlink', side_effect=OSError('no symlink privilege')):
            wsm.make_link(box / 'linked', self.repo / 'input')
        with patch.object(wsm.os.path, 'isjunction', None, create=True):
            self.assertTrue(wsm._is_junction(box / 'linked'))
            wsm.drop_sandbox(box)
        self.assertTrue((self.repo / 'input').is_dir())


if __name__ == '__main__':
    unittest.main()
