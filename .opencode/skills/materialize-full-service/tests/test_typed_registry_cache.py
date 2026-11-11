from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / 'service-workspace/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from artifact_reads import read_session
import typed_backends


class TypedRegistryCacheTests(unittest.TestCase):
    def test_live_bytes_invalidate_cached_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic_materializer.py'
            path.write_text("TYPED_BACKEND_SERVICES = ('one',)\n")
            with read_session(), patch.object(typed_backends.ast, 'parse', wraps=typed_backends.ast.parse) as parse:
                self.assertEqual(('one',), typed_backends.declared(path))
                self.assertEqual(('one',), typed_backends.declared(path))
                self.assertEqual(1, parse.call_count)
                path.write_text("TYPED_BACKEND_SERVICES = ('two',)\n")
                self.assertEqual(('two',), typed_backends.declared(path))
                self.assertEqual(2, parse.call_count)
                path.write_text('not python !')
                self.assertEqual((), typed_backends.declared(path))
                path.unlink()
                self.assertEqual((), typed_backends.declared(path))

    def test_no_import_or_execution_during_discovery(self):
        with tempfile.TemporaryDirectory() as tmp, read_session():
            path = Path(tmp) / 'synthetic_materializer.py'
            path.write_text("raise RuntimeError('never execute')\nTYPED_BACKEND_SERVICES = ('safe',)\n")
            self.assertEqual(('safe',), typed_backends.declared(path))


if __name__ == '__main__':
    unittest.main()
