"""Fast runner checks with synthetic modules only; no service suite execution."""

import ast
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'run_tests.py'
SPEC = importlib.util.spec_from_file_location('repository_test_runner', SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='runner-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.skills = self.root / '.opencode/skills'
        self.enterContext(patch.object(runner, 'ROOT', self.root))
        self.enterContext(patch.object(runner, 'SKILLS', self.skills))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def module(self, skill, name, source=''):
        path = self.skills / skill / 'tests' / ('test_' + name + '.py')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
        return path

    def test_inventory_and_selection_are_bounded(self):
        first = self.module('one', 'first')
        second = self.module('two', 'second')
        (first.parent / 'helper.py').write_text('', encoding='utf-8')
        known = runner.inventory()
        self.assertEqual(len(known), 2)
        self.assertEqual(runner.select(known, skills=['one']), [first])
        self.assertEqual(runner.select(known, modules=[second.relative_to(self.root).as_posix()]), [second])
        self.assertEqual(runner.select(known, all_modules=True), [first, second])
        for name in ('../outside.py', str(first), '.opencode/skills/one/tests/../../outside.py', 'test_first.py;echo unsafe'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.select(known, modules=[name])
        with self.assertRaises(ValueError):
            runner.select(known, skills=['missing'])

    def test_list_does_not_import_or_start_processes(self):
        self.module('one', 'unsafe', 'raise AssertionError("must not import")')
        with patch.object(runner.subprocess, 'Popen') as start:
            self.assertEqual(runner.main(['--list']), 0)
            start.assert_not_called()
        self.assertIn('dry enumeration', self.output.getvalue())

    def test_no_implicit_execution_and_invalid_limits(self):
        self.module('one', 'first')
        for args in ([], ['--all', '--jobs', '0'], ['--all', '--timeout', '-1'],
                     ['--all', '--timeout', 'nan'], ['--all', '--timeout', 'inf'],
                     ['--module', '../outside.py']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                runner.main(args)
            self.assertEqual(error.exception.code, 2)

    def test_class_selection_is_source_validated_without_import(self):
        self.module('one', 'first', 'raise RuntimeError("no import")\nclass Segment:\n def test_a(self): pass\n')
        self.assertEqual(runner.main(['--skill', 'one', '--class', 'Segment', '--list']), 0)
        self.assertIn(': Segment', self.output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            runner.main(['--skill', 'one', '--class', 'Segment.test_a', '--list'])
        path = next(iter(runner.inventory().values()))
        cmd = runner.command(path, ['Segment'])
        self.assertEqual(cmd[:4], [sys.executable, '-m', 'unittest', '-v'])
        self.assertEqual(cmd[-1], 'test_first.Segment')

    def test_isolated_parallel_modules_and_skip_summary(self):
        source = ('import unittest\nclass Tests(unittest.TestCase):\n'
                  ' def test_ok(self): self.assertTrue(True)\n'
                  ' @unittest.skip("synthetic prerequisite")\n'
                  ' def test_skip(self): pass\n')
        first = self.module('one', 'same', source)
        second = self.module('two', 'same', source.replace('test_ok', 'test_other'))
        results = runner.run_modules([first, second], 2, 10)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.returncode == 0 and result.skips == 1 for result in results))
        self.assertIn('test_other', next(result.output for result in results if '/two/' in result.module))
        self.assertNotIn('test_other', next(result.output for result in results if '/one/' in result.module))

    def test_failure_sets_nonzero_exit_and_summary(self):
        self.module('one', 'failure', 'import unittest\nclass Tests(unittest.TestCase):\n def test_bad(self): self.fail("synthetic")\n')
        self.assertEqual(runner.main(['--all', '--timeout', '10']), 1)
        self.assertIn('failed=1', self.output.getvalue())
        self.assertIn('returncode=1', self.output.getvalue())

    def test_timeout_stops_process(self):
        path = self.module('one', 'slow', 'import time\ntime.sleep(60)\n')
        results = runner.run_modules([path], 1, 0.2)
        self.assertTrue(results[0].timed_out)
        self.assertNotEqual(results[0].returncode, 0)

    def test_windows_tree_termination_uses_fixed_argv(self):
        process = Mock(pid=1234)
        process.poll.return_value = 0
        with patch.object(runner.os, 'name', 'nt'), patch.object(runner.subprocess, 'run') as run:
            runner.stop_tree(process)
        self.assertEqual(run.call_args.args[0], ['taskkill', '/PID', '1234', '/T', '/F'])
        self.assertNotIn('shell', run.call_args.kwargs)
        process.wait.assert_called_once_with(timeout=15)

    def test_posix_tree_termination_targets_group(self):
        process = Mock(pid=1234)
        process.poll.return_value = 0
        with patch.object(runner.os, 'name', 'posix'), \
                patch.object(runner.signal, 'SIGKILL', 9, create=True), \
                patch.object(runner.os, 'killpg', create=True) as kill:
            runner.stop_tree(process)
        kill.assert_called_once_with(1234, 9)
        process.wait.assert_called_once_with(timeout=15)

    def test_windows_missing_tree_command_still_terminates_parent(self):
        process = Mock(pid=1234)
        process.poll.return_value = None
        with patch.object(runner.os, 'name', 'nt'), \
                patch.object(runner.subprocess, 'run', side_effect=OSError('unavailable')):
            runner.stop_tree(process)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=15)

    def test_interruption_cleans_active_process(self):
        path = self.module('one', 'first')
        process = Mock(pid=1234)
        process.poll.side_effect = KeyboardInterrupt
        with patch.object(runner.subprocess, 'Popen', return_value=process), \
                patch.object(runner, 'stop_tree') as stop:
            with self.assertRaises(KeyboardInterrupt):
                runner.run_modules([path], 1, 10)
        stop.assert_called_once_with(process)


class BatchInventoryTests(unittest.TestCase):
    def test_37_unique_scenarios_without_inherited_tests(self):
        path = SCRIPT.parents[1] / '.opencode/skills/materialize-full-service/tests/test_batch_shell.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        fixture = classes.pop('BatchShellFixture')
        self.assertFalse(any(isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
                             for node in fixture.body))
        names = []
        for cls in classes.values():
            self.assertEqual([ast.unparse(base) for base in cls.bases],
                             ['BatchShellFixture', 'unittest.TestCase'])
            names.extend(node.name for node in cls.body
                         if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'))
        self.assertEqual(len(names), 37)
        self.assertEqual(len(set(names)), 37)


if __name__ == '__main__':
    unittest.main()
