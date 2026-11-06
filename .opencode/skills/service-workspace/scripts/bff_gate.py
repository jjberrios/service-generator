"""Source-only gate for a BFF service that has no Sparx export and no OpenAPI of its own.

The Sparx-vs-Swagger comparison is not applicable (no Sparx exists for a BFF); it is never faked as a successful audit. The sources are the
consumed backend contracts plus the user-authored `bff-contract-definition.yml`. The gate still requires verified factual mappings, a current
semantic review (`consistency/supplemental.yml`) and the existing explicit resume authorization (operational review grant). A profile label alone
never releases a workspace.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'reconcile-service-spec' / 'scripts'))
sys.path.insert(0, str(HERE.parents[1] / 'plan-service-implementation' / 'scripts'))
import archetype_contract as ac  # noqa: E402
import bff_source as source  # noqa: E402

COMPARISON = 'not-applicable-bff-no-sparx'
SPARX_ARTIFACTS = ('sparx-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'openapi-spec.yml')


def selected_profile(ws, repo, gate):
    state = gate.load(Path(ws) / 'service-generation-state.yml') or {}
    path = (state.get('archetype') or {}).get('path', '')
    if not isinstance(path, str) or not path.startswith('archetypes/') or '\\' in path or ':' in path or set(path.split('/')) & {'', '.', '..'}:
        return None
    manifest = Path(repo) / path / 'archetype.yml'
    if not manifest.is_file():
        return None
    return (gate.load(manifest) or {}).get('generation', {}).get('profile'), Path(repo) / path


def applies(ws, repo, gate):
    selected = selected_profile(ws, repo, gate)
    return bool(selected) and selected[0] == ac.BFF


def review_hashes(ws, root, gate, definition, contracts):
    """The facts a semantic review attests to: definition, backend contracts (source and normalized) and the selected archetype manifest."""
    return {'definitionSha256': gate.sha_bytes((Path(ws) / source.DEFINITION).read_bytes()),
            'archetypeSha256': gate.sha_bytes((Path(root) / 'archetype.yml').read_bytes()),
            'backends': {name: {'source': c['source']['sha256'], 'normalized': gate.sha_bytes((Path(ws) / definition['backends'][name]['normalized']).read_bytes())}
                         for name, c in sorted(contracts.items())}}


def evaluate(ws, repo, service, gate):
    ws, repo = Path(ws), Path(repo)
    result = {'status': gate.NO_AUDIT, 'blocking': [], 'resolved': [], 'orphanedResolutions': [], 'coveredByDecision': [], 'coverageProblems': [],
              'topics': [], 'evaluationHash': None, 'problems': [], 'comparison': COMPARISON, 'reviewArtifact': 'consistency/supplemental.yml',
              '_registry': None}
    try:
        state = gate.load(ws / 'service-generation-state.yml') or {}
        if state.get('targetService') != service:
            raise ValueError('checkpoint service mismatch')
        profile, root = selected_profile(ws, repo, gate)
        if profile != ac.BFF or not root.resolve().is_relative_to((repo / 'archetypes').resolve()):
            raise ValueError('selected archetype is not a BFF')
        present = [name for name in SPARX_ARTIFACTS if (ws / name).exists()]
        if present:
            raise ValueError(f'a BFF without Sparx must not carry Sparx/OpenAPI artifacts that would be silently ignored: {present}')
        if not (ws / source.DEFINITION).is_file():
            raise ValueError(f'{source.DEFINITION} is missing')
        definition = source.load(ws / source.DEFINITION)
        problems = source.validate_definition(definition, service)
        if problems:
            raise ValueError('; '.join(problems))
        contracts = source.backend_contracts(ws, repo, definition)
        derived = source.derive(definition, contracts, service)
        spec_path = ws / 'service-spec.yml'
        if spec_path.is_file() and gate.load(spec_path) != derived:
            raise ValueError('service-spec.yml differs from the deterministic derivation of the definition and backend contracts')
        hashes = review_hashes(ws, root, gate, definition, contracts)
        review = gate.load(ws / 'consistency/supplemental.yml') or {}
        result['evaluationHash'] = gate.digest({'service': service, 'hashes': hashes, 'review': review})
        if review.get('reviewed') is not True or not str(review.get('reviewedBy', '')).strip() or review.get('reviewedAgainst') != hashes:
            result['status'] = gate.SEMANTIC_REVIEW_PENDING
            result['problems'] = ['BFF semantic review absent or stale (definition, backend contracts or archetype changed)']
        elif review.get('findings') != []:
            result['status'] = gate.BLOCKED
            result['problems'] = ['BFF review has unresolved findings or lacks explicit findings: []']
        else:
            result['status'] = gate.AWAITING_AUTHORIZATION
    except (ValueError, TypeError, KeyError, OSError, source.SourceError) as error:
        result['status'] = gate.BLOCKED
        result['problems'] = [str(error)]
    return result
