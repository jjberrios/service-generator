"""Proposal-only decision requests. No imports/calls to approval writers."""
import copy
import os
from pathlib import Path
import re
import tempfile

import yaml

import decision_context as dc
from decision_context import DecisionError
from artifact_integrity import safe_path
from generation_context import load_mapping
import workspace as wsm

CLASSES = ('agent-technical', 'analysis-required', 'human-functional', 'explicit-authorization')
ID = re.compile(r'^[a-z][a-z0-9-]{0,79}$')
REQUEST_ID = re.compile(r'^request-[a-f0-9]{64}$')


def fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise DecisionError('invalid-decision-fields')


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 20000:
        raise DecisionError('invalid-decision-text')


def validate(proposal, context, repo, *, check_files=True):
    dc.canonical(proposal)  # reject dates, cycles, NaN and non-JSON data
    fields(proposal, ('schemaVersion', 'purpose', 'decisions'))
    if type(proposal['schemaVersion']) is not int or proposal['schemaVersion'] not in (1, 2) or proposal['purpose'] != context['purpose']:
        raise DecisionError('invalid-decision-version-or-purpose')
    decisions = proposal['decisions']
    if not isinstance(decisions, list) or not decisions or len(decisions) > 100:
        raise DecisionError('invalid-decision-group')
    keys = set()
    known = {f['fingerprint'] for f in context['findings']}
    ws = wsm.Workspace(repo, context['service'])
    for item in decisions:
        fields(item, ('key', 'classification', 'problem', 'evidence', 'alternatives', 'findingFingerprints'), ('recommendation',))
        if not isinstance(item['key'], str) or not ID.fullmatch(item['key']) or item['key'] in keys:
            raise DecisionError('duplicate-or-invalid-decision-key')
        keys.add(item['key'])
        if item['classification'] not in CLASSES:
            raise DecisionError('invalid-decision-classification')
        text(item['problem'])
        fps = item['findingFingerprints']
        if not isinstance(fps, list) or any(not isinstance(f, str) or f not in known for f in fps) or len(fps) != len(set(fps)):
            raise DecisionError('unknown-or-duplicate-finding')
        historical = proposal['schemaVersion'] == 2 and any(
            isinstance(a, dict) and isinstance(a.get('binding'), dict) and a['binding'].get('kind') == 'historical-decision'
            for a in item.get('alternatives', []))
        if item['classification'] == 'human-functional' and not fps and not historical:
            raise DecisionError('functional-decision-needs-finding')
        evidence = item['evidence']
        if not isinstance(evidence, list) or not evidence:
            raise DecisionError('decision-evidence-required')
        for entry in evidence:
            fields(entry, ('path', 'pointer', 'summary'))
            text(entry['pointer'])
            text(entry['summary'])
            rel = entry['path']
            if not isinstance(rel, str):
                raise DecisionError('invalid-evidence-path')
            if rel in dc.ARTIFACTS:
                target = safe_path(ws.dir, rel)
            elif rel in context['sources']:
                target = dc.source_path(repo, rel)
            else:
                raise DecisionError('evidence-outside-context')
            if check_files and not target.is_file():
                raise DecisionError('missing-evidence-file')
        alternatives = item['alternatives']
        if not isinstance(alternatives, list) or not alternatives:
            raise DecisionError('decision-alternatives-required')
        alt_ids = set()
        for alt in alternatives:
            fields(alt, ('id', 'description', 'effects'), ('binding',) if proposal['schemaVersion'] == 2 else ())
            if 'binding' in alt:
                import decision_reviews
                decision_reviews.validate_binding(alt['binding'], item, context)
            if not isinstance(alt['id'], str) or not ID.fullmatch(alt['id']) or alt['id'] in alt_ids:
                raise DecisionError('duplicate-or-invalid-alternative')
            alt_ids.add(alt['id'])
            text(alt['description'])
            if not isinstance(alt['effects'], list) or not alt['effects']:
                raise DecisionError('alternative-effects-required')
            for effect in alt['effects']:
                text(effect)
        if 'recommendation' in item:
            rec = item['recommendation']
            fields(rec, ('alternativeId', 'rationale', 'evidenceIndexes'))
            text(rec['rationale'])
            if rec['alternativeId'] not in alt_ids or not isinstance(rec['evidenceIndexes'], list) or not rec['evidenceIndexes']:
                raise DecisionError('invalid-recommendation')
            if any(type(i) is not int or i < 0 or i >= len(evidence) for i in rec['evidenceIndexes']):
                raise DecisionError('invalid-recommendation-evidence')


