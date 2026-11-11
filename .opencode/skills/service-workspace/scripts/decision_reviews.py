"""Model B operational reviews. NOT authentication against same-user execution.

Only review_cli exposes the writer interactively. Consumers recompute context;
legacy approval files are evidence, never authority. H-02 remains open.
"""
from contextlib import contextmanager
from copy import deepcopy
import datetime
import os
from pathlib import Path
import re
import subprocess
import tempfile

import yaml

import decision_context as dc
import decision_requests as dr
from artifact_integrity import safe_path, protected
from generation_context import load_mapping

KINDS = {'resolve-finding': ('resolve-findings', 'human-functional'),
         'resume': ('authorize-operation', 'explicit-authorization'),
         'historical-decision': ('resolve-findings', 'human-functional'),
         'overwrite': ('authorize-operation', 'explicit-authorization')}
EVENT = re.compile(r'^review-[0-9a-f]{64}$')
WARNING = 'H-02 remains open: Model B is operational mitigation, not strong human authentication.'


def validate_binding(binding, decision, context):
    if not isinstance(binding, dict) or binding.get('kind') not in KINDS:
        raise dc.DecisionError('invalid-review-binding')
    kind = binding['kind']
    fields = {'resolve-finding': ('fingerprint', 'disposition'), 'resume': ('evaluationHash',),
              'historical-decision': ('decisionId', 'contentSha256'),
              'overwrite': ('outputDirectory', 'path', 'currentSha256', 'planSha256')}[kind]
    dr.fields(binding, ('kind', *fields))
    purpose, classification = KINDS[kind]
    if context['purpose'] != purpose or decision['classification'] != classification:
        raise dc.DecisionError('binding-purpose-or-classification-mismatch')
    for name in fields:
        dr.text(binding[name])
    for name in ('fingerprint', 'evaluationHash', 'contentSha256', 'currentSha256', 'planSha256'):
        if name in binding and not re.fullmatch('[0-9a-f]{64}', binding[name]):
            raise dc.DecisionError('invalid-binding-fingerprint')
    if kind == 'resolve-finding':
        import consistency_gate as gate
        if binding['fingerprint'] not in decision['findingFingerprints'] or binding['disposition'] not in gate.DISPOSITIONS:
            raise dc.DecisionError('invalid-finding-binding')
    if kind == 'overwrite':
        for name in ('outputDirectory', 'path'):
            safe_path(Path.cwd(), binding[name])
        if not binding['outputDirectory'].startswith('output/') or protected(binding['path']):
            raise dc.DecisionError('invalid-overwrite-binding')


def location(repo):
    """Common Git directory is a local consistency scope, NOT an identity proof."""
    repo = Path(repo).resolve()
    done = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                          capture_output=True, text=True)
    common = Path(done.stdout.strip()).resolve().as_posix() if done.returncode == 0 else repo.as_posix()
    return {'worktree': repo.as_posix(), 'repository': dc.digest({'localGitCommonDirectory': common})}


def _functional(node):
    if isinstance(node, dict):
        return {k: _functional(v) for k, v in node.items() if k not in
                ('evaluatedAt', 'generatedAt', 'updatedAt', 'createdAt')}
    if isinstance(node, list):
        return [_functional(v) for v in node]
    return node


def context(repo, service, purpose):
    """Version 2 factual review context; excludes derived specs and gate outputs.

    Reuses v1 source closure/canonicalization. Decisions do not depend on grants,
    generated plans, checkpoints or derived HTTP specs written by consolidation.
    """
    old = dc.build(repo, service, purpose)
    artifacts = {}
    names = ('openapi-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml',
             'sparx-reviewed-decisions.yml', 'consistency/resolutions.yml', 'consistency/decision-coverage.yml',
              'consistency/supplemental.yml', 'consistency/batch-review.yml',
              'sparx-http-contract.yml', 'sparx-attachments.yml', 'consistency/sparx-only-review.yml')
    ws = Path(repo) / '.factory/services' / service
    for name in names:
        artifacts[name] = dc.digest(_functional(load_mapping(safe_path(ws, name))))
    if old['archetype']['profile'].startswith('batch-shell'):
        artifacts['sparx-spec.yml'] = dc.digest(_functional(load_mapping(ws / 'sparx-spec.yml')))
    value = {'schemaVersion': 2, 'kind': 'review-context', 'service': service, 'purpose': purpose,
             'archetype': old['archetype'], 'sources': old['sources'], 'artifactFingerprints': artifacts,
             'findings': old['findings'], 'semanticReview': _functional(old['semanticReview']),
             'previousDecisions': old['previousDecisions'], 'audit': old['audit']}
    value['contextId'] = dc.digest(value)
    return value


