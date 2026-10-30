"""Phase 2 / P4: deterministic Maven project assembler and official validation evidence (synthetic services, temporary directories only)."""
import copy
import hashlib
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))

import synth as fx  # noqa: E402
import full_materializer as mz  # noqa: E402
import assemble_project as ap  # noqa: E402
import validation_evidence as ve  # noqa: E402
import validate_generated_service as vg  # noqa: E402
import test_support as ts  # noqa: E402
from test_generated_tests import Base  # noqa: E402

TEMPLATE = fx.REPO_ROOT / fx.ARCHETYPE / 'template'
BUILD_FILES = {'pom.xml', 'settings.xml', '.gitignore', '.gitattributes', '.mvn/wrapper/maven-wrapper.properties', 'mvnw', 'mvnw.cmd', 'src/main/resources/checkstyle.xml', 'src/main/resources/logback.xml', 'src/main/resources/application.properties.example'}
DEPLOY_FILES = {'Dockerfile', 'Jenkinsfile', 'config/ExternalSecret.yml.j2', 'config/configmap.yml.j2', 'config/deployment.yml.j2'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


class AssemblyTests(Base):
    def assembled(self, name, **kw):
        out = self.gen(name, **kw)
        manifest = yaml.safe_load((out / '.generation-manifest.yml').read_bytes())
        return out, {r['path'] for r in manifest['fileInventory'] if r.get('componentType') == 'project-assembly'}

    def test_every_technical_file_of_the_archetype_is_assembled_for_both_services(self):
        for name in fx.SERVICES:
            out, files = self.assembled(name)
            package_path = fx.SERVICES[name]['package'].replace('.', '/')
            java = {f'src/main/java/{package_path}/{fx.APPLICATION[name]}.java', f'src/main/java/{package_path}/configuration/openapi/OpenApiConfig.java',
                    f'src/main/java/{package_path}/configuration/security/SecurityConfig.java', f'src/main/java/{package_path}/security/filter/JwtRequestFilter.java',
                    f'src/main/java/{package_path}/security/service/JwtValidatorService.java', f'src/main/java/{package_path}/security/service/impl/JwtValidatorServiceImpl.java'}
            self.assertEqual(files, BUILD_FILES | DEPLOY_FILES | java)
            for path in files:
                self.assertTrue((out / path).is_file(), path)

    def test_parameters_are_resolved_from_the_plan_and_the_workspace_values(self):
        out, _ = self.assembled('inventory-service')
        pom = (out / 'pom.xml').read_text(encoding='utf-8')
        self.assertIn('<groupId>com.acme.inventory.core</groupId>', pom)             # D-010: group id = base package
        self.assertIn('<artifactId>inventory-service</artifactId>', pom)
        self.assertIn('<version>1.0.0-SNAPSHOT</version>', pom)
        self.assertIn('com/acme/inventory/core/*.class', pom)
        self.assertIn('**/InventoryServiceApplication.java', pom)
        app = (out / 'src/main/java/com/acme/inventory/core/InventoryServiceApplication.java').read_text(encoding='utf-8')
        self.assertIn('package com.acme.inventory.core;', app)
        self.assertIn('class InventoryServiceApplication', app)
        logback = (out / 'src/main/resources/logback.xml').read_text(encoding='utf-8')
        for expected in ('"service":"inventory-service"', '<timeZone>UTC</timeZone>', 'level="DEBUG"', 'name="com.acme.inventory.core"'):
            self.assertIn(expected, logback)
        self.assertIn('EXPOSE 8085', (out / 'Dockerfile').read_text(encoding='utf-8'))
        self.assertIn('com.acme.inventory.core.InventoryServiceApplication', (out / 'Dockerfile').read_text(encoding='utf-8'))
        self.assertIn("nombreDeCompilado: 'inventory-service'", (out / 'Jenkinsfile').read_text(encoding='utf-8'))
        self.assertIn("nombreVault: 'vault-fixture'", (out / 'Jenkinsfile').read_text(encoding='utf-8'))

    def test_no_unresolved_token_remains_except_the_official_wrapper_identifiers(self):
        for name in fx.SERVICES:
            out, files = self.assembled(name)
            for path in files:
                text = (out / path).read_text(encoding='utf-8')
                self.assertEqual(ap.unresolved(text), [], path)
            self.assertIn('__MVNW_CMD__', (out / 'mvnw.cmd').read_text(encoding='utf-8'))             # allowed wrapper identifier, untouched

    def test_comment_markers_are_replaced_as_whole_lines(self):
        out, _ = self.assembled('billing-service')
        for rel in ('config/ExternalSecret.yml.j2', 'config/configmap.yml.j2'):
            text = (out / rel).read_text(encoding='utf-8')
            self.assertNotIn('ADDITIONAL_DATA', text)
            self.assertNotIn('SPECIFICATION_OWNED', text)

    def test_the_pom_and_the_quality_rules_of_the_archetype_are_preserved_exactly(self):
        out, _ = self.assembled('inventory-service')
        pom = (out / 'pom.xml').read_bytes()
        template = (TEMPLATE / 'pom.xml').read_bytes()
        restored = (pom.replace(b'com.acme.inventory.core', b'__GROUP_ID__', 1).replace(b'inventory-service', b'__ARTIFACT_ID__', 2)
                    .replace(b'1.0.0-SNAPSHOT', b'__PROJECT_VERSION__', 1).replace(b'com/acme/inventory/core', b'__BASE_PACKAGE_PATH__').replace(b'InventoryServiceApplication', b'__APPLICATION_CLASS__'))
        self.assertEqual(restored, template)
        self.assertEqual((out / 'src/main/resources/checkstyle.xml').read_bytes(), (TEMPLATE / 'src/main/resources/checkstyle.xml').read_bytes())
        self.assertEqual((out / 'settings.xml').read_bytes(), (TEMPLATE / 'settings.xml').read_bytes())
        self.assertEqual((out / 'mvnw').read_bytes(), (TEMPLATE / 'mvnw').read_bytes())
        config = ts.pom_jacoco(pom.decode('utf-8'))
        self.assertEqual((config['minimum'], config['counter'], config['value'], config['element']), ('80%', 'INSTRUCTION', 'COVEREDRATIO', 'PACKAGE'))

    def test_the_security_baseline_is_the_archetype_one_without_secrets(self):
        out, _ = self.assembled('inventory-service')
        text = (out / 'src/main/java/com/acme/inventory/core/security/service/impl/JwtValidatorServiceImpl.java').read_text(encoding='utf-8')
        self.assertNotIn('default', text.lower().split('@value')[1][:80] if '@value' in text.lower() else '')
        self.assertTrue(all(not re.search(r'(password|secret)\s*=\s*"[^"$]', (out / p).read_text(encoding='utf-8'), re.I) for p in ('pom.xml', 'Dockerfile', 'Jenkinsfile')))

    def test_deployment_files_are_assembled_only_when_the_plan_authorizes_them(self):
        out, files = self.assembled('billing-service', deploy=False, assembly_values={'vault_name': None, 'builder_image': None, 'k8s_namespace': None})
        self.assertFalse(files & DEPLOY_FILES)
        for rel in DEPLOY_FILES:
            self.assertFalse((out / rel).exists(), rel)
        report = yaml.safe_load((self.ws('billing-service') / 'materialization-report.yml').read_bytes())
        self.assertEqual(report['assembly']['deploymentArtifacts'], 'not-authorized-by-plan')
        self.assertTrue(all(r['reason'] for r in report['assembly']['notAssembled']))

    def test_application_properties_is_excluded_by_policy_and_never_touched(self):
        out = self.repo / 'output' / 'billing-service'
        target = out / 'src/main/resources/application.properties'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'local=environment\n')
        fx.ready_service(self.repo, 'billing-service')
        mz.materialize(self.repo, 'billing-service')
        self.assertEqual(target.read_bytes(), b'local=environment\n')
        manifest = yaml.safe_load((out / '.generation-manifest.yml').read_bytes())
        self.assertNotIn('src/main/resources/application.properties', [r['path'] for r in manifest['fileInventory']])
        report = yaml.safe_load((self.ws('billing-service') / 'materialization-report.yml').read_bytes())
        self.assertEqual(report['assembly']['applicationProperties']['status'], 'excluded-by-policy')
        self.assertIn('environment-only', report['assembly']['applicationProperties']['note'])

    def test_a_new_project_gets_no_application_properties(self):
        out, files = self.assembled('billing-service')
        self.assertFalse((out / 'src/main/resources/application.properties').exists())


