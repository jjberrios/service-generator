"""Deterministic FULL materializer, first version.

Reads ONLY the service workspace plan (`.factory/services/<service>/implementation-plan.yml`, bound to the workspace service-spec hash and the
archetype fingerprint) and the archetype templates, and writes Java under `output/<service>/`. Order of the controls (nothing is written before all pass):

 1. the Sparx/Swagger consistency gate must be CLEARED (recomputed, never trusted);
 2. the plan must be a full, ready plan of this service, consistent with its spec and archetype;
 3. every planned file is classified; components outside the supported set stop the operation (nothing is written unless --supported-only);
 4. every write goes through file_protection (manual or untracked content is preserved; application*.properties is never read or written);
 5. each write is re-checked with guard_write immediately before it happens, and recorded in a manifest with hashes.

Supported component types (v2 adds the functional layer; v1 foundation list kept): archetype-activity-logger, archetype-activity-logger-test, activity-constants, request-headers-model,
internal-typed-exception, jpa-entity, spring-data-jpa-repository. Everything else (DTOs, API interface, controller, service, validator, mapper,
specification, handler, tests that encode business behavior, remove actions) is reported as unsupported; nothing incomplete is invented.
Same plan + archetype + workspace spec => identical bytes and manifest (no timestamps, UTF-8, LF).
"""
from pathlib import Path
import argparse
import hashlib
import os
import sys
import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'plan-service-implementation' / 'scripts'))
import renderers as rd  # noqa: E402
import service_model as sm  # noqa: E402
import java_components as jc  # noqa: E402
import java_components2 as jc2  # noqa: E402
import test_support as ts  # noqa: E402
import assemble_project as ap  # noqa: E402
import consistency_gate as gate  # noqa: E402
import file_protection as fp  # noqa: E402
import workspace as wsm  # noqa: E402
import build_implementation_plan as planner_base  # noqa: E402

VERSION = 'full-materializer-6'
MANIFEST = '.generation-manifest.yml'
REPORT = 'materialization-report.yml'
FOUNDATION = ('archetype-activity-logger', 'archetype-activity-logger-test', 'activity-constants', 'request-headers-model', 'internal-typed-exception',
              'jpa-entity', 'spring-data-jpa-repository')
FUNCTIONAL = {'contract-dto': jc.dto, 'contract-api-interface': jc.api_interface, 'controller-implementation': jc.controller, 'internal-query-model': jc.query_model,
              'offset-based-pageable': jc.pageable, 'jpa-specification': jc.specification, 'data-access-error-translator': jc.translator, 'business-validator': jc2.validator,
              'explicit-contract-data-mapper': jc2.mapper, 'application-service-contract': jc2.service_interface, 'application-service-implementation': jc2.service_impl,
              'central-contract-error-advice': jc2.handler}
SUPPORTED = FOUNDATION + tuple(FUNCTIONAL) + ts.TEST_TYPES + (ts.PERSISTENCE_TYPE,)
CONSTANTS_MARKER = '    // ================= ACTIVIDADES (LOGS) ================='


class MaterializationError(RuntimeError):
    def __init__(self, kind: str, message: str, details=None):
        super().__init__(f'{kind}: {message}')
        self.kind, self.details = kind, details or {}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(rows: dict) -> str:
    return sha(''.join(f'{p}\0{h}\n' for p, h in sorted(rows.items())).encode('utf-8'))


def safe_relative(path: str) -> str:
    rel = str(path).replace('\\', '/')
    parts = rel.split('/')
    if not rel or rel.startswith('/') or ':' in parts[0] or '..' in parts or '' in parts:
        raise MaterializationError('invalid-plan', f'unsafe planned path {path!r}')
    return rel


