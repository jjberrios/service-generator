"""Mandatory Sparx vs Swagger consistency gate (blocking) for the service generation pipeline.

The gate REUSES the comparison logic of the audit-sparx-swagger skill (compare_sparx_swagger.build_registry, source_currency); it adds no
comparison rules of its own. It consumes the pipeline artifacts of the service workspace (openapi-spec.yml, sparx-target-authority.yml,
sparx-authoritative-endpoint-detail.yml) so analyzers are not run twice.

Blocking rule (no automatic choice between sources, no invented behavior):
  - every verified contradiction and every documental difference of the audit blocks;
  - unverified items that leave behavior unspecified (`comportamiento-no-especificado`) or pending (`verificacion-pendiente`) block;
  - internal-to-one-source issues, non comparable sources and discarded false positives do not block.
A blocking item is released only by an approved human resolution bound to the exact content of the finding (fingerprint). When the
finding changes (sources changed) the resolution no longer applies. After everything is resolved the user must authorize resuming; that
authorization is bound to the hash of the evaluation, so any later change invalidates it.

`check_cleared` recomputes everything from the workspace files (it never trusts a stored status), so no alternative path can skip the gate.
Statuses: NO_AUDIT, SEMANTIC_REVIEW_PENDING, BLOCKED_BY_INCONSISTENCIES, AWAITING_AUTHORIZATION, CLEARED.
"""
from pathlib import Path
import datetime
import hashlib
import json
import sys
import tempfile
import yaml

AUDIT_SCRIPTS = Path(__file__).resolve().parents[2] / 'audit-sparx-swagger' / 'scripts'
sys.path.insert(0, str(AUDIT_SCRIPTS))
import compare_sparx_swagger as cmp  # noqa: E402
import source_currency as currency  # noqa: E402

NO_AUDIT = 'NO_AUDIT'
SEMANTIC_REVIEW_PENDING = 'SEMANTIC_REVIEW_PENDING'
BLOCKED = 'BLOCKED_BY_INCONSISTENCIES'
AWAITING_AUTHORIZATION = 'AWAITING_AUTHORIZATION'
CLEARED = 'CLEARED'

BLOCKING_UNVERIFIED = {'comportamiento-no-especificado', 'verificacion-pendiente'}
DISPOSITIONS = ('sparx-governs', 'swagger-governs', 'documentation-corrected', 'not-relevant', 'custom-rule')
FORBIDDEN_APPROVERS = {'', 'agent', 'automatic', 'auto', 'system', 'service-generator', 'orchestrator', 'sparx-swagger-validator', 'assistant'}

CONSISTENCY = 'consistency'
ARTIFACTS = ('openapi-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml')


class GateError(RuntimeError):
    def __init__(self, status: str, message: str, details: dict | None = None):
        super().__init__(f'{status}: {message}')
        self.status = status
        self.details = details or {}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(obj) -> str:
    return sha_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8'))


def load(path: Path, default=None):
    path = Path(path)
    return yaml.safe_load(path.read_bytes()) if path.is_file() else default


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ------------------------------------------------------------------------------------------------------------------ items
def finding_fingerprint(finding: dict) -> str:
    op = finding.get('operation') or {}
    return digest([finding.get('category'), finding.get('kind'), op.get('method'), op.get('path'), finding.get('element'),
                   (finding.get('sparx') or {}).get('text'), (finding.get('swagger') or {}).get('text')])


def unverified_fingerprint(item: dict) -> str:
    op = item.get('operation') or {}
    return digest([item.get('category'), op.get('method') if isinstance(op, dict) else None, op.get('path') if isinstance(op, dict) else None, item.get('topic'), item.get('reason')])


def blocking_items(registry: dict) -> list[dict]:
    items = []
    for finding in registry.get('findings') or []:
        items.append({'id': finding['id'], 'type': 'finding', 'kind': finding.get('kind'), 'category': finding['category'], 'fingerprint': finding_fingerprint(finding),
                      'operation': finding['operation'], 'element': finding['element'], 'severity': finding.get('severity'),
                      'sparx': finding['sparx']['text'], 'swagger': finding['swagger']['text'], 'difference': finding['inconsistency']})
    number = 0
    for item in registry.get('unverified') or []:
        if item.get('category') in BLOCKING_UNVERIFIED:
            number += 1
            items.append({'id': f'UNV-{number:03d}', 'type': 'unverified', 'kind': 'unverified', 'category': item['category'], 'fingerprint': unverified_fingerprint(item),
                          'operation': item.get('operation'), 'element': item.get('topic'), 'severity': None, 'sparx': None, 'swagger': None, 'difference': item.get('reason')})
    return items


