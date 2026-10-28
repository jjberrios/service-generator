"""Test-component dispatch, rule traceability register and JaCoCo scope analysis (static; nothing here executes Maven or measures coverage)."""
import fnmatch
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from renderers import Unsupported, class_of
import test_components as t1
import test_components2 as t2
import test_components3 as t3
from test_components4 import parse

TEST_TYPES = ('unit-mapping-persistence-test', 'controller-contract-test', 'activity-logging-test')
PERSISTENCE_TYPE = 'repository-persistence-test'

# file-name stem suffix -> (generator, class kind the test belongs to)
BY_SUFFIX = (('ValidatorTest', t1.validator_test, 'business-validator'), ('MapperTest', t2.mapper_test, 'explicit-contract-data-mapper'),
             ('SpecificationsTest', t2.specification_test, 'jpa-specification'), ('ServiceImplTest', t2.service_test, 'application-service-implementation'),
             ('ControllerTest', t3.controller_test, 'controller-implementation'), ('ExceptionHandlerTest', t3.handler_test, 'central-contract-error-advice'),
             ('ActivityLoggingTest', t3.logging_test, 'archetype-activity-logger'))


def generator_for(kind: str, path: str):
    stem = class_of(path)
    if kind == PERSISTENCE_TYPE:
        raise Unsupported('JPA persistence tests need an in-memory database that the approved archetype POM does not declare; adding a dependency needs an explicit authorization')
    if kind not in TEST_TYPES:
        raise Unsupported(f'test component {kind!r} is not supported')
    for suffix, fn, _ in BY_SUFFIX:
        if stem.endswith(suffix):
            return fn
    model_entity = None
    return ('entity', stem)


def render_test(model, kind: str, path: str, cov: list, entry=None) -> str:
    chosen = planned_test_generator(model, kind, path, entry or {})
    if isinstance(chosen, tuple):
        if class_of(path) == model['entity']['class'] + 'Test':
            return t3.entity_test(model, path, cov)
        raise Unsupported(f'no test generator matches {class_of(path)}')
    return chosen(model, path, cov)


def planned_test_generator(model, kind, path, entry):
    """Semantic component + planned dependencies, preserving the planner's filename.

    Old fixture plans without dependencies use exact production-class names or the
    documented suffix fallback. Ambiguous dependencies never use that fallback.
    """
    if kind == PERSISTENCE_TYPE:
        return generator_for(kind, path)
    if kind == 'activity-logging-test':
        return t3.logging_test
    deps = entry.get('dependencies') or []
    paths = model['paths']
    if kind == 'controller-contract-test':
        if paths.get('controller-implementation') in deps or paths.get('contract-api-interface') in deps:
            return t3.controller_test
        if paths.get('central-contract-error-advice') in deps:
            return t3.handler_test
    targets = {k: fn for _, fn, k in BY_SUFFIX}
    targets['jpa-entity'] = t3.entity_test
    if kind == 'unit-mapping-persistence-test':
        candidates = [fn for k, fn in targets.items() if paths.get(k) in deps]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise Unsupported(f'{path}: ambiguous test dependencies; expected one production component')
    if deps:
        raise Unsupported(f'{path}: no supported test component is identified by its planned dependencies')
    for k, fn in targets.items():
        if k in paths and class_of(path) == class_of(paths[k]) + 'Test':
            return fn
    return generator_for(kind, path)       # explicit compatibility with old dependency-free plans


# ------------------------------------------------------------------------------------------------------------------------- traceability
def universe(model) -> dict:
    """Every rule id the generated production code implements, with the evidence class it came from."""
    rules = {}
    for op in model['ops']:
        oid = op['id']
        for status in op['statuses']:
            rules[f'{oid}:outcome:{status}'] = 'contract'
        for name in ('headers:roles', 'contract:required-header'):
            rules[f'{oid}:{name}'] = 'contract'
        for r in op.get('rules', []):
            rules[f'{oid}:rule:{r["ruleId"]}'] = 'business-rule'
        if op['requestModel']:
            for name in ('contract:malformed-body', 'contract:null-field'):
                rules[f'{oid}:{name}'] = 'contract'
        if op['requestModel']:
            rules[f'{oid}:logging:body'] = 'archetype'
        for kind in ('path', 'query', 'header'):
            for p in op['params'][kind]:
                for name, _ in parse(p['annotations']):
                    rules[f'{oid}:param:{p["name"]}:{name}'] = 'contract'
        if op['requestModel']:
            for f in model['models'][op['requestModel']]['fields']:
                for name, _ in parse(f.get('validationAnnotations')):
                    if name != 'NotNull':
                        rules[f'{oid}:body:{f["name"]}:{name}'] = 'contract'
    return rules