def load_plan(ws: 'wsm.Workspace', repo: Path) -> tuple[dict, bytes]:
    plan_file = ws.dir / 'implementation-plan.yml'
    if not plan_file.is_file():
        raise MaterializationError('invalid-plan', 'the workspace has no implementation-plan.yml')
    raw = plan_file.read_bytes()
    try:
        plan = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        raise MaterializationError('invalid-plan', 'implementation-plan.yml is not valid YAML') from error
    validate_contract(plan)
    svc = plan.get('service') or {}
    if (plan.get('plan') or {}).get('mode') != 'full' or (plan.get('generation') or {}).get('functionalGenerationReady') is not True:
        raise MaterializationError('invalid-plan', 'the plan is not a ready full plan')
    if svc.get('name') != ws.service or svc.get('outputDirectory') != f'output/{ws.service}':
        raise MaterializationError('invalid-plan', 'the plan belongs to another service or output directory')
    spec = ws.dir / 'service-spec.yml'
    expected = ((plan.get('inputs') or {}).get('serviceSpec') or {}).get('artifactSha256')
    if not spec.is_file() or expected != sha(spec.read_bytes()):
        raise MaterializationError('stale-plan', 'the plan was not built from the current service-spec of this workspace')
    arch = (plan.get('inputs') or {}).get('archetype') or {}
    root = repo / str(arch.get('path'))
    if not root.is_dir() or planner_base.archetype_fingerprint(root) != arch.get('fingerprint'):
        raise MaterializationError('stale-plan', 'the archetype differs from the one used for planning')
    # Planner write_full_plan binds parameters; legacy fixture plans omit this
    # binding explicitly. Never ignore a binding when it is present.
    for key, filename in (('generationParameters', 'generation-parameters.yml'), ('planningInput', 'full-planning-input.yml')):
        binding = plan['inputs'].get(key)
        if binding is not None:
            artifact = ws.dir / filename
            if not isinstance(binding, dict) or binding.get('path') != f'.factory/{filename}' or not artifact.is_file() or binding.get('sha256') != sha(artifact.read_bytes()):
                raise MaterializationError('stale-plan', f'{filename} is missing or changed since planning')
    params_file = ws.dir / 'generation-parameters.yml'
    if not plan['inputs'].get('generationParameters'):
        raise MaterializationError('invalid-plan', 'inputs.generationParameters.sha256 is required; replan with the current planner')
    if params_file.is_file():
        try:
            params = yaml.safe_load(params_file.read_bytes())
        except yaml.YAMLError as error:
            raise MaterializationError('invalid-plan', 'generation-parameters.yml is not valid YAML') from error
        if not isinstance(params, dict) or params.get('version') != 2 or params.get('service') != ws.service or not isinstance(params.get('values'), dict):
            raise MaterializationError('invalid-plan', 'generation-parameters.yml must be version 2, belong to this service and contain values')
        if params.get('unresolved') or (params.get('validation') or {}).get('errors'):
            raise MaterializationError('invalid-plan', 'generation parameters carry unresolved values or validation errors')
        if (params.get('readiness') or {}).get('functionalGenerationReady') is False:
            raise MaterializationError('invalid-plan', 'generation parameters are not functionally ready')
        if plan['inputs'].get('generationParameters'):
            bound_inputs = params.get('inputs') or {}
            if ((bound_inputs.get('serviceSpec') or {}).get('sha256') != expected
                    or (bound_inputs.get('archetype') or {}).get('fingerprint') != arch['fingerprint']):
                raise MaterializationError('stale-plan', 'generation parameter provenance differs from the plan')
    return plan, raw


