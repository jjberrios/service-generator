"""Read-only checkout prerequisites; no installation, global config or secrets."""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def inspect(root=ROOT):
    checks = []
    def check(name, ok, detail, required=True):
        checks.append({'name': name, 'ok': bool(ok), 'required': required, 'detail': detail})
    check('python', sys.version_info >= (3, 10), 'Requires Python 3.10+; ' + sys.version.split()[0])
    available = importlib.util.find_spec('yaml') is not None
    check('pyyaml', available, 'PyYAML is required by the pipeline; no packages are installed here')
    yaml = None
    if available:
        import yaml
        check('yaml-accelerator', hasattr(yaml, 'CSafeLoader'),
              'CSafeLoader preferred; SafeLoader remains a supported fallback', required=False)
    config = root / 'opencode.jsonc'
    try:
        if config.is_symlink() or not config.resolve().is_relative_to(root.resolve()):
            raise ValueError('redirected project config')
        value = json.loads(config.read_text(encoding='utf-8-sig'))
        rules = value.get('permissions')
        valid = isinstance(rules, list) and bool(rules) and all(
            isinstance(rule, dict) and isinstance(rule.get('action'), str)
            and isinstance(rule.get('resource'), str) and rule.get('effect') in ('allow', 'ask', 'deny')
            for rule in rules)
        check('project-permissions', valid, 'Repository V2 ordered rules; JSON-only subset of JSONC')
    except (OSError, ValueError) as error:
        check('project-permissions', False, type(error).__name__ + ': missing or invalid repository configuration')
    if yaml is not None:
        agents = sorted((root / '.opencode/agents').glob('*.md'))
        valid = bool(agents)
        for agent in agents:
            try:
                if agent.is_symlink() or not agent.resolve().is_relative_to(root.resolve()):
                    raise ValueError('redirected agent definition')
                text = agent.read_text(encoding='utf-8-sig')
                if not text.startswith('---\n'):
                    raise ValueError('missing frontmatter')
                frontmatter = yaml.safe_load(text.split('---', 2)[1])
                valid = valid and isinstance(frontmatter, dict) and isinstance(frontmatter.get('permissions'), list)
            except (OSError, ValueError, yaml.YAMLError):
                valid = False
        check('agent-definitions', valid, f'{len(agents)} repository agent definitions; syntax/shape only')
    for executable in ('git', 'javac', 'java'):
        check(executable, shutil.which(executable) is not None,
              'Optional diagnostic only; not executed and not an execution authorization', required=False)
    batch_tests = root / '.opencode/skills/materialize-full-service/tests/test_batch_shell.py'
    try:
        if batch_tests.is_symlink() or not batch_tests.resolve().is_relative_to(root.resolve()):
            raise ValueError('redirected test module')
        tree = ast.parse(batch_tests.read_text(encoding='utf-8'))
        count = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_')
                    for cls in tree.body if isinstance(cls, ast.ClassDef) for node in cls.body)
        check('batch-scenario-inventory', count == 37, f'{count} source-declared scenarios; no tests executed', required=False)
    except (OSError, SyntaxError, ValueError):
        check('batch-scenario-inventory', False, 'Source inventory unavailable', required=False)
    return {'ok': all(row['ok'] for row in checks if row['required']), 'checks': checks,
            'effectivePermissions': 'not-inspected: global, ancestor and runtime policies can override project rules',
            'sideEffects': 'none: no installs, service generation, tests, Maven, network, database or deployment'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Machine-readable checks')
    args = parser.parse_args(argv)
    result = inspect()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for row in result['checks']:
            status = 'OK' if row['ok'] else ('ERROR' if row['required'] else 'OPTIONAL')
            print(f"{status}: {row['name']}: {row['detail']}")
        print(result['effectivePermissions'])
        print(result['sideEffects'])
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
