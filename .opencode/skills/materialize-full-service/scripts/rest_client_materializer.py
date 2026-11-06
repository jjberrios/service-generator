"""Deterministic materializer for the `rest-client-v1` variant of an approved archetype (claro-spring-ms: REST orchestration without persistence).

Renders the Java derived from the implementation plan (rest_client_java*.py), the archetype template technical files through the shared assembler, and
records provenance exactly like the other backends: gate first, protected files, atomic publication with the manifest last. The plan is recomputed from the
current inputs and must be identical (a stale or hand-edited plan stops the run). Checkstyle (D-014) is never claimed as passed: it stays `unverified`.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import renderers as rd
import rest_client_java as rj
import rest_client_java2 as rj2

VARIANT = 'rest-client-v1'
VERSION = 'rest-client-materializer-1'
TYPED_BACKEND_SERVICES = ('collection-integration',)
CONSTANTS_MARKER = '    // ================= ACTIVIDADES (LOGS) ================='


def render_entry(g: rj.Gen, plan: dict, entry: dict, repo: Path) -> str:
    kind, path = entry['componentType'], entry['path']
    name = rd.class_of(path)
    svc, arch = plan['service'], plan['inputs']['archetype']
    names = g.names
    if kind == 'contract-dto':
        return g.dto(name)
    if kind == 'request-headers-model':
        return rd.request_headers(path, entry['components'])
    if kind == 'request-headers-model-all':
        return g.request_headers_all()
    if kind == 'contract-api-interface':
        return g.api_interface()
    if kind == 'controller-implementation':
        return g.controller()
    if kind == 'application-service-contract':
        return g.service_interface()
    if kind == 'application-service-implementation':
        return g.service_impl()
    if kind == 'business-validator':
        return g.validator()
    if kind == 'backend-request-mapper':
        return g.backend_mapper()
    if kind == 'response-mapper-omitted':
        return g.response_mapper()
    if kind == 'service-error-catalog':
        return {'ServiceError': g.service_error, 'ErrorCatalog': g.error_catalog}[name]()
    if kind == 'internal-typed-exception':
        return {'ServiceOperationException': g.service_operation_exception, 'IntegrationException': g.integration_exception}[name]()
    if kind == 'central-contract-error-advice':
        return g.handler()
    if kind in ('archetype-activity-logger', 'archetype-activity-logger-test', 'activity-constants'):
        template = repo / arch['path'] / 'template' / path.replace(svc['packagePath'], '__BASE_PACKAGE_PATH__')
        if not template.is_file():
            raise rd.Unsupported(f'archetype template for {path} not found')
        text = template.read_bytes().decode('utf-8')
        if kind == 'activity-constants':
            return rd.constants_file(text, svc['package'], svc['packagePath'], entry.get('activityConstants') or [], CONSTANTS_MARKER)
        return rd.from_template(text, svc['package'], svc['packagePath'])
    if kind == 'rest-client-config':
        return rj2.config(g)
    if kind == 'rest-client-support':
        return {'IntegrationSupport': rj2.support, 'CatalogCache': rj2.cache}[name](g)
    if kind == 'rest-client':
        integration = next(n for n, i in g.integrations.items() if i['client'] == name)
        return rj2.client(g, integration)
    if kind == 'rest-client-dto':
        return g.backend_dto(name)
    if kind == 'unit-test-junit5':
        if name == f"{names['controller']}Test":
            return rj2.controller_test(g)
        if name == f"{names['serviceImpl']}Test":
            return rj2.service_test(g)
        if name == f"{names['validator']}Test":
            return rj2.validator_test(g)
        if name == 'GlobalExceptionHandlerTest':
            return rj2.handler_test(g)
        if name == 'IntegrationClientsTest':
            return rj2.clients_test(g)
    raise rd.Unsupported(f'component {kind!r} ({path}) is not supported by {VERSION}')


def required_properties(plan: dict) -> dict:
    rows = []
    for name, item in sorted(plan['integrations'].items()):
        prefix = item['propertyPrefix']
        host = 'scheme://host:port of the integration (the Sparx connection uses http://ip:port)' if item['hostPlaceholder'] else 'base URL of the integration (the Sparx connection is a relative path)'
        rows += [{'key': f'{prefix}.base-url', 'integration': name, 'note': host, 'suggestedValue': None},
                 {'key': f'{prefix}.connect-timeout', 'integration': name, 'note': 'milliseconds; not specified by Sparx', 'suggestedValue': None},
                 {'key': f'{prefix}.read-timeout', 'integration': name, 'note': 'milliseconds; not specified by Sparx', 'suggestedValue': None}]
        if item['cache']:
            rows.append({'key': f'{prefix}.refresh-cache-ms', 'integration': name, 'note': 'optional; milliseconds; Sparx propRefreshCache', 'suggestedValue': item['cache']['refreshMs']})
    rows.append({'key': 'JWT_SECRET_KEY', 'integration': None, 'note': 'environment variable consumed by security.jwt.secret-key', 'suggestedValue': None})
    for key in ('DB_URL', 'DB_USERNAME', 'DB_PASSWORD'):
        rows.append({'key': key, 'integration': None, 'note': 'archetype baseline datasource variable (spring-boot-starter-data-jpa is a mandatory baseline dependency, D-011/D-012); this service performs no persistence', 'suggestedValue': None})
    return {'schemaVersion': 1, 'note': 'The generator never writes application*.properties values for these keys; define them in the environment or in your local configuration.', 'properties': rows}


def render_project(plan: dict, repo: Path, ws_dir: Path, out_dir: Path, ap) -> tuple:
    g = rj.Gen(plan)
    java, planned = {}, {e['path']: e for e in plan['files']['generate']}
    for path, entry in planned.items():
        if entry['action'] not in ('create', 'update'):
            raise rd.Unsupported(f'{path}: unsupported planned action {entry["action"]!r}')
        java[path] = (entry['componentType'], rd.lf(render_entry(g, plan, entry, repo)))
    assembly = ap.render(plan, repo, ws_dir, out_dir)
    for path, item in assembly['files'].items():
        if path in java:
            raise rd.Unsupported(f'{path}: duplicate materializer and assembler ownership')
        java[path] = ('project-assembly', item['bytes'].decode('utf-8'))
    return java, assembly


def _load_plan(ws, repo, fm):
    plan_file = ws.dir / 'implementation-plan.yml'
    if not plan_file.is_file():
        raise fm.MaterializationError('invalid-plan', 'the workspace has no implementation-plan.yml')
    raw = plan_file.read_bytes()
    plan = yaml.safe_load(raw)
    sha = fm.sha
    svc = plan.get('service') or {}
    if (plan.get('plan') or {}).get('mode') != 'full' or (plan.get('generation') or {}).get('functionalGenerationReady') is not True:
        raise fm.MaterializationError('invalid-plan', 'the plan is not a ready full plan')
    if (plan.get('plan') or {}).get('variant') != VARIANT:
        raise fm.MaterializationError('unsupported', 'the plan is not of the rest-client-v1 variant')
    if svc.get('name') != ws.service or svc.get('outputDirectory') != f'output/{ws.service}':
        raise fm.MaterializationError('invalid-plan', 'the plan belongs to another service or output directory')
    spec = ws.dir / 'service-spec.yml'
    inputs = plan.get('inputs') or {}
    if not spec.is_file() or (inputs.get('serviceSpec') or {}).get('artifactSha256') != sha(spec.read_bytes()):
        raise fm.MaterializationError('stale-plan', 'the plan was not built from the current service-spec of this workspace')
    arch = inputs.get('archetype') or {}
    root = repo / str(arch.get('path'))
    if not root.is_dir() or fm.planner_base.archetype_fingerprint(root) != arch.get('fingerprint'):
        raise fm.MaterializationError('stale-plan', 'the archetype differs from the one used for planning')
    for key, filename in (('generationParameters', 'generation-parameters.yml'), ('planningInput', 'full-planning-input.yml')):
        binding = inputs.get(key)
        artifact = ws.dir / filename
        if not isinstance(binding, dict) or binding.get('path') != f'.factory/{filename}' or not artifact.is_file() or binding.get('sha256') != sha(artifact.read_bytes()):
            raise fm.MaterializationError('stale-plan', f'{filename} is missing or changed since planning')
    for entry in plan['files']['generate']:
        fm.safe_relative(entry['path'])
    from generation_context import load_mapping
    import rest_client_plan
    try:
        expected, parameters = rest_client_plan.artifacts(repo, yaml, ws.dir / 'full-planning-input.yml')
        if plan != expected or parameters != load_mapping(ws.dir / 'generation-parameters.yml'):
            raise ValueError('REST client plan/parameters differ from the current authorized inputs; replan required')
    except (ValueError, KeyError, TypeError) as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    return plan, raw


def materialize(repo: Path, service: str, dry_run: bool = False) -> dict:
    import feasibility_preflight
    feasibility_preflight.enforce(repo, service)
    return _materialize_checked(repo, service, dry_run)


def materialize_unlocked(repo: Path, service: str, dry_run: bool = False, assemble: bool = True) -> dict:
    """Entry point of the typed-backend registry (the caller holds the service lock). Services using the rest-client-v1 plan variant are declared in TYPED_BACKEND_SERVICES."""
    import full_materializer as fm
    if service not in TYPED_BACKEND_SERVICES:
        raise fm.MaterializationError('unsupported', f'{service} is not declared for {VERSION}')
    if not assemble:
        raise fm.MaterializationError('unsupported', 'the rest-client-v1 variant requires full atomic project assembly; partial generation is not supported')
    return _materialize_checked(repo, service, dry_run)


def preflight(repo: Path, service: str, supported_only: bool = False, assemble: bool = True) -> dict:
    """Read-only technical feasibility in the format of feasibility_preflight.evaluate (in-memory dry run; nothing is written)."""
    import hashlib
    import json
    import full_materializer as fm
    from generation_context import load_mapping, resolve_context
    import archetype_contract as ac
    repo = Path(repo).resolve()
    ws = fm.wsm.Workspace(repo, service)
    rows, fingerprints = [], {}
    result = {'schemaVersion': 1, 'service': service, 'profile': None, 'archetype': None, 'inputFingerprints': fingerprints, 'requirements': rows, 'status': 'unknown', 'feasible': False,
              'backend': VERSION, 'limitations': ['Static preview does not prove compilation, tests or remote integration compatibility.',
                                                  'Behavior left unspecified by Sparx is omitted explicitly (see omittedBehavior of the plan).']}

    def add(ident, kind, status, evidence):
        rows.append({'id': str(ident), 'kind': kind, 'required': True, 'status': status, 'evidence': [str(evidence)]})

    for name in ('implementation-plan.yml', 'service-spec.yml', 'sparx-spec.yml', 'generation-parameters.yml', 'full-planning-input.yml', 'service-generation-state.yml', 'openapi-spec.yml',
                 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'consistency/supplemental.yml'):
        path = ws.dir / name
        if path.is_file() and not path.is_symlink():
            fingerprints[name] = fm.sha(path.read_bytes())
    here = Path(__file__).resolve().parent
    for name in ('rest_client_materializer.py', 'rest_client_java.py', 'rest_client_java2.py'):
        fingerprints[f'materialize-full-service/{name}'] = fm.sha((here / name).read_bytes())
    try:
        if supported_only:
            add('partial-generation', 'contract', 'unsupported', 'Partial generation is not supported by the rest-client-v1 variant')
        fm.gate.check_cleared(ws.dir, repo, service)
        add('consistency-gate', 'gate', 'supported', 'Consistency gate CLEARED (recomputed)')
        context = resolve_context(repo, service=service)
        result['archetype'] = Path(context.archetype).as_posix()
        contract = ac.normalize(load_mapping(repo / context.archetype / 'archetype.yml'))
        result['profile'] = contract['profile']
        ac.require_backend(contract)
        plan = load_mapping(ws.dir / 'implementation-plan.yml')
        if (plan.get('plan') or {}).get('profile') != contract['profile']:
            add('profile', 'contract', 'blocked', 'Plan profile disagrees with the explicitly selected archetype')
        for op in plan.get('operations', []):
            add(op['operationId'], 'operation', 'unknown', 'Awaiting whole-backend preview')
        for entry in (plan.get('files') or {}).get('generate', []):
            add(entry['path'], 'component', 'unknown', f'componentType={entry["componentType"]}; awaiting backend preview')
        for omitted in plan.get('omittedBehavior', []):
            result.setdefault('declaredOmissions', []).append({'operationId': omitted['operationId'], 'behavior': omitted['behavior']})
        preview = materialize_unlocked(repo, service, True, assemble) if not supported_only else None
        if preview is not None:
            result['backendPreview'] = {k: preview[k] for k in ('status', 'payloadTreeSha256') if k in preview}
            if preview['status'] != 'complete':
                add('backend-preview', 'behavior', 'unsupported', f'Backend reports {preview["status"]}')
        for row in rows:
            if row['status'] == 'unknown' and row['evidence'][0].startswith(('Awaiting', 'componentType=')) and preview is not None:
                row.update(status='supported', evidence=['Actual backend complete in-memory preview (including provenance and rendering)'])
    except ac.ContractError as error:
        add('profile', 'contract', 'unsupported', error)
    except fm.gate.GateError as error:
        add('consistency-gate', 'gate', 'blocked', error)
    except fm.MaterializationError as error:
        result['failureKind'], result['failureDetails'] = error.kind, error.details
        result['failureMessage'] = str(error).removeprefix(error.kind + ': ')
        status = 'unsupported' if error.kind == 'unsupported' else 'blocked' if error.kind in ('stale-plan', 'protected-files', 'missing-decision') else 'unknown'
        add('backend-validation', 'contract', status, error)
        for item in error.details.get('unsupported', []):
            add(item.get('path', 'backend'), 'component', 'unsupported', item.get('reason', error))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError, yaml.YAMLError) as error:
        add('input-validation', 'contract', 'unknown', f'{type(error).__name__}: {error}')
    statuses = {r['status'] for r in rows}
    result['status'] = next((s for s in ('blocked', 'unsupported', 'unknown') if s in statuses), 'supported')
    result['feasible'] = bool(rows) and result['status'] == 'supported'
    result['runId'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()
    return result


def _materialize_checked(repo: Path, service: str, dry_run: bool = False) -> dict:
    import full_materializer as fm
    fp, gate, wsm, ap = fm.fp, fm.gate, fm.wsm, fm.ap
    repo = Path(repo).resolve()
    ws = wsm.Workspace(repo, service)
    gate.check_cleared(ws.dir, repo, service)
    plan, plan_bytes = _load_plan(ws, repo, fm)
    out_dir = repo / plan['service']['outputDirectory']
    try:
        rendered, assembly = render_project(plan, repo, ws.dir, out_dir, ap)
    except rd.Unsupported as error:
        raise fm.MaterializationError('unsupported', str(error), {'unsupported': [{'path': 'implementation-plan.yml', 'componentType': 'rest-client-variant', 'reason': str(error)}]}) from error
    except ap.AssemblyError as error:
        raise fm.MaterializationError(error.kind, str(error).split(': ', 1)[1], error.details) from error
    except (KeyError, TypeError, IndexError, ValueError, StopIteration) as error:
        raise fm.MaterializationError('invalid-plan', f'cannot render the plan ({type(error).__name__}: {error})') from error
    rendered = {p: v for p, v in rendered.items() if not fp.is_excluded(p)}
    from artifact_integrity import prepare, publish, IntegrityError
    payload = {p: text.encode('utf-8') for p, (_, text) in rendered.items()}
    try:
        to_write, unchanged = prepare(out_dir, ws.dir, payload, reject_obsolete=True)
    except fp.ProtectedFileError as error:
        raise fm.MaterializationError('protected-files', str(error), getattr(error, 'details', {})) from error
    except IntegrityError as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    rows = {p: {'sha256': fm.sha(text.encode('utf-8')), 'action': 'create', 'componentType': ct} for p, (ct, text) in rendered.items()}
    omitted = list(plan.get('omittedBehavior', []))
    manifest = {'schemaVersion': 1, 'materializer': VERSION, 'complete': True, 'service': service,
                'inputs': {'implementationPlanSha256': fm.sha(plan_bytes), 'serviceSpecSha256': fm.sha((ws.dir / 'service-spec.yml').read_bytes()),
                           'archetypeFingerprint': plan['inputs']['archetype']['fingerprint'],
                           'assembly': {'assembler': ap.VERSION, 'parametersSha256': assembly['report']['parametersSha256']}},
                'fileInventory': [{'path': p, **rows[p]} for p in sorted(rows)], 'unsupportedComponents': [], 'omittedBehavior': [{'operationId': o['operationId'], 'behavior': o['behavior']} for o in omitted],
                'payloadTreeSha256': fm.tree_hash({p: r['sha256'] for p, r in rows.items()})}
    dump = lambda v: yaml.safe_dump(v, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
    manifest_bytes = dump(manifest)
    report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'profile': plan['plan']['profile'], 'variant': VARIANT, 'status': 'complete',
              'scope': plan['plan']['scope'], 'written': sorted(to_write), 'unchanged': sorted(unchanged), 'excludedUntouched': ['src/main/resources/application*.properties'],
              'omittedBehavior': omitted, 'unsupported': [], 'payloadTreeSha256': manifest['payloadTreeSha256'], 'manifestSha256': fm.sha(manifest_bytes), 'dryRun': dry_run,
              'assembly': assembly['report'],
              'validation': {'maven': 'not-run', 'compilation': 'not-verified', 'tests': 'not-run', 'checkstyle': 'unverified', 'jacoco': 'not-verified'}}
    if dry_run:
        return report
    publish(out_dir, ws.dir, payload, manifest_bytes)
    for rel, data in (assembly.get('createOnly') or {}).items():
        target = out_dir / rel
        if not target.exists():
            fm.write_atomic(target, data)
    fm.write_atomic(ws.dir / 'assumptions-register.yml', dump({'schemaVersion': 1, 'service': service, 'materializer': VERSION, 'assumptions': plan.get('assumptions', []),
                                                                 'omittedBehavior': omitted}))
    fm.write_atomic(ws.dir / 'required-properties.yml', dump(required_properties(plan)))
    fm.write_atomic(ws.dir / fm.REPORT, dump(report))
    return report
