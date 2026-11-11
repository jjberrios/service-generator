"""Synthetic source-only HTTP and attachment regressions; no real service or Maven."""
from pathlib import Path
import hashlib
import sys
import subprocess
import tempfile
import unittest
import zipfile
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import consistency_gate as gate
import sparx_only
from sparx_attachments import inventory
from workspace import resolve_sparx_root


class SparxOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve()
        self.root = self.repo / 'input/sparx'
        (self.root / 'js/data').mkdir(parents=True)
        self.page = 'input/sparx/service.htm'
        (self.repo / self.page).write_text('<p>Documented operation</p>', encoding='utf-8')
        self.ws = self.repo / '.factory/services/example-service'
        (self.ws / 'consistency').mkdir(parents=True)
        self.authority = {'kind': 'sparx-target-authority', 'contractMode': 'sparx-only',
                          'target': {'name': 'example-service', 'sourceRoot': 'input/sparx'},
                          'selection': {'status': 'resolved', 'authoritativeBranchRootId': '0.1'},
                          'hierarchySources': {'tocFiles': {}},
                          'branches': [{'branchRootId': '0.1', 'service': {'page': 'service.htm'},
                                        'operations': [{'method': 'GET', 'path': '/x'}]}]}
        self.dump('service-generation-state.yml', {'targetService': 'example-service', 'inputs': {'contractMode': 'sparx-only'}})
        self.dump('sparx-target-authority.yml', self.authority)
        self.dump('sparx-attachments.yml', inventory(self.repo, self.root, [self.page]))
        op = {'method': 'GET', 'path': '/x', 'operationId': 'getX', 'parameters': {}, 'requestBody': None,
              'responses': {'200': {'description': 'documented'}}, 'security': [],
              'lifecycle': {'disposition': 'active', 'state': 'ACTIVE'}}
        citation = {'path': self.page, 'sha256': self.sha(self.repo / self.page), 'locator': 'paragraph 1', 'quote': 'Documented operation'}
        self.contract = {'kind': 'sparx-http-contract', 'targetService': 'example-service', 'operations': [op],
                         'claims': {p: citation for p in sparx_only.leaf_paths([op], '/operations')}, 'unresolved': []}
        self.dump('sparx-http-contract.yml', self.contract)
        self.dump('sparx-spec.yml', {'unresolved': {}})
        self.dump('sparx-authoritative-endpoint-detail.yml', {})

    def dump(self, name, obj):
        (self.ws / name).write_text(yaml.safe_dump(obj, sort_keys=False), encoding='utf-8')

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def evaluate(self):
        return gate.current_decision(self.ws, self.repo, 'example-service', review_decisions=False)

    def review(self):
        names = ('sparx-http-contract.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'sparx-spec.yml', 'sparx-attachments.yml')
        self.dump('consistency/sparx-only-review.yml', {'reviewed': True, 'reviewedBy': 'semantic reviewer',
                  'reviewedAgainst': {n: self.sha(self.ws / n) for n in names}, 'findings': []})

    def test_repo_root_aliases_without_project_folder(self):
        for path in ('input/sparx', '/input/sparx/', '/sparx', 'sparx'):
            self.assertEqual(resolve_sparx_root(self.repo, path), 'input/sparx')

    def test_http_without_swagger_needs_review_and_authorization(self):
        self.assertEqual(self.evaluate()['status'], gate.SEMANTIC_REVIEW_PENDING)
        self.review()
        result = self.evaluate()
        self.assertEqual(result['status'], gate.AWAITING_AUTHORIZATION)
        self.assertEqual(result['comparison'], 'not-applicable-no-swagger')
        self.assertFalse((self.ws / 'openapi-spec.yml').exists())

    def test_existing_swagger_cannot_be_ignored(self):
        self.dump('openapi-spec.yml', {})
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)

    def test_supplied_swagger_path_is_not_absence(self):
        self.dump('service-generation-state.yml', {'targetService': 'example-service',
                  'inputs': {'contractMode': 'sparx-only', 'openapi': 'input/contracts/missing.yml'}})
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)

    def test_ambiguous_or_unclassified_http_methods_block(self):
        branch = self.authority['branches'][0]
        branch['operations'][0]['ambiguity'] = 'duplicate method'
        self.dump('sparx-target-authority.yml', self.authority)
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)
        branch['operations'][0].pop('ambiguity')
        branch['operations'].append({'method': 'POST', 'path': '/x'})
        self.dump('sparx-target-authority.yml', self.authority)
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)

    def test_authority_cli_discovers_only_target_owned_methods_without_swagger(self):
        rows = [
            ['0', '', 'Root', 'root.htm', '', '', '', 'root-guid', 'Package'],
            ['0.1', '', 'Services', 'package.htm', '', '', '', 'package-guid', 'Package'],
            ['0.1:1', '', '«Servicio» example-service', 'service.htm', '', 's1', '', '', 'Class', 's-guid'],
            ['0.1:2', '', '«Metodo» GET-/x', 'method.htm', '', 'm1', 's1', '', 'Class', 'm-guid'],
            ['0.1:3', '', '«Metodo» GET-/x', 'foreign.htm', '', 'm2', 'other-service', '', 'Class', 'f-guid'],
        ]
        (self.root / 'js/data/toc.xml').write_text('\n'.join('new Array(' + ','.join('"' + f + '"' for f in row) + ');' for row in rows), encoding='utf-8')
        script = Path(sparx_only.__file__).resolve().parents[2] / 'parse-sparx/scripts/resolve_target_authority.py'
        result = subprocess.run([sys.executable, str(script), 'input/sparx', str(self.ws / 'resolved.yml'),
                                 '--target', 'example-service', '--sparx-only'], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        authority = yaml.safe_load((self.ws / 'resolved.yml').read_text(encoding='utf-8'))
        self.assertEqual(authority['contractMode'], 'sparx-only')
        self.assertEqual(authority['selection']['status'], 'resolved')
        operation = authority['branches'][0]['operations'][0]
        self.assertEqual((operation['method'], operation['path']), ('GET', '/x'))
        self.assertEqual(operation['sparxMethodElements'], 1)
        self.assertFalse(authority['branches'][0]['sparxOnlyMethods'])
        self.assertFalse((self.ws / 'openapi-spec.yml').exists())

    def test_changed_source_or_missing_field_citation_blocks(self):
        self.contract['claims'].pop('/operations/0/security')
        self.dump('sparx-http-contract.yml', self.contract)
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)
        (self.repo / self.page).write_text('changed', encoding='utf-8')
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)

    def test_other_branch_citation_and_unknown_lifecycle_block(self):
        self.contract['operations'][0]['lifecycle']['disposition'] = 'unknown'
        self.dump('sparx-http-contract.yml', self.contract)
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)
        self.contract['operations'][0]['lifecycle']['disposition'] = 'active'
        path = self.root / 'other-branch.txt'
        path.write_text('Documented operation', encoding='utf-8')
        for claim in self.contract['claims'].values():
            claim.update(path='input/sparx/other-branch.txt', sha256=self.sha(path))
        self.dump('sparx-http-contract.yml', self.contract)
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)

    def test_attachments_docx_missing_remote_and_traversal(self):
        path = self.root / 'rules.docx'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="urn:test"><w:p><w:r><w:t>Regla exacta</w:t></w:r></w:p></w:document>')
        (self.repo / self.page).write_text('<a href="rules.docx">rules</a><a href="missing.pdf">missing</a>'
                                         '<object data="https://example.test/rules.pdf"></object>'
                                         '<a href="../../outside.docx">outside</a><a href="model.htm">navigation</a>', encoding='utf-8')
        result = inventory(self.repo, self.root, [self.page])
        self.assertEqual(len(result['documents']), 4)
        self.assertEqual(result['documents'][0]['text'], 'Regla exacta')
        self.assertEqual([d['status'] for d in result['documents']],
                         ['extracted', 'missing-local-file', 'external-or-absolute-reference', 'escapes-source-root'])

    def test_changed_attachment_invalidates_review(self):
        (self.repo / self.page).write_text('<a href="rules.txt">rules</a>', encoding='utf-8')
        path = self.root / 'rules.txt'
        path.write_text('Documented operation', encoding='utf-8')
        for claim in self.contract['claims'].values():
            claim.update(path='input/sparx/rules.txt', sha256=self.sha(path))
        self.dump('sparx-http-contract.yml', self.contract)
        self.dump('sparx-attachments.yml', inventory(self.repo, self.root, [self.page]))
        self.review()
        self.assertEqual(self.evaluate()['status'], gate.AWAITING_AUTHORIZATION)
        path.write_text('changed', encoding='utf-8')
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)

    def test_corrupt_and_unsupported_documents_remain_explicit_gaps(self):
        (self.repo / self.page).write_text('<a href="bad.pdf">pdf</a><a href="bad.docx">word</a><a href="old.doc">legacy</a>', encoding='utf-8')
        for name in ('bad.pdf', 'bad.docx', 'old.doc'):
            (self.root / name).write_bytes(b'not a valid document')
        records = inventory(self.repo, self.root, [self.page])['documents']
        self.assertEqual([r['status'] for r in records], ['unverified'] * 3)
        self.assertTrue(all(r.get('reason') and r.get('sha256') for r in records))

    def test_unresolved_behavior_or_semantic_findings_block(self):
        self.review()
        self.dump('sparx-spec.yml', {'unresolved': {'missingEvidence': ['required rule']}})
        self.assertEqual(self.evaluate()['status'], gate.BLOCKED)


if __name__ == '__main__':
    unittest.main()