def validate_contract(plan):
    """Structural v3 contract before any rendering. Semantic support is checked next."""
    def require(condition, message):
        if not condition:
            raise MaterializationError('invalid-plan', message)
    require(isinstance(plan, dict), 'implementation-plan must be a mapping')
    require(isinstance(plan.get('plan'), dict) and type(plan['plan'].get('version')) is int and plan['plan']['version'] == 3,
            'only implementation-plan version 3 is supported')
    for key in ('service', 'inputs', 'generation', 'files', 'api', 'persistenceModel', 'activityLogging'):
        require(isinstance(plan.get(key), dict), f'{key} is required and must be a mapping')
    for key, fields in (('serviceSpec', ('path', 'artifactSha256')), ('archetype', ('path', 'fingerprint'))):
        value = plan['inputs'].get(key)
        require(isinstance(value, dict) and all(isinstance(value.get(k), str) and bool(value[k]) for k in fields), f'inputs.{key} is missing required fields')
    arch_path = safe_relative(plan['inputs']['archetype']['path'])
    require(arch_path.startswith('archetypes/'), 'archetype must be a versioned path under archetypes/')
    for key in ('name', 'package', 'packagePath', 'outputDirectory'):
        require(isinstance(plan['service'].get(key), str) and bool(plan['service'][key]), f'service.{key} is required')
    require(plan['service']['packagePath'] == plan['service']['package'].replace('.', '/'), 'service.packagePath differs from service.package')
    require(isinstance(plan.get('models'), list), 'models must be a list')
    require(isinstance(plan['api'].get('operations'), list) and bool(plan['api']['operations']), 'api.operations must be a nonempty list')
    entries = plan['files'].get('generate')
    require(isinstance(entries, list) and bool(entries), 'files.generate must be a nonempty list')
    seen = set()
    for entry in entries:
        require(isinstance(entry, dict), 'each files.generate entry must be a mapping')
        require(all(isinstance(entry.get(k), str) and bool(entry[k]) for k in ('path', 'action', 'componentType')), 'file entries need path, action and componentType')
        path = safe_relative(entry['path'])
        if entry['action'] not in ('create', 'update', 'retain', 'remove'):
            raise MaterializationError('unsupported', f'{path}: unknown planned action {entry["action"]!r}',
                                       {'unsupported': [{'path': path, 'componentType': entry['componentType'], 'reason': 'unknown planned action'}]})
        require(path not in seen, f'duplicate planned file {path}')
        seen.add(path)
        require(isinstance(entry.get('dependencies', []), list), f'{path}: dependencies must be a list')
        require(type(entry.get('generationOrder', 0)) is int, f'{path}: generationOrder must be an integer')
        if entry['componentType'] in ap.PLANNED_BASELINES:
            require(path == ap.PLANNED_BASELINES[entry['componentType']], f'{entry["componentType"]} may only own {ap.PLANNED_BASELINES[entry["componentType"]]}')
    for entry in entries:
        require(all(isinstance(d, str) and d in seen for d in entry.get('dependencies', [])), f'{entry["path"]}: dependency is not in the planned inventory')
    if 'generationOrdering' in plan:
        order = plan['generationOrdering']
        require(isinstance(order, list) and len(order) == len(seen) and set(order) == seen, 'generationOrdering must cover the planned inventory exactly once')
        positions = {p: i for i, p in enumerate(order)}
        require(all(positions[d] < positions[e['path']] for e in entries for d in e.get('dependencies', [])), 'generationOrdering violates planned dependencies')
    for op in plan['api']['operations']:
        require(isinstance(op, dict) and all(k in op for k in ('operationId', 'method', 'path', 'actionKind', 'contract', 'effectiveStatusCodes', 'validation', 'modelMappings')), 'api operation is missing required fields')
        require(isinstance(op['contract'], dict) and isinstance(op['contract'].get('parameters'), dict)
                and isinstance(op['contract'].get('responses'), dict), f'{op["operationId"]}: contract parameters and responses are required')


def render(plan: dict, entry: dict, repo: Path, cov=None) -> str:
    kind, path = entry['componentType'], safe_relative(entry['path'])
    svc, arch = plan['service'], plan['inputs']['archetype']
    package, package_path = svc['package'], svc['packagePath']
    template_dir = repo / arch['path'] / 'template'
    if kind in ('archetype-activity-logger', 'archetype-activity-logger-test', 'activity-constants'):
        template = template_dir / path.replace(package_path, '__BASE_PACKAGE_PATH__')
        if not template.is_file():
            raise rd.Unsupported(f'archetype template for {path} not found')
        text = template.read_bytes().decode('utf-8')
        if kind == 'activity-constants':
            marker = entry.get('insertAfter') or CONSTANTS_MARKER
            return rd.constants_file(text, package, package_path, (entry.get('activityConstants') or []), marker)
        return rd.from_template(text, package, package_path)
    if kind == 'request-headers-model':
        return rd.request_headers(path, entry.get('components') or [])
    if kind == 'internal-typed-exception':
        return rd.typed_exception(path)
    if kind == 'jpa-entity':
        choices = plan.get('technicalChoices') or {}
        identity = 'GenerationType.IDENTITY' in str((choices.get('generated-id') or {}).get('mechanism', ''))
        return rd.jpa_entity(path, plan.get('persistenceModel') or {}, identity, 'entity-dml-shaping' in choices)
    if kind == 'spring-data-jpa-repository':
        model = plan.get('persistenceModel') or {}
        entity = next((f for f in plan['files']['generate'] if f['componentType'] == 'jpa-entity'), None)
        if not entity or rd.class_of(entity['path']) != model.get('entityClass'):
            raise rd.Unsupported('the repository needs the planned jpa-entity file')
        specification = any(f['componentType'] == 'jpa-specification' for f in plan['files']['generate'])
        return rd.jpa_repository(path, f'{rd.package_of(entity["path"])}.{rd.class_of(entity["path"])}', specification)
    if kind in FUNCTIONAL:
        if '_serviceModel' not in plan:
            plan['_serviceModel'] = sm.build(plan)          # raises Unsupported for any plan outside the supported pattern
        return jc.prune_imports(FUNCTIONAL[kind](plan['_serviceModel'], path))
    if kind in ts.TEST_TYPES or kind == ts.PERSISTENCE_TYPE:
        if '_serviceModel' not in plan:
            plan['_serviceModel'] = sm.build(plan)
        return jc.prune_imports(ts.render_test(plan['_serviceModel'], kind, path, cov if cov is not None else [], entry))
    raise rd.Unsupported(f'component type {kind!r} is not supported by {VERSION}')


