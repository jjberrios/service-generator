"""Deterministic typed-model materializer of the financingAgreement service (multi-table Spring Data JPA profile of claro-spring-ms/1.0.1).

The FULL planner/materializer pair supports a single-table, single-search service. financingAgreement exposes eight operations over six tables (financing and its
history, installments and their history, state catalog, request type catalog) with transactional DML, so its Java is produced from the typed model in
financing_agreement_java.py / financing_agreement_tests.py, with the controls of dom_cpe_request_materializer: consistency gate recomputed first, archetype assembly
through assemble_project.render, file protection and the per-service lock through artifact_integrity, hashed manifest written last. Same inputs => identical bytes.

Behaviour comes only from the workspace evidence. Before anything is rendered `verify_evidence` checks the typed model against the workspace OpenAPI normalization and the
authoritative Sparx detail (operations, schema properties, activities, tables/columns, Sparx property values); any drift stops the generation (nothing is written).

Usage: python financing_agreement_materializer.py <service> [--dry-run]   (also reached through `workspace_cli.py preflight|materialize financingAgreement`)
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import hashlib
import json
import sys
import types
import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'plan-service-implementation' / 'scripts'))
import consistency_gate as gate  # noqa: E402
import file_protection as fp  # noqa: E402
import workspace as wsm  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402
import financing_agreement_java as fj  # noqa: E402
import financing_agreement_tests as ft  # noqa: E402

TYPED_BACKEND_SERVICES = ('financingAgreement',)
VERSION = 'financing-agreement-materializer-1'
GENERATOR_FILES = ['dom_cpe_request_java.py', 'financing_agreement_java.py', 'financing_agreement_tests.py', 'dom_cpe_request_materializer.py', 'financing_agreement_materializer.py']
PACKAGE = fj.PACKAGE
EXPECTED_PROPERTIES = {'propEstadoFinanConfirmada': '2', 'propEstadoCuotaPendiente': '1', 'propEstadoCuotaErrorOac': '7', 'propTipoReFinanciamiento': '3',
                       'propEstadoConfirmado': '2', 'propEstadoTerminado': '5'}

ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.financingagreement and application class FinancingAgreementApplication are technical choices; no source defines them.'),
    ('A-02', 'Tables are mapped without schema (Sparx names the tables unqualified). FNNC_CODIGO and FNNC_CODIGOHIST use GenerationType.IDENTITY (Sparx names the output V_FNNC_CODIGO but not the key '
             'generator, so the real mechanism must be verified). Entities of CUST_CUOTA, CUST_CUOTA_HIST and CUST_TIPOSOLICITUD map only the columns the operations use.'),
    ('A-03', 'Sparx documents the DML through V_* parameters of an unspecified statement; it is implemented with Spring Data JPA over the evidenced table columns. Name differences are resolved to '
             'the table definition: V_FNNC_LINE -> FNNC_LINEA, FNNC_DOCUMENTOSAP -> FNNC_DOCUMENTOSAPID.'),
    ('A-04', 'Transactions: POST (financing + history) and PATCH (update + history) are each one transaction rolled back on any failure (Sparx states rollback for PATCH; a history failure in POST '
             'is not specified, the atomic option is the conservative one). DELETE runs the four deletes in one transaction, children first: CUST_CUOTA_HIST, CUST_CUOTA, CUST_FINANCIAMIENTO_HIST, '
             'CUST_FINANCIAMIENTO (Sparx lists the four tables without an order; the foreign keys of the table definitions dictate it).'),
    ('A-05', 'Audit columns: FNNC_USUARIOCREACION = x-user-id and FNNC_FECHACREACION = injectable Clock (never SYSDATE). PATCH sets FNNC_USUARIOULTIMAACT = x-user-id (V_USER_ID) and '
             'FNNC_FECHAULTIMAACT = Clock (Sparx lists only the user; the date is its audit pair). FNNC_SISTEMA = x-app-id.'),
    ('A-06', 'PATCH is a partial update: only informed (non-null) fields are written, an empty string counts as informed. The history row is a snapshot of the updated financing (Sparx maps '
             'only agreementCodeId and the user for it) with its own generated FNNC_CODIGOHIST.'),
    ('A-07', 'PATCH of an unknown agreementCodeId answers 400 IDF101 naming agreementCodeId (the OpenAPI declares no 404 for PATCH and Sparx is silent); no history is written.'),
    ('A-08', 'DELETE does not check existence: Sparx ends with IDF0 whenever the statement succeeds and the OpenAPI declares no 404. FKs not listed by Sparx (CUST_SOLICITUD, CUST_CONCILIACION, '
             'FNNC_CODIGOORIGINAL children) are not cleaned; a constraint violation is reported as 500 IDT3.'),
    ('A-09', 'Validation is exactly the Sparx/OpenAPI rules: required fields -> IDF101, isClient in S/N -> IDF106, quoteCycle yyyy-MM-dd -> IDF113, date ranges IDF126/IDF127, processDate IDF130, '
             'notification dates IDF131. A blank string counts as not informed for isClient, quoteCycle and sapSentDate. No length checks (the contract declares none; an oversize value fails in the database as 500).'),
    ('A-10', 'sapSentDate (OpenAPI date-time, Sparx date) accepts yyyy-MM-dd\'T\'HH:mm:ssZ, ISO offset or local date-time, converted to the server zone; anything else is 400 IDF101 (sapSentDate). '
             'Date-times in responses use yyyy-MM-dd\'T\'HH:mm:ssZ in the server zone (the OpenAPI example format); quoteCycle uses yyyy-MM-dd.'),
    ('A-11', 'search: equality filters on the informed parameters; FNNC_FECHACREACION in [dateBegin 00:00, dateEnd + 1 day 00:00); ordered by FNNC_CODIGO ascending; an unparseable dateBegin/dateEnd is '
             '400 IDF101 (no Sparx code); IDF127 applies when dateEnd is after dateBegin + 1 month unless documentNumber or saleOrder is informed. STFN_VALOR and TPSL_VALOR come from the catalog tables.'),
    ('A-12', 'search: hasOverduePayments is accepted (OpenAPI) but NOT applied: Sparx has no input mapping or semantics for it and its installment-state rule would have to be invented. GAP.'),
    ('A-13', 'state: all rows of CUST_ESTADOFINANCIAMIENTO ordered by STFN_CODIGO, active or not (Sparx has no filter); empty -> 404 IDF302.'),
    ('A-14', 'numberOfRefinancings: clientCode (OpenAPI integer, column VARCHAR2) is compared as decimal text; periodMonths is a non-negative integer (otherwise 400 IDF101). Active = type '
             'propTipoReFinanciamiento and state propEstadoConfirmado; completed = type propTipoReFinanciamiento, state propEstadoTerminado and FNNC_FECHACREACION in '
             '[processDate - periodMonths months, processDate] (the date column is inferred from index IDX_FIN_REFIN_VALIDATION). Aggregates always return a row, so the answer is 200 (zero counts included) '
             'and IDF302 is unreachable.'),
    ('A-15', 'notification-candidates: requestTypeIds is a comma separated list of integers (else 400 IDF101). Pending = state propEstadoFinanConfirmada with an installment in state propEstadoCuotaPendiente '
             'created in [dateBegin, dateEnd] (window column inferred from index IDX_FIN_BATCH_NOTIFICACION); errors = same state with an installment in state propEstadoCuotaErrorOac and no date window '
             '(Sparx ACT 3 has no date input). Sparx sequence kept literally: an empty pending list ends 404 IDF302 and so does an empty error list. Consolidation: pendings (isRetry 0) then errors '
             '(isRetry 1), no de-duplication. RISK: the endpoint answers 404 whenever either list is empty.'),
    ('A-16', 'The Sparx properties (propEstado..., propTipo...) are read with @Value and the Sparx names, using the values Sparx states as in-code defaults, because application*.properties is never read or written.'),
    ('A-17', 'Gate decisions delegated by the user (swagger-governs): only the statuses declared by the OpenAPI are emitted (201/200 and 400/404/500/503/504); no 401/403 handling. Error bodies follow the '
             'OpenAPI examples (message FINANCINGAGREEMENT_SERVICE_ERROR); [SERVICE_NAME] is FINANDB (Sparx lane) and [ERROR_DETAIL] a fixed generic text, never exception text.'),
    ('A-18', 'NUMBER(9,4) columns are BigDecimal in the entities and double in the API; DATE columns are LocalDate (FNNC_CICLOCUOTA) or LocalDateTime; ids are Long, catalog codes Integer.'),
]


def _fm():
    import full_materializer as fm
    return fm


def generator_sha():
    return hashlib.sha256(b''.join((HERE / name).read_bytes() for name in GENERATOR_FILES)).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return yaml.safe_load(Path(path).read_bytes()) or {}


# ----------------------------------------------------------------------------------------------------------------------------- evidence
def verify_evidence(ws_dir):
    """Typed model vs. workspace evidence. Returns the list of discrepancies (empty = the model is exactly what the sources say)."""
    ws_dir = Path(ws_dir)
    problems = []
    openapi, detail = load(ws_dir / 'openapi-spec.yml'), load(ws_dir / 'sparx-authoritative-endpoint-detail.yml')
    modeled = {(verb.upper(), path): op for op, verb, path, *_ in fj.OPERATIONS}
    declared = {(o.get('method'), o.get('path')): o.get('operationId') for o in openapi.get('operations') or []}
    sparx = {(o.get('method'), o.get('path')): o for o in detail.get('operations') or [] if o.get('status') == 'active'}
    if set(declared) != set(modeled):
        problems.append(f'OpenAPI operations differ from the model: {sorted(set(declared) ^ set(modeled))}')
    if set(sparx) != set(modeled):
        problems.append(f'active Sparx operations differ from the model: {sorted(set(sparx) ^ set(modeled))}')
    for key, op in modeled.items():
        ident = declared.get(key)
        if ident and ident[:1].lower() + ident[1:] != op:
            problems.append(f'operationId {ident} differs from the modeled {op}')
    titles = {a['activity']['name'] for o in sparx.values() for a in o.get('activities') or []}
    normalized = {(t.split('. ', 1)[1] if t[:1].isdigit() and '. ' in t else t).lower() for t in titles}
    modeled_titles = {t.lower() for _, t, _ in fj.ACTIVITY_TITLES}
    if normalized != modeled_titles:
        problems.append(f'Sparx activities differ from the modeled ones: {sorted(normalized ^ modeled_titles)}')
    schemas = (openapi.get('components') or {}).get('schemas') or {}

    def check_schema(name, fields):
        props = set((schemas.get(name) or {}).get('properties') or {})
        if props != set(fields):
            problems.append(f'schema {name}: contract properties {sorted(props ^ set(fields))} differ from the model')

    check_schema('CreateFinancingRequest', [n for n, *_ in fj.FIELDS])
    check_schema('UpdateFinancingRequest', ['agreementCodeId'] + fj.UPDATE_FIELDS)
    check_schema('FinancingDto', ['agreementCodeId', 'system'] + [n for n, *_ in fj.FIELDS] + ['createdBy', 'createdAt', 'updatedBy', 'updatedAt'])
    for name, fields in fj.DATA_DTOS.items():
        check_schema(name, [n for _, n in fields])
    for name in fj.ENVELOPES:
        check_schema(name, ['code', 'message', 'data'])
    tables = {d['identity']['name']: {c['column'] for c in d.get('columns') or []} for d in detail.get('dataDefinitions') or []}
    for cls, table in fj.ENTITY_TABLES.items():
        if table not in tables:
            problems.append(f'table {table} has no data definition in the Sparx evidence')
            continue
        for column in (c for _, _, c, _ in fj.entity_columns(cls)):
            if column not in tables[table]:
                problems.append(f'column {table}.{column} is not in the Sparx table definition')
    sparx_props = {}
    for o in sparx.values():
        for a in o.get('activities') or []:
            for line in ((a.get('normalized') or {}).get('variablesProperties') or {}).get('lines') or []:
                text = str(line.get('text', ''))
                if '=' in text and text.strip().startswith('prop'):
                    key, value = (part.strip() for part in text.split('=', 1))
                    sparx_props.setdefault(key, set()).add(value)
    for key, value in EXPECTED_PROPERTIES.items():
        if sparx_props.get(key) != {value}:
            problems.append(f'Sparx property {key} is {sorted(sparx_props.get(key, []))}, the model uses {value}')
    insert = next((a for o in sparx.values() for a in o.get('activities') or [] if ((a.get('normalized') or {}).get('descriptor') or {}).get('name') == 'CUST_FINANCIAMIENTO'
                   and a['normalized']['descriptor'].get('operation') == 'INSERT'), None)
    if insert:
        inputs = {r.get('input') for r in (insert['normalized'].get('input') or {}).get('rows') or []}
        expected = {n for n, *_ in fj.FIELDS} | {'x-app-id', 'x-user-id', 'SYSDATE'}
        if inputs != expected:
            problems.append(f'POST INSERT inputs differ from the model: {sorted(inputs ^ expected)}')
    else:
        problems.append('Sparx POST INSERT activity on CUST_FINANCIAMIENTO not found')
    return problems


# ----------------------------------------------------------------------------------------------------------------------------- rendering
@contextmanager
def configured():
    keys = ('PACKAGE', 'APPLICATION_CLASS', 'ASSUMPTIONS', 'VERSION', 'PARAMETERS', 'GENERATOR_FILES', 'dj', 'dt')
    saved = {k: getattr(dm, k) for k in keys}
    shim = types.SimpleNamespace(build_main=fj.build_main, build_tests=ft.build_tests, activity_constants=fj.activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, fj.APPLICATION_CLASS, ASSUMPTIONS, VERSION
    dm.PARAMETERS = {**saved['PARAMETERS'], 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': fj.APPLICATION_CLASS}
    dm.GENERATOR_FILES = GENERATOR_FILES
    dm.dj, dm.dt = shim, shim
    try:
        yield
    finally:
        for key, value in saved.items():
            setattr(dm, key, value)


def archetype_of(repo, service):
    import archetype_contract as ac
    from generation_context import resolve_context
    fm = _fm()
    context = resolve_context(repo, service=service)
    contract = ac.normalize(load(repo / context.archetype / 'archetype.yml'))
    if contract['profile'] != ac.LEGACY_JPA or contract['identity']['name'] != 'claro-spring-ms':
        raise fm.MaterializationError('unsupported', f'the financingAgreement backend supports the claro-spring-ms Spring Data JPA profile only, not {contract["identity"]} / {contract["profile"]}')
    ac.require_backend(contract)
    return Path(context.archetype).as_posix()


def _render(repo, service, assemble):
    fm = _fm()
    if not assemble:
        raise fm.MaterializationError('unsupported', 'the financingAgreement backend requires full atomic project assembly; partial generation is not supported')
    ws = wsm.Workspace(repo, service)
    problems = verify_evidence(ws.dir)
    if problems:
        raise fm.MaterializationError('invalid-plan', 'the typed model does not match the workspace evidence; nothing was written', {'evidenceMismatch': problems})
    archetype = archetype_of(repo, service)
    with configured():
        try:
            return dm.render(repo, service, archetype)
        except dm.MaterializationError as error:
            raise fm.MaterializationError('missing-parameter' if 'parameters' in str(error) else 'invalid-plan', str(error)) from error


def materialize_unlocked(repo, service, dry_run=False, assemble=True):
    """Whole materialization without taking the service lock (the caller holds it). Raises full_materializer.MaterializationError."""
    from artifact_integrity import prepare, publish, protected, write_atomic, IntegrityError
    fm = _fm()
    repo = Path(repo).resolve()
    if service not in TYPED_BACKEND_SERVICES:
        raise fm.MaterializationError('unsupported', f'{service} has no typed backend in {VERSION}')
    gate.check_cleared(wsm.Workspace(repo, service).dir, repo, service)
    ws, out_dir, plan, assembly, payload, parameters_bytes = _render(repo, service, assemble)
    try:
        to_write, unchanged = prepare(out_dir, ws.dir, payload)
    except fp.ProtectedFileError as error:
        raise fm.MaterializationError('protected-files', str(error), getattr(error, 'details', {})) from error
    except IntegrityError as error:
        raise fm.MaterializationError('integrity', str(error)) from error
    previous = load(out_dir / dm.MANIFEST) if (out_dir / dm.MANIFEST).is_file() else {}
    rows = {r['path']: {k: v for k, v in r.items() if k != 'path'} for r in (previous or {}).get('fileInventory', []) if not protected(r['path']) and (out_dir / r['path']).is_file()}
    for path, data in payload.items():
        rows[path] = {'sha256': sha(data), 'action': 'create', 'componentType': 'project-assembly' if path in assembly['files'] else 'service-java'}
    tree = sha(''.join(f'{p}\0{r["sha256"]}\n' for p, r in sorted(rows.items())).encode('utf-8'))      # same formula as full_materializer.tree_hash
    generator = sha(b''.join((HERE / name).read_bytes() for name in GENERATOR_FILES))
    manifest = {'schemaVersion': 1, 'materializer': VERSION, 'complete': True, 'service': service,
                'inputs': {'generatorSha256': generator, 'archetypeFingerprint': plan['inputs']['archetype']['fingerprint'],
                           'openapiSpecSha256': sha((ws.dir / 'openapi-spec.yml').read_bytes()), 'sparxEndpointDetailSha256': sha((ws.dir / 'sparx-authoritative-endpoint-detail.yml').read_bytes()),
                           'assembly': {'assembler': dm.ap.VERSION, 'parametersSha256': assembly['report']['parametersSha256']}},
                'fileInventory': [{'path': p, **rows[p]} for p in sorted(rows)], 'unsupportedComponents': [], 'payloadTreeSha256': tree}
    manifest_bytes = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
    report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'status': 'complete', 'written': sorted(to_write), 'unchanged': sorted(unchanged),
              'payloadTreeSha256': tree, 'manifestSha256': sha(manifest_bytes), 'dryRun': dry_run, 'assembly': assembly['report'],
              'evidenceVerification': {'status': 'matches-workspace-evidence', 'checks': ['operations', 'schemas', 'sparx-activities', 'table-columns', 'sparx-properties', 'insert-inputs']},
              'verification': {'maven': 'not-executed', 'checkstyle': 'unverified', 'jacoco': 'not-verified',
                               'note': 'static generation only; no compilation, no database, no deployment'}}
    if dry_run:
        return report
    publish(out_dir, ws.dir, payload, manifest_bytes)
    for rel, data in (assembly.get('createOnly') or {}).items():
        if not (out_dir / rel).exists():
            write_atomic(out_dir / rel, data)
    if not (ws.dir / 'generation-parameters.yml').is_file():
        write_atomic(ws.dir / 'generation-parameters.yml', parameters_bytes)
    register = {'schemaVersion': 1, 'service': service, 'kind': 'agent-decisions-under-user-delegation',
                'assumptions': [{'id': i, 'statement': s, 'status': 'assumption-not-confirmed-by-sources'} for i, s in ASSUMPTIONS]}
    write_atomic(ws.dir / 'assumptions-register.yml', yaml.safe_dump(register, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    write_atomic(ws.dir / 'materialization-report.yml', yaml.safe_dump(report, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    return report


def materialize(repo, service, dry_run=False, assemble=True):
    from artifact_integrity import service_lock, IntegrityError
    fm = _fm()
    repo = Path(repo).resolve()
    gate.check_cleared(wsm.Workspace(repo, service).dir, repo, service)
    try:
        with service_lock(repo, service):
            return materialize_unlocked(repo, service, dry_run, assemble)
    except IntegrityError as error:
        raise fm.MaterializationError('integrity', str(error)) from error


# ----------------------------------------------------------------------------------------------------------------------------- preflight
def preflight(repo, service, supported_only=False, assemble=True):
    """Read-only technical feasibility in the format of feasibility_preflight.evaluate (backend in-memory dry-run, nothing written)."""
    fm = _fm()
    repo = Path(repo).resolve()
    ws = wsm.Workspace(repo, service)
    rows, fingerprints = [], {}
    result = {'schemaVersion': 1, 'service': service, 'profile': None, 'archetype': None, 'inputFingerprints': fingerprints, 'requirements': rows, 'status': 'unknown', 'feasible': False,
              'backend': VERSION, 'limitations': ['Static preview does not prove compilation, tests, database or remote integration compatibility.',
                                                  'Typed-model backend: behaviour comes from the verified model, not from a consolidated service-spec / implementation-plan.']}

    def add(ident, kind, status, evidence):
        rows.append({'id': str(ident), 'kind': kind, 'required': True, 'status': status, 'evidence': [str(evidence)]})

    for name in ('service-generation-state.yml', 'openapi-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'generation-parameters.yml',
                 'consistency/supplemental.yml'):
        path = ws.dir / name
        if path.is_file() and not path.is_symlink():
            fingerprints[name] = sha(path.read_bytes())
    for name in GENERATOR_FILES:
        fingerprints[f'materialize-full-service/{name}'] = sha((HERE / name).read_bytes())
    try:
        if supported_only:
            add('partial-generation', 'contract', 'unsupported', 'Partial generation is not supported by the typed backend')
        gate.check_cleared(ws.dir, repo, service)
        add('consistency-gate', 'gate', 'supported', 'Consistency gate CLEARED (recomputed)')
        archetype = archetype_of(repo, service)
        result['archetype'] = archetype
        import archetype_contract as ac
        result['profile'] = ac.normalize(load(repo / archetype / 'archetype.yml'))['profile']
        problems = verify_evidence(ws.dir)
        for op, verb, path, *_ in fj.OPERATIONS:
            add(op, 'operation', 'blocked' if problems else 'supported', f'{verb.upper()} {path}: ' + ('; '.join(problems)[:300] if problems else 'typed model matches OpenAPI and authoritative Sparx'))
        if problems:
            add('evidence-verification', 'contract', 'blocked', '; '.join(problems)[:500])
        else:
            add('evidence-verification', 'contract', 'supported', 'operations, schemas, activities, table columns and Sparx properties verified')
            preview = materialize_unlocked(repo, service, True, assemble)
            result['backendPreview'] = {k: preview[k] for k in ('status', 'payloadTreeSha256') if k in preview}
            for path in preview['written'] + preview['unchanged']:
                add(path, 'component', 'supported', 'Actual backend complete in-memory preview (including provenance and rendering)')
            if preview['status'] != 'complete':
                add('backend-preview', 'behavior', 'unsupported', f'Backend reports {preview["status"]}')
    except gate.GateError as error:
        add('consistency-gate', 'gate', 'blocked', error)
    except fm.MaterializationError as error:
        result['failureKind'], result['failureDetails'] = error.kind, error.details
        result['failureMessage'] = str(error).removeprefix(error.kind + ': ')
        add('backend-validation', 'contract', 'unsupported' if error.kind == 'unsupported' else 'blocked', error)
    except Exception as error:  # noqa: BLE001  (the report must always be produced)
        add('input-validation', 'contract', 'unknown', f'{type(error).__name__}: {error}')
    statuses = {r['status'] for r in rows}
    result['status'] = next((s for s in ('blocked', 'unsupported', 'unknown') if s in statuses), 'supported')
    result['feasible'] = bool(rows) and result['status'] == 'supported'
    result['runId'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('service')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    fm = _fm()
    try:
        report = materialize(Path.cwd(), args.service, args.dry_run)
    except (fm.MaterializationError, gate.GateError, fp.ProtectedFileError, wsm.WorkspaceError) as error:
        print(f'financing_agreement_materializer: {error}', file=sys.stderr)
        print(yaml.safe_dump(getattr(error, 'details', {}), allow_unicode=True), file=sys.stderr)
        return 3
    print(yaml.safe_dump({k: report.get(k) for k in ('status', 'written', 'unchanged', 'payloadTreeSha256', 'verification')}, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
