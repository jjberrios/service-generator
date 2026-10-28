"""Phase 2 / P3: parameter-constraint tests, injectable Clock, coverage and risk reporting (synthetic services, temporary directories only)."""
import re
import sys
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))

import synth as fx  # noqa: E402
import full_materializer as mz  # noqa: E402
import validate_generated_service as vg  # noqa: E402
import test_support as ts  # noqa: E402
import test_components4 as c4  # noqa: E402
import java_components as jc  # noqa: E402
from test_generated_tests import Base  # noqa: E402

INV = 'src/test/java/com/acme/inventory/core/'
BIL = 'src/test/java/org/example/billing/'


def methods(text):
    return re.findall(r'void (\w+)\(\)', text)


class ConstraintParsingTests(unittest.TestCase):
    def test_declared_annotations_are_parsed_without_inventing_any(self):
        parsed = c4.parse(['@Size(min = 2, max = 40)', '@Pattern(regexp = "^[0-9]\\\\d+$")', '@Min(5)', '@NotNull', '@Unknown'])
        self.assertEqual(parsed[0], ('Size', {'min': 2, 'max': 40}))
        self.assertEqual(parsed[1][1]['regexp'], '^[0-9]\\d+$')
        self.assertEqual(parsed[2], ('Min', {'value': 5}))
        self.assertEqual([n for n, _ in parsed], ['Size', 'Pattern', 'Min', 'NotNull', 'Unknown'])
        self.assertEqual(c4.parse([]), [])

    def test_numeric_boundaries_are_exactly_on_and_beyond_the_declared_limit(self):
        cases, reasons = c4.numeric_cases('Integer', c4.parse(['@Min(3)', '@Max(9)']))
        self.assertEqual(cases['Min'], [('boundary-value', 'valid', 'Integer.valueOf("3")'), ('beyond-boundary', 'invalid', 'Integer.valueOf("2")')])
        self.assertEqual(cases['Max'], [('boundary-value', 'valid', 'Integer.valueOf("9")'), ('beyond-boundary', 'invalid', 'Integer.valueOf("10")')])
        self.assertEqual(reasons, {})

    def test_size_boundaries_and_pattern_samples_respect_every_declared_constraint(self):
        consts = {}
        constraints = c4.parse(['@Size(min = 2, max = 5)', '@Pattern(regexp = "[a-z]+")'])
        cases, reasons = c4.string_cases(constraints, consts)
        rows = {(label, kind): expr for label, kind, expr in cases['Size']}
        self.assertEqual(rows[('lower-bound', 'valid')], '"aa"')
        self.assertEqual(rows[('upper-bound', 'valid')], '"aaaaa"')
        self.assertEqual(rows[('below-minimum', 'invalid')], '"a"')
        self.assertEqual(rows[('above-maximum', 'invalid')], '"aaaaaa"')
        self.assertEqual({k for _, k, _ in cases['Pattern']}, {'valid', 'invalid'})

    def test_a_pattern_without_a_derivable_sample_is_reported_not_guessed(self):
        cases, reasons = c4.string_cases(c4.parse(['@Pattern(regexp = "QQQ-[0-9]{9}-QQQ")']), {})
        self.assertIn('Pattern', reasons)
        self.assertEqual([k for _, k, _ in cases['Pattern']], ['invalid'])

    def test_long_values_use_a_named_length_constant(self):
        consts = {}
        cases, _ = c4.string_cases(c4.parse(['@Size(max = 300)']), consts)
        self.assertTrue(consts)
        self.assertTrue(any('.repeat(LENGTH_' in expr for _, _, expr in cases['Size']))

    def test_annotation_numbers_become_constants_only_when_checkstyle_would_flag_them(self):
        consts = {}
        self.assertEqual(jc.constantize('@Size(min = 1, max = 50)', 'F', consts), '@Size(min = 1, max = F_SIZE_MAX)')
        self.assertEqual(jc.constantize('@Min(0)', 'F', consts), '@Min(0)')
        self.assertEqual(jc.constantize('@Max(100)', 'G', consts), '@Max(G_MAX)')
        self.assertEqual(jc.constantize('@Pattern(regexp = "[0-9]{50}")', 'F', consts), '@Pattern(regexp = "[0-9]{50}")')
        self.assertEqual(sorted(consts), ['F_SIZE_MAX', 'G_MAX'])