def assumption_register(plan: dict, ws: 'wsm.Workspace') -> dict:
    """Where every implemented rule comes from. Anything that would need an unapproved functional assumption stops the generation."""
    decisions = {}
    path = ws.dir / 'sparx-reviewed-decisions.yml'
    if path.is_file():
        raw = yaml.safe_load(path.read_bytes()) or {}
        decisions = {str(d.get('decisionId') or d.get('id')): d for d in (raw.get('decisions') if isinstance(raw, dict) else raw) or [] if isinstance(d, dict)}
    entries, cited = [], set()

    def add(source, ident, statement, ref=None):
        entries.append({'id': ident, 'source': source, 'statement': statement, **({'ref': ref} if ref else {})})

    for op in plan['api']['operations']:
        for rule in (op.get('validation') or [{}])[0].get('rules') or []:
            add('sparx', f'{op["operationId"]}:{rule["ruleId"]}', f'{rule["kind"]}', (rule.get('source') or {}).get('sourceText'))
        for code, response in op['contract']['responses'].items():
            example = (((response.get('content') or {}).get('application/json') or {}).get('example')) or {}
            if example:
                add('swagger', f'{op["operationId"]}:response-{code}-example', 'status text, type, subtype and detail taken verbatim from the contract example')
        for text in json_strings(op):
            cited.add(text)
    for key, choice in (plan.get('technicalChoices') or {}).items():
        add('archetype-technical', f'technical:{key}', str((choice or {}).get('mechanism', ''))[:240])
    for decision_id in sorted(d for d in cited if d in decisions or d.startswith('human-reviewed')):
        record = decisions.get(decision_id)
        if record is None or record.get('humanReviewed') is not True:
            raise MaterializationError('missing-decision', f'the plan relies on human decision {decision_id} which is not an approved human review of this workspace')
        add('human-decision', decision_id, 'approved human decision applied by the plan')
    spec = yaml.safe_load((ws.dir / 'service-spec.yml').read_bytes()) or {}
    pending = [a for a in (spec.get('derivedAssumptions') or []) if isinstance(a, dict) and (a.get('blocker') is True or a.get('classification') not in (None, 'technical-implementation-choice'))]
    for a in pending:
        add('pending-functional', str(a.get('id')), str(a.get('statement', ''))[:240])
    if plan.get('planningBlockers'):
        add('pending-functional', 'planning-blockers', 'the plan carries unresolved planning blockers')
        pending = pending or [{'id': 'planning-blockers'}]
    if pending:
        raise MaterializationError('pending-functional-assumptions', f'{len(pending)} functional assumption(s) need an approved decision before code can be generated; nothing was written',
                                   {'pending': [str(a.get('id')) for a in pending]})
    entries = sorted(entries, key=lambda e: (e['source'], e['id']))
    return {'schemaVersion': 1, 'service': plan['service']['name'], 'entries': entries}


def json_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            if k in ('decisionId', 'aliasDecisionId') and isinstance(v, str):
                yield v
            else:
                yield from json_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from json_strings(v)