def traceability(model, cov: list) -> dict:
    covered, seen, reasons = {}, set(), {}
    for item in cov:
        rule, test = item[0], item[1]
        if test:
            covered.setdefault(rule, []).append(test)
        elif len(item) > 2:
            reasons.setdefault(rule, item[2])
        seen.add(rule)
    known = universe(model)
    entries = [{'rule': r, 'source': known.get(r, 'derived'), 'status': 'covered', 'tests': sorted(set(t)), **({'gaps': [reasons[r]]} if r in reasons else {})} for r, t in sorted(covered.items())]
    for r in sorted(r for r in (set(known) | seen) if r not in covered):
        entries.append({'rule': r, 'source': known.get(r, 'derived'), 'status': 'uncovered', 'reason': reasons.get(r, 'no generator derives a test for this rule from the plan')})
    return {'schemaVersion': 2, 'service': model.get('service'), 'covered': sum(1 for e in entries if e['status'] == 'covered'), 'uncovered': sum(1 for e in entries if e['status'] == 'uncovered'), 'rules': entries}


# ----------------------------------------------------------------------------------------------------------------------- jacoco scope
def pom_jacoco(pom_text: str) -> dict:
    root = ET.fromstring(re.sub(r'\sxmlns="[^"]+"', '', pom_text, count=1))
    plugin = next((p for p in root.iter('plugin') if (p.findtext('artifactId') or '') == 'jacoco-maven-plugin'), None)
    if plugin is None:
        return {'configured': False}
    excludes = [e.text.strip() for e in plugin.iter('exclude') if e.text]
    limit = plugin.find('.//limit')
    rule = plugin.find('.//rule')
    return {'configured': True, 'excludes': excludes,
            'minimum': (limit.findtext('minimum') if limit is not None else None), 'counter': (limit.findtext('counter') if limit is not None else None),
            'value': (limit.findtext('value') if limit is not None else None), 'element': (rule.findtext('element') if rule is not None else None)}


def glob_regex(pattern: str):
    """Ant-style glob as JaCoCo applies it: ** crosses directories, * and ? stay inside one path segment."""
    out, i = '', 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out += '(?:.*/)?'
            i += 3
        elif pattern.startswith('**', i):
            out += '.*'
            i += 2
        elif pattern[i] == '*':
            out += '[^/]*'
            i += 1
        elif pattern[i] == '?':
            out += '[^/]'
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r'\Z')


def class_rows(plan_files: list, package_path: str, excludes: list, tested: dict) -> list:
    patterns = [glob_regex(g.replace('__BASE_PACKAGE_PATH__', package_path)) for g in excludes]
    rows = []
    for f in plan_files:
        path = f['path']
        if not path.startswith('src/main/java/') or not path.endswith('.java'):
            continue
        cls = path[len('src/main/java/'):-5] + '.class'
        skipped = any(rx.match(cls) for rx in patterns)
        name = class_of(path)
        rows.append({'class': name, 'path': path, 'componentType': f.get('componentType'), 'measured': not skipped, 'tests': sorted(tested.get(name, []))})
    return sorted(rows, key=lambda r: r['path'])


EVIDENCE = 'execution-evidence.yml'
HONORED = {'javac-compilation': 'compilation', 'junit-launcher-tests': 'testsExecuted'}
PERSISTENCE_PENDING = ('repository-persistence-test', 'JPA mapping, Specification queries, LIKE escaping, ordering and the Oracle treatment of empty strings are not exercised against a database; '
                       'an in-memory or real test database dependency is absent from the approved POM and needs explicit authorization')