class ParameterConstraintTestsGenerated(Base):
    def controller_text(self, name, rel):
        out = self.gen(name)
        return (out / rel).read_text(encoding='utf-8')

    def test_min_max_size_pattern_are_exercised_on_both_sides_of_the_limit(self):
        text = self.controller_text('inventory-service', INV + 'controller/impl/ItemControllerTest.java')
        found = set(methods(text))
        for expected in ('searchItemsLimitAcceptsBoundaryValueForMin', 'searchItemsLimitRejectsBeyondBoundaryForMin', 'searchItemsLimitAcceptsBoundaryValueForMax', 'searchItemsLimitRejectsBeyondBoundaryForMax',
                         'searchItemsNameAcceptsUpperBoundForSize', 'searchItemsNameRejectsAboveMaximumForSize', 'searchItemsStateAcceptsMatchingValueForPattern', 'searchItemsStateRejectsNonMatchingValueForPattern',
                         'patchItemIdRejectsBelowMinimumForSize', 'searchItemsAcceptsAbsentOptionalParameters'):
            self.assertIn(expected, found)
        self.assertIn('Integer.valueOf("101")', text)
        self.assertIn('Integer.valueOf("100")', text)
        self.assertIn('validateParameters(controller, method, arguments)', text)

    def test_request_body_constraints_run_through_bean_validation(self):
        text = self.controller_text('inventory-service', INV + 'controller/impl/ItemControllerTest.java')
        for expected in ('createItemBodyNameRejectsBelowMinimumForSize', 'createItemBodyNameAcceptsLowerBoundForSize', 'createItemBodyNameRejectsAboveMaximumForSize'):
            self.assertIn(expected, methods(text))
        billing = self.controller_text('billing-service', BIL + 'controller/impl/InvoiceControllerTest.java')
        for expected in ('createInvoiceBodyCustomerRejectsEmptyValueForNotblank', 'createInvoiceBodyCustomerRejectsBlankValueForNotblank', 'createInvoiceBodyCustomerAcceptsPresentValueForNotblank'):
            self.assertIn(expected, methods(billing))

    def test_pattern_and_size_combined_samples_pass_every_constraint(self):
        text = self.controller_text('billing-service', BIL + 'controller/impl/InvoiceControllerTest.java')
        self.assertIn('listInvoicesCustomerAcceptsLowerBoundForSize', methods(text))
        self.assertIn('listInvoicesCustomerAcceptsMatchingValueForPattern', methods(text))

    def test_no_constraint_is_invented_for_parameters_without_declared_constraints(self):
        text = self.controller_text('inventory-service', INV + 'controller/impl/ItemControllerTest.java')
        for undeclared in ('searchItemsNotes', 'searchItemsSku', 'searchItemsId'):
            self.assertFalse([m for m in methods(text) if m.startswith(undeclared) and ('Accepts' in m or 'Rejects' in m)], undeclared)
        register = yaml.safe_load((self.ws('inventory-service') / 'tests-traceability.yml').read_bytes())
        rules = {r['rule'] for r in register['rules']}
        self.assertFalse([r for r in rules if r.startswith('searchItems:param:notes')])
        self.assertTrue({'searchItems:param:limit:Min', 'searchItems:param:limit:Max', 'searchItems:param:name:Size', 'searchItems:param:state:Pattern', 'patchItem:param:id:Size', 'createItem:body:name:Size'} <= rules)

    def test_traceability_lists_every_constraint_as_covered(self):
        self.gen('inventory-service')
        register = yaml.safe_load((self.ws('inventory-service') / 'tests-traceability.yml').read_bytes())
        by_rule = {r['rule']: r for r in register['rules']}
        row = by_rule['searchItems:param:limit:Max']
        self.assertEqual(row['status'], 'covered')
        self.assertEqual(len(row['tests']), 2)
        self.assertEqual(register['schemaVersion'], 2)

    def test_the_generated_main_code_stays_within_the_declared_limits(self):
        out = self.gen('inventory-service')
        api = (out / 'src/main/java/com/acme/inventory/core/controller/ItemApi.java').read_text(encoding='utf-8')
        self.assertIn('public static final long SEARCH_ITEMS_LIMIT_MAX = 100;', api)
        self.assertIn('@Min(1) @Max(SEARCH_ITEMS_LIMIT_MAX)', api)


