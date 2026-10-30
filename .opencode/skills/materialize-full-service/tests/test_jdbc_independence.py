"""Synthetic unrelated services only; no reference, Maven or remote access."""
import copy
import json
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / '.opencode/skills/plan-service-implementation/scripts'))
sys.path.insert(0, str(REPO / '.opencode/skills/materialize-full-service/scripts'))
import jdbc_contract as contract
import jdbc_war_plan as planner
import jdbc_war_materializer as renderer


def obj(name, properties):
    return {'source': {'$ref': '#/components/schemas/' + name}, 'resolved': {'type': 'object', 'properties': properties}}


class JdbcIndependenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.arch = 'archetypes/claro-spring-java-8/v1.0.0'
        shutil.copytree(REPO / self.arch, self.root / self.arch, ignore=shutil.ignore_patterns('__pycache__'))

    def fixture(self, domain='Stock', code='SAVED'):
        service = domain.lower() + '-service'
        ws = self.root / '.factory/services' / service
        ws.mkdir(parents=True, exist_ok=True)
        oid = 'lookup' + domain
        request = obj(domain + 'Request', {'key': {'type': 'string'}})
        row = obj(domain + 'Item', {'label': {'type': 'string'}, 'count': {'type': 'integer'}})
        response = obj(domain + 'Response', {
            'responseAudit': obj(domain + 'Audit', {k: {'type': 'string'} for k in ('codigoRespuesta', 'mensajeRespuesta', 'idTransaccion')}),
            'responseData': obj(domain + 'Data', {'item': row})})
        procedure = {'name': domain.upper() + '_PKG.READ_ITEM',
            'inputs': [{'parameter': 'IN_KEY', 'source': 'key', 'origin': 'request', 'javaType': 'String'}],
            'codeOutput': 'OUT_CODE', 'messageOutput': 'OUT_TEXT', 'cursor': 'OUT_ROWS', 'columns': ['DISPLAY_NAME', 'TOTAL'],
            'rowTarget': {'property': 'item', 'many': False, 'wrapperProperty': None, 'rowClass': domain + 'Item', 'listItemClass': None},
            'columnMapping': [{'field': 'label', 'column': 'DISPLAY_NAME', 'javaType': 'String'}, {'field': 'count', 'column': 'TOTAL', 'javaType': 'Integer'}],
            'singleRowOnly': True, 'parameterOrder': ['IN_KEY', 'OUT_CODE', 'OUT_TEXT', 'OUT_ROWS'], 'successCode': code,
            'requireRows': True, 'unmappedFields': [], 'outputSqlType': 'VARCHAR', 'exceptionPolicy': 'sql-timeout-otherwise-unavailable'}
        binding = {'version': 1, 'evidence': ['sparx:' + domain + '#procedure-and-mapping'],
            'policies': {'validation': 'required-query-nonempty', 'absentBody': 'empty-request', 'successMessage': 'procedure-message',
                         'invalidParameterPlaceholder': '[PARAMETROS]', 'procedureMessagePlaceholder': '[PO_MSG_RESPUESTA(Act.2.0)]'},
            'envelope': {'audit': 'responseAudit', 'data': 'responseData', 'code': 'codigoRespuesta', 'message': 'mensajeRespuesta', 'transaction': 'idTransaccion'},
            'activities': {'validate': 'Validate ' + domain, 'persist': 'Read ' + domain}, 'procedure': procedure,
            'outcomes': {'success': domain + '_OK', **{key: {'code': domain + '_' + key, 'message': domain + ' ' + key + ' [PARAMETROS]'}
                         for key in ('invalidParameters', 'procedureFailure', 'timeout', 'unavailable')}}}
        operation = {'operationId': oid, 'method': 'POST', 'path': '/' + domain.lower() + '/lookup', 'jdbcBinding': binding,
            'behavior': {'actions': [{'implementationComplete': True, 'persistence': {'operation': procedure['name']}}]},
            'contract': {'parameters': {'query': [{'name': 'idTransaccion', 'required': True, 'schema': {'type': 'string'}}]},
                         'requestBody': {'content': {'application/json': {'schema': request}}},
                         'responses': {'200': {'content': {'application/json': {'schema': response}}}}}}
        spec = {'service': {'name': service}, 'operations': [operation],
                'readiness': {'functionalCodeGenerationReady': True, 'strictImplementationReady': True}}
        cfg = {'target': {'service': service, 'archetype': self.arch, 'output_directory': 'output/' + service,
                         'base_package': 'org.example.' + domain.lower(), 'group_id': 'org.example', 'project_version': '1.0.0'},
               'technical': {'jdbcNames': {'dao': domain + 'Dao', 'repository': domain + 'Repository', 'service': domain + 'Service', 'controller': domain + 'Controller'}},
               'template_parameters': {'CONFIG_ROOT_PROPERTY': 'example.config', 'CONFIG_SUBDIRECTORY': service,
                   'LOG_DIRECTORY': '/logs/' + service, 'CONTEXT_ROOT': service, 'CORPORATE_REPOSITORY_URL': 'https://example.invalid/releases/'}}
        self.write(ws, spec, cfg)
        return ws, spec, cfg

    def write(self, ws, spec, cfg):
        (ws / 'service-spec.yml').write_text(yaml.safe_dump(spec, sort_keys=False), encoding='utf-8')
        (ws / 'full-planning-input.yml').write_text(yaml.safe_dump(cfg, sort_keys=False), encoding='utf-8')

    def plan(self, ws):
        planner.write_plan(self.root, yaml, (ws / 'full-planning-input.yml').relative_to(self.root))
        return yaml.safe_load((ws / 'implementation-plan.yml').read_text(encoding='utf-8'))

    def materialize_fixture(self, ws, **kwargs):
        import full_materializer as fm
        (ws / 'service-generation-state.yml').write_text(yaml.safe_dump({
            'targetService': ws.name, 'archetype': {'path': self.arch}}))
        # Control tests only: gate functionality is tested separately with live
        # synthetic evidence. Never approve a real service here.
        with patch.object(fm.gate, 'check_cleared'):
            return fm.materialize(self.root, ws.name, **kwargs)

    def test_publication_is_idempotent_and_protects_identical_user_owned_files(self):
        import full_materializer as fm
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        self.materialize_fixture(ws)
        output = self.root / 'output' / ws.name
        manifest = (output / fm.MANIFEST).read_bytes()
        report = self.materialize_fixture(ws)
        self.assertEqual([], report['written'])
        self.assertEqual(manifest, (output / fm.MANIFEST).read_bytes())
        path = plan['files']['generate'][0]['path']
        (ws / 'user-owned-files.yml').write_text(yaml.safe_dump({'patterns': [path]}))
        with self.assertRaises(fm.MaterializationError) as result:
            self.materialize_fixture(ws)
        self.assertEqual('protected-files', result.exception.kind)
        self.assertEqual(manifest, (output / fm.MANIFEST).read_bytes())

    def test_tampered_plan_is_recomputed_before_any_publication(self):
        import full_materializer as fm
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        plan['operations'][0]['outcomes']['success'] = 'INVENTED'
        (ws / 'implementation-plan.yml').write_text(yaml.safe_dump(plan))
        with self.assertRaisesRegex(fm.MaterializationError, 'differ from current authorized inputs'):
            self.materialize_fixture(ws)
        self.assertFalse((self.root / 'output' / ws.name).exists())

    def test_technical_configuration_must_be_in_exact_inventory(self):
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        self.assertIn('pom.xml', {e['path'] for e in plan['files']['generate']})
        plan['files']['generate'] = [e for e in plan['files']['generate'] if e['path'] != 'pom.xml']
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            renderer.render_project(plan, self.root)

    def test_undeclared_and_protected_template_files_are_never_read_or_copied(self):
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        template = self.root / self.arch / 'template'
        extra = template / 'local-not-in-inventory.txt'
        extra.write_text('private local content')
        protected = template / 'src/main/resources/application-local.properties'
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_text('synthetic-secret')
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path in (extra, protected):
                raise AssertionError('unowned/protected template was read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            payload = renderer.render_project(plan, self.root)
        self.assertNotIn(extra.name, payload)
        self.assertNotIn('src/main/resources/application-local.properties', payload)

    def test_two_domains_render_without_target_decisions_or_names(self):
        for domain, other, code in [('Stock', 'Invoice', 'SAVED'), ('Invoice', 'Stock', 'ACCEPTED')]:
            ws, _, _ = self.fixture(domain, code)
            plan = self.plan(ws)
            payload = renderer.render_project(plan, self.root)
            text = '\n'.join(v[1] for v in payload.values())
            self.assertNotIn(other, text)
            for foreign in ('Atencion', 'consultarCodigoAtencion', 'PKG_TXRNOTIF', 'EA550', 'D-G', 'D-F'):
                self.assertNotIn(foreign, text)
                self.assertNotIn(foreign, json.dumps(plan))
            self.assertIn('class ' + domain + 'Service', text)
            self.assertIn('interface ' + domain + 'Dao', text)
            self.assertIn('getCodigo())', text)
            self.assertIn(code, text)
            self.assertIn('getLabel()', text)
            self.assertIn('DISPLAY_NAME', text)
            self.assertEqual([], plan['assumptions'])
            self.assertEqual(payload, renderer.render_project(plan, self.root))

    def test_missing_binding_fails_without_plan(self):
        ws, spec, cfg = self.fixture()
        spec['operations'][0].pop('jdbcBinding')
        self.write(ws, spec, cfg)
        with self.assertRaisesRegex(contract.JdbcContractError, 'jdbcBinding'):
            self.plan(ws)
        self.assertFalse((ws / 'implementation-plan.yml').exists())
        self.assertFalse((ws / 'generation-parameters.yml').exists())

    def test_names_are_not_defaults(self):
        ws, spec, cfg = self.fixture()
        cfg.pop('technical')
        self.write(ws, spec, cfg)
        with self.assertRaisesRegex(contract.JdbcContractError, 'jdbcNames'):
            self.plan(ws)

    def test_order_cannot_be_inferred(self):
        ws, spec, cfg = self.fixture()
        spec['operations'][0]['jdbcBinding']['procedure']['parameterOrder'].reverse()
        self.write(ws, spec, cfg)
        with self.assertRaisesRegex(contract.JdbcContractError, 'positional order'):
            self.plan(ws)

    def test_partial_operations_do_not_get_target_specific_stub(self):
        ws, spec, cfg = self.fixture()
        spec['readiness']['incompleteOperations'] = [{'operationId': 'somethingElse'}]
        self.write(ws, spec, cfg)
        with self.assertRaisesRegex(Exception, 'incomplete operations'):
            self.plan(ws)

    def test_only_explicit_columns_not_name_prefixes_are_used(self):
        ws, spec, cfg = self.fixture()
        p = spec['operations'][0]['jdbcBinding']['procedure']
        p['columnMapping'][0]['column'] = 'LABEL'
        self.write(ws, spec, cfg)
        with self.assertRaisesRegex(contract.JdbcContractError, 'column mapping'):
            self.plan(ws)

    def test_response_codes_are_not_defaulted(self):
        ws, spec, cfg = self.fixture()
        spec['operations'][0]['jdbcBinding']['outcomes'].pop('timeout')
        self.write(ws, spec, cfg)
        with self.assertRaisesRegex(contract.JdbcContractError, 'outcomes'):
            self.plan(ws)

    def test_schema_signature_includes_types_not_just_property_names(self):
        models = planner.Models()
        self.assertNotEqual(models.signature({'properties': {'value': {'type': 'string'}}}),
                            models.signature({'properties': {'value': {'type': 'integer'}}}))

    def test_legacy_inferred_plan_is_explicitly_unsupported(self):
        ws, _, _ = self.fixture()
        plan = self.plan(ws)
        plan['plan'].pop('jdbcBindingVersion')
        with self.assertRaisesRegex(ValueError, 'legacy inferred plans'):
            renderer.render_project(plan, self.root)

    def test_header_mapping_uses_declared_source_not_always_userid(self):
        ws, spec, cfg = self.fixture()
        p = spec['operations'][0]['jdbcBinding']['procedure']
        p['inputs'][0].update(source='idTransaccion', origin='header')
        self.write(ws, spec, cfg)
        payload = renderer.render_project(self.plan(ws), self.root)
        service = next(text for path, (_, text) in payload.items() if path.endswith('/StockService.java'))
        self.assertIn('cabecera.getIdTransaccion(), cabecera.getIdTransaccion()', service)
        self.assertNotIn('cabecera.getUserId()', service)

    def test_unknown_constraints_fail_instead_of_being_ignored(self):
        ws, spec, cfg = self.fixture()
        spec['operations'][0]['contract']['requestBody']['content']['application/json']['schema']['resolved']['properties']['key']['minLength'] = 3
        self.write(ws, spec, cfg)
        with self.assertRaisesRegex(Exception, 'unsupported schema constraints'):
            self.plan(ws)

    def test_two_operations_do_not_share_response_codes_or_owner(self):
        ws, spec, cfg = self.fixture()
        second = copy.deepcopy(spec['operations'][0])
        second['operationId'] = 'lookupOther'
        second['path'] = '/other'
        second['jdbcBinding']['outcomes']['success'] = 'OTHER_OK'
        second['jdbcBinding']['outcomes']['timeout'] = {'code': 'OTHER_TIMEOUT', 'message': 'Other timeout'}
        second['jdbcBinding']['procedure']['name'] = 'OTHER_OWNER.OTHER_PKG.READ_ITEM'
        second['behavior']['actions'][0]['persistence']['operation'] = 'OTHER_OWNER.OTHER_PKG.READ_ITEM'
        spec['operations'].append(second)
        self.write(ws, spec, cfg)
        plan = self.plan(ws)
        ctx = renderer.Ctx(plan, self.root)
        self.assertNotEqual(ctx.P['lookupStock']['ok'], ctx.P['lookupOther']['ok'])
        self.assertNotEqual(ctx.P['lookupStock']['to_code'], ctx.P['lookupOther']['to_code'])
        self.assertIsNone(ctx.P['lookupStock']['owner'])
        self.assertEqual('OTHER_OWNER', ctx.props['bd.jdbc.lookupOther.owner']['suggestedValue'])

    def test_two_domains_parse_as_java8_without_resolving_dependencies(self):
        javac, java = shutil.which('javac'), shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK unavailable; syntax unverified')
        sources = []
        for domain in ('Stock', 'Invoice'):
            ws, _, _ = self.fixture(domain)
            for path, (_, text) in renderer.render_project(self.plan(ws), self.root).items():
                if path.endswith('.java'):
                    dest = self.root / domain / path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(text, encoding='utf-8')
                    sources.append(str(dest))
        helper = self.root / 'SyntaxCheck.java'
        helper.write_text('''import java.util.Arrays;
import javax.tools.*;
import com.sun.source.util.JavacTask;
public class SyntaxCheck {
  public static void main(String[] args) throws Exception {
    JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
    DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
    try (StandardJavaFileManager manager = compiler.getStandardFileManager(diagnostics, null, null)) {
      JavacTask task = (JavacTask) compiler.getTask(null, manager, diagnostics,
          Arrays.asList("-proc:none", "-source", "8", "-encoding", "UTF-8"), null,
          manager.getJavaFileObjectsFromStrings(Arrays.asList(args)));
      task.parse();
      for (Diagnostic<? extends JavaFileObject> d : diagnostics.getDiagnostics()) {
        if (d.getKind() == Diagnostic.Kind.ERROR) throw new AssertionError(d.toString());
      }
    }
  }
}
''', encoding='utf-8')
        result = subprocess.run([javac, '-d', str(self.root), str(helper)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        result = subprocess.run([java, '-cp', str(self.root), 'SyntaxCheck', *sources], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
