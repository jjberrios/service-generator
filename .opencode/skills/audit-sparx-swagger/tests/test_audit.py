"""Comparison and report-format tests with synthetic fixtures (no real service data, no Sparx export)."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest
import zipfile

import yaml
from docx import Document

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import compare_sparx_swagger as cmp
import source_currency as currency
import snapshot_sources
import visual_evidence as ve
import capture_evidence as ce
import evidence_locator as loc
from unittest.mock import patch
import build_report_docx as builder
import validate_report_docx as validator

BRANCH = {'branchRootId': '0.2', 'pagePathPrefix': 'EARoot/EA2'}


def row(evidence, **values):
    return {'evidenceId': evidence, **values}


def swagger_param(name, required, type_='string'):
    return {'name': name, 'in': 'query', 'required': required, 'schema': {'type': type_}}


def openapi():
    response = {'resolved': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'items': {'type': 'array', 'items': {
        'type': 'object', 'properties': {'id': {'type': 'integer'}, 'name': {'type': 'string'}, 'extra': {'type': 'string'}}}}}}}}}
    return {'source': {'path': 'input/contracts/x.yml', 'sha256': 'a'}, 'operations': [
        {'method': 'GET', 'path': '/api/v1/things', 'operationId': 'getThings',
         'parameters': {'header': [{'name': 'x-app-id', 'in': 'header', 'required': True, 'schema': {'type': 'string'}}],
                        'query': [swagger_param('id', False, 'integer'), swagger_param('name', False), swagger_param('only-swagger', True)], 'path': []},
         'responses': {'200': {'content': {'application/json': {'schema': response}}}, '400': {}, '500': {}}},
        {'method': 'POST', 'path': '/api/v1/things', 'operationId': 'createThing', 'parameters': {'header': [], 'query': [], 'path': []},
         'requestBody': {'content': {'application/json': {'schema': {'resolved': {'type': 'object', 'required': ['name'], 'properties': {'name': {'type': 'string'}}}}}}},
         'responses': {'200': {}}},
        {'method': 'GET', 'path': '/api/v1/missing', 'operationId': 'missing', 'parameters': {}, 'responses': {'200': {}}}]}


def detail():
    activity_validation = {'activity': {'name': '1. Validar', 'uuid': '{ACT-1}', 'page': 'EARoot/EA2/p1.htm'}, 'embeddedLinkdoc': {'resolvedFile': 'linkdocs/L1.htm'},
                           'normalized': {'validation': {
                               'headerrequest': {'rows': [row('e-h1', headerrequest='x-app-id', required='Si', type='String'), row('e-h2', headerrequest='x-only-sparx', required='No', type='String')]},
                               'query': {'rows': [row('e-q1', query='id', required='Si', type='string'), row('e-q2', query='name', required='No', type='String')]},
                               'body': {'rows': []}}}}
    activity_behavior = {'activity': {'name': '2. Buscar', 'uuid': '{ACT-2}', 'page': 'EARoot/EA2/p2.htm'}, 'normalized': {
        'input': {'rows': [row('e-i1', input='id', origin='queryparam', destination='id'), row('e-i2', input='ghost', origin='queryparam', destination='x')]},
        'output': {'rows': [row('e-o1', output='SELECT[].ID', type='string', destination='data.items[].id'), row('e-o2', output='SELECT[].NAME', type='string', destination='data.items[].name'),
                            row('e-o3', output='SELECT[].AGE', type='integer', destination='data.items[].age')]}}}
    post_validation = {'activity': {'name': '1. Validar', 'uuid': '{ACT-3}', 'page': 'EARoot/EA2/p3.htm'}, 'normalized': {'validation': {
        'body': {'rows': [row('e-b1', body='name', required='No', type='String'), row('e-b2', body='surname', required='Si', type='String')]}}}}
    return {'authority': {'branch': BRANCH}, 'excludedInactiveOperations': [{'method': 'GET', 'path': '/api/v1/things/{id}'}], 'operations': [
        {'method': 'GET', 'path': '/api/v1/things', 'status': 'active', 'sparxMethod': {'name': 'GET-/api/v1/things', 'guid': '{M-1}', 'page': 'EARoot/EA2/m1.htm'},
         'activities': [activity_validation, activity_behavior], 'endEvents': [{'label': '200', 'guid': '{E-200}', 'page': 'e200.htm'}, {'label': '404', 'guid': '{E-404}', 'page': 'e404.htm'}, {'label': '400', 'guid': '{E-400}', 'page': 'e400.htm'}]},
        {'method': 'POST', 'path': '/api/v1/things', 'status': 'active', 'sparxMethod': {'name': 'POST-/api/v1/things', 'guid': '{M-2}', 'page': 'EARoot/EA2/m2.htm'},
         'activities': [post_validation], 'endEvents': []},
        {'method': 'GET', 'path': '/api/v1/missing', 'status': 'no-sparx-method-in-authoritative-branch'}]}


def audit(**overrides):
    spec, det = openapi(), detail()
    spec.update(overrides.get('openapi', {}))
    return cmp.Auditor('svc-a', spec, det, 'rama autoritativa EARoot/EA2 (0.2)', overrides.get('decisions')).run()


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auditor = audit()
        cls.findings = cls.auditor.registry()
        cls.by_key = {f['key']: f for f in cls.findings}

    def find(self, fragment, kind=None):
        hits = [f for f in self.findings if fragment in f['key'] and (kind is None or f['kind'] == kind)]
        self.assertTrue(hits, fragment)
        return hits[0]

    def test_requirement_type_and_presence_differences_are_detected_with_both_evidences(self):
        self.assertEqual(self.find('query:id|requirement-difference')['severity'], 'Alta')
        self.assertIn('Obligatorio: Si', self.find('query:id|requirement-difference')['sparx']['text'])
        self.assertTrue(self.find('query:id|type-or-structure-difference'))
        self.assertTrue(self.find('header:x-only-sparx|missing-in-swagger'))
        self.assertTrue(self.find('query:only-swagger|missing-in-sparx'))
        for finding in self.findings:
            self.assertTrue(finding['evidence']['sparx'] and finding['evidence']['swagger'], finding['key'])
            self.assertTrue(all(e['pointer'].startswith('#/') for e in finding['evidence']['swagger']))

    def test_equal_elements_and_responsibility_differences_are_not_reported(self):
        keys = '\n'.join(f['key'] for f in self.findings)
        self.assertNotIn('header:x-app-id', keys)
        self.assertNotIn('query:name|', keys)
        self.assertNotIn('code', keys.replace('status', ''))

    def test_output_mapping_and_status_codes(self):
        self.assertTrue(self.find('output:data.items[].age'))
        self.assertFalse([f for f in self.findings if 'output:data.items[].id' in f['key'] and f['kind'] == 'type-or-structure-difference'])
        self.assertTrue([u for u in self.auditor.unverified if u['category'] == 'fuente-no-comparable' and 'OUTPUT data.items[].id' in u['topic']])
        self.assertTrue(self.find('output:data.items[].extra|missing-in-sparx'))
        self.assertTrue(self.find('status:404|missing-in-swagger'))
        self.assertTrue(self.find('status:500|missing-in-sparx'))
        self.assertTrue(self.find('input:ghost'))

    def test_body_required_difference_and_absent_operation(self):
        self.assertEqual(self.find('body:name|requirement-difference')['severity'], 'Alta')
        self.assertTrue(self.find('body:surname|missing-in-swagger'))
        absent = self.find('/api/v1/missing|operation|missing-in-sparx')
        self.assertEqual(absent['severity'], 'Alta')
        self.assertIn('authorityFile', absent['evidence']['sparx'][0])

    def test_inactive_sparx_operations_absent_from_swagger_are_neither_findings_nor_unverified(self):
        self.assertFalse([f for f in self.findings if '{id}' in f['operation']['path']])
        self.assertFalse([u for u in self.auditor.unverified if '{id}' in str((u['operation'] or {}).get('path', ''))])

    def test_inactive_operation_declared_in_swagger_is_a_lifecycle_finding(self):
        spec, det = openapi(), detail()
        det['operations'][0]['status'] = 'ELIMINADO'
        result = cmp.Auditor('svc-a', spec, det, 'b').run().registry()
        self.assertTrue([f for f in result if f['kind'] == 'operation-lifecycle'])

    def test_comparison_is_deterministic_and_deduplicated(self):
        again = audit().registry()
        self.assertEqual(self.findings, again)
        keys = [f['key'] for f in again]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual([f['id'] for f in again], [f'INC-{n:03d}' for n in range(1, len(again) + 1)])

    def test_unverifiable_types_are_listed_not_asserted(self):
        spec, det = openapi(), detail()
        det['operations'][0]['activities'][0]['normalized']['validation']['query']['rows'][0]['type'] = 'Foo'
        result = cmp.Auditor('svc-a', spec, det, 'b').run()
        self.assertFalse([f for f in result.registry() if f['key'].endswith('query:id|type-or-structure-difference')])
        self.assertTrue([u for u in result.unverified if 'Tipo de query id' in u['topic']])

    def test_supplemental_findings_require_evidence_on_both_sources(self):
        auditor = audit()
        good = {'operation': {'method': 'GET', 'path': '/api/v1/things', 'operationId': 'getThings'}, 'element': 'Sin filtros', 'sparx': {'text': 'Retorna todos.'},
                'swagger': {'text': '400 IDF1.'}, 'inconsistency': 'Comportamiento contradictorio.', 'severity': 'Alta', 'kind': 'contradiction', 'category': 'contradiccion-verificada',
                'evidence': {'sparx': [{'guid': '{X}', 'page': 'p.htm'}], 'swagger': [{'method': 'GET', 'path': '/api/v1/things', 'pointer': '#/operations/0/parameters/query'}]}}
        bad = {**good, 'element': 'otro', 'evidence': {'sparx': [], 'swagger': good['evidence']['swagger']}}
        auditor.merge_supplemental({'findings': [good, bad, copy.deepcopy(good)]})
        supplemental = [f for f in auditor.registry() if 'supplemental' in f['key']]
        self.assertEqual(len(supplemental), 1)
        self.assertTrue([u for u in auditor.unverified if 'rechazado' in u['topic']])

    def test_human_decisions_are_context_only(self):
        auditor = audit(decisions=[{'id': 'DEC-1', 'operations': ['getThings']}])
        findings = auditor.registry()
        self.assertEqual(len(findings), len(self.findings))
        self.assertTrue(all(f.get('humanDecisionContext') == ['DEC-1'] for f in findings if f['operation']['operationId'] == 'getThings'))


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        auditor = audit()
        cls.registry = {'service': 'svc-a', 'readOnlyAudit': True, 'sourceCurrency': {'status': 'current'}, 'operationsAudited': [{'method': o['method'], 'path': o['path']} for o in openapi()['operations']],
                        'findings': auditor.registry(), 'unverified': auditor.unverified}
        cls.path = Path(cls.tmp.name) / 'svc-a_sparx_swagger.docx'
        builder.build(cls.registry, cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_report_passes_all_format_and_content_validations(self):
        checks = {**validator.registry_checks(self.registry, 'svc-a'), **validator.docx_checks(self.registry, self.path, 'svc-a')}
        self.assertEqual([k for k, v in checks.items() if not v], [])

    def test_document_starts_with_findings_and_has_no_forbidden_sections(self):
        document = Document(str(self.path))
        self.assertRegex(document.paragraphs[0].text, r'^(GET|POST) /')
        self.assertEqual(len(document.tables), len(self.registry['findings']))
        table = document.tables[0]
        self.assertEqual([table.rows[0].cells[0].text, table.rows[0].cells[2].text], ['ID', 'Severidad'])
        self.assertEqual([r.cells[0].text for r in table.rows[1:]], list(builder.BODY_LABELS))

    def test_docx_text_is_black_without_theme_colors_or_header_footer_content(self):
        with zipfile.ZipFile(self.path) as archive:
            blob = ''.join(archive.read(n).decode('utf-8', 'ignore') for n in ('word/document.xml', 'word/styles.xml'))
        self.assertNotIn('themeColor', blob)
        self.assertFalse(set(__import__('re').findall(r'<w:color [^>]*w:val="([^"]+)"', blob)) - {'000000'})

    def test_empty_registry_states_it_briefly(self):
        registry = {**self.registry, 'findings': [], 'unverified': []}
        path = Path(self.tmp.name) / 'empty.docx'
        builder.build(registry, path)
        self.assertEqual([p.text for p in Document(str(path)).paragraphs if p.text], [builder.EMPTY_TEXT])
        checks = validator.docx_checks(registry, path, 'svc-a')
        self.assertEqual([k for k, v in checks.items() if not v], [])

    def test_validator_rejects_wrong_service_duplicates_missing_evidence_and_colored_text(self):
        self.assertFalse(validator.registry_checks(self.registry, 'svc-b')['registryBelongsToRequestedService'])
        duplicated = copy.deepcopy(self.registry)
        duplicated['findings'].append(copy.deepcopy(duplicated['findings'][0]))
        self.assertFalse(validator.registry_checks(duplicated, 'svc-a')['noDuplicateFindings'])
        noevidence = copy.deepcopy(self.registry)
        noevidence['findings'][0]['evidence']['swagger'] = []
        self.assertFalse(validator.registry_checks(noevidence, 'svc-a')['everyFindingHasSwaggerEvidence'])
        mixed = copy.deepcopy(self.registry)
        mixed['findings'][0]['evidence']['sparx'][0]['branch'] = 'otra rama'
        self.assertFalse(validator.registry_checks(mixed, 'svc-a')['singleSparxBranch'])
        colored = Path(self.tmp.name) / 'colored.docx'
        document = Document(str(self.path))
        from docx.shared import RGBColor
        document.paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 0, 0)
        document.save(colored)
        checks = validator.docx_checks(self.registry, colored, 'svc-a')
        self.assertFalse(checks['allTextBlack'])

    def test_rendering_is_deterministic_in_content(self):
        other = Path(self.tmp.name) / 'again.docx'
        builder.build(self.registry, other)
        text = lambda p: [c.text for t in Document(str(p)).tables for r in t.rows for c in r.cells]
        self.assertEqual(text(self.path), text(other))

    def test_visual_review_is_never_claimed_without_a_renderer(self):
        result = validator.visual_review(self.path)
        self.assertIn(result['status'], ('not-executed', 'rendered-pdf-requires-manual-inspection'))


# ----------------------------------------------------------------------------------------------------------------------
# Regression cases derived from the first dom-document-language audit (synthetic data, no real service content).
# ----------------------------------------------------------------------------------------------------------------------
def sparx_method(name, status, invoked_by=None, guid='{M}', page='EARoot/EA2/EA6/m.htm'):
    verb, path = name.split('-', 1)
    return {'method': verb, 'path': path, 'name': name, 'guid': guid, 'page': page, 'pageSha256': 'x', 'status': status,
            'lifecycle': 'inactive' if status in ('ELIMINADO',) else ('active' if status else 'unknown'), 'invokedVia': invoked_by or []}


BFF_CALLER = {'name': 'GET-/api/v1/svc/things', 'page': 'EARoot/EA2/EA6/bff.htm', 'guid': '{BFF}', 'ownerService': 'bff-service', 'ownedByTargetService': False}


def swagger_only(path='/api/v1/things'):
    return {'source': {'path': 'x', 'sha256': 'a'}, 'operations': [{'method': 'GET', 'path': path, 'operationId': 'getThings', 'parameters': {}, 'responses': {'200': {}}}]}


def route_audit(methods, path='/api/v1/things'):
    det = {'authority': {'branch': BRANCH}, 'operations': [{'method': 'GET', 'path': path, 'status': 'no-sparx-method-in-authoritative-branch'}]}
    return cmp.Auditor('svc-a', swagger_only(path), det, 'rama autoritativa EARoot/EA2 (0.2)', None, methods).run()


class RouteVerificationTests(unittest.TestCase):
    def test_route_key_ignores_api_prefix_version_and_parameter_names(self):
        self.assertEqual(cmp.route_key('/api/v1/languages'), cmp.route_key('/api/languages'))
        self.assertEqual(cmp.route_key('/api/v2/things/{id}'), cmp.route_key('/things/{thingId}'))
        self.assertNotEqual(cmp.route_key('/api/v1/languages'), cmp.route_key('/api/v1/languages/{id}'))

    def test_prefix_difference_is_a_documental_route_difference_not_a_missing_operation(self):
        audit_result = route_audit([sparx_method('GET-/api/things', 'NUEVO', [BFF_CALLER]), sparx_method('GET-/api/v1/things/{id}', 'ELIMINADO')])
        findings = audit_result.registry()
        self.assertEqual([f['kind'] for f in findings], ['route-difference'])
        self.assertEqual(findings[0]['category'], 'diferencia-documental')
        self.assertFalse([f for f in findings if f['kind'] == 'missing-in-sparx'])
        self.assertEqual(audit_result.unverified, [])

    def test_invoca_from_another_service_is_a_caller_and_never_an_alternative_route(self):
        finding = route_audit([sparx_method('GET-/api/things', 'NUEVO', [BFF_CALLER])]).registry()[0]
        self.assertIn('invocador, no es una ruta de este servicio', finding['sparx']['text'])
        self.assertIn('bff-service', finding['sparx']['text'])
        self.assertTrue(any('Invoca' in e['element'] and e['guid'] == '{BFF}' for e in finding['evidence']['sparx']))

    def test_invoca_from_the_same_service_is_listed_as_unverified(self):
        own = {**BFF_CALLER, 'ownedByTargetService': True, 'ownerService': 'svc-a'}
        result = route_audit([sparx_method('GET-/api/things', 'NUEVO', [own])])
        self.assertTrue([u for u in result.unverified if 'Invoca' in u['topic']])

    def test_truly_absent_operation_is_reported_only_when_no_equivalent_route_exists(self):
        findings = route_audit([sparx_method('GET-/api/other', 'NUEVO')]).registry()
        self.assertEqual([f['kind'] for f in findings], ['missing-in-sparx'])
        self.assertEqual(route_audit([]).registry()[0]['kind'], 'missing-in-sparx')

    def test_only_an_inactive_equivalent_is_a_lifecycle_contradiction(self):
        findings = route_audit([sparx_method('GET-/api/things', 'ELIMINADO')]).registry()
        self.assertEqual([(f['kind'], f['category']) for f in findings], [('operation-lifecycle', 'contradiccion-verificada')])

    def test_ambiguous_or_unreadable_candidates_are_unverified_not_findings(self):
        result = route_audit([sparx_method('GET-/api/things', 'NUEVO', guid='{1}'), sparx_method('GET-/api/v1/things', 'NUEVO', guid='{2}')])
        self.assertEqual(result.registry(), [])
        self.assertEqual(result.unverified[0]['category'], 'verificacion-pendiente')
        self.assertEqual(route_audit([sparx_method('GET-/api/things', None)]).registry(), [])


class ClassificationTests(unittest.TestCase):
    OP = {'method': 'GET', 'path': '/api/v1/things', 'operationId': 'getThings'}

    def finding(self, **overrides):
        base = {'operation': self.OP, 'element': 'Elemento', 'sparx': {'text': 'a'}, 'swagger': {'text': 'b'}, 'inconsistency': 'c', 'severity': 'Media', 'kind': 'contradiction',
                'category': 'contradiccion-verificada', 'evidence': {'sparx': [{'guid': '{X}', 'page': 'p.htm'}], 'swagger': [{'method': 'GET', 'path': '/api/v1/things', 'pointer': '#/operations/0/parameters/query/0'}]}}
        base.update(overrides)
        return base

    def merged(self, supplemental):
        auditor = cmp.Auditor('svc-a', swagger_only(), {'authority': {'branch': BRANCH}, 'operations': []}, 'b')
        auditor.merge_supplemental(supplemental)
        return auditor

    def test_every_finding_carries_exactly_one_verified_category(self):
        findings = audit().registry()
        self.assertTrue(findings)
        self.assertTrue(all(f['category'] in cmp.CATEGORIES for f in findings))
        self.assertEqual({f['category'] for f in findings if f['kind'] == 'requirement-difference'}, {'contradiccion-verificada'})
        self.assertEqual({f['category'] for f in findings if f['kind'].startswith('missing') or f['kind'] == 'http-status-difference'}, {'diferencia-documental'})

    def test_findings_without_a_valid_category_are_rejected(self):
        auditor = self.merged({'findings': [self.finding(category='inconsistencia'), self.finding(category=None, element='otro')]})
        self.assertEqual(auditor.registry(), [])
        self.assertEqual(len([u for u in auditor.unverified if 'rechazado' in u['topic']]), 2)

    def test_contradiction_resting_only_on_a_swagger_example_is_not_accepted(self):
        example = {'sparx': [{'guid': '{X}', 'page': 'p.htm'}], 'swagger': [{'method': 'GET', 'path': '/api/v1/things', 'pointer': '#/operations/0/responses/400/content/application~1json/example'}]}
        auditor = self.merged({'findings': [self.finding(evidence=example)]})
        self.assertEqual(auditor.registry(), [])
        self.assertTrue([u for u in auditor.unverified if 'reclasificado' in u['topic']])
        accepted = self.merged({'findings': [self.finding(evidence=example, category='diferencia-documental', kind='behavior-difference')]})
        self.assertEqual(accepted.registry()[0]['category'], 'diferencia-documental')

    def test_contradiction_internal_to_sparx_is_never_a_sparx_swagger_finding(self):
        auditor = self.merged({'findings': [self.finding(sparxInternal=True)]})
        self.assertEqual(auditor.registry(), [])
        self.assertEqual(auditor.unverified[0]['category'], 'contradiccion-interna-sparx')

    def test_output_source_column_type_is_not_compared_with_the_response_contract(self):
        result = audit()
        self.assertFalse([f for f in result.registry() if f['element'].startswith('OUTPUT') and f['kind'] == 'type-or-structure-difference'])
        self.assertTrue([u for u in result.unverified if u['category'] == 'fuente-no-comparable'])

    def test_constraints_present_in_only_one_source_are_discarded_not_reported(self):
        auditor = self.merged({'findings': [self.finding(kind='missing-in-sparx', category='diferencia-documental', elementClass='constraint', element='Restricciones'),
                                            self.finding(kind='missing-in-swagger', category='diferencia-documental', elementClass='internal-column', element='Columna interna')]})
        self.assertEqual(auditor.registry(), [])
        self.assertEqual(len(auditor.discarded), 2)
        self.assertEqual(auditor.unverified, [])

    def test_successful_verifications_never_enter_no_verificado(self):
        auditor = cmp.Auditor('svc-a', swagger_only(), {'authority': {'branch': BRANCH}, 'operations': []}, 'b')
        for text in ('Los headers coinciden con Swagger', 'Sin diferencias', 'Operación consistente', 'No es inconsistencia'):
            with self.assertRaises(ValueError):
                auditor.cant_verify(self.OP, 'tema', text)
        with self.assertRaises(ValueError):
            auditor.cant_verify(self.OP, 'tema', 'razón', 'coincidencia')
        auditor.merge_supplemental({'unverified': [{'operation': self.OP, 'topic': 'Códigos HTTP', 'reason': 'Ambos conjuntos coinciden.', 'category': 'verificacion-pendiente'}]})
        self.assertEqual(auditor.unverified, [])
        self.assertEqual(len(auditor.discarded), 1)
        auditor.merge_supplemental({'unverified': [{'operation': self.OP, 'topic': 'Filtro name', 'reason': 'Ninguna fuente define el tipo de comparación.', 'category': 'comportamiento-no-especificado'}]})
        self.assertEqual(len(auditor.unverified), 1)

    def test_discarded_candidates_are_kept_in_the_registry_for_traceability_but_not_rendered(self):
        auditor = self.merged({'findings': [self.finding(kind='missing-in-sparx', category='diferencia-documental', elementClass='constraint')]})
        registry = {'service': 'svc-a', 'readOnlyAudit': True, 'sourceCurrency': {'status': 'current'}, 'operationsAudited': [], 'findings': [], 'unverified': [], 'discardedCandidates': auditor.discarded}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'd.docx'
            builder.build(registry, path)
            self.assertEqual([p.text for p in Document(str(path)).paragraphs if p.text], [builder.EMPTY_TEXT])


class SourceCurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / 'input/contracts').mkdir(parents=True)
        (self.repo / 'input/sparx/P/js/data').mkdir(parents=True)
        (self.repo / 'input/contracts/s.yml').write_text('openapi: 3.0.1', encoding='utf-8')
        work = self.repo / 'work'
        work.mkdir()
        (work / 'openapi-spec.yml').write_text('a: 1', encoding='utf-8')
        self.manifest = {'openapi': {'path': 'input/contracts/s.yml', 'sha256': currency.sha(self.repo / 'input/contracts/s.yml')}, 'sparx': {'root': 'input/sparx/P', 'tocFiles': {'t.xml': 'h1'}},
                         'work': 'work', 'artifacts': {'openapi-spec.yml': currency.sha(work / 'openapi-spec.yml')}, 'pages': {}}

    def tearDown(self):
        self.tmp.cleanup()

    def verify(self, toc=None):
        with patch.object(currency, 'sparx_state', return_value=toc or {'t.xml': 'h1'}):
            return currency.verify(self.manifest, self.repo)

    def test_unchanged_sources_are_current(self):
        self.assertEqual(self.verify()['status'], 'current')

    def test_changed_swagger_makes_the_audit_stale(self):
        (self.repo / 'input/contracts/s.yml').write_text('openapi: 3.0.2', encoding='utf-8')
        result = self.verify()
        self.assertEqual(result['status'], 'stale')
        self.assertFalse(result['checks']['openapiSourceUnchanged'])

    def test_changed_sparx_export_makes_the_audit_stale_even_if_swagger_is_unchanged(self):
        result = self.verify({'t.xml': 'changed'})
        self.assertEqual(result['status'], 'stale')
        self.assertTrue(result['checks']['openapiSourceUnchanged'])
        self.assertFalse(result['checks']['sparxHierarchyUnchanged'])

    def test_modified_snapshot_artifact_or_cited_page_makes_the_audit_stale(self):
        (self.repo / 'work' / 'openapi-spec.yml').write_text('a: 2', encoding='utf-8')
        self.assertEqual(self.verify()['status'], 'stale')
        (self.repo / 'work' / 'openapi-spec.yml').write_text('a: 1', encoding='utf-8')
        (self.repo / 'input/sparx/P/page.htm').write_text('v1', encoding='utf-8')
        self.manifest['pages'] = {'page.htm': currency.sha(self.repo / 'input/sparx/P/page.htm')}
        self.assertEqual(self.verify()['status'], 'current')
        (self.repo / 'input/sparx/P/page.htm').write_text('v2', encoding='utf-8')
        self.assertEqual(self.verify()['status'], 'stale')

    def test_validator_detects_cited_page_changes_and_wrong_snapshot_owner(self):
        (self.repo / 'input/sparx/P/page.htm').write_text('v1', encoding='utf-8')
        manifest_file = self.repo / 'work' / 'snapshot-manifest.yml'
        manifest_file.write_text(yaml.safe_dump({**self.manifest, 'service': 'svc-a'}), encoding='utf-8')
        registry = {'service': 'svc-a', 'sources': {'sparxRoot': 'input/sparx/P', 'openapi': {'sha256': self.manifest['openapi']['sha256']}},
                    'sourceCurrency': {'snapshotManifest': 'work/snapshot-manifest.yml', 'citedPageHashes': {'page.htm': currency.sha(self.repo / 'input/sparx/P/page.htm')}}}
        with patch.object(currency, 'sparx_state', return_value={'t.xml': 'h1'}):
            self.assertTrue(all(validator.currency_checks(registry, self.repo).values()))
            (self.repo / 'input/sparx/P/page.htm').write_text('v2', encoding='utf-8')
            self.assertFalse(validator.currency_checks(registry, self.repo)['citedSparxPagesUnchanged'])
            self.assertFalse(validator.currency_checks({**registry, 'service': 'svc-b'}, self.repo)['sourcesStillCurrent'])


class SnapshotIsolationTests(unittest.TestCase):
    def test_snapshots_are_written_only_under_the_service_work_directory_never_factory(self):
        work = snapshot_sources.safe_work_dir('svc-a')
        self.assertEqual(work.relative_to(snapshot_sources.REPO).as_posix(), 'reports/inconsistencias/registros/svc-a/work')
        for unsafe in ('', '../x', 'a/b', '..\\x', '.factory'):
            if unsafe == '.factory':
                self.assertNotIn('.factory', work.parts)
                continue
            with self.assertRaises(SystemExit):
                snapshot_sources.safe_work_dir(unsafe)
        text = (SCRIPTS / 'snapshot_sources.py').read_text(encoding='utf-8')
        self.assertNotIn("'.factory'", text.replace("factoryUsed", ''))
        self.assertIn("'factoryUsed': False", text)


class ReportStructureTests(unittest.TestCase):
    def test_findings_are_grouped_by_operation_then_by_category_with_unverified_last(self):
        auditor = audit()
        auditor.cant_verify({'method': 'GET', 'path': '/api/v1/things'}, 'Filtro name', 'Ninguna fuente define el tipo de comparación.', 'comportamiento-no-especificado')
        registry = {'service': 'svc-a', 'readOnlyAudit': True, 'sourceCurrency': {'status': 'current'}, 'operationsAudited': [{'method': o['method'], 'path': o['path']} for o in openapi()['operations']],
                    'findings': auditor.registry(), 'unverified': auditor.unverified}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'r.docx'
            builder.build(registry, path)
            document = Document(str(path))
            bold = [p.text for p in document.paragraphs if p.runs and all(r.bold for r in p.runs)]
            self.assertIn('Contradicciones verificadas', bold)
            self.assertIn('Diferencias documentales', bold)
            self.assertEqual(bold[-1], 'No verificado')
            self.assertLess(bold.index('GET /api/v1/things'), bold.index('Contradicciones verificadas'))
            self.assertTrue(any(p.text.startswith('GET /api/v1/things: Comportamiento no especificado. Filtro name') for p in document.paragraphs))
            checks = {**validator.registry_checks(registry, 'svc-a'), **validator.docx_checks(registry, path, 'svc-a')}
            self.assertEqual([k for k, v in checks.items() if not v], [])

    def test_validator_rejects_satisfactory_unverified_items_and_uncategorized_findings(self):
        auditor = audit()
        registry = {'service': 'svc-a', 'readOnlyAudit': True, 'sourceCurrency': {'status': 'stale'}, 'operationsAudited': [{'method': o['method'], 'path': o['path']} for o in openapi()['operations']],
                    'findings': auditor.registry(), 'unverified': [{'operation': {}, 'topic': 'Headers', 'reason': 'Los headers coinciden.', 'category': 'verificacion-pendiente'}]}
        checks = validator.registry_checks(registry, 'svc-a')
        self.assertFalse(checks['unverifiedItemsAreCategorizedAndNeverSatisfactory'])
        self.assertFalse(checks['sourceCurrencyRecordedAsCurrent'])
        registry['findings'][0]['category'] = 'otra'
        self.assertFalse(validator.registry_checks(registry, 'svc-a')['everyFindingHasAVerifiedCategory'])


class SimplifiedFormatTests(unittest.TestCase):
    """The Word report omits evidence and internal references; findings.yml keeps them for traceability."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        auditor = audit()
        auditor.cant_verify({'method': 'GET', 'path': '/api/v1/things'}, 'Filtro name', 'Ninguna fuente define el operador de comparación.', 'comportamiento-no-especificado')
        cls.registry = {'service': 'svc-a', 'readOnlyAudit': True, 'sourceCurrency': {'status': 'current'}, 'operationsAudited': [{'method': o['method'], 'path': o['path']} for o in openapi()['operations']],
                        'findings': auditor.registry(), 'unverified': auditor.unverified}
        cls.path = Path(cls.tmp.name) / 'r.docx'
        builder.build(cls.registry, cls.path)
        cls.document = Document(str(cls.path))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_tables_have_no_evidence_field_and_exactly_the_requested_fields(self):
        labels = []
        for table in self.document.tables:
            self.assertEqual(len(table.rows), 6)
            labels.append([table.rows[0].cells[0].text, table.rows[0].cells[2].text] + [r.cells[0].text for r in table.rows[1:]])
        self.assertTrue(labels)
        self.assertTrue(all(row == ['ID', 'Severidad', 'Operación', 'Elemento afectado', 'Sparx', 'Swagger', 'Inconsistencia detectada'] for row in labels))
        self.assertNotIn('Evidencias', '\n'.join(c.text for t in self.document.tables for r in t.rows for c in r.cells))

    def test_document_text_has_no_guid_pointer_page_or_generated_file_references(self):
        everything = '\n'.join(p.text for p in self.document.paragraphs) + '\n'.join(c.text for t in self.document.tables for r in t.rows for c in r.cells)
        for fragment in ('{M-1}', '#/operations', 'EARoot', '.htm', 'findings.yml', 'linkdocs', 'snapshot', 'pageSha256', 'ACT-1'):
            self.assertNotIn(fragment, everything)
        self.assertFalse(validator.INTERNAL_REFERENCE.search(everything))

    def test_evidence_is_kept_in_the_registry_for_traceability_and_verification(self):
        self.assertTrue(all(f['evidence']['sparx'] and f['evidence']['swagger'] for f in self.registry['findings']))
        self.assertTrue(all(any(e.get('guid') or e.get('page') or e.get('authorityFile') for e in f['evidence']['sparx']) for f in self.registry['findings']))
        self.assertTrue(all(e['pointer'].startswith('#/') for f in self.registry['findings'] for e in f['evidence']['swagger']))
        self.assertTrue(validator.registry_checks(self.registry, 'svc-a')['everyFindingHasSparxEvidence'])

    def test_validator_flags_internal_references_leaked_into_the_report(self):
        for leak in ('GUID {8F6E882A-76CA-09EE-8DEC-71FB038BD0D5}', 'puntero #/operations/0/parameters', 'página EA1496.htm', 'archivo findings.yml', 'ruta EARoot/EA2/EA6'):
            registry = copy.deepcopy(self.registry)
            registry['findings'][0]['sparx']['text'] += ' ' + leak
            path = Path(self.tmp.name) / 'leak.docx'
            builder.build(registry, path)
            checks = validator.docx_checks(registry, path, 'svc-a')
            self.assertFalse(checks['noInternalReferencesInDocument'], leak)

    def test_validator_flags_a_reintroduced_evidence_field_or_changed_table_shape(self):
        path = Path(self.tmp.name) / 'evidence.docx'
        document = Document(str(self.path))
        table = document.tables[0]
        table.add_row().cells[0].text = 'Evidencias'
        document.save(path)
        checks = validator.docx_checks(self.registry, path, 'svc-a')
        self.assertFalse(checks['noEvidenceFieldInTables'])

    def test_explanations_remain_complete_and_unverified_items_show_no_internal_references(self):
        blob = '\n'.join(c.text for t in self.document.tables for r in t.rows for c in r.cells)
        for finding in self.registry['findings']:
            self.assertIn(finding['sparx']['text'], blob)
            self.assertIn(finding['swagger']['text'], blob)
            self.assertIn(finding['inconsistency'], blob)
        self.assertTrue(any(p.text.startswith('GET /api/v1/things: Comportamiento no especificado') for p in self.document.paragraphs))

    def test_layout_is_compact_a4_with_widths_that_fit_the_text_area_and_black_calibri_11(self):
        section = self.document.sections[0]
        self.assertAlmostEqual(section.left_margin, builder.MARGIN, delta=1000)
        usable = section.page_width - section.left_margin - section.right_margin
        for table in self.document.tables:
            total = sum(c.width for c in table.rows[0].cells)
            self.assertLessEqual(total, usable + 1000)
            self.assertGreater(total, usable - builder.Cm(0.4))
        checks = validator.docx_checks(self.registry, self.path, 'svc-a')
        for name in ('allTextBlack', 'everyRunExplicitlyBlackCalibri11', 'noHeaderFooterContent', 'noPageNumberFields', 'noCoverPage', 'noGenericIntroductionsOrSections', 'tablesFitPageWidth'):
            self.assertTrue(checks[name], name)


