"""Static V2 rule regression, not a claim about effective global/runtime policy."""
import json
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def matches(pattern, value):
    # V2 whole-value * and ?, including /; do not treat [] as glob syntax.
    expression = re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.')
    return re.fullmatch(expression, value.replace('\\', '/'), re.IGNORECASE) is not None


def effect(rules, action, resource):
    result = 'ask'
    for rule in rules:
        target = rule['resource']
        resources = (target, target[:-2]) if action == 'shell' and target.endswith(' *') else (target,)
        if matches(rule['action'], action) and any(matches(pattern, resource) for pattern in resources):
            result = rule['effect']
    return result


class ProjectPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = json.loads((ROOT / 'opencode.jsonc').read_text())['permissions']
        cls.agents = {path.stem: yaml.safe_load(path.read_text(encoding='utf-8').split('---', 2)[1])['permissions']
                      for path in (ROOT / '.opencode/agents').glob('*.md')}

    def rules(self, name):
        return [{'action': '*', 'resource': '*', 'effect': 'allow'}] + self.project + self.agents[name]

    def test_non_sensitive_reads_searches_work_for_every_agent(self):
        self.assertEqual(7, len(self.agents))
        for agent in self.agents:
            for action, resource in (('read', 'input/contracts/service.yml'),
                                     ('read', '.factory/services/selected/sparx-spec.yml'),
                                     ('read', 'archetypes/selected/v1/archetype.yml'),
                                     ('glob', 'input/sparx/**/*.htm'), ('grep', 'selected-operation')):
                with self.subTest(agent=agent, action=action):
                    self.assertEqual('allow', effect(self.rules(agent), action, resource))

    def test_reference_and_sensitive_content_remain_blocked(self):
        for agent in self.agents:
            rules = self.rules(agent)
            self.assertEqual('allow' if agent == 'archetype-extractor' else 'deny',
                             effect(rules, 'read', 'input/reference/selected/pom.xml'), agent)
            for path in ('.env', 'nested/.env.local', 'nested/secret.pem', 'keys/auth.json',
                         'config/credentials.json', 'certificates/client.crt',
                         'output/selected/src/main/resources/application-local.properties'):
                with self.subTest(agent=agent, path=path):
                    self.assertEqual('deny', effect(rules, 'read', path))

    def test_orchestrator_cannot_edit_java_or_record_manual_reviews(self):
        rules = self.rules('service-generator')
        for path in ('output/service/src/main/java/Manual.java',
                     '.factory/services/service/consistency/decision-reviews/review.json',
                     '.factory/services/service/consistency/authorization.yml'):
            self.assertEqual('deny', effect(rules, 'edit', path))
        for command in ('python -B .opencode/skills/service-workspace/scripts/review_cli.py review service',
                        'py -3 -B .opencode/skills/service-workspace/scripts/workspace_cli.py gate-authorize service',
                        'mvn test', 'kubectl apply file.yml', 'python -c print(1)'):
            self.assertNotEqual('allow', effect(rules, 'shell', command), command)

    def test_allowlisted_pipeline_commands_have_portable_equivalents(self):
        for agent, rules in self.agents.items():
            for rule in rules:
                if rule['action'] == 'shell' and rule['effect'] == 'allow' and rule['resource'].startswith('python .opencode/skills/'):
                    for prefix in ('python -B ', 'py -3 -B '):
                        translated = prefix + rule['resource'][len('python '):]
                        self.assertIn({'action': 'shell', 'resource': translated, 'effect': 'allow'}, rules, agent)

    def test_no_blanket_python_or_shell_allow(self):
        for agent in self.agents:
            for rule in self.rules(agent):
                if rule['action'] == 'shell' and rule['effect'] == 'allow':
                    self.assertNotIn(rule['resource'], ('*', 'python *', 'python -B *', 'py *'), agent)


if __name__ == '__main__':
    unittest.main()