def classify(plan: dict, repo: Path) -> dict:
    """Render what is supported; list the rest. Pure: nothing is written here."""
    rendered, unsupported, excluded, kept = {}, [], [], []
    cov, baselines = [], []
    for entry in sorted(plan['files']['generate'], key=lambda f: (f.get('generationOrder', 0), f['path'])):
        path, action, kind = safe_relative(entry['path']), entry['action'], entry['componentType']
        if fp.is_excluded(path):
            excluded.append(path)                      # never opened, whatever the action
            continue
        known = kind in SUPPORTED or kind in ap.PLANNED_BASELINES or kind in ('generation-provenance-manifest', 'existing-technical-baseline')
        if not known or action not in ('create', 'update', 'retain'):
            unsupported.append({'path': path, 'componentType': kind, 'reason': f'unsupported component or action: {kind} / {action}'})
            continue
        if kind in ap.PLANNED_BASELINES:
            if entry.get('mavenAdditions'):
                unsupported.append({'path': path, 'componentType': kind, 'reason': 'service-specific Maven additions need separate assembler support; baseline will not be pruned or approximated'})
            else:
                baselines.append(entry)
            continue
        if path == MANIFEST or action == 'retain':
            kept.append(path)
            continue
        if action not in ('create', 'update'):
            unsupported.append({'path': path, 'componentType': kind, 'reason': f'action {action!r} is not supported by {VERSION}'})
            continue
        if kind not in SUPPORTED:
            unsupported.append({'path': path, 'componentType': kind, 'reason': f'component type {kind!r} is not supported by {VERSION}'})
            continue
        try:
            rendered[path] = {'text': rd.lf(render(plan, entry, repo, cov)), 'action': action, 'componentType': kind}
        except rd.Unsupported as error:
            unsupported.append({'path': path, 'componentType': kind, 'reason': str(error)})
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise MaterializationError('invalid-plan', f'{path}: malformed component data ({type(error).__name__}: {error})') from error
    return {'rendered': rendered, 'unsupported': unsupported, 'excluded': sorted(excluded), 'kept': sorted(kept), 'baselines': baselines, 'cov': sorted(set(cov), key=lambda c: (c[0], c[1] or ''))}


def materialize(repo: Path, service: str, supported_only: bool = False, dry_run: bool = False, assemble: bool = True) -> dict:
    from artifact_integrity import service_lock, IntegrityError
    repo = Path(repo).resolve()
    gate.check_cleared(wsm.Workspace(repo, service).dir, repo, service)
    try:
        with service_lock(repo, service):
            return _materialize_unlocked(repo, service, supported_only, dry_run, assemble)
    except IntegrityError as error:
        raise MaterializationError('integrity', str(error)) from error


