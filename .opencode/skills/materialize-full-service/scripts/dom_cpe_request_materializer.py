"""Deterministic materializer of the dom-cpeRequest service (multi-entity JPA profile of claro-spring-ms).

The FULL planner/materializer pair supports a single-entity, single-search service. dom-cpeRequest needs four entities, three searches, multi-table
writes and richer write responses, so its Java is produced from the typed model in dom_cpe_request_java.py / dom_cpe_request_tests.py, with the same
controls as full_materializer: consistency gate recomputed first, archetype assembly through assemble_project.render, file protection and the
per-service lock through artifact_integrity, hashed manifest written last. Same inputs => identical bytes (UTF-8, LF, ASCII Java).

Usage: python dom_cpe_request_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import argparse
import hashlib
import sys
import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'plan-service-implementation' / 'scripts'))
import assemble_project as ap  # noqa: E402
import consistency_gate as gate  # noqa: E402
import file_protection as fp  # noqa: E402
import workspace as wsm  # noqa: E402
import build_implementation_plan as planner_base  # noqa: E402
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_tests as dt  # noqa: E402

VERSION = 'dom-cpe-request-materializer-1'
MANIFEST = '.generation-manifest.yml'
PACKAGE = 'com.claro.dom.cperequest'
APPLICATION_CLASS = 'DomCpeRequestApplication'
MARKER = '    // ================= ACTIVIDADES (LOGS) ================='
GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py']
PARAMETERS = {'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'project_version': '1.0.0-SNAPSHOT',
              'application_class': APPLICATION_CLASS, 'application_log_level': 'INFO', 'corporate_logger_level': 'INFO', 'http_log_level': 'INFO', 'root_log_level': 'INFO',
              'log_time_zone': 'UTC', 'jwt_roles_claim': 'roles', 'java_version': '21', 'spring_boot_version': '3.4.1'}
ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.dom.cperequest and application class DomCpeRequestApplication are technical choices; no source defines them.'),
    ('A-02', 'All tables are mapped in schema FACEL (Sparx qualifies EPDREQUEST/EPDQUERY/EPDQUERYSTATUS as FACEL.*; the POST/GET text omits the schema).'),
    ('A-03', 'Primary keys use GenerationType.IDENTITY (reference convention); Sparx documents RETURNING ID INTO, so the real key generator must be verified.'),
    ('A-04', 'EPDREQUESTHIST is mapped only to columns that exist in its Sparx table definition (EA2072-2074 data definitions) AND appear in the Sparx INSERT list; '
             'the INSERT also lists SERIES, CORRELATIVE, UNIQUEREFERENCECOD, POINTOFSALE, PLOTSOVOS, DOCUMENTTYPE, DOCUMENTNUMBER, which the table definition lacks.'),
    ('A-05', 'The history insert runs in its own transaction after the request insert commits and its failure is logged and ignored (Sparx: continue the process).'),
    ('A-06', 'Gate decisions delegated by the user (swagger-governs): no 401/403 handling is generated; only statuses declared by the OpenAPI are emitted.'),
    ('A-07', 'No rule produces 409 except a database unique violation (ORA-00001), translated to 409; allowed status transitions are undefined, so none are validated.'),
    ('A-08', 'PATCH /emisiones/{id}: the three URLs are required unless the new status is 7 (rejected); incomplete URLs are a 400 raised before any write; '
             'no idempotency criterion exists for retries (each call inserts an EPDQUERY row).'),
    ('A-09', 'GET /emisiones/estado/{state} without rows returns 200 with an empty list (Sparx prose) although the OpenAPI also declares 404; nextAfterId on every item is the id of the last row.'),
    ('A-10', 'Pagination defaults come from api.pagination.defaultSize / maxSize with in-code fallbacks 50 / 100 because application.properties is never read or written.'),
    ('A-11', 'GET /cpe-requests compares UNIQUEREFERENCECOD with the decimal text of the integer referenceCode query parameter (OpenAPI integer vs Sparx varchar column).'),
    ('A-12', 'GET /emisiones/{id} maps referenceCode from UNIQUEREFERENCECOD (Sparx names REFERENCECODE, a column absent from the table).'),
    ('A-13', 'Audit dates use an injectable Clock (LocalDateTime.now(clock)); the status catalog is enabled when EPDQUERYSTATUS.STATUS = 1 and status 7 is the rejected status.'),
]


class MaterializationError(RuntimeError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plan_for(service, repo, archetype):
    return {'service': {'name': service, 'package': PACKAGE, 'packagePath': PARAMETERS['base_package_path'], 'groupId': PACKAGE, 'projectVersion': '1.0.0-SNAPSHOT',
                        'javaVersion': '21', 'springBootVersion': '3.4.1', 'outputDirectory': f'output/{service}', 'applicationClass': APPLICATION_CLASS},
            'inputs': {'archetype': {'path': archetype, 'fingerprint': planner_base.archetype_fingerprint(repo / archetype)}}, 'files': {'generate': []}, 'readiness': {}}


def render(repo, service, archetype):
    ws = wsm.Workspace(repo, service)
    params = ws.dir / 'generation-parameters.yml'
    parameters_doc = {'version': 2, 'mode': 'full', 'service': service, 'values': {**PARAMETERS, 'service_name': wsm.technical_identifier(service), 'artifact_id': wsm.technical_identifier(service)}}
    parameters_bytes = yaml.safe_dump(parameters_doc, sort_keys=False, allow_unicode=True).encode('utf-8')
    if params.is_file() and yaml.safe_load(params.read_bytes()).get('values') != parameters_doc['values']:
        raise MaterializationError('generation-parameters.yml exists with different values; resolve it explicitly (never overwritten)')
    plan = plan_for(service, repo, archetype)
    out_dir = repo / plan['service']['outputDirectory']
    try:
        assembly = ap.render(plan, repo, ws.dir, out_dir) if params.is_file() else _render_with(plan, repo, ws, out_dir, parameters_bytes)
    except ap.AssemblyError as error:
        raise MaterializationError(f'{error.kind}: {error}') from error
    payload = {path: item['bytes'] for path, item in assembly['files'].items()}
    constants = f'src/main/java/{PARAMETERS["base_package_path"]}/utils/ConstanApi.java'
    if constants not in payload:
        raise MaterializationError('the archetype ConstanApi template was not assembled')
    text = payload[constants].decode('utf-8')
    if MARKER not in text:
        raise MaterializationError('ConstanApi has no ACTIVIDADES (LOGS) marker')
    payload[constants] = text.replace(MARKER, MARKER + '\n' + dj.activity_constants() + '\n', 1).encode('utf-8')
    generated = {**dj.build_main(PACKAGE), **dt.build_tests(PACKAGE)}
    for path, content in generated.items():
        if path in payload:
            raise MaterializationError(f'{path}: duplicate generator and assembler ownership')
        payload[path] = content.encode('utf-8')
    return ws, out_dir, plan, assembly, payload, parameters_bytes


def _render_with(plan, repo, ws, out_dir, parameters_bytes):
    """First run: the parameters file does not exist yet; render against an in-memory copy and persist it only when the write proceeds."""
    original = ap.resolve_parameters

    def supplied(plan_doc, ws_dir):
        values, provenance = original(plan_doc, ws_dir)
        data = yaml.safe_load(parameters_bytes)['values']
        for name, value in data.items():
            values.setdefault(name, value)
            provenance.setdefault(name, 'dom_cpe_request_materializer PARAMETERS (technical choices, assumptions A-01)')
        return values, provenance
    ap.resolve_parameters = supplied
    try:
        return ap.render(plan, repo, ws.dir, out_dir)
    finally:
        ap.resolve_parameters = original


def materialize(repo, service, dry_run=False, archetype='archetypes/claro-spring-ms/v1.0.1'):
    from artifact_integrity import service_lock, prepare, publish, protected, write_atomic, IntegrityError
    repo = Path(repo).resolve()
    with service_lock(repo, service):
        ws = wsm.Workspace(repo, service)
        gate.check_cleared(ws.dir, repo, service)
        ws, out_dir, plan, assembly, payload, parameters_bytes = render(repo, service, archetype)
        try:
            to_write, unchanged = prepare(out_dir, ws.dir, payload)
        except fp.ProtectedFileError as error:
            raise MaterializationError(f'protected-files: {error}') from error
        except IntegrityError as error:
            raise MaterializationError(f'integrity: {error}') from error
        previous = yaml.safe_load((out_dir / MANIFEST).read_bytes()) if (out_dir / MANIFEST).is_file() else {}
        rows = {r['path']: {k: v for k, v in r.items() if k != 'path'} for r in (previous or {}).get('fileInventory', []) if not protected(r['path']) and (out_dir / r['path']).is_file()}
        for path, data in payload.items():
            group = 'project-assembly' if path in assembly['files'] else 'service-java'
            rows[path] = {'sha256': sha(data), 'action': 'create', 'componentType': group}
        tree = sha('\n'.join(f'{p}\0{r["sha256"]}' for p, r in sorted(rows.items())).encode('utf-8'))
        generator = sha(b''.join((HERE / name).read_bytes() for name in GENERATOR_FILES))
        manifest = {'schemaVersion': 1, 'materializer': VERSION, 'complete': True, 'service': service,
                    'inputs': {'generatorSha256': generator, 'archetypeFingerprint': plan['inputs']['archetype']['fingerprint'],
                               'assembly': {'assembler': ap.VERSION, 'parametersSha256': assembly['report']['parametersSha256']}},
                    'fileInventory': [{'path': p, **rows[p]} for p in sorted(rows)], 'unsupportedComponents': [], 'payloadTreeSha256': tree}
        manifest_bytes = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
        report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'status': 'complete', 'written': sorted(to_write), 'unchanged': sorted(unchanged),
                  'payloadTreeSha256': tree, 'manifestSha256': sha(manifest_bytes), 'dryRun': dry_run, 'assembly': assembly['report'],
                  'verification': {'maven': 'not-executed', 'checkstyle': 'unverified', 'jacoco': 'not-verified', 'note': 'static generation only; no compilation, no database, no deployment'}}
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('service')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--archetype', default='archetypes/claro-spring-ms/v1.0.1')
    args = parser.parse_args(argv)
    try:
        report = materialize(Path.cwd(), args.service, args.dry_run, args.archetype)
    except (MaterializationError, gate.GateError, fp.ProtectedFileError, wsm.WorkspaceError) as error:
        print(f'dom_cpe_request_materializer: {error}', file=sys.stderr)
        return 3
    print(yaml.safe_dump({k: report.get(k) for k in ('status', 'written', 'unchanged', 'payloadTreeSha256', 'verification')}, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
