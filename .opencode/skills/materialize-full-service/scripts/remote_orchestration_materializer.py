"""Deterministic materializer of the remote-orchestration pattern (HTTP orchestrator of claro-spring-ms that calls dependencies and compensates).

Reads ONLY the workspace plan (`implementation-plan.yml`, pattern `remote-orchestration`, bound to the workspace service-spec, generation parameters and archetype
fingerprint) plus the archetype templates, and writes Java under `output/<service>/` with the same controls as the single-entity FULL materializer: consistency
gate recomputed by the caller, assembly of the archetype technical files, file protection, per-file guard and a hashed manifest written last.
Same plan + archetype => identical bytes (UTF-8, LF, ASCII Java). Called from `full_materializer` and `feasibility_preflight`; it never touches
`application*.properties` except creating the example when absent (assembler, D-015).
"""
from pathlib import Path
import hashlib
import sys
import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'plan-service-implementation' / 'scripts'))
import assemble_project as ap  # noqa: E402
import file_protection as fp  # noqa: E402
import workspace as wsm  # noqa: E402
import build_implementation_plan as planner_base  # noqa: E402
import remote_orchestration_java as rj  # noqa: E402
import remote_orchestration_flow_tests as rft  # noqa: E402

PATTERN = 'remote-orchestration'
VERSION = 'remote-orchestration-materializer-1'
MANIFEST = '.generation-manifest.yml'
MARKER = '    // ================= ACTIVIDADES (LOGS) ================='
GENERATOR_FILES = ['remote_orchestration_runtime.py', 'remote_orchestration_java.py', 'remote_orchestration_tests.py', 'remote_orchestration_flow_tests.py',
                   'remote_orchestration_materializer.py']
COMPONENT_TYPES = {'controller/impl/AgreementController.java': 'controller-implementation', 'service/impl/AgreementServiceImpl.java': 'application-service-implementation',
                   'dto/request/RequestHeaders.java': 'request-headers-model'}


