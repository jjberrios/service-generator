import copy
import sys
import unittest
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from archetype_contract import normalize, require_backend, ContractError, LEGACY_JPA, JDBC_WAR, BATCH_SHELL

ROOT = Path(__file__).resolve().parents[4]


class ContractTests(unittest.TestCase):
    def test_three_independent_read_only_adapters(self):
        cases = [('claro-spring-ms', LEGACY_JPA, 'required'),
                 ('claro-spring-java-8', JDBC_WAR, 'not-applicable'),
                 ('claro-java-8-shell', BATCH_SHELL, 'not-applicable')]
        for name, profile, quality in cases:
            with self.subTest(name=name):
                path = ROOT / f'archetypes/{name}/v1.0.0/archetype.yml'
                before = path.read_bytes()
                value = yaml.safe_load(before)
                original = copy.deepcopy(value)
                contract = normalize(value)
                self.assertEqual(require_backend(contract), profile)
                self.assertEqual(contract['quality']['checkstyle']['applicability'], quality)
                self.assertEqual(value, original)
                self.assertEqual(path.read_bytes(), before)

    def test_unknown_fourth_extractable_not_generatable(self):
        value = {'schemaVersion': 1, 'identity': {'name': 'independent', 'version': '2.0'},
                 'persistence': {'technology': 'spring-data-jpa'}}
        contract = normalize(value)
        self.assertFalse(contract['backendSupported'])
        self.assertEqual(contract['decisions'], [])
        self.assertIsNone(contract['style'])
        self.assertEqual(contract['quality']['checkstyle']['applicability'], 'unknown')
        with self.assertRaisesRegex(ContractError, 'unsupported-generation-profile'):
            require_backend(contract)

    def test_missing_legacy_identity_not_inferred_from_jpa(self):
        with self.assertRaisesRegex(ContractError, 'no compatibility adapter'):
            normalize({'persistence': {'technology': 'spring-data-jpa'}})

    def test_versions_and_ambiguity_fail(self):
        with self.assertRaisesRegex(ContractError, 'schema-version'):
            normalize({'schemaVersion': 99, 'identity': {'name': 'other', 'version': '1'}})
        with self.assertRaisesRegex(ContractError, 'ambiguous'):
            normalize({'identity': {}, 'archetype': {}})

    def test_no_foreign_scaffold(self):
        for profile in (JDBC_WAR, BATCH_SHELL):
            contract = normalize({'schemaVersion': 1, 'identity': {'name': 'own', 'version': '1'},
                                  'generation': {'profile': profile}})
            with self.assertRaisesRegex(ContractError, 'unsupported-scaffold-profile'):
                require_backend(contract, mode='scaffold')

    def test_contract_is_detached(self):
        value = {'schemaVersion': 1, 'identity': {'name': 'own', 'version': '1'},
                 'generation': {'profile': BATCH_SHELL, 'style': {'hardcodedLiterals': 'allowed'}}}
        contract = normalize(value)
        contract['style']['hardcodedLiterals'] = 'forbidden'
        contract['backend']['limits'].append('foreign')
        self.assertEqual(normalize(value)['style']['hardcodedLiterals'], 'allowed')
        self.assertNotIn('foreign', normalize(value)['backend']['limits'])
