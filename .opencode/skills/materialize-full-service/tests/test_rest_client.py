"""Synthetic tests of the REST orchestration backend (rest-client-v1): consolidation patterns, planner, renderers. Temporary repository only; no Maven, no network."""
from pathlib import Path
import copy
import re
import shutil
import sys
import tempfile
import unittest
import yaml

REPO = Path(__file__).resolve().parents[4]
SKILLS = REPO / '.opencode/skills'
for sub in ('reconcile-service-spec', 'plan-service-implementation', 'materialize-full-service', 'service-workspace'):
    sys.path.insert(0, str(SKILLS / sub / 'scripts'))
import consolidate_rest_integration as cons
import rest_client_plan as planner
import rest_client_java as rj
import rest_client_materializer as rcm
import renderers as rd

ARCH = 'archetypes/claro-spring-ms/v1.0.1'
HEADERS = ['x-app-id', 'x-correlation-id', 'x-user-id']


def schema_obj(name, properties, required=None):
    resolved = {'type': 'object', 'properties': properties}
    if required:
        resolved['required'] = required
    return {'source': {'$ref': '#/components/schemas/' + name}, 'resolved': resolved}


def spec_fixture():
    error = schema_obj('ErrorResponse', {k: {'type': 'string'} for k in ('status', 'subType', 'type', 'message', 'detail')} | {'code': {'type': 'integer'}})
    response = schema_obj('GetThingResponse', {'code': {'type': 'integer'}, 'name': {'type': 'string'}, 'since': {'type': 'string', 'format': 'date'}})
    params = {'path': [], 'query': [{'name': 'thingId', 'in': 'query', 'required': True, 'schema': {'type': 'integer'}}],
              'header': [{'name': h, 'in': 'header', 'required': True, 'schema': {'type': 'string'}} for h in HEADERS]}
    activities = [
        {'order': 1, 'name': '1. Validar parametros', 'uuid': '{A}', 'page': 'p1', 'pageSha256': 'h1', 'role': 'validation',
         'rules': [{'id': 'required-fields', 'kind': 'required-fields-informed', 'errorCode': 'IDF101', 'evidence': 'e1'}]},
        {'order': 2, 'name': '2. Obtener catalogo', 'uuid': '{B}', 'page': 'p2', 'pageSha256': 'h2', 'role': 'remote-call',
         'integration': {'name': 'catalogs', 'type': 'OpenApi-Rest', 'httpMethod': 'GET', 'connection': '/api/v1/kinds'},
         'properties': {'propRefreshCache': {'value': '3600000', 'unit': 'en milisegundos'}},
         'request': {'headers': {'mode': 'forward-all-request-headers', 'mappings': []}, 'query': [], 'body': {'rootLabel': None, 'fields': []}},
         'response': {'root': None, 'fields': [{'path': 'data[].id', 'type': 'integer'}, {'path': 'data[].name', 'type': 'string'}]},
         'outcomes': {'rules': [{'kind': 'http-status-equals', 'status': 200, 'then': 'continue', 'evidence': 'e2'}, {'kind': 'otherwise', 'then': 'error', 'errorCode': 'IDF383', 'evidence': 'e3'}],
                      'unavailable': {'then': 'error', 'errorFamily': 'IDT', 'evidence': 'e4'}}},
        {'order': 3, 'name': '3. Obtener cosa', 'uuid': '{C}', 'page': 'p3', 'pageSha256': 'h3', 'role': 'remote-call',
         'integration': {'name': 'things-backend', 'type': 'OpenApi-Rest', 'httpMethod': 'GET', 'connection': 'http://ip:port/things/v1/obtenerCosa'},
         'properties': {'propAccept': {'value': 'application/json'}},
         'request': {'headers': {'mode': 'mapped', 'mappings': [{'kind': 'request-header', 'from': 'x-correlation-id', 'to': 'msgid'},
                                                                 {'kind': 'timestamp', 'to': 'timestamp', 'source': 'SYSDATE', 'transformation': "Aplicar formato yyyy-MM-dd'T'HH:mm:ssZ (ISO8601)"},
                                                                 {'kind': 'property', 'to': 'accept', 'property': 'propAccept'}]},
                     'query': [{'kind': 'field', 'from': 'thingId', 'to': 'idCosa', 'transformation': ''}], 'body': {'rootLabel': None, 'fields': []}},
         'response': {'root': 'obtenerCosaResponse', 'fields': [{'path': 'responseAudit.codigoRespuesta', 'type': 'string'}, {'path': 'responseAudit.mensajeRespuesta', 'type': 'string'},
                                                                  {'path': 'responseAudit.idTransaccion', 'type': 'string'}, {'path': 'responseData.items[].id', 'type': 'string'}]},
         'outcomes': {'rules': [{'kind': 'response-code-zero-and-list-not-empty', 'then': 'success', 'evidence': 'e5'},
                                {'kind': 'response-code-zero-and-list-empty', 'then': 'error', 'errorCode': 'IDF385', 'evidence': 'e6'},
                                {'kind': 'otherwise', 'then': 'error', 'errorCode': 'IDF383', 'evidence': 'e7'}],
                      'unavailable': {'then': 'error', 'errorFamily': 'IDT', 'evidence': 'e8'}}}]
    # the list rule of the planner names listaCuotas; keep the fixture on that name
    activities[2]['response']['fields'][3]['path'] = 'responseData.listaCuotas[].id'
    catalog = {'GetThing': {'IDF101': {'status': 'BAD_REQUEST', 'httpStatus': 400, 'type': 'MissingParameters', 'message': 'THINGS_SERVICE_ERROR', 'detail': 'Invalid [FIELD_NAME].'},
                            'IDF383': {'status': 'BAD_REQUEST', 'httpStatus': 400, 'type': 'RetrievalException', 'message': 'THINGS_SERVICE_ERROR', 'detail': 'Failed. [OUTPUT_DETAIL]'},
                            'IDF385': {'status': 'NOT_FOUND', 'httpStatus': 404, 'type': 'NotFoundException', 'message': 'THINGS_SERVICE_ERROR', 'detail': 'Nothing found.'},
                            'IDT1': {'status': 'GATEWAY_TIMEOUT', 'httpStatus': 504, 'type': 'TimeoutException', 'message': 'THINGS_SERVICE_ERROR', 'detail': 'Timeout in [SERVICE_NAME] [ERROR_DETAIL]'},
                            'IDT2': {'status': 'SERVICE_UNAVAILABLE', 'httpStatus': 503, 'type': 'ServiceUnavailable', 'message': 'THINGS_SERVICE_ERROR', 'detail': 'Down [SERVICE_NAME] [ERROR_DETAIL]'},
                            'IDT3': {'status': 'INTERNAL_SERVER_ERROR', 'httpStatus': 500, 'type': 'InternalError', 'message': 'THINGS_SERVICE_ERROR', 'detail': 'Internal [ERROR_DETAIL]'}}}
    op = {'operationId': 'GetThing', 'method': 'GET', 'path': '/api/v1/things',
          'contract': {'summary': 'Get a thing', 'description': 'Gets a thing.', 'parameters': params, 'requestBody': None,
                       'responses': {'200': {'content': {'application/json': {'schema': response}}}, '400': {'content': {'application/json': {'schema': error}}},
                                     '404': {'content': {'application/json': {'schema': error}}}, '500': {'content': {'application/json': {'schema': error}}}}},
          'behavior': {'kind': 'remote-rest-orchestration', 'endEvents': ['Fin'], 'activities': activities}}
    return {'specKind': 'rest-orchestration-v1', 'service': {'name': 'things-service'}, 'operations': [op], 'errorCatalog': catalog, 'inactive': {'operations': []},
            'unresolved': {'conflicts': [], 'ambiguities': [], 'missingEvidence': []}, 'persistence': {'status': 'none-in-sparx'},
            'unspecifiedMappings': [{'operationId': 'GetThing', 'kind': 'backend-response-to-contract-response'}],
            'readiness': {'contractComplete': True, 'restOrchestrationGenerationReady': True}}


