"""Reference Checkstyle gate (archetype decision D-014).

The approved reference checkstyle.xml is the authority for generated production AND test Java. This module only
EXECUTES the project's configured Checkstyle (through the generated project's own Maven wrapper) and interprets its
result; it never re-implements rules and never substitutes a Java parser for Checkstyle.

Statuses: passed (executed, 0 violations), failed (executed, violations > 0), unverified (could not be executed,
for example unavailable plugin/repository). Only `passed` may let generation be reported as complete.
"""
from pathlib import Path
import os
import re
import subprocess
import xml.etree.ElementTree as ET

PASSED = 'passed'
FAILED = 'failed'
UNVERIFIED = 'unverified'
VIOLATIONS_PATTERN = re.compile(r'You have (\d+) Checkstyle violations?')
REQUIRED_SOURCES = ('src/main/java', 'src/test/java')


def parse_result_xml(result_xml: Path) -> dict:
    """Count violations per Checkstyle rule and per source set from target/checkstyle-result.xml."""
    by_rule: dict = {}
    by_source = {'main': 0, 'test': 0}
    for file_node in ET.parse(result_xml).getroot().iter('file'):
        name = file_node.get('name', '').replace('\\', '/')
        for error in file_node.iter('error'):
            rule = (error.get('source') or '').rsplit('.', 1)[-1].replace('Check', '')
            by_rule[rule] = by_rule.get(rule, 0) + 1
            by_source['test' if '/src/test/' in name else 'main'] += 1
    return {'byRule': dict(sorted(by_rule.items())), 'bySource': by_source}


def interpret(returncode: int, output: str, result_xml: Path | None = None) -> dict:
    """Pure interpretation of one Maven Checkstyle execution (unit-testable without Maven)."""
    match = VIOLATIONS_PATTERN.search(output or '')
    if match is None:
        return {'status': UNVERIFIED, 'violations': None, 'reason': 'Checkstyle did not report a violation count (plugin, dependency or repository unavailable, or the build stopped earlier).'}
    count = int(match.group(1))
    detail = {}
    if result_xml is not None and result_xml.is_file():
        detail = parse_result_xml(result_xml)
    if count == 0 and returncode == 0:
        return {'status': PASSED, 'violations': 0, **detail}
    return {'status': FAILED, 'violations': count, **detail}


def run_checkstyle(project: Path, offline_first: bool = True, timeout: int = 600) -> dict:
    """Run the narrowest configured gate: the project's own `validate` phase (maven-checkstyle-plugin check)."""
    wrapper = 'mvnw.cmd' if os.name == 'nt' else './mvnw'
    attempts = [['-o'], []] if offline_first else [[]]
    last = {'status': UNVERIFIED, 'violations': None, 'reason': 'Checkstyle was not executed.'}
    for extra in attempts:
        command = [str(project / wrapper) if os.name == 'nt' else wrapper, *extra, '-s', 'settings.xml', 'validate']
        try:
            done = subprocess.run(command, cwd=project, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            last = {'status': UNVERIFIED, 'violations': None, 'reason': f'Maven could not be started: {exc}'}
            continue
        text = (done.stdout or '') + (done.stderr or '')
        last = interpret(done.returncode, text, project / 'target' / 'checkstyle-result.xml')
        last['command'] = ' '.join(command[1:]) if os.name == 'nt' else ' '.join(command)
        if last['status'] != UNVERIFIED:
            break
    return last


def final_static_status(static_checks_pass: bool, checkstyle: dict) -> str:
    """Final generation validation: Java syntax/structure alone can never produce `passed`."""
    if checkstyle.get('status') == FAILED:
        return 'failed'
    if not static_checks_pass:
        return 'failed'
    if checkstyle.get('status') != PASSED:
        return 'checkstyle-unverified'
    return 'passed'


def plan_gate_complete(plan: dict) -> list[str]:
    """Return defects of a plan's qualityGates.checkstyle section (empty list means the gate is correctly planned)."""
    gate = ((plan.get('qualityGates') or {}).get('checkstyle')) or {}
    defects = []
    if gate.get('mandatory') is not True or gate.get('decision') != 'D-014':
        defects.append('Checkstyle gate is not planned as mandatory (D-014)')
    if tuple(gate.get('sources') or ()) != REQUIRED_SOURCES or gate.get('includeTestSourceDirectory') is not True:
        defects.append('Checkstyle gate must cover src/main/java and src/test/java')
    applies = gate.get('appliesTo') or {}
    if not applies.get('mainJavaFiles') or not applies.get('testJavaFiles'):
        defects.append('Checkstyle gate must apply to planned main and test Java files')
    if gate.get('suppressionsAllowed') or gate.get('generatedCodeExclusionsAllowed') or gate.get('weakeningAllowed'):
        defects.append('Checkstyle rules must not be weakened, suppressed or excluded')
    if gate.get('syntaxParseSubstitutesCheckstyle') is not False:
        defects.append('A Java syntax parse must never substitute for Checkstyle')
    return defects
