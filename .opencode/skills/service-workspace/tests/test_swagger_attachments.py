"""Attachment review is mandatory with Swagger, including legacy authorities."""
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))
sys.path.insert(0, str(HERE.parent.parent / 'parse-sparx/scripts'))
import fixtures as fx
import consistency_gate as gate
from sparx_attachments import inventory, authorized_pages


class SwaggerAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = fx.make_repo(Path(self.tmp.name).resolve())
        self.ws = fx.make_service(self.repo, 'sample')

    def evaluate(self):
        return gate.current_decision(self.ws, self.repo, 'sample', review_decisions=False)

    def test_legacy_authority_requires_inventory(self):
        self.assertNotIn('contractMode', gate.load(self.ws / 'sparx-target-authority.yml'))
        (self.ws / 'sparx-attachments.yml').unlink()
        with self.assertRaisesRegex(gate.GateError, 'attachment inventory required'):
            self.evaluate()

    def test_swagger_review_requires_attachment_binding(self):
        for mode in (None, 'openapi'):
            with self.subTest(contractMode=mode):
                authority = gate.load(self.ws / 'sparx-target-authority.yml')
                if mode:
                    authority['contractMode'] = mode
                fx.dump(self.ws / 'sparx-target-authority.yml', authority)
                fx.review(self.ws)
                review = gate.load(self.ws / 'consistency/supplemental.yml')
                del review['reviewedAgainst']['attachmentsSha256']
                fx.dump(self.ws / 'consistency/supplemental.yml', review)
                self.assertEqual(self.evaluate()['status'], gate.SEMANTIC_REVIEW_PENDING)

    def test_changed_linked_document_requires_inventory_and_review_refresh(self):
        root = self.repo / 'input/sparx/P'
        (root / 'sample.htm').write_text('<a href="rules.txt">Rules</a>', encoding='utf-8')
        doc = root / 'rules.txt'
        doc.write_text('Documented rules', encoding='utf-8')
        authority = gate.load(self.ws / 'sparx-target-authority.yml')
        fx.dump(self.ws / 'sparx-attachments.yml', inventory(self.repo, root, authorized_pages(authority)))
        fx.review(self.ws)
        self.assertEqual(self.evaluate()['status'], gate.AWAITING_AUTHORIZATION)
        doc.write_text('Changed documented rules', encoding='utf-8')
        with self.assertRaisesRegex(gate.GateError, 'inventory incomplete or stale'):
            self.evaluate()
        fx.dump(self.ws / 'sparx-attachments.yml', inventory(self.repo, root, authorized_pages(authority)))
        self.assertEqual(self.evaluate()['status'], gate.SEMANTIC_REVIEW_PENDING)