def directory(repo, service):
    import workspace
    workspace.safe_name(service)
    return safe_path(Path(repo).resolve(), f'.factory/services/{service}/decision-reviews')


@contextmanager
def _lock(base):
    base.mkdir(parents=True, exist_ok=True)
    path = safe_path(base, '.writer.lock')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as error:
        raise dc.DecisionError('review-writer-busy; inspect stale lock manually') from error
    try:
        os.close(fd)
        yield
    finally:
        path.unlink()


def _publish(base, event):
    target = safe_path(base, event['eventId'] + '.yml')
    payload = dr.encode(event)
    if target.exists():
        if target.read_bytes() != payload:
            raise dc.DecisionError('review-content-conflict')
        return
    fd, temp = tempfile.mkstemp(dir=base, prefix='.review-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, target)  # exclusive publication, no overwrite fallback
    finally:
        os.unlink(temp)


def events(repo, service):
    result = []
    previous = None
    for path in directory(repo, service).glob('review-*.yml'):
        event = load_mapping(safe_path(path.parent, path.name))
        dr.fields(event, ('schemaVersion', 'kind', 'eventId', 'sequence', 'previous', 'service', 'action',
                          'requestId', 'requestContextId', 'context', 'location', 'scope', 'selections', 'targets', 'recordedAt', 'security'),
                  optional=('delegation',))
        if (event['schemaVersion'] != 1 or event['kind'] != 'operational-review' or event['service'] != service
                or not EVENT.fullmatch(path.stem) or event['eventId'] != path.stem
                or path.stem != 'review-' + dc.digest({k: v for k, v in event.items() if k != 'eventId'})
                or type(event['sequence']) is not int or event['action'] not in ('review', 'revoke')):
            raise dc.DecisionError('invalid-review-event')
        result.append(event)
        if event['action'] == 'review':
            snapshot = event['context']
            if (not isinstance(snapshot, dict) or snapshot.get('service') != service or snapshot.get('schemaVersion') != 2
                    or snapshot.get('contextId') != dc.digest({k: v for k, v in snapshot.items() if k != 'contextId'})):
                raise dc.DecisionError('invalid-review-context')
            seen = set()
            if not isinstance(event['selections'], list) or not isinstance(event['location'], dict):
                raise dc.DecisionError('invalid-review-selections-or-location')
            for selection in event['selections']:
                dr.fields(selection, ('decisionId', 'key', 'outcome', 'alternativeId', 'binding', 'decision'))
                decision = selection['decision']
                if not isinstance(decision, dict):
                    raise dc.DecisionError('invalid-reviewed-decision')
                ident = decision['decisionId']
                if (ident in seen or selection['decisionId'] != ident or selection['key'] != decision['key']
                        or ident != 'decision-' + dc.digest({'contextId': event['requestContextId'],
                            'decision': {k: v for k, v in decision.items() if k != 'decisionId'}})
                        or selection['outcome'] not in ('approved', 'rejected', 'pending')):
                    raise dc.DecisionError('invalid-reviewed-decision')
                seen.add(ident)
    result.sort(key=lambda e: e['sequence'])
    for n, event in enumerate(result, 1):
        if event['sequence'] != n or event['previous'] != previous:
            raise dc.DecisionError('review-history-gap-or-fork')
        previous = event['eventId']
    return result


def _append(repo, service, value):
    """Private manual-interface writer; callable Python is not an OS boundary."""
    base = directory(repo, service)
    with _lock(base):
        history = events(repo, service)
        value = {**value, 'schemaVersion': 1, 'kind': 'operational-review', 'service': service,
                 'sequence': len(history) + 1, 'previous': history[-1]['eventId'] if history else None,
                 'recordedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'security': WARNING}
        value['eventId'] = 'review-' + dc.digest(value)
        _publish(base, value)
        return value


def _record(repo, service, request_id, choices, *, scope='worktree', supersedes=(), delegation=None):
    """Only review_cli calls this after displaying and individually selecting items.
    Tests may simulate that local review; hashes do NOT attest who called it.
    """
    request = dr.read(repo, service, request_id)
    if dr.status(repo, service, request_id)['validity'] != 'current':
        raise dc.DecisionError('stale-request; prepare a current request')
    if scope not in ('worktree', 'functional-common-git') or not choices:
        raise dc.DecisionError('invalid-or-empty-review')
    snapshot = context(repo, service, request['purpose'])
    selections = []
    by_id = {d['decisionId']: d for d in request['decisions']}
    for ident, choice in sorted(choices.items()):
        if ident not in by_id:
            raise dc.DecisionError('decision-not-in-request')
        decision = by_id[ident]
        if decision['classification'] not in ('human-functional', 'explicit-authorization'):
            raise dc.DecisionError('analysis-and-technical-items-are-not-human-approvals')
        outcome, alt_id = choice
        alt = next((a for a in decision['alternatives'] if a['id'] == alt_id), None)
        if outcome not in ('approved', 'rejected', 'pending') or (outcome == 'approved' and (not alt or not alt.get('binding'))):
            raise dc.DecisionError('invalid-review-selection-or-unbound-v1-alternative')
        binding = deepcopy(alt['binding']) if outcome == 'approved' else None
        if binding:
            validate_binding(binding, decision, request['context'])
            _check_binding_now(repo, service, binding)
            if scope != 'worktree' and binding['kind'] not in ('resolve-finding', 'historical-decision'):
                raise dc.DecisionError('execution-and-overwrite-are-worktree-local')
        selections.append({'decisionId': ident, 'key': decision['key'], 'outcome': outcome,
                           'alternativeId': alt_id, 'binding': binding,
                           'decision': decision})
    targets = list(supersedes)
    known = {e['eventId'] for e in events(repo, service)}
    if any(t not in known for t in targets):
        raise dc.DecisionError('unknown-superseded-event')
    value = {'action': 'review', 'requestId': request_id,
             'requestContextId': request['context']['contextId'], 'context': snapshot,
             'location': location(repo), 'scope': scope, 'selections': selections, 'targets': targets}
    if delegation:
        value['delegation'] = delegation
    return _append(repo, service, value)


def _revoke(repo, service, event_id):
    if event_id not in {e['eventId'] for e in events(repo, service)}:
        raise dc.DecisionError('unknown-review-event')
    return _append(repo, service, {'action': 'revoke', 'requestId': None, 'requestContextId': None, 'context': None,
                                  'location': location(repo), 'scope': 'worktree', 'selections': [], 'targets': [event_id]})


def _check_binding_now(repo, service, binding):
    import consistency_gate as gate
    ws = Path(repo) / '.factory/services' / service
    kind = binding['kind']
    if kind == 'resolve-finding':
        facts = gate.current_decision(ws, repo, service, review_decisions=False)
        if binding['fingerprint'] not in {i['fingerprint'] for i in gate.blocking_items(facts.get('_registry') or {})}:
            raise dc.DecisionError('finding-no-longer-current')
    elif kind == 'resume':
        result = gate.current_decision(ws, repo, service)
        if result['status'] not in (gate.AWAITING_AUTHORIZATION, gate.CLEARED) or binding['evaluationHash'] != result['evaluationHash']:
            raise dc.DecisionError('gate-not-ready-or-resume-binding-stale')
    elif kind == 'historical-decision':
        raw = gate.decisions_by_id(ws / 'sparx-reviewed-decisions.yml')
        if binding['decisionId'] not in raw or dc.digest(raw[binding['decisionId']]) != binding['contentSha256']:
            raise dc.DecisionError('historical-decision-missing-or-changed')
        target = raw[binding['decisionId']].get('target') or {}
        if not isinstance(target, dict) or (target.get('service') and target['service'] != service):
            raise dc.DecisionError('historical-decision-outside-service-scope')
    else:
        import hashlib
        plan = safe_path(ws, 'implementation-plan.yml')
        actual = safe_path(Path(repo), binding['outputDirectory'] + '/' + binding['path'])
        if (not actual.is_file() or hashlib.sha256(actual.read_bytes()).hexdigest() != binding['currentSha256']
                or hashlib.sha256(plan.read_bytes()).hexdigest() != binding['planSha256']):
            raise dc.DecisionError('overwrite-content-or-plan-changed')


def current(repo, service):
    """Verified operational grants; missing/malformed review fails closed.
    No recursion through the gate: review-context builds factual evaluations only.
    """
    history = events(repo, service)
    dead = {target for e in history for target in e['targets']}
    here = location(repo)
    contexts, result = {}, []
    rejected = {s['decisionId']: e['sequence'] for e in history if e['action'] == 'review' and e['eventId'] not in dead
                for s in e['selections'] if s['outcome'] == 'rejected'}
    for event in history:
        if event['action'] != 'review' or event['eventId'] in dead:
            continue
        scope = event['scope']
        if (scope not in ('worktree', 'functional-common-git') or event['location']['repository'] != here['repository']
                or (scope == 'worktree' and event['location'] != here)):
            continue
        purpose = event['context']['purpose']
        if purpose not in contexts:
            contexts[purpose] = context(repo, service, purpose)
        if event['context'] != contexts[purpose]:
            continue
        for selection in event['selections']:
            if selection['outcome'] != 'approved' or rejected.get(selection['decisionId'], 0) > event['sequence']:
                continue
            decision, binding = selection['decision'], selection['binding']
            validate_binding(binding, decision, event['context'])
            if selection['alternativeId'] not in {a['id'] for a in decision['alternatives'] if a.get('binding') == binding}:
                raise dc.DecisionError('review-alternative-binding-mismatch')
            if scope != 'worktree' and binding['kind'] not in ('resolve-finding', 'historical-decision'):
                continue
            result.append({**selection, 'eventId': event['eventId'], 'recordedAt': event['recordedAt']})
    # Conflicting active selections do not silently choose a winner.
    unique = {}
    for item in result:
        b = item['binding']
        key = (b['kind'], b.get('fingerprint') or b.get('decisionId') or b.get('path') or 'resume')
        if key in unique and unique[key]['binding'] != b:
            raise dc.DecisionError('conflicting-active-reviews; explicitly supersede the prior review')
        unique[key] = item
    return list(unique.values())


def approved_decisions(repo, service):
    import consistency_gate as gate
    ws = Path(repo) / '.factory/services' / service
    raw = gate.decisions_by_id(ws / 'sparx-reviewed-decisions.yml')
    grants = current(repo, service)
    return {ident: d for ident, d in raw.items() if any(g['binding'] ==
            {'kind': 'historical-decision', 'decisionId': ident, 'contentSha256': dc.digest(d)} for g in grants)}


def consumer_workspace(ws_dir):
    """Resolve actual workspace behind the runner's junction, never trust cwd identity."""
    ws = Path(ws_dir).resolve()
    if ws.parent.name != 'services' or ws.parent.parent.name != '.factory':
        raise dc.DecisionError('review-consumer-requires-service-workspace')
    repo, service = ws.parents[2], ws.name
    return repo, service


def require_records(ws_dir, records):
    if not records:
        return []
    repo, service = consumer_workspace(ws_dir)
    approved = approved_decisions(repo, service)
    for item in records:
        ident = str(item.get('decisionId') or item.get('id'))
        if ident not in approved or dc.digest(item) != dc.digest(approved[ident]):
            raise dc.DecisionError(f'legacy-unattested-or-stale-decision: {ident}; use review_cli')
    return records


def require_citations(ws_dir, node):
    """Validate consumed decision references, not unrelated historical records."""
    import consistency_gate as gate
    raw = gate.decisions_by_id(Path(ws_dir) / 'sparx-reviewed-decisions.yml')
    cited = set()
    def walk(value, key=None):
        if isinstance(value, str):
            if value in raw or value.startswith('human-reviewed') or key in ('reviewedDecisionId', 'basedOnDecision', 'decisionId'):
                cited.add(value)
        elif isinstance(value, dict):
            for name, entry in value.items():
                walk(entry, name)
        elif isinstance(value, list):
            for entry in value:
                walk(entry, key)
    walk(node)
    require_records(ws_dir, [raw.get(ident, {'decisionId': ident}) for ident in sorted(cited)])


def _import_functional(repo, service, source_repo, event_id):
    """Manual, explicit functional adoption across worktrees of one Git common dir."""
    event = next((e for e in events(source_repo, service) if e['eventId'] == event_id), None)
    if (not event or event['scope'] != 'functional-common-git'
            or event['location']['repository'] != location(repo)['repository']):
        raise dc.DecisionError('review-is-not-portable-to-this-repository')
    active = [g for g in current(source_repo, service) if g['eventId'] == event_id]
    if not active or any(g['binding']['kind'] not in ('resolve-finding', 'historical-decision') for g in active):
        raise dc.DecisionError('review-not-current-or-not-functional')
    if event['context'] != context(repo, service, event['context']['purpose']):
        raise dc.DecisionError('worktree-semantic-context-differs')
    selections = [{k: v for k, v in g.items() if k not in ('eventId', 'recordedAt')} for g in active]
    return _append(repo, service, {'action': 'review', 'requestId': event['requestId'],
                                  'requestContextId': event['requestContextId'], 'context': event['context'],
                                  'location': location(repo), 'scope': event['scope'], 'selections': selections, 'targets': []})
