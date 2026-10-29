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
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='batch-shell-test-')
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.service = 'batch-example'
        self.ws = self.repo / '.factory/services' / self.service
        self.ws.mkdir(parents=True)
        self.arch_rel = 'archetypes/claro-java-8-shell/v1.0.0'
        self.arch = self.repo / self.arch_rel
        shutil.copytree(REPO / self.arch_rel, self.arch)
        arch = yaml.safe_load((self.arch / 'archetype.yml').read_bytes())
        arch['identity']['generationEnabled'] = True  # fixture-only authorization, never the real archetype
        dump(self.arch / 'archetype.yml', arch)
        source = self.repo / 'input/sparx/flow.htm'
        source.parent.mkdir(parents=True)
        source.write_text('<html>SYNTHETIC transfer flow, abort on failure, empty list succeeds</html>', encoding='utf-8')
        evidence = ['ea#flow']
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
        dump(self.ws / 'sparx-target-authority.yml', {'target': {'name': self.service}, 'selection': {'status': 'resolved', 'authoritativeBranchRootId': '0.1'}})
        dump(self.ws / 'full-planning-input.yml', self.cfg)
        self.review()
        self.authorize()

    def review(self):
        hashes = {name: sha(self.ws / filename) for name, filename in (('serviceSpecSha256', 'service-spec.yml'),
                  ('sparxSpecSha256', 'sparx-spec.yml'), ('authoritySha256', 'sparx-target-authority.yml'))}
        hashes['archetypeSha256'] = sha(self.arch / 'archetype.yml')
        dump(self.ws / 'consistency/batch-review.yml', {'reviewed': True, 'reviewedBy': 'test-semantic-review', 'reviewedAgainst': hashes, 'findings': []})

    def authorize(self):
        gate.authorize(self.ws, self.repo, self.service, 'fixture-human', 'Fixture authorization only; never a real service decision.')

    def plan(self):
        return bp.write_plan(self.repo, yaml, self.ws / 'full-planning-input.yml')

    def test_profile_and_deterministic_plan(self):
        self.assertEqual(profiles.resolve(yaml.safe_load((self.arch / 'archetype.yml').read_bytes())), bm.PROFILE)
        self.plan()
        first = (self.ws / 'implementation-plan.yml').read_bytes()
        self.plan()
        self.assertEqual(first, (self.ws / 'implementation-plan.yml').read_bytes())
        self.assertEqual(len(yaml.safe_load(first)['files']['generate']), 19)

    def test_cli_dispatch_in_workspace_sandbox_and_parameter_resolver(self):
        import workspace
        (self.repo / '.opencode').mkdir()
        ws = workspace.Workspace(self.repo, self.service)
        for name in ('build_implementation_plan.py', 'resolve_generation_parameters.py'):
            run = workspace.run_script(ws, REPO / '.opencode/skills/plan-service-implementation/scripts' / name,
                                       ['--mode', 'full', '--planning-input', '.factory/full-planning-input.yml'])
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(yaml.safe_load((self.ws / 'implementation-plan.yml').read_bytes())['plan']['profile'], bm.PROFILE)

    def test_listing_by_filename_empty_abort_and_explicit_disconnect(self):
        spec = copy.deepcopy(self.spec)
        spec['batch']['steps'][1].update(kind='list-name', emptyPolicy='abort')
        spec['batch']['steps'].append({'id': 'close', 'kind': 'disconnect', 'connection': 'Source', 'evidence': ['ea#flow']})
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
        config = (out / 'config/Example.properties.j2').read_text()
        self.assertEqual(config.count('\nftp.test.host='), 1)
        self.assertNotIn('System.exit', (out / 'src/main/java/pe/com/claro/shell/example/ExampleMain.java').read_text())

    def test_gate_requires_review_authorization_and_live_sources(self):
        (self.ws / 'consistency/authorization.yml').unlink()
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
        with self.assertRaises(fm.MaterializationError):
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


if __name__ == '__main__':
    unittest.main()
