"""Source-only batch gate. HTTP is N/A, never a fabricated successful Swagger audit.

Still requires current authoritative Sparx, explicit semantic review and the existing
human resume authorization. A profile label alone can never release a workspace.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'plan-service-implementation' / 'scripts'))
import batch_evidence
from batch_shell_contract import PROFILE, features_of, require, validate


def evaluate(ws, repo, service, gate):
    result = {'status': gate.NO_AUDIT, 'blocking': [], 'resolved': [], 'orphanedResolutions': [],
              'coveredByDecision': [], 'coverageProblems': [], 'topics': [], 'evaluationHash': None,
              'problems': [], 'comparison': 'not-applicable-non-http-batch', '_registry': None}
    try:
        sparx = gate.load(ws / 'sparx-spec.yml') or {}
        spec = gate.load(ws / 'service-spec.yml') if (ws / 'service-spec.yml').is_file() else dict(sparx)
        state = gate.load(ws / 'service-generation-state.yml') or {}
        require(state.get('targetService') == service, 'checkpoint service mismatch')
        path = (state.get('archetype') or {}).get('path', '')
        require(isinstance(path, str) and path.startswith('archetypes/') and '\\' not in path
                and ':' not in path and not set(path.split('/')) & {'', '.', '..'}, 'invalid selected archetype')
        root = repo / path
        require(root.resolve().is_relative_to((repo / 'archetypes').resolve()), 'archetype escapes repository')
        arch = gate.load(root / 'archetype.yml') or {}
        require((arch.get('generation') or {}).get('profile') == PROFILE
                and arch.get('generationOwnership', {}).get('apiContract') == 'not-applicable-non-http-batch',
                'selected archetype is not a non-HTTP batch')
        require(spec.get('service') == {'name': service, 'profile': 'batch-shell'}, 'batch service identity required')
        require(not (ws / 'openapi-spec.yml').exists(), 'batch workspace must not silently ignore an OpenAPI contract')
        batch = validate(spec.get('batch'), features_of(arch.get('generation') or {}))
        require(sparx.get('service') == spec['service'] and sparx.get('batch') == batch,
                'batch IR must equal the authoritative normalized Sparx behavior')
        require(not any((spec.get('unresolved') or {}).values()) and not any((sparx.get('unresolved') or {}).values()),
                'unresolved Sparx behavior/conflicts')
        require(sparx.get('service') == {'name': service, 'profile': 'batch-shell'}, 'normalized Sparx spec identity mismatch')
        require(not spec.get('operations') and not spec.get('inactive'), 'HTTP or inactive operations are not valid batch IR')
        require(not spec.get('validation', {}).get('errors'), 'invalid consolidated spec')
        authority = gate.load(ws / 'sparx-target-authority.yml') or {}
        selection = authority.get('selection') or {}
        flat = lambda name: ''.join(ch for ch in str(name).lower() if ch.isalnum())
        require(authority.get('kind') == 'sparx-target-authority' and (authority.get('hierarchySources') or {}).get('openapi') is None,
                'authority must be produced by resolve_target_authority.py --non-http')
        require(flat(authority.get('target', {}).get('name')) == flat(service) and selection.get('status') == 'resolved'
                and selection.get('authoritativeBranchRootId') is not None, 'resolved target-local Sparx authority required')
        for binding in batch['sourceBindings']:
            source = repo / binding['path']
            require(source.resolve().is_relative_to((repo / 'input/sparx').resolve()), 'source escapes Sparx root')
            require(source.is_file() and gate.sha_bytes(source.read_bytes()) == binding['sha256'], 'Sparx source missing or changed')
        batch_evidence.verify(batch, repo)
        hashes = {name: gate.sha_bytes((ws / filename).read_bytes()) for name, filename in
                  (('sparxSpecSha256', 'sparx-spec.yml'), ('authoritySha256', 'sparx-target-authority.yml'))}
        hashes['archetypeSha256'] = gate.sha_bytes((root / 'archetype.yml').read_bytes())
        review = gate.load(ws / 'consistency/batch-review.yml') or {}
        result['evaluationHash'] = gate.digest({'service': service, 'hashes': hashes, 'review': review, 'sources': batch['sourceBindings']})
        if review.get('reviewed') is not True or not str(review.get('reviewedBy', '')).strip() or review.get('reviewedAgainst') != hashes:
            result['status'] = gate.SEMANTIC_REVIEW_PENDING
            result['problems'] = ['batch semantic review absent or stale (including selected archetype)']
        elif review.get('findings') != []:
            result['status'] = gate.BLOCKED
            result['problems'] = ['batch review has unresolved findings or lacks explicit findings: []']
        else:
            # Historical authorization.yml is evidence only. The shared gate
            # applies current scoped operational reviews after factual checks.
            result['status'] = gate.AWAITING_AUTHORIZATION
    except (ValueError, TypeError, KeyError, OSError) as error:
        result['status'] = gate.BLOCKED
        result['problems'] = [str(error)]
    return result