def resolution_problem(resolution: dict, decision_ids: set) -> str | None:
    if resolution.get('status') != 'approved':
        return 'resolution is not approved'
    if resolution.get('disposition') not in DISPOSITIONS:
        return 'unknown disposition'
    if str(resolution.get('approvedBy', '')).strip().lower() in FORBIDDEN_APPROVERS:
        return 'approval must come from a human (approvedBy)'
    if not str(resolution.get('justification', '')).strip() or not resolution.get('scope') or not resolution.get('approvedAt'):
        return 'justification, scope and approvedAt are required'
    based = resolution.get('basedOnDecision')
    if based and based not in decision_ids:
        return f'referenced human decision {based} does not exist in the service decisions'
    return None


# ------------------------------------------------------------------------------------------ coverage by existing human decisions
def norm_text(value) -> str:
    return ' '.join(str(value).split()).lower()


def decision_text(decision: dict) -> str:
    return norm_text(json.dumps(decision, ensure_ascii=False, default=str))


def decision_scope(decision: dict) -> set:
    target = decision.get('target') or {}
    ops = list(target.get('operations') or [])
    if target.get('method') and target.get('path'):
        ops.append({'method': target['method'], 'path': target['path']})
    return {(o.get('method'), o.get('path')) for o in ops if isinstance(o, dict)}


def coverage_problem(entry: dict, item: dict | None, decisions: dict) -> str | None:
    """A finding is covered by an existing human decision only when ALL of this holds, so a changed source or decision invalidates it:
    the decision exists and is human-reviewed/approved, its content hash is the one recorded, the operation is inside its scope,
    the quoted rule appears verbatim in the decision, and the finding content (fingerprint) is exactly the one that was linked."""
    decision = decisions.get(entry.get('decisionId'))
    if decision is None:
        return 'decision does not exist'
    if not (decision.get('humanReviewed') is True and (decision.get('approvalStatus') in (None, 'approved')) and decision.get('reviewStatus', 'human-reviewed') == 'human-reviewed'):
        return 'decision is not an approved human review'
    if entry.get('decisionSha256') != digest(decision):
        return 'decision content changed since it was linked'
    if item is None:
        return 'finding no longer exists with this content'
    op = item.get('operation') or {}
    if (op.get('method'), op.get('path')) not in decision_scope(decision):
        return 'operation is outside the decision scope'
    quote = norm_text(entry.get('quote', ''))
    if len(quote) < 20 or quote not in decision_text(decision):
        return 'quoted rule is not verbatim in the decision'
    return None


def decisions_by_id(decisions_path: Path) -> dict:
    raw = load(decisions_path, {}) or {}
    entries = raw.get('decisions') if isinstance(raw, dict) else raw
    return {str(d.get('decisionId') or d.get('id')): d for d in entries or [] if isinstance(d, dict) and (d.get('decisionId') or d.get('id'))}


# ------------------------------------------------------------------------------------------------------------- decision topics
def field_of(element: str) -> str:
    return str(element or '').split(' ')[-1].split('.')[-1].replace('[]', '')


def topic_of(item: dict) -> tuple:
    op = item.get('operation') or {}
    where = f"{op.get('method')} {op.get('path')}" if isinstance(op, dict) and op.get('method') else 'general'
    kind = item.get('kind')
    if kind == 'type-or-structure-difference':
        return ('type', field_of(item['element']).lower()), f'Tipo del campo {field_of(item["element"])}'
    if kind in ('requirement-difference', 'conditional-rule-difference'):
        return ('requirement', where), f'Obligatoriedad de campos en {where}'
    return (kind, where, item.get('element')), f'{item.get("element")} ({where})'


def decision_topics(items: list[dict]) -> list[dict]:
    topics = {}
    for item in items:
        key, title = topic_of(item)
        topic = topics.setdefault(key, {'topic': title, 'items': [], 'operations': [], 'elements': []})
        topic['items'].append(item['id'])
        op = item.get('operation') or {}
        where = f"{op.get('method')} {op.get('path')}" if isinstance(op, dict) and op.get('method') else 'general'
        if where not in topic['operations']:
            topic['operations'].append(where)
        topic['elements'].append({'id': item['id'], 'where': where, 'element': item['element'], 'sparx': item.get('sparx'), 'swagger': item.get('swagger')})
    return sorted(topics.values(), key=lambda t: t['items'][0])


