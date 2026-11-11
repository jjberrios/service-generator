"""Offline Java fixtures; no Maven, sockets or execution of a generated batch."""
import os
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parents[3] / '.opencode/skills/plan-service-implementation/scripts'))
import batch_payment_sync_java as java
import batch_payment_sync_tests as tests


class PaymentHttpTests(unittest.TestCase):
    def plan(self):
        return {'templateParameters': {'BASE_PACKAGE': 'fixture.payment', 'SERVICE_INTERFACE': 'PaymentService'}}

    def test_transport_is_offline_safe_and_java8(self):
        text = java.http_client(self.plan())
        self.assertIn('status != 200', text)
        self.assertIn('disableAutomaticRetries()', text)
        self.assertIn('disableRedirectHandling()', text)
        self.assertIn('getUserInfo() != null', text)
        self.assertIn('try (CloseableHttpClient', text)
        self.assertNotIn('TrustAll', text)
        self.assertNotIn('TODO', text)

    @unittest.skipUnless(os.environ.get('PAYMENT_SYNC_LOCAL_JAVAC') == '1', 'explicit local javac fixture opt-in')
    def test_generated_transport_with_local_javac_and_junit4_no_network(self):
        cache = Path.home() / '.m2/repository'
        coordinates = [
            ('com/fasterxml/jackson/core/jackson-databind', '2.18.5'),
            ('com/fasterxml/jackson/core/jackson-core', '2.18.5'),
            ('com/fasterxml/jackson/core/jackson-annotations', '2.18.5'),
            ('org/apache/httpcomponents/httpclient', '4.5.14'),
            ('org/apache/httpcomponents/httpcore', '4.4.16'),
            ('org/springframework/spring-context', '5.1.6.RELEASE'),
            ('commons-logging/commons-logging', '1.1.1'), ('commons-codec/commons-codec', '1.15'),
            ('junit/junit', '4.12'), ('org/hamcrest/hamcrest-core', '1.3'),
            ('org/mockito/mockito-core', '2.15.0'), ('net/bytebuddy/byte-buddy', '1.14.10'),
            ('net/bytebuddy/byte-buddy-agent', '1.14.10'), ('org/objenesis/objenesis', '2.6')]
        jars = [cache / path / version / (path.split('/')[-1] + '-' + version + '.jar') for path, version in coordinates]
        self.assertTrue(all(p.is_file() for p in jars), 'Required local fixture jars must already exist; no downloads')
        self.assertTrue(shutil.which('javac') and shutil.which('java'))
        preferred = Path.home() / 'AppData/Local/Temp/opencode'
        with tempfile.TemporaryDirectory(prefix='payment-http-', dir=preferred if preferred.is_dir() else None) as directory:
            root = Path(directory)
            sources = []
            for name, text in [('PaymentHttpClient', java.http_client(self.plan())),
                               ('PaymentHttpClientTest', tests.http_test(self.plan()))]:
                path = root / (name + '.java')
                path.write_text(text, encoding='utf-8', newline='\n')
                sources.append(str(path))
            cp = os.pathsep.join(str(p) for p in jars)
            compilation = subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-cp', cp, '-d', str(root), *sources],
                                         capture_output=True, text=True, timeout=90)
            self.assertEqual(compilation.returncode, 0, compilation.stdout + compilation.stderr)
            execution = subprocess.run(['java', '-cp', str(root) + os.pathsep + cp, 'org.junit.runner.JUnitCore',
                                        'fixture.payment.client.PaymentHttpClientTest'], capture_output=True, text=True, timeout=90)
            self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
            self.assertIn('OK (5 tests)', execution.stdout)

    @unittest.skipUnless(os.environ.get('PAYMENT_SYNC_TEST_PLAN'), 'explicit local typed-model fixture opt-in')
    def test_closed_model_rejects_unreviewed_changes(self):
        from batch_payment_sync_model import validate
        batch = yaml.safe_load(Path(os.environ['PAYMENT_SYNC_TEST_PLAN']).read_bytes())['batch']
        self.assertEqual(validate(batch), batch)
        mutations = [
            lambda b: b['decisions'].pop(),
            lambda b: b['properties'].pop(),
            lambda b: b['steps'].pop(),
            lambda b: b['model'].update(scaffoldFallback=True),
            lambda b: b['model'].update(omittedBehavior=['authentication']),
            lambda b: b['model']['calls'][0].update(method='GET'),
            lambda b: b['model'].update(arbitraryJava='System.exit(0);'),
            lambda b: b['sourceBindings'][0].update(path='input/reference/forbidden'),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                changed = copy.deepcopy(batch)
                mutate(changed)
                with self.assertRaises(ValueError):
                    validate(changed)

    @unittest.skipUnless(os.environ.get('PAYMENT_SYNC_TEST_PLAN'), 'explicit local typed-model fixture opt-in')
    def test_complete_service_with_local_javac_and_junit4_no_network(self):
        plan = yaml.safe_load(Path(os.environ['PAYMENT_SYNC_TEST_PLAN']).read_bytes())
        from batch_shell_materializer import render_project
        repo = SCRIPTS.parents[3]
        rendered = render_project(plan, repo)
        cache = Path.home() / '.m2/repository'
        coordinates = [('com/fasterxml/jackson/core/jackson-databind', '2.18.5'),
            ('com/fasterxml/jackson/core/jackson-core', '2.18.5'), ('com/fasterxml/jackson/core/jackson-annotations', '2.18.5'),
            ('org/apache/httpcomponents/httpclient', '4.5.14'), ('org/apache/httpcomponents/httpcore', '4.4.16'),
            ('org/springframework/spring-context', '5.1.6.RELEASE'), ('org/springframework/spring-beans', '5.1.6.RELEASE'),
            ('org/springframework/spring-core', '5.1.6.RELEASE'),
            ('commons-logging/commons-logging', '1.1.1'), ('commons-codec/commons-codec', '1.15'),
            ('log4j/log4j', '1.2.17'), ('junit/junit', '4.12'), ('org/hamcrest/hamcrest-core', '1.3'),
            ('org/mockito/mockito-core', '2.15.0'), ('net/bytebuddy/byte-buddy', '1.14.10'),
            ('net/bytebuddy/byte-buddy-agent', '1.14.10'), ('org/objenesis/objenesis', '2.6')]
        jars = [cache / path / version / (path.split('/')[-1] + '-' + version + '.jar') for path, version in coordinates]
        self.assertTrue(all(p.is_file() for p in jars), 'local jars required; never download')
        preferred = Path.home() / 'AppData/Local/Temp/opencode'
        with tempfile.TemporaryDirectory(prefix='payment-full-', dir=preferred if preferred.is_dir() else None) as directory:
            root = Path(directory)
            sources = []
            for name, (_, text) in rendered.items():
                # The real Spring main is compiled, NEVER started.
                if name.endswith('.java'):
                    actual = repo / plan['service']['outputDirectory'] / name
                    if actual.is_file():
                        self.assertEqual(actual.read_bytes(), text.encode('utf-8'),
                                         'Local execution evidence requires exact generated Java bytes')
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding='utf-8', newline='\n')
                    sources.append(str(path))
            cp = os.pathsep.join(map(str, jars))
            compilation = subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-cp', cp,
                '-d', str(root / 'classes'), *sources], capture_output=True, text=True, timeout=90)
            self.assertEqual(compilation.returncode, 0, compilation.stdout + compilation.stderr)
            package = plan['templateParameters']['BASE_PACKAGE']
            service = plan['templateParameters']['SERVICE_INTERFACE']
            execution = subprocess.run(['java', '-cp', str(root / 'classes') + os.pathsep + cp,
                'org.junit.runner.JUnitCore', package + '.client.PaymentHttpClientTest',
                package + '.service.' + service + 'ImplTest'], capture_output=True, text=True, timeout=90)
            self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
            self.assertIn('OK (25 tests)', execution.stdout)


if __name__ == '__main__':
    unittest.main()
