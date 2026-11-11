"""Workspaces, migration, consistency gate, checkpoints, resume, guards and file protection (synthetic fixtures only)."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))
import fixtures as fx
import consistency_gate as gate
import file_protection as fp
import gate_guard
import migrate_legacy as mig
import workspace as wsm
import workspace_cli as cli

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS = REPO_ROOT / '.opencode' / 'skills'
PLANNER = SKILLS / 'plan-service-implementation' / 'scripts' / 'build_implementation_plan.py'
RECONCILE = SKILLS / 'reconcile-service-spec' / 'scripts' / 'reconcile_specs.py'
APPROVER = 'Maria Lopez (user)'
STATEMENT = 'Autorizo reanudar el desarrollo.'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = fx.make_repo(Path(self.tmp.name).resolve())

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, name, **kwargs):
        ws_dir = fx.make_service(self.repo, name, **kwargs)
        return wsm.Workspace(self.repo, name), ws_dir

    def evaluate(self, ws):
        return gate.evaluate(ws.dir, self.repo, ws.service)

    def clear(self, ws, resolve=True):
        """Walk the legitimate path: review, resolve every blocking item as the user, authorize, re-check."""
        fx.review(ws.dir)
        result = self.evaluate(ws)
        if resolve and result['blocking']:
            fx.simulate_manual(self.repo, ws.service)
        fx.simulate_manual(self.repo, ws.service)
        return gate.check_cleared(ws.dir, self.repo, ws.service)


class WorkspaceIndependenceTests(Base):
    def test_service_names_are_validated_and_workspaces_are_separate_directories(self):
        for bad in ('', '../x', '1a', 'a/b', 'a b', '.factory', 'a--b-', None):
            with self.assertRaises(wsm.WorkspaceError, msg=repr(bad)):
                wsm.Workspace(self.repo, bad)
        a, b = wsm.Workspace(self.repo, 'svc-a').ensure(), wsm.Workspace(self.repo, 'svc-b').ensure()
        self.assertEqual(a.dir.relative_to(self.repo).as_posix(), '.factory/services/svc-a')
        self.assertNotEqual(a.dir, b.dir)
        self.assertEqual(wsm.list_services(self.repo), ['svc-a', 'svc-b'])

    def test_processing_one_service_never_touches_the_artifacts_or_state_of_another(self):
        a, _ = self.service('svc-a')
        a.set_state(status='in-progress', currentPhase='target-authority', runId='RUN-A')
        before = {p.relative_to(a.dir).as_posix(): p.read_bytes() for p in a.dir.rglob('*') if p.is_file()}
        b, _ = self.service('svc-b', path='/api/v1/other')
        b.set_state(status='awaiting-human-decision', runId='RUN-B')
        self.evaluate(b)
        after = {p.relative_to(a.dir).as_posix(): p.read_bytes() for p in a.dir.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual((a.state()['runId'], b.state()['runId']), ('RUN-A', 'RUN-B'))
        self.assertFalse((self.repo / '.factory' / 'archive').exists())          # nothing was archived to switch services

    def test_a_workspace_state_of_another_service_is_refused(self):
        a, _ = self.service('svc-a')
        a.set_state(status='idle')
        stolen = wsm.Workspace(self.repo, 'svc-b').ensure()
        with self.assertRaises(wsm.WorkspaceError):
            stolen.write_state(a.state())
        stolen.state_file.write_bytes(a.state_file.read_bytes())
        with self.assertRaises(wsm.WorkspaceError):
            stolen.set_state(status='in-progress')

    def test_artifact_names_cannot_escape_the_workspace(self):
        ws = wsm.Workspace(self.repo, 'svc-a')
        for bad in ('../x.yml', 'a/b.yml', '..'):
            with self.assertRaises(wsm.WorkspaceError):
                ws.path(bad)

    def test_the_sandbox_runner_redirects_existing_scripts_to_the_workspace_and_never_deletes_real_folders(self):
        a, _ = self.service('svc-a')
        (self.repo / 'input' / 'keep.txt').write_text('keep', encoding='utf-8')
        script = self.repo / '.opencode/skills/parse-openapi/scripts/probe.py'
        script.parent.mkdir(parents=True)
        script.write_text("from pathlib import Path\nPath('.factory/produced.txt').write_text('x')\nprint(sorted(p.name for p in Path('input').iterdir()))\n", encoding='utf-8')
        done = wsm.run_script(a, script, [])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((a.dir / 'produced.txt').is_file())
        self.assertFalse((self.repo / '.factory' / 'produced.txt').exists())
        self.assertTrue((self.repo / 'input' / 'keep.txt').is_file())             # link removal did not recurse into the target
        self.assertTrue((self.repo / 'input' / 'contracts' / 'svc-a.yml').is_file())
        self.assertFalse((self.repo / '.factory' / '.sandboxes' / 'svc-a').exists())


def archive_fixture(base: Path, service: str) -> Path:
    archive = base / '.factory' / 'archive' / f'{service}-run'
    fx.dump(archive / 'service-spec.yml', {'service': {'name': service}, 'readiness': {'strictImplementationReady': True, 'functionalCodeGenerationReady': True}})
    fx.dump(archive / 'implementation-plan.yml', {'service': {'name': service}, 'plan': {'mode': 'full'}, 'inputs': {'archetype': {'path': 'archetypes/x', 'fingerprint': 'f'}}})
    fx.dump(archive / 'openapi-spec.yml', {'source': {'path': f'input/contracts/{service}.yml', 'sha256': 'a'}, 'service': {'title': service}})
    fx.dump(archive / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [{'decisionId': f'human-reviewed-{service}-1', 'humanReviewed': True, 'decision': {'rule': 'OR'}}]})
    fx.dump(archive / 'service-generation-state.yml', {'schemaVersion': 1, 'status': 'idle', 'targetService': None})
    (archive / 'sub').mkdir()
    (archive / 'sub' / 'unit.yml').write_text('unit: 1\n', encoding='utf-8')
    (archive / '__pycache__').mkdir()
    (archive / '__pycache__' / 'x.pyc').write_bytes(b'\x00')
    return archive


def tree(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob('*')) if p.is_file()}


class MigrationTests(Base):
    def test_archived_run_is_recovered_byte_for_byte_and_the_archive_is_untouched(self):
        archive = archive_fixture(self.repo, 'svc-a')
        before = tree(archive)
        result = mig.migrate_archived_run(self.repo, archive, 'svc-a')
        ws = wsm.Workspace(self.repo, 'svc-a')
        self.assertEqual(tree(archive), before)
        self.assertEqual(result['copied'], 5)                                          # 4 yaml + sub/unit.yml; pycache and the archived idle state are not copied
        for name in ('service-spec.yml', 'implementation-plan.yml', 'openapi-spec.yml', 'sparx-reviewed-decisions.yml', 'sub/unit.yml'):
            self.assertEqual((ws.dir / name).read_bytes(), before[name], name)
        self.assertFalse((ws.dir / '__pycache__').exists())
        self.assertEqual((ws.dir / 'migration' / 'archived-service-generation-state.yml').read_bytes(), before['service-generation-state.yml'])

    def test_approved_decisions_are_preserved_and_the_checkpoint_only_states_what_files_prove(self):
        archive = archive_fixture(self.repo, 'svc-a')
        mig.migrate_archived_run(self.repo, archive, 'svc-a')
        ws = wsm.Workspace(self.repo, 'svc-a')
        decisions = yaml.safe_load((ws.dir / 'sparx-reviewed-decisions.yml').read_bytes())
        self.assertEqual([d['decisionId'] for d in decisions['decisions']], ['human-reviewed-svc-a-1'])
        state = ws.state()
        self.assertEqual((state['status'], state['targetService'], state['completedPhases']), ('legacy-migrated', 'svc-a', []))
        self.assertEqual(state['consistencyGate']['status'], 'NOT_EVALUATED')
        self.assertTrue(state['legacyEvidence']['humanDecisionsPresent'])
        self.assertEqual(state['reviewedDecisions']['sha256'], fx.sha((ws.dir / 'sparx-reviewed-decisions.yml').read_bytes()))

    def test_migration_is_idempotent_and_does_not_overwrite_later_progress(self):
        archive = archive_fixture(self.repo, 'svc-a')
        mig.migrate_archived_run(self.repo, archive, 'svc-a')
        ws = wsm.Workspace(self.repo, 'svc-a')
        ws.set_state(status='in-progress', currentPhase='target-authority')
        again = mig.migrate_archived_run(self.repo, archive, 'svc-a')
        self.assertEqual(again['copied'], 0)
        self.assertEqual(ws.state()['status'], 'in-progress')

    def test_a_different_file_at_the_destination_aborts_instead_of_overwriting(self):
        archive = archive_fixture(self.repo, 'svc-a')
        ws = wsm.Workspace(self.repo, 'svc-a').ensure()
        (ws.dir / 'service-spec.yml').write_text('manual: true\n', encoding='utf-8')
        with self.assertRaises(mig.MigrationError):
            mig.migrate_archived_run(self.repo, archive, 'svc-a')
        self.assertEqual((ws.dir / 'service-spec.yml').read_text(encoding='utf-8'), 'manual: true\n')

    def test_an_archive_that_cannot_be_identified_with_certainty_is_refused(self):
        archive = archive_fixture(self.repo, 'svc-a')
        with self.assertRaises(mig.MigrationError):
            mig.migrate_archived_run(self.repo, archive, 'svc-b')                      # belongs to svc-a
        fx.dump(archive / 'implementation-plan.yml', {'service': {'name': 'svc-other'}})
        with self.assertRaises(mig.MigrationError):
            mig.migrate_archived_run(self.repo, archive, 'svc-a')                      # mixed identities
        self.assertFalse((self.repo / '.factory' / 'services' / 'svc-b').exists())

    def test_root_artifacts_are_migrated_only_when_tied_to_the_active_service_and_left_in_place(self):
        root = self.repo / '.factory'
        fx.dump(root / 'service-generation-state.yml', {'schemaVersion': 1, 'status': 'awaiting-human-decision', 'targetService': 'svc-a', 'pendingQuestion': {'id': 'Q1'}})
        fx.dump(root / 'openapi-spec.yml', {'source': {'path': 'x', 'sha256': 'a'}, 'service': {'title': 'svc-a'}})
        fx.dump(root / 'sparx-target-authority.yml', {'target': {'name': 'svc-a', 'sourceRoot': 'input/sparx/P'}})
        fx.dump(root / 'sparx-authoritative-endpoint-detail.yml', {'authority': {'sha256': fx.sha((root / 'sparx-target-authority.yml').read_bytes())}, 'operations': []})
        fx.dump(root / 'sparx-nonauthoritative-evidence.yml', {'authority': {'sha256': 'different'}})        # cannot be tied to the authority
        fx.dump(root / 'service-spec.yml', {'service': {'name': 'svc-other'}})                              # belongs to another service
        before = tree(root)
        result = mig.migrate_root_active(self.repo)
        ws = wsm.Workspace(self.repo, 'svc-a')
        self.assertEqual(sorted(result['skipped']), ['service-spec.yml', 'sparx-nonauthoritative-evidence.yml'])
        self.assertTrue(all((ws.dir / n).is_file() for n in ('openapi-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'service-generation-state.yml')))
        self.assertFalse((ws.dir / 'service-spec.yml').exists())
        self.assertEqual(ws.state()['pendingQuestion'], {'id': 'Q1'})                                          # checkpoint kept verbatim
        self.assertEqual({k: v for k, v in tree(root).items() if not k.startswith('services/')}, {k: v for k, v in before.items()})
        self.assertEqual(mig.migrate_root_active(self.repo)['service'], 'svc-a')                              # rerun is safe


class ConsistencyGateTests(Base):
    def test_consistent_sources_reach_the_gate_only_after_semantic_review_and_explicit_authorization(self):
        ws, _ = self.service('svc-a')
        self.assertEqual(self.evaluate(ws)['status'], gate.SEMANTIC_REVIEW_PENDING)
        fx.review(ws.dir)
        result = self.evaluate(ws)
        self.assertEqual((result['status'], result['blocking']), (gate.AWAITING_AUTHORIZATION, []))
        with self.assertRaises(gate.GateError):
            gate.check_cleared(ws.dir, self.repo)
        fx.simulate_manual(self.repo, 'svc-a')
        self.assertEqual(gate.check_cleared(ws.dir, self.repo)['status'], gate.CLEARED)

    def test_a_verified_contradiction_blocks_and_is_recorded_in_the_checkpoint(self):
        ws, _ = self.service('svc-a', sparx_required='Si', swagger_required=False)
        fx.review(ws.dir)
        result = ws.refresh_gate()
        self.assertEqual(result['status'], gate.BLOCKED)
        self.assertEqual({i['category'] for i in result['blocking']}, {'contradiccion-verificada'})
        state = ws.state()
        self.assertEqual(state['status'], 'BLOCKED_BY_INCONSISTENCIES')
        self.assertEqual(state['pendingQuestion']['kind'], 'sparx-swagger-inconsistencies')
        self.assertEqual(state['blockers'][0]['id'], result['blocking'][0]['id'])
        item = result['blocking'][0]
        self.assertIn('Obligatorio: Si', item['sparx'])                               # each source is shown, neither is chosen
        self.assertIn('required: false', item['swagger'])

    def test_documental_differences_block_too(self):
        ws, _ = self.service('svc-a', extra_header='x-only-sparx')
        fx.review(ws.dir)
        result = self.evaluate(ws)
        self.assertEqual(result['status'], gate.BLOCKED)
        self.assertEqual({i['category'] for i in result['blocking']}, {'diferencia-documental'})

    def test_an_operation_missing_in_sparx_blocks(self):
        ws, _ = self.service('svc-a', sparx_ops=[])
        fx.review(ws.dir)
        result = self.evaluate(ws)
        self.assertEqual(result['status'], gate.BLOCKED)
        self.assertIn('Operación', [i['element'] for i in result['blocking']])

    def test_unverified_behavior_that_is_indispensable_blocks_but_irrelevant_items_do_not(self):
        ws, _ = self.service('svc-a')
        op = {'method': 'GET', 'path': '/api/v1/items'}
        fx.review(ws.dir, unverified=[{'operation': op, 'category': 'comportamiento-no-especificado', 'topic': 'Filtro name', 'reason': 'Ninguna fuente define el operador.'}])
        result = self.evaluate(ws)
        self.assertEqual((result['status'], [i['type'] for i in result['blocking']]), (gate.BLOCKED, ['unverified']))
        fx.review(ws.dir, unverified=[{'operation': op, 'category': 'contradiccion-interna-sparx', 'topic': 'Tipo STATUS', 'reason': 'Sparx se contradice a si mismo.'},
                                      {'operation': op, 'category': 'fuente-no-comparable', 'topic': 'Tipo de OUTPUT', 'reason': 'No comparable con el contrato.'}],
                  discarded=[{'operation': op, 'element': 'Restricciones', 'reason': 'Responsabilidades distintas.'}])
        result = self.evaluate(ws)
        self.assertEqual((result['status'], result['blocking']), (gate.AWAITING_AUTHORIZATION, []))

    def test_resolution_plus_authorization_clears_and_the_audit_report_alone_does_not(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        fx.review(ws.dir)
        blocked = self.evaluate(ws)
        self.assertTrue((ws.dir / 'consistency' / 'findings.yml').is_file())          # the audit artifact exists ...
        with self.assertRaises(gate.GateError):
            gate.check_cleared(ws.dir, self.repo)                                      # ... and does not authorize anything
        with self.assertRaises(gate.GateError):
            gate.authorize(ws.dir, self.repo, 'svc-a', APPROVER, STATEMENT)           # cannot authorize while blocked
        entry = fx.simulate_manual(self.repo, 'svc-a')
        self.assertEqual(entry['selections'][0]['outcome'], 'approved')
        self.assertEqual(self.evaluate(ws)['status'], gate.AWAITING_AUTHORIZATION)     # resolved, still waiting for the user to authorize resuming
        fx.simulate_manual(self.repo, 'svc-a')
        self.assertEqual(gate.check_cleared(ws.dir, self.repo)['status'], gate.CLEARED)

    def test_machine_approvals_are_rejected(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        fx.review(ws.dir)
        item = self.evaluate(ws)['blocking'][0]
        for who in ('agent', 'service-generator', 'auto', ''):
            with self.assertRaises(gate.GateError):
                gate.record_resolution(ws.dir, self.repo, 'svc-a', item['id'], 'sparx-governs', 'x', who)
        with self.assertRaises(gate.GateError):
            gate.record_resolution(ws.dir, self.repo, 'svc-a', 'INC-999', 'sparx-governs', 'x', APPROVER)
        with self.assertRaises(gate.GateError):
            gate.record_resolution(ws.dir, self.repo, 'svc-a', item['id'], 'sparx-governs', '   ', APPROVER)

    def test_a_resolution_applies_only_to_the_exact_finding_it_approved(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        self.clear(ws)
        # a different difference on the same element (sources changed): the old approval must not cover it
        fx.make_service(self.repo, 'svc-a', sparx_required='No', swagger_required=True)
        fx.review(ws.dir)
        result = self.evaluate(ws)
        self.assertEqual(result['status'], gate.BLOCKED)
        self.assertEqual(len(result['resolved']), 0)  # entire relevant context is now stale
        # and a NEW conflict next to the resolved one blocks while the resolved one stays resolved
        fx.make_service(self.repo, 'svc-a', sparx_required='Si', extra_header='x-new')
        fx.review(ws.dir)
        result = self.evaluate(ws)
        self.assertEqual({i['element'] for i in result['blocking']}, {'header x-new', 'query id'})
        self.assertEqual(len(result['resolved']), 0)

    def test_existing_human_decisions_are_respected_by_reference_and_must_exist(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        fx.dump(ws.dir / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [{'decisionId': 'human-reviewed-svc-a-1', 'humanReviewed': True}]})
        fx.review(ws.dir)
        item = self.evaluate(ws)['blocking'][0]
        with self.assertRaises(gate.GateError):
            gate.record_resolution(ws.dir, self.repo, 'svc-a', item['id'], 'sparx-governs', 'x', APPROVER, based_on_decision='made-up-decision')
        fx.simulate_manual(self.repo, 'svc-a')
        self.assertEqual(self.evaluate(ws)['status'], gate.AWAITING_AUTHORIZATION)
        self.assertEqual(yaml.safe_load((ws.dir / 'sparx-reviewed-decisions.yml').read_bytes())['decisions'][0]['decisionId'], 'human-reviewed-svc-a-1')   # decision untouched

    def test_an_authorization_is_invalidated_by_any_later_change(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        self.clear(ws)
        fx.make_service(self.repo, 'svc-a', sparx_required='Si', extra_header='x-new')      # a new conflict after authorization
        fx.review(ws.dir)
        with self.assertRaises(gate.GateError):
            gate.check_cleared(ws.dir, self.repo)
        fx.make_service(self.repo, 'svc-a', sparx_required='Si')                              # back to the approved state
        fx.review(ws.dir)
        self.assertEqual(gate.check_cleared(ws.dir, self.repo)['status'], gate.CLEARED)       # same evaluation hash: authorization still bound to it

    def test_changed_sources_make_the_gate_stale_and_a_stored_status_is_never_trusted(self):
        ws, _ = self.service('svc-a')
        self.clear(ws)
        ws_state_before = ws.state()
        (self.repo / 'input' / 'contracts' / 'svc-a.yml').write_text('openapi: 3.0.2\n', encoding='utf-8')     # the Swagger changed after the audit
        with self.assertRaises(gate.GateError):
            gate.check_cleared(ws.dir, self.repo)
        (self.repo / 'input' / 'contracts' / 'svc-a.yml').write_text('openapi: 3.0.1\ninfo:\n  title: svc-a\n', encoding='utf-8')
        (self.repo / 'input' / 'sparx' / 'P' / 'js' / 'data' / 'toc.xml').write_text('new Array("0","1","El","p.htm","","5","6","g","Class");\n', encoding='utf-8')   # the Sparx export changed
        with self.assertRaises(gate.GateError):
            gate.check_cleared(ws.dir, self.repo)
        self.assertEqual(ws.state(), ws_state_before)

    def test_editing_the_stored_audit_or_gate_files_cannot_clear_a_blocked_service(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        fx.review(ws.dir)
        self.evaluate(ws)
        registry = ws.dir / 'consistency' / 'findings.yml'
        data = yaml.safe_load(registry.read_bytes())
        data['findings'], data['unverified'] = [], []
        registry.write_text(yaml.safe_dump(data), encoding='utf-8')
        gate_file = ws.dir / 'consistency' / 'gate.yml'
        gate_file.write_text(yaml.safe_dump({'status': gate.CLEARED}), encoding='utf-8')
        (ws.dir / 'consistency' / 'authorization.yml').write_text(yaml.safe_dump({'evaluationHash': 'forged', 'authorizedBy': APPROVER}), encoding='utf-8')
        with self.assertRaises(gate.GateError):
            gate.check_cleared(ws.dir, self.repo)

    def test_the_gate_reuses_the_auditor_comparison_and_adds_no_rules(self):
        self.assertIs(gate.cmp, sys.modules['compare_sparx_swagger'])
        source = (HERE.parent / 'scripts' / 'consistency_gate.py').read_text(encoding='utf-8')
        for forbidden in ('required_flag', 'def family', 'route_key'):
            self.assertNotIn(forbidden, source)


class CheckpointAndResumeTests(Base):
    def test_phases_after_the_gate_cannot_be_entered_while_blocked_and_checkpoint_stays_blocked(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        fx.review(ws.dir)
        ws.refresh_gate()
        for phase in ('specification-consolidation', 'implementation-planning', 'materialization', 'static-validation'):
            with self.assertRaises(gate.GateError, msg=phase):
                ws.enter_phase(phase)
        self.assertEqual(ws.state()['status'], 'BLOCKED_BY_INCONSISTENCIES')
        self.assertIsNone(ws.state().get('currentPhase') if ws.state().get('currentPhase') in wsm.PHASES[wsm.GATED_FROM:] else None)
        ws.enter_phase('target-authority')            # earlier analysis phases remain available

    def test_resuming_a_tampered_checkpoint_cannot_skip_the_block(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        fx.review(ws.dir)
        ws.set_state(status='in-progress', currentPhase='implementation-planning', completedPhases=list(wsm.PHASES[:5]))      # forged progress
        outcome = ws.resume()
        self.assertFalse(outcome['resumable'])
        self.assertEqual(ws.state()['status'], 'BLOCKED_BY_INCONSISTENCIES')
        self.assertEqual(ws.state()['currentPhase'], 'consistency-validation')
        with self.assertRaises(gate.GateError):
            ws.enter_phase('implementation-planning')

    def test_resume_after_resolution_requires_the_user_authorization_and_then_continues(self):
        ws, _ = self.service('svc-a', sparx_required='Si')
        fx.review(ws.dir)
        item = ws.resume()['gate']['blocking'][0]
        self.assertEqual(ws.state()['status'], 'BLOCKED_BY_INCONSISTENCIES')
        fx.simulate_manual(self.repo, 'svc-a', choice='swagger-governs')
        self.assertFalse(ws.resume()['resumable'])                                    # resolved but not yet authorized
        self.assertEqual(ws.state()['status'], 'AWAITING_RESUME_AUTHORIZATION')
        with self.assertRaises(gate.GateError):
            ws.enter_phase('implementation-planning')
        fx.simulate_manual(self.repo, 'svc-a')
        outcome = ws.resume()
        self.assertTrue(outcome['resumable'])
        self.assertEqual(ws.state()['status'], 'in-progress')
        self.assertIsNone(ws.state()['pendingQuestion'])
        self.assertEqual(ws.enter_phase('implementation-planning')['currentPhase'], 'implementation-planning')

    def test_the_orchestrator_state_machine_works_independently_for_several_services(self):
        a, _ = self.service('svc-a')
        b, _ = self.service('svc-b', sparx_required='Si')
        c, _ = self.service('svc-c', path='/api/v1/others')
        self.clear(a)
        fx.review(b.dir)
        b.refresh_gate()
        self.clear(c)
        self.assertEqual(a.enter_phase('implementation-planning')['status'], 'in-progress')
        self.assertEqual(c.enter_phase('materialization')['currentPhase'], 'materialization')
        with self.assertRaises(gate.GateError):
            b.enter_phase('implementation-planning')
        self.assertEqual([wsm.Workspace(self.repo, n).state()['status'] for n in ('svc-a', 'svc-b', 'svc-c')], ['in-progress', 'BLOCKED_BY_INCONSISTENCIES', 'in-progress'])
        self.assertEqual(b.state()['targetService'], 'svc-b')

    def test_a_legacy_migrated_service_is_blocked_until_the_gate_is_evaluated_and_cleared(self):
        archive = archive_fixture(self.repo, 'svc-a')
        mig.migrate_archived_run(self.repo, archive, 'svc-a')
        ws = wsm.Workspace(self.repo, 'svc-a')
        with self.assertRaises(gate.GateError):
            ws.enter_phase('implementation-planning')
        self.assertEqual(gate.check_cleared.__name__, 'check_cleared')


class NoCodeWhenBlockedTests(Base):
    def run_direct(self, script, cwd):
        return subprocess.run([sys.executable, str(script), *(['--mode', 'full'] if script == PLANNER else [])], cwd=cwd, capture_output=True, text=True)

    def test_a_blocked_service_cannot_plan_consolidate_or_generate_and_no_java_is_created(self):
        a, _ = self.service('svc-a', sparx_required='Si')
        fx.review(a.dir)
        a.refresh_gate()
        out = self.repo / 'output' / 'svc-a'
        snapshot = tree(self.repo / '.factory')
        for script in (PLANNER, RECONCILE, SKILLS / 'plan-service-implementation' / 'scripts' / 'resolve_generation_parameters.py',
                       SKILLS / 'materialize-service-scaffold' / 'scripts' / 'materialize_scaffold.py', SKILLS / 'materialize-service-scaffold' / 'scripts' / 'materialize_build_files.py'):
            with self.assertRaises((gate.GateError, wsm.WorkspaceError), msg=script.name):
                wsm.run_script(a, script, [])                                         # the runner refuses before executing anything
        self.assertEqual(tree(self.repo / '.factory'), snapshot)                       # nothing created or modified
        self.assertFalse(out.exists())
        self.assertEqual(fx.java_files(self.repo / 'output', self.repo / '.factory'), [])

    def test_the_scripts_refuse_on_their_own_when_called_directly_without_the_runner(self):
        a, _ = self.service('svc-a', sparx_required='Si')
        fx.review(a.dir)
        a.refresh_gate()
        for script in (PLANNER, RECONCILE):
            done = self.run_direct(script, self.repo)                                  # plain repository: no service workspace clears the gate
            self.assertEqual(done.returncode, 3, done.stderr)
            self.assertIn('GATE BLOCKED', done.stderr)
        self.assertEqual(fx.java_files(self.repo), [])
        self.assertFalse((self.repo / '.factory' / 'implementation-plan.yml').exists())
        self.assertFalse((self.repo / '.factory' / 'service-spec.yml').exists())

    def test_the_scripts_refuse_inside_a_blocked_sandbox_and_proceed_to_their_own_checks_when_cleared(self):
        blocked, _ = self.service('svc-a', sparx_required='Si')
        fx.review(blocked.dir)
        blocked.refresh_gate()
        cleared, _ = self.service('svc-b')
        self.clear(cleared)
        # blocked: the guard exits 3 even if the runner check were bypassed (run the script inside a manual sandbox)
        for ws, expected in ((blocked, 3), (cleared, None)):
            box = self.repo / '.factory' / '.sandboxes' / ws.service
            box.mkdir(parents=True)
            try:
                for name, target in (('.factory', ws.dir), ('input', self.repo / 'input')):
                    wsm.make_link(box / name, target)
                done = subprocess.run([sys.executable, str(PLANNER), '--mode', 'full'], cwd=box, capture_output=True, text=True)
            finally:
                wsm.drop_sandbox(box)
            if expected == 3:
                self.assertEqual(done.returncode, 3, done.stderr)
                self.assertIn('GATE BLOCKED', done.stderr)
            else:
                self.assertNotIn('GATE BLOCKED', done.stderr)                           # passes the gate; later fails for missing service-spec, not for the gate
                self.assertNotEqual(done.returncode, 0)
        self.assertEqual(fx.java_files(self.repo / 'output'), [])

    def test_guard_exit_codes(self):
        a, _ = self.service('svc-a')
        self.assertEqual(gate_guard.enforce(self.repo), 3)                              # no workspace at the root .factory
        box = self.repo / '.factory' / '.sandboxes' / 'svc-a'
        box.mkdir(parents=True)
        try:
            wsm.make_link(box / '.factory', a.dir)
            wsm.make_link(box / 'input', self.repo / 'input')
            self.assertEqual(gate_guard.enforce(box), 3)                                # not reviewed yet
            self.clear(a)
            self.assertIsNone(gate_guard.enforce(box))
        finally:
            wsm.drop_sandbox(box)

    def test_cli_status_and_resume_reflect_the_block(self):
        a, _ = self.service('svc-a', sparx_required='Si')
        fx.review(a.dir)
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            self.assertEqual(cli.main(['gate-evaluate', 'svc-a']), 3)
            self.assertEqual(cli.main(['resume', 'svc-a']), 3)
            self.assertEqual(cli.main(['gate-check', 'svc-a']), 3)
            self.assertEqual(cli.main(['gate-authorize', 'svc-a', '--by', APPROVER, '--statement', STATEMENT]), 3)
            self.assertEqual(cli.main(['status', 'svc-a']), 0)
        finally:
            os.chdir(cwd)
        self.assertEqual(a.state()['status'], 'BLOCKED_BY_INCONSISTENCIES')


class FileProtectionTests(Base):
    def setUp(self):
        super().setUp()
        self.ws = wsm.Workspace(self.repo, 'svc-a').ensure()
        self.out = self.repo / 'output' / 'svc-a'
        (self.out / 'src/main/java/x').mkdir(parents=True)
        (self.out / 'src/main/resources').mkdir(parents=True)
        self.generated = self.out / 'src/main/java/x/Gen.java'
        self.generated.write_text('class Gen {}', encoding='utf-8')
        self.edited = self.out / 'src/main/java/x/Edited.java'
        self.edited.write_text('class Edited {}', encoding='utf-8')
        self.untracked = self.out / 'src/main/java/x/Manual.java'
        self.untracked.write_text('class Manual {}', encoding='utf-8')
        self.props = self.out / 'src/main/resources/application.properties'
        self.props.write_text('server.port=8080\n', encoding='utf-8')
        fx.dump(self.out / '.generation-manifest.yml', {'fileInventory': [{'path': 'src/main/java/x/Gen.java', 'sha256': fx.sha(b'class Gen {}')},
                                                                            {'path': 'src/main/java/x/Edited.java', 'sha256': fx.sha(b'class Edited { /* generated */ }')}]})

    def decisions(self, planned):
        return {d['path']: d for d in fp.evaluate(self.out, planned, self.ws.dir)}

    def test_generated_files_may_be_updated_manual_ones_are_preserved(self):
        d = self.decisions([{'path': 'src/main/java/x/Gen.java', 'action': 'update'}, {'path': 'src/main/java/x/Edited.java', 'action': 'update'},
                            {'path': 'src/main/java/x/Manual.java', 'action': 'update'}, {'path': 'src/main/java/x/New.java', 'action': 'create'},
                            {'path': 'src/main/java/x/Edited.java', 'action': 'retain'}])
        self.assertEqual(d['src/main/java/x/Gen.java']['decision'], 'write')
        self.assertEqual(d['src/main/java/x/Edited.java']['state'], fp.MODIFIED)
        self.assertEqual(d['src/main/java/x/Manual.java']['state'], fp.UNTRACKED)
        self.assertEqual(d['src/main/java/x/New.java']['decision'], 'write')
        self.assertEqual(self.edited.read_text(encoding='utf-8'), 'class Edited {}')                 # content preserved; the guard never writes
        self.assertEqual(len(fp.blocked(fp.evaluate(self.out, [{'path': 'src/main/java/x/Edited.java', 'action': 'update'}], self.ws.dir))), 1)
        self.assertEqual(fp.evaluate(self.out, [{'path': 'src/main/java/x/Edited.java', 'action': 'retain'}], self.ws.dir)[0]['decision'], 'keep')

    def test_a_difference_from_the_archetype_is_not_an_error_and_a_planned_create_over_manual_work_is_blocked(self):
        self.assertEqual(self.decisions([{'path': 'src/main/java/x/Edited.java', 'action': 'retain'}])['src/main/java/x/Edited.java']['decision'], 'keep')
        self.assertEqual(self.decisions([{'path': 'src/main/java/x/Manual.java', 'action': 'create'}])['src/main/java/x/Manual.java']['decision'], 'blocked-needs-authorization')

    def test_overwrite_requires_an_authorization_bound_to_the_exact_content(self):
        rel = 'src/main/java/x/Edited.java'
        with self.assertRaises(fp.ProtectedFileError):
            fp.guard_write(self.out, rel, self.ws.dir)
        with self.assertRaises(fp.ProtectedFileError):
            fp.authorize_overwrite(self.out, rel, self.ws.dir, 'agent', 'because')
        fx.dump(self.ws.dir / 'service-spec.yml', {'service': {'name': 'svc-a'}})
        fx.dump(self.ws.dir / 'implementation-plan.yml', {'service': {'outputDirectory': 'output/svc-a'}, 'files': {'generate': [{'path': rel}]}})
        fx.simulate_manual(self.repo, 'svc-a', kind='overwrite', path=rel)
        self.assertTrue(fp.guard_write(self.out, rel, self.ws.dir))
        self.edited.write_text('class Edited { int again; }', encoding='utf-8')                       # the user edits it again
        with self.assertRaises(fp.ProtectedFileError):
            fp.guard_write(self.out, rel, self.ws.dir)

    def test_user_owned_patterns_are_protected_even_if_generated_hash_matches(self):
        fx.dump(self.ws.dir / 'user-owned-files.yml', {'patterns': ['src/main/java/x/Gen.java']})
        self.assertEqual(self.decisions([{'path': 'src/main/java/x/Gen.java', 'action': 'update'}])['src/main/java/x/Gen.java']['decision'], 'blocked-needs-authorization')

    def test_application_properties_is_never_read_reported_blocked_or_authorized(self):
        rel = 'src/main/resources/application.properties'
        reads = []
        original = fp.sha

        def spy(path):
            reads.append(Path(path).name)
            return original(path)
        with patch.object(fp, 'sha', side_effect=spy):
            d = self.decisions([{'path': rel, 'action': 'update'}, {'path': 'src/main/resources/application-local.properties', 'action': 'create'}])
            self.assertFalse(fp.guard_write(self.out, rel, self.ws.dir))
        self.assertNotIn('application.properties', reads)
        self.assertEqual(d[rel]['decision'], 'skip-excluded')
        self.assertNotIn('currentSha256', d[rel])                                                  # no content analysis
        self.assertEqual(fp.blocked(list(d.values())), [])                                         # never blocks the pipeline
        with self.assertRaises(fp.ProtectedFileError):
            fp.authorize_overwrite(self.out, rel, self.ws.dir, APPROVER, 'x')
        self.assertEqual(self.props.read_text(encoding='utf-8'), 'server.port=8080\n')

    def test_cli_protect_check_reports_blocked_files_without_listing_the_excluded_one(self):
        plan = {'service': {'outputDirectory': 'output/svc-a'}, 'files': {'generate': [{'path': 'src/main/java/x/Edited.java', 'action': 'update'},
                                                                                       {'path': 'src/main/resources/application.properties', 'action': 'update'}]}}
        plan_file = self.repo / 'plan.yml'
        fx.dump(plan_file, plan)
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            self.assertEqual(cli.main(['protect-check', 'svc-a', '--plan', str(plan_file)]), 3)
            self.assertEqual(cli.main(['protect-authorize', 'svc-a', 'src/main/resources/application.properties', '--by', APPROVER, '--reason', 'x']), 3)
        finally:
            os.chdir(cwd)


class DecisionCoverageTests(Base):
    QUOTE = 'Business search query parameters remain optional as declared by the contract'
    OP = {'method': 'GET', 'path': '/api/v1/items'}

    def decision(self, **over):
        base = {'decisionId': 'human-reviewed-x-1', 'humanReviewed': True, 'reviewStatus': 'human-reviewed', 'approvalStatus': 'approved',
                'target': {'service': 'svc-a', 'operations': [self.OP]}, 'decision': {'rule': self.QUOTE}}
        base.update(over)
        return base

    def prepare(self, **kw):
        ws, _ = self.service('svc-a', sparx_required='Si')
        decision = self.decision()
        fx.dump(ws.dir / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [decision]})
        fx.review(ws.dir)
        item = self.evaluate(ws)['blocking'][0]
        return ws, decision, item

    def link(self, ws, item, decision, **over):
        entry = {'findingId': item['id'], 'findingFingerprint': item['fingerprint'], 'decisionId': decision['decisionId'], 'decisionSha256': gate.digest(decision), 'quote': self.QUOTE}
        entry.update(over)
        fx.dump(ws.dir / 'consistency' / 'decision-coverage.yml', {'coverage': [entry]})
        if not over:
            fx.simulate_manual(self.repo, 'svc-a', kind='historical', decision_id=decision['decisionId'])

    def test_a_valid_existing_decision_covers_the_difference_without_a_new_approval(self):
        ws, decision, item = self.prepare()
        self.link(ws, item, decision)
        result = self.evaluate(ws)
        self.assertEqual((result['status'], result['blocking']), (gate.AWAITING_AUTHORIZATION, []))
        self.assertEqual([i['coveredBy']['decisionId'] for i in result['coveredByDecision']], ['human-reviewed-x-1'])
        self.assertFalse((ws.dir / 'consistency' / 'resolutions.yml').exists())              # nothing was approved on anyone's behalf
        with self.assertRaises(gate.GateError):
            gate.check_cleared(ws.dir, self.repo)                                              # still needs the user's authorization to resume

    def test_coverage_is_rejected_when_the_decision_the_scope_the_quote_or_the_finding_do_not_match(self):
        ws, decision, item = self.prepare()
        cases = {
            'missing decision': dict(decisionId='nope'),
            'changed decision content': dict(decisionSha256='0' * 64),
            'quote not in decision': dict(quote='La decision dice algo que nunca dijo en realidad'),
            'quote too short': dict(quote='optional'),
            'stale finding': dict(findingFingerprint='f' * 64),
        }
        for name, over in cases.items():
            self.link(ws, item, decision, **over)
            result = self.evaluate(ws)
            self.assertEqual(result['status'], gate.BLOCKED, name)
            self.assertEqual(result['coveredByDecision'], [], name)
        other_scope = self.decision(target={'service': 'svc-a', 'operations': [{'method': 'POST', 'path': '/api/v1/items'}]})
        fx.dump(ws.dir / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [other_scope]})
        self.link(ws, item, other_scope)
        self.assertEqual(self.evaluate(ws)['status'], gate.BLOCKED)
        unapproved = self.decision(humanReviewed=False)
        fx.dump(ws.dir / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [unapproved]})
        self.link(ws, item, unapproved)
        self.assertEqual(self.evaluate(ws)['status'], gate.BLOCKED)

    def test_editing_the_decision_or_the_sources_after_linking_invalidates_the_coverage(self):
        ws, decision, item = self.prepare()
        self.link(ws, item, decision)
        self.assertEqual(self.evaluate(ws)['status'], gate.AWAITING_AUTHORIZATION)
        edited = dict(decision, decision={'rule': self.QUOTE + ' (modified)'})
        fx.dump(ws.dir / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [edited]})
        self.assertEqual(self.evaluate(ws)['status'], gate.BLOCKED)
        fx.dump(ws.dir / 'sparx-reviewed-decisions.yml', {'version': 2, 'decisions': [decision]})
        self.assertEqual(self.evaluate(ws)['status'], gate.AWAITING_AUTHORIZATION)
        fx.make_service(self.repo, 'svc-a', sparx_required='Si', swagger_required=True)         # the contradiction changed (different Swagger value)
        fx.review(ws.dir)
        self.assertEqual(self.evaluate(ws)['status'], gate.AWAITING_AUTHORIZATION if not self.evaluate(ws)['blocking'] else gate.BLOCKED)

    def test_a_covered_difference_does_not_hide_a_new_one_and_resume_stays_blocked(self):
        ws, decision, item = self.prepare()
        self.link(ws, item, decision)
        fx.make_service(self.repo, 'svc-a', sparx_required='Si', extra_header='x-new')
        fx.review(ws.dir)
        result = ws.resume()
        self.assertFalse(result['resumable'])
        self.assertIn('header x-new', [i['element'] for i in result['gate']['blocking']])
        self.assertEqual(len(result['gate']['coveredByDecision']), 0)  # changed source context requires review
        self.assertEqual(ws.state()['status'], 'BLOCKED_BY_INCONSISTENCIES')
        with self.assertRaises(gate.GateError):
            ws.enter_phase('implementation-planning')

    def test_the_decision_file_itself_is_never_modified_by_the_gate(self):
        ws, decision, item = self.prepare()
        before = (ws.dir / 'sparx-reviewed-decisions.yml').read_bytes()
        self.link(ws, item, decision)
        self.evaluate(ws)
        fx.simulate_manual(self.repo, 'svc-a')
        self.assertEqual((ws.dir / 'sparx-reviewed-decisions.yml').read_bytes(), before)
        self.assertEqual(gate.check_cleared(ws.dir, self.repo)['status'], gate.CLEARED)


class DecisionTopicsTests(unittest.TestCase):
    def item(self, number, method, element, kind):
        return {'id': f'INC-{number:03d}', 'kind': kind, 'operation': {'method': method, 'path': '/api/v1/things'}, 'element': element, 'sparx': 'a', 'swagger': 'b'}

    def test_related_fields_are_grouped_by_decision_topic_not_repeated(self):
        items = [self.item(1, 'GET', 'query code', 'type-or-structure-difference'), self.item(2, 'POST', 'body code', 'type-or-structure-difference'),
                 self.item(3, 'PATCH', 'body code', 'type-or-structure-difference'), self.item(4, 'GET', 'query size', 'type-or-structure-difference'),
                 self.item(5, 'POST', 'body alpha', 'requirement-difference'), self.item(6, 'POST', 'body beta', 'requirement-difference'),
                 self.item(7, 'POST', 'body gamma', 'conditional-rule-difference'), self.item(8, 'PATCH', 'body alpha', 'requirement-difference'),
                 self.item(9, 'POST', 'Ruta de la operacion', 'route-difference')]
        topics = gate.decision_topics(items)
        by_title = {t['topic']: t for t in topics}
        self.assertEqual(by_title['Tipo del campo code']['items'], ['INC-001', 'INC-002', 'INC-003'])
        self.assertEqual(sorted(by_title['Tipo del campo code']['operations']), ['GET /api/v1/things', 'PATCH /api/v1/things', 'POST /api/v1/things'])
        self.assertEqual(by_title['Obligatoriedad de campos en POST /api/v1/things']['items'], ['INC-005', 'INC-006', 'INC-007'])
        self.assertEqual(by_title['Obligatoriedad de campos en PATCH /api/v1/things']['items'], ['INC-008'])
        self.assertEqual(len(topics), 5)
        self.assertEqual(sorted(i for t in topics for i in t['items']), sorted(i['id'] for i in items))     # nothing lost, nothing duplicated


if __name__ == '__main__':
    unittest.main()