def semantic_review_ok(supplemental: dict | None, registry: dict) -> bool:
    """The prose of Activities/CONSIDERACIONES must have been reviewed (agent step) against these exact sources."""
    if not supplemental or supplemental.get('reviewed') is not True or not str(supplemental.get('reviewer', '')).strip():
        return False
    against = supplemental.get('reviewedAgainst') or {}
    sources = registry.get('sources') or {}
    return against.get('openapiSha256') == (sources.get('openapi') or {}).get('sha256') and against.get('endpointDetailSha256') == sources.get('endpointDetailSha256')


def decide(registry: dict | None, resolutions: list, decision_ids: set, authorization: dict | None, semantic_ok: bool, coverage: list | None = None, decisions: dict | None = None) -> dict:
    if registry is None:
        return {'status': NO_AUDIT, 'blocking': [], 'resolved': [], 'orphanedResolutions': [], 'coveredByDecision': [], 'coverageProblems': [], 'topics': [],
                'evaluationHash': None, 'problems': ['no audit registry']}
    items = blocking_items(registry)
    problems, valid = [], {}
    for res in resolutions or []:
        problem = resolution_problem(res, decision_ids)
        if problem:
            problems.append({'resolution': res.get('findingId') or res.get('findingFingerprint'), 'problem': problem})
        else:
            valid[res['findingFingerprint']] = res
    by_fp = {i['fingerprint']: i for i in items}
    covered, coverage_problems = {}, []
    for entry in coverage or []:
        problem = coverage_problem(entry, by_fp.get(entry.get('findingFingerprint')), decisions or {})
        if problem:
            coverage_problems.append({'finding': entry.get('findingId'), 'decision': entry.get('decisionId'), 'problem': problem})
        else:
            covered[entry['findingFingerprint']] = entry
    unresolved = [i for i in items if i['fingerprint'] not in valid and i['fingerprint'] not in covered]
    covered_items = [{**i, 'coveredBy': {k: covered[i['fingerprint']].get(k) for k in ('decisionId', 'quote')}} for i in items if i['fingerprint'] in covered and i['fingerprint'] not in valid]
    resolved = [{**i, 'resolution': {k: valid[i['fingerprint']].get(k) for k in ('disposition', 'approvedBy', 'approvedAt', 'justification', 'scope', 'basedOnDecision')}}
                for i in items if i['fingerprint'] in valid]
    orphaned = [r for fp, r in valid.items() if fp not in {i['fingerprint'] for i in items}]
    sources = registry.get('sources') or {}
    evaluation_hash = digest({'covered': sorted((fp, e['decisionId'], e['decisionSha256']) for fp, e in covered.items()), 'items': sorted((i['fingerprint'], valid[i['fingerprint']]['disposition'], valid[i['fingerprint']]['approvedAt']) for i in items if i['fingerprint'] in valid),
                              'unresolved': sorted(i['fingerprint'] for i in unresolved), 'openapi': (sources.get('openapi') or {}).get('sha256'),
                              'detail': sources.get('endpointDetailSha256'), 'authority': sources.get('authoritySha256')})
    if not semantic_ok:
        status = SEMANTIC_REVIEW_PENDING
    elif unresolved:
        status = BLOCKED
    elif not authorization or authorization.get('evaluationHash') != evaluation_hash or not str(authorization.get('authorizedBy', '')).strip():
        status = AWAITING_AUTHORIZATION
    else:
        status = CLEARED
    return {'status': status, 'blocking': unresolved, 'resolved': resolved, 'orphanedResolutions': [{k: r.get(k) for k in ('findingId', 'findingFingerprint', 'disposition')} for r in orphaned],
            'coveredByDecision': covered_items, 'coverageProblems': coverage_problems, 'topics': decision_topics(unresolved),
            'evaluationHash': evaluation_hash, 'problems': problems}


# ----------------------------------------------------------------------------------------------------------------- workspace I/O
def paths(ws_dir: Path) -> dict:
    base = Path(ws_dir) / CONSISTENCY
    return {'base': base, 'registry': base / 'findings.yml', 'manifest': base / 'snapshot-manifest.yml', 'supplemental': base / 'supplemental.yml',
            'resolutions': base / 'resolutions.yml', 'coverage': base / 'decision-coverage.yml', 'authorization': base / 'authorization.yml', 'gate': base / 'gate.yml',
            'decisions': Path(ws_dir) / 'sparx-reviewed-decisions.yml'}