class ParameterStopTests(Base):
    def stop(self, name='billing-service', **kw):
        fx.ready_service(self.repo, name, **kw)
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, name)
        self.assertFalse((self.repo / 'output' / name).exists(), 'nothing may be written when a parameter is missing or invalid')
        return caught.exception

    def test_a_missing_logging_parameter_stops_the_assembly_and_names_it(self):
        error = self.stop(assembly_values={'application_log_level': None})
        self.assertEqual(error.kind, 'missing-parameter')
        self.assertEqual([m['parameter'] for m in error.details['missing']], ['application_log_level'])
        self.assertIn('src/main/resources/logback.xml', error.details['missing'][0]['neededBy'])

    def test_a_missing_deployment_parameter_stops_when_deployment_is_authorized(self):
        error = self.stop(assembly_values={'vault_name': None, 'container_port': None})
        self.assertEqual(sorted(m['parameter'] for m in error.details['missing']), ['container_port', 'vault_name'])

    def test_a_missing_application_class_stops_instead_of_being_invented(self):
        def drop(plan):
            plan['service'].pop('applicationClass', None)
        error = self.stop(mutate=drop)
        self.assertEqual(error.kind, 'missing-parameter')
        self.assertIn('application_class', [m['parameter'] for m in error.details['missing']])

    def test_invalid_values_are_rejected_with_the_expected_form(self):
        for values, parameter in (({'application_log_level': 'LOUD'}, 'application_log_level'), ({'container_port': '99999'}, 'container_port')):
            self.setUp()
            error = self.stop(assembly_values=values)
            self.assertEqual(error.kind, 'invalid-parameter')
            self.assertEqual(error.details['invalid'][0]['parameter'], parameter)

    def test_a_disagreement_between_plan_and_parameters_is_a_conflict_not_a_silent_choice(self):
        error = self.stop(assembly_values={'group_id': 'other.group', 'artifact_id': 'billing-service'})
        self.assertEqual(error.kind, 'parameter-conflict')
        self.assertEqual(error.details['conflicts'][0]['parameter'], 'group_id')

    def test_the_check_command_reports_without_writing(self):
        fx.ready_service(self.repo, 'billing-service', assembly_values={'http_log_level': None})
        plan, _ = mz.load_plan(__import__('workspace').Workspace(self.repo, 'billing-service'), self.repo)
        with self.assertRaises(ap.AssemblyError):
            ap.render(plan, self.repo, self.ws('billing-service'), self.repo / 'output' / 'billing-service')
        self.assertFalse((self.repo / 'output' / 'billing-service').exists())


