"""Stage 2A proposals: temporary synthetic services only, no real approvals."""
from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))
import fixtures as fx
import decision_context as dc
import decision_requests as dr
import consistency_gate as gate
import workspace_cli as cli

REPO = HERE.parents[3]


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class DecisionRequestTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='decision-2a-')
        self.addCleanup(tmp.cleanup)
        self.repo = fx.make_repo(Path(tmp.name))
        self.service = 'request-example'
        self.ws = fx.make_service(self.repo, self.service, swagger_required=True)
        self.arch = 'archetypes/claro-spring-ms/v1.0.1'
        shutil.copytree(REPO / self.arch, self.repo / self.arch)
        fx.dump(self.ws / 'service-generation-state.yml', {'targetService': self.service, 'archetype': {'path': self.arch}})
        fx.review(self.ws)
        self.proposal = {'schemaVersion': 1, 'purpose': 'clarify-analysis', 'decisions': [{
            'key': 'inspect-validation', 'classification': 'analysis-required',
            'problem': 'Confirm the authoritative validation rule.',
            'findingFingerprints': [],
            'evidence': [{'path': 'sparx-authoritative-endpoint-detail.yml', 'pointer': '/operations/0',
                          'summary': 'The documented validation activity.'}],
            'alternatives': [{'id': 'inspect', 'description': 'Expand the cited analysis.',
                              'effects': ['No approval and no generation.']},
                             {'id': 'ask', 'description': 'Ask for missing documentation.',
                              'effects': ['Analysis remains incomplete.']}],
            'recommendation': {'alternativeId': 'inspect', 'rationale': 'Evidence is available.', 'evidenceIndexes': [0]}}]}

    def context(self):
        return dc.build(self.repo, self.service, self.proposal['purpose'])

    def create(self):
        return dr.create(self.repo, self.service, self.proposal)

    def test_valid_creation_is_proposal_only(self):
        request = self.create()
        self.assertEqual(request['authority'], 'none')
        self.assertEqual(request['schemaVersion'], 1)
        self.assertEqual(dr.read(self.repo, self.service, request['requestId']), request)

    def test_serialization_and_identifiers_are_deterministic(self):
        a = dr.assemble(self.repo, self.service, self.proposal)
        reverse = dict(reversed(list(self.proposal.items())))
        b = dr.assemble(self.repo, self.service, reverse)
        self.assertEqual(dr.encode(a), dr.encode(b))
        self.assertEqual(a['context'], self.context())

    def test_duplicate_creation_reuses_bytes_without_overwrite(self):
        a = self.create()
        before = tree(self.ws / 'decision-requests')
        b = self.create()
        self.assertEqual(a, b)
        self.assertEqual(before, tree(self.ws / 'decision-requests'))
        self.assertEqual(len(before), 1)

    def test_modified_duplicate_is_not_overwritten(self):
        a = self.create()
        path = self.ws / 'decision-requests' / (a['requestId'] + '.yml')
        path.write_bytes(b'manual: true\n')
        with self.assertRaises(dc.DecisionError):
            self.create()
        self.assertEqual(path.read_bytes(), b'manual: true\n')

    def test_live_source_change_marks_request_stale(self):
        a = self.create()
        source = self.repo / 'input/contracts' / (self.service + '.yml')
        source.write_bytes(source.read_bytes() + b'\n# changed\n')
        result = dr.status(self.repo, self.service, a['requestId'])
        self.assertEqual(result['validity'], 'stale')
        self.assertNotEqual(result['contextId'], result['currentContextId'])

    def test_cited_sparx_page_change_is_detected(self):
        source = self.repo / 'input/sparx/P/EARoot/EA2/EA6/a.htm'
        source.parent.mkdir(parents=True)
        source.write_text('activity one')
        a = self.context()
        source.write_text('activity two')
        self.assertNotEqual(a['contextId'], self.context()['contextId'])

    def test_removed_evidence_is_stale_not_a_new_approval(self):
        self.proposal['decisions'][0]['evidence'][0]['path'] = 'input/contracts/' + self.service + '.yml'
        a = self.create()
        (self.repo / self.proposal['decisions'][0]['evidence'][0]['path']).unlink()
        self.assertEqual(dr.status(self.repo, self.service, a['requestId'])['validity'], 'stale')

    def test_review_decisions_findings_and_archetype_changes_invalidate(self):
        for name, value in (
            ('consistency/supplemental.yml', {'reviewed': False}),
            ('sparx-reviewed-decisions.yml', {'decisions': [{'id': 'historical', 'rule': 'OR'}]}),
            ('sparx-authoritative-endpoint-detail.yml', {'operations': []})):
            before = self.context()['contextId']
            fx.dump(self.ws / name, value)
            self.assertNotEqual(before, self.context()['contextId'])
        before = self.context()['contextId']
        manifest = self.repo / self.arch / 'archetype.yml'
        manifest.write_bytes(manifest.read_bytes() + b'\n# fixture change\n')
        self.assertNotEqual(before, self.context()['contextId'])

    def test_checkpoint_status_gate_reports_and_request_files_are_not_context(self):
        before = self.context()
        fx.dump(self.ws / 'service-generation-state.yml', {'targetService': self.service,
            'archetype': {'path': self.arch}, 'status': 'changed', 'evaluatedAt': 'later', 'runId': 'run-two'})
        fx.dump(self.ws / 'consistency/gate.yml', {'status': 'CLEARED'})
        fx.dump(self.ws / 'materialization-report.yml', {'status': 'complete'})
        self.create()
        self.assertEqual(before, self.context())

    def test_no_gate_checkpoint_or_approval_side_effects(self):
        before_gate = gate.current_decision(self.ws, self.repo, self.service)
        before = tree(self.ws)
        with patch.object(gate, 'authorize', side_effect=AssertionError('approval forbidden')), \
             patch.object(gate, 'record_resolution', side_effect=AssertionError('approval forbidden')), \
             patch.object(gate, 'evaluate', side_effect=AssertionError('persistence forbidden')):
            a = self.create()
            dr.status(self.repo, self.service, a['requestId'])
            dr.list_requests(self.repo, self.service)
        after = {k: v for k, v in tree(self.ws).items() if not k.startswith('decision-requests/')}
        self.assertEqual(before, after)
        after_gate = gate.current_decision(self.ws, self.repo, self.service)
        self.assertEqual(before_gate['status'], after_gate['status'])
        self.assertEqual(before_gate['evaluationHash'], after_gate['evaluationHash'])
        self.assertNotEqual(after_gate['status'], gate.CLEARED)

    def test_service_isolation(self):
        a = self.create()
        other = 'other-service'
        ws = fx.make_service(self.repo, other)
        fx.dump(ws / 'service-generation-state.yml', {'targetService': other, 'archetype': {'path': self.arch}})
        b = dr.create(self.repo, other, self.proposal)
        self.assertNotEqual(a['requestId'], b['requestId'])
        self.assertNotEqual(a['context']['contextId'], b['context']['contextId'])
        with self.assertRaises(dc.DecisionError):
            dr.read(self.repo, other, a['requestId'])

    def test_repository_location_is_not_trusted_identity(self):
        self.assertEqual(self.context()['repository']['identityKind'], 'local-location-untrusted')

    def test_conflicting_runtime_archetype_selection_is_not_ignored(self):
        with patch.dict(os.environ, {'SERVICE_ARCHETYPE_PATH': 'archetypes/other/v1.0.0'}):
            with self.assertRaises(ValueError):
                self.context()

    def test_path_traversal_absolute_ads_and_cross_service_ids_rejected(self):
        for bad in ('../bad', 'C:/bad', 'a/b', 'request-' + 'a' * 64 + ':stream'):
            with self.assertRaises(ValueError):
                dr.read(self.repo, self.service, bad)
        for bad in ('../bad', 'C:/bad', 'input/contracts/../../bad', 'application.properties',
                    '.factory/services/other/authorization.yml'):
            proposal = copy.deepcopy(self.proposal)
            proposal['decisions'][0]['evidence'][0]['path'] = bad
            with self.assertRaises(ValueError):
                dr.assemble(self.repo, self.service, proposal)

    def test_malicious_source_path_rejected_before_legacy_evaluator(self):
        for bad in ('../outside', 'input/contracts/../../outside', 'C:/outside'):
            fx.dump(self.ws / 'openapi-spec.yml', {'source': {'path': bad}})
            with patch.object(gate, 'current_decision', side_effect=AssertionError('must validate first')):
                with self.assertRaises(ValueError):
                    self.context()

    def test_malformed_contracts_and_approval_fields_rejected(self):
        for change in ({'schemaVersion': 2}, {'schemaVersion': True}, {'approved': True},
                       {'purpose': 'auto-approve'}, {'decisions': []}, {'decisions': 'bad'}):
            p = {**self.proposal, **change}
            with self.assertRaises((ValueError, TypeError)):
                dr.assemble(self.repo, self.service, p)
        p = copy.deepcopy(self.proposal)
        p['decisions'][0]['authorizedBy'] = 'invented'
        with self.assertRaises(ValueError):
            dr.assemble(self.repo, self.service, p)

    def test_unknown_findings_and_unfounded_recommendations_rejected(self):
        p = copy.deepcopy(self.proposal)
        p['decisions'][0]['findingFingerprints'] = ['unknown']
        with self.assertRaises(ValueError):
            dr.assemble(self.repo, self.service, p)
        p = copy.deepcopy(self.proposal)
        p['decisions'][0]['recommendation']['evidenceIndexes'] = [9]
        with self.assertRaises(ValueError):
            dr.assemble(self.repo, self.service, p)

    def test_duplicate_individual_keys_and_alternatives_rejected(self):
        p = copy.deepcopy(self.proposal)
        p['decisions'].append(copy.deepcopy(p['decisions'][0]))
        with self.assertRaises(ValueError):
            dr.assemble(self.repo, self.service, p)
        p = copy.deepcopy(self.proposal)
        p['decisions'][0]['alternatives'].append(copy.deepcopy(p['decisions'][0]['alternatives'][0]))
        with self.assertRaises(ValueError):
            dr.assemble(self.repo, self.service, p)

    def test_tampered_self_attested_approval_is_rejected(self):
        request = self.create()
        request['approved'] = True
        path = self.ws / 'decision-requests' / (request['requestId'] + '.yml')
        fx.dump(path, request)
        with self.assertRaises(ValueError):
            dr.read(self.repo, self.service, request['requestId'])

    def test_grouping_keeps_individual_identity_and_order_is_stable(self):
        a = self.create()
        second = copy.deepcopy(self.proposal['decisions'][0])
        second['key'] = 'other-question'
        self.proposal['decisions'].append(second)
        b = self.create()
        self.assertEqual(a['decisions'][0]['decisionId'], b['decisions'][0]['decisionId'])
        self.assertNotEqual(b['decisions'][0]['decisionId'], b['decisions'][1]['decisionId'])
        self.proposal['decisions'].reverse()
        self.assertEqual(b, self.create())

    def test_classification_representation_does_not_change_autonomy(self):
        context = self.context()
        for classification in dr.CLASSES:
            p = copy.deepcopy(self.proposal)
            p['decisions'][0]['classification'] = classification
            if classification == 'human-functional':
                p['decisions'][0]['findingFingerprints'] = [context['findings'][0]['fingerprint']]
            self.assertEqual(dr.assemble(self.repo, self.service, p)['authority'], 'none')

    def test_cli_create_show_context_list_status_and_stale(self):
        fx.dump(self.ws / 'proposal.yml', self.proposal)
        def run(args):
            out, err = io.StringIO(), io.StringIO()
            old = Path.cwd()
            try:
                os.chdir(self.repo)
                with redirect_stdout(out), redirect_stderr(err):
                    code = cli.main(args)
            finally:
                os.chdir(old)
            return code, yaml.safe_load(out.getvalue()), err.getvalue()
        code, request, _ = run(['decision-request-create', self.service, '--proposal', 'proposal.yml'])
        self.assertEqual(code, 0)
        rid = request['requestId']
        for args in (['decision-request-show', self.service, rid],
                     ['decision-request-context', self.service, '--request', rid],
                     ['decision-request-context', self.service, '--purpose', 'clarify-analysis'],
                     ['decision-request-list', self.service], ['decision-request-status', self.service, rid]):
            self.assertEqual(run(args)[0], 0, args)
        self.assertEqual(run(['decision-request-stale', self.service])[1], [])
        fx.dump(self.ws / 'consistency/supplemental.yml', {'reviewed': False})
        self.assertEqual(run(['decision-request-status', self.service, rid])[0], 4)
        self.assertEqual(len(run(['decision-request-stale', self.service])[1]), 1)
        self.assertEqual(run(['decision-request-create', self.service, '--proposal', '../bad'])[0], 3)

    def test_duplicate_yaml_keys_rejected(self):
        path = self.ws / 'bad.yml'
        path.write_text('purpose: clarify-analysis\npurpose: authorize-operation\n')
        from generation_context import load_mapping
        with self.assertRaises(ValueError):
            load_mapping(path)

    def test_symlink_request_directory_rejected(self):
        target = self.repo / 'elsewhere'
        target.mkdir()
        try:
            (self.ws / 'decision-requests').symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation unavailable for this OS identity')
        with self.assertRaises(ValueError):
            self.create()
        self.assertEqual(list(target.iterdir()), [])

    def test_jdbc_profile_uses_existing_adapter(self):
        arch = 'archetypes/claro-spring-java-8/v1.0.0'
        shutil.copytree(REPO / arch, self.repo / arch)
        fx.dump(self.ws / 'service-generation-state.yml', {'targetService': self.service, 'archetype': {'path': arch}})
        self.assertEqual(self.create()['context']['archetype']['profile'], 'war-jdbc-callablestatement-junit4')

    def test_batch_profile_sources_and_semantic_review_without_http(self):
        arch = 'archetypes/claro-java-8-shell/v1.0.0'
        shutil.copytree(REPO / arch, self.repo / arch)
        (self.ws / 'openapi-spec.yml').unlink()
        (self.ws / 'sparx-authoritative-endpoint-detail.yml').unlink()
        fx.dump(self.ws / 'service-generation-state.yml', {'targetService': self.service, 'archetype': {'path': arch}})
        source = self.repo / 'input/sparx/P/flow.htm'
        source.write_text('synthetic flow')
        fx.dump(self.ws / 'sparx-spec.yml', {'service': {'name': self.service, 'profile': 'batch-shell'},
            'batch': {'sourceBindings': [{'id': 'ea', 'path': 'input/sparx/P/flow.htm', 'sha256': fx.sha(source.read_bytes())}]}})
        fx.dump(self.ws / 'consistency/batch-review.yml', {'reviewed': False, 'findings': ['analyze']})
        self.proposal['decisions'][0]['evidence'][0]['path'] = 'sparx-spec.yml'
        a = self.create()
        self.assertEqual(a['context']['archetype']['profile'], 'batch-shell-jar-spring-xml-log4j-sftp-junit4')
        self.assertEqual(a['context']['audit']['comparison'], 'not-applicable-non-http-batch')
        source.write_text('changed flow')
        self.assertEqual(dr.status(self.repo, self.service, a['requestId'])['validity'], 'stale')


if __name__ == '__main__':
    unittest.main()
