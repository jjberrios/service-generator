"""Deterministic consolidation of services whose authoritative Sparx behavior is an orchestration of remote REST calls (no persistence).

Reads (from the workspace presented as `.factory/`): `openapi-spec.yml`, `sparx-authoritative-endpoint-detail.yml` and `sparx-target-authority.yml`.
Writes `sparx-spec.yml` (structured, evidence-cited interpretation of the authoritative activities) and `service-spec.yml` (spec kind
`rest-orchestration-v1`: OpenAPI contract + Sparx behavior + explicit unresolved items).

Only literal, pattern-matched Sparx statements are interpreted. A statement that no pattern covers is reported under `unresolved.ambiguities`
and keeps `strictImplementationReady` false: nothing is invented. Mappings that Sparx does not specify (for example backend response fields to
the contract response fields) are reported under `unspecifiedMappings`, never approximated. HTTP statuses and error shapes come only from the
OpenAPI examples. Run through `workspace_cli.py run <service> consolidate_rest_integration.py`.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import yaml

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'plan-service-implementation' / 'scripts'))

KIND = 'rest-orchestration-v1'
VERSION = 'consolidate-rest-integration-1'
HEADER_ORIGINS = ('header request', 'headerrequest')
BODY_SECTIONS = ('body request', 'body')


class ConsolidationError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path):
    return yaml.safe_load(path.read_bytes())


def dump(value) -> bytes:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')


def ordinal_of(name: str) -> int:
    match = re.match(r'^\s*(\d+)\s*[.)-]', name)
    if not match:
        raise ConsolidationError(f'activity {name!r} has no leading ordinal; the sequence cannot be derived')
    return int(match.group(1))


def error_catalog(openapi: dict) -> dict:
    """{operationId: {subType: {status, httpStatus, type, message, detail}}} from the OpenAPI error examples (contract-owned).

    A subType must keep the same status, code and type everywhere; its message and detail text may differ per operation (kept verbatim per operation)."""
    catalog, shapes = {}, {}
    for op in openapi['operations']:
        per_op = catalog.setdefault(op['operationId'], {})
        for code, response in op['responses'].items():
            for media in (response.get('content') or {}).values():
                examples = [e.get('value') for e in (media.get('examples') or {}).values()] + ([media['example']] if media.get('example') else [])
                for value in examples:
                    if not isinstance(value, dict) or 'subType' not in value:
                        continue
                    entry = {'status': value['status'], 'httpStatus': int(value['code']), 'type': value['type'], 'message': value['message'], 'detail': value['detail']}
                    shape = {k: entry[k] for k in ('status', 'httpStatus', 'type')}
                    if shapes.setdefault(value['subType'], shape) != shape:
                        raise ConsolidationError(f"error {value['subType']} is declared with different status/code/type across operations")
                    if per_op.setdefault(value['subType'], entry) != entry:
                        raise ConsolidationError(f"{op['operationId']}: error {value['subType']} is declared twice with different content")
    return catalog


def rows_of(section) -> list:
    return [{k: v for k, v in row.items() if k != 'evidenceId'} | {'evidenceId': row.get('evidenceId')} for row in (section or {}).get('rows', [])]


def parse_input(section) -> dict:
    """INPUT table -> headers/query/body mappings (literal rows only)."""
    out = {'headers': {'mode': 'none', 'mappings': []}, 'query': [], 'body': {'rootLabel': None, 'fields': []}}
    current = None
    for row in rows_of(section):
        src, origin, dest, trans = (row.get(k) or '' for k in ('input', 'origin', 'destination', 'transformation'))
        ev = row['evidenceId']
        if not src and not origin and dest:
            low = dest.strip().lower()
            if low == 'headers':
                current = 'headers'
            elif low.replace(' ', '') in ('queryparam',):
                current = 'query'
            elif low in BODY_SECTIONS:
                current = 'body'
            elif current == 'body' and out['body']['rootLabel'] is None:
                out['body']['rootLabel'] = dest.strip()
            else:
                raise ConsolidationError(f'unrecognized INPUT section header {dest!r}')
            continue
        if current == 'headers':
            if origin.strip().lower() in HEADER_ORIGINS and dest.strip().lower() == 'headerrequest':
                out['headers']['mode'] = 'forward-all-request-headers'
            elif src == 'SYSDATE':
                out['headers']['mappings'].append({'kind': 'timestamp', 'to': dest, 'source': 'SYSDATE', 'transformation': trans, 'evidence': ev})
            elif origin.strip().lower() == 'properties':
                out['headers']['mappings'].append({'kind': 'property', 'to': dest, 'property': src, 'evidence': ev})
            elif origin.strip().lower() in HEADER_ORIGINS:
                out['headers']['mappings'].append({'kind': 'request-header', 'from': src, 'to': dest, 'evidence': ev})
                out['headers']['mode'] = 'mapped'
            else:
                raise ConsolidationError(f'unrecognized header mapping row {src!r}->{dest!r}')
        elif current == 'query':
            if src == 'NULL':
                out['query'].append({'kind': 'null', 'to': dest, 'evidence': ev})
            elif src == 'TRANSFORMACIÓN' or src.upper().startswith('TRANSFORMACI'):
                match = re.search(r'type\[id = (\w+)[^\]]*\]\.name \(Act\. (\d+)\)', trans)
                if not match:
                    raise ConsolidationError(f'unrecognized transformation for {dest!r}: {trans!r}')
                out['query'].append({'kind': 'catalog-lookup', 'to': dest, 'matchField': match.group(1), 'activityOrder': int(match.group(2)), 'catalogField': 'name',
                                     'catalogKey': 'id', 'text': trans, 'evidence': ev})
            else:
                out['query'].append({'kind': 'field', 'from': src, 'to': dest, 'transformation': trans, 'evidence': ev})
        elif current == 'body':
            if src.upper().startswith('TRANSFORMACI'):
                match = re.search(r'type\[id = (\w+)[^\]]*\]\.name \(Act\. (\d+)\)', trans)
                if not match:
                    raise ConsolidationError(f'unrecognized transformation for {dest!r}: {trans!r}')
                out['body']['fields'].append({'kind': 'catalog-lookup', 'to': dest, 'matchField': match.group(1), 'activityOrder': int(match.group(2)), 'catalogField': 'name',
                                              'catalogKey': 'id', 'text': trans, 'evidence': ev})
            else:
                out['body']['fields'].append({'kind': 'field', 'from': src, 'to': dest, 'transformation': trans, 'evidence': ev})
        else:
            raise ConsolidationError(f'INPUT row {src!r}->{dest!r} outside a known section')
    return out


def parse_output(section) -> dict:
    rows = rows_of(section)
    if not rows:
        return {'root': None, 'fields': []}
    has_root = bool(re.fullmatch(r'\w+Response', rows[0]['output'] or ''))
    head = rows[:1] if has_root else []
    return {'root': head[0]['output'] if head else None, 'rootEvidence': head[0]['evidenceId'] if head else None,
            'fields': [{'path': r['output'], 'type': r.get('type') or None, 'destination': r.get('destination') or None,
                        'transformation': r.get('transformation') or None, 'evidence': r['evidenceId']} for r in rows[len(head):]]}


def considerations(normalized) -> list:
    return [{'text': line['text'], 'evidence': (normalized['considerations'] or {}).get('evidenceId'), 'index': line['index']}
            for line in (normalized.get('considerations') or {}).get('lines', [])]


def parse_outcomes(lines: list, activity: str) -> dict:
    """Closed set of literal patterns of the Sparx CONSIDERACIONES of a remote call."""
    outcome = {'rules': [], 'unavailable': None, 'unmatched': []}
    for line in lines:
        text = line['text'].strip().lstrip('-').strip()
        ref = {'text': line['text'], 'evidence': line['evidence'], 'lineIndex': line['index']}
        code = re.search(r'\b(IDF\d+|IDT)\b', text)
        if re.search(r'HTTP STATUS = 200"?,? continuar con la siguiente actividad', text):
            outcome['rules'].append({'kind': 'http-status-equals', 'status': 200, 'then': 'continue', **ref})
        elif re.match(r'Caso contrario,? Finalizar transacci.n con (IDF\d+)$', text, re.I):
            outcome['rules'].append({'kind': 'otherwise', 'then': 'error', 'errorCode': code.group(1), **ref})
        elif re.search(r'codigoRespuesta = 0 y listaCuotas\[\]\.size > 0', text) and code:
            outcome['rules'].append({'kind': 'response-code-zero-and-list-not-empty', 'then': 'success', 'sparxCode': code.group(1), **ref})
        elif re.search(r'codigoRespuesta = 0 y listaCuotas\[\]\.size = 0', text) and code:
            outcome['rules'].append({'kind': 'response-code-zero-and-list-empty', 'then': 'error', 'errorCode': code.group(1), **ref})
        elif re.search(r'Si "codigoRespuesta = 0"', text) and code:
            outcome['rules'].append({'kind': 'response-code-zero', 'then': 'success', 'sparxCode': code.group(1), **ref})
        elif re.search(r'insumo esta NO DISPONIBLE, genera TIME-OUT u ocurre ERROR INTERNO/NO CONTROLADO', text, re.I) and code and code.group(1) == 'IDT':
            outcome['unavailable'] = {'then': 'error', 'errorFamily': 'IDT', **ref}
        else:
            outcome['unmatched'].append(ref)
    return outcome


def parse_validation(normalized, sections) -> dict:
    rules, unmatched = [], []
    required = {'headers': [], 'query': [], 'body': []}
    for section in sections or []:
        if section.get('kind') != 'columnar':
            continue
        key = {'headerrequest': 'headers', 'query-param': 'query'}.get(section.get('key'), 'body' if str(section.get('key', '')).startswith('body') else None)
        if key is None:
            continue
        for row in section.get('rows', []):
            values = row.get('values') or {}
            name = values.get(section['key'])
            if name and str(values.get('required', '')).strip().lower().startswith('s'):
                required[key].append(name)
    for line in considerations(normalized):
        text = line['text'].strip().lstrip('-').strip()
        ref = {'text': line['text'], 'evidence': line['evidence'], 'lineIndex': line['index']}
        code = re.search(r'\b(IDF\d+)\b', text)
        if re.search(r'Campos que indican necesario "Si" deben de venir informados', text) and code:
            rules.append({'id': 'required-fields', 'kind': 'required-fields-informed', 'errorCode': code.group(1), **ref})
        elif re.search(r'fecha final no debe ser menor que la fecha inicial', text) and code:
            rules.append({'id': 'date-range-order', 'kind': 'end-not-before-begin', 'errorCode': code.group(1), **ref})
        elif re.match(r'Sino continuar con la siguiente actividad', text):
            continue
        else:
            unmatched.append(ref)
    return {'rules': rules, 'unmatched': unmatched, 'requiredPerSparx': required}


def parse_properties(normalized) -> dict:
    props = {}
    lines = [x['text'] for x in ((normalized.get('variablesProperties') or {}).get('lines') or [])]
    unit = None
    for text in lines:
        if text.startswith('#'):
            unit = text.lstrip('#').strip()
            continue
        match = re.match(r'(\w+)\s*=\s*(.+)$', text)
        if match:
            props[match.group(1)] = {'value': match.group(2).strip(), **({'unit': unit} if unit else {})}
            unit = None
    return props


def interpret_operation(op: dict, openapi_op: dict) -> tuple:
    activities, unresolved = [], []
    ordered = sorted(op['activities'], key=lambda a: ordinal_of(a['activity']['name']))
    orders = [ordinal_of(a['activity']['name']) for a in ordered]
    if orders != list(range(1, len(orders) + 1)):
        raise ConsolidationError(f"{op['operationId']}: activity ordinals {orders} are not a consecutive sequence")
    for act in ordered:
        n, meta = act['normalized'], act['activity']
        base = {'order': ordinal_of(meta['name']), 'name': meta['name'], 'uuid': meta['uuid'], 'page': meta['page'], 'pageSha256': meta['pageSha256'],
                'lifecycleStatus': meta.get('status'), 'modified': meta.get('modified')}
        if n.get('activityRole') == 'validation':
            parsed = parse_validation(n, act.get('sections'))
            base |= {'role': 'validation', 'rules': parsed['rules'], 'requiredPerSparx': parsed['requiredPerSparx']}
            unresolved += [{'id': f"{op['operationId']}:act{base['order']}:validation-statement", 'operation': op['operationId'], 'statement': u, 'implementationBlocker': True} for u in parsed['unmatched']]
        elif n.get('activityRole') == 'behavior' and (n.get('descriptor') or {}).get('type') == 'OpenApi-Rest':
            d = n['descriptor']
            request = parse_input(n.get('input'))
            outcome = parse_outcomes(considerations(n), base['name'])
            base |= {'role': 'remote-call', 'integration': {'name': d['name'], 'type': d['type'], 'httpMethod': d['operation'], 'connection': d['connection'],
                                                            'descriptorEvidence': (n['descriptor'].get('sectionEvidenceId'))},
                     'properties': parse_properties(n), 'request': request, 'response': parse_output(n.get('output')),
                     'outcomes': {'rules': outcome['rules'], 'unavailable': outcome['unavailable']}}
            unresolved += [{'id': f"{op['operationId']}:act{base['order']}:outcome-statement", 'operation': op['operationId'], 'statement': u, 'implementationBlocker': True} for u in outcome['unmatched']]
        else:
            unresolved.append({'id': f"{op['operationId']}:act{base['order']}:unsupported-activity", 'operation': op['operationId'], 'statement': base['name'], 'implementationBlocker': True})
        activities.append(base)
    return activities, unresolved


def swagger_leaf_fields(schema: dict, prefix: str = '') -> list:
    node = schema.get('resolved') or schema
    out = []
    if node.get('type') == 'array':
        return swagger_leaf_fields(node.get('items') or {}, prefix + '[]')
    if node.get('type') == 'object' or 'properties' in node:
        for name, sub in sorted((node.get('properties') or {}).items()):
            out += swagger_leaf_fields(sub, f'{prefix}.{name}' if prefix else name)
        return out
    return [prefix]


def main(argv=None) -> int:
    import gate_guard
    code = gate_guard.enforce()
    if code is not None:
        return code
    root = Path.cwd().resolve()
    ws = root / '.factory'
    from artifact_integrity import write_atomic
    try:
        openapi_raw = (ws / 'openapi-spec.yml').read_bytes()
        detail_raw = (ws / 'sparx-authoritative-endpoint-detail.yml').read_bytes()
        authority_raw = (ws / 'sparx-target-authority.yml').read_bytes()
        openapi, detail, authority = yaml.safe_load(openapi_raw), yaml.safe_load(detail_raw), yaml.safe_load(authority_raw)
        service_name = (authority.get('target') or {}).get('name')
        if not service_name:
            raise ConsolidationError('sparx-target-authority has no target name')
        if detail.get('excludedInactiveOperations'):
            raise ConsolidationError('inactive operations exist; reconcile them explicitly before consolidation')
        catalog = error_catalog(openapi)
        branch = detail['authority']['branch']
        by_key = {(o['method'], o['path']): o for o in detail['operations']}
        if set(by_key) != {(o['method'], o['path']) for o in openapi['operations']}:
            raise ConsolidationError('the Sparx authoritative operations and the OpenAPI operations differ')
        decision_dir = ws / 'decision-reviews'
        reviews = sorted(p.name for p in decision_dir.glob('review-*.yml')) if decision_dir.is_dir() else []
        findings = (load(ws / 'consistency' / 'findings.yml') or {}).get('findings', [])
        gate = load(ws / 'consistency' / 'gate.yml') if (ws / 'consistency' / 'gate.yml').is_file() else {}
        sparx_ops, spec_ops, unresolved, unspecified = [], [], [], []
        for index, oapi in enumerate(openapi['operations']):
            detail_op = by_key[(oapi['method'], oapi['path'])]
            activities, op_unresolved = interpret_operation(detail_op, oapi)
            unresolved += op_unresolved
            if sum(1 for a in activities if a['role'] == 'remote-call') == 0:
                raise ConsolidationError(f"{oapi['operationId']}: no remote call found in the authoritative behavior")
            responses = {c: r for c, r in oapi['responses'].items()}
            success = [c for c in responses if c.startswith('2')]
            if len(success) != 1:
                raise ConsolidationError(f"{oapi['operationId']}: exactly one 2xx response is required")
            schema = next(iter(responses[success[0]]['content'].values()))['schema']
            primary = [a for a in activities if a['role'] == 'remote-call'][-1]
            declared_fields = swagger_leaf_fields(schema)
            mapped = {f['destination'] for f in primary['response']['fields'] if f['destination']}
            unspecified.append({'operationId': oapi['operationId'], 'kind': 'backend-response-to-contract-response', 'primaryIntegration': primary['integration']['name'],
                                'swaggerResponseFields': declared_fields, 'sparxOutputFields': [f['path'] for f in primary['response']['fields']],
                                'sparxDeclaredDestinations': sorted(mapped),
                                'reason': 'Sparx OUTPUT rows of the primary backend call declare no destination: no field-to-field mapping, status-code or envelope (code/message) source is specified',
                                'coveringFindings': [f['id'] for f in findings if (f.get('operation') or {}).get('operationId') == oapi['operationId'] and f.get('kind') == 'missing-in-sparx']})
            sparx_ops.append({'operationId': oapi['operationId'], 'method': oapi['method'], 'path': oapi['path'], 'status': detail_op['status'],
                              'sparxMethod': detail_op['sparxMethod'], 'process': detail_op['process'], 'endEvents': [e['label'] for e in detail_op['endEvents']],
                              'activities': activities})
            spec_ops.append({'operationId': oapi['operationId'], 'method': oapi['method'], 'path': oapi['path'],
                             'contract': {'summary': oapi.get('summary'), 'description': oapi.get('description'), 'tags': oapi.get('tags'), 'parameters': oapi['parameters'],
                                          'requestBody': oapi.get('requestBody'), 'responses': responses},
                             'behavior': {'kind': 'remote-rest-orchestration', 'sparxMethod': detail_op['sparxMethod'], 'process': detail_op['process'],
                                          'endEvents': [e['label'] for e in detail_op['endEvents']], 'activities': activities,
                                          'responseMapping': {'status': 'unspecified', 'reference': f"unspecifiedMappings/{oapi['operationId']}"}},
                             'unresolved': [u['id'] for u in op_unresolved]})
        blocking = [u for u in unresolved if u.get('implementationBlocker')]
        sources = {'openapi': {'path': '.factory/openapi-spec.yml', 'artifactSha256': sha(openapi_raw), 'fingerprint': openapi['source']['sha256'], 'validation': openapi['validation']},
                   'sparx': {'path': '.factory/sparx-authoritative-endpoint-detail.yml', 'artifactSha256': sha(detail_raw), 'authority': {'path': '.factory/sparx-target-authority.yml', 'artifactSha256': sha(authority_raw)},
                             'authoritativeBranch': branch}}
        resolved = [{'id': f['id'], 'classification': 'human-resolved', 'disposition': 'swagger-governs', 'scope': ['contract'], 'element': f['element'], 'operation': f['operation']['operationId'],
                     'source': '.factory/decision-reviews', 'reviews': reviews} for f in findings]
        sparx_spec = {'schemaVersion': 1, 'kind': 'sparx-spec', 'specKind': KIND, 'consolidator': VERSION, 'service': service_name, 'sources': sources,
                      'operations': sparx_ops, 'unresolved': {'ambiguities': unresolved}, 'inactive': {'operations': []}, 'readiness': {'interpretationComplete': not blocking}}
        warnings = [{'id': f"unspecified-response-mapping:{u['operationId']}", 'warning': f"{u['operationId']}: {u['reason']}; the generator omits this mapping explicitly (never approximated)"} for u in unspecified]
        service_spec = {
            'specKind': KIND, 'consolidator': VERSION,
            'service': {'name': service_name, 'contractVersion': openapi['service']['version'], 'description': openapi['service'].get('description'), 'servers': openapi['servers'],
                        'source': {'path': '.factory/openapi-spec.yml', 'artifactSha256': sha(openapi_raw)}},
            'sources': sources, 'operations': spec_ops, 'errorCatalog': catalog, 'effectiveContractDeltas': [],
            'humanDecisions': {'applied': [], 'gate': {'status': (gate or {}).get('status'), 'evaluationHash': (gate or {}).get('evaluationHash')}, 'reviews': reviews},
            'inactive': {'operations': [], 'actions': [], 'integrations': []},
            'unresolved': {'conflicts': [], 'ambiguities': unresolved, 'missingEvidence': []},
            'unspecifiedMappings': unspecified, 'resolvedConflicts': resolved,
            'persistence': {'status': 'none-in-sparx', 'note': 'the authoritative Sparx behavior never persists data: every operation calls REST backends'},
            'warnings': warnings,
            'readiness': {'contractComplete': True, 'behaviorComplete': False, 'strictImplementationReady': False, 'implementationReady': False,
                          'functionalCodeGenerationReady': False, 'scaffoldImplementationReady': not blocking, 'restOrchestrationGenerationReady': not blocking,
                          'blockers': [u['id'] for u in blocking],
                          'nonBlockingIssues': [w['id'] for w in warnings],
                          'analysisStatus': {'scope': f"authoritative Sparx branch {branch['branchRootId']} + OpenAPI + cleared consistency gate", 'implementationBlocker': bool(blocking)}},
            'validation': {'warnings': [], 'errors': []}}
        write_atomic(ws / 'sparx-spec.yml', dump(sparx_spec))
        write_atomic(ws / 'service-spec.yml', dump(service_spec))
        print({'service': service_name, 'operations': len(spec_ops), 'unresolvedBlocking': len(blocking), 'unspecifiedMappings': len(unspecified),
               'scaffoldImplementationReady': service_spec['readiness']['scaffoldImplementationReady']})
        return 0 if not blocking else 2
    except (ConsolidationError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
        print(f'consolidate_rest_integration.py: {type(error).__name__}: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