class ProtectionAndIndependenceTests(Base):
    def test_a_hand_modified_assembled_file_is_preserved_and_blocks_the_run(self):
        out = self.gen('billing-service')
        for rel in ('pom.xml', 'src/main/resources/logback.xml', 'src/main/java/org/example/billing/configuration/security/SecurityConfig.java'):
            target = out / rel
            original = target.read_bytes()
            target.write_bytes(original + b'\n<!-- manual -->\n')
            with self.assertRaises(mz.MaterializationError) as caught:
                mz.materialize(self.repo, 'billing-service')
            self.assertEqual(caught.exception.kind, 'protected-files', rel)
            self.assertIn(b'manual', target.read_bytes())
            target.write_bytes(original)

    def test_an_explicit_baseline_create_preserves_but_blocks_an_untracked_file(self):
        out = self.repo / 'output' / 'billing-service'
        out.mkdir(parents=True)
        (out / 'pom.xml').write_bytes(b'<project>hand written</project>')
        fx.ready_service(self.repo, 'billing-service')
        # No explicit write may silently become retain. A manual file stays
        # intact, but the explicit create in the plan blocks the FULL run.
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'billing-service')
        self.assertEqual(caught.exception.kind, 'protected-files')
        self.assertEqual((out / 'pom.xml').read_bytes(), b'<project>hand written</project>')
        self.assertFalse((out / '.generation-manifest.yml').exists())

    def test_a_blocked_gate_assembles_and_writes_nothing(self):
        fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        with self.assertRaises(Exception):
            mz.materialize(self.repo, 'inventory-service')
        self.assertFalse((self.repo / 'output' / 'inventory-service').exists())
        self.assertFalse((self.ws('inventory-service') / 'materialization-report.yml').exists())

    def test_services_are_assembled_independently_in_one_repository(self):
        first = self.gen('inventory-service')
        before = {p.relative_to(first).as_posix(): sha(p.read_bytes()) for p in first.rglob('*') if p.is_file()}
        second = self.gen('billing-service')
        self.assertEqual(before, {p.relative_to(first).as_posix(): sha(p.read_bytes()) for p in first.rglob('*') if p.is_file()})
        self.assertNotIn('inventory', (second / 'pom.xml').read_text(encoding='utf-8'))
        self.assertNotIn('billing', (first / 'Jenkinsfile').read_text(encoding='utf-8'))
        fx.make_plan(self.repo, 'billing-service', assembly_values={'root_log_level': 'ERROR'})
        mz.materialize(self.repo, 'billing-service')
        self.assertIn('level="ERROR"', (second / 'src/main/resources/logback.xml').read_text(encoding='utf-8'))
        self.assertEqual(before, {p.relative_to(first).as_posix(): sha(p.read_bytes()) for p in first.rglob('*') if p.is_file()})

    def test_no_assemble_cannot_silently_omit_a_planned_baseline(self):
        fx.ready_service(self.repo, 'billing-service')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'billing-service', assemble=False)
        self.assertEqual(caught.exception.kind, 'unsupported')
        out = self.repo / 'output' / 'billing-service'
        self.assertFalse((out / 'pom.xml').exists())
        self.assertFalse((out / 'Dockerfile').exists())

    def test_dot_files_keep_their_name_in_the_protection_layer(self):
        self.assertEqual(ap.fp.norm('./.gitignore'), '.gitignore')
        self.assertEqual(ap.fp.norm('.mvn/wrapper/maven-wrapper.properties'), '.mvn/wrapper/maven-wrapper.properties')
        self.assertEqual(ap.fp.norm('\\src\\a'), 'src/a')