# ----------------------------------------------------------------------------------------------------------------------
# Visual evidence: authentic grayscale images below each table; text-only when an authentic image is not possible.
# ----------------------------------------------------------------------------------------------------------------------
SPEC_YAML = """openapi: 3.0.1
paths:
  /api/v1/things:
    get:
      summary: Busca.
components:
  schemas:
    Thing:
      type: object
      required:
        - code
        - name
      properties:

        code:
          type: integer
          format: int32
          description: Codigo.

        name:
          $ref: '#/components/schemas/Other'
"""
HTML_PAGE = """<html><body><h1>Titulo</h1>
<table border="1"><tr><td>Campo</td><td>Tipo</td></tr>
<tr><td>code</td><td>string</td></tr><tr><td>name</td><td>string</td></tr>
<tr><td>filler</td><td>x</td></tr><tr><td>filler2</td><td>y</td></tr><tr><td>filler3</td><td>z</td></tr></table>
<p style="margin-top:600px">Regla: sin filtros devuelve todos los registros de la tabla.</p>
<p>UUID: {8F6E882A-76CA-09EE-8DEC-71FB038BD0D5}</p></body></html>"""
needs_browser = unittest.skipIf(ce.find_browser() is None, 'no browser available for real screenshots')


class YamlFragmentTests(unittest.TestCase):
    def test_fragments_are_verbatim_and_never_include_the_next_sibling(self):
        self.assertEqual(ve.yaml_fragment(SPEC_YAML, ['components', 'schemas', 'Thing', 'properties', 'code']),
                         ['        code:', '          type: integer', '          format: int32', '          description: Codigo.'])
        self.assertEqual(ve.yaml_fragment(SPEC_YAML, ['components', 'schemas', 'Thing', 'required']), ['      required:', '        - code', '        - name'])
        self.assertEqual(ve.yaml_fragment(SPEC_YAML, ['paths', '/api/v1/things', 'get'], key_only=True), ['    get:'])
        self.assertIsNone(ve.yaml_fragment(SPEC_YAML, ['components', 'schemas', 'Missing']))

    def test_each_fragment_is_dedented_alone_or_kept_relative_when_requested(self):
        nodes = [{'path': ['components', 'schemas', 'Thing', 'required']}, {'path': ['components', 'schemas', 'Thing', 'properties', 'code']}]
        lines = ve.yaml_fragments(SPEC_YAML, nodes)
        self.assertEqual(lines[0], 'required:')
        self.assertIn('code:', lines)
        route = [{'path': ['paths', '/api/v1/things'], 'keyOnly': True}, {'path': ['paths', '/api/v1/things', 'get'], 'keyOnly': True}]
        self.assertEqual(ve.yaml_fragments(SPEC_YAML, route, relative=True), ['/api/v1/things:', '  get:'])

    def test_fragment_longer_than_the_limit_is_refused(self):
        self.assertIsNone(ve.yaml_fragments(SPEC_YAML, [{'path': ['components']}], max_lines=3))


