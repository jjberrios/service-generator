"""Regression tests against the approved normalized fixture; no application writes."""
from pathlib import Path
import atexit
import copy
import shutil
import tempfile
import sys
import unittest
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[4]
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'reference-service'


def build_fixture_root() -> Path:
    """Self-contained planning root: frozen reference service-spec and planning input plus the (read-only copied) archetype.
    No live .factory/, no active service, no archive: the tests behave identically on any machine and for any checkpoint state."""
    root = Path(tempfile.mkdtemp(prefix='planner-fixture-'))
    (root / '.factory').mkdir()
    for name in ('service-spec.yml', 'full-planning-input.yml'):
        shutil.copy2(FIXTURES / name, root / '.factory' / name)
    shutil.copytree(REPO / 'archetypes', root / 'archetypes')
    return root


ROOT = build_fixture_root()
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_implementation_plan as base
import full_implementation_plan as full
import checkstyle_gate as gate

INPUT = Path('.factory/full-planning-input.yml')


class FullPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.parameters = full.build_full(ROOT, yaml, INPUT)

    def test_fixture_root_is_independent_of_any_live_service_or_checkpoint(self):
        self.assertFalse((ROOT / '.factory' / 'services').exists())
        self.assertFalse((ROOT / '.factory' / 'archive').exists())
        self.assertFalse((ROOT / '.factory' / 'service-generation-state.yml').exists())
        self.assertEqual(self.plan['service']['name'], 'dom-document-mailing-info')           # the frozen reference fixture, not whatever service is active
        self.assertEqual(self.plan['plan']['mode'], 'full')

    def test_a_service_without_prior_generation_parameters_is_planned_from_the_archetype(self):
        self.assertFalse((ROOT / '.factory' / 'generation-parameters.yml').exists())
        self.assertTrue(self.parameters['values']['base_package'])
        self.assertEqual(self.parameters['approvedResolutions'], [])

    def test_functional_gate_cannot_be_promoted(self):
        original = base.read_yaml

        def read(path, root, module):
            data, payload = original(path, root, module)
            if path == ROOT / full.SPEC:
                data = copy.deepcopy(data)
                data['readiness']['functionalCodeGenerationReady'] = False
            return data, payload

        with patch.object(base, 'read_yaml', side_effect=read):
            with self.assertRaisesRegex(base.PlanError, 'functionalCodeGenerationReady'):
                full.context(ROOT, yaml, INPUT)

    def test_scaffold_mode_keeps_source_readiness(self):
        result = base.plan(ROOT, yaml)
        self.assertEqual(result['plan']['mode'], 'scaffold')
        self.assertTrue(result['readiness']['strictImplementationReady'])
        self.assertTrue(all(f['generationStatus'] == 'omit-scaffold-scope' for f in result['files']['omitUnresolved']))

    def test_query_policy_is_effective_not_literal_traceability(self):
        select = next(o for o in self.plan['api']['operations'] if o['actionKind'] == 'select')
        self.assertEqual(select['query']['filterPolicy']['combinator'], 'OR')
        self.assertEqual(select['query']['filterPolicy']['minimumActiveFilters'], 1)
        for item in select['query']['filters']:
            expected = 'exact' if item['javaType'] in ('Integer', 'BigDecimal', 'Long') else 'contains'
            self.assertEqual(item['effectiveMatch'], expected)
        self.assertEqual(set(select['query']['pagination']), {'limit', 'offset'})
        self.assertNotIn('TEMPLATEID', [i['physicalColumn'] for i in select['query']['selectedColumns']])

    def test_file_inventory_complete_with_topological_order(self):
        records = {f['path']: f for f in self.plan['files']['generate']}
        positions = {p: i for i, p in enumerate(self.plan['generationOrdering'])}
        self.assertEqual(set(positions), set(records))
        self.assertTrue(set(self.plan['inputs']['existingOutputInventory']) <= set(records))
        for record in records.values():
            for dependency in record['dependencies']:
                self.assertLess(positions[dependency], positions[record['path']])

    def test_model_json_pointers_escape_media_type_slashes(self):
        spec = yaml.safe_load((ROOT / full.SPEC).read_bytes())
        for model in self.plan['models']:
            self.assertNotIn('/content/application/json/', model['traceability'])
            node = spec
            for token in model['traceability'].strip('/').split('/'):
                token = token.replace('~1', '/').replace('~0', '~')
                node = node[int(token)] if isinstance(node, list) else node[token]
            self.assertIsInstance(node, dict)

    def test_omitted_patch_fields_cannot_be_overwritten(self):
        update = next(o for o in self.plan['api']['operations'] if o['actionKind'] == 'update')
        self.assertIn('Track declared JSON property presence', update['write']['presencePolicy'])
        self.assertEqual(update['write']['noMatchingRecordOutcome']['status'], 404)
        writes = {v['value'].get('input'): v['physicalColumn'] for v in update['write']['mappings']}
        self.assertEqual(writes['emailBody'], 'EMAILBODY')
        self.assertEqual(writes['requestId'], 'REQUESTID')
        self.assertNotIn('x-request-id', writes)

    def test_persistence_is_inherited_and_jdbc_cannot_be_chosen_for_simplicity(self):
        self.assertEqual(self.plan['persistenceAuthority']['technology'], 'spring-data-jpa')
        self.assertFalse(self.plan['persistenceAuthority']['jdbcAllowedBecauseSimpler'])
        service, config, archetype, _ = full.context(ROOT, yaml, INPUT)
        config = copy.deepcopy(config)
        config['technical']['persistence_mechanism'] = 'spring-jdbc-named-parameters'
        with self.assertRaisesRegex(base.PlanError, 'simplicity is not a reason'):
            full.persistence_authority(archetype, config)
        config['technical']['persistence_override'] = {'authority': 'explicit-user-instruction', 'provenance': 'test'}
        with self.assertRaisesRegex(base.PlanError, 'no backend is implemented'):
            full.persistence_authority(archetype, config)

    def test_checkstyle_is_a_mandatory_gate_for_main_and_test_sources(self):
        planned = self.plan['qualityGates']['checkstyle']
        self.assertEqual(gate.plan_gate_complete(self.plan), [])
        self.assertEqual(planned['sources'], ['src/main/java', 'src/test/java'])
        self.assertTrue(planned['includeTestSourceDirectory'])
        self.assertFalse(planned['suppressionsAllowed'] or planned['generatedCodeExclusionsAllowed'] or planned['weakeningAllowed'])
        self.assertFalse(planned['syntaxParseSubstitutesCheckstyle'])
        java = {f['path'] for f in self.plan['files']['generate'] if f['path'].endswith('.java') and f['action'] != 'remove'}
        self.assertEqual(set(planned['appliesTo']['mainJavaFiles']) | set(planned['appliesTo']['testJavaFiles']), java)
        self.assertTrue(planned['appliesTo']['testJavaFiles'])
        self.assertEqual(self.parameters['functional']['qualityGates']['checkstyle']['unexecutableStatus'], 'unverified')

    def test_planner_refuses_to_plan_without_or_with_a_weakened_checkstyle_gate(self):
        _, _, archetype, archetype_root = full.context(ROOT, yaml, INPUT)
        paths = ['src/main/java/A.java', 'src/test/java/ATest.java']
        for key, value in (('mandatory_generation_gate', False), ('generated_code_exclusions_allowed', True), ('suppressions_allowed', True),
                           ('include_test_source_directory', False), ('sources', ['src/main/java'])):
            broken = copy.deepcopy(archetype)
            broken['quality']['checkstyle'][key] = value
            with self.assertRaises(base.PlanError, msg=key):
                full.checkstyle_gate(broken, archetype_root, paths)
        broken_plan = copy.deepcopy(self.plan)
        broken_plan['qualityGates']['checkstyle']['appliesTo']['testJavaFiles'] = []
        self.assertTrue(gate.plan_gate_complete(broken_plan))
        self.assertTrue(gate.plan_gate_complete({}))

    def test_syntax_parse_alone_or_violations_never_report_final_validation_passed(self):
        clean = {'status': gate.PASSED, 'violations': 0}
        self.assertEqual(gate.final_static_status(True, clean), 'passed')
        self.assertNotEqual(gate.final_static_status(True, {'status': gate.UNVERIFIED, 'violations': None}), 'passed')
        self.assertEqual(gate.final_static_status(True, {'status': gate.FAILED, 'violations': 35}), 'failed')
        self.assertEqual(gate.final_static_status(False, clean), 'failed')

    def test_checkstyle_result_interpretation_is_never_optimistic(self):
        self.assertEqual(gate.interpret(1, '[ERROR] You have 35 Checkstyle violations.')['status'], gate.FAILED)
        self.assertEqual(gate.interpret(0, '[INFO] You have 0 Checkstyle violations.')['status'], gate.PASSED)
        self.assertEqual(gate.interpret(1, '[ERROR] Could not resolve dependencies')['status'], gate.UNVERIFIED)
        self.assertEqual(gate.interpret(0, '')['status'], gate.UNVERIFIED)
        self.assertEqual(gate.interpret(1, 'You have 0 Checkstyle violations.')['status'], gate.FAILED)

    def test_application_properties_follow_archetype_baseline_without_subtypes(self):
        props = self.parameters['functional']['applicationProperties']
        self.assertIn('JPA / HIBERNATE', props['baselineBlocks'])
        self.assertFalse(props['referenceCredentialsCopied'])
        self.assertTrue(any('SUBTYPES' in s for s in props['excludedSections']))

    def test_parameters_preserve_environment_only_credentials(self):
        self.assertFalse(self.parameters['secretsStored'])
        db = self.parameters['functional']['database']
        self.assertEqual(db['properties']['spring.datasource.password'], '${DB_PASSWORD}')
        self.assertNotIn('DB_PASSWORD', self.parameters['values'])
        self.assertEqual(self.parameters['values']['base_package'], 'com.claro.document.mailing.info.support')

    def test_no_raw_source_is_needed_for_full_build(self):
        original_read = Path.read_bytes

        def guarded(path):
            self.assertNotIn('input/sparx', path.as_posix())
            self.assertNotIn('input/reference', path.as_posix())
            self.assertNotIn('input/contracts', path.as_posix())
            return original_read(path)

        with patch.object(Path, 'read_bytes', guarded):
            full.build_full(ROOT, yaml, INPUT)


if __name__ == '__main__':
    unittest.main()
