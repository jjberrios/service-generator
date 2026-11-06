"""Agent-safe typed proposals; no approval writer is called here."""
import hashlib
from pathlib import Path

import consistency_gate as gate
import decision_context as dc
import decision_requests as dr
from artifact_integrity import safe_path, protected
from generation_context import load_mapping


def prepare(repo, service, kind='gate', *, decision_id=None, path=None):
    ws = Path(repo) / '.factory/services' / service
    items = []
    purpose = 'resolve-findings'

    def add(key, problem, bindings, evidence, fps=()):
        items.append({'key': key, 'classification': 'explicit-authorization' if purpose == 'authorize-operation' else 'human-functional',
                      'problem': problem, 'evidence': [{'path': evidence, 'pointer': '/', 'summary': problem}],
                      'findingFingerprints': list(fps), 'alternatives': [
                          {'id': ident, 'description': description, 'effects': [description], 'binding': binding}
                          for ident, description, binding in bindings]})

    if kind == 'gate':
        result = gate.current_decision(ws, repo, service)
        if result['status'] == gate.CLEARED:
            return {'service': service, 'requestId': None, 'reason': 'current review reused; gate already CLEARED'}
        if result['status'] not in (gate.BLOCKED, gate.AWAITING_AUTHORIZATION):
            raise dc.DecisionError('complete source/semantic analysis before requesting a review')
        for n, item in enumerate(result['blocking']):
            add('finding-' + str(n + 1), str(item['difference']), [
                (d, f'{d}: {item["element"]}. Applies only to this exact finding; does not rewrite sources.',
                 {'kind': 'resolve-finding', 'fingerprint': item['fingerprint'], 'disposition': d}) for d in gate.DISPOSITIONS
                if d != 'custom-rule'], 'sparx-authoritative-endpoint-detail.yml', [item['fingerprint']])
        if not items:
            purpose = 'authorize-operation'
            add('resume-current-context', 'Authorize continuation through consolidation, planning and FULL materialization for this context. Not Maven, DB or deployment.',
                [('continue', 'Allow this current gate evaluation only; technical preflight remains mandatory.',
                  {'kind': 'resume', 'evaluationHash': result['evaluationHash']})],
                result.get('reviewArtifact') or ('consistency/batch-review.yml' if result.get('comparison') else 'consistency/supplemental.yml'))
    elif kind == 'historical':
        records = gate.decisions_by_id(ws / 'sparx-reviewed-decisions.yml')
        if decision_id not in records:
            raise dc.DecisionError('historical-decision-not-found')
        add('reattest-existing-decision', f'Review the entire unchanged historical decision {decision_id}, including machineEffects. No automatic migration.',
            [('reattest', 'Apply exactly this historical decision content and scope under the current sources.',
              {'kind': 'historical-decision', 'decisionId': decision_id, 'contentSha256': dc.digest(records[decision_id])})],
            'sparx-reviewed-decisions.yml')
    elif kind == 'overwrite':
        purpose = 'authorize-operation'
        plan = load_mapping(ws / 'implementation-plan.yml')
        out = plan['service']['outputDirectory']
        if not isinstance(path, str) or protected(path):
            raise dc.DecisionError('invalid-overwrite-path')
        actual = safe_path(Path(repo), out + '/' + path)
        if path not in {e['path'] for e in plan['files']['generate']}:
            raise dc.DecisionError('overwrite-not-in-plan')
        add('overwrite-exact-file', f'Permit replacing manual content at {out}/{path} by this exact implementation plan.',
            [('replace', 'Replace only the current bytes at this path, using the bound plan, in this worktree.',
              {'kind': 'overwrite', 'outputDirectory': out, 'path': path,
               'currentSha256': hashlib.sha256(actual.read_bytes()).hexdigest(),
               'planSha256': hashlib.sha256((ws / 'implementation-plan.yml').read_bytes()).hexdigest()})], 'service-spec.yml')
    else:
        raise dc.DecisionError('unknown-review-proposal-kind')
    return dr.create(repo, service, {'schemaVersion': 2, 'purpose': purpose, 'decisions': items})