class ClockTests(Base):
    def service(self, name, rel):
        return (self.gen(name) / rel).read_text(encoding='utf-8')

    def test_dates_use_an_injectable_clock_with_the_system_default_zone(self):
        text = self.service('inventory-service', 'src/main/java/com/acme/inventory/core/service/impl/ItemServiceImpl.java')
        self.assertIn('private Clock clock = Clock.systemDefaultZone();', text)
        self.assertIn('@Autowired(required = false)\n    void setClock(Clock clock)', text)
        self.assertIn('LocalDateTime.now(clock)', text)
        for forbidden in ('ZONE_ID', 'ZoneId', 'SYSDATE', 'LocalDateTime.now()'):
            self.assertNotIn(forbidden, text)

    def test_services_without_audit_dates_get_no_clock(self):
        def without_dates(plan):
            for op in plan['api']['operations']:
                op['modelMappings'] = [m for m in op.get('modelMappings', []) if (m.get('value') or {}).get('kind') != 'database-function']
        fx.ready_service(self.repo, 'billing-service', mutate=without_dates)
        mz.materialize(self.repo, 'billing-service')
        text = (self.repo / 'output/billing-service/src/main/java/org/example/billing/service/impl/InvoiceServiceImpl.java').read_text(encoding='utf-8')
        self.assertNotIn('Clock', text)
        test = (self.repo / 'output/billing-service' / BIL / 'service/impl/InvoiceServiceImplTest.java').read_text(encoding='utf-8')
        self.assertNotIn('Clock', test)

    def test_tests_use_a_fixed_clock_and_check_creation_and_modification_dates(self):
        out = self.gen('inventory-service')
        text = (out / INV / 'service/impl/ItemServiceImplTest.java').read_text(encoding='utf-8')
        self.assertIn('service.setClock(Clock.fixed(Instant.parse(FIXED_INSTANT), ZoneOffset.UTC));', text)
        self.assertIn('assertEquals(FIXED_LOCAL, saved.getCreatedAt());', text)
        self.assertIn('assertEquals(FIXED_LOCAL, stored.getUpdatedAt());', text)
        self.assertIn('assertEquals(LocalDateTime.parse("2020-01-01T00:00:00"), stored.getCreatedAt());', text)      # modification leaves the creation date alone
        for expected in ('createItemStampsTheDateInTheZoneOfTheClock', 'createItemStampsTheDateWithTheSystemDefaultClock', 'patchItemStampsTheDateInTheZoneOfTheClock', 'patchItemStampsTheDateWithTheSystemDefaultClock'):
            self.assertIn(expected, methods(text))
        self.assertNotIn('assertNotNull(saved.getCreatedAt())', text)

    def test_a_partially_sampled_constraint_keeps_its_gap_in_the_register(self):
        model = {'service': 's', 'ops': [], 'models': {}}
        register = ts.traceability(model, [('op:param:x:Pattern', 'T#a'), ('op:param:x:Pattern', None, 'only one side of the declared pattern could be sampled')])
        self.assertEqual(register['rules'][0]['gaps'], ['only one side of the declared pattern could be sampled'])

    def test_clock_rules_are_traceable(self):
        self.gen('inventory-service')
        register = yaml.safe_load((self.ws('inventory-service') / 'tests-traceability.yml').read_bytes())
        covered = {r['rule'] for r in register['rules'] if r['status'] == 'covered'}
        self.assertTrue({'createItem:audit:date', 'createItem:audit:clock-zone', 'createItem:audit:default-clock', 'patchItem:audit:date', 'patchItem:audit:clock-zone'} <= covered)


