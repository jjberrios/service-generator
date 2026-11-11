"""Separate lifecycle states of an archetype and of a service workspace, and the question policy.

Each state is `yes`, `no`, `partial`, `unknown` or `not-verified`. A state is `yes` only with direct evidence in the
files; a tool that was never run is `not-verified`, never inferred from another state (for example a materialized
service is not compiled, and a frozen archetype is not generation-enabled).
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'plan-service-implementation' / 'scripts'))
import generation_context as gc  # noqa: E402
import archetype_contract as ac  # noqa: E402

TOOLS = ('maven', 'compilation', 'tests', 'jacoco', 'checkstyle')


def _tri(value):
    return 'yes' if value is True else 'no' if value is False else 'unknown'


def archetype_lifecycle(repo, archetype_path):
    manifest = gc.load_mapping(Path(repo) / archetype_path / 'archetype.yml')
    contract = ac.normalize(manifest)
    life = contract['lifecycle']
    identity = manifest.get('identity') or {}
    readiness = manifest.get('readiness') or {}
    try:
        ac.require_backend(contract, mode='full')
        backend = 'yes'
    except ac.ContractError:
        backend = 'no'
    return {
        'archetype': archetype_path,
        'extracted': 'yes',
        'approved': _tri(life['approved']),
        'frozen': _tri(life['frozen']),
        'generationEnabled': _tri(life['generationEnabled']),
        'backendImplemented': backend,
        'serviceGenerationAuthorizedForConcreteTargets': _tri(readiness.get('serviceGenerationAuthorized')),
        'runtimeVerified': 'not-verified',
        'note': 'frozen and generationEnabled are independent; neither implies a working backend or an authorized target',
    }


def _load(path):
    return gc.load_mapping(path) if path.is_file() else None


def service_lifecycle(repo, service, gate):
    repo = Path(repo)
    ws = repo / '.factory' / 'services' / service
    state = _load(ws / 'service-generation-state.yml') or {}
    result = {'service': service, 'archetypeSelected': 'yes' if (state.get('archetype') or {}).get('path') else 'no'}
    try:
        status = gate.current_decision(ws, repo, service)['status']
    except Exception as error:  # an unreadable workspace never reads as cleared
        status = f'unevaluable: {type(error).__name__}'
    result['gate'] = status
    result['gateCleared'] = 'yes' if status == gate.CLEARED else 'no'
    result['specConsolidated'] = 'yes' if (ws / 'service-spec.yml').is_file() else 'no'
    result['planned'] = 'yes' if (ws / 'implementation-plan.yml').is_file() else 'no'
    report = _load(ws / 'materialization-report.yml')
    plan_doc = _load(ws / 'implementation-plan.yml') or {}
    out_rel = ((plan_doc.get('service') or {}).get('outputDirectory') or f'output/{service}')
    manifest_seen = bool(report) and (repo / out_rel / '.generation-manifest.yml').is_file()
    result['materialized'] = 'yes' if manifest_seen else 'no'
    if report:
        status_text = str(report.get('status', ''))
        result['functionallyComplete'] = ('partial' if 'incomplete' in status_text else
                                           'yes' if status_text == 'complete' else 'unknown')
    else:
        result['functionallyComplete'] = 'no'
    result['declaredLimitations'] = len((_load(ws / 'service-spec.yml') or {}).get('warnings') or [])
    if report:
        status_text = str(report.get('status', ''))
        complete = status_text == 'complete' and result['declaredLimitations'] == 0
        result['functionallyComplete'] = ('partial' if 'incomplete' in status_text or (status_text == 'complete' and not complete)
                                           else 'yes' if complete else 'unknown')
    else:
        result['functionallyComplete'] = 'no'
    evidence = _load(ws / 'validation-evidence.yml') or {}
    for tool in TOOLS:
        recorded = evidence.get(tool)
        result[tool] = 'yes' if recorded == 'passed' else 'no' if recorded == 'failed' else 'not-verified'
    if state.get('archetype', {}).get('path'):
        contract = ac.normalize(gc.load_mapping(repo / state['archetype']['path'] / 'archetype.yml'))
        if contract['quality']['checkstyle']['applicability'] == 'not-applicable' and result['checkstyle'] == 'not-verified':
            result['checkstyle'] = 'not-applicable'
    result['runtime'] = 'not-verified'
    return result


# ---- question policy -------------------------------------------------------------------------------

POLICY = {
    'source-evidence-clear': ('apply-and-cite', False, 'use the owning contract, Sparx or attachment evidence; do not ask for it again'),
    'analysis-incomplete': ('analyze-target-evidence', False, 'finish bounded source and attachment analysis before asking'),
    'technical-convention': ('resolve-and-record', False, 'choose a consistent internal convention without changing public or business semantics'),
    'supported-service-extension': ('plan-extension', False, 'plan a compatible evidence-backed service addition; preserve the versioned archetype'),
    'environment-configuration': ('externalize-configuration', False, 'keep runtime values external; never request credentials for static generation'),
    'functional-evidence-missing': ('group-ask', True, 'indispensable functional evidence is absent after target-local analysis'),
    'reference-evidence-clear': ('apply-and-cite', False, 'the selected reference decides; cite the evidence'),
    'technology-absent-in-reference': ('record-absent', False, 'record it as not-present-in-reference; never offer another stack'),
    'decision-already-approved': ('reuse-decision', False, 'reuse the approved decision for the same target/version; do not reopen it'),
    'request-covers-phase': ('proceed', False, 'the user request already authorizes this phase; do not ask again'),
    'unsupported-backend': ('technical-failure', False, 'engineering limitation, not a business choice; report and stop'),
    'source-conflict': ('ask', True, 'real conflicting evidence: stop the affected behavior and ask'),
    'required-parameter-missing': ('group-ask', True, 'ask once, grouped with the other missing parameters'),
    'intentional-deviation': ('scoped-approval', True, 'ask for an approval limited to this target/version'),
    'gate-release': ('ask-bound-to-evaluation-hash', True, 'human authorization bound to the current evaluation hash'),
}


def decide(kind):
    if kind not in POLICY:
        raise ValueError(f'unknown question kind: {kind}')
    action, ask, why = POLICY[kind]
    return {'kind': kind, 'action': action, 'askUser': ask, 'reason': why}


def find_decision(decisions, scope, ws_dir=None):
    """Approved human decision for exactly this scope (target-local), or None. Never matches machine approvals."""
    import decision_reviews
    for item in decisions or []:
        if item.get('scope') == scope and ws_dir is not None:
            try:
                decision_reviews.require_records(ws_dir, [item])
                return item
            except (ValueError, OSError, KeyError, TypeError):
                pass
    return None


def group_questions(questions):
    """Deduplicate by (kind, key); every `ask` question for missing parameters becomes ONE grouped question."""
    seen, grouped, params = set(), [], []
    for q in questions:
        policy = decide(q['kind'])
        if not policy['askUser']:
            continue
        marker = (q['kind'], q.get('key'))
        if marker in seen:
            continue
        seen.add(marker)
        if q['kind'] == 'required-parameter-missing':
            params.append(q.get('key'))
        else:
            grouped.append(q)
    if params:
        grouped.append({'kind': 'required-parameter-missing', 'keys': sorted(params)})
    return grouped


def triage(issues):
    """Classify proposed issues, never grant reviews or change readiness.

    Extensions require both source references and explicit backend capability.
    Claims here are routing metadata, not proof of functional readiness.
    """
    actions = []
    for issue in issues:
        item = dict(issue)
        kind = item['kind']
        if kind == 'supported-service-extension':
            if not item.get('evidence'):
                kind = 'analysis-incomplete'
            elif item.get('backendSupported') is not True or item.get('compatibleWithArchetype') is not True:
                kind = 'unsupported-backend'
        item['kind'] = kind
        actions.append({**item, **decide(kind)})
    return {'actions': actions, 'questions': group_questions(actions), 'grantsAuthority': False}


def capability_check(repo, service):
    """Early read-only profile check, before semantic analysis or the gate."""
    context = gc.resolve_context(Path(repo), service=service)
    contract = ac.normalize(gc.load_mapping(Path(repo) / context.archetype / 'archetype.yml'))
    try:
        ac.require_backend(contract, mode='full')
    except ac.ContractError as error:
        return {'service': service, 'supported': False, 'askUser': False,
                'action': 'technical-failure', 'reason': str(error), 'gateEvaluated': False}
    return {'service': service, 'supported': True, 'askUser': False,
            'action': 'continue-analysis', 'gateEvaluated': False,
            'note': 'profile support only; component feasibility, readiness and human review still required'}