def decision_ids(decisions_path: Path) -> set:
    raw = load(decisions_path, {}) or {}
    entries = raw.get('decisions') if isinstance(raw, dict) else raw
    return {str(d.get('decisionId') or d.get('id')) for d in entries or [] if isinstance(d, dict) and (d.get('decisionId') or d.get('id'))}


def snapshot_from_workspace(ws_dir: Path) -> dict | None:
    """Manifest binding the audit to the pipeline artifacts of the workspace and to the live Swagger file and Sparx export."""
    ws_dir = Path(ws_dir)
    if not all((ws_dir / a).is_file() for a in ARTIFACTS):
        return None
    openapi = load(ws_dir / 'openapi-spec.yml')
    authority = load(ws_dir / 'sparx-target-authority.yml')
    source = (openapi.get('source') or {})
    root = (authority.get('target') or {}).get('sourceRoot')
    return {'schemaVersion': 1, 'kind': 'audit-snapshot-manifest', 'service': (authority.get('target') or {}).get('name'), 'workspaceRelative': True, 'work': '.',
            'openapi': {'path': source.get('path'), 'sha256': source.get('sha256')}, 'sparx': {'root': str(root).rstrip('/'), 'tocFiles': (authority.get('hierarchySources') or {}).get('tocFiles')},
            'artifacts': {a: currency.sha(ws_dir / a) for a in ARTIFACTS}, 'pages': {}, 'factoryUsed': True}


def build_manifest(ws_dir: Path, repo: Path) -> dict | None:
    """The Sparx hierarchy hashes are those RECORDED by the authority analysis, so a later change of the export makes the audit stale."""
    manifest = snapshot_from_workspace(ws_dir)
    if manifest is None:
        return None
    if manifest['sparx']['tocFiles'] is None:
        raise GateError(NO_AUDIT, 'the Sparx authority artifact does not record the hierarchy fingerprint of the analyzed export')
    return manifest


def fresh_registry(ws_dir: Path, repo: Path, service: str, persist: bool = False) -> dict | None:
    """Recompute the audit from the workspace artifacts and the live sources (deterministic; reuses compare_sparx_swagger)."""
    p = paths(ws_dir)
    manifest = build_manifest(ws_dir, repo)
    if manifest is None:
        return None
    if manifest['service'] != service:
        raise GateError(NO_AUDIT, f'workspace artifacts belong to {manifest["service"]}, not {service}')
    if persist:
        p['base'].mkdir(parents=True, exist_ok=True)
        p['manifest'].write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding='utf-8')
        manifest_path, output = p['manifest'], p['registry']
    else:
        tmp = Path(tempfile.mkdtemp(prefix='gate-'))
        manifest_path, output = tmp / 'm.yml', tmp / 'f.yml'
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding='utf-8')
    try:
        cmp.build_registry(service, Path(ws_dir) / 'openapi-spec.yml', Path(ws_dir) / 'sparx-authoritative-endpoint-detail.yml', Path(ws_dir) / 'sparx-target-authority.yml', output,
                           p['supplemental'] if p['supplemental'].is_file() else None, p['decisions'] if p['decisions'].is_file() else None, manifest_path, repo, workspace=Path(ws_dir))
    except SystemExit as error:  # stale or unusable sources: the gate cannot be cleared
        raise GateError(NO_AUDIT, str(error))
    return yaml.safe_load(Path(output).read_bytes())


def current_decision(ws_dir: Path, repo: Path, service: str, persist: bool = False) -> dict:
    spec = load(Path(ws_dir) / 'service-spec.yml') or {}
    if (spec.get('service') or {}).get('profile') == 'batch-shell':
        import batch_gate
        return batch_gate.evaluate(Path(ws_dir), Path(repo), service, sys.modules[__name__])
    p = paths(ws_dir)
    registry = fresh_registry(ws_dir, repo, service, persist)
    supplemental = load(p['supplemental'])
    resolutions = (load(p['resolutions'], {}) or {}).get('resolutions', [])
    coverage = (load(p['coverage'], {}) or {}).get('coverage', [])
    result = decide(registry, resolutions, decision_ids(p['decisions']), load(p['authorization']),
                    semantic_review_ok(supplemental, registry) if registry else False, coverage, decisions_by_id(p['decisions']))
    return {**result, '_registry': registry}


