"""Phase 2 / P2: generated JUnit 5 + Mockito tests, rule traceability and JaCoCo scope analysis (synthetic services, temporary directories only)."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))

import synth as fx  # noqa: E402
import jars  # noqa: E402
import full_materializer as mz  # noqa: E402
import style_lint  # noqa: E402
import validate_generated_service as vg  # noqa: E402
import test_support as ts  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = fx.make_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def gen(self, name, **kw):
        fx.ready_service(self.repo, name, **kw)
        mz.materialize(self.repo, name)
        return self.repo / 'output' / name

    def ws(self, name):
        return self.repo / '.factory' / 'services' / name


class GeneratedTestsTests(Base):
    def test_every_planned_test_file_is_written_and_contains_test_methods(self):
        for name in fx.SERVICES:
            out = self.gen(name)
            files = sorted((out / 'src/test/java').rglob('*.java'))
            stems = {f.stem for f in files}
            for suffix in ('ValidatorTest', 'MapperTest', 'ServiceImplTest', 'ControllerTest', 'ExceptionHandlerTest', 'ActivityLoggingTest'):
                self.assertTrue(any(s.endswith(suffix) for s in stems), (name, suffix))
            for f in files:
                self.assertIn('@Test', f.read_text(encoding='utf-8'), f.name)

    def test_tests_mirror_the_target_package_of_the_service(self):
        out = self.gen('inventory-service')
        controller = out / 'src/test/java/com/acme/inventory/core/controller/impl/ItemControllerTest.java'
        self.assertTrue(controller.is_file())
        self.assertIn('package com.acme.inventory.core.controller.impl;', controller.read_text(encoding='utf-8'))

    def test_generated_tests_carry_no_names_from_another_service(self):
        out = self.gen('inventory-service')
        for f in (out / 'src/test').rglob('*.java'):
            text = f.read_text(encoding='utf-8')
            for forbidden in ('mailing', 'Mailing', 'MAILINGINFORMATION', 'emailBody', 'dom-document', 'Invoice'):
                self.assertNotIn(forbidden, text, f.name)

    def test_generated_tests_pass_the_preventive_lint_for_both_source_sets(self):
        for name in fx.SERVICES:
            out = self.gen(name)
            report = style_lint.lint_project(out)
            self.assertEqual(report['findings'], [], (name, report['findings'][:5]))
            self.assertNotIn(report['checkstyleOfficial'], (True, 'passed'))
            self.assertIn('src/test/java', ' '.join(map(str, report['sourceSets'])))

    def test_the_generic_validator_accepts_the_complete_generation(self):
        for name in fx.SERVICES:
            self.gen(name)
            report = vg.validate(self.repo, name)
            self.assertEqual(report['status'], 'passed', report['violations'])
            self.assertGreater(len(report['checks']), 10)

    def test_the_validator_rejects_a_traceability_register_that_points_to_a_missing_test(self):
        self.gen('billing-service')
        path = self.ws('billing-service') / 'tests-traceability.yml'
        register = yaml.safe_load(path.read_bytes())
        register['rules'][0]['tests'] = ['GhostTest#doesNotExist']
        path.write_text(yaml.safe_dump(register), encoding='utf-8')
        self.assertIn('traceabilityPointsToExistingTests', [v['check'] for v in vg.validate(self.repo, 'billing-service')['violations']])


class TraceabilityTests(Base):
    def test_covered_and_uncovered_rules_are_listed_and_uncovered_ones_have_reasons(self):
        self.gen('inventory-service')
        register = yaml.safe_load((self.ws('inventory-service') / 'tests-traceability.yml').read_bytes())
        self.assertGreater(register['covered'], 50)
        self.assertEqual(register['uncovered'], 0)
        for rule in register['rules']:
            if rule['status'] == 'uncovered':
                self.assertTrue(rule['reason'])
            else:
                self.assertTrue(rule['tests'])

    def test_contract_outcomes_and_business_rules_are_traced(self):
        self.gen('inventory-service')
        register = yaml.safe_load((self.ws('inventory-service') / 'tests-traceability.yml').read_bytes())
        covered = {r['rule'] for r in register['rules'] if r['status'] == 'covered'}
        for rule in ('createItem:outcome:200', 'createItem:outcome:409', 'patchItem:presence', 'searchItems:filter-policy:combinator'):
            self.assertIn(rule, covered)
        for prefix in ('createItem:rule:', 'createItem:range:', 'searchItems:rule:'):
            self.assertTrue(any(c.startswith(prefix) for c in covered), prefix)

    def test_untestable_areas_are_reported_with_a_reason_not_invented(self):
        model = {'service': 's', 'ops': [{'id': 'op', 'statuses': [200], 'requestModel': None, 'rules': [], 'params': {'path': [], 'query': [], 'header': [
            {'name': 'x-id', 'annotations': ['@Size(max = 5)']}]}}], 'models': {}}
        cov = [('op:param:x-id:Size', None, 'declared on a header parameter; not executed')]
        register = ts.traceability(model, cov)
        row = next(r for r in register['rules'] if r['rule'] == 'op:param:x-id:Size')
        self.assertEqual((row['status'], row['reason']), ('uncovered', 'declared on a header parameter; not executed'))

    def test_the_register_is_deterministic(self):
        self.gen('billing-service')
        first = (self.ws('billing-service') / 'tests-traceability.yml').read_bytes()
        mz.materialize(self.repo, 'billing-service')
        self.assertEqual(first, (self.ws('billing-service') / 'tests-traceability.yml').read_bytes())


class CoverageScopeTests(Base):
    def test_scope_report_reads_the_pom_and_never_claims_coverage(self):
        self.gen('inventory-service')
        scope = yaml.safe_load((self.ws('inventory-service') / 'coverage-scope.yml').read_bytes())
        self.assertEqual(scope['status'], 'not-verified')
        self.assertEqual(scope['threshold'], {'minimum': '80%', 'counter': 'INSTRUCTION', 'value': 'COVEREDRATIO', 'element': 'PACKAGE'})
        excluded, measured = set(scope['excludedClasses']), {m['class'] for m in scope['measuredClasses']}
        self.assertTrue({'ItemController', 'ItemEntity', 'ItemRepository', 'GlobalExceptionHandler', 'CreateItemRequest'} <= excluded)
        self.assertTrue({'ItemServiceImpl', 'ItemValidator'} <= measured)

    def test_a_measured_class_without_a_test_is_reported_as_a_risk(self):
        plan = {'service': {'name': 's', 'packagePath': 'a/b'}, 'files': {'generate': [{'path': 'src/main/java/a/b/service/FooService.java', 'componentType': 'application-service-implementation'}]}}
        pom = (self.repo / fx.ARCHETYPE / 'template' / 'pom.xml').read_text(encoding='utf-8')
        scope = ts.coverage_scope(plan, pom, [], [])
        self.assertTrue(any('FooService' in r for r in scope['risks']))
        self.assertEqual(scope['status'], 'not-verified')

    def test_a_pom_without_jacoco_is_a_declared_risk(self):
        plan = {'service': {'name': 's', 'packagePath': 'a/b'}, 'files': {'generate': []}}
        scope = ts.coverage_scope(plan, '<project xmlns="http://maven.apache.org/POM/4.0.0"><build/></project>', [], [])
        self.assertTrue(any('jacoco' in r for r in scope['risks']))

    def test_glob_translation_matches_jacoco_semantics(self):
        rx = ts.glob_regex('a/b/*.class')
        self.assertTrue(rx.match('a/b/Main.class'))
        self.assertFalse(rx.match('a/b/service/Main.class'))
        self.assertTrue(ts.glob_regex('**/dto/**').match('a/b/dto/mapper/X.class'))


class UnsupportedTests(Base):
    def test_persistence_tests_need_an_unapproved_dependency_and_stop_the_generation(self):
        fx.ready_service(self.repo, 'inventory-service', with_unsupported=True)
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        reasons = [u['reason'] for u in caught.exception.details['unsupported']]
        self.assertEqual(len(reasons), 1)
        self.assertIn('dependency', reasons[0])
        self.assertFalse((self.repo / 'output' / 'inventory-service').exists())

    def test_an_unmatched_test_file_name_is_unsupported_not_guessed(self):
        extra = [fx.file_entry('src/test/java/com/acme/inventory/core/misc/WeirdThingTest.java', 'unit-mapping-persistence-test', 60)]
        fx.ready_service(self.repo, 'inventory-service', extra_files=extra)
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertIn('WeirdThingTest', caught.exception.details['unsupported'][0]['path'])


class DeterminismTests(Base):
    def test_two_independent_repositories_produce_byte_identical_tests(self):
        trees = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                repo = fx.make_repo(Path(tmp))
                fx.ready_service(repo, 'inventory-service')
                mz.materialize(repo, 'inventory-service')
                out = repo / 'output' / 'inventory-service'
                ws = repo / '.factory' / 'services' / 'inventory-service'
                trees.append(({p.relative_to(out).as_posix(): p.read_bytes() for p in (out / 'src/test').rglob('*.java')},
                              (ws / 'tests-traceability.yml').read_bytes(), (ws / 'coverage-scope.yml').read_bytes()))
        self.assertEqual(trees[0], trees[1])

    def test_a_second_run_changes_nothing_including_tests(self):
        self.gen('billing-service')
        again = mz.materialize(self.repo, 'billing-service')
        self.assertEqual(again['written'], [])
        self.assertTrue(any(p.endswith('Test.java') for p in again['unchanged']))


class BlockedGateTests(Base):
    def test_a_blocked_service_gets_no_test_files_and_no_registers(self):
        fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        with self.assertRaises(Exception):
            mz.materialize(self.repo, 'inventory-service')
        self.assertFalse((self.repo / 'output' / 'inventory-service').exists())
        self.assertFalse((self.ws('inventory-service') / 'tests-traceability.yml').exists())


@unittest.skipUnless(shutil.which('javac') and shutil.which('java') and (Path.home() / '.m2' / 'repository').is_dir(), 'JDK or the local Maven cache is not available')
class ExecutionWithoutMavenTests(Base):
    """javac + a JUnit Platform launcher against local jars. This is NOT Maven, Checkstyle or JaCoCo."""
    LAUNCHER = '''import org.junit.platform.launcher.*;
import org.junit.platform.launcher.core.*;
import org.junit.platform.launcher.listeners.*;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import java.io.PrintWriter;

public class Run {
    public static void main(String[] args) {
        LauncherDiscoveryRequest request = LauncherDiscoveryRequestBuilder.request().selectors(DiscoverySelectors.selectPackage(args[0])).build();
        SummaryGeneratingListener listener = new SummaryGeneratingListener();
        LauncherFactory.create().execute(request, listener);
        PrintWriter out = new PrintWriter(System.out);
        listener.getSummary().printTo(out);
        listener.getSummary().printFailuresTo(out, 15);
        out.flush();
        System.exit(listener.getSummary().getTotalFailureCount() == 0 && listener.getSummary().getTestsFoundCount() > 0 ? 0 : 1);
    }
}
'''

    def compile(self, out, label, mutate=None):
        compile_jars = [j for j in jars.collect(True) if 'jpamodelgen' not in j]
        lombok = [j for j in compile_jars if '/lombok-1' in j.replace('\\', '/')]
        needed = ('mockito-core', 'junit-jupiter-api', 'junit-platform-launcher', 'spring-test', 'hibernate-validator', 'json-path', 'logback-classic', 'classmate')
        if not lombok or any(not any(n in j for j in compile_jars) for n in needed):
            self.skipTest('required jars are not in the local cache')
        src = self.repo / f'{label}-src'
        shutil.copytree(out / 'src', src)
        for row in yaml.safe_load((out / '.generation-manifest.yml').read_bytes())['fileInventory']:
            if row.get('componentType') == 'project-assembly' and row['path'].endswith('.java'):
                (src / Path(row['path']).relative_to('src')).unlink()       # assembled archetype Java is validated by Maven, not by this javac check
        if mutate:
            mutate(src)
        classes = self.repo / f'{label}-classes'
        args = self.repo / f'{label}.args'
        sources = [str(p).replace('\\', '/') for p in src.rglob('*.java')]
        args.write_text('\n'.join(['-parameters', '-proc:full', '-processorpath', f'"{lombok[0]}"'.replace('\\', '/'), '-d', f'"{classes}"'.replace('\\', '/'), '-cp',
                                   '"' + os.pathsep.join(compile_jars).replace('\\', '/') + '"'] + [f'"{s}"' for s in sources]), encoding='utf-8')
        done = subprocess.run(['javac', f'@{args}'], capture_output=True, text=True)
        return done, classes, compile_jars

    def run_tests(self, classes, runtime_jars, package):
        launcher = self.repo / 'launcher'
        launcher.mkdir(exist_ok=True)
        (launcher / 'Run.java').write_text(self.LAUNCHER, encoding='ascii')
        run_jars = [j for j in runtime_jars if 'lombok' not in j]
        done = subprocess.run(['javac', '-d', str(launcher), '-cp', os.pathsep.join(run_jars), str(launcher / 'Run.java')], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        result = subprocess.run(['java', '-cp', os.pathsep.join([str(launcher), str(classes)] + run_jars), 'Run', package], capture_output=True, text=True)
        found = re.search(r'(\d+) tests found', result.stdout)
        failed = re.search(r'(\d+) tests failed', result.stdout)
        return result.returncode, int(found.group(1)) if found else 0, int(failed.group(1)) if failed else -1, result.stdout

    def test_generated_main_and_tests_compile_and_the_generated_tests_pass(self):
        for name, package in (('inventory-service', 'com.acme.inventory.core'), ('billing-service', 'org.example.billing')):
            out = self.gen(name)
            done, classes, runtime = self.compile(out, name)
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            code, found, failed, stdout = self.run_tests(classes, runtime, package)
            self.assertGreater(found, 40, stdout[-1500:])
            self.assertEqual((code, failed), (0, 0), stdout[-3000:])

    def test_the_generated_tests_detect_a_broken_production_class(self):
        out = self.gen('inventory-service')

        def mutate(src):
            validator = next(src.rglob('ItemValidator.java'))
            text = validator.read_text(encoding='utf-8')
            match = re.search(r'throw (\w+)\.badRequest\(', text)
            self.assertIsNotNone(match)
            validator.write_text(text.replace(match.group(0), 'if (System.nanoTime() < 0) ' + match.group(0), 1), encoding='utf-8')
        done, classes, runtime = self.compile(out, 'mutant', mutate=mutate)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        code, found, failed, stdout = self.run_tests(classes, runtime, 'com.acme.inventory.core')
        self.assertGreater(found, 40)
        self.assertGreater(failed, 0, 'the generated tests did not notice a disabled validation rule')


    def mutant_run(self, label, mutate, name='inventory-service', package='com.acme.inventory.core'):
        out = self.gen(name)
        done, classes, runtime = self.compile(out, label, mutate=mutate)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return self.run_tests(classes, runtime, package)

    def test_generated_tests_notice_a_removed_parameter_constraint(self):
        for label, token in (('nomax', '@Max(SEARCH_ITEMS_LIMIT_MAX) '), ('nopattern', '@Pattern(regexp = "^[01]$") '), ('nosize', '@Size(max = SEARCH_ITEMS_NAME_SIZE_MAX) ')):
            def mutate(src, token=token):
                api = next(src.rglob('ItemApi.java'))
                text = api.read_text(encoding='utf-8')
                self.assertIn(token, text)
                api.write_text(text.replace(token, '', 1), encoding='utf-8')
            code, found, failed, stdout = self.mutant_run(label, mutate)
            self.assertGreater(failed, 0, f'{label}: the removed constraint went unnoticed')

    def test_generated_tests_notice_a_date_that_ignores_the_injected_clock(self):
        def mutate(src):
            impl = next(src.rglob('ItemServiceImpl.java'))
            text = impl.read_text(encoding='utf-8')
            self.assertIn('LocalDateTime.now(clock)', text)
            impl.write_text(text.replace('LocalDateTime.now(clock)', 'LocalDateTime.now()'), encoding='utf-8')
        code, found, failed, stdout = self.mutant_run('noclock', mutate)
        self.assertGreater(failed, 0)

    def test_generated_tests_notice_a_date_in_the_wrong_zone(self):
        def mutate(src):
            impl = next(src.rglob('ItemServiceImpl.java'))
            text = impl.read_text(encoding='utf-8')
            impl.write_text(text.replace('LocalDateTime.now(clock)', 'LocalDateTime.now(clock.withZone(java.time.ZoneOffset.UTC))'), encoding='utf-8')
        code, found, failed, stdout = self.mutant_run('wrongzone', mutate)
        self.assertGreater(failed, 0)


if __name__ == '__main__':
    unittest.main()
