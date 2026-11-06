"""Synthetic BFF services only; temporary repository, no reference, Maven or remote access."""
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / '.opencode/skills/plan-service-implementation/scripts'))
sys.path.insert(0, str(REPO / '.opencode/skills/materialize-full-service/scripts'))
sys.path.insert(0, str(REPO / '.opencode/skills/service-workspace/scripts'))
import bff_plan as planner
import bff_materializer as renderer

ARCH = 'archetypes/claro-spring-bff/v1.0.0'


def obj(name, properties, required=None):
    resolved = {'type': 'object', 'properties': properties}
    if required:
        resolved['required'] = required
    return {'source': {'$ref': '#/components/schemas/' + name}, 'resolved': resolved}


class BffBackendTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(REPO / ARCH, self.root / ARCH, ignore=shutil.ignore_patterns('__pycache__'))
        path = self.root / ARCH / 'archetype.yml'
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        data['identity']['approved'] = True
        data['identity']['generationEnabled'] = True
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')

    def fixture(self, bound=True):
        service = 'dom-sample-bff'
        ws = self.root / '.factory/services' / service
        ws.mkdir(parents=True, exist_ok=True)
        reply = obj('SampleReply', {'label': {'type': 'string'}, 'count': {'type': 'integer'}})
        request = obj('SampleRequest', {'key': {'type': 'string'}})
        read = {'operationId': 'readSample', 'method': 'GET', 'path': '/samples/{sampleId}',
                'contract': {'parameters': {'path': [{'name': 'sampleId', 'required': True, 'schema': {'type': 'string'}}],
                                            'query': [], 'header': []},
                             'responses': {'200': {'content': {'application/json': {'schema': reply}}}}}}
        create = {'operationId': 'createSample', 'method': 'POST', 'path': '/samples',
                  'contract': {'parameters': {'path': [], 'query': [], 'header': []},
                               'requestBody': {'required': True, 'content': {'application/json': {'schema': request}}},
                               'responses': {'201': {'content': {'application/json': {'schema': reply}}}}}}
        if bound:
            read['behavior'] = {'actions': [{'implementationComplete': True}]}
            read['bffBinding'] = {'version': 1, 'evidence': ['sparx:Sample#read'],
                                  'integration': {'name': 'sampleBackend', 'propertyPrefix': 'sample.backend', 'method': 'GET',
                                                  'forwardRequestBody': False, 'responseMapping': 'identity'}}
        spec = {'service': {'name': service}, 'operations': [read, create],
                'readiness': {'contractComplete': True, 'functionalCodeGenerationReady': True, 'strictImplementationReady': True},
                'unresolved': {'conflicts': [], 'ambiguities': [], 'missingEvidence': []}}
        cfg = {'target': {'service': service, 'archetype': ARCH, 'output_directory': 'output/' + service,
                          'base_package': 'com.acme.sample', 'group_id': 'com.acme', 'project_version': '1.0.0'},
               'template_parameters': {'VAULT_NAME': 'vault-sample', 'OWNER_LABEL': 'team-sample', 'PART_OF_LABEL': 'suite-sample',
                                       'APPLICATION_CLASS': 'SampleBffApplication'}}
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        (ws / 'full-planning-input.yml').write_text(yaml.safe_dump(cfg, sort_keys=False), encoding='utf-8')
        return ws, spec, cfg

    def plan(self, ws):
        planner.write_plan(self.root, yaml, (ws / 'full-planning-input.yml').relative_to(self.root))
        return yaml.safe_load((ws / 'implementation-plan.yml').read_text(encoding='utf-8'))

    def materialize(self, ws, **kwargs):
        import full_materializer as fm
        (ws / 'service-generation-state.yml').write_text(yaml.safe_dump(
            {'targetService': ws.name, 'archetype': {'path': ARCH}}))
        with patch.object(fm.gate, 'check_cleared'):
            return fm.materialize(self.root, ws.name, **kwargs)

    def test_plan_separates_bound_and_omitted_behavior(self):
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        self.assertEqual(plan['plan']['profile'], planner.PROFILE)
        self.assertEqual(plan['incompleteOperations'], [])
        self.assertEqual([o['operationId'] for o in plan['omittedBehavior']], ['createSample'])
        bound = {o['operationId']: o['binding'] for o in plan['operations']}
        self.assertIsNotNone(bound['readSample'])
        self.assertIsNone(bound['createSample'])

    def test_unapproved_archetype_is_refused(self):
        ws, _, _ = self.fixture()
        path = self.root / ARCH / 'archetype.yml'
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        data['identity']['generationEnabled'] = False
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
        with self.assertRaises(Exception):
            self.plan(ws)

    def test_unsupported_schema_constraint_is_rejected(self):
        ws, spec, cfg = self.fixture()
        reply = spec['operations'][0]['contract']['responses']['200']['content']['application/json']['schema']
        reply['resolved']['properties']['label']['maxLength'] = 5
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        with self.assertRaises(Exception):
            self.plan(ws)

    def test_invalid_binding_is_rejected(self):
        ws, spec, cfg = self.fixture()
        spec['operations'][0]['bffBinding']['integration']['responseMapping'] = 'custom'
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        with self.assertRaises(Exception):
            self.plan(ws)

    def test_materialization_generates_contract_and_reports_omissions(self):
        ws, _, _ = self.fixture()
        self.plan(ws)
        report = self.materialize(ws)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual([o['operationId'] for o in report['omittedBehavior']], ['createSample'])
        self.assertEqual(report['validation']['maven'], 'not-run')
        self.assertEqual(report['validation']['checkstyle'], 'unverified')
        self.assertTrue((ws / 'assumptions-register.yml').is_file())
        out = self.root / 'output/dom-sample-bff/src/main/java/com/acme/sample'
        service_impl = next(out.glob('service/impl/*ServiceImpl.java')).read_text(encoding='utf-8')
        self.assertIn('Behavior omitted', service_impl)
        self.assertIn('import com.acme.sample.service.SampleBffService;', service_impl)
        controller_impl = next(out.glob('controller/impl/*ControllerImpl.java')).read_text(encoding='utf-8')
        self.assertIn('import com.acme.sample.controller.SampleBffController;', controller_impl)
        self.assertIn('import com.acme.sample.service.SampleBffService;', controller_impl)
        self.assertTrue(any(out.rglob('*Controller.java')))
        self.assertTrue(any(out.rglob('SampleReply.java')))
        self.assertTrue(any((self.root / 'output/dom-sample-bff/src/test').rglob('*Test.java')))
        self.assertTrue((self.root / 'output/dom-sample-bff/pom.xml').is_file())

    def test_materialization_is_idempotent(self):
        ws, _, _ = self.fixture()
        self.plan(ws)
        self.materialize(ws)
        again = self.materialize(ws)
        self.assertEqual(again['status'], 'complete')
        self.assertEqual(again['written'], [] if isinstance(again['written'], list) else 0)

    def test_tampered_plan_is_recomputed(self):
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        plan['omittedBehavior'] = []
        (ws / 'implementation-plan.yml').write_text(yaml.safe_dump(plan, sort_keys=False), encoding='utf-8')
        with self.assertRaises(Exception):
            self.materialize(ws)

    def test_no_application_properties_are_created_from_plan(self):
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        paths = [f['path'] for f in plan['files']['generate']]
        self.assertFalse([p for p in paths if '/application' in p and p.endswith('.properties')
                          and 'configuration' not in p])


    def forwarding_fixture(self, backend_path='/api/v1/items/{itemId}'):
        ws, spec, cfg = self.fixture()
        reply = obj('ItemReply', {'label': {'type': 'string'}})
        params = {'path': [{'name': 'itemId', 'required': True, 'schema': {'type': 'integer', 'format': 'int64'}}],
                  'query': [{'name': 'filter', 'required': False, 'schema': {'type': 'string'}}],
                  'header': [{'name': 'x-request-id', 'required': True, 'schema': {'type': 'string'}},
                             {'name': 'x-optional', 'required': False, 'schema': {'type': 'string'}}]}
        op = {'operationId': 'getItem', 'method': 'GET', 'path': '/items/{itemId}',
              'contract': {'parameters': params, 'responses': {'200': {'content': {'application/json': {'schema': reply}}}}},
              'behavior': {'actions': [{'implementationComplete': True}]},
              'bffBinding': {'version': 1, 'evidence': ['backend:items#get'],
                             'integration': {'name': 'itemsBackend', 'propertyPrefix': 'items.backend', 'method': 'GET', 'forwardRequestBody': False,
                                             'forwardParameters': True, 'backendPath': backend_path, 'responseMapping': 'identity'}}}
        spec['operations'] = [op]
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        return ws, spec

    def test_forwarded_parameters_generate_client_and_client_test(self):
        ws, _ = self.forwarding_fixture()
        plan = self.plan(ws)
        self.assertEqual(plan['templateParameters']['ARTIFACT_ID'], 'dom-sample-bff')
        self.assertIn('src/test/java/com/acme/sample/client/itemsbackend/ItemsBackendClientTest.java', [f['path'] for f in plan['files']['generate']])
        self.materialize(ws)
        out = self.root / 'output/dom-sample-bff/src/main/java/com/acme/sample/client/itemsbackend/ItemsBackendClient.java'
        text = out.read_text(encoding='utf-8')
        self.assertIn('variables.put("itemId", itemId);', text)
        self.assertIn('builder.queryParam("filter", "{filter}");', text)
        self.assertIn('headers.add("x-request-id", xRequestId);', text)
        self.assertIn('public ItemReply getItem(Long itemId, String filter, String xRequestId, String xOptional)', text)
        props = (ws / 'required-properties.yml').read_text(encoding='utf-8')
        self.assertIn('/api/v1/items/{itemId}', props)
        service = (self.root / 'output/dom-sample-bff/src/main/java/com/acme/sample/service/impl/SampleBffServiceImpl.java').read_text(encoding='utf-8')
        self.assertIn('itemsBackendClient.getItem(itemId, filter, xRequestId, xOptional)', service)

    def test_backend_path_must_match_path_parameters(self):
        ws, _ = self.forwarding_fixture('/api/v1/items/{other}')
        with self.assertRaises(Exception):
            self.plan(ws)

    def test_parameter_forwarding_integration_serves_one_operation(self):
        ws, spec = self.forwarding_fixture()
        again = copy.deepcopy(spec['operations'][0])
        again.update(operationId='getItemAgain', path='/items/{itemId}/again')
        spec['operations'].append(again)
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        with self.assertRaises(Exception):
            self.plan(ws)

    def test_required_is_accepted_in_responses(self):
        ws, spec, cfg = self.fixture()
        reply = spec['operations'][0]['contract']['responses']['200']['content']['application/json']['schema']
        reply['resolved']['required'] = ['label']
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        plan = self.plan(ws)
        self.assertFalse([m for m in plan['models'] if m.get('validated')])

    def body_fixture(self, mutate=None):
        ws, spec, cfg = self.fixture()
        nested = obj('Extra', {'name': {'type': 'string'}})
        nested['resolved']['additionalProperties'] = True
        request = obj('ResolveRequest', {'note': {'type': 'string', 'maxLength': 255}, 'userId': {'type': 'string'}, 'extra': nested},
                      ['userId', 'extra'])
        reply = obj('ResolveReply', {'ok': {'type': 'boolean'}})
        reply['resolved']['required'] = ['ok']
        contract = {'parameters': {'path': [{'name': 'id', 'required': True, 'schema': {'type': 'integer', 'format': 'int64'}}], 'query': [], 'header': []},
                    'requestBody': {'required': True, 'content': {'application/json': {'schema': request}}},
                    'responses': {'200': {'content': {'application/json': {'schema': reply}}}}}
        op = {'operationId': 'resolveCase', 'method': 'POST', 'path': '/cases/{id}/resolution', 'contract': contract,
              'behavior': {'actions': [{'implementationComplete': True}]},
              'bffBinding': {'version': 1, 'evidence': ['backend:cases#resolve'],
                             'integration': {'name': 'caseResolution', 'propertyPrefix': 'cases.backend', 'method': 'POST', 'forwardRequestBody': True,
                                             'forwardParameters': True, 'backendPath': '/api/v1/cases/{id}/resolution', 'responseMapping': 'identity'}}}
        spec['operations'] = [op]
        if mutate:
            mutate(request['resolved'])
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        return ws

    def test_request_body_constraints_generate_validated_dtos_and_forwarding(self):
        ws = self.body_fixture()
        plan = self.plan(ws)
        self.assertEqual(plan['omittedBehavior'], [])
        self.assertIn('src/test/java/com/acme/sample/dto/request/RequestContractTest.java', [f['path'] for f in plan['files']['generate']])
        self.materialize(ws)
        base = self.root / 'output/dom-sample-bff/src'
        dto = (base / 'main/java/com/acme/sample/dto/request/ResolveRequest.java').read_text(encoding='utf-8')
        self.assertIn('@NotNull\n    private String userId;', dto)
        self.assertIn('private static final int NOTE_MAX_LENGTH = 255;', dto)
        self.assertIn('@Size(max = NOTE_MAX_LENGTH)\n    private String note;', dto)
        self.assertIn('@NotNull\n    @Valid\n    private Extra extra;', dto)
        self.assertIn('@JsonInclude(JsonInclude.Include.NON_NULL)', dto)
        extra = next((base / 'main/java').rglob('Extra.java')).read_text(encoding='utf-8')
        self.assertIn('@JsonAnySetter', extra)
        self.assertIn('Map<String, Object> additionalProperties = new HashMap<>();', extra)
        client = next((base / 'main/java').rglob('CaseResolutionClient.java')).read_text(encoding='utf-8')
        self.assertIn('.bodyValue(body)', client)
        self.assertIn('resolveCase(Long id, ResolveRequest body)', client)
        controller = next((base / 'main/java').rglob('SampleBffController.java')).read_text(encoding='utf-8')
        self.assertIn('@Valid @RequestBody ResolveRequest body', controller)
        contract_test = (base / 'test/java/com/acme/sample/dto/request/RequestContractTest.java').read_text(encoding='utf-8')
        self.assertIn('Assertions.assertEquals(2, violations.size());', contract_test)
        self.assertIn('"x".repeat(RESOLVE_REQUEST_NOTE_MAX_LENGTH + 1)', contract_test)
        client_test = next((base / 'test/java').rglob('CaseResolutionClientTest.java')).read_text(encoding='utf-8')
        self.assertIn('ClientRequest sent = captured.get();', client_test)

    def test_other_request_constraints_remain_unsupported(self):
        for mutate in (lambda r: r['properties']['note'].update(pattern='^a$'), lambda r: r['properties']['note'].update(minLength=1, enum=['a']),
                       lambda r: r['properties']['extra']['resolved'].update(additionalProperties=False),
                       lambda r: r['properties']['userId'].update(maxLength=True),
                       lambda r: r['properties']['extra']['resolved'].update(additionalProperties={'type': 'string'}),
                       lambda r: r.update(required=['ghost'])):
            with self.subTest():
                ws = self.body_fixture(mutate)
                with self.assertRaises(Exception):
                    self.plan(ws)

    def test_artifact_id_is_kebab_case_of_mixed_case_service(self):
        ws, spec, cfg = self.fixture()
        self.assertEqual(planner.base.technical_identifier('bff-customerBillApp'), 'bff-customer-bill-app')

    def test_artifact_id_is_kebab_case_of_mixed_case_service(self):
        ws, spec, cfg = self.fixture()
        self.assertEqual(planner.base.technical_identifier('bff-customerBillApp'), 'bff-customer-bill-app')


if __name__ == '__main__':
    unittest.main()