class DeterminismTests(Base):
    def tree(self, name):
        out = self.repo / 'output' / name
        return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob('*')) if p.is_file()}

    def test_independent_repositories_produce_byte_identical_projects_manifests_and_reports(self):
        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                repo = fx.make_repo(Path(tmp))
                fx.ready_service(repo, 'inventory-service')
                mz.materialize(repo, 'inventory-service')
                ws = repo / '.factory/services/inventory-service'
                out = repo / 'output/inventory-service'
                results.append(({p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob('*')) if p.is_file()},
                                {n: (ws / n).read_bytes() for n in ('materialization-report.yml', 'coverage-scope.yml', 'tests-traceability.yml', 'assumptions-register.yml')}))
        self.assertEqual(results[0], results[1])

    def test_a_second_run_writes_nothing_and_keeps_every_hash(self):
        self.gen('billing-service')
        before = self.tree('billing-service')
        again = mz.materialize(self.repo, 'billing-service')
        self.assertEqual(again['written'], [])
        self.assertEqual(before, self.tree('billing-service'))

    def test_the_manifest_records_a_hash_for_every_assembled_file_and_the_parameters_digest(self):
        out = self.gen('billing-service')
        manifest = yaml.safe_load((out / '.generation-manifest.yml').read_bytes())
        rows = {r['path']: r for r in manifest['fileInventory']}
        assembled = [r for r in rows.values() if r.get('componentType') == 'project-assembly']
        self.assertGreaterEqual(len(assembled), 20)
        for row in assembled:
            self.assertEqual(row['sha256'], sha((out / row['path']).read_bytes()))
        self.assertEqual(manifest['inputs']['assembly']['assembler'], ap.VERSION)
        self.assertEqual(len(manifest['inputs']['assembly']['parametersSha256']), 64)

    def test_changing_a_parameter_changes_only_the_files_that_use_it(self):
        self.gen('billing-service')
        before = self.tree('billing-service')
        fx.make_plan(self.repo, 'billing-service', assembly_values={'time_zone': 'America/Lima'})
        mz.materialize(self.repo, 'billing-service')
        after = self.tree('billing-service')
        changed = sorted(p for p in after if before.get(p) != after[p] and p != '.generation-manifest.yml')
        self.assertEqual(changed, ['Dockerfile'])

    def test_the_generic_validator_accepts_the_assembled_project(self):
        for name in fx.SERVICES:
            self.gen(name)
            report = vg.validate(self.repo, name)
            self.assertEqual(report['status'], 'passed', report['violations'])


