import re
import sys
import unittest
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import archetype_contract as ac
import profiles

ROOT = Path(__file__).resolve().parents[4]
PLAN = ROOT / '.opencode/skills/plan-service-implementation/scripts'
MAT = ROOT / '.opencode/skills/materialize-full-service/scripts'
SELECTED = {'claro-spring-ms/v1.0.0': ac.LEGACY_JPA,
            'claro-spring-java-8/v1.0.0': ac.JDBC_WAR,
            'claro-java-8-shell/v1.0.0': ac.BATCH_SHELL}
FOREIGN = {ac.JDBC_WAR: ('claro-spring-ms', 'activity_logging_plan', 'spring-data-jpa', 'SFTP'),
           ac.BATCH_SHELL: ('claro-spring-ms', 'activity_logging_plan', 'spring-data-jpa',
                            'CallableStatement', 'openapi-spec', 'CRMLITE')}


class ProfileMatrixTests(unittest.TestCase):
    def test_registry_and_dispatcher_agree(self):
        self.assertEqual(set(profiles.SUPPORTED), set(ac.CAPABILITIES))

    def test_each_capability_points_to_existing_modules(self):
        for profile, cap in ac.CAPABILITIES.items():
            with self.subTest(profile=profile):
                self.assertTrue((PLAN / f"{cap['planner']}.py").is_file())
                self.assertTrue((MAT / f"{cap['materializer']}.py").is_file())
                self.assertIn(cap['inputKind'], ('http', 'batch'))
                self.assertIn(cap['templateDialect'], ('__TOKEN__', '@@TOKEN@@'))
                self.assertTrue(cap['limits'])

    def test_real_archetypes_normalize_to_their_profile(self):
        for rel, profile in SELECTED.items():
            with self.subTest(archetype=rel):
                value = yaml.safe_load((ROOT / 'archetypes' / rel / 'archetype.yml').read_text(encoding='utf-8'))
                contract = ac.normalize(value)
                self.assertEqual(contract['profile'], profile)
                self.assertEqual(ac.require_backend(contract), profile)

    def test_template_dialect_matches_template_tokens(self):
        for rel, profile in SELECTED.items():
            with self.subTest(archetype=rel):
                dialect = ac.CAPABILITIES[profile]['templateDialect']
                text = ''.join(p.read_text(encoding='utf-8', errors='ignore')
                               for p in (ROOT / 'archetypes' / rel / 'template').rglob('*')
                               if p.is_file() and not p.name.startswith('application')
                               and p.suffix in ('.java', '.xml', '.yml', '.j2', '.properties'))
                other = '@@' if dialect == '__TOKEN__' else '__'
                if other == '@@':
                    self.assertIsNone(re.search(r'@@[A-Z_]+@@', text))

    def test_profiles_do_not_borrow_other_profile_rules(self):
        files = {ac.JDBC_WAR: [PLAN / 'jdbc_war_plan.py', MAT / 'jdbc_war_materializer.py'],
                 ac.BATCH_SHELL: [PLAN / 'batch_shell_plan.py', PLAN / 'batch_shell_contract.py',
                                  MAT / 'batch_shell_materializer.py']}
        for profile, paths in files.items():
            for path in paths:
                text = path.read_text(encoding='utf-8')
                for term in FOREIGN[profile]:
                    if term == 'CRMLITE' and profile == ac.JDBC_WAR:
                        continue
                    with self.subTest(file=path.name, term=term):
                        self.assertNotIn(term, text)

    def test_unknown_profile_has_no_backend(self):
        contract = ac.normalize({'schemaVersion': 1, 'identity': {'name': 'x', 'version': '1.0.0'},
                                 'generation': {'profile': 'unknown'}})
        with self.assertRaises(ac.ContractError):
            ac.require_backend(contract)

    def test_batch_has_no_http_input(self):
        self.assertEqual(ac.CAPABILITIES[ac.BATCH_SHELL]['inputKind'], 'batch')


if __name__ == '__main__':
    unittest.main()
