"""Planner for services of an approved archetype whose behavior is an orchestration of outbound REST calls (no persistence).

Variant `rest-client-v1` of the archetype profile that the selected archetype resolves to (claro-spring-ms/1.0.1: Spring MVC controller, service,
D-013 ActivityLogger structure, D-014 Checkstyle gate). It is selected by `variant: rest-client-v1` in `full-planning-input.yml` and reads only
`service-spec.yml` (spec kind `rest-orchestration-v1`, produced by `consolidate_rest_integration.py`) and the planning input; never raw Sparx/OpenAPI.

No persistence is planned: no entity, repository, datasource or SQL. Outbound calls are rendered with Spring `RestTemplate` (already part of
`spring-boot-starter-web`, an archetype baseline dependency; no dependency is added). Behavior that the specification leaves unspecified (the
backend-to-contract response mapping) is recorded under `omittedBehavior` and generated as an explicit failure, never approximated.
Writes `<ws>/generation-parameters.yml` and `<ws>/implementation-plan.yml`.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import build_implementation_plan as base
import full_implementation_plan as legacy

VARIANT = 'rest-client-v1'
SPEC_KIND = 'rest-orchestration-v1'
PLANNING_INPUT = '.factory/full-planning-input.yml'
PLAN_VERSION = 1
SCOPE = 'rest-orchestration-without-response-mapping'
JAVA_KEYWORDS = set('abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null var record'.split())
UNSUPPORTED_SCHEMA_KEYS = {'minimum', 'maximum', 'minLength', 'maxLength', 'pattern', 'minItems', 'maxItems', 'oneOf', 'allOf', 'anyOf', 'additionalProperties', 'writeOnly', 'enum'}
SPARX_TYPES = {'string': 'String', 'integer': 'Integer', 'double': 'Double', 'boolean': 'Boolean', 'string.date': 'String', None: 'String'}
STATUS_NAMES = {200: 'OK', 201: 'CREATED'}
RESERVED = {'ErrorResponse', 'ServiceError', 'ErrorCatalog', 'ServiceOperationException', 'IntegrationException', 'GlobalExceptionHandler', 'RequestHeaders', 'CallerHeaders',
            'ActivityLogger', 'ConstanApi', 'SecurityConfig', 'SwaggerConfig', 'JwtRequestFilter', 'CatalogCache', 'IntegrationSupport', 'IntegrationClientConfig'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(cond, msg):
    if not cond:
        raise base.PlanError(msg)


def pascal(text: str) -> str:
    return ''.join(part[:1].upper() + part[1:] for part in re.split(r'[^A-Za-z0-9]+', text) if part)


def camel(text: str) -> str:
    value = pascal(text)
    return value[:1].lower() + value[1:]


def applies(root: Path, yaml, input_path: Path) -> bool:
    try:
        config, _ = base.read_yaml(root / input_path, root, yaml)
    except (base.PlanError, OSError, ValueError):
        return False
    return isinstance(config, dict) and config.get('variant') == VARIANT


# ------------------------------------------------------------------------------------------------------------ contract models
def scalar_type(node: dict, where: str) -> str:
    kind, fmt = node.get('type'), node.get('format')
    if kind == 'integer':
        return 'Long' if fmt == 'int64' else 'Integer'
    if kind == 'number':
        return {'double': 'Double', 'float': 'Float'}.get(fmt, 'BigDecimal')
    if kind == 'boolean':
        return 'Boolean'
    check(kind in (None, 'string'), f'unsupported schema type {kind!r} at {where}')
    return {'date': 'LocalDate', 'date-time': 'OffsetDateTime'}.get(fmt, 'String')


class Models:
    """Walk resolved OpenAPI schemas into Java DTO descriptions (fail closed on constraints that are not rendered)."""

    def __init__(self):
        self.classes = {}

    def java_type(self, node: dict, hint: str, parent: str, role: str) -> str:
        resolved = node.get('resolved', node)
        unsupported = UNSUPPORTED_SCHEMA_KEYS & set(resolved)
        check(not unsupported, f'{parent}.{hint}: unsupported schema constraints {sorted(unsupported)}')
        ref = (node.get('source') or {}).get('$ref')
        name = ref.rsplit('/', 1)[-1] if ref else None
        if 'properties' in resolved or resolved.get('type') == 'object':
            cname = name or pascal(hint)
            check(re.fullmatch(r'[A-Z][A-Za-z0-9]*', cname) is not None and cname not in RESERVED - {'ErrorResponse'}, f'unsafe or reserved DTO name {cname!r}')
            signature = repr(sorted((resolved.get('properties') or {}).keys())) + repr(sorted(resolved.get('required') or []))
            if cname in self.classes:
                check(self.classes[cname]['signature'] == signature, f'DTO {cname} is declared with different definitions')
                if role == 'request':
                    self.classes[cname]['role'] = 'request'
                return cname
            entry = {'name': cname, 'role': role, 'fields': [], 'signature': signature}
            self.classes[cname] = entry
            required = set(resolved.get('required') or [])
            for prop, sub in (resolved.get('properties') or {}).items():
                check(re.fullmatch(r'[a-z][A-Za-z0-9]*', prop) is not None and prop not in JAVA_KEYWORDS, f'unsafe DTO property {prop!r}')
                sub_resolved = sub.get('resolved', sub)
                entry['fields'].append({'name': prop, 'javaType': self.java_type(sub, prop, cname, role), 'required': prop in required,
                                        'nullable': bool(sub_resolved.get('nullable')), 'format': sub_resolved.get('format')})
            return cname
        if resolved.get('type') == 'array':
            return 'List<' + self.java_type(resolved.get('items') or {}, hint + 'Item', parent, role) + '>'
        return scalar_type(resolved, f'{parent}.{hint}')


def parameters_of(contract: dict, oid: str) -> list:
    out, seen = [], set()
    for where in ('path', 'query', 'header'):
        for param in (contract.get('parameters') or {}).get(where) or []:
            name = param['name']
            check(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', name) is not None, f'{oid}: unsafe parameter name {name!r}')
            schema = param.get('schema') or {}
            check(schema.get('type', 'string') != 'array' and 'enum' not in schema, f'{oid}: unsupported parameter schema for {name}')
            var = camel(name)
            check(var and var not in JAVA_KEYWORDS and var not in seen and var != 'body', f'{oid}: parameter variable collision for {name}')
            seen.add(var)
            kind = scalar_type(schema, f'{oid}.{name}')
            out.append({'name': name, 'in': where, 'variable': var, 'javaType': kind if where != 'query' or kind != 'OffsetDateTime' else 'String',
                        'declaredType': kind, 'format': schema.get('format'), 'required': True if where == 'path' else bool(param.get('required'))})
    check(not (contract.get('parameters') or {}).get('cookie'), f'{oid}: cookie parameters are unsupported')
    return out


# ------------------------------------------------------------------------------------------------------------ backend DTO trees
def split_path(path: str) -> list:
    return [segment for segment in re.split(r'\.', path) if segment]


def tree_of(paths: list) -> dict:
    """[{'path': 'a.b[].c', 'type': 'string'}] -> nested {name: {'array': bool, 'children': {...}, 'type': sparx type}}."""
    root = {}
    for item in paths:
        node = root
        segments = split_path(item['path'])
        for index, segment in enumerate(segments):
            array = segment.endswith('[]')
            name = segment[:-2] if array else segment
            current = node.setdefault(name, {'array': array, 'children': {}, 'type': None})
            check(current['array'] == array, f"inconsistent array notation at {item['path']}")
            if index == len(segments) - 1:
                current['type'] = item.get('type')
            node = current['children']
    return root


class BackendDtos:
    def __init__(self):
        self.classes = {}

    def add_tree(self, class_name: str, tree: dict, shared_audit: bool = True, prefix: str | None = None) -> str:
        check(class_name not in RESERVED, f'backend DTO name {class_name!r} is reserved')
        prefix = prefix or re.sub(r'Response$|Request$', '', class_name)
        fields = []
        for name, node in tree.items():
            check(re.fullmatch(r'[a-z][A-Za-z0-9]*', name) is not None and name not in JAVA_KEYWORDS, f'unsafe backend property {name!r}')
            if node['children']:
                child_prefix = prefix + pascal(name)
                child_class = 'ResponseAudit' if (shared_audit and name == 'responseAudit') else child_prefix + ('Item' if node['array'] else '')
                self.add_tree(child_class, node['children'], shared_audit, child_prefix)
                java = f'List<{child_class}>' if node['array'] else child_class
            else:
                scalar = SPARX_TYPES.get(node['type'])
                check(scalar is not None, f"unsupported Sparx type {node['type']!r} for {class_name}.{name}")
                java = f'List<{scalar}>' if node['array'] else scalar
            fields.append({'name': name, 'javaType': java})
        entry = {'name': class_name, 'fields': fields}
        previous = self.classes.get(class_name)
        check(previous is None or previous['fields'] == fields, f'backend DTO {class_name} is declared with different definitions')
        self.classes[class_name] = entry
        return class_name


def sparx_leaf_types(activities: list) -> dict:
    """{leaf property name: Sparx type} over every backend OUTPUT row (used to type same-named request fields)."""
    types = {}
    for act in activities:
        for field in ((act.get('response') or {}).get('fields') or []):
            leaf = split_path(field['path'])[-1].removesuffix('[]')
            if field.get('type'):
                types.setdefault(leaf, set()).add(field['type'])
    return {k: next(iter(v)) for k, v in types.items() if len(v) == 1}


def convert(source_type: str, target_type: str, where: str) -> str:
    if source_type == target_type:
        return 'identity'
    if target_type == 'String' and source_type in ('Integer', 'Long', 'Double', 'BigDecimal'):
        return 'valueOf'
    if target_type == 'String' and source_type in ('LocalDate', 'OffsetDateTime'):
        return 'toString'
    check(False, f'{where}: no evidence-backed conversion from {source_type} to {target_type}')


# ------------------------------------------------------------------------------------------------------------ build
def build(root: Path, yaml, input_path: Path):
    ws = (root / input_path).parent
    spec = base.read_yaml(ws / 'service-spec.yml', root, yaml)[0]
    config = base.read_yaml(root / input_path, root, yaml)[0]
    target = config['target']
    check(config.get('variant') == VARIANT, f'the planning input does not select variant {VARIANT}')
    check(spec.get('specKind') == SPEC_KIND, f'service-spec is not of kind {SPEC_KIND}')
    check(target['service'] == spec['service']['name'], 'Target and service-spec disagree.')
    archetype_root = root / target['archetype']
    archetype = base.read_yaml(archetype_root / 'archetype.yml', root, yaml)[0]
    check((archetype.get('archetype') or {}).get('id') == 'claro-spring-ms' or (archetype.get('identity') or {}).get('name') == 'claro-spring-ms',
          'variant rest-client-v1 is implemented for the claro-spring-ms archetype only')
    ready = spec.get('readiness') or {}
    check(ready.get('contractComplete') is True and ready.get('restOrchestrationGenerationReady') is True, 'service-spec is not ready for REST orchestration generation.')
    unresolved = spec.get('unresolved') or {}
    check(not any(unresolved.get(k) for k in ('conflicts', 'ambiguities', 'missingEvidence')), 'service-spec carries unresolved blocking items; nothing is invented.')
    check(not (spec.get('inactive') or {}).get('operations'), 'inactive operations must be reconciled before planning.')
    check(re.fullmatch(r'[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+', target['base_package']) is not None, 'Unsafe Java package.')
    out_dir = Path(target['output_directory'])
    check(not out_dir.is_absolute() and out_dir.parts[:1] == ('output',) and '..' not in out_dir.parts and out_dir.as_posix() == f"output/{target['service']}", 'Output must be output/<service>.')
    tech = config.get('technical') or {}
    prefix = pascal(target['service'])
    app_class = (tech.get('application_class') or prefix + 'Application')
    check(re.fullmatch(r'[A-Z][A-Za-z0-9]*Application', app_class) is not None, 'Unsafe application class name.')
    domain = re.sub(r'Application$', '', app_class)
    names = {'api': domain + 'Api', 'controller': domain + 'Controller', 'service': domain + 'Service', 'serviceImpl': domain + 'ServiceImpl',
             'validator': domain + 'Validator', 'backendMapper': domain + 'BackendMapper', 'responseMapper': domain + 'ResponseMapper'}
    models = Models()
    ops, all_activities = [], []
    header_names = None
    leaf_types = sparx_leaf_types([a for o in spec['operations'] for a in o['behavior']['activities'] if a['role'] == 'remote-call'])
    integrations = {}
    backend = BackendDtos()
    for index, op in enumerate(spec['operations']):
        oid = op['operationId']
        check(re.fullmatch(r'[A-Z][A-Za-z0-9]*', oid) is not None, f'unsafe operation identifier {oid!r}')
        contract = op['contract']
        behavior = op['behavior']
        check(behavior.get('kind') == 'remote-rest-orchestration', f'{oid}: unsupported behavior kind')
        content = (contract.get('requestBody') or {}).get('content') or {}
        check(set(content) <= {'application/json'}, f'{oid}: only JSON request bodies are supported')
        request_class = models.java_type(content['application/json']['schema'], oid + 'Request', oid, 'request') if content else None
        success = [c for c in contract['responses'] if re.fullmatch(r'2\d\d', str(c))]
        check(len(success) == 1 and int(success[0]) in STATUS_NAMES, f'{oid}: exactly one 2xx response (200/201) is required')
        success_content = contract['responses'][success[0]].get('content') or {}
        response_class = models.java_type(next(iter(success_content.values()))['schema'], oid + 'Response', oid, 'response')
        for code, response in contract['responses'].items():
            for media in (response.get('content') or {}).values():
                if str(code).startswith(('4', '5')):
                    models.java_type(media['schema'], 'ErrorResponse', oid, 'response')
        params = parameters_of(contract, oid)
        headers = [p for p in params if p['in'] == 'header']
        header_set = sorted(p['name'] for p in headers)
        check(header_names is None or header_names == header_set, f'{oid}: request headers differ across operations; per-operation header records are not supported')
        header_names = header_set
        activities = behavior['activities']
        all_activities += activities
        entry = {'operationId': oid, 'method': camel(oid), 'httpMethod': op['method'], 'path': op['path'], 'successStatus': int(success[0]),
                 'summary': contract.get('summary'), 'description': contract.get('description'),
                 'parameters': [p for p in params if p['in'] != 'header'], 'requestClass': request_class,
                 'requestRequired': bool((contract.get('requestBody') or {}).get('required')), 'responseClass': response_class,
                 'declaredResponses': sorted(int(c) for c in contract['responses']), 'activities': [], 'sparxEndEvents': behavior['endEvents'],
                 'sourceRefs': [f'.factory/service-spec.yml#/operations/{index}/behavior']}
        remote = [a for a in activities if a['role'] == 'remote-call']
        primary = remote[-1]
        for act in activities:
            step = {'order': act['order'], 'name': act['name'], 'uuid': act['uuid'], 'page': act['page'], 'pageSha256': act['pageSha256'], 'role': act['role']}
            if act['role'] == 'validation':
                step['rules'] = [{'id': r['id'], 'kind': r['kind'], 'errorCode': r['errorCode'], 'evidence': r['evidence']} for r in act['rules']]
                kinds = {r['kind'] for r in act['rules']}
                check('required-fields-informed' in kinds, f'{oid}: the validation activity has no required-fields rule')
                step['dateRange'] = None
                if 'end-not-before-begin' in kinds:
                    mapped = {m['to']: m['from'] for m in primary['request']['query'] if m['kind'] == 'field'}
                    begin, end = mapped.get('fechaInicio'), mapped.get('fechaFin')
                    check(begin and end, f'{oid}: the date-range rule needs the begin/end query mapping (fechaInicio/fechaFin) in the backend INPUT')
                    rule = next(r for r in act['rules'] if r['kind'] == 'end-not-before-begin')
                    step['dateRange'] = {'begin': begin, 'end': end, 'errorCode': rule['errorCode']}
            else:
                step.update(plan_remote_call(oid, act, primary is act, activities, params, request_class, models, backend, integrations, tech, leaf_types))
            entry['activities'].append(step)
        ops.append(entry)
    check(len({o['operationId'] for o in ops}) == len(ops), 'Duplicate operation identifiers')
    check(len({(o['httpMethod'], o['path']) for o in ops}) == len(ops), 'Duplicate method/path pairs')
    # catalogs (OpenAPI-owned): per-operation bodies, shared status/type
    catalog = spec['errorCatalog']
    codes = sorted({code for per in catalog.values() for code in per})
    errors = {code: next({k: v[code][k] for k in ('status', 'httpStatus', 'type')} for v in catalog.values() if code in v) for code in codes}
    details = {code: {oid: {'message': per[code]['message'], 'detail': per[code]['detail']} for oid, per in catalog.items() if code in per} for code in codes}
    contract_models = {n: c for n, c in models.classes.items()}
    check(not set(contract_models) & (RESERVED - {'ErrorResponse'}), 'DTO names collide with technical classes')
    check('ErrorResponse' in contract_models, 'the contract declares no ErrorResponse schema')
    for fixed in (set(names.values()) | {app_class}):
        check(fixed not in contract_models and fixed not in backend.classes, f'generated class name {fixed} collides with a DTO')
    check(not set(contract_models) & set(backend.classes), 'contract DTO names collide with backend DTO names')
    return spec, config, archetype, archetype_root, names, app_class, models, ops, integrations, backend, header_names, errors, details, all_activities


def integration_of(act: dict, tech: dict) -> dict:
    d = act['integration']
    name = d['name']
    check(re.fullmatch(r'[a-z][a-z0-9-]*', name) is not None, f'unsafe integration name {name!r}')
    check(d['type'] == 'OpenApi-Rest' and d['httpMethod'] in ('GET', 'POST'), f'{name}: only OpenApi-Rest GET/POST integrations are supported')
    connection = d['connection']
    match = re.fullmatch(r'http://ip:port(/[A-Za-z0-9/._-]+)', connection) or re.fullmatch(r'(/[A-Za-z0-9/._-]+)', connection)
    check(match is not None, f'{name}: unsupported connection {connection!r}')
    path = match.group(1)
    segment = path.rsplit('/', 1)[-1]
    method = segment if re.search(r'[A-Z]', segment) else d['httpMethod'].lower() + pascal(segment)
    check(re.fullmatch(r'[a-z][A-Za-z0-9]*', method) is not None, f'{name}: unsafe client method {method!r}')
    return {'name': name, 'client': pascal(name) + 'Client', 'propertyPrefix': f"{tech.get('integration_property_prefix', 'integration')}.{name}", 'method': method, 'httpMethod': d['httpMethod'],
            'path': path, 'hostPlaceholder': connection.startswith('http://ip:port')}


def plan_remote_call(oid, act, is_primary, activities, params, request_class, models, backend, integrations, tech, leaf_types) -> dict:
    spec_integration = integration_of(act, tech)
    name = spec_integration['name']
    entry = integrations.setdefault(name, {'name': name, 'client': spec_integration['client'], 'propertyPrefix': spec_integration['propertyPrefix'],
                                           'hostPlaceholder': spec_integration['hostPlaceholder'], 'methods': {}, 'cache': None})
    check(entry['propertyPrefix'] == spec_integration['propertyPrefix'], f'{name}: inconsistent property prefix')
    request = act['request']
    headers = request['headers']
    out = {'integration': name, 'clientMethod': spec_integration['method'], 'httpMethod': spec_integration['httpMethod'], 'path': spec_integration['path'],
           'primary': is_primary, 'properties': act.get('properties') or {}}
    # headers
    if headers['mode'] == 'forward-all-request-headers':
        out['headers'] = {'mode': 'forward-all-request-headers'}
    else:
        mappings = []
        for m in headers['mappings']:
            if m['kind'] == 'request-header':
                mappings.append({'kind': 'request-header', 'from': m['from'], 'to': m['to']})
            elif m['kind'] == 'timestamp':
                check(m['source'] == 'SYSDATE' and "yyyy-MM-dd'T'HH:mm:ssZ" in m['transformation'], f'{oid}: unsupported timestamp mapping')
                mappings.append({'kind': 'timestamp', 'to': m['to'], 'pattern': "yyyy-MM-dd'T'HH:mm:ssZ", 'clock': 'injectable-system-default-zone'})
            elif m['kind'] == 'property':
                prop = (act.get('properties') or {}).get(m['property'])
                check(prop is not None, f"{oid}: header property {m['property']} has no value in the activity properties")
                mappings.append({'kind': 'constant', 'to': m['to'], 'value': prop['value'], 'source': f"Sparx property {m['property']}"})
        out['headers'] = {'mode': 'mapped', 'mappings': mappings}
    # query / body mapping
    api_params = {p['name']: p for p in params}
    query = []
    for m in request['query']:
        if m['kind'] == 'null':
            continue
        if m['kind'] == 'catalog-lookup':
            query.append({'to': m['to'], 'kind': 'catalog-lookup', 'matchField': m['matchField'], 'activityOrder': m['activityOrder'], 'backendType': 'String'})
            continue
        param = api_params.get(m['from'])
        check(param is not None, f"{oid}: query mapping source {m['from']!r} is not an API parameter")
        btype = SPARX_TYPES.get(leaf_types.get(m['to']), 'String') if m['to'] in leaf_types else 'String'
        query.append({'to': m['to'], 'kind': 'field', 'from': m['from'], 'variable': param['variable'], 'sourceType': param['javaType'], 'backendType': btype,
                      'conversion': convert(param['javaType'], btype, f"{oid}.{m['to']}")})
    out['query'] = query
    out['nullQueryParameters'] = [m['to'] for m in request['query'] if m['kind'] == 'null']
    body = request['body']
    if body['fields']:
        out['body'] = plan_body(oid, body, request_class, models, backend, leaf_types)
    else:
        out['body'] = None
    # response DTO
    response = act['response']
    root_label = response.get('root')
    class_name = pascal(root_label) if root_label else pascal(spec_integration['method']) + 'Response'
    tree = tree_of(response['fields'])
    out['responseClass'] = backend.add_tree(class_name, tree)
    out['responseFields'] = [f['path'] for f in response['fields']]
    # outcomes
    rules = act['outcomes']['rules']
    unavailable = act['outcomes']['unavailable']
    check(unavailable is not None, f'{oid}: activity {act["order"]} has no unavailable/timeout/internal-error rule')
    kinds = [r['kind'] for r in rules]
    if kinds == ['http-status-equals', 'otherwise']:
        out['outcome'] = {'kind': 'http-status-200', 'otherwiseError': rules[1]['errorCode']}
        entry['methods'][spec_integration['method']] = {'httpMethod': spec_integration['httpMethod'], 'path': spec_integration['path'], 'responseClass': out['responseClass'],
                                                         'requestClass': out['body']['class'] if out['body'] else None, 'cacheable': True}
        refresh = (act.get('properties') or {}).get('propRefreshCache')
        if refresh:
            check(refresh.get('unit') == 'en milisegundos' and refresh['value'].isdigit(), f'{oid}: unsupported propRefreshCache declaration')
            entry['cache'] = {'refreshMs': int(refresh['value']), 'source': 'Sparx property propRefreshCache'}
    elif set(kinds) <= {'response-code-zero', 'response-code-zero-and-list-not-empty', 'response-code-zero-and-list-empty', 'otherwise'} and 'otherwise' in kinds:
        otherwise = next(r for r in rules if r['kind'] == 'otherwise')['errorCode']
        empty = next((r['errorCode'] for r in rules if r['kind'] == 'response-code-zero-and-list-empty'), None)
        needs_list = 'response-code-zero-and-list-not-empty' in kinds
        check(needs_list == (empty is not None), f'{oid}: list-not-empty and list-empty rules must come together')
        out['outcome'] = {'kind': 'response-code-zero', 'otherwiseError': otherwise, 'emptyListError': empty, 'listPath': None, 'successCode': '0'}
        if needs_list:
            paths = [f['path'] for f in response['fields'] if split_path(f['path'])[-2:-1] and split_path(f['path'])[-2] == 'listaCuotas[]']
            check(paths, f'{oid}: the list named by the rule is not present in the backend OUTPUT')
            parent = split_path(paths[0])[:-1]
            out['outcome']['listPath'] = list(parent)
        entry['methods'][spec_integration['method']] = {'httpMethod': spec_integration['httpMethod'], 'path': spec_integration['path'], 'responseClass': out['responseClass'],
                                                         'requestClass': out['body']['class'] if out['body'] else None, 'cacheable': False}
    else:
        check(False, f'{oid}: unsupported outcome rule set {kinds}')
    out['unavailableError'] = {'family': 'IDT', 'timeout': 'IDT1', 'unavailable': 'IDT2', 'unexpected': 'IDT3',
                               'basis': 'IDT identifiers of the OpenAPI examples: TimeoutException/ServiceUnavailable/InternalError'}
    out['evidence'] = {'outcomeLines': [r['evidence'] for r in rules]}
    # a lookup step is consumed by a later catalog-lookup mapping; otherwise the result is not used
    consumers = [m for later in activities if later['role'] == 'remote-call' for m in (later['request']['query'] + later['request']['body']['fields'])
                 if m['kind'] == 'catalog-lookup' and m['activityOrder'] == act['order']]
    out['lookupConsumers'] = [{'matchField': m['matchField'], 'to': m['to']} for m in consumers]
    check(is_primary or out['outcome']['kind'] == 'http-status-200', f'{oid}: a non-primary call must be a status-checked catalog call')
    return out


def plan_body(oid, body, request_class, models, backend, leaf_types) -> dict:
    root = body['rootLabel']
    check(root is not None and re.fullmatch(r'[a-z][A-Za-z0-9]*Request', root) is not None, f'{oid}: unsupported body root label {root!r}')
    check(request_class in models.classes, f'{oid}: the backend body needs an API request body')
    api = {f['name']: f for f in models.classes[request_class]['fields']}
    assignments, items = [], {}
    paths = []
    for m in body['fields']:
        to_path, segs = m['to'], split_path(m['to'])
        if m['kind'] == 'catalog-lookup':
            assignments.append({'to': to_path, 'kind': 'catalog-lookup', 'matchField': m['matchField'], 'activityOrder': m['activityOrder'], 'backendType': 'String'})
            paths.append({'path': to_path, 'type': 'string'})
            continue
        src = m['from']
        leaf_to = segs[-1].removesuffix('[]')
        btype = SPARX_TYPES.get(leaf_types.get(leaf_to), 'String') if leaf_to in leaf_types else 'String'
        if '[]' in to_path:
            check(src.count('[]') == 1 and len(segs) == 2 and segs[0].endswith('[]') and len(split_path(src)) == 2, f'{oid}: only one-level list mappings are supported')
            src_list, src_leaf = split_path(src)[0].removesuffix('[]'), split_path(src)[1]
            field = api.get(src_list)
            check(field is not None and field['javaType'].startswith('List<'), f'{oid}: list source {src_list} is not a request list')
            item_class = field['javaType'][5:-1]
            item_field = next((f for f in models.classes[item_class]['fields'] if f['name'] == src_leaf), None)
            check(item_field is not None, f'{oid}: list item field {src_leaf} is not declared')
            group = items.setdefault(segs[0].removesuffix('[]'), {'sourceList': src_list, 'sourceClass': item_class, 'fields': []})
            check(group['sourceList'] == src_list, f'{oid}: a backend list maps from more than one request list')
            group['fields'].append({'to': leaf_to, 'from': src_leaf, 'sourceType': item_field['javaType'], 'backendType': btype, 'conversion': convert(item_field['javaType'], btype, f'{oid}.{to_path}')})
            paths.append({'path': to_path, 'type': {'String': 'string', 'Integer': 'integer', 'Double': 'double'}[btype]})
        else:
            field = api.get(src)
            check(field is not None, f'{oid}: body mapping source {src!r} is not a request field')
            assignments.append({'to': to_path, 'kind': 'field', 'from': src, 'sourceType': field['javaType'], 'backendType': btype, 'conversion': convert(field['javaType'], btype, f'{oid}.{to_path}')})
            paths.append({'path': to_path, 'type': {'String': 'string', 'Integer': 'integer', 'Double': 'double'}[btype]})
    tree = tree_of(paths)
    class_name = pascal(root)
    backend.add_tree(class_name, tree, shared_audit=False)
    return {'class': class_name, 'rootLabel': root, 'assignments': assignments, 'lists': [{'to': k, **v} for k, v in sorted(items.items())],
            'rootIsWrapper': False}


def activity_plan(ops: list, tech: dict, archetype: dict) -> tuple:
    convention = archetype.get('activity_logging') or {}
    legacy.check(convention.get('mandatory') is True and convention.get('approved_decision') == 'D-013', 'The archetype declares no mandatory activity-logging convention (D-013).')
    constants, per_op = {}, []
    for op in ops:
        sequence = []
        for act in op['activities']:
            ordinal, value, constant = legacy.activity_key(act['name'])
            entry = constants.setdefault(constant, {'constant': constant, 'value': value, 'activityName': act['name'], 'role': act['role'], 'usedBy': [], 'sources': []})
            check(entry['value'] == value and entry['role'] == act['role'], f'Activity constant {constant} would be ambiguous across operations')
            entry['usedBy'].append(op['operationId'])
            entry['sources'].append({'operationId': op['operationId'], 'activityUuid': act['uuid'], 'page': act['page'], 'pageSha256': act['pageSha256']})
            act['constant'] = constant
            sequence.append({'order': act['order'], 'constant': constant, 'value': value, 'sourceActivity': act['name'], 'role': act['role']})
        per_op.append({'operationId': op['operationId'], 'activitySequence': sequence})
    for entry in constants.values():
        if entry['role'] == 'remote-call':
            entry['logMessages'] = {f"LOG_TIMEOUT_{entry['constant']}": f"Timeout en la actividad {entry['value']}: ",
                                    f"LOG_ERROR_INTEGRACION_{entry['constant']}": f"Error de integracion en la actividad {entry['value']}: "}
    return sorted(constants.values(), key=lambda e: e['constant']), per_op


def artifacts(root: Path, yaml, input_path: Path):
    ws = (root / input_path).parent
    (spec, config, archetype, archetype_root, names, app_class, models, ops, integrations, backend, header_names, errors, details, all_activities) = build(root, yaml, input_path)
    target, tech = config['target'], config.get('technical') or {}
    constants, per_op = activity_plan(ops, tech, archetype)
    roles = legacy.header_roles(header_names, tech.get('header_roles') or {})
    header_params = [{'name': n, 'variable': camel(n)} for n in header_names]
    contract_models = [{'name': n, 'role': c['role'], 'fields': c['fields']} for n, c in sorted(models.classes.items())]
    pkg = target['base_package']
    main, test = f"src/main/java/{pkg.replace('.', '/')}", f"src/test/java/{pkg.replace('.', '/')}"
    files = []

    def add(path, ctype, **extra):
        files.append({'path': path, 'action': 'create', 'componentType': ctype, **extra})
    for cname, c in sorted(models.classes.items()):
        add(f"{main}/dto/{'request' if c['role'] == 'request' else 'response'}/{cname}.java", 'contract-dto')
    add(f'{main}/dto/request/RequestHeaders.java', 'request-headers-model', components=[r for r in ('transactionId', 'userId', 'applicationName') if r in roles])
    add(f'{main}/dto/request/CallerHeaders.java', 'request-headers-model-all')
    add(f"{main}/controller/{names['api']}.java", 'contract-api-interface')
    add(f"{main}/controller/impl/{names['controller']}.java", 'controller-implementation')
    add(f"{main}/service/{names['service']}.java", 'application-service-contract')
    add(f"{main}/service/impl/{names['serviceImpl']}.java", 'application-service-implementation')
    add(f"{main}/validation/{names['validator']}.java", 'business-validator')
    add(f"{main}/mapper/{names['backendMapper']}.java", 'backend-request-mapper')
    add(f"{main}/mapper/{names['responseMapper']}.java", 'response-mapper-omitted')
    add(f'{main}/exception/ServiceError.java', 'service-error-catalog')
    add(f'{main}/exception/ErrorCatalog.java', 'service-error-catalog')
    add(f'{main}/exception/ServiceOperationException.java', 'internal-typed-exception')
    add(f'{main}/exception/IntegrationException.java', 'internal-typed-exception')
    add(f'{main}/exception/GlobalExceptionHandler.java', 'central-contract-error-advice')
    add(f'{main}/utils/ActivityLogger.java', 'archetype-activity-logger')
    add(f'{main}/utils/ConstanApi.java', 'activity-constants', activityConstants=constants)
    add(f'{main}/client/config/IntegrationClientConfig.java', 'rest-client-config')
    add(f'{main}/client/IntegrationSupport.java', 'rest-client-support')
    add(f'{main}/client/CatalogCache.java', 'rest-client-support')
    for name, item in sorted(integrations.items()):
        add(f"{main}/client/{item['client']}.java", 'rest-client')
    for cname in sorted(backend.classes):
        add(f'{main}/client/dto/{cname}.java', 'rest-client-dto')
    add(f"{test}/controller/impl/{names['controller']}Test.java", 'unit-test-junit5')
    add(f"{test}/service/impl/{names['serviceImpl']}Test.java", 'unit-test-junit5')
    add(f"{test}/validation/{names['validator']}Test.java", 'unit-test-junit5')
    add(f'{test}/exception/GlobalExceptionHandlerTest.java', 'unit-test-junit5')
    add(f'{test}/client/IntegrationClientsTest.java', 'unit-test-junit5')
    add(f'{test}/utils/ActivityLoggerTest.java', 'archetype-activity-logger-test')
    planned = {f['path'] for f in files}
    from artifact_integrity import template_paths
    render = lambda s: s.replace('__BASE_PACKAGE_PATH__', pkg.replace('.', '/')).replace('__APPLICATION_CLASS__', app_class)
    for relative in template_paths(archetype_root):
        path = render(relative)
        check(path not in planned or path.endswith(('/utils/ActivityLogger.java', '/utils/ConstanApi.java', '/utils/ActivityLoggerTest.java')),
              f'Generated file {path} collides with an archetype template file.')
    gate = legacy.checkstyle_gate(archetype, archetype_root, [f['path'] for f in files])
    spec_raw = (ws / 'service-spec.yml').read_bytes()
    values = {'base_package': pkg, 'base_package_path': pkg.replace('.', '/'), 'group_id': target['group_id'], 'project_version': target['project_version'],
              'service_name': base.technical_identifier(target['service']), 'artifact_id': base.technical_identifier(target['service']), 'application_class': app_class}
    for key in ('application_log_level', 'corporate_logger_level', 'http_log_level', 'root_log_level', 'log_time_zone', 'jwt_roles_claim'):
        check(tech.get(key) is not None, f'technical.{key} is required in the planning input')
        values[key] = tech[key]
    values['java_version'] = archetype['platform']['java']['version']
    values['spring_boot_version'] = archetype['platform']['spring_boot']['version']
    params = {'version': 2, 'mode': 'full', 'variant': VARIANT, 'service': target['service'], 'values': values, 'approvedResolutions': [],
              'resolved': [{'name': k, 'value': v, 'status': 'approved-target-value' if k in ('group_id', 'base_package', 'project_version') else 'technical-implementation-choice',
                            'source': f'{PLANNING_INPUT}#/' + ('target' if k in target else 'technical'), 'required': True} for k, v in sorted(values.items())],
              'unresolved': [],
              'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'sha256': sha(spec_raw)},
                         'archetype': {'path': target['archetype'], 'fingerprint': base.archetype_fingerprint(archetype_root)},
                         'planningInput': {'path': PLANNING_INPUT, 'sha256': sha((root / input_path).read_bytes())}},
              'functional': {'technical': tech, 'persistence': {'technology': 'none', 'reason': 'authoritative Sparx behavior only calls REST backends; no persistence is specified',
                                                                'archetypeBaselineDependenciesKept': True},
                             'runtimeEnvironmentOnly': ['JWT_SECRET_KEY'], 'integrationProperties': 'see required-properties.yml (never written to application*.properties)'},
              'readiness': {'functionalGenerationReady': True, 'deploymentGenerationAuthorized': False}, 'secretsStored': False, 'validation': {'errors': []}}
    params_raw = base.dump_yaml(params, yaml)
    omitted = []
    for op in ops:
        omitted.append({'operationId': op['operationId'], 'behavior': 'backend-response-to-contract-response-mapping',
                        'reason': 'Sparx declares no destination for the backend OUTPUT rows: field mapping, status code and envelope (code/message) source are unspecified',
                        'generated': 'response mapper method throws UnsupportedOperationException; everything before it (validation, catalog lookups, backend call, IDF/IDT outcomes) is implemented',
                        'reference': next(u for u in spec['unspecifiedMappings'] if u['operationId'] == op['operationId'])})
    plan = {'plan': {'version': PLAN_VERSION, 'mode': 'full', 'profile': legacy_profile(), 'variant': VARIANT, 'scope': SCOPE, 'strictModeAuthorized': False,
                     'generatorMustOmitUnresolvedBehavior': True},
            'service': {'name': target['service'], 'package': pkg, 'packagePath': pkg.replace('.', '/'), 'groupId': target['group_id'], 'projectVersion': target['project_version'],
                        'javaVersion': str(values['java_version']), 'springBootVersion': str(values['spring_boot_version']), 'outputDirectory': target['output_directory'], 'applicationClass': app_class},
            'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'artifactSha256': sha(spec_raw)}, 'archetype': params['inputs']['archetype'],
                       'generationParameters': {'path': '.factory/generation-parameters.yml', 'sha256': sha(params_raw)}, 'planningInput': params['inputs']['planningInput']},
            'readiness': {'functionalGenerationReady': True, 'deploymentGenerationAuthorized': False, 'strictImplementationReady': False,
                          'reason': 'response mapping is unspecified in Sparx; see omittedBehavior'},
            'technicalProfile': {'persistence': 'none', 'jpa': False, 'outboundHttp': 'spring-web RestTemplate (spring-boot-starter-web baseline dependency)', 'tests': 'junit5+mockito+spring-test',
                                 'names': names, 'java': str(values['java_version'])},
            'activityLogging': {'decision': 'D-013', 'mandatory': True, 'archetypeSection': 'archetype.yml#/activity_logging',
                                'requestHeaders': {'location': 'dto/request/RequestHeaders', 'type': 'record', 'roles': roles,
                                                   'components': [r for r in ('transactionId', 'userId', 'applicationName') if r in roles]},
                                'callerHeaders': {'location': 'dto/request/CallerHeaders', 'components': header_params,
                                                  'note': 'all declared request headers, carried to the outbound calls exactly as the Sparx INPUT tables require'},
                                'activityConstants': constants, 'operations': per_op, 'transactionHeaderConstant': roles['transactionId']['header'],
                                'masking': 'none (reference applies none)', 'inventedActivities': False},
            'qualityGates': {'checkstyle': gate},
            'contract': {'models': contract_models, 'headers': header_params},
            'errors': {'catalog': errors, 'perOperationText': details, 'messageFormat': 'verbatim from the OpenAPI examples of each operation',
                       'placeholders': {'FIELD_NAME': 'name of the invalid parameter/field', 'OUTPUT_DETAIL': 'backend responseAudit.mensajeRespuesta', 'SERVICE_NAME': 'integration name',
                                        'ERROR_DETAIL': 'exception message'}},
            'integrations': {n: {k: v for k, v in i.items()} for n, i in sorted(integrations.items())},
            'backendDtos': [backend.classes[k] for k in sorted(backend.classes)],
            'operations': ops, 'omittedBehavior': omitted, 'incompleteOperations': [], 'assumptions': assumptions_of(ops),
            'files': {'generate': files}, 'planningBlockers': [],
            'generation': {'functionalGenerationReady': True, 'javaWritten': False, 'mavenRun': False, 'deploymentGenerationAuthorized': False}}
    return plan, params


def legacy_profile() -> str:
    import archetype_contract as ac
    return ac.LEGACY_JPA


def assumptions_of(ops: list) -> list:
    return [
        {'id': 'A-REST-1', 'topic': 'outbound HTTP client', 'statement': 'The archetype reference has no outbound HTTP client; Spring RestTemplate from the baseline spring-boot-starter-web is used (no dependency added). Temporary technical choice, not an archetype decision.'},
        {'id': 'A-REST-2', 'topic': 'backend failure classification', 'statement': 'A received HTTP response that is not 200 (catalog calls) or a body with codigoRespuesta other than 0 (backend calls) maps to the IDF code written in the Sparx CONSIDERACIONES; the absence of a response (timeout, connection failure) or an unexpected error maps to IDT1 (timeout), IDT2 (unavailable) and IDT3 (internal) whose HTTP statuses come from the OpenAPI examples.'},
        {'id': 'A-REST-3', 'topic': 'document type not found in catalog', 'statement': 'Sparx does not say what happens when documentCodeId is not in the identification-types catalog; IDF101 (invalid parameter value, 400) is used because the value is not a valid catalog id.'},
        {'id': 'A-REST-4', 'topic': 'backend body shape', 'statement': 'The labels crearCuotaRequest/actualizarCuotaRequest/*Response are treated as object names, not as JSON wrapper keys (OUTPUT paths such as responseAudit.codigoRespuesta carry no root prefix).'},
        {'id': 'A-REST-5', 'topic': 'backend field types', 'statement': 'Request field types are taken from the Sparx OUTPUT type of the same-named field when present (ids as string, numCuota integer, montoCuota double, dates as yyyy-MM-dd strings) and string otherwise; contract values are converted only with String.valueOf/toString.'},
        {'id': 'A-REST-6', 'topic': 'activity order', 'statement': 'The execution order of activities is the ordinal prefix of their Sparx names (consecutive 1..n).'},
        {'id': 'A-REST-7', 'topic': 'parameters call', 'statement': 'The `parameters` call (GET /api/v1/parameters, no filters) is executed and its HTTP status checked as Sparx specifies, but no Sparx step consumes its result (config[].clave/valor have no later use).'},
        {'id': 'A-REST-8', 'topic': 'catalog cache', 'statement': 'propRefreshCache (milliseconds, 3600000) is read as a time-to-live for the catalog calls that declare it.'},
        {'id': 'A-REST-9', 'topic': 'payments list rule', 'statement': 'For the paid-installments query the rule "listaCuotas[].size" is evaluated over the installments of all responseData groups.'}]


def write_plan(root: Path, yaml, input_path: Path) -> int:
    from artifact_integrity import write_atomic, safe_path
    plan, params = artifacts(root, yaml, input_path)
    ws = (root / input_path).parent
    plan_raw, params_raw = base.dump_yaml(plan, yaml), base.dump_yaml(params, yaml)
    destinations = [safe_path(ws, name) for name in ('generation-parameters.yml', 'implementation-plan.yml')]
    for destination, data in zip(destinations, (params_raw, plan_raw)):
        write_atomic(destination, data)
    print({'mode': 'full', 'variant': VARIANT, 'operations': len(plan['operations']), 'omittedBehavior': [o['operationId'] for o in plan['omittedBehavior']],
           'plannedFiles': len(plan['files']['generate']), 'planSha256': sha((ws / 'implementation-plan.yml').read_bytes())})
    return 0
