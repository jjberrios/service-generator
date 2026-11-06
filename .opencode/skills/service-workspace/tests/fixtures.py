"""Reusable synthetic fixtures for service workspaces (no real service data, no live .factory)."""
from pathlib import Path
import hashlib
import yaml
import shutil

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

BRANCH = {'branchRootId': '0.2', 'pagePathPrefix': 'EARoot/EA2'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')


def swagger_operation(path, id_required=False):
    return {'method': 'GET', 'path': path, 'operationId': 'getItems',
            'parameters': {'header': [{'name': 'x-app-id', 'in': 'header', 'required': True, 'schema': {'type': 'string'}}],
                           'query': [{'name': 'id', 'in': 'query', 'required': id_required, 'schema': {'type': 'integer'}}], 'path': []},
            'responses': {'200': {}, '400': {}}}


def sparx_operation(path, id_required='No', extra_header=None):
    headers = [{'evidenceId': 'e-h1', 'headerrequest': 'x-app-id', 'required': 'Si', 'type': 'String'}]
    if extra_header:
        headers.append({'evidenceId': 'e-h2', 'headerrequest': extra_header, 'required': 'Si', 'type': 'String'})
    return {'method': 'GET', 'path': path, 'status': 'active', 'sparxMethod': {'name': f'GET-{path}', 'guid': '{M}', 'page': 'EARoot/EA2/EA6/m.htm'},
            'activities': [{'activity': {'name': '1. Validar', 'uuid': '{A}', 'page': 'EARoot/EA2/EA6/a.htm'},
                            'normalized': {'validation': {'headerrequest': {'rows': headers},
                                                          'query': {'rows': [{'evidenceId': 'e-q1', 'query': 'id', 'required': id_required, 'type': 'integer'}]}}}}],
            'endEvents': [{'label': '200', 'guid': '{E2}', 'page': 'e2.htm'}, {'label': '400', 'guid': '{E4}', 'page': 'e4.htm'}]}


def make_service(repo: Path, service: str, path='/api/v1/items', sparx_required='No', swagger_required=False, extra_header=None, sparx_ops=None):
    """Create contract, Sparx export root and the pipeline artifacts of a service workspace; returns the workspace directory."""
    contract = repo / 'input' / 'contracts' / f'{service}.yml'
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(f'openapi: 3.0.1\ninfo:\n  title: {service}\n', encoding='utf-8')
    (repo / 'input' / 'sparx' / 'P' / 'js' / 'data').mkdir(parents=True, exist_ok=True)
    ws = repo / '.factory' / 'services' / service
    dump(ws / 'openapi-spec.yml', {'source': {'path': f'input/contracts/{service}.yml', 'sha256': sha(contract.read_bytes())}, 'service': {'title': service},
                                   'operations': [swagger_operation(path, swagger_required)]})
    dump(ws / 'sparx-target-authority.yml', {'target': {'name': service, 'sourceRoot': 'input/sparx/P'}, 'selection': {'status': 'resolved', 'authoritativeBranchRootId': '0.2'}, 'hierarchySources': {'tocFiles': {}},
                                              'branches': [{'branchRootId': '0.2', 'operations': [], 'sparxOnlyMethods': []}]})
    dump(ws / 'sparx-authoritative-endpoint-detail.yml', {'authority': {'branch': BRANCH}, 'excludedInactiveOperations': [],
                                                           'operations': sparx_ops if sparx_ops is not None else [sparx_operation(path, sparx_required, extra_header)]})
    return ws


def review(ws: Path, reviewer='sparx-swagger-validator', unverified=None, discarded=None):
    """The agent's semantic review of prose, recorded against the exact current sources."""
    openapi = yaml.safe_load((ws / 'openapi-spec.yml').read_bytes())
    data = {'reviewed': True, 'reviewer': reviewer, 'reviewedAgainst': {'openapiSha256': openapi['source']['sha256'], 'endpointDetailSha256': sha((ws / 'sparx-authoritative-endpoint-detail.yml').read_bytes())},
            'findings': [], 'unverified': unverified or [], 'discarded': discarded or []}
    dump(ws / 'consistency' / 'supplemental.yml', data)


def make_repo(tmp: Path) -> Path:
    for folder in ('.factory', 'input', 'output', 'archetypes', '.opencode'):
        (tmp / folder).mkdir(parents=True, exist_ok=True)
    return tmp


def simulate_manual(repo, service, *, kind='gate', choice=None, decision_id=None, path=None):
    """Tests ONLY: simulate explicit manual selection, never human authentication."""
    import decision_reviews as reviews
    import review_proposals
    state_file = repo / '.factory/services' / service / 'service-generation-state.yml'
    state = yaml.safe_load(state_file.read_bytes()) if state_file.is_file() else {}
    if not (state.get('archetype') or {}).get('path'):
        arch = 'archetypes/claro-spring-ms/v1.0.1'
        if not (repo / arch).exists():
            shutil.copytree(Path(__file__).resolve().parents[4] / arch, repo / arch)
        dump(state_file, {**state, 'targetService': service, 'archetype': {'path': arch}})
    request = review_proposals.prepare(repo, service, kind, decision_id=decision_id, path=path)
    if not request.get('requestId'):
        return None
    return reviews._record(repo, service, request['requestId'], {
        d['decisionId']: ('approved', choice or d['alternatives'][0]['id']) for d in request['decisions']})


def revoke_reviews(repo, service):
    import decision_reviews as reviews
    for event_id in {g['eventId'] for g in reviews.current(repo, service)}:
        reviews._revoke(repo, service, event_id)


def java_files(*roots: Path) -> list[str]:
    return sorted(str(p) for root in roots if root.exists() for p in root.rglob('*.java'))
