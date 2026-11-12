"""Batch config and registry use the same reviewed defaults; no live configuration."""
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[4]
for skill in ('plan-service-implementation', 'service-workspace', 'materialize-full-service'):
    sys.path.insert(0, str(REPO / '.opencode/skills' / skill / 'scripts'))
import batch_shell_materializer as bm


class BatchPropertyTests(unittest.TestCase):
    def batch(self):
        values = [('api.app.id', 'FINAN'), ('range.minutes', 70), ('zero', 0),
                  ('unknown', None), ('empty', ''), ('credential', 'synthetic-secret')]
        return {'variant': 'payment-sync-v1', 'connections': [],
                'properties': [{'key': key, 'secret': key == 'credential', 'evidence': ['ea#properties']}
                               for key, _ in values],
                'model': {'properties': [{'key': key, 'default': value} for key, value in values]}}

    def test_documented_values_and_evidence_are_retained(self):
        records = {p['key']: p for p in bm.property_records(self.batch())}
        for key, value in [('api.app.id', 'FINAN'), ('range.minutes', 70), ('zero', 0), ('empty', '')]:
            with self.subTest(key=key):
                self.assertEqual(records[key]['value'], value)
                self.assertEqual(records[key]['documentedDefault'], value)
                self.assertEqual(records[key]['evidence'], ['ea#properties'])

    def test_missing_values_and_secrets_are_empty(self):
        records = {p['key']: p for p in bm.property_records(self.batch())}
        for key in ('unknown', 'credential', 'idf0.codigo', 'log4j.file.dir'):
            self.assertEqual(records[key]['value'], '')
            self.assertNotIn('documentedDefault', records[key])
        self.assertNotIn('synthetic-secret', repr(records))
        self.assertNotIn('operator-required', repr(records))

    def test_config_matches_every_registry_value(self):
        batch = self.batch()
        text = bm.config_source(batch)
        actual = dict(line.split('=', 1) for line in text.splitlines() if not line.startswith('#'))
        self.assertEqual(actual, {p['key']: str(p['value']) for p in bm.property_records(batch)})
        self.assertIn('zero=0\n', text)
        self.assertIn('credential=\n', text)
        self.assertNotIn('synthetic-secret', text)
        self.assertEqual(text, bm.config_source(batch))

    def test_batch_without_documented_defaults_stays_empty(self):
        batch = self.batch()
        batch.pop('variant')
        batch.pop('model')
        self.assertTrue(all(p['value'] == '' for p in bm.property_records(batch)))


if __name__ == '__main__':
    unittest.main()
