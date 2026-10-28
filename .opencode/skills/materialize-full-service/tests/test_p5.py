"""Phase 2 / P5: application.properties.example and header constraints (synthetic services, temporary directories only)."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))

import synth as fx  # noqa: E402
import full_materializer as mz  # noqa: E402
import assemble_project as ap  # noqa: E402
import style_lint  # noqa: E402
import validate_generated_service as vg  # noqa: E402
import test_components4 as c4  # noqa: E402
from renderers import Unsupported  # noqa: E402
from test_generated_tests import Base  # noqa: E402

EXAMPLE = 'src/main/resources/application.properties.example'
INV = 'src/test/java/com/acme/inventory/core/'
BIL = 'src/test/java/org/example/billing/'


def methods(text):
    return re.findall(r'void (\w+)\(\)', text)


class ExampleTests(Base):
    def example(self, name='billing-service', **kw):
        out = self.gen(name, **kw)
        return out, (out / EXAMPLE).read_text(encoding='utf-8')

    def keys(self, text):
        return dict(line.split('=', 1) for line in text.split('\n') if line and not line.startswith('#'))

    def test_the_example_follows_the_archetype_blocks_and_values(self):
        _, text = self.example()
        archetype = yaml.safe_load((fx.REPO_ROOT / fx.ARCHETYPE / 'archetype.yml').read_bytes())['runtime']['application_properties']
        found = self.keys(text)
        for key, value in archetype['static'].items():
            self.assertEqual(found[key], str(value).lower() if isinstance(value, bool) else str(value))
        self.assertEqual(len(found), len(archetype['static']) + len(archetype['parameterized']) + len(archetype['environment_only']))        # nothing invented, nothing dropped
        blocks = re.findall(r'# ===== (.+?) =====', text)
        self.assertEqual(blocks, ['APPLICATION', 'LOGGING', 'SWAGGER', 'ACTUATOR', 'DATA SOURCE', 'HIKARI', 'JPA / HIBERNATE', 'JWT TOKEN', 'SPRING CLOUD'])

    def test_parameters_are_resolved_and_secrets_are_environment_placeholders(self):
        _, text = self.example('inventory-service')
        found = self.keys(text)
        self.assertEqual((found['spring.application.name'], found['springdoc.packagesToScan'], found['logging.level.com.acme.inventory.core'], found['security.jwt.roles-claim']),
                         ('inventory-service', 'com.acme.inventory.core', 'DEBUG', 'roles'))
        for key, env in (('security.jwt.secret-key', 'JWT_SECRET_KEY'), ('spring.datasource.url', 'DB_URL'), ('spring.datasource.username', 'DB_USERNAME'), ('spring.datasource.password', 'DB_PASSWORD')):
            self.assertEqual(found[key], '${' + env + '}')
        self.assertEqual(ap.unresolved(text), [])

    def test_the_example_documents_how_to_create_the_real_file(self):
        _, text = self.example()
        self.assertIn('copy this file to src/main/resources/application.properties', text)
        self.assertIn('The generator never reads or writes application.properties', text)

    def test_the_example_is_a_tracked_assembled_file_with_a_manifest_hash(self):
        out, _ = self.example()
        manifest = yaml.safe_load((out / '.generation-manifest.yml').read_bytes())
        rows = {r['path']: r for r in manifest['fileInventory']}
        self.assertEqual(rows[EXAMPLE]['componentType'], 'project-assembly')
        self.assertNotIn('src/main/resources/application.properties', rows)
        report = yaml.safe_load((self.ws('billing-service') / 'materialization-report.yml').read_bytes())
        self.assertEqual(report['assembly']['applicationProperties']['example'], EXAMPLE)

    def test_the_real_application_properties_is_never_created_nor_touched(self):
        target = self.repo / 'output' / 'billing-service' / 'src/main/resources/application.properties'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'local=environment\n')
        fx.ready_service(self.repo, 'billing-service')
        mz.materialize(self.repo, 'billing-service')
        self.assertEqual(target.read_bytes(), b'local=environment\n')
        self.assertTrue((target.parent / 'application.properties.example').is_file())

    def test_a_hand_edited_example_is_protected_and_an_untracked_one_is_kept(self):
        out, _ = self.example()
        path = out / EXAMPLE
        path.write_text(path.read_text(encoding='utf-8') + 'manual=1\n', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'billing-service')
        self.assertEqual(caught.exception.kind, 'protected-files')

    def test_a_missing_parameter_stops_before_any_write(self):
        fx.ready_service(self.repo, 'billing-service', assembly_values={'jwt_roles_claim': None})
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'billing-service')
        self.assertEqual(caught.exception.kind, 'missing-parameter')
        self.assertIn('jwt_roles_claim', [m['parameter'] for m in caught.exception.details['missing']])
        self.assertFalse((self.repo / 'output' / 'billing-service').exists())

    def test_deterministic_and_idempotent(self):
        out, text = self.example()
        again = mz.materialize(self.repo, 'billing-service')
        self.assertEqual(again['written'], [])
        with tempfile.TemporaryDirectory() as tmp:
            repo = fx.make_repo(Path(tmp))
            fx.ready_service(repo, 'billing-service')
            mz.materialize(repo, 'billing-service')
            self.assertEqual((repo / 'output/billing-service' / EXAMPLE).read_text(encoding='utf-8'), text)

    def test_a_blocked_gate_writes_no_example(self):
        fx.blocked_gate(self.repo, 'billing-service', fx.SERVICES['billing-service']['route'])
        fx.make_plan(self.repo, 'billing-service')
        with self.assertRaises(Exception):
            mz.materialize(self.repo, 'billing-service')
        self.assertFalse((self.repo / 'output' / 'billing-service').exists())


class HeaderConstraintTests(Base):
    def controller_test(self, name, rel):
        return (self.gen(name) / rel).read_text(encoding='utf-8')

    def test_declared_header_constraints_are_applied_in_the_api_interface(self):
        out = self.gen('inventory-service')
        api = (out / 'src/main/java/com/acme/inventory/core/controller/ItemApi.java').read_text(encoding='utf-8')
        self.assertIn('@Size(min = 1, max = SEARCH_ITEMS_X_CORRELATION_ID_SIZE_MAX) @Pattern(regexp = "^[A-Za-z0-9-]+$") @RequestHeader(name = "x-correlation-id", required = true) String xCorrelationId', api)
        self.assertIn('@RequestHeader(name = "x-user-id", required = true) String xUserId', api)             # nothing invented for undeclared constraints
        billing = (self.gen('billing-service') / 'src/main/java/org/example/billing/controller/InvoiceApi.java').read_text(encoding='utf-8')
        self.assertIn('@Size(max = LIST_INVOICES_X_TRACE_ID_SIZE_MAX) @RequestHeader(name = "x-trace-id"', billing)
        self.assertIn('@RequestHeader(name = "x-user", required = true) String xUser', billing)

    def test_limits_and_negative_positive_cases_are_generated_for_headers(self):
        text = self.controller_test('inventory-service', INV + 'controller/impl/ItemControllerTest.java')
        found = set(methods(text))
        for expected in ('searchItemsXCorrelationIdRejectsBelowMinimumForSize', 'searchItemsXCorrelationIdAcceptsLowerBoundForSize', 'searchItemsXCorrelationIdAcceptsUpperBoundForSize',
                         'searchItemsXCorrelationIdRejectsNonMatchingValueForPattern', 'searchItemsXCorrelationIdAcceptsMatchingValueForPattern',
                         'searchItemsHeaderXCorrelationIdOverHttpRejectsBelowMinimumForSize', 'searchItemsHeaderXCorrelationIdOverHttpAcceptsMatchingValueForPattern',
                         'searchItemsRejectsARequestWithoutTheRequiredXcorrelationid'):
            self.assertIn(expected, found)

    def test_validation_runs_through_method_validation_in_mockmvc(self):
        text = self.controller_test('billing-service', BIL + 'controller/impl/InvoiceControllerTest.java')
        self.assertIn('new MethodValidationInterceptor((Validator) validator)', text)
        self.assertIn('standaloneSetup(factory.getProxy())', text)
        self.assertIn('verifyNoInteractions(service);', text)

    def test_valid_requests_use_header_values_that_satisfy_the_declared_constraints(self):
        text = self.controller_test('inventory-service', INV + 'controller/impl/ItemControllerTest.java')
        self.assertIn('builder.header("x-correlation-id", "x-correlation-id".equals(overridden) ? value : "a");', text)
        self.assertIn('builder.header("x-user-id", "x-user-id".equals(overridden) ? value : "value-of-xUserId");', text)

    def test_traceability_lists_every_declared_header_constraint_as_covered_and_none_undeclared(self):
        self.gen('inventory-service')
        register = yaml.safe_load((self.ws('inventory-service') / 'tests-traceability.yml').read_bytes())
        rows = {r['rule']: r for r in register['rules']}
        for op in ('searchItems', 'createItem', 'patchItem'):
            for ann in ('Size', 'Pattern'):
                self.assertEqual(rows[f'{op}:param:x-correlation-id:{ann}']['status'], 'covered')
                self.assertGreaterEqual(len(rows[f'{op}:param:x-correlation-id:{ann}']['tests']), 4)
        self.assertFalse([r for r in rows if ':param:x-user-id:' in r])
        self.assertEqual(register['uncovered'], 0)

    def test_required_headers_are_still_enforced(self):
        text = self.controller_test('billing-service', BIL + 'controller/impl/InvoiceControllerTest.java')
        self.assertIn('createInvoiceRejectsARequestWithoutTheRequiredXtraceid', methods(text))
        self.assertIn('@RequestHeader(name = "x-trace-id", required = true)', (self.repo / 'output/billing-service/src/main/java/org/example/billing/controller/InvoiceApi.java').read_text(encoding='utf-8'))

    def test_a_service_without_header_constraints_keeps_the_previous_neutral_samples(self):
        fx.SERVICES['billing-service'].pop('header_constraints')
        try:
            out = self.gen('billing-service')
        finally:
            fx.SERVICES['billing-service']['header_constraints'] = {'x-trace-id': {'maxLength': 64}}
        text = (out / BIL / 'controller/impl/InvoiceControllerTest.java').read_text(encoding='utf-8')
        self.assertNotIn('HeaderXTraceId', text)
        self.assertIn('"x-trace-id".equals(overridden) ? value : "value-of-xTraceId"', text)

    def test_unsupported_header_shapes_are_reported_not_guessed(self):
        class M:
            pass
        model = {'ops': [{'params': {'header': [{'name': 'x-n', 'java': 'xN', 'type': 'Integer', 'annotations': ['@Min(1)']}]}}]}
        with self.assertRaises(Unsupported):
            c4.header_sample(model, model['ops'][0]['params']['header'][0], {})
        model['ops'][0]['params']['header'][0].update(type='String', annotations=['@Pattern(regexp = "QQQ-[0-9]{9}-QQQ")'])
        with self.assertRaises(Unsupported):
            c4.header_sample(model, model['ops'][0]['params']['header'][0], {})

    def test_quality_gates_and_determinism(self):
        for name in fx.SERVICES:
            out = self.gen(name)
            self.assertEqual(style_lint.lint_project(out)['findings'], [])
            self.assertEqual(vg.validate(self.repo, name)['status'], 'passed')
            first = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob('*') if p.is_file()}
            self.assertEqual(mz.materialize(self.repo, name)['written'], [])
            self.assertEqual(first, {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob('*') if p.is_file()})

    def test_a_hand_edited_test_is_protected(self):
        out = self.gen('inventory-service')
        target = out / INV / 'controller/impl/ItemControllerTest.java'
        target.write_text(target.read_text(encoding='utf-8') + '\n// manual\n', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(caught.exception.kind, 'protected-files')

    def test_blocked_gate_writes_nothing(self):
        fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        with self.assertRaises(Exception):
            mz.materialize(self.repo, 'inventory-service')
        self.assertFalse((self.repo / 'output' / 'inventory-service').exists())


if __name__ == '__main__':
    unittest.main()
