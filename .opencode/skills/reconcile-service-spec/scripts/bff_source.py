"""Deterministic derivation of a BFF service-spec from consumed backend contracts (no Sparx, no own Swagger).

A BFF has no OpenAPI of its own. Its contract is declared in `bff-contract-definition.yml` (endpoint list + backend mapping, authored from the
user's statement) and derived from the normalized OpenAPI contracts of the backends it consumes (`backend-contracts/*.openapi-spec.yml`, produced
by parse-openapi). Operations that map to a backend operation get an explicit `bffBinding` v1 (identity passthrough with parameter forwarding); the
others are declared as explicitly omitted with the minimal contract shape given in the definition. Nothing else is invented.

Shared by the consistency gate (`bff_gate.py`) and by `consolidate_bff_spec.py`.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re

import yaml

KIND = 'bff-contract-definition'
SPEC_KIND = 'bff-contract-v1'
METHODS = ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')
DEFINITION = 'bff-contract-definition.yml'
SOURCE_PREFIX = 'input/contracts/'
SCALARS = {'string', 'integer', 'number', 'boolean'}


class SourceError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path):
    return yaml.safe_load(Path(path).read_bytes())


def placeholders(path: str) -> list:
    return re.findall(r'\{([^{}]+)\}', path)


def backend_contracts(ws: Path, repo: Path, definition: dict) -> dict:
    """{name: normalized contract} after verifying that each normalized artifact is current with its live source."""
    out = {}
    for name, entry in sorted((definition.get('backends') or {}).items()):
        source, normalized = entry.get('source'), entry.get('normalized')
        if not isinstance(source, str) or not source.startswith(SOURCE_PREFIX) or '..' in Path(source).parts:
            raise SourceError(f'backend {name}: source must be under {SOURCE_PREFIX}')
        if not isinstance(normalized, str) or Path(normalized).is_absolute() or '..' in Path(normalized).parts:
            raise SourceError(f'backend {name}: unsafe normalized path')
        live, artifact = Path(repo) / source, Path(ws) / normalized
        if not live.is_file() or not artifact.is_file():
            raise SourceError(f'backend {name}: source or normalized contract missing')
        data = load(artifact)
        recorded = (data.get('source') or {})
        if recorded.get('path') != source or recorded.get('sha256') != sha(live.read_bytes()):
            raise SourceError(f'backend {name}: the normalized contract is stale or belongs to another source')
        out[name] = data
    return out


def validate_definition(definition, service: str) -> list:
    problems = []
    if not isinstance(definition, dict) or definition.get('kind') != KIND or definition.get('schemaVersion') != 1:
        return ['invalid bff contract definition (kind/schemaVersion)']
    if definition.get('service') != service:
        problems.append('definition belongs to another service')
    basis = definition.get('basis') or {}
    if not all(isinstance(basis.get(k), str) and basis[k].strip() for k in ('noOwnSwagger', 'endpoints', 'omission')):
        problems.append('basis must quote the user statements (noOwnSwagger, endpoints, omission)')
    backends = definition.get('backends')
    if not isinstance(backends, dict) or not backends:
        problems.append('backends are required')
    operations = definition.get('operations')
    if not isinstance(operations, list) or not operations:
        return problems + ['operations are required']
    seen_ids, seen_routes = set(), set()
    for op in operations:
        oid = op.get('operationId') if isinstance(op, dict) else None
        if not isinstance(oid, str) or not re.fullmatch(r'[a-z][A-Za-z0-9]*', oid) or oid in seen_ids:
            problems.append(f'invalid or duplicate operationId {oid!r}')
            continue
        seen_ids.add(oid)
        route = (op.get('method'), op.get('path'))
        if op.get('method') not in METHODS or not isinstance(op.get('path'), str) or not op['path'].startswith('/') or route in seen_routes:
            problems.append(f'{oid}: invalid or duplicate method/path')
            continue
        seen_routes.add(route)
        if ('binding' in op) == ('omitted' in op):
            problems.append(f'{oid}: exactly one of binding / omitted is required')
        elif 'binding' in op:
            binding = op['binding']
            if not isinstance(binding, dict) or binding.get('backend') not in (backends or {}) or binding.get('method') not in METHODS \
                    or not isinstance(binding.get('path'), str) or not isinstance(binding.get('integration'), dict):
                problems.append(f'{oid}: incomplete binding')
        else:
            omitted = op['omitted']
            if not isinstance(omitted, dict) or not all(isinstance(omitted.get(k), str) and omitted[k].strip() for k in ('reason', 'authorization')):
                problems.append(f'{oid}: omitted needs reason and authorization')
                continue
            names = [p.get('name') for p in omitted.get('pathParameters') or []]
            if sorted(names) != sorted(placeholders(op['path'])):
                problems.append(f'{oid}: omitted pathParameters differ from the path placeholders')
            if any(p.get('type') not in SCALARS for p in omitted.get('pathParameters') or []):
                problems.append(f'{oid}: unsupported omitted path parameter type')
    return problems


def find_operation(normalized: dict, method: str, path: str):
    return next((o for o in normalized.get('operations') or [] if o['method'].upper() == method and o['path'] == path), None)


def derive(definition: dict, contracts: dict, service: str) -> dict:
    """The service-spec for the definition. Raises SourceError when a mapping cannot be verified against its backend contract."""
    problems = validate_definition(definition, service)
    if problems:
        raise SourceError('; '.join(problems))
    operations, omitted = [], []
    for op in definition['operations']:
        oid = op['operationId']
        if 'omitted' in op:
            omit = op['omitted']
            params = [{'name': p['name'], 'in': 'path', 'required': True,
                       'schema': {k: v for k, v in (('type', p['type']), ('format', p.get('format'))) if v}} for p in omit.get('pathParameters') or []]
            operations.append({'operationId': oid, 'method': op['method'], 'path': op['path'],
                               'contract': {'parameters': {'path': params, 'query': [], 'header': []}, 'responses': {'200': {'description': 'Omitted'}}},
                               'behavior': {'actions': []}, 'origin': {'kind': 'omitted-explicit', 'authorization': omit['authorization']}})
            omitted.append({'operationId': oid, 'reason': omit['reason'], 'authorization': omit['authorization']})
            continue
        binding = op['binding']
        backend_op = find_operation(contracts[binding['backend']], binding['method'], binding['path'])
        if backend_op is None:
            raise SourceError(f'{oid}: backend operation {binding["method"]} {binding["path"]} not found in {binding["backend"]}')
        params = backend_op.get('parameters') or {}
        path_names = [p['name'] for p in params.get('path') or []]
        if sorted(path_names) != sorted(placeholders(op['path'])) or sorted(path_names) != sorted(placeholders(binding['path'])):
            raise SourceError(f'{oid}: path parameters differ between the BFF path, the backend path and the backend contract')
        success = [code for code in backend_op.get('responses') or {} if re.fullmatch(r'2\d\d', str(code))]
        if len(success) != 1:
            raise SourceError(f'{oid}: the backend operation must declare exactly one 2xx response')
        contract = {'parameters': {w: copy.deepcopy(params.get(w) or []) for w in ('path', 'query', 'header')},
                    'responses': {success[0]: copy.deepcopy(backend_op['responses'][success[0]])}}
        body = backend_op.get('requestBody')
        if body:
            contract['requestBody'] = copy.deepcopy(body)
        integration = dict(binding['integration'])
        integration.update(method=binding['method'], forwardRequestBody=bool(body), forwardParameters=True, backendPath=binding['path'], responseMapping='identity')
        evidence = [f"{contracts[binding['backend']]['source']['path']}#{binding['method']} {binding['path']} ({backend_op['operationId']})",
                    'basis.endpoints', 'basis.noOwnSwagger']
        operations.append({'operationId': oid, 'method': op['method'], 'path': op['path'], 'contract': contract,
                           'behavior': {'actions': [{'kind': 'backend-passthrough', 'implementationComplete': True, 'evidence': evidence}]},
                           'bffBinding': {'version': 1, 'evidence': evidence, 'integration': integration},
                           'origin': {'kind': 'consumed-backend', 'backend': binding['backend'], 'backendOperationId': backend_op['operationId']}})
    return {'kind': SPEC_KIND, 'service': {'name': service, 'profile': 'bff'},
            'basis': definition['basis'], 'operations': operations, 'omittedBehavior': omitted,
            'readiness': {'contractComplete': True, 'strictImplementationReady': not omitted, 'scaffoldImplementationReady': True,
                          'implementationReady': not omitted},
            'unresolved': {'conflicts': [], 'ambiguities': [], 'missingEvidence': []},
            'warnings': [f'omitted behavior: {o["operationId"]}' for o in omitted]}
