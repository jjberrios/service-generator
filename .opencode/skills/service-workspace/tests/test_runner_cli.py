from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workspace_cli as cli


class RunnerCliTests(unittest.TestCase):
    def test_timeout_option_is_separate_from_script_arguments(self):
        result = subprocess.CompletedProcess([], 7, 'child output', 'child error')
        with patch.object(cli.wsm, 'run_script', return_value=result) as run, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = cli.main(['run', '--runner-timeout', '120', 'synthetic', 'bounded.py', '--target', 'selected'])
        self.assertEqual(7, code)
        self.assertEqual({'timeout': 120.0}, run.call_args.kwargs)
        self.assertEqual(['--target', 'selected'], run.call_args.args[2])

    def test_timeout_diagnostic_does_not_echo_command_or_secret_arguments(self):
        errors = io.StringIO()
        with patch.object(cli.wsm, 'run_script', side_effect=subprocess.TimeoutExpired(['secret-argument'], 1)), \
                redirect_stderr(errors):
            code = cli.main(['run', 'synthetic', 'bounded.py'])
        self.assertEqual(124, code)
        self.assertNotIn('secret-argument', errors.getvalue())
        self.assertIn('timed out', errors.getvalue())

    def test_legacy_invocation_keeps_default_timeout(self):
        result = subprocess.CompletedProcess([], 0, '', '')
        with patch.object(cli.wsm, 'run_script', return_value=result) as run:
            self.assertEqual(0, cli.main(['run', 'synthetic', 'bounded.py']))
        self.assertEqual(900, run.call_args.kwargs['timeout'])


if __name__ == '__main__':
    unittest.main()