def _materialize_unlocked(repo: Path, service: str, supported_only: bool = False, dry_run: bool = False, assemble: bool = True) -> dict:
    repo = Path(repo).resolve()
    ws = wsm.Workspace(repo, service)
    # 1. The gate comes first: a blocked service gets no further than this line (GateError propagates; no file has been touched).
    gate.check_cleared(ws.dir, repo, service)
    from generation_context import resolve_context, SelectionError
    plan_file = ws.dir / 'implementation-plan.yml'
    try:
        plan_doc = yaml.safe_load(plan_file.read_bytes()) if plan_file.is_file() else None
    except yaml.YAMLError:
        plan_doc = None
    plan_section = plan_doc.get('plan') if isinstance(plan_doc, dict) else None
    profile = plan_section.get('profile') if isinstance(plan_section, dict) else None
    try:
        context = resolve_context(repo, service=service)
    except SelectionError as error:
        if profile is None:
            load_plan(ws, repo)  # plan-level errors (stale/invalid) surface before the selection error
        raise MaterializationError('invalid-selection', str(error)) from error
    import profiles
    selected_profile = profiles.resolve(yaml.safe_load((repo / context.archetype / 'archetype.yml').read_bytes()))
    if profile is None and selected_profile != profiles.LEGACY_JPA:
        raise MaterializationError('invalid-plan', 'missing profile for non-legacy archetype')
    if profile is not None and profile != selected_profile:
        raise MaterializationError('invalid-plan', 'plan profile disagrees with selected archetype')
    if profile == profiles.LEGACY_JPA:
        profile = None
    if profile:
        import batch_shell_materializer as batch
        if profile == batch.PROFILE:
            if supported_only or not assemble:
                raise MaterializationError('unsupported', 'batch requires full atomic project assembly; partial generation is not supported')
            return batch.materialize(repo, service, dry_run)
        import jdbc_war_materializer as jdbc
        if profile != jdbc.PROFILE:
            raise MaterializationError('unsupported', f'generation profile {profile!r} has no materializer', {'unsupported': [{'path': 'implementation-plan.yml', 'componentType': 'profile', 'reason': profile}]})
        return jdbc.materialize(repo, service, dry_run)
    plan, plan_bytes = load_plan(ws, repo)
    out_dir = repo / plan['service']['outputDirectory']
    for entry in plan['files']['generate']:
        if (entry['action'] == 'retain' and entry['componentType'] in (*SUPPORTED, *ap.PLANNED_BASELINES, 'existing-technical-baseline') and not fp.is_excluded(entry['path'])
                and entry['path'] != MANIFEST and not (out_dir / entry['path']).is_file()):
            raise MaterializationError('invalid-plan', f'{entry["path"]}: retain requires an existing file')
    try:
        # Always validate semantic capabilities, even if all functional files are
        # marked retain. No partial FULL output for unsupported business behavior.
        plan['_serviceModel'] = sm.build(plan)
        roles, components = sm.header_roles(plan)
        if plan['inputs'].get('generationParameters'):
            entry = next(e for e in plan['files']['generate'] if e['componentType'] == 'request-headers-model')
            if entry.get('components') != components or entry.get('roleMapping', roles) != roles:
                raise MaterializationError('invalid-plan', 'planned RequestHeaders differs from activityLogging.requestHeaders')
    except rd.Unsupported as error:
        raise MaterializationError('unsupported', str(error), {'unsupported': [{'path': 'implementation-plan.yml', 'componentType': 'service-model', 'reason': str(error)}]}) from error
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, StopIteration) as error:
        raise MaterializationError('invalid-plan', f'malformed service model ({type(error).__name__}: {error})') from error
    try:
        register = assumption_register(plan, ws)        # raises before any write when a functional assumption is pending
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise MaterializationError('invalid-plan', f'malformed assumption data ({type(error).__name__}: {error})') from error
    work = classify(plan, repo)
    if work['unsupported'] and not supported_only:
        raise MaterializationError('unsupported', f'{len(work["unsupported"])} planned file(s) need capabilities that {VERSION} does not have; nothing was written',
                                   {'unsupported': work['unsupported']})
    assembly = None
    for entry in work['baselines']:
        exists = (out_dir / entry['path']).is_file()
        if entry['action'] == 'retain' and not exists and plan['inputs'].get('generationParameters'):
            raise MaterializationError('invalid-plan', f'{entry["path"]}: retain requires an existing file')
        if not assemble and (entry['action'] != 'retain' or not exists):
            raise MaterializationError('unsupported', f'{entry["path"]}: the planned baseline requires the Maven assembler')
        if entry['action'] == 'retain':
            work['kept'].append(entry['path'])
    if assemble:
        try:
            assembly = ap.render(plan, repo, ws.dir, out_dir)           # raises before any write on a missing/invalid parameter or an unresolved token
        except ap.AssemblyError as error:
            raise MaterializationError(error.kind, str(error).split(': ', 1)[1], error.details)
        for path, item in assembly['files'].items():
            if path in work['rendered']:
                raise MaterializationError('invalid-plan', f'{path}: duplicate materializer and assembler ownership')
            baseline = next((e for e in work['baselines'] if e['path'] == path), None)
            work['rendered'][path] = {'text': item['bytes'].decode('utf-8'), 'action': baseline['action'] if baseline else 'create', 'componentType': 'project-assembly'}
        for entry in work['baselines']:
            if entry['action'] in ('create', 'update') and entry['path'] not in assembly['files']:
                raise MaterializationError('invalid-plan', f'{entry["path"]}: planned baseline was not assembled')
    from artifact_integrity import prepare, publish, protected, IntegrityError
    payload = {p: item['text'].encode('utf-8') for p, item in work['rendered'].items()}
    try:
        to_write, unchanged = prepare(out_dir, ws.dir, payload)
    except fp.ProtectedFileError as error:
        raise MaterializationError('protected-files', str(error), getattr(error, 'details', {})) from error
    except IntegrityError as error:
        raise MaterializationError('invalid-plan', str(error)) from error
    previous_manifest = yaml.safe_load((out_dir / MANIFEST).read_bytes()) if (out_dir / MANIFEST).is_file() else {}
    rows = {r['path']: {k: v for k, v in r.items() if k != 'path'} for r in (previous_manifest or {}).get('fileInventory', [])
            if not protected(r['path']) and (out_dir / r['path']).is_file()}
    for path, item in work['rendered'].items():
        rows[path] = {'sha256': sha(item['text'].encode('utf-8')), 'action': item['action'], 'componentType': item['componentType']}
    manifest = {'schemaVersion': 1, 'materializer': VERSION, 'complete': not work['unsupported'], 'service': service,
                'inputs': {'implementationPlanSha256': sha(plan_bytes), 'serviceSpecSha256': sha((ws.dir / 'service-spec.yml').read_bytes()),
                           'archetypeFingerprint': plan['inputs']['archetype']['fingerprint'], **({'assembly': {'assembler': ap.VERSION, 'parametersSha256': assembly['report']['parametersSha256']}} if assembly else {})},
                'fileInventory': [{'path': p, **rows[p]} for p in sorted(rows)], 'unsupportedComponents': sorted(work['unsupported'], key=lambda u: u['path']),
                'payloadTreeSha256': tree_hash({p: r['sha256'] for p, r in rows.items()})}
    manifest_bytes = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
    report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'status': 'complete' if manifest['complete'] else 'partial-supported-only',
              'written': sorted(to_write), 'unchanged': sorted(unchanged), 'excludedUntouched': work['excluded'], 'retained': work['kept'],
              'unsupported': manifest['unsupportedComponents'], 'payloadTreeSha256': manifest['payloadTreeSha256'], 'manifestSha256': sha(manifest_bytes), 'dryRun': dry_run, **({'assembly': assembly['report']} if assembly else {})}
    report['planContract'] = {'version': plan['plan']['version'], 'parametersHashVerified': True,
                              'headerRolesSource': 'roles' if 'roles' in plan['activityLogging']['requestHeaders'] else 'legacy-roleMapping'}
    if dry_run:
        return report
    publish(out_dir, ws.dir, payload, manifest_bytes)
    write_atomic(ws.dir / 'assumptions-register.yml', yaml.safe_dump(register, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    if work['cov'] or any(v['componentType'] in ts.TEST_TYPES for v in work['rendered'].values()):
        model = plan.get('_serviceModel') or sm.build(plan)
        model['service'] = service
        pom = out_dir / 'pom.xml'
        pom_text = pom.read_text(encoding='utf-8') if pom.is_file() else (repo / plan['inputs']['archetype']['path'] / 'template' / 'pom.xml').read_text(encoding='utf-8')
        tests = [rd.class_of(p) for p, v in work['rendered'].items() if v['componentType'] in ts.TEST_TYPES]
        trace = ts.traceability(model, work['cov'])
        evidence_file = ws.dir / ts.EVIDENCE
        evidence = yaml.safe_load(evidence_file.read_bytes()) if evidence_file.is_file() else None
        official_file = ws.dir / ts.OFFICIAL
        official = yaml.safe_load(official_file.read_bytes()) if official_file.is_file() else None
        write_atomic(ws.dir / 'tests-traceability.yml', yaml.safe_dump(trace, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
        write_atomic(ws.dir / 'coverage-scope.yml', yaml.safe_dump(ts.coverage_scope(plan, pom_text, work['cov'], tests, trace, evidence, manifest['payloadTreeSha256'], official), sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    write_atomic(ws.dir / REPORT, yaml.safe_dump(report, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    return report


def write_atomic(target: Path, data: bytes):
    from artifact_integrity import write_atomic as atomic
    atomic(target, data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('service')
    parser.add_argument('--supported-only', action='store_true', help='write only the supported components and mark the manifest incomplete')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-assemble', action='store_true', help='do not assemble the archetype technical files (pom, wrapper, configuration, deployment)')
    args = parser.parse_args(argv)
    try:
        report = materialize(Path.cwd(), args.service, args.supported_only, args.dry_run, not args.no_assemble)
        print(yaml.safe_dump({k: report.get(k) for k in ('status', 'written', 'unchanged', 'excludedUntouched', 'unsupported', 'payloadTreeSha256')}, allow_unicode=True, sort_keys=False))
        return 0
    except (gate.GateError, fp.ProtectedFileError, wsm.WorkspaceError) as error:
        print(f'full_materializer: BLOCKED {error}', file=sys.stderr)
        return 3
    except MaterializationError as error:
        print(f'full_materializer: {error}', file=sys.stderr)
        print(yaml.safe_dump(error.details, allow_unicode=True), file=sys.stderr)
        return 4 if error.kind == 'unsupported' else 3 if error.kind in ('protected-files', 'pending-functional-assumptions', 'missing-decision', 'missing-parameter', 'invalid-parameter', 'parameter-conflict') else 2


if __name__ == '__main__':
    sys.exit(main())
