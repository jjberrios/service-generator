"""Unit tests of the remote-orchestration pattern helpers (pure functions; no workspace, no Maven)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'materialize-full-service' / 'scripts'))
sys.path.insert(0, str(ROOT / 'interpret-sparx' / 'scripts'))
sys.path.insert(0, str(ROOT / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(ROOT / 'plan-service-implementation' / 'scripts'))
import orchestration_interpretation as oi  # noqa: E402
import orchestration_flows as of  # noqa: E402
import remote_orchestration_java as rj  # noqa: E402


class OutcomeParsing(unittest.TestCase):
    def test_statuses_codes_and_compensation(self):
        out = oi.parse_outcomes(['Si "HTTP STATUS = 200", continuar con la siguiente actividad', 'Si "HTTP STATUS = 404", entonces devolver IDF461',
                                 "Caso contrario, ejecutar 'Rollback Solicitud' y finalizar transacción con IDF464",
                                 'Si el insumo esta NO DISPONIBLE, genera TIME-OUT, ejecutar "Rollback CambioCiclo" y finalizar proceso con IDT'])
        self.assertEqual(out['ok'], [200])
        self.assertEqual(out['byStatus'], {404: 'IDF461'})
        self.assertEqual((out['otherwise'], out['otherwiseCompensation']), ('IDF464', 'rollback solicitud'))
        self.assertEqual(out['technicalCompensation'], 'rollback cambiociclo')

    def test_request_validations_are_bound_to_known_rules(self):
        lines = ['Si "requestTypeId = 8" entonces:', '- Los siguientes atributos deben de venir informados (mandatorios), caso contrario devolver IDF101', '. agreementCodeId',
                 '- quoteCycle debe tener el formato correcto, caso contrario devolver IDF113']
        parsed = of.parse_request_validations(lines)
        self.assertEqual(parsed[8]['required'][0]['field'], 'agreementCodeId')
        self.assertEqual(parsed[8]['rules'][0]['code'], 'IDF113')
        with self.assertRaises(oi.InterpretationError):
            of.parse_request_validations(['Si "requestTypeId = 1" entonces:', '- algo desconocido, caso contrario devolver IDF999'])


class JavaText(unittest.TestCase):
    def test_numbers_are_hoisted_and_long_chains_wrapped(self):
        text = 'class T {\n    void a() {\n        run(5001L, "7");\n    }\n}'
        out = rj.hoist_numbers(text)
        self.assertIn('private static final long VALUE_5001_L = 5001L;', out)
        self.assertIn('"7"', out)
        line = '        x = Body.of()' + ''.join(f'.put("k{i}", v{i})' for i in range(30)) + ';'
        self.assertTrue(all(len(piece) < 200 for piece in rj.wrap_long(line).split('\n')))

    def test_output_is_ascii_and_lf(self):
        text = rj.finalize('p.q', 'x', 'public final class A {\n    String s = "\u00f3";\n}')
        self.assertNotIn('\r', text)
        self.assertTrue(text.isascii())


if __name__ == '__main__':
    unittest.main()
