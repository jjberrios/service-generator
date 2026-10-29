"""Read-only relational extraction checks; no reference configuration is read."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import yaml


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        key = loader.construct_object(key, deep=deep)
        if key in result:
            raise ValueError('duplicate YAML key: ' + str(key))
        result[key] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def protected(path):
    return path.name.lower().startswith('application') and path.name.lower().endswith('.properties')


def validate(target):
    target = Path(target)
    manifest = yaml.load((target / 'archetype.yml').read_text(encoding='utf-8'), Loader=UniqueLoader)
    issues = []
    legacy = manifest.get('archetype', {}).get('id') == 'claro-spring-ms'
    decision_text = (target / 'decisions.md').read_text(encoding='utf-8')
    inventory = manifest.get('templateInventory')
    if legacy and inventory is None:
        inventory = [dict(item, path=item['path'].removeprefix('template/'),
                          evidence=[item['evidence']],
                          decisionRefs=[item['approved_decision']] if item.get('approved_decision') else [])
                     for item in manifest.get('template_inventory', [])]
    if not isinstance(inventory, list):
        return {'status': 'unsupported-schema', 'issues': ['templateInventory is not declared']}
    declared = [item['path'] for item in inventory]
    for name in declared:
        if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:
            issues.append('unsafe inventory path')
    if len(set(declared)) != len(declared):
        issues.append('duplicate template inventory path')
    files = {}
    for path in (target / 'template').rglob('*'):
        if path.is_symlink():
            issues.append('symlink in template: ' + path.relative_to(target).as_posix())
        elif path.is_file():
            files[path.relative_to(target / 'template').as_posix()] = path
    if set(files) != set(declared):
        issues.append('inventory mismatch: ' + repr(sorted(set(files) ^ set(declared))))
    usage = {}
    for name, path in files.items():
        if protected(path):
            if not legacy:
                issues.append('protected configuration in template: ' + name)
            continue
        if any(parent.is_symlink() for parent in path.parents):
            continue
        pattern = r'__([A-Z][A-Z0-9_]*?)__' if legacy else r'@@([A-Z][A-Z0-9_]*)@@'
        for token in set(re.findall(pattern, name + '\n' + path.read_text(encoding='utf-8'))):
            if legacy and name in {'mvnw', 'mvnw.cmd'} and token in {'MVNW_CMD', 'MVNW_ERROR', 'MVNW_ARG0_NAME'}:
                continue  # Maven Wrapper's own identifiers, not archetype parameters.
            usage.setdefault(token, set()).add(name)
    parameters = manifest.get('parameters', {})
    if legacy:
        parameters = {item['token'].strip('_'): {'affectedFiles': [p.removeprefix('template/') for p in item['affected_paths']]}
                      for item in parameters if item.get('token')}
    if set(usage) != set(parameters):
        issues.append('parameter inventory mismatch: ' + repr(sorted(set(usage) ^ set(parameters))))
    for name, definition in parameters.items():
        expected = set(definition.get('affectedFiles', []))
        if legacy:
            expected = {f for f, p in files.items() if not protected(p) and
                        any(f == e or f.startswith(e + '/') for e in expected)}
        if usage.get(name, set()) != expected:
            issues.append('affectedFiles mismatch: ' + name)
    decisions = set(manifest.get('provenance', {}).get('approvedDecisionRefs', []))
    evidence = manifest.get('evidence', {}).get('entries', {})
    if legacy:
        decisions = set(re.findall(r'\bD-\d{3}\b', decision_text))
        evidence = manifest.get('evidence', {})
    for decision in decisions:
        if decision not in decision_text:
            issues.append('undocumented decision: ' + decision)
    for item in inventory:
        for decision in item.get('decisionRefs', []):
            if decision not in decisions:
                issues.append('unregistered approved decision: ' + decision)
        for entry in item.get('evidence', []):
            if entry not in evidence:
                issues.append('unknown evidence: ' + entry)
    generation = manifest.get('generation', {})
    for category in ('utilities', 'configuration'):
        for item in generation.get(category, {}).get('items', []):
            path = item.get('template') or item.get('path')
            if path and path not in files:
                issues.append('missing ' + category + ' template: ' + path)
    pom_inventory = 'not-declared'
    pom = files.get('pom.xml')
    build = manifest.get('build', {})
    if pom and not pom.is_symlink() and not any(p.is_symlink() for p in pom.parents):
        document = ET.fromstring(pom.read_bytes())
        ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
        for section, xpath in [('dependencies', 'm:dependencies/m:dependency'),
                               ('plugins', 'm:build/m:plugins/m:plugin')]:
            if section not in build:
                continue
            pom_inventory = 'checked-against-declared-build-inventory'
            observed = document.findall(xpath, ns)
            declared_items = build[section]
            if [e.findtext('m:artifactId', namespaces=ns) for e in observed] != [e['artifactId'] for e in declared_items]:
                issues.append('POM ' + section + ' inventory mismatch')
                continue
            for element, item in zip(observed, declared_items):
                for field in ('groupId', 'artifactId', 'version', 'scope', 'optional', 'type', 'classifier'):
                    actual = element.findtext('m:' + field, namespaces=ns)
                    expected = item.get(field)
                    if isinstance(expected, bool):
                        expected = str(expected).lower()
                    if expected is not None:
                        expected = str(expected)
                    if actual != expected:
                        issues.append('POM ' + section + ' field mismatch: ' + item['artifactId'] + '.' + field)
    return {'status': 'failed' if issues else 'passed', 'templates': len(files),
            'parameters': len(parameters), 'issues': sorted(set(issues)),
            'scope': 'inventory-parameters-decision-evidence-relations',
            'pomInventory': pom_inventory, 'pomFidelity': 'requires-profile-validator', 'runtime': 'not-verified'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archetype')
    args = parser.parse_args()
    result = validate(args.archetype)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
