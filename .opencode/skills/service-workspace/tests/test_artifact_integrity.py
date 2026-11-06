"""Shared controls tested with synthetic files, never real output or references."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import artifact_integrity as ai
import file_protection as fp


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.output = self.root / 'output/service'
        self.ws = self.root / 'workspace'
        self.ws.mkdir()

    def manifest(self, payload):
        return yaml.safe_dump({'fileInventory': [{'path': p, 'sha256': hashlib.sha256(v).hexdigest()}
                                                for p, v in sorted(payload.items())]}).encode()

    def test_identical_untracked_content_is_not_adopted(self):
        self.output.mkdir(parents=True)
        (self.output / 'a.txt').write_bytes(b'a')
        with self.assertRaises(fp.ProtectedFileError):
            ai.publish(self.output, self.ws, {'a.txt': b'a', 'b.txt': b'b'}, b'')
        self.assertFalse((self.output / 'b.txt').exists())

    def test_identical_user_owned_file_and_manifest_are_protected(self):
        payload = {'a.txt': b'a'}
        ai.publish(self.output, self.ws, payload, self.manifest(payload))
        for name in ('a.txt', fp.MANIFEST):
            (self.ws / 'user-owned-files.yml').write_text(yaml.safe_dump({'patterns': [name]}))
            with self.assertRaises(fp.ProtectedFileError):
                ai.prepare(self.output, self.ws, payload)

    def test_idempotent_manifest_and_no_temporary_files(self):
        payload = {'a.txt': b'a'}
        raw = self.manifest(payload)
        ai.publish(self.output, self.ws, payload, raw)
        ai.publish(self.output, self.ws, payload, raw)
        self.assertEqual(raw, (self.output / fp.MANIFEST).read_bytes())
        self.assertEqual(({}, ['a.txt']), ai.prepare(self.output, self.ws, payload))
        self.assertFalse(list(self.output.glob('*.tmp')))

    def test_modified_manifest_is_not_used_to_adopt_content(self):
        raw = self.manifest({'a.txt': b'a'})
        ai.publish(self.output, self.ws, {'a.txt': b'a'}, raw)
        (self.ws / 'materialization-report.yml').write_text(yaml.safe_dump({'manifestSha256': hashlib.sha256(raw).hexdigest()}))
        (self.output / fp.MANIFEST).write_bytes(raw + b'#manual\n')
        with self.assertRaisesRegex(fp.ProtectedFileError, 'manifest was modified'):
            ai.prepare(self.output, self.ws, {'a.txt': b'a'})

    def test_manifest_authorization_does_not_authorize_payload_adoption(self):
        payload = {'a.txt': b'a'}
        raw = self.manifest(payload)
        ai.publish(self.output, self.ws, payload, raw)
        (self.ws / 'materialization-report.yml').write_text(yaml.safe_dump({'manifestSha256': hashlib.sha256(raw).hexdigest()}))
        (self.output / fp.MANIFEST).write_bytes(raw + b'#manual\n')
        with self.assertRaises(fp.ProtectedFileError):
            fp.authorize_overwrite(self.output, fp.MANIFEST, self.ws, 'Fixture User', 'Replace synthetic metadata')
        with self.assertRaises(fp.ProtectedFileError):
            ai.prepare(self.output, self.ws, payload)
        with self.assertRaises(fp.ProtectedFileError):
            fp.authorize_overwrite(self.output, 'a.txt', self.ws, 'Fixture User', 'Recover this exact payload')

    def test_protected_configuration_is_rejected_before_read(self):
        original = Path.read_bytes
        def read(path):
            if path.name.startswith('application'):
                raise AssertionError('protected content was read')
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaises(ai.IntegrityError):
                ai.prepare(self.output, self.ws, {'src/main/resources/application.properties': b'x'})

    def test_paths_and_obsolete_inventory_fail_before_writes(self):
        for path in ('../outside', '/absolute', 'a/../b', 'C:/file', 'a\\b'):
            with self.assertRaises(ai.IntegrityError):
                ai.prepare(self.output, self.ws, {path: b'x'})
        ai.publish(self.output, self.ws, {'old': b'x'}, self.manifest({'old': b'x'}))
        with self.assertRaisesRegex(ai.IntegrityError, 'obsolete'):
            ai.prepare(self.output, self.ws, {'new': b'x'}, reject_obsolete=True)
        self.assertFalse((self.output / 'new').exists())

    def test_historical_protected_manifest_entry_never_blocks_or_reads_configuration(self):
        payload = {'a.txt': b'a'}
        ai.publish(self.output, self.ws, payload, self.manifest(payload))
        manifest = yaml.safe_load((self.output / fp.MANIFEST).read_bytes())
        manifest['fileInventory'].append({'path': 'src/main/resources/application.properties', 'sha256': 'legacy'})
        (self.output / fp.MANIFEST).write_text(yaml.safe_dump(manifest))
        original = Path.read_bytes
        def read(path):
            if path.name == 'application.properties':
                raise AssertionError('protected content was read')
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            self.assertEqual(({}, ['a.txt']), ai.prepare(self.output, self.ws, payload, reject_obsolete=True))

    def test_atomic_failure_preserves_previous_file_and_cleans_staging(self):
        dst = self.ws / 'artifact.yml'
        dst.write_bytes(b'old')
        with patch.object(ai.os, 'replace', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                ai.write_atomic(dst, b'new')
        self.assertEqual(b'old', dst.read_bytes())
        self.assertEqual([dst], list(self.ws.iterdir()))

    def test_lock_is_exclusive_scoped_and_released_after_error(self):
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            with ai.service_lock(self.root, 'service'):
                with self.assertRaisesRegex(ai.IntegrityError, 'service-busy'):
                    with ai.service_lock(self.root, 'service'):
                        self.fail('concurrent writer entered')
                with ai.service_lock(self.root, 'other'):
                    pass
                raise RuntimeError('failure')
        with ai.service_lock(self.root, 'service'):
            pass

    def test_fingerprint_uses_only_declared_files_and_separates_docs(self):
        arch = self.root / 'arch'
        (arch / 'template').mkdir(parents=True)
        (arch / 'template/pom.xml').write_text('<project/>')
        (arch / 'archetype.yml').write_text(yaml.safe_dump({'templateInventory': [
            {'path': 'pom.xml'}, {'path': 'src/main/resources/application.properties'}]}))
        (arch / 'decisions.md').write_text('approved')
        first = ai.archetype_hashes(arch)
        (arch / '__pycache__').mkdir()
        (arch / '__pycache__/local.pyc').write_bytes(b'local')
        (arch / 'random.txt').write_text('unrelated')
        original = Path.read_bytes
        def read(path):
            if path.name == 'application.properties':
                raise AssertionError('protected content was read')
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            self.assertEqual(first, ai.archetype_hashes(arch))
        (arch / 'decisions.md').write_text('revised')
        revised = ai.archetype_hashes(arch)
        self.assertEqual(first['technical'], revised['technical'])
        self.assertNotEqual(first['documentation'], revised['documentation'])
        (arch / 'template/pom.xml').write_text('<project>change</project>')
        self.assertNotEqual(revised['technical'], ai.archetype_hashes(arch)['technical'])
