import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

spec = importlib.util.spec_from_file_location('inventory', Path(__file__).parents[1] / 'scripts/validate_inventory.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'template').mkdir()
        (self.root / 'template/utility.txt').write_text('@@NAME@@', encoding='utf-8')
        (self.root / 'decisions.md').write_text('D-001 approved', encoding='utf-8')
        self.data = {'templateInventory': [{'path': 'utility.txt', 'evidence': ['E-1'], 'decisionRefs': ['D-001']}],
                     'parameters': {'NAME': {'affectedFiles': ['utility.txt']}},
                     'provenance': {'approvedDecisionRefs': ['D-001']},
                     'evidence': {'entries': {'E-1': {'path': 'utility.txt'}}}}

    def run_validation(self):
        (self.root / 'archetype.yml').write_text(yaml.safe_dump(self.data), encoding='utf-8')
        return module.validate(self.root)

    def test_unknown_technology_needs_no_backend_or_other_archetype(self):
        self.data['identity'] = {'name': 'unrelated-rust-worker'}
        self.assertEqual('passed', self.run_validation()['status'])

    def test_missing_utility_fails(self):
        (self.root / 'template/utility.txt').unlink()
        self.assertEqual('failed', self.run_validation()['status'])

    def test_added_config_requires_inventory(self):
        (self.root / 'template/settings.j2').write_text('config', encoding='utf-8')
        self.assertIn('inventory mismatch', ' '.join(self.run_validation()['issues']))

    def test_stale_parameter_locations_fail(self):
        self.data['parameters']['NAME']['affectedFiles'] = []
        self.assertIn('affectedFiles mismatch: NAME', self.run_validation()['issues'])

    def test_unknown_decision_and_evidence_fail(self):
        self.data['templateInventory'][0].update(decisionRefs=['D-999'], evidence=['E-999'])
        self.assertEqual(2, len(self.run_validation()['issues']))

    def test_duplicate_yaml_keys_fail(self):
        (self.root / 'archetype.yml').write_text('identity: 1\nidentity: 2\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            module.validate(self.root)

    def test_pom_scope_drift_is_not_silently_accepted(self):
        (self.root / 'template/pom.xml').write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><dependencies>'
            '<dependency><groupId>x</groupId><artifactId>lib</artifactId><scope>test</scope>'
            '</dependency></dependencies></project>', encoding='utf-8')
        self.data['templateInventory'].append({'path': 'pom.xml'})
        self.data['build'] = {'dependencies': [{'groupId': 'x', 'artifactId': 'lib', 'scope': 'provided'}]}
        self.assertIn('POM dependencies field mismatch: lib.scope', self.run_validation()['issues'])

    def test_unrelated_reference_and_archetype_do_not_affect_result(self):
        before = self.run_validation()
        (self.root / 'unrelated-reference').mkdir()
        (self.root / 'unrelated-reference/private.txt').write_text('not inspected', encoding='utf-8')
        self.assertEqual(before, self.run_validation())

    def test_unknown_schema_is_not_a_success(self):
        self.data.pop('templateInventory')
        self.assertEqual('unsupported-schema', self.run_validation()['status'])

    def test_protected_content_is_never_opened(self):
        (self.root / 'template/application.properties').write_text('never-read', encoding='utf-8')
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            if module.protected(path):
                raise AssertionError('protected read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', guarded):
            self.assertEqual('failed', self.run_validation()['status'])


if __name__ == '__main__':
    unittest.main()