class EvidenceTests(Base):
    """Evidence mechanics with fabricated reports (negative cases) - the real Maven build is exercised in OfficialMavenValidationTests."""

    def project(self, name='billing-service'):
        out = self.gen(name)
        build = self.repo / f'{name}-build'
        shutil.copytree(out, build)
        return out, build

    def fake_reports(self, build, violations=0, failures=0, jacoco_ratio=(97, 0)):
        target = build / 'target'
        (target / 'surefire-reports').mkdir(parents=True)
        (target / 'surefire-reports' / 'TEST-x.xml').write_text(f'<testsuite tests="5" failures="{failures}" errors="0" skipped="0"/>', encoding='utf-8')
        errors = ''.join('<error source="x.Indentation" line="1"/>' for _ in range(violations))
        (target / 'checkstyle-result.xml').write_text(f'<checkstyle><file name="a">{errors}</file></checkstyle>', encoding='utf-8')
        (target / 'site' / 'jacoco').mkdir(parents=True)
        (target / 'site' / 'jacoco' / 'jacoco.csv').write_text('GROUP,PACKAGE,CLASS,INSTRUCTION_MISSED,INSTRUCTION_COVERED\ng,p.service,C,%d,%d\n' % (jacoco_ratio[1], jacoco_ratio[0]), encoding='utf-8')

    LOG_OK = ('[INFO] --- checkstyle:3.3.1:check (default) @ s ---\n[INFO] You have 0 Checkstyle violations.\n[INFO] --- compiler:3.8.1:compile (default-compile) @ s ---\n'
              '[INFO] --- compiler:3.8.1:testCompile (default-testCompile) @ s ---\n[INFO] All coverage checks have been met.\n[INFO] BUILD SUCCESS\n')

    def ingest(self, build, log, code, name='billing-service'):
        log_path = self.repo / 'maven.log'
        log_path.write_text(log, encoding='utf-8')
        return ve.ingest(self.repo, name, build, log_path, code)

    def test_statuses_come_only_from_the_reports(self):
        out, build = self.project()
        self.fake_reports(build)
        record = self.ingest(build, self.LOG_OK, 0)
        tools = record['tools']
        self.assertEqual({k: v['status'] for k, v in tools.items()}, {'maven': 'passed', 'compilation': 'passed', 'testsExecuted': 'passed', 'checkstyleOfficial': 'passed', 'jacoco': 'passed'})
        self.assertEqual(tools['testsExecuted']['total'], 5)
        self.assertEqual(record['projectTreeSha256'], ve.project_hash(out)[0])

    def test_failures_are_recorded_as_failed_never_passed(self):
        out, build = self.project()
        self.fake_reports(build, violations=3, failures=2, jacoco_ratio=(50, 50))
        log = self.LOG_OK.replace('You have 0 Checkstyle', 'You have 3 Checkstyle').replace('All coverage checks have been met.', 'Rule violated for package p.service').replace('BUILD SUCCESS', 'BUILD FAILURE')
        tools = self.ingest(build, log, 1)['tools']
        self.assertEqual((tools['maven']['status'], tools['checkstyleOfficial']['status'], tools['testsExecuted']['status'], tools['jacoco']['status']), ('failed', 'failed', 'failed', 'failed'))
        self.assertEqual(tools['checkstyleOfficial']['violations'], 3)
        self.assertEqual(tools['jacoco']['belowThreshold'], ['p.service'])

    def test_a_tool_that_did_not_run_is_not_executed_or_unverified(self):
        out, build = self.project()
        log = '[INFO] --- checkstyle:3.3.1:check (default) @ s ---\n[ERROR] BUILD FAILURE\n'
        tools = self.ingest(build, log, 1)['tools']
        self.assertEqual((tools['compilation']['status'], tools['testsExecuted']['status'], tools['checkstyleOfficial']['status'], tools['jacoco']['status']),
                         ('not-executed', 'not-executed', 'unverified', 'not-verified'))

    def test_the_threshold_comes_from_the_pom_of_the_project_not_from_the_recorder(self):
        out, build = self.project()
        self.fake_reports(build, jacoco_ratio=(79, 21))
        tools = self.ingest(build, self.LOG_OK, 0)['tools']
        self.assertEqual(tools['jacoco']['threshold']['minimum'], '80%')
        self.assertEqual(tools['jacoco']['status'], 'failed')        # 79 % < 80 % even though the log claims success: the report decides

    def test_a_build_of_a_different_project_is_refused(self):
        out, build = self.project()
        self.fake_reports(build)
        (build / 'src/main/resources/logback.xml').write_text('changed', encoding='utf-8')
        with self.assertRaises(ve.EvidenceError):
            self.ingest(build, self.LOG_OK, 0)
        self.assertFalse((self.ws('billing-service') / ts.OFFICIAL).exists())

    def test_a_project_that_drifted_from_its_manifest_gets_no_evidence(self):
        out, build = self.project()
        self.fake_reports(build)
        (out / 'pom.xml').write_bytes((out / 'pom.xml').read_bytes() + b'\n')
        with self.assertRaises(ve.EvidenceError):
            self.ingest(build, self.LOG_OK, 0)

    def test_evidence_becomes_stale_when_the_project_changes(self):
        out, build = self.project()
        self.fake_reports(build)
        self.ingest(build, self.LOG_OK, 0)
        self.assertEqual(ve.status(self.repo, 'billing-service')['tools']['jacoco'], 'passed')
        fx.make_plan(self.repo, 'billing-service', assembly_values={'root_log_level': 'ERROR'})
        mz.materialize(self.repo, 'billing-service')
        status = ve.status(self.repo, 'billing-service')['tools']
        self.assertEqual(set(status.values()), {'stale'})
        scope = yaml.safe_load((self.ws('billing-service') / 'coverage-scope.yml').read_bytes())
        self.assertEqual(scope['tools']['jacoco']['status'], 'stale')
        self.assertEqual(scope['status'], 'not-verified')

    def test_the_coverage_scope_follows_the_evidence(self):
        out, build = self.project()
        self.fake_reports(build)
        self.ingest(build, self.LOG_OK, 0)
        scope = yaml.safe_load((self.ws('billing-service') / 'coverage-scope.yml').read_bytes())
        self.assertEqual((scope['status'], scope['tools']['jacoco']['status'], scope['tools']['checkstyleOfficial']['status']), ('verified-by-maven-evidence', 'passed', 'passed'))
        self.assertEqual(vg.validate(self.repo, 'billing-service')['status'], 'passed')

    def test_a_tampered_tool_status_is_detected_by_the_validator(self):
        out, build = self.project()
        path = self.ws('billing-service') / 'coverage-scope.yml'
        data = yaml.safe_load(path.read_bytes())
        data['tools']['checkstyleOfficial']['status'] = 'passed'
        data['status'] = 'verified-by-maven-evidence'
        path.write_text(yaml.safe_dump(data), encoding='utf-8')
        failed = [v['check'] for v in vg.validate(self.repo, 'billing-service')['violations']]
        self.assertIn('toolStatusesAreHonest', failed)
        self.assertIn('coverageNeverClaimed', failed)

    def test_without_evidence_every_tool_is_not_executed_unverified_or_not_verified(self):
        self.gen('billing-service')
        tools = yaml.safe_load((self.ws('billing-service') / 'coverage-scope.yml').read_bytes())['tools']
        self.assertEqual({k: tools[k]['status'] for k in ts.OFFICIAL_TOOLS}, ts.NOT_RUN)

    def test_running_maven_requires_explicit_authorization(self):
        self.gen('billing-service')
        with self.assertRaises(ve.EvidenceError):
            ve.run_official(self.repo, 'billing-service', self.repo / 'work', False)
        self.assertFalse((self.repo / 'work').exists())

    def test_no_evidence_for_a_service_with_a_blocked_gate(self):
        fx.blocked_gate(self.repo, 'inventory-service', fx.SERVICES['inventory-service']['route'])
        fx.make_plan(self.repo, 'inventory-service')
        with self.assertRaises(Exception):
            ve.run_official(self.repo, 'inventory-service', self.repo / 'work', True)


