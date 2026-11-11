"""Explicit HTTP-without-Swagger source mode. Never manufactures an OpenAPI artifact."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'parse-sparx/scripts'))
from sparx_attachments import inventory, extract_text, authorized_pages
import source_currency

CONTRACT = 'sparx-http-contract.yml'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def leaf_paths(value, pointer=''):
    if isinstance(value, dict) and value:
        return [p for k, v in value.items() for p in leaf_paths(v, pointer + '/' + str(k).replace('~', '~0').replace('/', '~1'))]
    if isinstance(value, list) and value:
        return [p for i, v in enumerate(value) for p in leaf_paths(v, pointer + '/' + str(i))]
    return [pointer]


def attachment_check(ws, repo, authority, gate):
    manifest = gate.load(ws / 'sparx-attachments.yml') or {}
    require(manifest.get('kind') == 'sparx-attachments', 'target attachment inventory required')
    root = authority.get('target', {}).get('sourceRoot')
    require(manifest.get('sourceRoot') == root, 'attachment source root mismatch')
    pages = authorized_pages(authority)
    require(pages, 'no authoritative pages for attachment discovery')
    current = inventory(repo, repo / root, pages)
    require(manifest == current, 'attachment inventory incomplete or stale; regenerate from all selected branch pages')
    return gate.sha_bytes((ws / 'sparx-attachments.yml').read_bytes())


def normalized(ws, repo, service, gate):
    state = gate.load(ws / 'service-generation-state.yml') or {}
    require(state.get('targetService') == service, 'checkpoint identity mismatch')
    require((state.get('inputs') or {}).get('contractMode') == 'sparx-only', 'explicit inputs.contractMode: sparx-only required')
    require(not (ws / 'openapi-spec.yml').exists() and not (state.get('inputs') or {}).get('openapi'),
            'Sparx-only mode must not ignore an existing/selected Swagger')
    authority = gate.load(ws / 'sparx-target-authority.yml') or {}
    require(authority.get('contractMode') == 'sparx-only' and authority.get('target', {}).get('name') == service,
            'target-local --sparx-only authority required')
    require(authority.get('selection', {}).get('status') == 'resolved', 'unresolved source authority')
    root = repo / authority['target']['sourceRoot']
    require(root.resolve().is_relative_to((repo / 'input/sparx').resolve()), 'unsafe Sparx root')
    require(source_currency.sparx_state(root) == authority.get('hierarchySources', {}).get('tocFiles'), 'Sparx hierarchy changed')
    contract = gate.load(ws / CONTRACT) or {}
    require(contract.get('kind') == 'sparx-http-contract' and contract.get('targetService') == service, 'Sparx HTTP contract identity required')
    require(contract.get('unresolved') == [], 'contract ambiguities/gaps must be resolved')
    operations = contract.get('operations')
    require(isinstance(operations, list) and operations, 'no evidenced HTTP operations')
    claims = contract.get('claims') or {}
    allowed_sources = {b['path'] for b in (gate.load(ws / 'sparx-attachments.yml') or {}).get('sourceBindings', [])}
    selected = next(b for b in authority['branches'] if b['branchRootId'] == authority['selection']['authoritativeBranchRootId'])
    require(not selected.get('unresolvedHttpMethods'), 'target methods lack explicit HTTP identities; unsupported source shape')
    require(not any(o.get('ambiguity') or o.get('sparxMethodElements', 1) != 1
                    for o in selected.get('operations', [])), 'ambiguous target HTTP method evidence')
    known = {(o['method'], o['path']) for o in selected.get('operations', [])}
    seen = set()
    for op in operations:
        key = (op.get('method'), op.get('path'))
        require(key in known and key not in seen, 'unknown/duplicate target HTTP operation')
        seen.add(key)
        require(isinstance(op.get('operationId'), str) and op['operationId'].strip()
                and op.get('lifecycle', {}).get('disposition') == 'active'
                and op['lifecycle'].get('state'), 'operation identity/explicit active lifecycle required')
        require(all(k in op for k in ('parameters', 'requestBody', 'responses', 'security')), 'incomplete HTTP contract')
        require(isinstance(op['parameters'], dict) and isinstance(op['responses'], dict) and op['responses']
                and isinstance(op['security'], list), 'incomplete parameters/responses/security')
        require(all(location in ('header', 'path', 'query', 'cookie') and isinstance(values, list)
                    for location, values in op['parameters'].items()), 'invalid parameter groups')
        for location, values in op['parameters'].items():
            for parameter in values:
                require(isinstance(parameter, dict) and parameter.get('name')
                        and ('schema' in parameter or 'content' in parameter), 'parameter schema/name missing')
                require(location != 'path' or parameter.get('required') is True, 'path parameter must be required')
        require(all(re.fullmatch(r'[1-5][0-9X]{2}|default', str(code)) and isinstance(response, dict)
                    and isinstance(response.get('description'), str) for code, response in op['responses'].items()), 'invalid HTTP responses')
        require(op['requestBody'] is None or isinstance(op['requestBody'], dict) and op['requestBody'].get('content'), 'invalid request body')
    inactive = contract.get('inactiveOperations') or []
    inactive_keys = {(op.get('method'), op.get('path')) for op in inactive}
    require(not seen.intersection(inactive_keys) and seen | inactive_keys == known,
            'all discovered methods must be classified; no silent operation omission')
    require(len(inactive_keys) == len(inactive) and all(op.get('lifecycle', {}).get('disposition') == 'inactive'
                and op['lifecycle'].get('state') for op in inactive), 'unique inactive operations with explicit lifecycle required')
    pointers = leaf_paths(operations, '/operations') + (leaf_paths(inactive, '/inactiveOperations') if inactive else [])
    for pointer in pointers:
        claim = claims.get(pointer) or {}
        rel = claim.get('path', '')
        path = (repo / rel).resolve()
        require(rel in allowed_sources and rel.startswith('input/sparx/') and path.is_relative_to(root.resolve()) and path.is_file(), f'unsafe/missing/non-authoritative citation: {pointer}')
        require(gate.sha_bytes(path.read_bytes()) == claim.get('sha256'), f'stale citation: {pointer}')
        require(claim.get('locator') and str(claim.get('quote', '')).strip(), f'exact quote and locator required: {pointer}')
        require(claim['quote'] in extract_text(path), f'citation quote not found: {pointer}')
    # This is a common normalized contract shape, NOT an OpenAPI document.
    return {'service': {'title': service}, 'operations': operations, 'validation': {'valid': True, 'errors': [], 'warnings': []},
            '_contractPath': '.factory/' + CONTRACT, '_contractOwner': 'sparxContract'}


def evaluate(ws, repo, service, gate):
    result = {'status': gate.NO_AUDIT, 'blocking': [], 'resolved': [], 'orphanedResolutions': [],
              'coveredByDecision': [], 'coverageProblems': [], 'topics': [], 'evaluationHash': None,
              'problems': [], 'comparison': 'not-applicable-no-swagger', '_registry': None}
    try:
        normalized(ws, repo, service, gate)
        authority = gate.load(ws / 'sparx-target-authority.yml')
        attachments_hash = attachment_check(ws, repo, authority, gate)
        names = (CONTRACT, 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'sparx-spec.yml')
        hashes = {name: gate.sha_bytes((ws / name).read_bytes()) for name in names}
        hashes['sparx-attachments.yml'] = attachments_hash
        sparx = gate.load(ws / 'sparx-spec.yml') or {}
        require(not any((sparx.get('unresolved') or {}).values()), 'unresolved Sparx behavior')
        review = gate.load(ws / 'consistency/sparx-only-review.yml') or {}
        result['evaluationHash'] = gate.digest({'service': service, 'hashes': hashes, 'review': review})
        if review.get('reviewed') is not True or not review.get('reviewedBy') or review.get('reviewedAgainst') != hashes:
            result.update(status=gate.SEMANTIC_REVIEW_PENDING, problems=['Sparx contract, behavior and attachments semantic review absent/stale'])
        elif review.get('findings') != []:
            result.update(status=gate.BLOCKED, problems=['unresolved Sparx/attachment findings'])
        else:
            result['status'] = gate.AWAITING_AUTHORIZATION
    except (ValueError, TypeError, KeyError, OSError, StopIteration) as error:
        result.update(status=gate.BLOCKED, problems=[str(error)])
    return result
