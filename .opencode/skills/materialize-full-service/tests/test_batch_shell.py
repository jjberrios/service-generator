"""Synthetic batch end-to-end tests. No reference reads, Maven or remote execution."""
from pathlib import Path
import copy
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

REPO = Path(__file__).resolve().parents[4]
for skill in ('plan-service-implementation', 'service-workspace', 'materialize-full-service'):
    sys.path.insert(0, str(REPO / '.opencode/skills' / skill / 'scripts'))
import profiles
import batch_shell_plan as bp
import batch_shell_materializer as bm
import consistency_gate as gate
import full_materializer as fm


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(obj, sort_keys=False), encoding='utf-8')


class BatchShellTests(unittest.TestCase):
    ARCH = 'archetypes/claro-java-8-shell/v1.0.0'
    FILES = 15

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='batch-shell-test-')
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.service = 'batch-example'
        self.ws = self.repo / '.factory/services' / self.service
        self.ws.mkdir(parents=True)
        self.arch_rel = self.ARCH
        self.arch = self.repo / self.arch_rel
        shutil.copytree(REPO / self.arch_rel, self.arch)
        arch = yaml.safe_load((self.arch / 'archetype.yml').read_bytes())
        arch['identity']['generationEnabled'] = True  # fixture-only authorization, never the real archetype
        dump(self.arch / 'archetype.yml', arch)
        source = self.repo / 'input/sparx/flow.htm'
        source.parent.mkdir(parents=True)
        source.write_text('<html>SYNTHETIC transfer flow, abort on failure, empty list succeeds</html>', encoding='utf-8')
        evidence = ['ea#synthetic transfer flow']
        properties = [{'key': 'ftp.test.' + key, 'field': field, 'secret': key == 'password', 'evidence': evidence}
                      for key, field in [('host', 'HOST'), ('username', 'USER'), ('port', 'PORT'), ('password', 'PASSWORD'),
                                         ('remote', 'REMOTE'), ('local', 'LOCAL'), ('date', 'DATE'), ('format', 'FORMAT')]]
        batch = {'version': 1, 'sourceBindings': [{'id': 'ea', 'path': 'input/sparx/flow.htm', 'sha256': sha(source)}],
                 'properties': properties,
                 'connections': [{'id': 'Source', 'username': 'ftp.test.username', 'host': 'ftp.test.host', 'port': 'ftp.test.port',
                                  'password': 'ftp.test.password', 'credentialMode': 'resolved-external', 'evidence': evidence}],
                 'steps': [{'id': 'open', 'kind': 'connect', 'connection': 'Source', 'evidence': evidence},
                           {'id': 'list', 'kind': 'list-mtime', 'connection': 'Source', 'remoteDirectory': 'ftp.test.remote',
                            'date': 'ftp.test.date', 'dateFormat': 'ftp.test.format', 'onFailure': 'abort', 'emptyPolicy': 'success', 'evidence': evidence},
                           {'id': 'each', 'kind': 'for-each', 'list': 'list', 'evidence': evidence, 'steps': [
                               {'id': 'get', 'kind': 'download', 'connection': 'Source', 'filename': '$item',
                                'remoteDirectory': 'ftp.test.remote', 'localDirectory': 'ftp.test.local', 'onFailure': 'abort', 'evidence': evidence},
                               {'id': 'put', 'kind': 'upload', 'connection': 'Source', 'filename': '$item',
                                'remoteDirectory': 'ftp.test.remote', 'localDirectory': 'ftp.test.local', 'onFailure': 'abort', 'evidence': evidence}]}],
                 'outcomes': {'success': 'idf0', 'sftpFailure': 'idt2', 'generalFailure': 'idt3', 'evidence': evidence}}
        self.spec = {'service': {'name': self.service, 'profile': 'batch-shell'}, 'batch': batch,
                     'readiness': {'strictImplementationReady': True, 'functionalCodeGenerationReady': True}, 'unresolved': {}}
        self.cfg = {'target': {'service': self.service, 'archetype': self.arch_rel, 'output_directory': 'output/' + self.service},
                    'template_parameters': {'GROUP_ID': 'pe.com.claro.shell', 'ARTIFACT_ID': 'SH_Example', 'PROJECT_VERSION': '1.0.0',
                                            'BASE_PACKAGE': 'pe.com.claro.shell.example', 'MAIN_CLASS': 'ExampleMain',
                                            'SERVICE_INTERFACE': 'ExampleService', 'PROPERTIES_FILE_BASENAME': 'Example'}}
        dump(self.ws / 'service-generation-state.yml', {'targetService': self.service, 'archetype': {'path': self.arch_rel}})
        dump(self.ws / 'service-spec.yml', self.spec)
        dump(self.ws / 'sparx-spec.yml', {'service': self.spec['service'], 'batch': batch})
        dump(self.ws / 'sparx-target-authority.yml', {'kind': 'sparx-target-authority', 'hierarchySources': {'openapi': None}, 'target': {'name': self.service}, 'selection': {'status': 'resolved', 'authoritativeBranchRootId': '0.1'}})
        dump(self.ws / 'full-planning-input.yml', self.cfg)
        self.review()
        self.authorize()

    def review(self):
        hashes = {name: sha(self.ws / filename) for name, filename in (
                  ('sparxSpecSha256', 'sparx-spec.yml'), ('authoritySha256', 'sparx-target-authority.yml'))}
        hashes['archetypeSha256'] = sha(self.arch / 'archetype.yml')
        dump(self.ws / 'consistency/batch-review.yml', {'reviewed': True, 'reviewedBy': 'test-semantic-review', 'reviewedAgainst': hashes, 'findings': []})

    def authorize(self):
        sys.path.insert(0, str(REPO / '.opencode/skills/service-workspace/tests'))
        import fixtures
        fixtures.simulate_manual(self.repo, self.service)

    def plan(self):
        return bp.write_plan(self.repo, yaml, self.ws / 'full-planning-input.yml')

    def test_profile_and_deterministic_plan(self):
        self.assertEqual(profiles.resolve(yaml.safe_load((self.arch / 'archetype.yml').read_bytes())), bm.PROFILE)
        self.plan()
        first = (self.ws / 'implementation-plan.yml').read_bytes()
        self.plan()
        self.assertEqual(first, (self.ws / 'implementation-plan.yml').read_bytes())
        self.assertEqual(len(yaml.safe_load(first)['files']['generate']), self.FILES)

    def test_cli_dispatch_in_workspace_sandbox_and_parameter_resolver(self):
        import workspace
        shutil.copytree(REPO / '.opencode/skills', self.repo / '.opencode/skills',
                        ignore=shutil.ignore_patterns('__pycache__'))
        ws = workspace.Workspace(self.repo, self.service)
        for name in ('build_implementation_plan.py', 'resolve_generation_parameters.py'):
            run = workspace.run_script(ws, self.repo / '.opencode/skills/plan-service-implementation/scripts' / name,
                                       ['--mode', 'full', '--planning-input', '.factory/full-planning-input.yml'])
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(yaml.safe_load((self.ws / 'implementation-plan.yml').read_bytes())['plan']['profile'], bm.PROFILE)

    def test_listing_by_filename_empty_abort_and_explicit_disconnect(self):
        spec = copy.deepcopy(self.spec)
        spec['batch']['steps'][1].update(kind='list-name', emptyPolicy='abort')
        spec['batch']['steps'].append({'id': 'close', 'kind': 'disconnect', 'connection': 'Source', 'evidence': ['ea#synthetic transfer flow']})
        plan = bp.build(self.repo, spec, self.cfg)
        text = bm.service_source(plan)
        self.assertIn('listarArchivosPorNombreFecha', text)
        self.assertIn('batchList_list.isEmpty()', text)
        self.assertIn('batchConn_Source = null;', text)

    def test_materialization_idempotence_and_reference_conventions(self):
        self.plan()
        first = fm.materialize(self.repo, self.service)
        out = self.repo / 'output' / self.service
        manifest = (out / fm.MANIFEST).read_bytes()
        second = fm.materialize(self.repo, self.service)
        self.assertEqual(first['status'], 'complete')
        self.assertEqual(second['written'], [])
        self.assertEqual(manifest, (out / fm.MANIFEST).read_bytes())
        import validate_generated_service as validator
        result = validator.validate(self.repo, self.service)
        self.assertEqual(result['status'], 'passed', result['violations'])
        self.assertEqual(result['checkstyleOfficial'], 'not-applicable')
        service = (out / 'src/main/java/pe/com/claro/shell/example/service/ExampleServiceImpl.java').read_text()
        self.assertIn('SFTPConnectionManager', service)
        self.assertIn('finally', service)
        self.assertNotIn('System.exit', service)
        self.assertNotIn('org.springframework.boot', service)
        self.assertNotIn('jakarta.', service)
        cfgs = list((out / 'config').glob('*.properties'))
        self.assertEqual(len(cfgs), 1)
        self.assertTrue(all(l.endswith('=') or l.startswith('#') for l in cfgs[0].read_text(encoding='utf-8').splitlines()))
        self.assertIn('`ftp.test.host`', (out / 'README.MD').read_text(encoding='utf-8'))
        self.assertNotIn('System.exit', (out / 'src/main/java/pe/com/claro/shell/example/ExampleMain.java').read_text())

    def test_gate_requires_review_authorization_and_live_sources(self):
        import fixtures
        fixtures.revoke_reviews(self.repo, self.service)
        self.assertEqual(gate.current_decision(self.ws, self.repo, self.service)['status'], gate.AWAITING_AUTHORIZATION)
        with self.assertRaises(gate.GateError):
            self.plan()
        self.authorize()
        (self.repo / 'input/sparx/flow.htm').write_text('CHANGED', encoding='utf-8')
        with self.assertRaises(gate.GateError):
            self.plan()
        self.assertFalse((self.repo / 'output').exists())

    def test_http_cannot_be_bypassed_with_batch_label(self):
        dump(self.ws / 'openapi-spec.yml', {'operations': []})
        self.assertEqual(gate.current_decision(self.ws, self.repo, self.service)['status'], gate.BLOCKED)

    def test_unknown_steps_and_missing_evidence_fail_closed(self):
        for mutate in (lambda b: b['steps'][1].update(kind='soap'),
                       lambda b: b['steps'][1].update(evidence=[]),
                       lambda b: b['connections'][0].update(credentialMode='decrypt-soap'),
                       lambda b: b['steps'][1].update(emptyPolicy='guess'),
                       lambda b: b['properties'][0].update(field='class')):
            spec = copy.deepcopy(self.spec)
            mutate(spec['batch'])
            with self.subTest(spec=spec['batch']['steps'][1]), self.assertRaises(ValueError):
                bp.build(self.repo, spec, self.cfg)

    def test_archetype_must_be_enabled_and_parameters_explicit(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg['template_parameters']['MAIN_CLASS']
        with self.assertRaises(ValueError):
            bp.build(self.repo, self.spec, cfg)
        arch = yaml.safe_load((self.arch / 'archetype.yml').read_bytes())
        arch['identity']['generationEnabled'] = False
        dump(self.arch / 'archetype.yml', arch)
        with self.assertRaises(ValueError):
            bp.build(self.repo, self.spec, self.cfg)

    def test_manual_file_preserved_and_no_partial_output(self):
        self.plan()
        out = self.repo / 'output' / self.service
        out.mkdir(parents=True)
        (out / 'pom.xml').write_text('MANUAL', encoding='utf-8')
        with self.assertRaises(fm.MaterializationError) as caught:
            fm.materialize(self.repo, self.service)
        self.assertEqual(caught.exception.kind, 'protected-files')
        self.assertEqual([p.name for p in out.iterdir()], ['pom.xml'])
        self.assertEqual((out / 'pom.xml').read_text(), 'MANUAL')

    def test_excluded_configuration_never_read_and_dry_run_writes_nothing(self):
        self.plan()
        self.assertTrue(fm.materialize(self.repo, self.service, dry_run=True)['dryRun'])
        self.assertFalse((self.repo / 'output').exists())
        out = self.repo / 'output' / self.service
        local = out / 'src/main/resources/application-local.properties'
        local.parent.mkdir(parents=True)
        local.write_text('LOCAL', encoding='utf-8')
        original = Path.read_bytes
        def guarded(path):
            if path == local:
                raise AssertionError('protected file read')
            return original(path)
        with patch.object(Path, 'read_bytes', guarded):
            fm.materialize(self.repo, self.service)
        self.assertEqual(local.read_text(), 'LOCAL')

    def test_tampered_plan_and_stale_parameters_stop_without_writing(self):
        self.plan()
        planfile = self.ws / 'implementation-plan.yml'
        plan = yaml.safe_load(planfile.read_bytes())
        plan['files']['generate'][0]['path'] = '../escape'
        dump(planfile, plan)
        with self.assertRaises(fm.MaterializationError):
            fm.materialize(self.repo, self.service)
        self.plan()
        (self.ws / 'generation-parameters.yml').write_text('changed', encoding='utf-8')
        with self.assertRaises((fm.MaterializationError, gate.GateError)):
            fm.materialize(self.repo, self.service)
        self.assertFalse((self.repo / 'output').exists())

    def test_modified_tracked_file_and_user_owned_file_protected(self):
        self.plan()
        fm.materialize(self.repo, self.service)
        out = self.repo / 'output' / self.service
        pom = out / 'pom.xml'
        pom.write_text(pom.read_text() + '\n<!-- manual -->', encoding='utf-8')
        with self.assertRaises(fm.MaterializationError):
            fm.materialize(self.repo, self.service)
        self.assertIn('manual', pom.read_text())

    def test_user_owned_identical_content_is_not_adopted(self):
        self.plan()
        fm.materialize(self.repo, self.service)
        dump(self.ws / 'user-owned-files.yml', {'patterns': ['pom.xml']})
        with self.assertRaises(fm.MaterializationError) as error:
            fm.materialize(self.repo, self.service)
        self.assertEqual(error.exception.kind, 'protected-files')

    def test_review_and_sparx_equality_cannot_be_faked_by_stored_status(self):
        dump(self.ws / 'consistency/gate.yml', {'status': 'CLEARED'})
        dump(self.ws / 'sparx-spec.yml', {'service': self.spec['service'], 'batch': {}})
        with self.assertRaises(gate.GateError):
            gate.check_cleared(self.ws, self.repo, self.service)
        self.assertFalse((self.repo / 'output').exists())

    def test_generated_java_compiles_and_junit_runs_with_local_jars(self):
        javac, java = shutil.which('javac'), shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK unavailable; compilation not verified')
        cache = Path.home() / '.m2/repository'
        coords = [('org/springframework/spring-context', 'spring-context-*.jar'),
                  ('org/springframework/spring-beans', 'spring-beans-*.jar'),
                  ('org/springframework/spring-core', 'spring-core-*.jar'),
                  ('log4j/log4j', 'log4j-*.jar'), ('com/jcraft/jsch', 'jsch-*.jar'),
                  ('junit/junit', 'junit-4*.jar'), ('org/hamcrest/hamcrest-core', 'hamcrest-core-*.jar'),
                  ('org/mockito/mockito-core', 'mockito-core-2*.jar'),
                  ('net/bytebuddy/byte-buddy', 'byte-buddy-*.jar'), ('net/bytebuddy/byte-buddy-agent', 'byte-buddy-agent-*.jar'),
                  ('org/objenesis/objenesis', 'objenesis-*.jar')]
        jars = []
        for directory, glob in coords:
            matches = sorted(p for p in (cache / directory).glob('*/' + glob) if not p.name.endswith(('-sources.jar', '-javadoc.jar')))
            if not matches:
                self.skipTest('Missing local dependency: ' + directory + '; Maven not invoked')
            jars.append(str(matches[-1]))
        self.plan()
        fm.materialize(self.repo, self.service)
        output = self.repo / 'output' / self.service
        classes = self.repo / 'classes'
        classes.mkdir()
        import os
        cp = os.pathsep.join(jars)
        sources = [str(p) for p in output.rglob('*.java')]
        run = subprocess.run([javac, '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp, '-d', str(classes), *sources], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        run = subprocess.run([java, '-cp', str(classes) + os.pathsep + cp, 'org.junit.runner.JUnitCore',
                              'pe.com.claro.shell.example.service.ExampleServiceImplTest'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_all_generated_java_parses_as_java8_without_dependency_resolution(self):
        javac, java = shutil.which('javac'), shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK unavailable; Java syntax not verified')
        self.plan()
        fm.materialize(self.repo, self.service)
        output = self.repo / 'output' / self.service
        helper = self.repo / 'SyntaxCheck.java'
        helper.write_text('''import java.util.Arrays;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaFileObject;
import javax.tools.JavaCompiler;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;
import com.sun.source.util.JavacTask;
public class SyntaxCheck {
  public static void main(String[] args) throws Exception {
    JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
    DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
    try (StandardJavaFileManager manager = compiler.getStandardFileManager(diagnostics, null, null)) {
      JavacTask task = (JavacTask) compiler.getTask(null, manager, diagnostics,
          Arrays.asList("-proc:none", "-source", "8", "-encoding", "UTF-8"), null,
          manager.getJavaFileObjectsFromStrings(Arrays.asList(args)));
      task.parse();
      for (Diagnostic<? extends JavaFileObject> d : diagnostics.getDiagnostics()) {
        if (d.getKind() == Diagnostic.Kind.ERROR) {
          throw new AssertionError(d.toString());
        }
      }
    }
  }
}
''', encoding='utf-8')
        built = subprocess.run([javac, '-d', str(self.repo), str(helper)], capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        sources = [str(p) for p in output.rglob('*.java')]
        parsed = subprocess.run([java, '-cp', str(self.repo), 'SyntaxCheck', *sources], capture_output=True, text=True)
        self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)


class BatchFlowPackage7Tests(BatchShellTests):
    def test_ungrounded_evidence_is_rejected_by_the_gate(self):
        for section in (self.spec['batch'],):
            section['steps'][0]['evidence'] = ['ea#slug-that-the-page-never-says']
        dump(self.ws / 'sparx-spec.yml', {'service': self.spec['service'], 'batch': self.spec['batch']})
        dump(self.ws / 'service-spec.yml', self.spec)
        result = gate.current_decision(self.ws, self.repo, self.service)
        self.assertEqual(result['status'], gate.BLOCKED)
        self.assertIn('ungrounded', ' '.join(result['problems']))

    def test_gate_clears_before_the_service_spec_exists_and_consolidation_copies_only_the_candidate(self):
        (self.ws / 'service-spec.yml').unlink()
        self.review()
        self.authorize()
        self.assertEqual(gate.current_decision(self.ws, self.repo, self.service)['status'], gate.CLEARED)
        shutil.copytree(REPO / '.opencode/skills', self.repo / '.opencode/skills',
                        ignore=shutil.ignore_patterns('__pycache__'))
        script = self.repo / '.opencode/skills/reconcile-service-spec/scripts/consolidate_batch_spec.py'
        import workspace
        (self.repo / '.opencode').mkdir(exist_ok=True)
        run = workspace.run_script(workspace.Workspace(self.repo, self.service), script, [])
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        produced = yaml.safe_load((self.ws / 'service-spec.yml').read_bytes())
        self.assertEqual(produced['batch'], self.spec['batch'])
        self.assertEqual(set(produced), {'service', 'batch', 'readiness', 'unresolved', 'warnings'})

    def test_consolidation_is_refused_without_authorization(self):
        (self.ws / 'service-spec.yml').unlink()
        import fixtures
        fixtures.revoke_reviews(self.repo, self.service)
        import workspace
        (self.repo / '.opencode').mkdir(exist_ok=True)
        with self.assertRaises(Exception):
            run = workspace.run_script(workspace.Workspace(self.repo, self.service),
                                       REPO / '.opencode/skills/reconcile-service-spec/scripts/consolidate_batch_spec.py', [])
            if run.returncode == 0:
                return
            raise RuntimeError(run.stderr)
        self.assertFalse((self.ws / 'service-spec.yml').exists())

    def test_authority_must_come_from_the_non_http_resolver(self):
        dump(self.ws / 'sparx-target-authority.yml', {'target': {'name': self.service}, 'selection': {'status': 'resolved', 'authoritativeBranchRootId': '0.1'}})
        self.review()
        self.assertEqual(gate.current_decision(self.ws, self.repo, self.service)['status'], gate.BLOCKED)


class BatchShellDecryptTests(BatchShellTests):
    def decrypted_spec(self):
        spec = copy.deepcopy(self.spec)
        for prop in spec['batch']['properties']:
            if prop['field'] in ('USER', 'PASSWORD'):
                prop['secret'] = True
        spec['batch']['connections'][0]['credentialMode'] = 'decrypted-soap'
        return spec

    def test_decrypted_soap_connection_generates_decrypt_then_connect(self):
        text = bm.service_source(bp.build(self.repo, self.decrypted_spec(), self.cfg))
        self.assertIn('desencriptarCredenciales(msjTrx,', text)
        self.assertIn('credenciales.getUsuarioAplicacion()', text)
        self.assertIn('catch (WSException e)', text)

    def test_decrypted_soap_requires_secret_properties(self):
        spec = self.decrypted_spec()
        spec['batch']['properties'][1]['secret'] = False
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)

    def test_decrypt_module_is_pruned_when_unused_and_kept_when_used(self):
        plain = bm.render_project(bp.build(self.repo, self.spec, self.cfg), self.repo)
        used = bm.render_project(bp.build(self.repo, self.decrypted_spec(), self.cfg), self.repo)
        base = 'src/main/java/pe/com/claro/shell/example/'
        for rel in ('proxy/EbsConsultaClavesWSService.java', 'proxy/EbsConsultaClavesWSServiceImpl.java', 'exception/WSException.java'):
            self.assertNotIn(base + rel, plain)
            self.assertIn(base + rel, used)
        self.assertNotIn('src/main/resources/applicationProxyWS.xml', plain)
        self.assertNotIn('applicationProxyWS', plain['src/main/resources/applicationContext.xml'][1])
        self.assertNotIn('wsEbsConsultaClavesWS', plain[base + 'util/PropertiesExterno.java'][1])
        self.assertIn('wsEbsConsultaClavesWSUrl', used[base + 'util/PropertiesExterno.java'][1])
        self.assertIn('ws.ebsConsultaClavesWS.url', used['README.MD'][1])
        self.assertNotIn('ws.ebsConsultaClavesWS', plain['README.MD'][1])

    def test_no_unused_classes_config_template_or_sonar_exclusions(self):
        for spec in (self.spec, self.decrypted_spec()):
            rendered = bm.render_project(bp.build(self.repo, spec, self.cfg), self.repo)
            paths = set(rendered)
            for name in ('UtilSFTP', 'PropertiesException', 'BaseException'):
                self.assertFalse([p for p in paths if p.endswith('/' + name + '.java')])
            self.assertEqual(len([p for p in paths if p.startswith('config/') and p.endswith('.properties')]), 1)
            self.assertFalse([p for p in paths if p.endswith('.j2')])
            self.assertNotIn('sonar.exclusions', rendered['pom.xml'][1])
            self.assertNotIn('sonar.coverage.exclusions', rendered['pom.xml'][1])
            self.assertNotIn('{{', rendered['README.MD'][1])

    def test_unused_class_is_reported(self):
        plan = bp.build(self.repo, self.spec, self.cfg)
        rendered = bm.render_project(plan, self.repo)
        rendered['src/main/java/pe/com/claro/shell/example/util/Orphan.java'] = ('x', 'class Orphan {}')
        with self.assertRaises(ValueError):
            bm.check_quality(rendered, plan, plan['batch'])


class BatchStructureOnlyTests(BatchShellTests):
    def structure_spec(self):
        spec = copy.deepcopy(self.spec)
        ev = ['ea#synthetic transfer flow']
        spec['batch'] = {'version': 1, 'scope': 'structure-only', 'sourceBindings': spec['batch']['sourceBindings'],
                         'properties': [], 'connections': [], 'steps': [],
                         'omittedBehavior': [{'id': 'dbUpdate', 'description': 'Database update is not specified for this backend',
                                              'evidence': ev}],
                         'outcomes': {'generalFailure': 'idt3', 'evidence': ev}}
        spec['readiness'] = {'strictImplementationReady': False, 'functionalCodeGenerationReady': False,
                             'scaffoldImplementationReady': True, 'blockers': ['dbUpdate']}
        return spec

    def test_structure_only_renders_without_sftp_decrypt_or_simulated_success(self):
        plan = bp.build(self.repo, self.structure_spec(), self.cfg)
        rendered = bm.render_project(plan, self.repo)
        paths = set(rendered)
        for name in ('SFTPConnectionManager', 'SFTPException', 'BaseExceptionSFTP', 'WSException',
                     'EbsConsultaClavesWSService', 'EbsConsultaClavesWSServiceImpl'):
            self.assertFalse([p for p in paths if p.endswith('/' + name + '.java')], name)
        service = rendered['src/main/java/pe/com/claro/shell/example/service/ExampleServiceImpl.java'][1]
        self.assertIn('PENDIENTE', service)
        self.assertNotIn('idf0', service)
        self.assertIn('dbUpdate', rendered['README.MD'][1])
        self.assertNotIn('sonar.exclusions', rendered['pom.xml'][1])

    def test_structure_only_requires_omitted_behavior_and_honest_readiness(self):
        spec = self.structure_spec()
        spec['batch']['omittedBehavior'] = []
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)
        spec = self.structure_spec()
        spec['readiness']['functionalCodeGenerationReady'] = True
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)

    def test_structure_only_cannot_declare_steps(self):
        spec = self.structure_spec()
        spec['batch']['steps'] = self.spec['batch']['steps']
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)