@unittest.skipUnless(os.environ.get('SERVICE_GENERATOR_AUTHORIZED_MAVEN_TESTS') == '1' and shutil.which('mvn') and (Path.home() / '.m2' / 'repository').is_dir(), 'Explicit Maven test authorization and local Maven cache required')
class OfficialMavenValidationTests(unittest.TestCase):
    """Real offline Maven builds (mvn -o -B -s settings.xml verify) of both synthetic services in temporary directories."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = fx.make_repo(Path(cls.tmp.name))
        cls.records = {}
        for name in fx.SERVICES:
            fx.ready_service(cls.repo, name)
            mz.materialize(cls.repo, name)
            cls.records[name] = ve.run_official(cls.repo, name, Path(cls.tmp.name) / 'work', True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_both_services_pass_every_official_tool_with_real_numbers(self):
        for name, record in self.records.items():
            tools = record['tools']
            self.assertEqual({k: v['status'] for k, v in tools.items()}, {k: 'passed' for k in ts.OFFICIAL_TOOLS}, name)
            self.assertEqual((tools['maven']['exitCode'], tools['maven']['buildResult']), (0, 'BUILD SUCCESS'))
            self.assertEqual((tools['testsExecuted']['total'], tools['testsExecuted']['failures'], tools['testsExecuted']['errors']), (sum(f.read_text(encoding='utf-8').count('@Test') for f in (self.repo / 'output' / name / 'src/test/java').rglob('*.java')), 0, 0))
            self.assertEqual(tools['checkstyleOfficial']['violations'], 0)
            self.assertGreater(tools['checkstyleOfficial']['filesChecked'], 30)
            self.assertEqual(tools['jacoco']['threshold']['minimum'], '80%')
            self.assertEqual(tools['jacoco']['belowThreshold'], [])
            self.assertTrue(all(v['ratio'] >= 0.8 for v in tools['jacoco']['packages'].values()))

    def test_the_evidence_is_bound_to_the_exact_project_and_registered_in_the_workspace(self):
        for name, record in self.records.items():
            out = self.repo / 'output' / name
            self.assertEqual(record['projectTreeSha256'], ve.project_hash(out)[0])
            self.assertEqual(record['projectTreeSha256'], yaml.safe_load((out / '.generation-manifest.yml').read_bytes())['payloadTreeSha256'])
            self.assertTrue((self.repo / '.factory/services' / name / ts.OFFICIAL).is_file())
            self.assertEqual(len(record['reports']['mavenLog']), 64)
            scope = yaml.safe_load((self.repo / '.factory/services' / name / 'coverage-scope.yml').read_bytes())
            self.assertEqual((scope['status'], scope['tools']['maven']['status']), ('verified-by-maven-evidence', 'passed'))
            self.assertEqual(vg.validate(self.repo, name)['status'], 'passed')

    def test_maven_never_touched_the_real_output_directory(self):
        for name in fx.SERVICES:
            self.assertFalse((self.repo / 'output' / name / 'target').exists())

    def test_regenerating_keeps_the_evidence_fresh_because_the_project_is_identical(self):
        mz.materialize(self.repo, 'billing-service')
        self.assertEqual(ve.status(self.repo, 'billing-service')['tools']['jacoco'], 'passed')


if __name__ == '__main__':
    unittest.main()