LIMITATIONS = ('JaCoCo, Maven and the official Checkstyle gate (D-014) were not executed by the materializer; their results are unknown',
               'generated tests were never run by the materializer; any execution recorded as evidence was made without Maven and is bound to the exact generated tree',
               'persistence behavior against a database is not verified',
               'the 80% package threshold of the POM is unverified; the scope below only says which classes would be measured',
               'declared constraints are exercised only where a sample can be derived from the declared source values; the rest is listed with a reason',
               'header parameter constraints are not applied by the generated API interface and therefore not executed')


OFFICIAL = 'validation-evidence.yml'
OFFICIAL_TOOLS = ('maven', 'compilation', 'testsExecuted', 'checkstyleOfficial', 'jacoco')
NOT_RUN = {'maven': 'not-executed', 'compilation': 'not-executed', 'testsExecuted': 'not-executed', 'checkstyleOfficial': 'unverified', 'jacoco': 'not-verified'}


def tool_status(evidence: dict, tree_hash: str, threshold: dict, official: dict = None) -> dict:
    tools = _tool_status(evidence, tree_hash, threshold)
    if official:
        fresh = official.get('projectTreeSha256') == tree_hash
        for key in OFFICIAL_TOOLS:
            entry = (official.get('tools') or {}).get(key) or {'status': 'not-executed'}
            if entry['status'] == 'not-executed':
                tools[key] = {'status': NOT_RUN[key], 'source': 'maven-reports', 'note': 'the tool did not run in the recorded Maven build'}
            elif fresh:
                tools[key] = dict(entry, source='maven-reports', mavenUsed=True)
            else:
                tools[key] = {'status': 'stale', 'previousStatus': entry['status'], 'source': 'maven-reports', 'note': 'recorded for a different project tree; rerun the official validation'}
        if 'jacoco' in tools and 'threshold' not in tools['jacoco']:
            tools['jacoco']['threshold'] = threshold
    return tools


def _tool_status(evidence: dict, tree_hash: str, threshold: dict) -> dict:
    tools = {'maven': {'status': 'not-executed'},
             'checkstyleOfficial': {'status': 'unverified', 'note': 'maven-checkstyle-plugin (D-014) has not run; the preventive lint never replaces it'},
             'jacoco': {'status': 'not-verified', 'threshold': threshold, 'note': 'no coverage percentage exists'}}
    recorded = (evidence or {}).get('entries') or {}
    for tool, key in HONORED.items():
        entry = recorded.get(tool)
        if not entry:
            tools[key] = {'status': 'not-executed'}
        elif entry.get('payloadTreeSha256') != tree_hash:
            tools[key] = {'status': 'stale', 'note': 'recorded for a different generated tree; rerun and record again'}
        else:
            tools[key] = {'status': entry['status'], 'method': entry['method'], 'mavenUsed': False, 'detail': entry.get('detail')}
    return tools


def record_execution(ws_dir, tool: str, status: str, method: str, detail: str, tree_hash: str):
    """Records an execution that really happened (javac or a JUnit launcher, never Maven/Checkstyle/JaCoCo), bound to the generated tree."""
    if tool not in HONORED or status not in ('passed', 'failed'):
        raise ValueError(f'only {sorted(HONORED)} with passed/failed can be recorded; Maven, Checkstyle and JaCoCo results are never recorded here')
    path = Path(ws_dir) / EVIDENCE
    data = (__import__('yaml').safe_load(path.read_bytes()) if path.is_file() else None) or {'schemaVersion': 1, 'entries': {}}
    data['entries'][tool] = {'status': status, 'method': method, 'detail': detail, 'payloadTreeSha256': tree_hash}
    path.write_text(__import__('yaml').safe_dump(data, sort_keys=True, allow_unicode=True), encoding='utf-8')


def scope_status(tools: dict) -> tuple:
    if (tools.get('jacoco') or {}).get('status') == 'passed':
        return 'verified-by-maven-evidence', 'JaCoCo ran in a recorded Maven build bound to this exact project tree; the per-package ratios are in tools.jacoco'
    return 'not-verified', 'static analysis of the POM and the plan; no valid JaCoCo execution is recorded for this exact project tree and no coverage percentage is claimed'


