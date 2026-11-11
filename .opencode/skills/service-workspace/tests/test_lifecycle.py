from pathlib import Path
import sys
import tempfile
import unittest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import lifecycle as lc  # noqa: E402


class FakeGate:
    CLEARED = 'CLEARED'

    def __init__(self, status):
        self.status = status

    def current_decision(self, ws, repo, service):
        return {'status': self.status}


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding='utf-8')


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)

    def archetype(self, **identity):
        base = {'name': 'x', 'version': '1.0.0', 'approved': True, 'frozen': False, 'generationEnabled': True}
        base.update(identity)
        dump(self.repo / 'archetypes/x/v1/archetype.yml',
             {'schemaVersion': 1, 'identity': base, 'generation': {'profile': 'batch-shell-jar-spring-xml-log4j-sftp-junit4'}})
        return 'archetypes/x/v1'

    def test_frozen_and_enabled_are_independent_and_runtime_is_never_assumed(self):
        life = lc.archetype_lifecycle(self.repo, self.archetype(frozen=False, generationEnabled=True))
        self.assertEqual((life['frozen'], life['generationEnabled']), ('no', 'yes'))
        self.assertEqual(life['runtimeVerified'], 'not-verified')
        self.assertEqual(life['serviceGenerationAuthorizedForConcreteTargets'], 'unknown')

    def test_unknown_profile_has_no_backend_and_missing_flags_stay_unknown(self):
        dump(self.repo / 'archetypes/y/v1/archetype.yml', {'schemaVersion': 1, 'identity': {'name': 'y', 'version': '1'}, 'generation': {'profile': 'other'}})
        life = lc.archetype_lifecycle(self.repo, 'archetypes/y/v1')
        self.assertEqual((life['approved'], life['backendImplemented']), ('unknown', 'no'))

    def service(self, status='CLEARED', report=None, warnings=None, evidence=None):
        ws = self.repo / '.factory/services/s'
        dump(ws / 'service-generation-state.yml', {'targetService': 's', 'archetype': {'path': self.archetype()}})
        dump(ws / 'service-spec.yml', {'service': {'name': 's'}, 'warnings': warnings or []})
        dump(ws / 'implementation-plan.yml', {})
        if report:
            dump(ws / 'materialization-report.yml', {'status': report})
            dump(self.repo / 'output/s/.generation-manifest.yml', {})
        if evidence:
            dump(ws / 'validation-evidence.yml', evidence)
        return lc.service_lifecycle(self.repo, 's', FakeGate(status))

    def test_materialized_is_not_compiled_tested_or_running(self):
        result = self.service(report='complete')
        self.assertEqual((result['materialized'], result['functionallyComplete']), ('yes', 'yes'))
        for key in ('maven', 'compilation', 'tests', 'jacoco', 'runtime'):
            self.assertEqual(result[key], 'not-verified', key)

    def test_declared_limitations_or_incomplete_operations_are_partial(self):
        self.assertEqual(self.service(report='complete', warnings=['mail not generated'])['functionallyComplete'], 'partial')
        self.assertEqual(self.service(report='complete-with-incomplete-operations')['functionallyComplete'], 'partial')

    def test_only_recorded_evidence_marks_a_tool_and_a_blocked_gate_is_not_cleared(self):
        result = self.service(status='BLOCKED_BY_INCONSISTENCIES', evidence={'compilation': 'passed', 'tests': 'failed'})
        self.assertEqual((result['gateCleared'], result['compilation'], result['tests'], result['maven']), ('no', 'yes', 'no', 'not-verified'))


class QuestionPolicyTests(unittest.TestCase):
    def test_only_real_conflicts_parameters_deviations_and_gate_release_ask(self):
        asking = {k for k in lc.POLICY if lc.decide(k)['askUser']}
        self.assertEqual(asking, {'source-conflict', 'required-parameter-missing', 'intentional-deviation', 'gate-release', 'functional-evidence-missing'})
        for k in ('reference-evidence-clear', 'technology-absent-in-reference', 'decision-already-approved', 'request-covers-phase', 'unsupported-backend'):
            self.assertFalse(lc.decide(k)['askUser'], k)
        self.assertEqual(lc.decide('unsupported-backend')['action'], 'technical-failure')

    def test_unknown_kind_is_an_error(self):
        with self.assertRaises(ValueError):
            lc.decide('whatever')

    def test_technical_judgment_does_not_become_business_questions(self):
        result = lc.triage([{'kind': kind, 'key': kind} for kind in
                            ('technical-convention', 'environment-configuration', 'analysis-incomplete', 'source-evidence-clear')])
        self.assertEqual(result['questions'], [])
        self.assertFalse(result['grantsAuthority'])

    def test_extensions_need_evidence_compatibility_and_backend_support(self):
        issue = {'kind': 'supported-service-extension', 'key': 'adapter'}
        self.assertEqual(lc.triage([issue])['actions'][0]['action'], 'analyze-target-evidence')
        issue['evidence'] = ['.factory/service-spec.yml#/integrations/0']
        self.assertEqual(lc.triage([issue])['actions'][0]['action'], 'technical-failure')
        issue.update(backendSupported=True, compatibleWithArchetype=True)
        self.assertEqual(lc.triage([issue])['actions'][0]['action'], 'plan-extension')
        self.assertEqual(lc.triage([issue])['questions'], [])

    def test_missing_business_evidence_remains_a_question(self):
        issue = {'kind': 'functional-evidence-missing', 'key': 'response-status'}
        self.assertEqual(len(lc.triage([issue, issue])['questions']), 1)

    def test_missing_parameters_are_one_grouped_question_without_duplicates(self):
        qs = [{'kind': 'required-parameter-missing', 'key': 'B'}, {'kind': 'required-parameter-missing', 'key': 'A'},
              {'kind': 'required-parameter-missing', 'key': 'A'}, {'kind': 'unsupported-backend', 'key': 'z'},
              {'kind': 'source-conflict', 'key': 'c1'}, {'kind': 'source-conflict', 'key': 'c1'}]
        self.assertEqual(lc.group_questions(qs), [{'kind': 'source-conflict', 'key': 'c1'},
                                                    {'kind': 'required-parameter-missing', 'keys': ['A', 'B']}])

    def test_existing_human_decision_is_found_for_the_same_scope_only(self):
        decisions = [{'decisionId': 'D1', 'humanReviewed': True, 'scope': 'svc-a'},
                     {'decisionId': 'D2', 'humanReviewed': True, 'scope': 'svc-b', 'approvedBy': 'agent'},
                     {'decisionId': 'D3', 'humanReviewed': False, 'scope': 'svc-c'}]
        self.assertIsNone(lc.find_decision(decisions, 'svc-a'))  # raw flags are historical evidence only
        for other in ('svc-b', 'svc-c', 'svc-z'):
            self.assertIsNone(lc.find_decision(decisions, other))


if __name__ == '__main__':
    unittest.main()
