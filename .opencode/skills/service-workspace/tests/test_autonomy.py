"""Fresh-workspace autonomy checks: no real inputs, Maven or generated services."""
from contextlib import redirect_stdout, redirect_stderr
from fnmatch import fnmatchcase
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import os
import sys
import tempfile
import unittest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))
import lifecycle
import workspace_cli

REPO = HERE.parents[3]


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.ws = self.repo / '.factory/services/example'
        self.ws.mkdir(parents=True)
        arch = self.repo / 'archetypes/example/v1'
        arch.mkdir(parents=True)
        self.manifest = arch / 'archetype.yml'
        self.write(self.manifest, {'schemaVersion': 1, 'identity': {'name': 'example', 'version': '1'},
                                 'generation': {'profile': 'batch-shell-jar-spring-xml-log4j-sftp-junit4'}})
        self.write(self.ws / 'service-generation-state.yml', {
            'targetService': 'example', 'archetype': {'path': 'archetypes/example/v1'},
            'inputs': {'contractMode': 'sparx-only', 'openapi': None}})

    def write(self, path, doc):
        path.write_text(yaml.safe_dump(doc), encoding='utf-8')

    def snapshot(self):
        return {str(p.relative_to(self.repo)): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}

    def cli(self, args):
        old = Path.cwd()
        output = StringIO()
        try:
            os.chdir(self.repo)
            with redirect_stdout(output), redirect_stderr(StringIO()), patch.dict(os.environ, {}, clear=True):
                code = workspace_cli.main(args)
        finally:
            os.chdir(old)
        return code, yaml.safe_load(output.getvalue())

    def test_fresh_clone_profile_check_needs_no_gate_contract_or_plan(self):
        before = self.snapshot()
        with patch.object(workspace_cli.gate, 'current_decision', side_effect=AssertionError('must not run gate')):
            code, report = self.cli(['capability-check', 'example'])
        self.assertEqual(code, 0)
        self.assertTrue(report['supported'])
        self.assertFalse(report['gateEvaluated'])
        self.assertFalse(report['askUser'])
        self.assertEqual(before, self.snapshot())

    def test_unknown_profile_is_early_technical_failure_not_question(self):
        doc = yaml.safe_load(self.manifest.read_bytes())
        doc['generation']['profile'] = 'unsupported-profile'
        self.write(self.manifest, doc)
        code, report = self.cli(['capability-check', 'example'])
        self.assertEqual(code, 4)
        self.assertFalse(report['supported'])
        self.assertEqual(report['action'], 'technical-failure')
        self.assertFalse(report['askUser'])

    def test_triage_is_read_only_and_filters_technical_questions(self):
        self.write(self.ws / 'issues.yml', {'issues': [
            {'kind': 'technical-convention', 'key': 'helper-name'},
            {'kind': 'environment-configuration', 'key': 'database-url'},
            {'kind': 'functional-evidence-missing', 'key': 'query'},
            {'kind': 'functional-evidence-missing', 'key': 'query'}]})
        before = self.snapshot()
        code, report = self.cli(['question-triage', 'example', '--input', 'issues.yml'])
        self.assertEqual(code, 0)
        self.assertEqual(len(report['questions']), 1)
        self.assertFalse(report['grantsAuthority'])
        self.assertEqual(before, self.snapshot())
        code, _ = self.cli(['question-triage', 'example', '--input', '../../outside.yml'])
        self.assertEqual(code, 4)

    def test_specialists_allow_routine_scripts_but_not_approval_writers(self):
        commands = {
            'openapi-analyzer': 'parse-openapi/scripts/normalize_openapi.py',
            'sparx-analyzer': 'parse-sparx/scripts/build_authoritative_endpoint_detail.py',
            'spec-analyzer': 'reconcile-service-spec/scripts/reconcile_specs.py',
            'implementation-planner': 'plan-service-implementation/scripts/build_implementation_plan.py'}
        for agent, script in commands.items():
            text = (REPO / '.opencode/agents' / f'{agent}.md').read_text(encoding='utf-8')
            rules = yaml.safe_load(text.split('---', 2)[1])['permissions']

            def effect(command):
                return next((r['effect'] for r in reversed(rules)
                             if r['action'] == 'shell' and fnmatchcase(command, r['resource'])), 'ask')

            with self.subTest(agent=agent):
                self.assertEqual(effect(f'python .opencode/skills/{script} --help'), 'allow')
                self.assertEqual(effect('python review_cli.py review'), 'deny')
                self.assertNotEqual(effect('python -c "print(1)"'), 'allow')
                self.assertNotEqual(effect('mvn test'), 'allow')