def coverage_scope(plan: dict, pom_text: str, cov: list, generated_tests: list, register: dict = None, evidence: dict = None, tree_hash: str = None, official: dict = None) -> dict:
    config = pom_jacoco(pom_text)
    package_path = plan['service']['packagePath']
    tested, methods_by_test = {}, {}
    for item in cov:
        test = item[1]
        if test:
            cls, method = test.split('#')
            tested.setdefault(cls.removesuffix('Test'), set()).add(test)
            methods_by_test.setdefault(cls, set()).add(method)
    for stem in generated_tests:
        tested.setdefault(stem.removesuffix('Test'), set())
    rows = class_rows(plan['files']['generate'], package_path, config.get('excludes', []), tested) if config['configured'] else []
    measured = [r for r in rows if r['measured']]
    logger_tests = {'ActivityLoggerTest', 'ActivityLoggingTest'}
    for r in measured:
        kind = r['componentType']
        if kind in ('application-service-contract', 'contract-api-interface'):
            r['covered-by-generated-tests'], r['note'] = True, 'interface without executable instructions'
        elif kind == 'activity-constants':
            r['covered-by-generated-tests'], r['note'] = True, 'constants only; no behavior to test'
        elif kind == 'archetype-activity-logger':
            r['covered-by-generated-tests'] = bool(logger_tests & set(generated_tests))
        else:
            r['covered-by-generated-tests'] = any(g == r['class'] + 'Test' for g in generated_tests)
    risks = []
    if not config['configured']:
        risks.append('the POM declares no jacoco-maven-plugin; no coverage scope can be derived')
    for r in measured:
        if not r['covered-by-generated-tests']:
            risks.append(f'measured class {r["class"]} has no generated test; the package threshold may fail')
    folder = lambda r: r['path'][len('src/main/java/'):].rsplit('/', 1)[0].replace('/', '.')
    packages = {'excludedFromJacoco': sorted({folder(r) for r in rows if not r['measured']} - {folder(r) for r in measured}),
                'partiallyExcluded': sorted({folder(r) for r in rows if not r['measured']} & {folder(r) for r in measured}), 'measured': sorted({folder(r) for r in measured})}
    entries = (register or {}).get('rules', [])
    rule_summary = {'register': 'tests-traceability.yml', 'covered': sum(1 for e in entries if e['status'] == 'covered'), 'uncovered': sum(1 for e in entries if e['status'] == 'uncovered'),
                    'uncoveredRules': [{'rule': e['rule'], 'reason': e['reason']} for e in entries if e['status'] == 'uncovered']}
    has_repository = any(f['componentType'] == 'spring-data-jpa-repository' for f in plan['files']['generate'])
    pending = [{'kind': PERSISTENCE_PENDING[0], 'reason': PERSISTENCE_PENDING[1]}] if has_repository and not any(f['componentType'] == 'repository-persistence-test' for f in plan['files']['generate']) else []
    threshold = {k: config.get(k) for k in ('minimum', 'counter', 'value', 'element')}
    if pending:
        risks.append('persistence tests are pending; database-dependent behavior has no executable evidence')
    tools = tool_status(evidence, tree_hash, threshold, official)
    status, statement = scope_status(tools)
    return {'schemaVersion': 2, 'service': plan['service']['name'], 'status': status,
            'statement': statement,
            'threshold': threshold, 'excludePatterns': config.get('excludes', []), 'packages': packages,
            'componentsWithGeneratedTests': [{'component': k.removesuffix('Test'), 'testClass': k, 'testMethods': len(v)} for k, v in sorted(methods_by_test.items())],
            'testClasses': sorted(generated_tests), 'rules': rule_summary, 'pendingTests': pending,
            'tools': tools, 'limitations': list(LIMITATIONS),
            'measuredClasses': [{k: v for k, v in r.items() if k not in ('measured', 'componentType')} for r in measured], 'excludedClasses': [r['class'] for r in rows if not r['measured']],
            'risks': sorted(set(risks))}
