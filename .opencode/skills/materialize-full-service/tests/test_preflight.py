"""Feasibility against actual synthetic backend fixtures; no production writes."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth as fx
import full_materializer as fm
import feasibility_preflight as pf
import test_batch_shell as batch_fixture
import test_jdbc_independence as jdbc_fixture


class PreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = fx.make_repo(Path(tmp.name))
        self.service = 'inventory-service'
        fx.ready_service(self.repo, self.service)
        self.ws = self.repo / '.factory/services' / self.service

    def change(self, mutate):
        path = self.ws / 'implementation-plan.yml'
        plan = yaml.safe_load(path.read_bytes())
        mutate(plan)
        path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding='utf-8')

    def test_http_supported_and_repeatable(self):
        before = fx.tree(self.repo / 'output')
        a = pf.evaluate(self.repo, self.service)
        self.assertTrue(a['feasible'], a)
        self.assertEqual(a, pf.evaluate(self.repo, self.service))
        self.assertEqual(before, fx.tree(self.repo / 'output'))

    def test_unsupported_files_are_all_reported(self):
        def mutate(p):
            for i in range(2):
                p['files']['generate'].append({'path': f'unknown{i}.java', 'componentType': 'unknown', 'action': 'create'})
            p.pop('generationOrdering', None)
        self.change(mutate)
        report = pf.evaluate(self.repo, self.service)
        self.assertFalse(report['feasible'])
        for i in range(2):
            self.assertTrue(any(r['id'] == f'unknown{i}.java' and r['status'] == 'unsupported' for r in report['requirements']))

    def test_multiple_unsupported_operations(self):
        def mutate(p):
            for i in range(2):
                op = copy.deepcopy(p['api']['operations'][0])
                op.update(operationId=f'bad{i}', actionKind='teleport')
                p['api']['operations'].append(op)
        self.change(mutate)
        result = pf.evaluate(self.repo, self.service)
        self.assertFalse(result['feasible'])
        for i in range(2):
            self.assertTrue(any(r['id'] == f'bad{i}' and r['status'] != 'supported' for r in result['requirements']))

    def test_unknown_profile(self):
        self.change(lambda p: p['plan'].update(profile='unknown-profile'))
        self.assertFalse(pf.evaluate(self.repo, self.service)['feasible'])

    def test_incomplete_contract(self):
        self.change(lambda p: p.pop('api'))
        self.assertFalse(pf.evaluate(self.repo, self.service)['feasible'])

    def test_invalid_yaml_and_duplicate_keys_fail_closed(self):
        path = self.ws / 'implementation-plan.yml'
        for payload in ('[broken', 'plan: {}\nplan: {}\n'):
            path.write_text(payload, encoding='utf-8')
            self.assertFalse(pf.evaluate(self.repo, self.service)['feasible'])

    def test_cli_emits_versioned_yaml_without_writing_workspace(self):
        import os
        import io
        import workspace_cli
        from contextlib import redirect_stdout
        before = fx.tree(self.ws)
        cwd = Path.cwd()
        try:
            os.chdir(self.repo)
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = workspace_cli.main(['preflight', self.service])
            self.assertEqual(code, 0)
            self.assertEqual(yaml.safe_load(stream.getvalue())['schemaVersion'], 1)
        finally:
            os.chdir(cwd)
        self.assertEqual(before, fx.tree(self.ws))

    def test_selected_unknown_profile_is_unsupported(self):
        path = self.repo / fx.ARCHETYPE / 'archetype.yml'
        arch = yaml.safe_load(path.read_bytes())
        arch['generation'] = {'profile': 'unknown'}
        path.write_text(yaml.safe_dump(arch), encoding='utf-8')
        result = pf.evaluate(self.repo, self.service)
        self.assertEqual(result['status'], 'unsupported')

    def test_incomplete_batch_scopes_block_public_backends(self):
        fixture = batch_fixture.BatchShellTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.plan()
        path = fixture.ws / 'implementation-plan.yml'
        original = yaml.safe_load(path.read_bytes())
        for scope in ('ports-flow', 'structure-only'):
            plan = copy.deepcopy(original)
            plan['batch']['scope'] = scope
            path.write_text(yaml.safe_dump(plan), encoding='utf-8')
            report = pf.evaluate(fixture.repo, fixture.service)
            self.assertTrue(any(r['id'] == 'batch-flow' and r['status'] == 'unsupported' for r in report['requirements']))
            with self.assertRaises(fm.MaterializationError):
                batch_fixture.bm.materialize(fixture.repo, fixture.service)
            self.assertFalse((fixture.repo / 'output').exists())

    def test_stale_fingerprint(self):
        before = pf.evaluate(self.repo, self.service)
        path = self.ws / 'service-spec.yml'
        path.write_bytes(path.read_bytes() + b'\n# changed\n')
        after = pf.evaluate(self.repo, self.service)
        self.assertFalse(after['feasible'])
        self.assertNotEqual(before['runId'], after['runId'])

    def test_materialization_cannot_skip_preflight_or_write_partial_output(self):
        self.change(lambda p: p.update(incompleteOperations=['mandatory-op']))
        before = fx.tree(self.repo / 'output')
        with self.assertRaises(fm.MaterializationError):
            fm.materialize(self.repo, self.service)
        self.assertEqual(before, fx.tree(self.repo / 'output'))

    def test_supported_only_is_not_an_override(self):
        with self.assertRaises(fm.MaterializationError):
            fm.materialize(self.repo, self.service, supported_only=True)
        self.assertFalse((self.repo / 'output' / self.service).exists())

    def test_real_materialize_cli_fails_controlled_before_output(self):
        import subprocess
        self.change(lambda p: p.update(incompleteOperations=['mandatory-op']))
        command = [sys.executable, '-B', str(Path(fm.__file__)), self.service]
        done = subprocess.run(command, cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertNotIn('Traceback', done.stderr)
        self.assertIn('mandatory-op', done.stderr)
        self.assertFalse((self.repo / 'output' / self.service).exists())

    def test_previous_feasible_result_cannot_override_gate(self):
        self.assertTrue(pf.evaluate(self.repo, self.service)['feasible'])
        with patch.object(fm.gate, 'check_cleared', side_effect=fm.gate.GateError('BLOCKED', 'fixture')):
            with self.assertRaises(fm.gate.GateError):
                fm.materialize(self.repo, self.service)

    def test_batch_supported(self):
        fixture = batch_fixture.BatchShellTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.plan()
        report = pf.evaluate(fixture.repo, fixture.service)
        self.assertTrue(report['feasible'], report)

    def test_jdbc_supported(self):
        fixture = jdbc_fixture.JdbcIndependenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ws, _, _ = fixture.fixture()
        with patch.object(fm.gate, 'check_cleared'):
            fixture.plan(ws)
            (ws / 'service-generation-state.yml').write_text(yaml.safe_dump({
                'targetService': ws.name, 'archetype': {'path': fixture.arch}}))
            report = pf.evaluate(fixture.root, ws.name)
        self.assertTrue(report['feasible'], report)


if __name__ == '__main__':
    unittest.main()
