"""BFF without Sparx and without own Swagger: source-only consistency gate and deterministic service-spec derivation. Synthetic repository only."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

SKILLS = Path(__file__).resolve().parents[2]
for name in ('service-workspace', 'reconcile-service-spec', 'plan-service-implementation'):
    sys.path.insert(0, str(SKILLS / name / 'scripts'))
import archetype_contract as ac  # noqa: E402
import bff_gate  # noqa: E402
import bff_source as source  # noqa: E402
import consistency_gate as gate  # noqa: E402
import decision_reviews  # noqa: E402

SERVICE = 'bff-demoApp'
CONTRACT = b'openapi: 3.0.1\ninfo: {title: backend, version: 1}\npaths: {}\n'


def param(name, where, required=True, kind='string'):
    return {'name': name, 'in': where, 'required': required, 'schema': {'type': kind}}


def reply():
    return {'source': {'$ref': '#/components/schemas/ItemReply'}, 'resolved': {'type': 'object', 'properties': {'label': {'type': 'string'}}}}


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve()
        arch = self.repo / 'archetypes/claro-spring-bff/v1.0.0'
        arch.mkdir(parents=True)
        (arch / 'archetype.yml').write_text(yaml.safe_dump({'generation': {'profile': ac.BFF}}), encoding='utf-8')
        contracts = self.repo / 'input/contracts'
        contracts.mkdir(parents=True)
        (contracts / 'dom-items.yml').write_bytes(CONTRACT)
        self.ws = self.repo / '.factory/services' / SERVICE
        (self.ws / 'backend-contracts').mkdir(parents=True)
        (self.ws / 'consistency').mkdir()
        self.dump('service-generation-state.yml', {'schemaVersion': 1, 'targetService': SERVICE, 'archetype': {'path': 'archetypes/claro-spring-bff/v1.0.0'}})
        normalized = {'source': {'path': 'input/contracts/dom-items.yml', 'sha256': hashlib.sha256(CONTRACT).hexdigest()},
                      'operations': [{'path': '/api/v1/items/{itemId}', 'method': 'GET', 'operationId': 'getItem',
                                      'parameters': {'path': [param('itemId', 'path', kind='integer')], 'query': [param('filter', 'query', False)],
                                                     'header': [param('x-request-id', 'header')]},
                                      'responses': {'200': {'content': {'application/json': {'schema': reply()}}}, '404': {'description': 'nf'}}}]}
        self.dump('backend-contracts/dom-items.openapi-spec.yml', normalized)
        self.definition = {'schemaVersion': 1, 'kind': source.KIND, 'service': SERVICE,
                           'basis': {'noOwnSwagger': 'quote one', 'endpoints': 'quote two', 'omission': 'quote three'},
                           'backends': {'items': {'source': 'input/contracts/dom-items.yml', 'normalized': 'backend-contracts/dom-items.openapi-spec.yml'}},
                           'operations': [
                               {'operationId': 'getItem', 'method': 'GET', 'path': '/api/v1/bff-demoApp/items/{itemId}',
                                'binding': {'backend': 'items', 'method': 'GET', 'path': '/api/v1/items/{itemId}',
                                            'integration': {'name': 'items', 'propertyPrefix': 'dom-items'}}},
                               {'operationId': 'listThings', 'method': 'GET', 'path': '/api/v1/bff-demoApp/things',
                                'omitted': {'reason': 'no backend operation', 'authorization': 'basis.omission', 'pathParameters': []}}]}
        self.dump(source.DEFINITION, self.definition)

    def dump(self, name, data):
        path = self.ws / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')

    def review(self, findings=()):
        definition = source.load(self.ws / source.DEFINITION)
        contracts = source.backend_contracts(self.ws, self.repo, definition)
        hashes = bff_gate.review_hashes(self.ws, self.repo / 'archetypes/claro-spring-bff/v1.0.0', gate, definition, contracts)
        self.dump('consistency/supplemental.yml', {'reviewed': True, 'reviewedBy': 'tester', 'reviewedAgainst': hashes, 'findings': list(findings)})

    def decision(self):
        return gate.current_decision(self.ws, self.repo, SERVICE, review_decisions=False)


class BffGateTests(Fixture):
    def test_gate_is_independent_of_sparx_and_never_claims_a_comparison(self):
        self.assertEqual(self.decision()['status'], gate.SEMANTIC_REVIEW_PENDING)
        self.review()
        result = self.decision()
        self.assertEqual(result['status'], gate.AWAITING_AUTHORIZATION)
        self.assertEqual(result['comparison'], bff_gate.COMPARISON)
        self.assertIsNone(result['_registry'])

    def test_resume_grant_is_required_to_clear(self):
        self.review()
        facts = self.decision()
        grant = [{'binding': {'kind': 'resume', 'evaluationHash': facts['evaluationHash']}}]
        with patch.object(decision_reviews, 'current', return_value=grant):
            self.assertEqual(gate.current_decision(self.ws, self.repo, SERVICE)['status'], gate.CLEARED)
        with patch.object(decision_reviews, 'current', return_value=[{'binding': {'kind': 'resume', 'evaluationHash': '0' * 64}}]):
            self.assertEqual(gate.current_decision(self.ws, self.repo, SERVICE)['status'], gate.AWAITING_AUTHORIZATION)

    def test_review_findings_block(self):
        self.review(findings=[{'id': 'x'}])
        self.assertEqual(self.decision()['status'], gate.BLOCKED)

    def test_changed_backend_source_makes_review_and_contract_stale(self):
        self.review()
        (self.repo / 'input/contracts/dom-items.yml').write_bytes(CONTRACT + b'# changed\n')
        result = self.decision()
        self.assertEqual(result['status'], gate.BLOCKED)
        self.assertIn('stale', result['problems'][0])

    def test_changed_definition_makes_review_stale(self):
        self.review()
        self.definition['operations'][1]['omitted']['reason'] = 'another reason'
        self.dump(source.DEFINITION, self.definition)
        self.assertEqual(self.decision()['status'], gate.SEMANTIC_REVIEW_PENDING)

    def test_unverifiable_backend_mapping_blocks(self):
        self.definition['operations'][0]['binding']['path'] = '/api/v1/items/other'
        self.dump(source.DEFINITION, self.definition)
        self.assertEqual(self.decision()['status'], gate.BLOCKED)

    def test_ignored_sparx_or_openapi_artifacts_block(self):
        self.review()
        self.dump('sparx-spec.yml', {'service': {'name': SERVICE}})
        result = self.decision()
        self.assertEqual(result['status'], gate.BLOCKED)
        self.assertIn('Sparx', result['problems'][0])

    def test_service_spec_must_equal_the_derivation(self):
        self.review()
        definition = source.load(self.ws / source.DEFINITION)
        spec = source.derive(definition, source.backend_contracts(self.ws, self.repo, definition), SERVICE)
        self.dump('service-spec.yml', spec)
        self.assertEqual(self.decision()['status'], gate.AWAITING_AUTHORIZATION)
        spec['operations'][0]['path'] = '/tampered'
        self.dump('service-spec.yml', spec)
        self.assertEqual(self.decision()['status'], gate.BLOCKED)

    def test_other_profiles_do_not_use_the_bff_gate(self):
        (self.repo / 'archetypes/claro-spring-bff/v1.0.0/archetype.yml').write_text(yaml.safe_dump({'generation': {'profile': ac.BATCH_SHELL}}), encoding='utf-8')
        self.assertFalse(bff_gate.applies(self.ws, self.repo, gate))


class BffDerivationTests(Fixture):
    def derive(self):
        definition = source.load(self.ws / source.DEFINITION)
        return source.derive(definition, source.backend_contracts(self.ws, self.repo, definition), SERVICE)

    def test_bound_operation_copies_backend_parameters_and_success_response(self):
        spec = self.derive()
        bound, omitted = spec['operations']
        self.assertEqual(list(bound['contract']['responses']), ['200'])
        self.assertEqual([p['name'] for p in bound['contract']['parameters']['header']], ['x-request-id'])
        integration = bound['bffBinding']['integration']
        self.assertTrue(integration['forwardParameters'])
        self.assertEqual(integration['backendPath'], '/api/v1/items/{itemId}')
        self.assertNotIn('bffBinding', omitted)
        self.assertEqual([o['operationId'] for o in spec['omittedBehavior']], ['listThings'])
        self.assertFalse(spec['readiness']['strictImplementationReady'])
        self.assertTrue(spec['readiness']['scaffoldImplementationReady'])

    def test_path_placeholders_must_match_backend(self):
        self.definition['operations'][0]['path'] = '/api/v1/bff-demoApp/items/{other}'
        self.dump(source.DEFINITION, self.definition)
        with self.assertRaises(source.SourceError):
            self.derive()

    def test_omitted_operation_needs_authorization_and_matching_path_parameters(self):
        self.definition['operations'][1]['omitted']['authorization'] = ''
        self.dump(source.DEFINITION, self.definition)
        with self.assertRaises(source.SourceError):
            self.derive()
        self.definition['operations'][1]['omitted']['authorization'] = 'basis.omission'
        self.definition['operations'][1]['path'] += '/{id}'
        self.dump(source.DEFINITION, self.definition)
        with self.assertRaises(source.SourceError):
            self.derive()


if __name__ == '__main__':
    unittest.main()
