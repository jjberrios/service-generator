"""FULL materializer: determinism, supported set, blocked gate, file protection and bypass resistance (synthetic services in temp dirs)."""
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
import synth as fx
import full_materializer as mz
import renderers as rd
import file_protection as fp
import consistency_gate as gate
import workspace as wsm
import workspace_cli as cli

SCRIPT = HERE.parent / 'scripts' / 'full_materializer.py'
AGENT = fx.REPO_ROOT / '.opencode' / 'agents' / 'service-generator.md'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = fx.make_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, service):
        return self.repo / 'output' / service

    def java(self):
        return sorted(str(p) for p in (self.repo / 'output').rglob('*.java')) if (self.repo / 'output').exists() else []


class DeterminismTests(Base):
    def test_same_inputs_give_identical_bytes_manifest_and_report_in_independent_repositories(self):
        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as other:
                repo = fx.make_repo(Path(other))
                fx.ready_service(repo, 'inventory-service')
                report = mz.materialize(repo, 'inventory-service')
                results.append((fx.tree(repo / 'output' / 'inventory-service'), report['payloadTreeSha256'], report['manifestSha256']))
        self.assertEqual(results[0], results[1])
        self.assertTrue(results[0][0])

    def test_rerun_in_the_same_repository_changes_nothing(self):
        fx.ready_service(self.repo, 'inventory-service')
        first = mz.materialize(self.repo, 'inventory-service')
        snapshot = fx.tree(self.out('inventory-service'))
        second = mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(second['written'], [])
        self.assertEqual(sorted(second['unchanged']), sorted(first['written']))
        self.assertEqual(fx.tree(self.out('inventory-service')), snapshot)

    def test_output_is_lf_utf8_without_timestamps(self):
        fx.ready_service(self.repo, 'inventory-service')
        mz.materialize(self.repo, 'inventory-service')
        for path, data in fx.tree(self.out('inventory-service')).items():
            if path.endswith(('.java', '.yml')):               # archetype files assembled byte for byte (the reference pom.xml is CRLF) keep their own line endings
                self.assertNotIn(b'\r', data, path)
            data.decode('utf-8')
        manifest = (self.out('inventory-service') / '.generation-manifest.yml').read_text(encoding='utf-8')
        self.assertNotRegex(manifest, r'\d{4}-\d{2}-\d{2}T')


class GenerationTests(Base):
    def test_two_services_with_different_packages_and_structures_are_generated_independently(self):
        for name in fx.SERVICES:
            fx.ready_service(self.repo, name)
            mz.materialize(self.repo, name)
        a, b = self.out('inventory-service'), self.out('billing-service')
        entity_a = (a / 'src/main/java/com/acme/inventory/core/model/ItemEntity.java').read_text(encoding='utf-8')
        entity_b = (b / 'src/main/java/org/example/billing/model/InvoiceEntity.java').read_text(encoding='utf-8')
        self.assertIn('package com.acme.inventory.core.model;', entity_a)
        self.assertIn('@Table(name = "ITEM")', entity_a)
        self.assertIn('@Lob', entity_a)
        self.assertIn('import java.math.BigDecimal;', entity_b)
        self.assertIn('import java.time.LocalDateTime;', entity_b)
        self.assertIn('private Long invoiceId;', entity_b)
        everything = '\n'.join(d.decode('utf-8') for t in (fx.tree(a), fx.tree(b)) for d in t.values())
        for forbidden in ('mailing', 'Mailing', 'MAILINGINFORMATION', 'emailBody'):
            self.assertNotIn(forbidden, everything)
        self.assertNotIn('org.example', '\n'.join(d.decode('utf-8') for d in fx.tree(a).values()))        # no cross contamination
        repo_text = (b / 'src/main/java/org/example/billing/repository/InvoiceRepository.java').read_text(encoding='utf-8')
        self.assertIn('extends JpaRepository<InvoiceEntity, Long>', repo_text)
        self.assertIn('JpaSpecificationExecutor<InvoiceEntity>', repo_text)        # the plan has a search specification

    def test_constants_logging_and_headers_come_from_the_plan_and_the_archetype_template(self):
        fx.ready_service(self.repo, 'inventory-service')
        mz.materialize(self.repo, 'inventory-service')
        base = self.out('inventory-service') / 'src/main/java/com/acme/inventory/core'
        constants = (base / 'utils/ConstanApi.java').read_text(encoding='utf-8')
        self.assertIn('public static final String ACT2_CONSULTAR = "CONSULTAR";', constants)
        self.assertIn('LOG_TIMEOUT_ACT2_CONSULTAR', constants)
        self.assertIn('package com.acme.inventory.core.utils;', constants)
        headers = (base / 'dto/request/RequestHeaders.java').read_text(encoding='utf-8')
        self.assertIn('String transactionId,\n        String userId\n', headers)
        logger = (base / 'utils/ActivityLogger.java').read_text(encoding='utf-8')
        self.assertIn('logContenido', logger)
        self.assertNotIn('__BASE_PACKAGE', logger)

    def test_manifest_records_every_written_file_with_its_hash(self):
        fx.ready_service(self.repo, 'inventory-service')
        report = mz.materialize(self.repo, 'inventory-service')
        out = self.out('inventory-service')
        manifest = yaml.safe_load((out / '.generation-manifest.yml').read_bytes())
        rows = {r['path']: r['sha256'] for r in manifest['fileInventory']}
        self.assertEqual(sorted(rows), sorted(report['written']))
        self.assertTrue(all(fx.sha((out / p).read_bytes()) == h for p, h in rows.items()))
        self.assertTrue(manifest['complete'])
        self.assertEqual(manifest['materializer'], mz.VERSION)

    def test_generated_java_is_clean_for_the_preventive_style_lint(self):
        import style_lint
        for name in fx.SERVICES:
            fx.ready_service(self.repo, name)
            mz.materialize(self.repo, name)
            result = style_lint.lint_project(self.out(name))
            self.assertEqual((result['findings'], result['filesChecked'] > 0), ([], True))

    def test_dry_run_writes_nothing(self):
        fx.ready_service(self.repo, 'inventory-service')
        report = mz.materialize(self.repo, 'inventory-service', dry_run=True)
        self.assertTrue(report['written'])
        self.assertFalse(self.out('inventory-service').exists())