def assemble(repo, service, proposal):
    if not isinstance(proposal, dict):
        raise DecisionError('invalid-decision-proposal')
    context = dc.build(repo, service, proposal.get('purpose'))
    validate(proposal, context, repo)
    items = []
    for item in sorted(proposal['decisions'], key=lambda d: d['key']):
        item = copy.deepcopy(item)
        item['findingFingerprints'] = sorted(item['findingFingerprints'])
        item['decisionId'] = 'decision-' + dc.digest({'contextId': context['contextId'], 'decision': item})
        items.append(item)
    result = {'schemaVersion': proposal['schemaVersion'], 'kind': 'decision-request', 'authority': 'none',
              'service': service, 'purpose': proposal['purpose'], 'context': context, 'decisions': items}
    result['requestId'] = 'request-' + dc.digest(result)
    return result


def encode(request):
    return yaml.safe_dump(request, sort_keys=True, allow_unicode=True, width=100).encode('utf-8')


def directory(repo, service):
    wsm.safe_name(service)
    return safe_path(Path(repo).resolve(), f'.factory/services/{service}/decision-requests')


def create(repo, service, proposal):
    request = assemble(repo, service, proposal)
    base = directory(repo, service)
    target = safe_path(base, request['requestId'] + '.yml')
    payload = encode(request)
    if target.exists():
        if target.read_bytes() != payload:
            raise DecisionError('existing-request-content-conflict')
        return request
    base.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.request-', suffix='.tmp', dir=base)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Exclusive, atomic publication; never overwrite a modified request.
        try:
            os.link(name, target)
        except FileExistsError:
            if target.read_bytes() != payload:
                raise DecisionError('existing-request-content-conflict')
    finally:
        os.unlink(name)
    return request


def read(repo, service, request_id):
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise DecisionError('invalid-request-id')
    target = safe_path(directory(repo, service), request_id + '.yml')
    if not target.is_file():
        raise DecisionError('request-not-found')
    request = load_mapping(target)
    fields(request, ('schemaVersion', 'kind', 'authority', 'service', 'purpose', 'context', 'decisions', 'requestId'))
    content = {k: v for k, v in request.items() if k != 'requestId'}
    if (request['service'] != service or request['kind'] != 'decision-request' or request['authority'] != 'none'
            or type(request['schemaVersion']) is not int or request['schemaVersion'] not in (1, 2)
            or request_id != request['requestId'] or request_id != 'request-' + dc.digest(content)):
        raise DecisionError('invalid-stored-request')
    context = request['context']
    if not isinstance(context, dict) or context.get('contextId') != dc.digest({k: v for k, v in context.items() if k != 'contextId'}):
        raise DecisionError('invalid-stored-context')
    # No stored flags are used as authority, including a self-consistent forged hash.
    proposal = {'schemaVersion': request['schemaVersion'], 'purpose': request['purpose'],
                'decisions': [{k: v for k, v in d.items() if k != 'decisionId'} for d in request['decisions']]}
    if context.get('service') != service or context.get('purpose') != request['purpose']:
        raise DecisionError('invalid-stored-context-identity')
    validate(proposal, context, repo, check_files=False)
    for item in request['decisions']:
        if item.get('decisionId') != 'decision-' + dc.digest({'contextId': context['contextId'],
                                                           'decision': {k: v for k, v in item.items() if k != 'decisionId'}}):
            raise DecisionError('invalid-stored-decision-id')
    return request


def status(repo, service, request_id):
    request = read(repo, service, request_id)
    try:
        current = dc.build(repo, service, request['purpose'])
        validity = 'current' if current['contextId'] == request['context']['contextId'] else 'stale'
        reason = None
        current_id = current['contextId']
    except (ValueError, OSError, TypeError, KeyError) as error:
        validity, reason, current_id = 'unavailable', str(error), None
    return {'requestId': request_id, 'service': service, 'authority': 'none',
            'validity': validity, 'contextId': request['context']['contextId'],
            'currentContextId': current_id, 'reason': reason,
            'decisions': [{'decisionId': d['decisionId'], 'key': d['key'], 'classification': d['classification']}
                          for d in request['decisions']]}


def list_requests(repo, service, stale_only=False):
    base = directory(repo, service)
    rows = []
    for path in sorted(base.glob('request-*.yml')):
        try:
            row = status(repo, service, path.stem)
        except (ValueError, OSError, TypeError, KeyError) as error:
            row = {'requestId': path.stem, 'validity': 'invalid', 'authority': 'none', 'reason': str(error)}
        if not stale_only or row['validity'] != 'current':
            rows.append(row)
    return rows