class BatchPortsFlowTests(BatchShellTests):
    def flow_spec(self):
        spec = copy.deepcopy(self.spec)
        ev = ['ea#synthetic transfer flow']
        call = lambda i, port, method, args, policy, result=None: {
            'id': i, 'kind': 'call', 'port': port, 'method': method, 'args': args, 'onFailure': policy, 'evidence': ev,
            **({'result': result} if result else {})}
        spec['batch'] = {
            'version': 1, 'scope': 'ports-flow', 'sourceBindings': spec['batch']['sourceBindings'],
            'properties': [], 'connections': [], 'steps': [],
            'omittedBehavior': [{'id': 'dbAdapter', 'description': 'Database adapter is not specified', 'evidence': ev}],
            'dtos': [{'name': 'Job', 'evidence': ev, 'fields': [{'name': 'tries', 'type': 'Integer'}]}],
            'ports': [{'id': 'JobStore', 'kind': 'db', 'evidence': ev, 'methods': [
                {'name': 'pending', 'params': [], 'returns': 'List<Job>', 'evidence': ev},
                {'name': 'limit', 'params': [], 'returns': 'Integer', 'evidence': ev},
                {'name': 'retry', 'params': [{'name': 'job', 'type': 'Job'}], 'returns': 'void', 'evidence': ev},
                {'name': 'close', 'params': [{'name': 'job', 'type': 'Job'}], 'returns': 'void', 'evidence': ev}]}],
            'flow': [call('listPending', 'JobStore', 'pending', [], 'abort', 'jobs'),
                     call('readLimit', 'JobStore', 'limit', [], 'abort', 'max'),
                     {'id': 'eachJob', 'kind': 'for-each', 'list': 'jobs', 'item': 'job', 'evidence': ev, 'steps': [
                         {'id': 'withinLimit', 'kind': 'if', 'left': 'job.tries', 'op': '<', 'right': 'max', 'evidence': ev,
                          'then': [call('retryJob', 'JobStore', 'retry', ['job'], 'skip-item')],
                          'else': [call('closeJob', 'JobStore', 'close', ['job'], 'skip-item')]}]}],
            'outcomes': {'success': 'idf0', 'generalFailure': 'idt3', 'evidence': ev}}
        spec['readiness'] = {'strictImplementationReady': False, 'functionalCodeGenerationReady': False,
                             'scaffoldImplementationReady': True, 'blockers': ['dbAdapter']}
        return spec

    def test_ports_flow_renders_flow_adapters_and_path_tests_without_simulating_integrations(self):
        plan = bp.build(self.repo, self.flow_spec(), self.cfg)
        rendered = bm.render_project(plan, self.repo)
        base = 'src/main/java/pe/com/claro/shell/example/'
        service = rendered[base + 'service/ExampleServiceImpl.java'][1]
        self.assertIn('job.getTries().intValue() < max.intValue()', service)
        self.assertIn('jobStore.retry(job);', service)
        adapter = rendered[base + 'port/JobStoreImpl.java'][1]
        self.assertIn('OperacionNoImplementadaException', adapter)
        self.assertIn('@Repository', adapter)
        for name in ('dto/Job', 'port/JobStore', 'exception/OperacionNoImplementadaException'):
            self.assertIn(base + name + '.java', rendered)
        test = rendered['src/test/java/pe/com/claro/shell/example/service/ExampleServiceImplTest.java'][1]
        for method in ('run_ruta_withinLimitSi_debeRegistrarExito', 'run_ruta_withinLimitNo_debeRegistrarExito',
                       'run_falla_listPending_debeRegistrarFalloGeneral', 'run_falla_retryJob_debeContinuarConSiguiente'):
            self.assertIn(method, test)
        self.assertIn('times(2)', test)
        self.assertNotIn('Sftp', service)

    def test_ports_flow_rejects_unused_methods_abort_in_loop_and_unknown_types(self):
        spec = self.flow_spec()
        spec['batch']['ports'][0]['methods'].append({'name': 'extra', 'params': [], 'returns': 'void', 'evidence': ['ea#x']})
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)
        spec = self.flow_spec()
        spec['batch']['flow'][2]['steps'][0]['then'][0]['onFailure'] = 'abort'
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)
        spec = self.flow_spec()
        spec['batch']['ports'][0]['methods'][2]['params'][0]['type'] = 'Missing'
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)

    def test_ports_flow_requires_honest_readiness(self):
        spec = self.flow_spec()
        spec['readiness']['functionalCodeGenerationReady'] = True
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)

    def test_ports_flow_has_no_unused_classes(self):
        plan = bp.build(self.repo, self.flow_spec(), self.cfg)
        bm.check_quality(bm.render_project(plan, self.repo), plan, plan['batch'])

    def adapters_spec(self):
        spec = self.flow_spec()
        ev = ['ea#synthetic transfer flow']
        batch = spec['batch']
        batch['dtos'].append({'name': 'Cfg', 'evidence': ev, 'fields': [{'name': n, 'type': 'String'} for n in ('subject', 'to', 'cc', 'bcc', 'bodyFormat', 'body')]})
        batch['dtos'][0]['fields'].append({'name': 'label', 'type': 'String'})
        batch['ports'] += [
            {'id': 'Remote', 'kind': 'rest', 'evidence': ev, 'methods': [
                {'name': 'fetchCfg', 'params': [], 'returns': 'Cfg', 'evidence': ev},
                {'name': 'push', 'params': [{'name': 'job', 'type': 'Job'}], 'returns': 'void', 'evidence': ev}]},
            {'id': 'Mailer', 'kind': 'mail', 'evidence': ev, 'methods': [
                {'name': 'send', 'params': [{'name': 'cfg', 'type': 'Cfg'}, {'name': 'job', 'type': 'Job'}], 'returns': 'void', 'evidence': ev}]}]
        call = lambda i, port, method, args, policy, result=None: {
            'id': i, 'kind': 'call', 'port': port, 'method': method, 'args': args, 'onFailure': policy, 'evidence': ev,
            **({'result': result} if result else {})}
        batch['flow'] = [call('getCfg', 'Remote', 'fetchCfg', [], 'log', 'cfg')] + batch['flow']
        loop = next(s for s in batch['flow'] if s['kind'] == 'for-each')
        loop['steps'] += [call('pushJob', 'Remote', 'push', ['job'], 'skip-item'), call('mailJob', 'Mailer', 'send', ['cfg', 'job'], 'log')]
        batch['adapters'] = [
            {'port': 'JobStore', 'evidence': ev, 'methods': [
                {'name': 'pending', 'sql': 'SELECT TRIES, LABEL FROM JOBS WHERE STATE = 0', 'bind': [], 'result': 'list',
                 'columns': [{'column': 'TRIES', 'field': 'tries'}, {'column': 'LABEL', 'field': 'label'}], 'assumed': True, 'evidence': ev},
                {'name': 'limit', 'sql': 'SELECT MAX(N) FROM LIMITS', 'bind': [], 'result': 'scalar', 'columns': [], 'assumed': True, 'evidence': ev},
                {'name': 'retry', 'sql': 'UPDATE JOBS SET STATE = 1 WHERE LABEL = ?', 'bind': ['job.label'], 'result': 'none', 'columns': [], 'assumed': True, 'evidence': ev},
                {'name': 'close', 'sql': 'UPDATE JOBS SET STATE = 2 WHERE LABEL = ?', 'bind': ['job.label'], 'result': 'none', 'columns': [], 'assumed': True, 'evidence': ev}]},
            {'port': 'Remote', 'evidence': ev, 'methods': [
                {'name': 'fetchCfg', 'httpMethod': 'GET', 'path': '/api/v1/cfg', 'query': [{'name': 'status', 'value': '1'}], 'body': [], 'assumed': True, 'evidence': ev},
                {'name': 'push', 'httpMethod': 'POST', 'path': '/api/v1/jobs', 'query': [], 'body': [{'json': 'label', 'from': 'job.label'}], 'assumed': True, 'evidence': ev}]},
            {'port': 'Mailer', 'evidence': ev, 'methods': [
                {'name': 'send', 'placeholders': [{'token': '{label}', 'from': 'job.label'}], 'assumed': True, 'evidence': ev}]}]
        return spec

    def test_adapters_render_concrete_integrations_from_assumptions_and_keep_pom_baseline(self):
        plan = bp.build(self.repo, self.adapters_spec(), self.cfg)
        rendered = bm.render_project(plan, self.repo)
        base = 'src/main/java/pe/com/claro/shell/example/'
        db = rendered[base + 'port/JobStoreImpl.java'][1]
        self.assertIn('SELECT TRIES, LABEL FROM JOBS', db)
        self.assertNotIn('OperacionNoImplementada', db)
        self.assertIn('sentencia.setObject(1, job.getLabel());', db)
        rest = rendered[base + 'port/RemoteImpl.java'][1]
        self.assertIn('externalProperties.restRemoteUrl', rest)
        self.assertIn('"/api/v1/cfg" + "?status=1"', rest)
        mail = rendered[base + 'port/MailerImpl.java'][1]
        self.assertIn('{label}', mail)
        for path in (base + 'util/ConexionBd.java', base + 'util/RestClienteHttp.java',
                     'src/test/java/pe/com/claro/shell/example/port/JobStoreImplTest.java',
                     'src/test/java/pe/com/claro/shell/example/port/RemoteImplTest.java'):
            self.assertIn(path, rendered)
        self.assertNotIn('src/test/java/pe/com/claro/shell/example/port/MailerImplTest.java', rendered)
        props = rendered[base + 'util/PropertiesExterno.java'][1]
        for key in ('bd.url', 'bd.password', 'rest.remote.url', 'rest.remote.timeout.ms', 'mail.smtp.host', 'mail.from'):
            self.assertIn('${' + key + '}', props)
        pom = rendered['pom.xml'][1]
        for artifact in ('jackson-databind', 'httpclient', 'javax.mail'):
            self.assertIn(artifact, pom)
        self.assertIn('<artifactId>jsch</artifactId>', pom)
        self.assertNotIn('sonar.exclusions', pom)
        bm.check_quality(rendered, plan, plan['batch'])

    def test_adapters_without_assumed_flag_or_with_wrong_shape_are_rejected(self):
        spec = self.adapters_spec()
        spec['batch']['adapters'][0]['methods'][0]['assumed'] = False
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)
        spec = self.adapters_spec()
        spec['batch']['adapters'][0]['methods'][2]['bind'] = []
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)
        spec = self.adapters_spec()
        spec['batch']['adapters'][0]['methods'].pop()
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)

    def nested_spec(self):
        spec = self.flow_spec()
        ev = ['ea#synthetic transfer flow']
        batch = spec['batch']
        batch['dtos'].append({'name': 'Sub', 'evidence': ev, 'fields': [{'name': 'kind', 'type': 'Integer'}, {'name': 'ok', 'type': 'Boolean'}]})
        batch['dtos'][0]['fields'].append({'name': 'status', 'type': 'Integer'})
        batch['ports'].append({'id': 'Remote', 'kind': 'rest', 'evidence': ev, 'methods': [
            {'name': 'subs', 'params': [{'name': 'job', 'type': 'Job'}], 'returns': 'List<Sub>', 'evidence': ev},
            {'name': 'create', 'params': [{'name': 'sub', 'type': 'Sub'}], 'returns': 'Boolean', 'evidence': ev},
            {'name': 'mark', 'params': [{'name': 'sub', 'type': 'Sub'}], 'returns': 'void', 'evidence': ev}]})
        call = lambda i, port, method, args, policy, result=None: {
            'id': i, 'kind': 'call', 'port': port, 'method': method, 'args': args, 'onFailure': policy, 'evidence': ev,
            **({'result': result} if result else {})}
        batch['flow'] = [
            call('listPending', 'JobStore', 'pending', [], 'abort', 'jobs'),
            call('readLimit', 'JobStore', 'limit', [], 'abort', 'max'),
            {'id': 'anyJobs', 'kind': 'if', 'left': 'jobs', 'op': 'nonempty', 'evidence': ev, 'then': [
                {'id': 'eachJob', 'kind': 'for-each', 'list': 'jobs', 'item': 'job', 'evidence': ev, 'steps': [
                    {'id': 'eligible', 'kind': 'guard', 'evidence': ev, 'any': [
                        {'left': 'job.status', 'op': 'equals', 'right': 5}, {'left': 'job.status', 'op': 'equals', 'right': 6}]},
                    call('retryJob', 'JobStore', 'retry', ['job'], 'skip-item'),
                    call('closeJob', 'JobStore', 'close', ['job'], 'skip-item'),
                    call('listSubs', 'Remote', 'subs', ['job'], 'skip-item', 'subs'),
                    {'id': 'eachSub', 'kind': 'for-each', 'list': 'subs', 'item': 'sub', 'evidence': ev, 'steps': [
                        call('createSub', 'Remote', 'create', ['sub'], 'skip-item', 'created'),
                        {'id': 'wasCreated', 'kind': 'if', 'left': 'created', 'op': 'true', 'evidence': ev,
                         'then': [call('markSub', 'Remote', 'mark', ['sub'], 'skip-item')]}]}]}]}]
        batch['adapters'] = [
            {'port': 'Remote', 'evidence': ev, 'methods': [
                {'name': 'subs', 'httpMethod': 'GET', 'path': '/api/v1/subs', 'query': [], 'body': [], 'assumed': True, 'evidence': ev},
                {'name': 'create', 'httpMethod': 'POST', 'path': '/api/v1/subs', 'query': [], 'body': [{'json': 'kind', 'from': 'sub.kind'}],
                 'okStatus': [409], 'assumed': True, 'evidence': ev},
                {'name': 'mark', 'httpMethod': 'PATCH', 'path': '/api/v1/subs', 'query': [], 'body': [], 'assumed': True, 'evidence': ev}]}]
        return spec

    def test_nested_loops_guards_compound_conditions_and_boolean_rest(self):
        plan = bp.build(self.repo, self.nested_spec(), self.cfg)
        rendered = bm.render_project(plan, self.repo)
        base = 'src/main/java/pe/com/claro/shell/example/'
        service = rendered[base + 'service/ExampleServiceImpl.java'][1]
        self.assertIn('continue;', service)
        self.assertIn('||', service)
        self.assertIn('isEmpty()', service)
        self.assertIn('Boolean.TRUE.equals(created)', service)
        rest = rendered[base + 'port/RemoteImpl.java'][1]
        self.assertIn('ejecutarEstado', rest)
        self.assertIn('409', rest)
        test = rendered['src/test/java/pe/com/claro/shell/example/service/ExampleServiceImplTest.java'][1]
        self.assertIn('run_falla_listPending_debeRegistrarFalloGeneral', test)
        self.assertIn('times(4)', test)
        bm.check_quality(rendered, plan, plan['batch'])

    def test_nested_loops_beyond_depth_two_and_guard_outside_loop_are_rejected(self):
        spec = self.nested_spec()
        inner = spec['batch']['flow'][2]['then'][0]['steps'][4]
        inner['steps'].append({'id': 'deep', 'kind': 'for-each', 'list': 'subs', 'item': 'x', 'evidence': ['ea#x'], 'steps': []})
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)
        spec = self.nested_spec()
        spec['batch']['flow'].insert(0, {'id': 'g', 'kind': 'guard', 'left': 'jobs', 'op': 'nonempty', 'evidence': ['ea#x']})
        with self.assertRaises(Exception):
            bp.build(self.repo, spec, self.cfg)

    def test_adapters_generated_java_parses_as_java8(self):
        plan = bp.build(self.repo, self.adapters_spec(), self.cfg)
        rendered = bm.render_project(plan, self.repo)
        import shutil
        import subprocess
        import tempfile
        javac = shutil.which('javac')
        if not javac:
            self.skipTest('javac unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for path, (_, text) in rendered.items():
                if path.endswith('.java'):
                    target = Path(tmp) / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding='utf-8')
                    files.append(str(target))
            probe = Path(tmp) / 'Probe.java'
            probe.write_text('public class Probe {}', encoding='utf-8')
            # Syntax only: unresolved dependencies are expected; any 'error: ... expected' style parse failure is reported.
            out = subprocess.run([javac, '-proc:none', '-Xdiags:compact', '-d', tmp, *files], capture_output=True, text=True).stderr
            syntax = [l for l in out.splitlines() if 'error:' in l and any(w in l for w in ('expected', 'illegal', 'unclosed', 'not a statement', 'reached end'))]
            self.assertEqual([], syntax, out[:2000])


if __name__ == '__main__':
    unittest.main()
