"""Typed-model backend registry and the financingAgreement generator (pure functions + evidence verification; no gate, no Maven)."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest
import yaml

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'scripts'
REPO = HERE.parents[3]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE.parents[1] / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(HERE.parents[1] / 'plan-service-implementation' / 'scripts'))
import typed_backends  # noqa: E402
import financing_agreement_java as fj  # noqa: E402
import financing_agreement_tests as ft  # noqa: E402
import financing_agreement_materializer as fam  # noqa: E402

WORKSPACE = REPO / '.factory' / 'services' / 'financingAgreement'


class RegistryTests(unittest.TestCase):
    def test_discovers_the_declaring_module_only(self):
        self.assertEqual(typed_backends.module_name('financingAgreement'), 'financing_agreement_materializer')
        for other in ('dom-cpeRequest', 'dom-invoice', 'sod-customerBillStatus', 'unknown-service'):
            self.assertIsNone(typed_backends.module_name(other))

    def test_declaration_is_read_without_importing(self):
        self.assertEqual(typed_backends.declared(SCRIPTS / 'financing_agreement_materializer.py'), ('financingAgreement',))
        self.assertEqual(typed_backends.declared(SCRIPTS / 'full_materializer.py'), ())


class GeneratorTests(unittest.TestCase):
    def test_main_and_tests_are_deterministic_ascii_and_well_packaged(self):
        first = {**fj.build_main(fj.PACKAGE), **ft.build_tests(fj.PACKAGE)}
        second = {**fj.build_main(fj.PACKAGE), **ft.build_tests(fj.PACKAGE)}
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 50)
        for path, text in first.items():
            text.encode('ascii')
            self.assertIn(f'package {fj.PACKAGE}', text, path)
            self.assertNotIn('\r', text)
            self.assertNotIn('application.properties', path)

    def test_every_operation_reaches_api_controller_and_service(self):
        main = fj.build_main(fj.PACKAGE)
        api = main[f'src/main/java/{fj.PACKAGE.replace(".", "/")}/controller/FinancingApi.java']
        service = main[f'src/main/java/{fj.PACKAGE.replace(".", "/")}/service/impl/FinancingServiceImpl.java']
        for op, verb, path, *_ in fj.OPERATIONS:
            self.assertIn(f'{op}(', api)
            self.assertIn(f'{op}(', service)
            self.assertIn(f'@{verb}Mapping(path = "{path}"', api)

    def test_activity_constants_cover_every_sparx_activity(self):
        constants = fj.activity_constants()
        for const, _, data in fj.ACTIVITIES:
            self.assertIn(f'String {const} =', constants)
            self.assertEqual(f'LOG_TIMEOUT_{const}' in constants, data)

    def test_no_business_rule_is_hidden_in_the_generated_main_code(self):
        main = '\n'.join(fj.build_main(fj.PACKAGE).values())
        self.assertNotIn('SYSDATE', main)
        self.assertNotIn('createNativeQuery', main)
        self.assertNotIn('FACEL', main)


@unittest.skipUnless((WORKSPACE / 'openapi-spec.yml').is_file(), 'financingAgreement workspace not present')
class EvidenceTests(unittest.TestCase):
    def copy_workspace(self, tmp):
        for name in ('openapi-spec.yml', 'sparx-authoritative-endpoint-detail.yml'):
            (Path(tmp) / name).write_bytes((WORKSPACE / name).read_bytes())

    def test_the_model_matches_the_workspace_evidence(self):
        self.assertEqual(fam.verify_evidence(WORKSPACE), [])

    def test_a_missing_operation_or_column_stops_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.copy_workspace(tmp)
            spec = yaml.safe_load((Path(tmp) / 'openapi-spec.yml').read_bytes())
            spec['operations'] = [o for o in spec['operations'] if o['operationId'] != 'StateFinancing']
            (Path(tmp) / 'openapi-spec.yml').write_text(yaml.safe_dump(spec), encoding='utf-8')
            self.assertTrue(any('OpenAPI operations differ' in p for p in fam.verify_evidence(tmp)))
        with tempfile.TemporaryDirectory() as tmp:
            self.copy_workspace(tmp)
            detail = yaml.safe_load((Path(tmp) / 'sparx-authoritative-endpoint-detail.yml').read_bytes())
            table = next(d for d in detail['dataDefinitions'] if d['identity']['name'] == 'CUST_FINANCIAMIENTO')
            table['columns'] = [c for c in table['columns'] if c['column'] != 'FNNC_ORDEN']
            (Path(tmp) / 'sparx-authoritative-endpoint-detail.yml').write_text(yaml.safe_dump(detail), encoding='utf-8')
            self.assertTrue(any('FNNC_ORDEN' in p for p in fam.verify_evidence(tmp)))

    def test_a_changed_sparx_property_value_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.copy_workspace(tmp)
            detail = yaml.safe_load((Path(tmp) / 'sparx-authoritative-endpoint-detail.yml').read_bytes())
            changed = copy.deepcopy(detail)
            for op in changed['operations']:
                for act in op['activities']:
                    for line in ((act.get('normalized') or {}).get('variablesProperties') or {}).get('lines') or []:
                        line['text'] = line['text'].replace('propEstadoCuotaErrorOac = 7', 'propEstadoCuotaErrorOac = 8')
            (Path(tmp) / 'sparx-authoritative-endpoint-detail.yml').write_text(yaml.safe_dump(changed), encoding='utf-8')
            self.assertTrue(any('propEstadoCuotaErrorOac' in p for p in fam.verify_evidence(tmp)))


if __name__ == '__main__':
    unittest.main()