class UnsupportedPatternTests(Base):
    def test_a_plan_with_unsupported_components_writes_nothing_and_lists_them(self):
        fx.ready_service(self.repo, 'inventory-service', with_unsupported=True)
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(caught.exception.kind, 'unsupported')
        self.assertEqual([u['componentType'] for u in caught.exception.details['unsupported']], ['repository-persistence-test'])
        self.assertFalse(self.out('inventory-service').exists())
        self.assertEqual(self.java(), [])

    def test_supported_only_cannot_bypass_full_feasibility(self):
        fx.ready_service(self.repo, 'inventory-service', with_unsupported=True)
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service', supported_only=True)
        self.assertFalse(caught.exception.details['preflight']['feasible'])
        self.assertFalse(self.out('inventory-service').exists())

    def test_unsupported_attributes_and_actions_are_refused_not_approximated(self):
        cases = {
            'java type': {'fields': [('ID', 'id', 'Long', False, True), ('PHOTO', 'photo', 'byte[]', False, False)]},
            'two keys': {'fields': [('ID', 'id', 'Long', False, True), ('ID2', 'id2', 'Long', False, True)]},
            'string key': {'fields': [('ID', 'id', 'String', False, True)]},
            'lob on number': {'fields': [('ID', 'id', 'Long', False, True), ('N', 'n', 'Integer', True, False)]},
            'unsafe name': {'fields': [('ID', 'id', 'Long', False, True), ('X', 'class name', 'String', False, False)]},
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as other:
                    repo = fx.make_repo(Path(other))
                    fx.ready_service(repo, 'inventory-service', **kwargs)
                    with self.assertRaises(mz.MaterializationError) as caught:
                        mz.materialize(repo, 'inventory-service')
                    self.assertEqual(caught.exception.kind, 'unsupported')
                    self.assertFalse((repo / 'output' / 'inventory-service').exists())
        fx.ready_service(self.repo, 'billing-service', extra_files=[fx.file_entry('src/main/java/org/example/billing/utils/Old.java', 'archetype-activity-logger', 20, 'remove')])
        with self.assertRaises(mz.MaterializationError):
            mz.materialize(self.repo, 'billing-service')
        fx.ready_service(self.repo, 'billing-service', extra_files=[fx.file_entry('src/main/java/org/example/billing/x/Made.java', 'made-up-component', 20)])
        with self.assertRaises(mz.MaterializationError):
            mz.materialize(self.repo, 'billing-service')

    def test_identity_generation_is_required_and_not_assumed(self):
        fx.ready_service(self.repo, 'inventory-service')
        plan_file = self.repo / '.factory/services/inventory-service/implementation-plan.yml'
        plan = yaml.safe_load(plan_file.read_bytes())
        plan['technicalChoices']['generated-id']['mechanism'] = 'sequence ITEM_SEQ'
        plan_file.write_text(yaml.safe_dump(plan), encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(caught.exception.kind, 'unsupported')

    def test_renderers_refuse_unresolved_templates_and_missing_markers(self):
        with self.assertRaises(rd.Unsupported):
            rd.from_template('package __BASE_PACKAGE__;\n__OTHER_TOKEN__', 'a.b', 'a/b')
        with self.assertRaises(rd.Unsupported):
            rd.constants_file('class X {}', 'a.b', 'a/b', [], '    // marker')
        with self.assertRaises(rd.Unsupported):
            rd.package_of('docs/readme.md')


class BlockedGateTests(Base):
    def test_a_blocked_service_writes_no_java_and_leaves_the_workspace_untouched(self):
        ws = fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        before = fx.tree(ws.dir)
        with self.assertRaises(gate.GateError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(caught.exception.status, gate.BLOCKED)
        self.assertFalse((self.repo / 'output').exists() and any((self.repo / 'output').iterdir()))
        self.assertEqual(self.java(), [])
        self.assertEqual(fx.tree(ws.dir), before)

    def test_blocked_and_unreviewed_and_unauthorized_services_are_refused(self):
        statuses = {}
        for label, prepare in (('unreviewed', lambda r: (fx.wfx.make_service(r, 'inventory-service', path='/api/v1/items'), None)),
                               ('awaiting', lambda r: (fx.wfx.make_service(r, 'inventory-service', path='/api/v1/items'), fx.wfx.review(r / '.factory/services/inventory-service')))):
            with tempfile.TemporaryDirectory() as other:
                repo = fx.make_repo(Path(other))
                prepare(repo)
                fx.make_plan(repo, 'inventory-service')
                with self.assertRaises(gate.GateError) as caught:
                    mz.materialize(repo, 'inventory-service')
                statuses[label] = caught.exception.status
                self.assertFalse((repo / 'output').exists() and any((repo / 'output').iterdir()))
        self.assertEqual(statuses['unreviewed'], gate.SEMANTIC_REVIEW_PENDING)
        self.assertIn(statuses['awaiting'], (gate.BLOCKED, gate.AWAITING_AUTHORIZATION))

    def test_blocking_one_service_does_not_stop_an_authorized_one(self):
        fx.blocked_gate(self.repo, 'billing-service', fx.SERVICES['billing-service']['route'])
        fx.make_plan(self.repo, 'billing-service')
        fx.ready_service(self.repo, 'inventory-service')
        mz.materialize(self.repo, 'inventory-service')
        with self.assertRaises(gate.GateError):
            mz.materialize(self.repo, 'billing-service')
        self.assertTrue(self.out('inventory-service').exists())
        self.assertFalse(self.out('billing-service').exists())

    def test_the_authorized_fixture_state_is_temporary_and_never_touches_real_workspaces(self):
        fx.ready_service(self.repo, 'inventory-service')
        real = fx.REPO_ROOT / '.factory' / 'services' / 'inventory-service'
        self.assertFalse(real.exists())
        self.assertNotIn(self.tmp.name, str(fx.REPO_ROOT))


class BypassResistanceTests(Base):
    def test_cli_and_script_entry_points_refuse_a_blocked_service(self):
        fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        done = subprocess.run([sys.executable, str(SCRIPT), 'inventory-service'], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertIn('BLOCKED', done.stderr)
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            self.assertEqual(cli.main(['materialize', 'inventory-service']), 3)
        finally:
            os.chdir(cwd)
        self.assertEqual(self.java(), [])

    def test_the_sandbox_runner_refuses_the_materializer_script_for_a_blocked_service(self):
        ws = fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        with self.assertRaises(gate.GateError):
            wsm.run_script(ws, SCRIPT, ['inventory-service'])
        self.assertIn('materialize-full-service', wsm.POST_GATE_SKILLS)

    def test_forged_gate_authorization_plan_or_spec_files_cannot_unlock_generation(self):
        ws = fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        base = ws.dir / 'consistency'
        (base / 'gate.yml').write_text(yaml.safe_dump({'status': gate.CLEARED}), encoding='utf-8')
        (base / 'authorization.yml').write_text(yaml.safe_dump({'evaluationHash': 'forged', 'authorizedBy': 'someone'}), encoding='utf-8')
        data = yaml.safe_load((base / 'findings.yml').read_bytes())
        data['findings'], data['unverified'] = [], []
        (base / 'findings.yml').write_text(yaml.safe_dump(data), encoding='utf-8')
        ws.set_state(status='in-progress', currentPhase='materialization', completedPhases=list(wsm.PHASES))
        with self.assertRaises(gate.GateError):
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(self.java(), [])

    def test_a_plan_of_another_service_a_stale_spec_or_a_changed_archetype_is_refused_before_writing(self):
        fx.ready_service(self.repo, 'inventory-service')
        plan_file = self.repo / '.factory/services/inventory-service/implementation-plan.yml'
        plan = yaml.safe_load(plan_file.read_bytes())
        (self.repo / '.factory/services/inventory-service/service-spec.yml').write_text('service: {name: changed}\n', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(caught.exception.kind, 'stale-plan')
        fx.make_plan(self.repo, 'inventory-service')
        (self.repo / fx.ARCHETYPE / 'conventions.md').write_text('changed', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError):
            mz.materialize(self.repo, 'inventory-service')
        plan['service']['name'] = 'other-service'
        plan_file.write_text(yaml.safe_dump(plan), encoding='utf-8')
        with self.assertRaises(mz.MaterializationError):
            mz.materialize(self.repo, 'inventory-service')
        self.assertFalse(self.out('inventory-service').exists())

    def test_path_traversal_and_absolute_paths_in_a_plan_are_rejected(self):
        for bad in ('../escape/X.java', '/abs/X.java', 'a//b.java', 'C:/x.java'):
            with self.subTest(bad):
                with tempfile.TemporaryDirectory() as other:
                    repo = fx.make_repo(Path(other))
                    fx.ready_service(repo, 'inventory-service', extra_files=[fx.file_entry(bad, 'internal-typed-exception', 30)])
                    with self.assertRaises(mz.MaterializationError):
                        mz.materialize(repo, 'inventory-service')
                    self.assertFalse((repo / 'output' / 'inventory-service').exists())

    def test_the_orchestrator_agent_cannot_edit_output_paths_directly(self):
        text = AGENT.read_text(encoding='utf-8')
        front = text.split('---')[1]
        edit = yaml.safe_load(front)['permission']['edit']
        self.assertEqual(edit.get('output/**'), 'deny')
        self.assertEqual(edit.get('*'), 'deny')
        self.assertIn('workspace_cli.py materialize', text)
        self.assertEqual(yaml.safe_load(front)['permission']['bash'].get('python .opencode/skills/materialize-full-service/scripts/*'), 'allow')


class FileProtectionTests(Base):
    def setUp(self):
        super().setUp()
        fx.ready_service(self.repo, 'inventory-service')
        mz.materialize(self.repo, 'inventory-service')
        self.base = self.out('inventory-service') / 'src/main/java/com/acme/inventory/core'

    def test_a_manually_edited_generated_file_is_preserved_and_blocks_the_whole_run(self):
        entity = self.base / 'model/ItemEntity.java'
        entity.write_text(entity.read_text(encoding='utf-8') + '\n// manual change\n', encoding='utf-8')
        manual = entity.read_bytes()
        plan_file = self.repo / '.factory/services/inventory-service/implementation-plan.yml'
        plan = yaml.safe_load(plan_file.read_bytes())
        # Keep the header contract coherent. M1a rejects mismatched header
        # components before reaching file protection; this case tests a valid
        # regeneration (an additional entity field) against a manual file.
        plan_file.write_text(yaml.safe_dump(plan), encoding='utf-8')
        entity_plan = [f for f in plan['files']['generate'] if f['path'].endswith('ItemEntity.java')][0]
        plan['persistenceModel']['fields'].append({'physicalColumn': 'EXTRA', 'property': 'extra', 'javaType': 'String', 'lob': False, 'primaryKey': False})
        plan_file.write_text(yaml.safe_dump(plan), encoding='utf-8')
        headers = (self.base / 'dto/request/RequestHeaders.java').read_bytes()
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(caught.exception.kind, 'protected-files')
        self.assertEqual(caught.exception.details['blocked'][0]['state'], fp.MODIFIED)
        self.assertEqual(entity.read_bytes(), manual)                  # preserved
        self.assertEqual((self.base / 'dto/request/RequestHeaders.java').read_bytes(), headers)      # atomic: nothing else was rewritten either
        self.assertTrue(entity_plan)

    def test_an_authorization_bound_to_the_exact_content_allows_the_replacement_once(self):
        entity = self.base / 'model/ItemEntity.java'
        generated = entity.read_bytes()
        entity.write_text('manual', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError):
            mz.materialize(self.repo, 'inventory-service')
        ws = self.repo / '.factory/services/inventory-service'
        fp.authorize_overwrite(self.out('inventory-service'), 'src/main/java/com/acme/inventory/core/model/ItemEntity.java', ws, fx.APPROVER, 'Replace manual edit with generated entity (fixture).')
        report = mz.materialize(self.repo, 'inventory-service')
        self.assertEqual(entity.read_bytes(), generated)
        self.assertIn('src/main/java/com/acme/inventory/core/model/ItemEntity.java', report['written'])

    def test_a_pre_existing_untracked_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as other:
            repo = fx.make_repo(Path(other))
            fx.ready_service(repo, 'billing-service')
            manual = repo / 'output/billing-service/src/main/java/org/example/billing/model/InvoiceEntity.java'
            manual.parent.mkdir(parents=True)
            manual.write_text('class Mine {}', encoding='utf-8')
            with self.assertRaises(mz.MaterializationError) as caught:
                mz.materialize(repo, 'billing-service')
            self.assertEqual(caught.exception.details['blocked'][0]['state'], fp.UNTRACKED)
            self.assertEqual(manual.read_text(encoding='utf-8'), 'class Mine {}')
            self.assertEqual(len(list((repo / 'output').rglob('*.java'))), 1)        # nothing else was generated

    def test_application_properties_is_never_read_listed_written_or_blocking(self):
        props = self.out('inventory-service') / 'src/main/resources/application.properties'
        props.parent.mkdir(parents=True, exist_ok=True)
        props.write_text('server.port=9999\nspring.datasource.password=local-only\n', encoding='utf-8')
        before = props.read_bytes()
        reads = []
        original = fp.sha
        with patch.object(fp, 'sha', side_effect=lambda p: (reads.append(Path(p).name), original(p))[1]):
            report = mz.materialize(self.repo, 'inventory-service')
        self.assertNotIn('application.properties', reads)
        self.assertEqual(props.read_bytes(), before)
        self.assertIn('src/main/resources/application.properties', report['excludedUntouched'])
        self.assertNotIn('password', yaml.safe_dump(report))
        manifest = (self.out('inventory-service') / '.generation-manifest.yml').read_text(encoding='utf-8')
        self.assertNotIn('path: src/main/resources/application.properties\n', manifest)          # only the distinct .example file may be tracked

    def test_every_write_goes_through_guard_write(self):
        entity = self.base / 'model/ItemEntity.java'
        entity.unlink()
        calls = []
        original = fp.guard_write
        with patch.object(fp, 'guard_write', side_effect=lambda out, rel, ws: (calls.append(rel), original(out, rel, ws))[1]):
            report = mz.materialize(self.repo, 'inventory-service')
        # Metadata publication is now guarded too; preflight/rechecks may call
        # the manifest guard more than once. Every payload + commit marker must
        # still pass the same guard, with no unexpected writes.
        self.assertEqual(set(calls), set(report['written']) | {mz.MANIFEST})
        self.assertTrue(all(path in calls for path in report['written']))
        self.assertTrue(calls)

    def test_a_guard_that_refuses_at_write_time_aborts_without_writing_that_file(self):
        (self.base / 'model/ItemEntity.java').unlink()
        with patch.object(fp, 'guard_write', side_effect=fp.ProtectedFileError('changed after planning')):
            with self.assertRaises(fp.ProtectedFileError):
                mz.materialize(self.repo, 'inventory-service')
        self.assertFalse((self.base / 'model/ItemEntity.java').exists())


if __name__ == '__main__':
    unittest.main()
