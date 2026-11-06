"""Model B consistency/UX tests. Simulated manual selections are NOT authentication."""
from contextlib import redirect_stdout, redirect_stderr
import copy
import io
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
import decision_reviews as rv
import review_proposals as rp
import review_cli
import consistency_gate as gate
import file_protection as fp
import workspace as wsm
import workspace_cli as cli
import test_decision_requests as request_fixture


class OperationalReviewTests(unittest.TestCase):
    def setUp(self):
        request_fixture.DecisionRequestTests.setUp(self)

    def prepare(self):
        return rp.prepare(self.repo, self.service)

    def select(self, request, outcome='approved', subset=None, **options):
        decisions = request['decisions'] if subset is None else subset
        return rv._record(self.repo, self.service, request['requestId'], {
            d['decisionId']: (outcome, d['alternatives'][0]['id'] if outcome == 'approved' else None)
            for d in decisions}, **options)

    def result(self):
        return gate.current_decision(self.ws, self.repo, self.service)

    def clear(self):
        self.select(self.prepare())
        self.select(self.prepare())
        self.assertEqual(self.result()['status'], gate.CLEARED)

    def test_request_and_forged_name_never_authorize(self):
        request = self.prepare()
        self.assertEqual(request['authority'], 'none')
        self.assertEqual(rv.current(self.repo, self.service), [])
        with self.assertRaises(gate.GateError):
            gate.authorize(self.ws, self.repo, self.service, 'Invented Person', 'Approve')
        self.assertEqual(self.result()['status'], gate.BLOCKED)

    def test_both_legacy_gate_writers_are_retired(self):
        before = fx.sha((self.ws / 'consistency/supplemental.yml').read_bytes())
        with self.assertRaises(gate.GateError):
            gate.record_resolution(self.ws, self.repo, self.service, 'INC-001', 'sparx-governs', 'reason', 'Invented Person')
        self.assertFalse((self.ws / 'consistency/resolutions.yml').exists())
        self.assertEqual(before, fx.sha((self.ws / 'consistency/supplemental.yml').read_bytes()))

    def test_legacy_cli_is_nonwriting_failure(self):
        with patch('pathlib.Path.cwd', return_value=self.repo), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['gate-authorize', self.service, '--by', 'Invented', '--statement', 'yes']), 3)

    def test_no_by_or_pipe_approval_in_manual_interface(self):
        request = self.prepare()
        with patch.object(sys.stdin, 'isatty', return_value=False), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(review_cli.main(['review', self.service, request['requestId']]), 3)
        self.assertEqual(rv.events(self.repo, self.service), [])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            review_cli.main(['review', self.service, request['requestId'], '--by', 'Invented'])

    def test_manual_interactive_selection_records_only_displayed_choice(self):
        request = self.prepare()
        alt = request['decisions'][0]['alternatives'][0]['id']
        with redirect_stdout(io.StringIO()), patch('pathlib.Path.cwd', return_value=self.repo), patch.object(sys.stdin, 'isatty', return_value=True), patch.object(sys.stdout, 'isatty', return_value=True), patch('builtins.input', side_effect=[alt, 'RECORD']):
            self.assertEqual(review_cli.main(['review', self.service, request['requestId']]), 0)
        self.assertEqual(len(rv.current(self.repo, self.service)), 1)

    def test_individual_review_clears_only_finding_then_explicit_resume(self):
        event = self.select(self.prepare())
        self.assertEqual(self.result()['status'], gate.AWAITING_AUTHORIZATION)
        self.select(self.prepare())
        self.assertEqual(gate.check_cleared(self.ws, self.repo, self.service)['status'], gate.CLEARED)
        self.assertTrue(event['selections'][0]['decisionId'])

    def test_partial_group_preserves_pending_and_rejected_items(self):
        detail = yaml.safe_load((self.ws / 'sparx-authoritative-endpoint-detail.yml').read_bytes())
        detail['operations'][0]['activities'][0]['normalized']['validation']['headerrequest']['rows'].append(
            {'headerrequest': 'x-extra', 'required': 'Si', 'type': 'String'})
        fx.dump(self.ws / 'sparx-authoritative-endpoint-detail.yml', detail)
        fx.review(self.ws)
        request = self.prepare()
        self.assertGreater(len(request['decisions']), 1)
        choices = {d['decisionId']: ('approved', d['alternatives'][0]['id']) if n == 0 else ('pending', None)
                   for n, d in enumerate(request['decisions'])}
        event = rv._record(self.repo, self.service, request['requestId'], choices)
        self.assertEqual(len(rv.current(self.repo, self.service)), 1)
        self.assertEqual(self.result()['status'], gate.BLOCKED)
        self.assertEqual(sum(s['outcome'] == 'pending' for s in event['selections']), len(choices) - 1)

    def test_rejection_records_trace_without_authority(self):
        event = self.select(self.prepare(), 'rejected')
        self.assertEqual(event['selections'][0]['outcome'], 'rejected')
        self.assertEqual(rv.current(self.repo, self.service), [])

    def test_revocation_blocks_again(self):
        self.clear()
        first = rv.events(self.repo, self.service)[0]
        rv._revoke(self.repo, self.service, first['eventId'])
        self.assertEqual(self.result()['status'], gate.BLOCKED)

    def test_substitution_is_explicit_and_rebinds_resume(self):
        first = self.select(self.prepare())
        # Same request, different alternative: no silent last-writer-wins.
        request = dr.read(self.repo, self.service, first['requestId'])
        d = request['decisions'][0]
        rv._record(self.repo, self.service, first['requestId'], {d['decisionId']: ('approved', 'swagger-governs')},
                   supersedes=[first['eventId']])
        self.assertEqual(rv.current(self.repo, self.service)[0]['binding']['disposition'], 'swagger-governs')

    def test_conflicting_reviews_fail_closed(self):
        request = self.prepare()
        self.select(request)
        d = request['decisions'][0]
        rv._record(self.repo, self.service, request['requestId'], {d['decisionId']: ('approved', 'swagger-governs')})
        self.assertEqual(self.result()['status'], gate.BLOCKED)

    def test_changed_sources_invalidate_review(self):
        self.clear()
        source = self.repo / 'input/contracts' / (self.service + '.yml')
        source.write_bytes(source.read_bytes() + b'\n# changed')
        self.assertEqual(rv.current(self.repo, self.service), [])

    def test_operational_changes_do_not_invalidate(self):
        self.clear()
        fx.dump(self.ws / 'consistency/gate.yml', {'evaluatedAt': 'later', 'status': 'forged'})
        state = yaml.safe_load((self.ws / 'service-generation-state.yml').read_bytes())
        fx.dump(self.ws / 'service-generation-state.yml', {**state, 'status': 'restarted', 'runId': 'new'})
        self.assertEqual(self.result()['status'], gate.CLEARED)

    def test_derived_http_specs_do_not_create_approval_loop(self):
        self.clear()
        fx.dump(self.ws / 'service-spec.yml', {'service': {'name': self.service}, 'derived': 'consolidated'})
        self.assertEqual(self.result()['status'], gate.CLEARED)

    def test_duplicate_request_and_current_review_reused(self):
        a, b = self.prepare(), self.prepare()
        self.assertEqual(a, b)
        self.clear()
        self.assertIsNone(self.prepare()['requestId'])

    def test_unselected_decisions_never_gain_authority(self):
        req = self.prepare()
        self.select(req, 'pending')
        self.assertEqual(rv.current(self.repo, self.service), [])

    def test_service_isolation_rejects_copied_review(self):
        self.select(self.prepare())
        other = self.repo / '.factory/services/other/decision-reviews'
        shutil.copytree(rv.directory(self.repo, self.service), other)
        with self.assertRaises(dc.DecisionError):
            rv.current(self.repo, 'other')

    def test_worktree_execution_scope_never_portable(self):
        self.clear()
        actual = rv.location(self.repo)
        with patch.object(rv, 'location', return_value={**actual, 'worktree': '/different-tree'}):
            self.assertEqual(rv.current(self.repo, self.service), [])

    def test_explicit_functional_scope_can_match_same_common_git(self):
        self.select(self.prepare(), scope='functional-common-git')
        actual = rv.location(self.repo)
        with patch.object(rv, 'location', return_value={**actual, 'worktree': '/different-tree'}):
            self.assertEqual(len(rv.current(self.repo, self.service)), 1)
        with patch.object(rv, 'location', return_value={'repository': 'other', 'worktree': actual['worktree']}):
            self.assertEqual(rv.current(self.repo, self.service), [])

    def test_resume_cannot_receive_portable_scope(self):
        self.select(self.prepare())
        with self.assertRaises(dc.DecisionError):
            self.select(self.prepare(), scope='functional-common-git')

    def test_manual_functional_import_requires_same_context_and_local_adoption(self):
        temp = tempfile.TemporaryDirectory(prefix='review-other-worktree-')
        self.addCleanup(temp.cleanup)
        other = Path(temp.name)
        shutil.copytree(self.repo, other, dirs_exist_ok=True)
        def same_common(path):
            return {'repository': 'synthetic-common-directory', 'worktree': Path(path).resolve().as_posix()}
        with patch.object(rv, 'location', side_effect=same_common):
            event = self.select(self.prepare(), scope='functional-common-git')
            self.assertEqual(rv.current(other, self.service), [])
            adopted = rv._import_functional(other, self.service, self.repo, event['eventId'])
            self.assertEqual(len(rv.current(other, self.service)), 1)
            self.assertEqual(adopted['selections'][0]['decisionId'], event['selections'][0]['decisionId'])
            fx.dump(other / '.factory/services' / self.service / 'consistency/supplemental.yml', {})
            with self.assertRaises(dc.DecisionError):
                rv._import_functional(other, self.service, self.repo, event['eventId'])

    def test_historical_yaml_needs_new_review_without_modification(self):
        record = {'decisionId': 'human-reviewed-old', 'humanReviewed': True, 'approvedBy': 'Invented', 'machineEffects': {'rule': 'OR'}}
        path = self.ws / 'sparx-reviewed-decisions.yml'
        fx.dump(path, {'decisions': [record]})
        before = path.read_bytes()
        with self.assertRaises(dc.DecisionError):
            rv.require_records(self.ws, [record])
        self.select(rp.prepare(self.repo, self.service, 'historical', decision_id=record['decisionId']))
        self.assertEqual(rv.require_records(self.ws, [record]), [record])
        self.assertEqual(before, path.read_bytes())

    def test_historical_record_cannot_extend_another_services_scope(self):
        record = {'decisionId': 'human-reviewed-other', 'target': {'service': 'different-service'}}
        fx.dump(self.ws / 'sparx-reviewed-decisions.yml', {'decisions': [record]})
        request = rp.prepare(self.repo, self.service, 'historical', decision_id=record['decisionId'])
        with self.assertRaises(dc.DecisionError):
            self.select(request)

    def test_legacy_resolution_and_authorization_flags_are_inert(self):
        result = self.result()
        item = result['blocking'][0]
        fx.dump(self.ws / 'consistency/resolutions.yml', {'resolutions': [{'findingFingerprint': item['fingerprint'],
                'status': 'approved', 'disposition': 'sparx-governs', 'approvedBy': 'Invented',
                'approvedAt': 'now', 'scope': [self.service], 'justification': 'because'}]})
        fx.dump(self.ws / 'consistency/authorization.yml', {'evaluationHash': result['evaluationHash'], 'authorizedBy': 'Invented'})
        self.assertEqual(self.result()['status'], gate.BLOCKED)

    def test_direct_decide_does_not_trust_legacy_yaml(self):
        registry = self.result()['_registry']
        result = gate.decide(registry, [], set(), {'evaluationHash': 'x', 'authorizedBy': 'Invented'}, True)
        self.assertEqual(result['status'], gate.BLOCKED)

    def test_manual_content_requires_review_bound_to_file_and_plan(self):
        out = self.repo / 'output' / self.service
        out.mkdir(parents=True)
        (out / 'manual.java').write_text('manual')
        fx.dump(self.ws / 'service-spec.yml', {'service': {'name': self.service}})
        fx.dump(self.ws / 'implementation-plan.yml', {'service': {'outputDirectory': 'output/' + self.service},
                 'files': {'generate': [{'path': 'manual.java', 'action': 'update'}]}})
        planned = [{'path': 'manual.java', 'action': 'update'}]
        self.assertTrue(fp.blocked(fp.evaluate(out, planned, self.ws)))
        with self.assertRaises(fp.ProtectedFileError):
            fp.authorize_overwrite(out, 'manual.java', self.ws, 'Invented', 'yes')
        req = rp.prepare(self.repo, self.service, 'overwrite', path='manual.java')
        self.select(req)
        self.assertFalse(fp.blocked(fp.evaluate(out, planned, self.ws)))
        (out / 'manual.java').write_text('later edit')
        self.assertTrue(fp.blocked(fp.evaluate(out, planned, self.ws)))

    def test_malformed_or_unavailable_reviews_fail_closed(self):
        self.clear()
        path = next(rv.directory(self.repo, self.service).glob('review-*.yml'))
        path.write_text('bad: [')
        self.assertEqual(self.result()['status'], gate.BLOCKED)

    def test_stale_request_cannot_be_recorded(self):
        req = self.prepare()
        fx.dump(self.ws / 'consistency/supplemental.yml', {'reviewed': False})
        with self.assertRaises(dc.DecisionError):
            self.select(req)

    def test_unbound_v1_request_never_authorizes(self):
        proposal = copy.deepcopy(self.proposal)
        proposal['decisions'][0]['classification'] = 'explicit-authorization'
        proposal['purpose'] = 'authorize-operation'
        req = dr.create(self.repo, self.service, proposal)
        with self.assertRaises(dc.DecisionError):
            self.select(req)

    def test_runner_refuses_manual_review_and_untrusted_helpers(self):
        ws = wsm.Workspace(self.repo, self.service)
        for path in (HERE.parent / 'scripts/review_cli.py', self.ws / 'helper.py'):
            with self.assertRaises(wsm.WorkspaceError):
                wsm.run_script(ws, path, [])

    def test_model_b_warning_is_explicit(self):
        self.assertIn('H-02 remains open', rv.WARNING)
        self.assertIn('not strong human authentication', rv.WARNING)


