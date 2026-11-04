"""Persistent planner -> artifact -> model -> renderers -> assembler contract tests.

Specs are synthetic, plans/parameters come from the real guarded planner CLI.
No mailing-info fixture is materialized and no gate is mocked or disabled.
"""
import copy
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synth as fx
import real_planner_fixture as rf
import full_materializer as mz
import service_model as sm
import validation_evidence as ve
import validate_generated_service as vg
import file_protection as fp


class RealPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=r'C:\Users\proma\AppData\Local\Temp\opencode')
        self.repo = fx.make_repo(Path(self.tmp.name))
        self.name = 'inventory-service'
        self.ws = rf.prepare(self.repo, self.name)
        self.out = self.repo / 'output' / self.name

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self):
        return yaml.safe_load((self.ws.dir / 'implementation-plan.yml').read_bytes())

    def save(self, plan):
        fx.wfx.dump(self.ws.dir / 'implementation-plan.yml', plan)

    def materialize(self):
        return mz.materialize(self.repo, self.name)

    def refused(self, mutation, kind=None):
        p = self.plan()
        mutation(p)
        self.save(p)
        before = fx.tree(self.ws.dir)
        with self.assertRaises(mz.MaterializationError) as raised:
            self.materialize()
        if kind:
            self.assertEqual(raised.exception.kind, kind, str(raised.exception))
        self.assertFalse(self.out.exists())
        self.assertEqual(before, fx.tree(self.ws.dir))
        return raised.exception

    def test_real_cli_artifacts_are_consumed_without_rewriting_the_plan(self):
        p = self.plan()
        self.assertIn('roles', p['activityLogging']['requestHeaders'])
        self.assertNotIn('roleMapping', p['activityLogging']['requestHeaders'])
        model = sm.build(p)
        self.assertEqual(model['headers']['roles'], {'transactionId': 'x-correlation-id', 'userId': 'x-user-id'})
        before = {n: (self.ws.dir / n).read_bytes() for n in ('implementation-plan.yml', 'generation-parameters.yml', 'service-spec.yml')}
        self.assertEqual(self.materialize()['status'], 'complete')
        self.assertEqual(before, {n: (self.ws.dir / n).read_bytes() for n in before})
        self.assertEqual(vg.validate(self.repo, self.name)['status'], 'passed')
        for entry in p['files']['generate']:
            if entry['path'].endswith('.java'):
                self.assertTrue((self.out / entry['path']).is_file(), entry['path'])

    def test_contract_test_keeps_exact_planner_name_and_tests_the_controller(self):
        p = self.plan()
        entry = next(f for f in p['files']['generate'] if f['componentType'] == 'controller-contract-test')
        self.assertTrue(entry['path'].endswith('InventoryServiceApiContractTest.java'))
        self.materialize()
        text = (self.out / entry['path']).read_text(encoding='utf-8')
        self.assertIn('class InventoryServiceApiContractTest', text)
        self.assertIn('MockMvcBuilders.standaloneSetup', text)
        self.assertIn('searchItems', text)
        self.assertEqual(len(list(self.out.rglob('*ApiContractTest.java'))), 1)

    def test_arbitrary_test_name_uses_semantic_dependencies_not_suffix(self):
        p = self.plan()
        entry = next(f for f in p['files']['generate'] if f['componentType'] == 'unit-mapping-persistence-test' and f['path'].endswith('MapperTest.java'))
        old = entry['path']
        entry['path'] = old.rsplit('/', 1)[0] + '/MappingContractChecks.java'
        p['generationOrdering'] = [entry['path'] if x == old else x for x in p['generationOrdering']]
        for f in p['files']['generate']:
            f['dependencies'] = [entry['path'] if d == old else d for d in f['dependencies']]
        self.save(p)
        self.materialize()
        text = (self.out / entry['path']).read_text(encoding='utf-8')
        self.assertIn('class MappingContractChecks', text)
        self.assertIn('mapper.', text)
        self.assertFalse((self.out / old).exists())

    def test_missing_roles_fail_clearly_before_writing(self):
        err = self.refused(lambda p: p['activityLogging']['requestHeaders'].pop('roles'), 'unsupported')
        self.assertIn('requestHeaders.roles is required', str(err))

    def test_duplicate_header_assignment_is_ambiguous(self):
        def change(p):
            p['activityLogging']['requestHeaders']['roles']['userId']['header'] = 'x-correlation-id'
        self.assertIn('ambiguous header roles', str(self.refused(change, 'unsupported')))

    def test_role_without_declared_header_is_refused(self):
        def change(p):
            p['activityLogging']['requestHeaders']['roles']['transactionId']['header'] = 'missing-header'
        self.assertIn('missing or ambiguous', str(self.refused(change, 'unsupported')))

    def test_missing_role_mapping_for_a_component_is_refused(self):
        self.assertIn('exactly', str(self.refused(lambda p: p['activityLogging']['requestHeaders']['roles'].pop('userId'), 'unsupported')))

    def test_conflicting_legacy_alias_is_not_silently_selected(self):
        def change(p):
            h = p['activityLogging']['requestHeaders']
            h['roleMapping'] = copy.deepcopy(h['roles'])
            h['roleMapping']['userId']['header'] = 'different'
        self.assertIn('disagree', str(self.refused(change, 'unsupported')))

    def test_legacy_role_mapping_is_explicitly_compatible(self):
        p = self.plan()
        expected = sm.build(p)['headers']
        h = p['activityLogging']['requestHeaders']
        h['roleMapping'] = h.pop('roles')
        self.assertEqual(sm.build(p)['headers'], expected)
        self.save(p)
        self.assertEqual(self.materialize()['status'], 'complete')

    def test_invalid_version_is_refused(self):
        self.refused(lambda p: p['plan'].update(version=99), 'invalid-plan')

    def test_missing_required_field_is_not_a_key_error(self):
        original = self.plan()
        for change in (lambda p: p.pop('activityLogging'), lambda p: p['inputs'].update(archetype='malformed'),
                       lambda p: p['files']['generate'][0].update(generationOrder='malformed')):
            self.save(copy.deepcopy(original))
            self.refused(change, 'invalid-plan')

    def test_removing_parameter_hash_does_not_enter_an_unbound_legacy_profile(self):
        self.refused(lambda p: p['inputs'].pop('generationParameters'), 'invalid-plan')

    def test_retained_functional_files_still_require_supported_behavior(self):
        self.materialize()
        p = self.plan()
        for f in p['files']['generate']:
            if f['path'].endswith('.java'):
                f['action'] = 'retain'
        p['api']['operations'][0]['validation'][0]['rules'].append({'ruleId': 'unknown', 'kind': 'unsupported-functional-rule'})
        self.save(p)
        before = fx.tree(self.out)
        with self.assertRaises(mz.MaterializationError) as err:
            self.materialize()
        self.assertEqual(err.exception.kind, 'unsupported')
        self.assertEqual(before, fx.tree(self.out))

    def test_missing_retained_java_is_not_silently_omitted(self):
        self.refused(lambda p: next(f for f in p['files']['generate'] if f['componentType'] == 'business-validator').update(action='retain'), 'invalid-plan')

    def test_missing_nested_field_is_not_a_key_error(self):
        self.refused(lambda p: p['activityLogging'].pop('operations'), 'invalid-plan')

    def test_duplicate_inventory_path_is_refused(self):
        self.refused(lambda p: p['files']['generate'].append(copy.deepcopy(p['files']['generate'][0])), 'invalid-plan')

    def test_unknown_dependency_is_refused(self):
        self.refused(lambda p: p['files']['generate'][0]['dependencies'].append('unknown.java'), 'invalid-plan')

    def test_unknown_action_is_not_retain(self):
        self.refused(lambda p: p['files']['generate'][0].update(action='keep-silently'), 'unsupported')

    def test_unknown_component_is_refused_even_if_marked_retain(self):
        self.refused(lambda p: p['files']['generate'][0].update(componentType='unknown-component', action='retain'), 'unsupported')

    def test_unsupported_business_rule_stops_the_whole_full_generation(self):
        self.refused(lambda p: p['api']['operations'][0]['validation'][0]['rules'].append({'ruleId': 'UNSUPPORTED', 'kind': 'invented-rule'}), 'unsupported')

    def test_baselines_are_assembled_once_for_create(self):
        p = self.plan()
        baselines = [f for f in p['files']['generate'] if f['componentType'] in ('build-baseline', 'logging-baseline')]
        self.assertEqual({f['action'] for f in baselines}, {'create'})
        report = self.materialize()
        manifest = yaml.safe_load((self.out / mz.MANIFEST).read_bytes())
        for f in baselines:
            self.assertEqual(report['written'].count(f['path']), 1)
            self.assertEqual(sum(r['path'] == f['path'] for r in manifest['fileInventory']), 1)
            if f.get('expectedSha256'):
                self.assertEqual(fx.sha((self.out / f['path']).read_bytes()), f['expectedSha256'])

    def test_baseline_update_and_retain_actions(self):
        self.materialize()
        p = self.plan()
        for f in p['files']['generate']:
            if f['componentType'] == 'build-baseline':
                f['action'] = 'update'
            if f['componentType'] == 'logging-baseline':
                f['action'] = 'retain'
        self.save(p)
        before = (self.out / 'src/main/resources/logback.xml').read_bytes()
        report = self.materialize()
        self.assertEqual(report['written'], [])
        self.assertEqual((self.out / 'src/main/resources/logback.xml').read_bytes(), before)

    def test_retain_missing_baseline_is_a_contract_error(self):
        def change(p):
            next(f for f in p['files']['generate'] if f['componentType'] == 'logging-baseline')['action'] = 'retain'
        self.assertIn('retain requires', str(self.refused(change, 'invalid-plan')))

    def test_baseline_wrong_path_is_refused(self):
        def change(p):
            next(f for f in p['files']['generate'] if f['componentType'] == 'build-baseline')['path'] = 'other-pom.xml'
        self.refused(change, 'invalid-plan')

    def test_pom_hash_mismatch_is_not_ignored(self):
        def change(p):
            next(f for f in p['files']['generate'] if f['componentType'] == 'build-baseline')['expectedSha256'] = '0' * 64
        self.refused(change, 'baseline-mismatch')

    def test_malformed_maven_additions_are_refused_not_silently_dropped(self):
        def change(p):
            next(f for f in p['files']['generate'] if f['componentType'] == 'build-baseline')['mavenAdditions'] = [{'artifactId': 'not-supported'}]
        self.refused(change, 'preflight-failed')

    def test_parameter_hash_is_checked_before_write(self):
        path = self.ws.dir / 'generation-parameters.yml'
        path.write_bytes(path.read_bytes() + b'\n# changed\n')
        with self.assertRaises(mz.MaterializationError) as err:
            self.materialize()
        self.assertEqual(err.exception.kind, 'stale-plan')
        self.assertFalse(self.out.exists())

    def test_planning_input_hash_is_checked_before_write(self):
        path = self.ws.dir / 'full-planning-input.yml'
        path.write_bytes(path.read_bytes() + b'\n# changed\n')
        with self.assertRaises(mz.MaterializationError) as err:
            self.materialize()
        self.assertEqual(err.exception.kind, 'stale-plan')

    def test_manual_baseline_is_not_overwritten_for_create_or_update(self):
        self.out.mkdir(parents=True)
        (self.out / 'pom.xml').write_text('user owned', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as err:
            self.materialize()
        self.assertEqual(err.exception.kind, 'protected-files')
        self.assertEqual((self.out / 'pom.xml').read_text(), 'user owned')
        self.assertEqual(list(self.out.rglob('*.java')), [])

    def test_guard_write_protects_assembled_and_java_files(self):
        calls = []
        guard = fp.guard_write
        with patch.object(fp, 'guard_write', side_effect=lambda out, path, ws: (calls.append(path), guard(out, path, ws))[1]):
            report = self.materialize()
        self.assertEqual(set(calls), set(report['written']) | {mz.MANIFEST})
        self.assertTrue(all(path in calls for path in report['written']))
        (self.out / 'pom.xml').write_text('manual', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as err:
            self.materialize()
        self.assertEqual(err.exception.kind, 'protected-files')

    def test_consistency_change_blocks_without_any_workspace_write(self):
        fx.blocked_gate(self.repo, self.name, fx.SERVICES[self.name]['route'])
        before = fx.tree(self.ws.dir)
        with self.assertRaises(fx.gate.GateError):
            self.materialize()
        self.assertEqual(before, fx.tree(self.ws.dir))
        self.assertFalse(self.out.exists())

    def test_determinism_idempotency_and_service_independence(self):
        self.materialize()
        before = fx.tree(self.out)
        self.assertEqual(self.materialize()['written'], [])
        self.assertEqual(before, fx.tree(self.out))
        with tempfile.TemporaryDirectory(dir=r'C:\Users\proma\AppData\Local\Temp\opencode') as tmp:
            other = fx.make_repo(Path(tmp))
            rf.prepare(other, self.name)
            mz.materialize(other, self.name)
            self.assertEqual(before, fx.tree(other / 'output' / self.name))
        rf.prepare(self.repo, 'billing-service')
        mz.materialize(self.repo, 'billing-service')
        self.assertEqual(before, fx.tree(self.out))


@unittest.skipUnless(os.environ.get('SERVICE_GENERATOR_AUTHORIZED_MAVEN_TESTS') == '1' and shutil.which('mvn'), 'Explicit Maven test authorization required')
class RealPlanMavenTests(unittest.TestCase):
    def test_real_planner_to_official_maven_for_two_synthetic_services(self):
        with tempfile.TemporaryDirectory(dir=r'C:\Users\proma\AppData\Local\Temp\opencode') as tmp:
            repo = fx.make_repo(Path(tmp))
            for name in fx.SERVICES:
                with self.subTest(name=name):
                    rf.prepare(repo, name)
                    mz.materialize(repo, name)
                    record = ve.run_official(repo, name, Path(tmp) / 'build', True)
                    self.assertEqual({k: v['status'] for k, v in record['tools'].items()},
                                     {k: 'passed' for k in ve.ts.OFFICIAL_TOOLS}, record['tools'])
                    self.assertEqual(record['tools']['checkstyleOfficial']['violations'], 0)
                    self.assertEqual(record['tools']['jacoco']['belowThreshold'], [])
                    self.assertGreater(record['tools']['testsExecuted']['total'], 0)
                    self.assertEqual(vg.validate(repo, name)['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