class CoverageReportTests(Base):
    def scope(self, name='inventory-service'):
        return yaml.safe_load((self.ws(name) / 'coverage-scope.yml').read_bytes())

    def test_the_report_names_components_rules_packages_pending_tests_and_tool_states(self):
        self.gen('inventory-service')
        scope = self.scope()
        self.assertEqual(scope['schemaVersion'], 2)
        self.assertTrue({c['component'] for c in scope['componentsWithGeneratedTests']} >= {'ItemValidator', 'ItemServiceImpl', 'ItemController', 'GlobalExceptionHandler'})
        self.assertGreater(scope['rules']['covered'], 100)
        self.assertEqual(scope['rules']['uncovered'], 0)
        self.assertIn('com.acme.inventory.core.controller.impl', scope['packages']['excludedFromJacoco'] + scope['packages']['partiallyExcluded'])
        self.assertEqual(scope['pendingTests'][0]['kind'], 'repository-persistence-test')
        self.assertIn('database', scope['pendingTests'][0]['reason'])
        tools = scope['tools']
        self.assertEqual((tools['maven']['status'], tools['checkstyleOfficial']['status'], tools['jacoco']['status']), ('not-executed', 'unverified', 'not-verified'))
        self.assertEqual((tools['compilation']['status'], tools['testsExecuted']['status']), ('not-executed', 'not-executed'))
        self.assertTrue(scope['limitations'])
        self.assertTrue(any('persistence' in r for r in scope['risks']))

    def test_recorded_executions_are_bound_to_the_generated_tree_and_never_claim_maven(self):
        self.gen('billing-service')
        ws = self.ws('billing-service')
        manifest = yaml.safe_load((self.repo / 'output/billing-service/.generation-manifest.yml').read_bytes())
        ts.record_execution(ws, 'javac-compilation', 'passed', 'javac against local jars', 'main+test', manifest['payloadTreeSha256'])
        ts.record_execution(ws, 'junit-launcher-tests', 'passed', 'JUnit Platform launcher', '80 tests', manifest['payloadTreeSha256'])
        mz.materialize(self.repo, 'billing-service')
        tools = self.scope('billing-service')['tools']
        self.assertEqual((tools['compilation']['status'], tools['testsExecuted']['status']), ('passed', 'passed'))
        self.assertFalse(tools['compilation']['mavenUsed'])
        self.assertEqual((tools['jacoco']['status'], tools['checkstyleOfficial']['status'], tools['maven']['status']), ('not-verified', 'unverified', 'not-executed'))

    def test_a_recorded_execution_becomes_stale_when_the_generated_tree_changes(self):
        self.gen('billing-service')
        ws = self.ws('billing-service')
        ts.record_execution(ws, 'javac-compilation', 'passed', 'javac', '', 'deadbeef')
        mz.materialize(self.repo, 'billing-service')
        self.assertEqual(self.scope('billing-service')['tools']['compilation']['status'], 'stale')

    def test_maven_checkstyle_and_jacoco_results_cannot_be_recorded(self):
        self.gen('billing-service')
        for tool in ('maven', 'checkstyleOfficial', 'jacoco'):
            with self.assertRaises(ValueError):
                ts.record_execution(self.ws('billing-service'), tool, 'passed', 'x', '', 'h')
        with self.assertRaises(ValueError):
            ts.record_execution(self.ws('billing-service'), 'javac-compilation', 'unknown', 'x', '', 'h')

    def test_the_validator_exposes_the_scope_and_rejects_a_tampered_tool_status(self):
        self.gen('billing-service')
        report = vg.validate(self.repo, 'billing-service')
        self.assertEqual(report['status'], 'passed', report['violations'])
        self.assertEqual(report['validationScope']['tools']['jacoco']['status'], 'not-verified')
        self.assertTrue(report['validationScope']['limitations'])
        path = self.ws('billing-service') / 'coverage-scope.yml'
        data = yaml.safe_load(path.read_bytes())
        data['tools']['jacoco']['status'] = 'passed'
        path.write_text(yaml.safe_dump(data), encoding='utf-8')
        self.assertIn('toolStatusesAreHonest', [v['check'] for v in vg.validate(self.repo, 'billing-service')['violations']])

    def test_the_report_is_deterministic_across_runs(self):
        self.gen('billing-service')
        first = (self.ws('billing-service') / 'coverage-scope.yml').read_bytes()
        mz.materialize(self.repo, 'billing-service')
        self.assertEqual(first, (self.ws('billing-service') / 'coverage-scope.yml').read_bytes())


class GatesAndProtectionTests(Base):
    def test_a_blocked_gate_writes_nothing_new(self):
        fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        with self.assertRaises(Exception):
            mz.materialize(self.repo, 'inventory-service')
        self.assertFalse((self.repo / 'output' / 'inventory-service').exists())
        self.assertFalse((self.ws('inventory-service') / 'coverage-scope.yml').exists())

    def test_a_hand_modified_test_file_is_preserved_by_guard_write(self):
        out = self.gen('billing-service')
        target = out / BIL / 'validation/InvoiceValidatorTest.java'
        target.write_text(target.read_text(encoding='utf-8') + '\n// manual\n', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'billing-service')
        self.assertEqual(caught.exception.kind, 'protected-files')
        self.assertIn('// manual', target.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