class AgentPermissionTests(unittest.TestCase):
    def test_native_v2_all_agents_deny_sensitive_paths_and_commands(self):
        from fnmatch import fnmatchcase
        for path in (HERE.parents[1] / 'agents').glob('*.md'):
            data = yaml.safe_load(path.read_text(encoding='utf8').split('---')[1])
            self.assertNotIn('permission', data, path)
            rules = data['permissions']
            def effect(action, resource):
                matches = [r['effect'] for r in rules if r['action'] in ('*', action)
                           and fnmatchcase(resource.lower(), r['resource'].lower())]
                return matches[-1] if matches else 'ask'
            for resource in ('python .opencode/skills/service-workspace/scripts/review_cli.py review svc request-x',
                             'python .opencode/skills/service-workspace/scripts/workspace_cli.py gate-authorize svc --by Invented',
                             'python .opencode/skills/service-workspace/scripts/workspace_cli.py protect-authorize svc a --by Invented'):
                self.assertEqual(effect('shell', resource), 'deny', (path, resource))
            for name in ('decision-reviews/review-x.yml', 'consistency/authorization.yml', 'consistency/resolutions.yml',
                         'sparx-reviewed-decisions.yml', 'overwrite-authorizations.yml'):
                self.assertEqual(effect('edit', '.factory/services/svc/' + name), 'deny', (path, name))


if __name__ == '__main__':
    unittest.main()
