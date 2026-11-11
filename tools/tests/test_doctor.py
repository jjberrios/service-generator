import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import doctor


class DoctorTests(unittest.TestCase):
    def test_project_shape_checks_without_invoking_executables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'opencode.jsonc').write_text(json.dumps({'permissions': [
                {'action': 'read', 'resource': '*', 'effect': 'allow'}]}))
            agents = root / '.opencode/agents'
            agents.mkdir(parents=True)
            (agents / 'synthetic.md').write_text('---\npermissions: []\n---\nOnly a fixture')
            result = doctor.inspect(root)
            self.assertTrue(result['ok'])
            self.assertIn('not-inspected', result['effectivePermissions'])

    def test_missing_project_config_is_a_required_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = doctor.inspect(Path(tmp))
            self.assertFalse(result['ok'])
            self.assertFalse(next(row for row in result['checks'] if row['name'] == 'project-permissions')['ok'])

    def test_invalid_permission_shape_is_not_reported_as_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'opencode.jsonc').write_text('{"permissions": {"read": "allow"}}')
            result = doctor.inspect(root)
            self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main()
