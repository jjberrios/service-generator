"""Pure preparation reuse must not cache authority or file protection."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_batch_shell import BatchShellFixture, bp, bm, fm


class BatchPreparationTests(BatchShellFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.plan()

    def test_preflight_and_publish_render_and_plan_once(self):
        with patch.object(bp, 'build', wraps=bp.build) as build, \
                patch.object(bm, 'render_project', wraps=bm.render_project) as render:
            report = fm.materialize(self.repo, self.service)
        self.assertEqual('complete', report['status'])
        self.assertEqual(1, build.call_count)
        self.assertEqual(1, render.call_count)

    def test_modified_source_after_preview_blocks_publication(self):
        original = bm.render_project
        def change(plan, repo):
            result = original(plan, repo)
            binding = plan['batch']['sourceBindings'][0]
            source = repo / binding['path']
            source.write_bytes(source.read_bytes() + b' changed')
            return result
        with patch.object(bm, 'render_project', side_effect=change):
            with self.assertRaises(Exception):
                fm.materialize(self.repo, self.service)
        self.assertFalse((self.repo / 'output' / self.service).exists())

    def test_new_undeclared_template_after_preview_is_not_hidden(self):
        original = bm.render_project
        def change(plan, repo):
            result = original(plan, repo)
            (repo / self.ARCH / 'template/undeclared.txt').write_text('unexpected')
            return result
        with patch.object(bm, 'render_project', side_effect=change):
            with self.assertRaises(Exception):
                fm.materialize(self.repo, self.service)
        self.assertFalse((self.repo / 'output' / self.service).exists())

    def test_untracked_manual_file_created_after_preview_is_protected(self):
        original = bm.render_project
        target = self.repo / 'output' / self.service / 'pom.xml'
        def change(plan, repo):
            result = original(plan, repo)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('manual work')
            return result
        with patch.object(bm, 'render_project', side_effect=change):
            with self.assertRaises(fm.MaterializationError):
                fm.materialize(self.repo, self.service)
        self.assertEqual('manual work', target.read_text())
        self.assertFalse((target.parent / '.generation-manifest.yml').exists())


if __name__ == '__main__':
    unittest.main()