def planning_input():
    return {'version': 1, 'mode': 'full', 'variant': 'rest-client-v1',
            'target': {'service': 'things-service', 'base_package': 'com.claro.things.service.support', 'group_id': 'com.claro.things.service.support', 'project_version': '1.0.0-SNAPSHOT',
                       'output_directory': 'output/things-service', 'archetype': ARCH},
            'technical': {'application_log_level': 'INFO', 'corporate_logger_level': 'INFO', 'http_log_level': 'INFO', 'root_log_level': 'INFO', 'log_time_zone': 'UTC', 'jwt_roles_claim': 'roles',
                          'header_roles': {'transactionId': 'x-correlation-id', 'userId': 'x-user-id', 'applicationName': 'x-app-id'}}}


class ConsolidationPatternTests(unittest.TestCase):
    def test_outcome_patterns_are_closed(self):
        lines = [{'text': 'Si "HTTP STATUS = 200", continuar con la siguiente actividad', 'evidence': 'e', 'index': 0},
                 {'text': 'Caso contrario, Finalizar transacción con IDF383', 'evidence': 'e', 'index': 1},
                 {'text': 'Si el insumo esta NO DISPONIBLE, genera TIME-OUT u ocurre ERROR INTERNO/NO CONTROLADO, Finalizar proceso con IDT', 'evidence': 'e', 'index': 2},
                 {'text': 'Un comportamiento inventado', 'evidence': 'e', 'index': 3}]
        outcome = cons.parse_outcomes(lines, 'act')
        self.assertEqual(['http-status-equals', 'otherwise'], [r['kind'] for r in outcome['rules']])
        self.assertEqual('IDF383', outcome['rules'][1]['errorCode'])
        self.assertIsNotNone(outcome['unavailable'])
        self.assertEqual(1, len(outcome['unmatched']), 'an uncovered statement must be reported, never guessed')

    def test_input_sections_and_unknown_section(self):
        rows = {'rows': [{'evidenceId': 'e0', 'input': '', 'origin': '', 'destination': 'Headers'},
                         {'evidenceId': 'e1', 'input': 'x-request-id', 'origin': 'Header Request', 'destination': 'idTransaccion', 'transformation': ''},
                         {'evidenceId': 'e2', 'input': 'SYSDATE', 'origin': '', 'destination': 'timestamp', 'transformation': "Aplicar formato yyyy-MM-dd'T'HH:mm:ssZ"},
                         {'evidenceId': 'e3', 'input': '', 'origin': '', 'destination': 'Query Param'},
                         {'evidenceId': 'e4', 'input': 'clientCode', 'origin': 'Query Param', 'destination': 'idCliente', 'transformation': ''}]}
        parsed = cons.parse_input(rows)
        self.assertEqual('mapped', parsed['headers']['mode'])
        self.assertEqual(['request-header', 'timestamp'], [m['kind'] for m in parsed['headers']['mappings']])
        self.assertEqual('idCliente', parsed['query'][0]['to'])
        with self.assertRaises(cons.ConsolidationError):
            cons.parse_input({'rows': [{'evidenceId': 'x', 'input': '', 'origin': '', 'destination': 'Cookies'}]})

    def test_output_root_is_only_a_response_label(self):
        with_root = cons.parse_output({'rows': [{'evidenceId': 'a', 'output': 'obtenerCuotasResponse', 'type': ''}, {'evidenceId': 'b', 'output': 'responseAudit.codigoRespuesta', 'type': 'string'}]})
        without = cons.parse_output({'rows': [{'evidenceId': 'a', 'output': 'code', 'type': ''}, {'evidenceId': 'b', 'output': 'data[].id', 'type': 'integer'}]})
        self.assertEqual('obtenerCuotasResponse', with_root['root'])
        self.assertIsNone(without['root'])
        self.assertEqual(2, len(without['fields']))

    def test_error_catalog_keeps_operation_texts_but_rejects_status_conflicts(self):
        def op(oid, message, status='BAD_REQUEST'):
            return {'operationId': oid, 'responses': {'400': {'content': {'application/json': {'example': {'status': status, 'code': 400, 'subType': 'IDF1', 'type': 'T', 'message': message, 'detail': 'd'}}}}}}
        catalog = cons.error_catalog({'operations': [op('A', 'M1'), op('B', 'M2')]})
        self.assertEqual('M1', catalog['A']['IDF1']['message'])
        self.assertEqual('M2', catalog['B']['IDF1']['message'])
        with self.assertRaises(cons.ConsolidationError):
            cons.error_catalog({'operations': [op('A', 'M1'), op('B', 'M1', status='NOT_FOUND')]})


class RestClientPlanAndRenderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(REPO / ARCH, self.root / ARCH, ignore=shutil.ignore_patterns('__pycache__'))
        self.ws = self.root / 'ws'
        self.ws.mkdir()
        self.write(self.ws / 'service-spec.yml', spec_fixture())
        self.write(self.ws / 'full-planning-input.yml', planning_input())

    @staticmethod
    def write(path, data):
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')

    def artifacts(self):
        return planner.artifacts(self.root, yaml, Path('ws/full-planning-input.yml'))

    def test_plan_is_deterministic_and_has_no_persistence(self):
        plan, params = self.artifacts()
        again, _ = self.artifacts()
        self.assertEqual(plan, again)
        self.assertEqual('none', plan['technicalProfile']['persistence'])
        self.assertFalse(plan['technicalProfile']['jpa'])
        kinds = {f['componentType'] for f in plan['files']['generate']}
        self.assertFalse({k for k in kinds if 'jpa' in k or 'repository' in k or 'entity' in k})
        self.assertEqual(['GetThing'], [o['operationId'] for o in plan['omittedBehavior']])
        self.assertTrue(plan['qualityGates']['checkstyle']['mandatory'])
        self.assertEqual('spring-data-jpa-activity-logger', plan['plan']['profile'])

    def test_activity_constants_come_from_the_authoritative_activities(self):
        plan, _ = self.artifacts()
        constants = {c['constant'] for c in plan['activityLogging']['activityConstants']}
        self.assertEqual({'ACT1_VALIDAR_PARAMETROS', 'ACT2_OBTENER_CATALOGO', 'ACT3_OBTENER_COSA'}, constants)

    def test_backend_types_follow_sparx_and_contract_fields(self):
        plan, _ = self.artifacts()
        dtos = {d['name']: {f['name']: f['javaType'] for f in d['fields']} for d in plan['backendDtos']}
        self.assertEqual({'codigoRespuesta': 'String', 'mensajeRespuesta': 'String', 'idTransaccion': 'String'}, dtos['ResponseAudit'])
        self.assertEqual('List<ObtenerCosaResponseDataListaCuotasItem>', dtos['ObtenerCosaResponseData']['listaCuotas'])
        query = plan['operations'][0]['activities'][2]['query'][0]
        self.assertEqual({'to': 'idCosa', 'from': 'thingId', 'sourceType': 'Integer', 'backendType': 'String', 'conversion': 'valueOf'}, {k: query[k] for k in ('to', 'from', 'sourceType', 'backendType', 'conversion')})

    def test_unresolved_items_or_wrong_kind_stop_planning(self):
        spec = spec_fixture()
        spec['unresolved']['ambiguities'] = [{'id': 'x'}]
        self.write(self.ws / 'service-spec.yml', spec)
        with self.assertRaises(planner.base.PlanError):
            self.artifacts()
        spec = spec_fixture()
        spec['specKind'] = 'other'
        self.write(self.ws / 'service-spec.yml', spec)
        with self.assertRaises(planner.base.PlanError):
            self.artifacts()

    def test_renderers_produce_complete_style_conforming_java(self):
        plan, _ = self.artifacts()
        g = rj.Gen(plan)
        texts = {}
        for entry in plan['files']['generate']:
            texts[entry['path']] = rcm.render_entry(g, plan, entry, self.root)
        self.assertEqual(len(plan['files']['generate']), len(texts))
        for path, text in texts.items():
            self.assertTrue(text.startswith('package '), path)
            self.assertNotIn('\r', text, path)
            self.assertFalse(re.search(r'__[A-Z_]+__', text), path)
            imports = re.findall(r'^import ([\w.]+);$', text, re.M)
            self.assertEqual(imports, sorted(set(imports)), f'{path}: imports must be sorted and unique')
            code = rj.scrub(text.split('\n\n', 1)[1] if text.count('\n\n') else text)
            for name in imports:
                simple = name.rsplit('.', 1)[-1]
                self.assertRegex(code.replace(f'import {name};', ''), rf'\b{simple}\b', f'{path}: unused import {name}')
            self.assertFalse(re.search(r'\b(JpaRepository|@Entity|EntityManager|DataSource)\b', text), f'{path}: persistence must not be generated')
        mapper = next(t for p, t in texts.items() if p.endswith('ResponseMapper.java'))
        self.assertIn('UnsupportedOperationException', mapper)
        service = next(t for p, t in texts.items() if p.endswith('ServiceImpl.java'))
        self.assertIn('ActivityLogger.inicioActividad', service)
        self.assertIn('ServiceError.IDT1', service)
        client = next(t for p, t in texts.items() if p.endswith('ThingsBackendClient.java'))
        self.assertIn('ZonedDateTime.now(clock)', client, 'the timestamp uses the injectable clock, never SYSDATE')

    def test_rendering_is_deterministic(self):
        plan, _ = self.artifacts()
        first = {e['path']: rcm.render_entry(rj.Gen(plan), plan, e, self.root) for e in plan['files']['generate']}
        second = {e['path']: rcm.render_entry(rj.Gen(copy.deepcopy(plan)), copy.deepcopy(plan), e, self.root) for e in plan['files']['generate']}
        self.assertEqual(first, second)

    def test_count_lines_has_balanced_blocks_and_uniform_indentation(self):
        plan, _ = self.artifacts()
        g = rj.Gen(plan)
        lines = g.count_lines('response', 'ObtenerCosaResponse', ['responseData', 'listaCuotas[]'], 0, '        ')
        self.assertEqual(sum(l.count('{') for l in lines), sum(l.count('}') for l in lines))
        for line in lines:
            self.assertEqual(0, (len(line) - len(line.lstrip())) % 4)


if __name__ == '__main__':
    unittest.main()
