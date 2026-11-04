"""Stage 2A cannot replace any real backend preflight. Synthetic fixtures only."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth as fx
import test_batch_shell as bf
import test_jdbc_independence as jf
import full_materializer as fm
import feasibility_preflight as pf
import decision_requests as dr


def request(repo, service, evidence='service-spec.yml'):
    return dr.create(repo, service, {'schemaVersion': 1, 'purpose': 'authorize-operation', 'decisions': [{
        'key': 'resume-question', 'classification': 'explicit-authorization',
        'problem': 'Ask whether generation may resume; this proposal grants nothing.',
        'findingFingerprints': [], 'evidence': [{'path': evidence, 'pointer': '/', 'summary': 'Synthetic source.'}],
        'alternatives': [{'id': 'defer', 'description': 'Defer to future human review.',
                          'effects': ['Does not authorize generation.']}]}]})


class DecisionRequestIntegrationTests(unittest.TestCase):
    def test_jpa_preflight_unchanged_by_request(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = fx.make_repo(Path(tmp.name))
        fx.ready_service(repo, 'inventory-service')
        before = pf.evaluate(repo, 'inventory-service')
        self.assertTrue(before['feasible'])
        request(repo, 'inventory-service')
        self.assertEqual(before, pf.evaluate(repo, 'inventory-service'))

    def test_proposal_cannot_bypass_blocked_gate_or_unknown_requirement(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = fx.make_repo(Path(tmp.name))
        service = 'inventory-service'
        fx.ready_service(repo, service)
        request(repo, service)
        ws = repo / '.factory/services' / service
        plan = yaml.safe_load((ws / 'implementation-plan.yml').read_bytes())
        plan['incompleteOperations'] = ['mandatory-question']
        (ws / 'implementation-plan.yml').write_text(yaml.safe_dump(plan))
        before = fx.tree(repo / 'output')
        with self.assertRaises(fm.MaterializationError):
            fm.materialize(repo, service)
        with patch.object(fm.gate, 'check_cleared', side_effect=fm.gate.GateError('BLOCKED', 'fixture')):
            with self.assertRaises(fm.gate.GateError):
                fm.materialize(repo, service)
        self.assertEqual(before, fx.tree(repo / 'output'))

    def test_batch_preflight_unchanged_and_not_http(self):
        fixture = bf.BatchShellTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.plan()
        before = pf.evaluate(fixture.repo, fixture.service)
        self.assertTrue(before['feasible'])
        proposal = request(fixture.repo, fixture.service)
        self.assertEqual(proposal['context']['audit']['comparison'], 'not-applicable-non-http-batch')
        self.assertEqual(before, pf.evaluate(fixture.repo, fixture.service))

    def test_jdbc_preflight_unchanged(self):
        fixture = jf.JdbcIndependenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ws, _, _ = fixture.fixture()
        # Existing JDBC fixture intentionally mocks the audit only; actual
        # JDBC planner, renderer and feasibility validators still execute.
        with patch.object(fm.gate, 'check_cleared'):
            fixture.plan(ws)
            (ws / 'service-generation-state.yml').write_text(yaml.safe_dump({
                'targetService': ws.name, 'archetype': {'path': fixture.arch}}))
            before = pf.evaluate(fixture.root, ws.name)
            self.assertTrue(before['feasible'])
            request(fixture.root, ws.name, 'service-spec.yml')
            self.assertEqual(before, pf.evaluate(fixture.root, ws.name))


if __name__ == '__main__':
    unittest.main()