class Failure(RuntimeError):
    def __init__(self, kind, message, details=None):
        super().__init__(f'{kind}: {message}')
        self.kind, self.details = kind, details or {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def is_pattern(plan):
    return isinstance(plan, dict) and isinstance(plan.get('plan'), dict) and plan['plan'].get('pattern') == PATTERN


def generate(plan):
    """Pure generation: ({relative path: text}, constants)."""
    main, constants = rj.build_main(plan)
    tests = rft.build_tests(plan)
    overlap = set(main) & set(tests)
    if overlap:
        raise Failure('invalid-plan', f'duplicate generated paths {sorted(overlap)}')
    return {**main, **tests}, constants


def component_type(path):
    for suffix, kind in COMPONENT_TYPES.items():
        if path.endswith(suffix):
            return kind
    return 'remote-orchestration-test' if path.startswith('src/test/') else 'remote-orchestration-component'


def load_plan(ws, repo):
    plan_file = ws.dir / 'implementation-plan.yml'
    if not plan_file.is_file():
        raise Failure('invalid-plan', 'the workspace has no implementation-plan.yml')
    raw = plan_file.read_bytes()
    plan = yaml.safe_load(raw)
    if not is_pattern(plan) or plan['plan'].get('mode') != 'full' or (plan.get('generation') or {}).get('functionalGenerationReady') is not True:
        raise Failure('invalid-plan', 'the plan is not a ready full remote-orchestration plan')
    svc = plan.get('service') or {}
    if svc.get('name') != ws.service or svc.get('outputDirectory') != f'output/{ws.service}':
        raise Failure('invalid-plan', 'the plan belongs to another service or output directory')
    spec_file = ws.dir / 'service-spec.yml'
    if not spec_file.is_file() or plan['inputs']['serviceSpec']['artifactSha256'] != sha(spec_file.read_bytes()):
        raise Failure('stale-plan', 'the plan was not built from the current service-spec of this workspace')
    arch = plan['inputs']['archetype']
    root = repo / arch['path']
    if not root.is_dir() or planner_base.archetype_fingerprint(root) != arch['fingerprint']:
        raise Failure('stale-plan', 'the archetype differs from the one used for planning')
    for key, filename in (('generationParameters', 'generation-parameters.yml'), ('planningInput', 'full-planning-input.yml')):
        binding = plan['inputs'].get(key)
        artifact = ws.dir / filename
        if not isinstance(binding, dict) or not artifact.is_file() or binding.get('sha256') != sha(artifact.read_bytes()):
            raise Failure('stale-plan', f'{filename} is missing or changed since planning')
    params = yaml.safe_load((ws.dir / 'generation-parameters.yml').read_bytes())
    if params.get('version') != 2 or params.get('service') != ws.service or not isinstance(params.get('values'), dict) or params.get('unresolved'):
        raise Failure('invalid-plan', 'generation-parameters.yml must be version 2, belong to this service, contain values and carry no unresolved entry')
    spec = yaml.safe_load(spec_file.read_bytes())
    if spec['orchestration'] != {k: v for k, v in plan['orchestration'].items() if k in spec['orchestration']} or spec['contract'] != plan['contract']:
        raise Failure('stale-plan', 'the plan orchestration or contract differs from the service-spec')
    return plan, raw, spec


def render(repo, ws, plan):
    out_dir = repo / plan['service']['outputDirectory']
    generated, constants = generate(plan)
    planned = {f['path'] for f in plan['files']['generate']} - {MANIFEST}
    if planned != set(generated):
        raise Failure('invalid-plan', 'the planned file inventory differs from the generated components', {'missing': sorted(planned - set(generated))[:10], 'unplanned': sorted(set(generated) - planned)[:10]})
    try:
        assembly = ap.render(plan, repo, ws.dir, out_dir)
    except ap.AssemblyError as error:
        raise Failure(error.kind, str(error).split(': ', 1)[-1], error.details) from error
    payload = {path: item['bytes'] for path, item in assembly['files'].items()}
    package_path = plan['service']['packagePath']
    constants_path = f'src/main/java/{package_path}/utils/ConstanApi.java'
    if constants_path not in payload:
        raise Failure('invalid-plan', 'the archetype ConstanApi template was not assembled')
    text = payload[constants_path].decode('utf-8')
    if MARKER not in text:
        raise Failure('invalid-plan', 'ConstanApi has no ACTIVIDADES (LOGS) marker')
    payload[constants_path] = text.replace(MARKER, MARKER + '\n' + rj.activity_constants(constants) + '\n', 1).encode('utf-8')
    for path, content in generated.items():
        if path in payload:
            raise Failure('invalid-plan', f'{path}: duplicate generator and assembler ownership')
        payload[path] = content.encode('utf-8')
    return out_dir, assembly, payload


def _materialize_checked(repo, service, dry_run=False):
    from artifact_integrity import prepare, publish, protected, write_atomic, IntegrityError
    repo = Path(repo).resolve()
    ws = wsm.Workspace(repo, service)
    plan, plan_bytes, spec = load_plan(ws, repo)
    out_dir, assembly, payload = render(repo, ws, plan)
    try:
        to_write, unchanged = prepare(out_dir, ws.dir, payload)
    except fp.ProtectedFileError as error:
        raise Failure('protected-files', str(error), getattr(error, 'details', {})) from error
    except IntegrityError as error:
        raise Failure('invalid-plan', str(error)) from error
    previous = yaml.safe_load((out_dir / MANIFEST).read_bytes()) if (out_dir / MANIFEST).is_file() else {}
    rows = {r['path']: {k: v for k, v in r.items() if k != 'path'} for r in (previous or {}).get('fileInventory', []) if not protected(r['path']) and (out_dir / r['path']).is_file()}
    for path, data in payload.items():
        rows[path] = {'sha256': sha(data), 'action': 'create', 'componentType': 'project-assembly' if path in assembly['files'] else component_type(path)}
    tree = sha(''.join(f'{p}\0{r["sha256"]}\n' for p, r in sorted((p, r) for p, r in rows.items())).encode('utf-8'))
    generator = sha(b''.join((HERE / name).read_bytes().replace(b'\r\n', b'\n') for name in GENERATOR_FILES))
    manifest = {'schemaVersion': 1, 'materializer': VERSION, 'complete': True, 'service': service,
                'inputs': {'implementationPlanSha256': sha(plan_bytes), 'serviceSpecSha256': sha((ws.dir / 'service-spec.yml').read_bytes()), 'generatorSha256': generator,
                           'archetypeFingerprint': plan['inputs']['archetype']['fingerprint'], 'assembly': {'assembler': ap.VERSION, 'parametersSha256': assembly['report']['parametersSha256']}},
                'fileInventory': [{'path': p, **rows[p]} for p in sorted(rows)], 'unsupportedComponents': [], 'payloadTreeSha256': tree}
    manifest_bytes = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
    report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'status': 'complete', 'written': sorted(to_write), 'unchanged': sorted(unchanged), 'unsupported': [],
              'payloadTreeSha256': tree, 'manifestSha256': sha(manifest_bytes), 'dryRun': dry_run, 'assembly': assembly['report'],
              'verification': {'maven': 'not-executed', 'checkstyle': 'unverified', 'jacoco': 'not-verified', 'note': 'static generation only; no compilation, no database, no deployment'}}
    if dry_run:
        return report
    publish(out_dir, ws.dir, payload, manifest_bytes)
    for rel, data in (assembly.get('createOnly') or {}).items():
        if not (out_dir / rel).exists():
            write_atomic(out_dir / rel, data)
    register = {'schemaVersion': 1, 'service': service, 'kind': 'agent-decisions-under-user-delegation',
                'assumptions': [{'id': a['id'], 'statement': a['statement'], 'status': 'assumption-not-confirmed-by-sources'} for a in spec['derivedAssumptions']],
                'gaps': spec['gaps'], 'discrepancies': spec['discrepancies']}
    write_atomic(ws.dir / 'assumptions-register.yml', yaml.safe_dump(register, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    write_atomic(ws.dir / 'materialization-report.yml', yaml.safe_dump(report, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    return report


def preflight(repo, service, plan, add):
    """Rows for the feasibility report: each operation, every planned component and the in-memory preview (nothing is written)."""
    import full_materializer as fm
    for op in plan['api']['operations']:
        add(op['operationId'], 'operation', 'supported', 'remote-orchestration pattern: remote calls, decisions and compensation chains from the plan')
    try:
        report = _materialize_checked(repo, service, True)
    except Failure as error:
        raise fm.MaterializationError(error.kind, str(error).split(': ', 1)[-1], error.details) from error
    for path in sorted(report['written'] + report['unchanged']):
        add(path, 'component', 'supported', 'generated by remote_orchestration_materializer (in-memory preview)')
    return report