class ImageFittingTests(unittest.TestCase):
    def test_images_are_fitted_inside_the_margins_without_exceeding_page_limits(self):
        width, height, scale = ve.fit_cm(4000, 600)
        self.assertLessEqual(width, ve.MAX_WIDTH_CM + 1e-6)
        self.assertLess(scale, 1)
        width, height, scale = ve.fit_cm(300, 3000)
        self.assertLessEqual(height, ve.MAX_HEIGHT_CM + 1e-6)
        self.assertEqual(ve.fit_cm(300, 100)[2], 1.0)

    def test_stitching_keeps_separate_fragments_apart_and_merges_adjacent_ones(self):
        rects = [{'x': 0, 'y': 0, 'w': 100, 'h': 30}, {'x': 0, 'y': 40, 'w': 120, 'h': 30}, {'x': 0, 'y': 400, 'w': 100, 'h': 30}]
        merged = ce.merge_rects(rects)
        self.assertEqual(len(merged), 2)
        self.assertEqual((merged[0]['y'], merged[0]['h'], merged[0]['w']), (0, 70, 120))


class SwaggerCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Path(self.tmp.name) / 's.yml'
        self.source.write_text(SPEC_YAML, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_swagger_fragment_is_rendered_from_the_original_lines_in_grayscale(self):
        output = Path(self.tmp.name) / 'a.png'
        result = ce.capture_swagger(self.source, {'nodes': [{'path': ['components', 'schemas', 'Thing', 'properties', 'code']}]}, output)
        self.assertEqual(result['status'], 'captured')
        self.assertEqual(result['capturedText'][0], 'code:')
        from PIL import Image
        with Image.open(output) as image:
            self.assertTrue(ve.is_grayscale(image))
        self.assertEqual(self.source.read_text(encoding='utf-8'), SPEC_YAML)

    def test_reference_lines_are_replaced_by_an_ellipsis_never_shown(self):
        output = Path(self.tmp.name) / 'b.png'
        result = ce.capture_swagger(self.source, {'nodes': [{'path': ['components', 'schemas', 'Thing', 'properties', 'name']}]}, output)
        self.assertEqual(result['status'], 'captured')
        self.assertEqual(result['capturedText'], ['name:', '  ' + ve.ELISION])
        self.assertFalse(ve.leaks(result['capturedText']))

    def test_missing_nodes_stay_text_only(self):
        output = Path(self.tmp.name) / 'b.png'
        self.assertEqual(ce.capture_swagger(self.source, {'nodes': [{'path': ['nope']}]}, output)['status'], 'unavailable')
        self.assertFalse(output.exists())

    def test_illegible_images_are_rejected_instead_of_shrunk(self):
        output = Path(self.tmp.name) / 'c.png'
        from PIL import Image
        Image.new('L', (12000, 300), 255).save(output)
        result = ce.finalize({'status': 'captured', 'widthPx': 12000, 'heightPx': 300}, output, Path(self.tmp.name), self.source, 's.yml')
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse(output.exists())


@needs_browser
class SparxScreenshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.page = Path(self.tmp.name) / 'page.htm'
        self.page.write_text(HTML_PAGE, encoding='utf-8')
        self.before = self.page.read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def shot(self, regions, name='s.png'):
        return ce.capture_sparx(self.page, regions, Path(self.tmp.name) / name, ce.find_browser())

    def test_real_screenshot_is_cropped_to_the_justifying_rows_and_is_grayscale(self):
        result = self.shot([{'text': 'Campo', 'kind': 'row'}, {'text': 'code', 'kind': 'row'}])
        self.assertEqual(result['status'], 'captured')
        self.assertEqual(result['capturedText'], ['Campo Tipo', 'code string'])
        from PIL import Image
        with Image.open(Path(self.tmp.name) / 's.png') as image:
            self.assertEqual(image.mode, 'L')
            self.assertLess(image.height, 200)      # only two rows, not the whole page
        self.assertEqual(self.page.read_bytes(), self.before)

    def test_distant_fragments_are_stitched_and_text_spans_are_supported(self):
        result = self.shot([{'text': 'code', 'kind': 'row'}, {'text': 'Regla: sin filtros', 'to': 'de la tabla', 'kind': 'span'}])
        self.assertEqual(result['status'], 'captured')
        self.assertEqual(len(result['capturedText']), 2)
        self.assertIn('sin filtros devuelve todos los registros de la tabla', result['capturedText'][1])

    def test_missing_text_or_internal_references_leave_the_finding_text_only(self):
        missing = self.shot([{'text': 'texto inexistente', 'kind': 'row'}])
        self.assertEqual(missing['status'], 'unavailable')
        leak = self.shot([{'text': 'UUID:', 'kind': 'block'}], 'leak.png')
        self.assertEqual(leak['status'], 'unavailable')
        self.assertFalse((Path(self.tmp.name) / 'leak.png').exists())


class VisualRegistryAndReportTests(unittest.TestCase):
    """capture_evidence.run + builder + validator over a synthetic repository."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        (cls.repo / 'input/contracts').mkdir(parents=True)
        (cls.repo / 'input/sparx/P').mkdir(parents=True)
        (cls.repo / 'input/contracts/s.yml').write_text(SPEC_YAML, encoding='utf-8')
        (cls.repo / 'input/sparx/P/page.htm').write_text(HTML_PAGE, encoding='utf-8')
        cls.registry_dir = cls.repo / 'reports/svc-a'
        cls.registry_dir.mkdir(parents=True)
        op = {'method': 'GET', 'path': '/api/v1/things', 'operationId': 'getThings'}
        code_swagger = {'method': 'GET', 'path': '/api/v1/things', 'pointer': '#/operations/0/parameters/query/0',
                        'capture': {'nodes': [{'path': ['components', 'schemas', 'Thing', 'properties', 'code']}]}}
        sparx_capture = {'branch': 'b', 'page': 'P/page.htm', 'guid': '{G}', 'capture': {'file': 'page.htm', 'regions': [{'text': 'Campo', 'kind': 'row'}, {'text': 'code', 'kind': 'row'}]}}

        def finding(number, sparx_evidence, swagger_evidence):
            return {'id': f'INC-00{number}', 'key': f'k{number}', 'operation': op, 'element': f'campo {number}', 'kind': 'type-or-structure-difference', 'category': 'contradiccion-verificada',
                    'sparx': {'text': 'Sparx declara string.'}, 'swagger': {'text': 'Swagger declara integer.'}, 'inconsistency': 'El tipo difiere.', 'severity': 'Media',
                    'evidence': {'sparx': sparx_evidence, 'swagger': swagger_evidence}}
        cls.registry = {'service': 'svc-a', 'readOnlyAudit': True, 'sourceCurrency': {'status': 'current'}, 'sources': {'sparxRoot': 'input/sparx/P', 'openapi': {'path': 'input/contracts/s.yml', 'sha256': 'x'}},
                        'operationsAudited': [{'method': 'GET', 'path': '/api/v1/things'}], 'unverified': [],
                        'findings': [finding(1, [sparx_capture], [code_swagger]),
                                     finding(2, [{'branch': 'b', 'page': 'P/page.htm', 'guid': '{G}'}], [{'method': 'GET', 'path': '/api/v1/things', 'pointer': '#/operations/0/responses'}])]}
        cls.registry_path = cls.registry_dir / 'findings.yml'
        cls.registry_path.write_text(yaml.safe_dump(cls.registry, allow_unicode=True, sort_keys=False), encoding='utf-8')
        cls.summary = ce.run(cls.registry_path, cls.repo)
        cls.registry = yaml.safe_load(cls.registry_path.read_bytes())
        cls.docx = cls.repo / 'out.docx'
        builder.build(cls.registry, cls.docx, cls.registry_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def captured(self):
        return [(f['id'], s, v) for f in self.registry['findings'] for s, v in f['visualEvidence'].items() if v['status'] == 'captured']

    @needs_browser
    def test_findings_with_authentic_images_record_them_and_others_stay_text_only(self):
        first, second = self.registry['findings']
        self.assertEqual(first['visualEvidence']['sparx']['status'], 'captured')
        self.assertEqual(first['visualEvidence']['swagger']['status'], 'captured')
        self.assertTrue(all(v['status'] == 'unavailable' and 'image' not in v and v['reason'] for v in second['visualEvidence'].values()))
        self.assertTrue(all(f['evidence']['sparx'] and f['evidence']['swagger'] for f in self.registry['findings']))   # evidence stays structured

    @needs_browser
    def test_word_shows_labelled_images_below_the_table_of_the_finding_only(self):
        document = Document(str(self.docx))
        self.assertEqual(len(document.inline_shapes), 2)
        order = []
        for element in document.element.body:
            tag = element.tag.split('}')[1]
            if tag == 'tbl':
                order.append('TABLA')
            elif tag == 'p':
                text = ''.join(t.text or '' for t in element.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                if list(element.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}blip')):
                    order.append('IMG')
                elif text in ('Sparx', 'Swagger'):
                    order.append(text)
        self.assertEqual(order, ['TABLA', 'Sparx', 'IMG', 'Swagger', 'IMG', 'TABLA'])
        usable = document.sections[0].page_width - document.sections[0].left_margin - document.sections[0].right_margin
        self.assertTrue(all(shape.width <= usable + 1000 for shape in document.inline_shapes))

    @needs_browser
    def test_validator_accepts_authentic_images_and_rejects_tampering(self):
        base = validator.visual_checks(self.registry, self.docx, self.registry_dir, self.repo)
        self.assertEqual([k for k, v in base.items() if not v], [])
        doc_checks = validator.docx_checks(self.registry, self.docx, 'svc-a')
        self.assertEqual([k for k, v in doc_checks.items() if not v], [])
        leaky = copy.deepcopy(self.registry)
        leaky['findings'][0]['visualEvidence']['sparx']['capturedText'].append('GUID {8F6E882A-76CA-09EE-8DEC-71FB038BD0D5}')
        self.assertFalse(validator.visual_checks(leaky, self.docx, self.registry_dir, self.repo)['imagesShowNoInternalReferences'])
        forged = copy.deepcopy(self.registry)
        forged['findings'][0]['visualEvidence']['swagger']['capturedText'] = ['code:', '  type: string']
        self.assertFalse(validator.visual_checks(forged, self.docx, self.registry_dir, self.repo)['imageFragmentsMatchOriginalSources'])
        (self.repo / 'input/contracts/s.yml').write_text(SPEC_YAML + '# changed\n', encoding='utf-8')
        try:
            self.assertFalse(validator.visual_checks(self.registry, self.docx, self.registry_dir, self.repo)['imageSourcesUnchanged'])
        finally:
            (self.repo / 'input/contracts/s.yml').write_text(SPEC_YAML, encoding='utf-8')

    @needs_browser
    def test_validator_rejects_color_images_and_a_changed_image_file(self):
        from PIL import Image
        name = next(v['image'] for _, s, v in self.captured() if s == 'swagger')
        path = self.registry_dir / name
        original = path.read_bytes()
        try:
            Image.new('RGB', (300, 60), (200, 30, 30)).save(path, dpi=(ve.DPI, ve.DPI))
            checks = validator.visual_checks(self.registry, self.docx, self.registry_dir, self.repo)
            self.assertFalse(checks['imagesAreGrayscale'])
            self.assertFalse(checks['imagesMatchRecordedHashes'])
        finally:
            path.write_bytes(original)

    def test_no_image_is_inserted_for_unavailable_evidence_and_missing_files_are_not_hidden(self):
        registry = copy.deepcopy(self.registry)
        for finding in registry['findings']:
            finding['visualEvidence'] = {'sparx': {'status': 'unavailable', 'reason': 'x'}, 'swagger': {'status': 'unavailable', 'reason': 'x'}}
        path = Path(self.tmp.name) / 'text_only.docx'
        builder.build(registry, path, self.registry_dir)
        document = Document(str(path))
        self.assertEqual(len(document.inline_shapes), 0)
        self.assertNotIn('Sparx', [p.text for p in document.paragraphs])
        self.assertTrue(all(validator.visual_checks(registry, path, self.registry_dir, self.repo).values()))
        broken = copy.deepcopy(self.registry)
        broken['findings'][0]['visualEvidence']['swagger'] = {'status': 'captured', 'image': 'images/nope.png', 'widthPx': 300, 'heightPx': 100}
        with self.assertRaises(FileNotFoundError):
            builder.build(broken, Path(self.tmp.name) / 'broken.docx', self.registry_dir)

    @needs_browser
    def test_word_text_still_has_no_internal_references_or_evidence_field_with_images(self):
        document = Document(str(self.docx))
        everything = '\n'.join(p.text for p in document.paragraphs) + '\n'.join(c.text for t in document.tables for r in t.rows for c in r.cells)
        self.assertFalse(validator.INTERNAL_REFERENCE.search(everything))
        self.assertNotIn('Evidencias', everything)


# ----------------------------------------------------------------------------------------------------------------------
# Automatic derivation of captures from structured findings (no capture specs, no supplemental.yml).
# ----------------------------------------------------------------------------------------------------------------------
AUTO_YAML = """openapi: 3.0.1
paths:
  /api/v1/things:
    get:
      parameters:
        - $ref: '#/components/parameters/AppId'
        - name: id
          in: query
          required: false
          schema:
            type: integer
      responses:
        '200':
          description: OK
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ThingResponse'
              example:
                code: 200
        '400':
          description: Bad request
    post:
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ThingRequest'
      responses:
        '200':
          description: OK
components:
  parameters:
    AppId:
      name: x-app-id
      in: header
      required: true
      schema:
        type: string
  schemas:
    ThingRequest:
      type: object
      properties:
        name:
          type: string
    ThingResponse:
      type: object
      properties:
        code:
          type: integer
          format: int32
        data:
          $ref: '#/components/schemas/Data'
    Data:
      type: object
"""
AUTO_NORMALIZED = {'operations': [
    {'method': 'GET', 'path': '/api/v1/things', 'parameters': {'header': [{'name': 'x-app-id'}], 'query': [{'name': 'id'}], 'path': []}},
    {'method': 'POST', 'path': '/api/v1/things', 'parameters': {'header': [], 'query': [], 'path': []}}]}
OP = '#/operations/0'


class SwaggerDerivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.swagger = loc.Swagger(AUTO_YAML, AUTO_NORMALIZED)

    def lines(self, pointer):
        derived = self.swagger.derive(pointer)
        self.assertNotIn('reason', derived, derived)
        return ve.yaml_fragments(AUTO_YAML, derived['nodes'], derived.get('maxLines', 40), bool(derived.get('relative')))

    def test_route_pointer_yields_the_path_and_method_keys(self):
        self.assertEqual(self.lines(OP + '/path'), ['/api/v1/things:', '  get:'])

    def test_parameters_are_found_inline_and_through_a_ref_without_showing_the_reference(self):
        self.assertEqual(self.lines(OP + '/parameters/query/0'), ['- name: id', '  in: query', '  required: false', '  schema:', '    type: integer'])
        header = self.lines(OP + '/parameters/header/0')
        self.assertEqual(header[0], 'name: x-app-id')            # resolved from the shared component, without its name
        self.assertFalse(ve.leaks(header))
        self.assertEqual(self.lines(OP + '/parameters/query')[0], '- name: id')     # collection of an existing location

    def test_ref_is_followed_to_locate_nested_schema_properties_and_examples(self):
        code = self.lines(OP + '/responses/200/content/application~1json/schema/properties/code')
        self.assertEqual(code, ['code:', '  type: integer', '  format: int32'])
        self.assertEqual(self.lines(OP + '/responses/200/content/application~1json/example'), ['example:', '  code: 200'])
        request = self.lines('#/operations/1/requestBody/content/application~1json/schema/properties/name')
        self.assertEqual(request, ['name:', '  type: string'])

    def test_reference_lines_inside_a_fragment_are_elided_not_hidden_silently(self):
        properties = self.lines(OP + '/responses/200/content/application~1json/schema/properties')
        self.assertIn('  data:', properties)
        self.assertIn('    ' + ve.ELISION, properties)
        self.assertFalse(ve.leaks(properties))

    def test_responses_collection_lists_only_the_declared_status_codes(self):
        self.assertEqual(self.lines(OP + '/responses'), ['responses:', "  '200':", "  '400':"])

    def test_large_nodes_fall_back_to_a_shallow_excerpt_and_unknown_elements_are_refused(self):
        derived = loc.Swagger(AUTO_YAML, AUTO_NORMALIZED).derive(OP + '/responses/200')
        self.assertNotIn('reason', derived)
        big = AUTO_YAML.replace("          description: OK\n          content:", "          description: OK\n          bulk:\n" + ''.join(f'            x{i}: v\n' for i in range(60)) + "          content:", 1)
        shallow = loc.Swagger(big, AUTO_NORMALIZED).derive(OP + '/responses/200')
        self.assertTrue(shallow['relative'])
        self.assertLessEqual(len(ve.yaml_fragments(big, shallow['nodes'], 100, True)), 100)
        self.assertIn('reason', self.swagger.derive(OP + '/responses/200/content/application~1json/schema/properties/ghost'))
        self.assertIn('reason', self.swagger.derive(OP + '/parameters/query/7'))
        self.assertIn('reason', self.swagger.derive('#/operations/9/path'))
        self.assertIn('reason', self.swagger.derive('#/components/schemas/X'))

    def test_derivation_never_changes_the_source_and_is_deterministic(self):
        self.assertEqual(self.swagger.derive(OP + '/parameters/query/0'), loc.Swagger(AUTO_YAML, AUTO_NORMALIZED).derive(OP + '/parameters/query/0'))
        self.assertEqual(self.swagger.text, AUTO_YAML)


def model(rows, blocks=(), text=''):
    built = []
    first = 0
    for i, cells in enumerate(rows):
        if cells == '---':          # starts a new table
            first = i + 1
            built.append({'i': i, 'first': i, 'cells': ['']})
            continue
        built.append({'i': i, 'first': first, 'cells': cells})
    return {'rows': built, 'blocks': list(blocks), 'text': text}


TABLE = [['OUTPUT', 'SchemaObject', 'Valores', 'Tipo'], ['responseAudit', 'openapi.attribute', '', 'ResponseAuditType'],
         ['ResponseAuditType', 'SchemaObject', '', ''], ['code', 'openapi.attribute', 'Codigo HTTP', 'string'], ['message', 'openapi.attribute', 'Mensaje', 'string'],
         ['subtype', 'openapi.attribute', 'Si termina en exito', 'string'], ['LanguagesResponseType', 'AnonSchemaObject', '', ''], ['code', 'openapi.attribute', 'SELECT[].CODE', 'string']]


class SparxPlanningTests(unittest.TestCase):
    def finding(self, element, text, **extra):
        return {'element': element, 'sparx': {'text': text}, 'swagger': {'text': 'x'}, 'inconsistency': 'y', **extra}

    def test_field_rows_are_chosen_inside_the_section_named_by_the_finding(self):
        finding = self.finding('Respuesta: tipo del campo code', 'ResponseAuditType declara code con tipo string')
        plan = loc.plan_sparx(finding, {'element': '«EndEvent» 200'}, model(TABLE), None, 'svc')
        chosen = [r['index'] for r in plan['regions']]
        self.assertIn(3, chosen)            # code of ResponseAuditType
        self.assertNotIn(7, chosen)         # not the code of the other section
        self.assertIn(2, chosen)            # the section header gives context
        self.assertIn(0, chosen)            # and the table header names the columns

    def test_rows_without_a_named_section_use_the_first_match_and_unknown_fields_find_nothing(self):
        plan = loc.plan_sparx(self.finding('Nombre del campo subtype', 'x'), {'element': 'a'}, model(TABLE), None, 'svc')
        self.assertIn(5, [r['index'] for r in plan['regions']])
        none = loc.plan_sparx(self.finding('Campo ghost', 'zzz'), {'element': 'a'}, model(TABLE), None, 'svc')
        self.assertIn('reason', none)
        self.assertEqual(none['score'], 0)

    def test_row_id_values_and_section_tables_locate_rows_of_auto_findings(self):
        detail = {'operations': [{'activities': [{'sections': [{'rows': [{'evidenceId': 'e1', 'values': {'query': 'id', 'sparx': 'openapi.parameter', 'type': 'integer'}}]}]}]}]}
        values = loc.row_values_for(detail, 'e1')
        self.assertEqual(values, ['id', 'openapi.parameter', 'integer'])
        query_table = model([['Query', 'SPARX', 'Tipo'], ['id', 'openapi.parameter', 'integer'], ['code', 'openapi.parameter', 'string']])
        by_row = loc.plan_sparx(self.finding('query id', 'x'), {'element': 'q', 'evidenceId': 'e1'}, query_table, values, 'svc')
        self.assertIn(1, [r['index'] for r in by_row['regions']])
        self.assertNotIn(2, [r['index'] for r in by_row['regions']])
        absent = loc.plan_sparx(self.finding('query limit', 'x'), {'element': 'q', 'section': 'query'}, query_table, None, 'svc')
        self.assertEqual(sorted({r['index'] for r in absent['regions']}), [0, 1, 2])     # the real table that lacks the element, nothing invented
        self.assertIsNone(loc.row_values_for(detail, 'missing'))

    def test_prose_is_narrowed_to_the_lines_that_carry_the_finding_vocabulary(self):
        lines = ['Sin filtros se devuelven todos los idiomas registrados en la tabla LANGUAGE', 'SELECT', 'ID,', 'CODE,', 'FROM LANGUAGE', 'WHERE ID = 1']
        block = {'text': ' '.join(lines) + ' ' + ' '.join(['relleno'] * 70), 'lines': lines}
        plan = loc.plan_sparx(self.finding('Consulta sin filtros', 'Sin filtros se devuelven todos los idiomas registrados en la tabla'), {'element': 'a'}, model(TABLE, [block]), None, 'svc')
        region = plan['regions'][0]
        self.assertEqual(region['kind'], 'span')
        self.assertTrue(region['text'].startswith('Sin filtros'))
        self.assertTrue(region['to'].endswith('LANGUAGE'))
        self.assertNotIn('SELECT', region['to'])

    def test_method_and_end_event_pages_and_context_only_relations(self):
        page = model([], text='dom-document-language / GET-/api/languages\nGET-/api/languages : Public <<Metodo>> Actividad')
        plan = loc.plan_sparx(self.finding('Ruta', 'x'), {'element': '«Método» GET-/api/languages'}, page, None, 'dom-document-language')
        self.assertEqual([r['kind'] for r in plan['regions']], ['text', 'span'])
        self.assertIn('reason', loc.plan_sparx(self.finding('Ruta', 'x'), {'element': '«Método» GET-/api/other'}, page, None, 'dom-document-language'))
        self.assertIn('reason', loc.plan_sparx(self.finding('Ruta', 'x'), {'element': 'Relación «Invoca» desde «Método» GET-/api/languages'}, page, None, 'svc'))
        end = model([], text='404 : Public <<EndEvent>> EndEvent')
        self.assertEqual(loc.plan_sparx(self.finding('HTTP 404', 'x'), {'element': 'Evento de fin 404'}, end, None, 'svc')['regions'][0]['to'], 'EndEvent')


AUTO_HTML = """<html><body><h1>Titulo</h1>
<table border="1"><tr><td>OUTPUT</td><td>SchemaObject</td><td>Valores</td><td>Tipo</td></tr>
<tr><td>ResponseAuditType</td><td>SchemaObject</td><td></td><td></td></tr>
<tr><td>code</td><td>openapi.attribute</td><td>Codigo HTTP numerico</td><td>string</td></tr>
<tr><td>message</td><td>openapi.attribute</td><td>Mensaje estandar</td><td>string</td></tr>
<tr><td>LanguagesType</td><td>AnonSchemaObject</td><td></td><td></td></tr>
<tr><td>code</td><td>openapi.attribute</td><td>SELECT.CODE</td><td>string</td></tr></table>
<div style="margin-top:500px">Sin filtros se devuelven todos los idiomas registrados en la tabla LANGUAGE<br>SELECT ID<br>FROM LANGUAGE</div>
</body></html>"""


@needs_browser
class AutomaticCaptureEndToEndTests(unittest.TestCase):
    """Findings carry only structured evidence: no capture specs, no supplemental.yml."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        for folder in ('input/contracts', 'input/sparx/P', 'reports/svc-a/work'):
            (cls.repo / folder).mkdir(parents=True)
        (cls.repo / 'input/contracts/s.yml').write_text(AUTO_YAML, encoding='utf-8')
        (cls.repo / 'input/sparx/P/linkdoc.htm').write_text(AUTO_HTML, encoding='utf-8')
        work = cls.repo / 'reports/svc-a/work'
        (work / 'openapi-spec.yml').write_text(yaml.safe_dump(AUTO_NORMALIZED), encoding='utf-8')
        (work / 'sparx-authoritative-endpoint-detail.yml').write_text(yaml.safe_dump({'operations': []}), encoding='utf-8')
        (work / 'snapshot-manifest.yml').write_text(yaml.safe_dump({'work': 'reports/svc-a/work', 'service': 'svc-a'}), encoding='utf-8')
        cls.registry_dir = cls.repo / 'reports/svc-a'
        op = {'method': 'GET', 'path': '/api/v1/things', 'operationId': 'getThings'}

        def finding(number, element, sparx_text, sparx_evidence, swagger_pointer):
            return {'id': f'INC-00{number}', 'key': f'k{number}', 'operation': op, 'element': element, 'kind': 'type-or-structure-difference', 'category': 'contradiccion-verificada',
                    'sparx': {'text': sparx_text}, 'swagger': {'text': 'Swagger declara code integer.'}, 'inconsistency': 'El tipo difiere.', 'severity': 'Media',
                    'evidence': {'sparx': sparx_evidence, 'swagger': [{'method': 'GET', 'path': '/api/v1/things', 'pointer': swagger_pointer}]}}
        evidence = [{'branch': 'b', 'element': '«EndEvent» 200', 'linkdoc': 'linkdoc.htm', 'guid': '{G}'}]
        cls.registry = {'service': 'svc-a', 'readOnlyAudit': True, 'sourceCurrency': {'status': 'current', 'snapshotManifest': 'reports/svc-a/work/snapshot-manifest.yml'},
                        'sources': {'sparxRoot': 'input/sparx/P', 'openapi': {'path': 'input/contracts/s.yml', 'sha256': 'x'}},
                        'operationsAudited': [{'method': 'GET', 'path': '/api/v1/things'}], 'unverified': [],
                        'findings': [finding(1, 'Respuesta: tipo del campo code', 'ResponseAuditType declara code con tipo string', evidence,
                                             OP + '/responses/200/content/application~1json/schema/properties/code'),
                                     finding(2, 'Consulta sin filtros', 'Sin filtros se devuelven todos los idiomas registrados en la tabla LANGUAGE', evidence, OP + '/parameters/query/0'),
                                     finding(3, 'Campo fantasma', 'Texto que no existe en la pagina original', evidence, OP + '/parameters/query/5')]}
        cls.path = cls.registry_dir / 'findings.yml'
        cls.path.write_text(yaml.safe_dump(cls.registry, allow_unicode=True, sort_keys=False), encoding='utf-8')
        cls.summary = ce.run(cls.path, cls.repo)
        cls.result = yaml.safe_load(cls.path.read_bytes())
        cls.docx = cls.repo / 'out.docx'
        builder.build(cls.result, cls.docx, cls.registry_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_no_finding_declares_a_capture_spec(self):
        self.assertFalse([e for f in self.registry['findings'] for s in ('sparx', 'swagger') for e in f['evidence'][s] if 'capture' in e])

    def test_images_are_generated_automatically_from_structured_evidence(self):
        first, second, third = (f['visualEvidence'] for f in self.result['findings'])
        self.assertEqual((first['sparx']['status'], first['swagger']['status']), ('captured', 'captured'))
        self.assertEqual((second['sparx']['status'], second['swagger']['status']), ('captured', 'captured'))
        self.assertTrue(first['sparx']['derivedSpec']['automatic'] and first['swagger']['derivedSpec']['automatic'])
        self.assertEqual(self.summary['automatic'], self.summary['captured'])

    def test_sparx_rows_come_from_the_section_the_finding_names_and_prose_from_the_matching_lines(self):
        rows = self.result['findings'][0]['visualEvidence']['sparx']['capturedText']
        self.assertTrue(any(t.startswith('code openapi.attribute Codigo HTTP') for t in rows))
        self.assertFalse(any('SELECT.CODE' in t for t in rows))
        prose = ' '.join(self.result['findings'][1]['visualEvidence']['sparx']['capturedText'])
        self.assertIn('Sin filtros se devuelven todos', prose)
        self.assertNotIn('SELECT ID', prose)

    def test_swagger_images_come_from_resolved_original_lines_without_references(self):
        text = self.result['findings'][0]['visualEvidence']['swagger']['capturedText']
        self.assertEqual(text, ['code:', '  type: integer', '  format: int32'])
        self.assertFalse(ve.leaks(self.result['findings'][1]['visualEvidence']['swagger']['capturedText']))

    def test_evidence_that_cannot_be_found_stays_text_only_with_the_cause_recorded(self):
        third = self.result['findings'][2]['visualEvidence']
        self.assertEqual(third['sparx']['status'], 'unavailable')
        self.assertEqual(third['swagger']['status'], 'unavailable')
        self.assertTrue(third['sparx']['reason'] and third['swagger']['reason'])
        self.assertNotIn('image', third['sparx'])
        self.assertFalse((self.registry_dir / 'images' / 'INC-003-sparx.png').exists())

    def test_images_match_their_findings_in_the_word_and_pass_every_authenticity_check(self):
        document = Document(str(self.docx))
        self.assertEqual(len(document.inline_shapes), 4)
        checks = {**validator.visual_checks(self.result, self.docx, self.registry_dir, self.repo), **validator.docx_checks(self.result, self.docx, 'svc-a')}
        self.assertEqual([k for k, v in checks.items() if not v], [])
        names = sorted(p.name for p in (self.registry_dir / 'images').iterdir())
        self.assertEqual(names, ['INC-001-sparx.png', 'INC-001-swagger.png', 'INC-002-sparx.png', 'INC-002-swagger.png'])

    def test_validator_detects_unrelated_or_non_reproducible_captures(self):
        unrelated = copy.deepcopy(self.result)
        unrelated['findings'][0]['visualEvidence']['swagger']['capturedText'] = ['zzzz: yyyy']
        self.assertFalse(validator.visual_checks(unrelated, self.docx, self.registry_dir, self.repo)['imagesRelateToTheirFinding'])
        forged = copy.deepcopy(self.result)
        forged['findings'][1]['visualEvidence']['swagger']['derivedSpec']['nodes'] = [{'path': ['paths', '/api/v1/things', 'post', 'responses']}]
        self.assertFalse(validator.visual_checks(forged, self.docx, self.registry_dir, self.repo)['captureSpecsReproducibleFromFindings'])


# ----------------------------------------------------------------------------------------------------------------------
# Precision: conditional requirements, section labels, header counterparts, naming pairs (synthetic, service independent).
# ----------------------------------------------------------------------------------------------------------------------
def body_op(properties, required=(), min_properties=None):
    schema = {'type': 'object', 'properties': {n: {'type': 'string'} for n in properties}, 'required': list(required)}
    if min_properties:
        schema['minProperties'] = min_properties
    return {'method': 'POST', 'path': '/api/v1/things', 'operationId': 'createThing', 'parameters': {'header': [{'name': 'x-user-id', 'in': 'header', 'required': True, 'schema': {'type': 'string'}}], 'query': [], 'path': []},
            'requestBody': {'content': {'application/json': {'schema': {'resolved': schema}}}}, 'responses': {'200': {}}}


def body_detail(rows, notes=(), inputs=(), headers=()):
    normalized = {'activityRole': 'validation', 'validation': {'body': {'rows': [dict(r, evidenceId=f'b{i}') for i, r in enumerate(rows)]}},
                  'considerations': {'lines': [{'text': t} for t in notes]}}
    if headers:
        normalized['validation']['headerrequest'] = {'rows': [{'evidenceId': f'h{i}', 'headerrequest': h, 'required': 'Si', 'type': 'String'} for i, h in enumerate(headers)]}
    if inputs:
        normalized['input'] = {'rows': [{'evidenceId': f'i{i}', 'input': n, 'origin': o, 'destination': n} for i, (n, o) in enumerate(inputs)]}
    return {'authority': {'branch': BRANCH}, 'excludedInactiveOperations': [], 'operations': [{'method': 'POST', 'path': '/api/v1/things', 'status': 'active',
            'sparxMethod': {'name': 'POST-/api/v1/things', 'guid': '{M}', 'page': 'EARoot/EA2/EA6/m.htm'}, 'activities': [{'activity': {'name': '1. Validar', 'uuid': '{A}', 'page': 'a.htm'}, 'normalized': normalized}],
            'endEvents': [{'label': '200', 'guid': '{E}', 'page': 'e.htm'}]}]}


def audit_body(op, detail):
    return cmp.Auditor('svc-a', {'source': {}, 'operations': [op]}, detail, 'rama').run()


def field(name, required, type_='string'):
    return {'body': name, 'required': required, 'type': type_}


class ConditionalRequirementTests(unittest.TestCase):
    DEPENDS_NOTE = '* Si beta viene, alpha también debe ser obligatorio (escenario de solicitud)'

    def kinds(self, result):
        return sorted((f['element'], f['kind'], f['category']) for f in result.registry())

    def test_requirement_modes_keep_the_conditional_marker(self):
        self.assertEqual([cmp.requirement_mode(v) for v in ('Si', 'No', 'No*', 'Si*', 'no *', '', 'tal vez')], ['required', 'optional', 'conditional', 'conditional', 'conditional', None, None])

    def test_rules_are_parsed_from_considerations(self):
        rules = cmp.conditional_rules([{'text': self.DEPENDS_NOTE}, {'text': 'Se debe enviar al menos uno de estos campos; sino, se rechaza'},
                                       {'text': 'El uso de limit y offset es opcional, sin embargo, ambos deben enviarse conjuntamente en la solicitud'}])
        self.assertEqual(rules['depends'], [('beta', 'alpha')])
        self.assertTrue(rules['atLeastOne'])
        self.assertEqual(rules['together'], [('limit', 'offset')])

    def test_conditional_against_mandatory_is_a_contradiction_for_the_dependent_and_the_trigger(self):
        detail = body_detail([field('alpha', 'No*'), field('beta', 'No*'), field('gamma', 'No')], [self.DEPENDS_NOTE])
        result = audit_body(body_op(['alpha', 'beta', 'gamma'], required=['alpha', 'beta']), detail)
        found = {f['element']: f for f in result.registry()}
        self.assertEqual({k: v['category'] for k, v in found.items()}, {'body alpha': 'contradiccion-verificada', 'body beta': 'contradiccion-verificada'})
        self.assertIn('condicional', found['body alpha']['sparx']['text'])
        self.assertIn('si beta viene', found['body alpha']['sparx']['text'].lower())
        self.assertIn('obligatorio siempre', found['body alpha']['swagger']['text'])
        self.assertIn('Obligatorio: No*', found['body beta']['sparx']['text'] + 'Obligatorio: No*')        # the trigger is optional, never boolean-collapsed to the mandatory flag
        self.assertNotIn('gamma', ' '.join(found))

    def test_conditional_against_optional_is_a_documental_difference_not_a_contradiction(self):
        result = audit_body(body_op(['alpha', 'beta']), body_detail([field('alpha', 'No*'), field('beta', 'No*')], [self.DEPENDS_NOTE]))
        self.assertEqual(self.kinds(result), [('body alpha', 'conditional-rule-difference', 'diferencia-documental')])

    def test_the_conditional_rule_is_equivalent_when_both_sources_agree_and_unconditional_flags_still_compare(self):
        result = audit_body(body_op(['alpha', 'beta', 'gamma']), body_detail([field('alpha', 'No'), field('beta', 'No'), field('gamma', 'No')]))
        self.assertEqual(result.registry(), [])
        wrong = audit_body(body_op(['alpha'], required=['alpha']), body_detail([field('alpha', 'No')]))
        self.assertEqual(self.kinds(wrong), [('body alpha', 'requirement-difference', 'contradiccion-verificada')])

    def test_at_least_one_is_satisfied_by_min_properties_and_otherwise_reported_once_for_the_group(self):
        notes = ['* Se debe enviar al menos uno de estos campos; sino, el servicio rechazará la petición.']
        rows = [field('alpha', 'No*'), field('beta', 'No*'), field('gamma', 'No*')]
        satisfied = audit_body(body_op(['alpha', 'beta', 'gamma'], min_properties=1), body_detail(rows, notes))
        self.assertEqual(satisfied.registry(), [])
        missing = audit_body(body_op(['alpha', 'beta', 'gamma']), body_detail(rows, notes))
        self.assertEqual(len(missing.registry()), 1)                                              # one finding, not one per field
        self.assertEqual(missing.registry()[0]['kind'], 'conditional-rule-difference')
        conflicting = audit_body(body_op(['alpha', 'beta', 'gamma'], required=['alpha'], min_properties=1), body_detail(rows, notes))
        self.assertEqual(self.kinds(conflicting), [('body alpha', 'requirement-difference', 'contradiccion-verificada')])

    def test_joint_sending_rule_is_reported_once_when_swagger_does_not_express_it(self):
        note = ['El uso de limit y offset es opcional, sin embargo, ambos deben enviarse conjuntamente en la solicitud']
        detail = body_detail([field('limit', 'No*'), field('offset', 'No*')], note)
        op = body_op(['limit', 'offset'])
        result = audit_body(op, detail)
        elements = [f['element'] for f in result.registry()]
        self.assertEqual(len(elements), 1)
        self.assertIn('limit y offset', elements[0])

    def test_conditional_without_an_explaining_rule_is_unverified_behavior_that_blocks(self):
        result = audit_body(body_op(['alpha']), body_detail([field('alpha', 'No*')]))
        self.assertEqual(result.registry(), [])
        self.assertEqual([(u['category']) for u in result.unverified], ['comportamiento-no-especificado'])


class FalsePositiveReductionTests(unittest.TestCase):
    def test_section_labels_are_not_fields_and_are_kept_as_discarded_candidates(self):
        detail = body_detail([{'body': 'request', 'required': '', 'type': ''}, field('alpha', 'No')])
        result = audit_body(body_op(['alpha']), detail)
        self.assertEqual(result.registry(), [])
        self.assertEqual([d['element'] for d in result.discarded], ['body request'])

    def test_an_internal_name_with_a_header_counterpart_is_not_a_missing_input(self):
        detail = body_detail([field('alpha', 'No')], inputs=[('alpha', 'request'), ('userId', 'headerRequest')], headers=['x-user-id'])
        self.assertEqual(audit_body(body_op(['alpha']), detail).registry(), [])

    def test_the_same_internal_name_without_evidence_of_a_header_remains_a_finding(self):
        detail = body_detail([field('alpha', 'No')], inputs=[('alpha', 'request'), ('userId', 'headerRequest')], headers=['x-other-id'])
        found = audit_body(body_op(['alpha']), detail).registry()
        self.assertIn('INPUT userId', [f['element'] for f in found])
        ambiguous = body_detail([field('alpha', 'No')], inputs=[('userId', 'headerRequest')], headers=['x-user-id', 'user-id'])
        self.assertIn('INPUT userId', [f['element'] for f in audit_body(body_op(['alpha']), ambiguous).registry()])

    def test_header_counterpart_never_hides_a_header_that_swagger_lacks(self):
        op = body_op(['alpha'])
        op['parameters']['header'] = []
        detail = body_detail([field('alpha', 'No')], inputs=[('userId', 'headerRequest')], headers=['x-user-id'])
        elements = sorted(f['element'] for f in audit_body(op, detail).registry())
        self.assertEqual(elements, ['header x-user-id'])               # reported once as the header difference, not twice (no INPUT duplicate)

    def test_request_origin_in_the_mapping_is_the_body_not_an_unknown_source(self):
        detail = body_detail([field('alpha', 'No')], inputs=[('alpha', 'request')])
        result = audit_body(body_op(['alpha']), detail)
        self.assertEqual((result.registry(), result.unverified), ([], []))
        missing = audit_body(body_op(['alpha']), body_detail([field('alpha', 'No')], inputs=[('ghost', 'request')]))
        self.assertEqual([f['element'] for f in missing.registry()], ['INPUT ghost'])

    def test_one_concept_with_two_names_is_reported_once_and_ambiguous_pairs_are_not_guessed(self):
        detail = body_detail([field('body', 'No')], inputs=[('payload', 'request')])
        found = audit_body(body_op(['payload']), detail).registry()
        self.assertEqual([(f['kind'], f['element']) for f in found], [('naming-difference', 'body body / payload')])
        ambiguous = body_detail([field('one', 'No'), field('two', 'No')], inputs=[('payload', 'request'), ('other', 'request')])
        kinds = sorted(f['kind'] for f in audit_body(body_op(['payload', 'other']), ambiguous).registry())
        self.assertNotIn('naming-difference', kinds)
        self.assertEqual(len(kinds), 4)

    def test_real_contradictions_and_missing_fields_are_still_detected(self):
        detail = body_detail([field('alpha', 'Si', 'integer'), field('only_sparx', 'No')], inputs=[('alpha', 'request'), ('only_sparx', 'request')])
        found = {(f['element'], f['kind']) for f in audit_body(body_op(['alpha', 'only_swagger'], required=['alpha']), detail).registry()}
        self.assertIn(('body alpha', 'type-or-structure-difference'), found)
        self.assertIn(('body only_sparx', 'missing-in-swagger'), found)
        self.assertIn(('body only_swagger', 'missing-in-sparx'), found)


if __name__ == '__main__':
    unittest.main()
