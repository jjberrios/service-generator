"""Parsing optimizations never retain a gate result or trust filesystem metadata."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import artifact_reads as reads
import generation_context as context


class ArtifactReadTests(unittest.TestCase):
    def test_safe_loader_equivalence(self):
        raw = b'a: [true, null, 2.5]\nb: &value {name: text}\nc: *value\ndate: 2026-11-11\n'
        self.assertEqual(yaml.safe_load(raw), reads.load_yaml(raw))

    def test_no_python_object_construction(self):
        with self.assertRaises(yaml.YAMLError):
            reads.load_yaml(b'!!python/object/apply:os.system ["not-executed"]')

    def test_cache_values_are_isolated_and_nested_scopes_reuse(self):
        with reads.read_session() as metrics:
            first = reads.load_yaml(b'a: [1, 2]')
            first['a'].append(3)
            with reads.read_session() as nested:
                self.assertIs(metrics, nested)
                self.assertEqual({'a': [1, 2]}, reads.load_yaml(b'a: [1, 2]'))
            self.assertEqual((1, 1), (metrics['parses'], metrics['hits']))
        self.assertEqual({}, metrics['entries'])

    def test_changed_bytes_are_read_again_even_with_identical_size(self):
        with tempfile.TemporaryDirectory() as tmp, reads.read_session() as metrics:
            path = Path(tmp) / 'artifact.yml'
            path.write_bytes(b'a: one')
            self.assertEqual({'a': 'one'}, context.load_mapping(path))
            path.write_bytes(b'a: two')
            self.assertEqual({'a': 'two'}, context.load_mapping(path))
            self.assertEqual(2, metrics['parses'])

    def test_duplicate_key_validation_is_not_lost_in_cache(self):
        raw = b'a: 1\na: 2'
        with reads.read_session():
            self.assertEqual({'a': 2}, reads.load_yaml(raw))
            with self.assertRaises(reads.DuplicateKeyError):
                reads.load_yaml(raw, reject_duplicates=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'selection.yml'
            path.write_bytes(b'a: {b: 1, b: 2}')
            with self.assertRaisesRegex(context.SelectionError, 'duplicate-selection-key: b'):
                context.load_mapping(path)

    def test_bound_cache_eviction(self):
        with patch.object(reads, 'MAX_ENTRIES', 2), patch.object(reads, 'MAX_BYTES', 16):
            with reads.read_session() as metrics:
                for raw in (b'a: 1', b'a: 2', b'a: 3'):
                    reads.load_yaml(raw)
                self.assertEqual(2, len(metrics['entries']))
                self.assertLessEqual(metrics['bytes'], 16)
                reads.load_yaml(b'a: 1')
                self.assertEqual(4, metrics['parses'])

    def test_no_cache_between_invocations_or_threads(self):
        def run(_):
            with reads.read_session() as metrics:
                reads.load_yaml(b'a: 1')
                return metrics['parses'], metrics['hits']
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual([(1, 0)] * 4, list(workers.map(run, range(4))))

    def test_failure_leaves_no_session(self):
        @reads.read_scoped
        def fail():
            reads.load_yaml(b'a: [')
        with self.assertRaises(yaml.YAMLError):
            fail()
        self.assertIsNone(reads._session.get())

    def test_pure_preparation_reused_only_within_run_and_matching_content(self):
        build = unittest.mock.Mock(return_value={'files': ['one']})
        with reads.read_session() as metrics:
            reads.reuse_preparation('batch', 'hash-one', build)['files'].append('changed')
            self.assertEqual({'files': ['one']}, reads.reuse_preparation('batch', 'hash-one', build))
            self.assertEqual(1, build.call_count)
            self.assertEqual(1, metrics['preparedHits'])
            reads.reuse_preparation('batch', 'hash-two', build)
            self.assertEqual(2, build.call_count)
        self.assertEqual({}, metrics['prepared'])
        with reads.read_session():
            reads.reuse_preparation('batch', 'hash-two', build)
        self.assertEqual(3, build.call_count)


if __name__ == '__main__':
    unittest.main()