def evaluate(ws_dir: Path, repo: Path, service: str) -> dict:
    """Recompute, persist the audit registry and the gate result; returns the decision (without the registry)."""
    result = current_decision(ws_dir, repo, service, persist=True)
    registry = result.pop('_registry')
    out = {'schemaVersion': 1, 'service': service, 'evaluatedAt': now(), **result,
           'counts': {'findings': len((registry or {}).get('findings') or []), 'blocking': len(result['blocking']), 'resolved': len(result['resolved']), 'coveredByDecision': len(result['coveredByDecision']), 'topics': len(result['topics'])}}
    paths(ws_dir)['gate'].write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=200), encoding='utf-8')
    return out


def check_cleared(ws_dir: Path, repo: Path, service: str | None = None) -> dict:
    """Raise GateError unless the gate is CLEARED right now, recomputed from the files (never from a stored status)."""
    ws_dir = Path(ws_dir)
    authority = load(ws_dir / 'sparx-target-authority.yml') or {}
    service = service or (authority.get('target') or {}).get('name')
    if not service:
        raise GateError(NO_AUDIT, 'no service identity: the workspace has no resolved Sparx authority')
    result = current_decision(ws_dir, repo, service)
    result.pop('_registry', None)
    if result['status'] != CLEARED:
        message = f'{len(result["blocking"])} blocking item(s) pending' if result['blocking'] else 'consistency gate is not cleared'
        if result.get('comparison') == 'not-applicable-non-http-batch' and result.get('problems'):
            message += ': ' + '; '.join(str(p) for p in result['problems'])
        raise GateError(result['status'], message, result)
    return result


# --------------------------------------------------------------------------------------------------------------- human steps
def record_resolution(ws_dir: Path, repo: Path, service: str, item_id: str, disposition: str, justification: str, approved_by: str,
                      scope: list | None = None, based_on_decision: str | None = None) -> dict:
    """Persist an approved human resolution bound to the current content of the item. Never called automatically."""
    p = paths(ws_dir)
    result = current_decision(ws_dir, repo, service)
    item = next((i for i in result['blocking'] + [r for r in result['resolved']] if i['id'] == item_id), None)
    if item is None:
        raise GateError(NO_AUDIT, f'unknown blocking item {item_id}')
    scope = scope or [f"{item['operation']['method']} {item['operation']['path']}" if isinstance(item.get('operation'), dict) and item['operation'].get('method') else 'service']
    entry = {'findingId': item_id, 'findingFingerprint': item['fingerprint'], 'status': 'approved', 'disposition': disposition, 'justification': justification, 'scope': scope,
             'approvedBy': approved_by, 'approvedAt': now(), 'approvalSource': 'explicit user decision', **({'basedOnDecision': based_on_decision} if based_on_decision else {})}
    problem = resolution_problem(entry, decision_ids(p['decisions']))
    if problem:
        raise GateError(BLOCKED, problem)
    data = load(p['resolutions'], {}) or {'schemaVersion': 1, 'resolutions': []}
    data['resolutions'] = [r for r in data['resolutions'] if r.get('findingFingerprint') != entry['findingFingerprint']] + [entry]
    p['base'].mkdir(parents=True, exist_ok=True)
    p['resolutions'].write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=200), encoding='utf-8')
    return entry


def authorize(ws_dir: Path, repo: Path, service: str, authorized_by: str, statement: str) -> dict:
    """Explicit user authorization to resume development; only possible when nothing blocking remains, bound to this exact evaluation."""
    result = current_decision(ws_dir, repo, service)
    if result['status'] not in (AWAITING_AUTHORIZATION, CLEARED):
        raise GateError(result['status'], 'resuming cannot be authorized while the gate has pending items', result)
    if str(authorized_by).strip().lower() in FORBIDDEN_APPROVERS or not str(statement).strip():
        raise GateError(BLOCKED, 'authorization must come from the user and quote their statement')
    entry = {'schemaVersion': 1, 'service': service, 'authorizedBy': authorized_by, 'statement': statement, 'authorizedAt': now(), 'evaluationHash': result['evaluationHash']}
    p = paths(ws_dir)
    p['base'].mkdir(parents=True, exist_ok=True)
    p['authorization'].write_text(yaml.safe_dump(entry, sort_keys=False, allow_unicode=True), encoding='utf-8')
    return entry
