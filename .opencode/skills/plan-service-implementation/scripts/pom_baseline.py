"""Mandatory Maven baseline: render, parse and compare POMs (generic; no service-specific knowledge).

The approved reference project's pom.xml is the mandatory Maven baseline of an archetype
(archetype.yml#/maven/reference_pom_baseline). The archetype template is that POM with a small,
declared set of token substitutions. A generated POM is the template rendered with the target's
values plus justified target-specific additions; baseline items may never be pruned or altered.

Functions are pure/read-only. Nothing here reads the reference project: the reference model is
reconstructed from the archetype template by substituting the recorded reference literals.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

NS = '{http://maven.apache.org/POM/4.0.0}'
SECTIONS = ('coordinates', 'parent', 'properties', 'repositories', 'dependencies', 'plugins', 'profiles', 'buildOther')


class BaselineError(Exception):
    pass


def _strip(tag: str) -> str:
    return tag.replace(NS, '')


def _norm(value: str | None) -> str | None:
    return None if value is None else re.sub(r'\s+', ' ', value).strip()


def _obj(node: ET.Element) -> Any:
    children = list(node)
    if not children:
        return _norm(node.text) or ''
    result: dict[str, Any] = {}
    for child in children:
        key, value = _strip(child.tag), _obj(child)
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result


def _text(node: ET.Element, path: str) -> str | None:
    child = node.find(path)
    return None if child is None or child.text is None else _norm(child.text)


def parse_pom(text: str | bytes) -> dict[str, Any]:
    root = ET.fromstring(text)
    model: dict[str, Any] = {
        'coordinates': {k: _text(root, f'{NS}{k}') for k in ('modelVersion', 'groupId', 'artifactId', 'version', 'packaging', 'name')},
        'parent': {k: _text(root, f'{NS}parent/{NS}{k}') for k in ('groupId', 'artifactId', 'version', 'relativePath')},
    }
    props = root.find(f'{NS}properties')
    model['properties'] = {_strip(p.tag): _norm(p.text) for p in props} if props is not None else {}
    model['repositories'] = {_text(r, f'{NS}id'): _obj(r) for r in root.findall(f'{NS}repositories/{NS}repository')}
    model['dependencies'] = {f"{_text(d, f'{NS}groupId')}:{_text(d, f'{NS}artifactId')}": _obj(d)
                             for d in root.findall(f'{NS}dependencies/{NS}dependency')}
    model['plugins'] = {f"{_text(p, f'{NS}groupId') or 'org.apache.maven.plugins'}:{_text(p, f'{NS}artifactId')}":
                        {k: v for k, v in _obj(p).items() if k != 'groupId' or v != 'org.apache.maven.plugins'}
                        for p in root.findall(f'{NS}build/{NS}plugins/{NS}plugin')}
    model['profiles'] = {_text(p, f'{NS}id'): _obj(p) for p in root.findall(f'{NS}profiles/{NS}profile')}
    build = root.find(f'{NS}build')
    model['buildOther'] = {_strip(c.tag): _obj(c) for c in build if _strip(c.tag) != 'plugins'} if build is not None else {}
    return model


def baseline_config(archetype: dict) -> dict:
    config = ((archetype.get('maven') or {}).get('reference_pom_baseline')) or {}
    if not config.get('mandatory') or not config.get('substitutions'):
        raise BaselineError('archetype.yml#/maven/reference_pom_baseline is missing or not mandatory (decision D-012).')
    return config


def values_for(config: dict, params: dict[str, Any]) -> dict[str, str]:
    values = {}
    for sub in config['substitutions']:
        if params.get(sub['parameter']) in (None, ''):
            raise BaselineError(f"Maven baseline parameter '{sub['parameter']}' has no value.")
        values[sub['token']] = str(params[sub['parameter']])
    return values


def _replace_tokens(text: str, values: dict[str, str]) -> str:
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def reference_text(template_text: str, config: dict) -> str:
    """Reconstruct the reference POM text (without reading the reference) from the template."""
    return _replace_tokens(template_text, {s['token']: s['reference_value'] for s in config['substitutions']})


def build_template(reference: str, config: dict) -> str:
    """Archetype maintenance: derive the template from the reference POM using the declared snippets."""
    text = reference
    for sub in config['substitutions']:
        for snippet in sub['reference_snippets']:
            if text.count(snippet) != sub.get('occurrences_per_snippet', 1):
                raise BaselineError(f"Substitution snippet for {sub['token']} occurs {text.count(snippet)} times: {snippet!r}")
            text = text.replace(snippet, snippet.replace(sub['reference_value'], sub['token']))
    return text


def _addition_xml(addition: dict, eol: str) -> str:
    lines = ['\t\t<dependency>', f"\t\t\t<groupId>{addition['groupId']}</groupId>", f"\t\t\t<artifactId>{addition['artifactId']}</artifactId>"]
    if addition.get('version'):
        lines.append(f"\t\t\t<version>{addition['version']}</version>")
    if addition.get('scope'):
        lines.append(f"\t\t\t<scope>{addition['scope']}</scope>")
    lines.append('\t\t</dependency>')
    return eol.join(lines)


def insert_additions(text: str, additions: list[dict] | None) -> str:
    """Justified target-specific dependencies appended inside <dependencies>; baseline content is never removed or reordered."""
    additions = additions or []
    if additions:
        eol = '\r\n' if '\r\n' in text else '\n'
        baseline = parse_pom(text)
        for add in additions:
            key = f"{add['groupId']}:{add['artifactId']}"
            if key in baseline['dependencies']:
                raise BaselineError(f'Addition {key} duplicates a baseline dependency.')
            if not add.get('justification'):
                raise BaselineError(f'Addition {key} has no justification.')
        block = eol.join(['\t\t<!-- TARGET-SPECIFIC ADDITIONS (justified in the implementation plan); the baseline above is never pruned -->']
                         + [_addition_xml(a, eol) for a in additions]) + eol
        match = None
        for match in re.finditer(r'[ \t]*</dependencies>', text):
            break
        if match is None:
            raise BaselineError('Template has no dependencies section.')
        text = text[:match.start()] + block + text[match.start():]
    return text


def render_pom(template_text: str, config: dict, params: dict[str, Any], additions: list[dict] | None = None) -> str:
    """Template + target values + justified additions. Baseline content is never removed or reordered."""
    text = _replace_tokens(template_text, values_for(config, params))
    if re.search(r'__[A-Z0-9_]+__', text):
        raise BaselineError('Rendered POM still contains an unresolved placeholder.')
    return insert_additions(text, additions)


def compare(reference_model: dict, template_rendered_model: dict, generated_model: dict, additions: list[dict] | None = None,
            exclusions: dict[str, list[str]] | None = None) -> dict:
    """Account for every reference item. Statuses: inherited, parameterized, target-specific-addition,
    intentionally-excluded; failures: missing, modified, unjustified-addition."""
    exclusions = exclusions or {}
    additions = additions or []
    justified = {f"{a['groupId']}:{a['artifactId']}": a for a in additions if a.get('justification')}
    rows: list[dict] = []
    for section in SECTIONS:
        ref, expected, gen = reference_model[section], template_rendered_model[section], generated_model[section]
        for key in sorted(ref):
            if key not in gen:
                status = 'intentionally-excluded' if key in exclusions.get(section, []) else 'missing'
            elif gen[key] != expected[key]:
                status = 'modified'
            elif gen[key] == ref[key]:
                status = 'inherited'
            else:
                status = 'parameterized'
            rows.append({'category': section, 'item': key, 'reference': ref[key], 'generated': gen.get(key), 'status': status})
        for key in sorted(set(gen) - set(ref)):
            status = 'target-specific-addition' if section == 'dependencies' and key in justified else 'unjustified-addition'
            rows.append({'category': section, 'item': key, 'reference': None, 'generated': gen[key], 'status': status,
                         **({'justification': justified[key]['justification']} if status == 'target-specific-addition' else {})})
    counts: dict[str, int] = {}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    failures = [r for r in rows if r['status'] in ('missing', 'modified', 'unjustified-addition')]
    return {'rows': rows, 'counts': dict(sorted(counts.items())), 'failures': failures,
            'unintentionallyMissingBaselineItems': [r['item'] for r in failures if r['status'] == 'missing']}
