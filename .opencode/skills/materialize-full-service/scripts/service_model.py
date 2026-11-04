"""Typed service model extracted from a FULL implementation plan (no raw sources, no domain knowledge).

`build(plan)` validates that the plan fits the single pattern supported by materializer v2 ("relational search / insert / presence-aware patch over one
JPA entity") and returns a plain dict consumed by the Java renderers. Anything else raises renderers.Unsupported with the reason, so the whole generation
stops instead of producing an approximation. Texts that reach HTTP responses come only from the contract examples; rules come only from the plan's
structured rules. Nothing here names a service, endpoint, field or message.
"""
import re

from renderers import Unsupported, ident, class_of, package_of

ENTITY_TYPES = {'String', 'Long', 'Integer', 'BigDecimal', 'LocalDateTime'}
DTO_TYPES = {'String', 'Integer', 'Long', 'Boolean', 'BigDecimal'}
CONVERTIBLE = {'Long', 'Integer', 'BigDecimal'}
STATUS_ENUM = {400: 'BAD_REQUEST', 404: 'NOT_FOUND', 409: 'CONFLICT', 500: 'INTERNAL_SERVER_ERROR', 503: 'SERVICE_UNAVAILABLE', 504: 'GATEWAY_TIMEOUT'}
ANNOTATION_IMPORTS = {'NotNull': 'jakarta.validation.constraints.NotNull', 'NotBlank': 'jakarta.validation.constraints.NotBlank', 'Email': 'jakarta.validation.constraints.Email',
                      'Size': 'jakarta.validation.constraints.Size', 'Pattern': 'jakarta.validation.constraints.Pattern', 'Min': 'jakarta.validation.constraints.Min',
                      'Max': 'jakarta.validation.constraints.Max', 'Valid': 'jakarta.validation.Valid'}
RULE_KINDS = {'pagination-pairing', 'conditional-required', 'at-least-one-of', 'failed-validation-outcome', 'validation-success-continues'}
HTTP_VERBS = {'GET': 'GetMapping', 'POST': 'PostMapping', 'PATCH': 'PatchMapping', 'PUT': 'PutMapping', 'DELETE': 'DeleteMapping'}
TYPES_WITH_FILES = ('contract-dto', 'contract-api-interface', 'controller-implementation', 'application-service-contract', 'application-service-implementation',
                    'business-validator', 'explicit-contract-data-mapper', 'jpa-specification', 'internal-query-model', 'offset-based-pageable',
                    'data-access-error-translator', 'central-contract-error-advice')


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def camel(name: str) -> str:
    parts = [p for p in re.split(r'[-_\s]+', name) if p]
    return parts[0][:1].lower() + parts[0][1:] + ''.join(cap(p) for p in parts[1:])


def snake(name: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).upper()


def need(condition, message):
    if not condition:
        raise Unsupported(message)


def header_roles(plan):
    """Planner v3 owns `roles`; `roleMapping` is an explicit legacy alias only."""
    headers = (plan.get('activityLogging') or {}).get('requestHeaders') or {}
    roles, legacy = headers.get('roles'), headers.get('roleMapping')
    need(roles is not None or legacy is not None, 'activityLogging.requestHeaders.roles is required (legacy alias: roleMapping)')
    need(roles is None or legacy is None or roles == legacy, 'requestHeaders.roles and legacy roleMapping disagree')
    roles = roles if roles is not None else legacy
    components = headers.get('components')
    need(isinstance(roles, dict) and isinstance(components, list), 'requestHeaders.roles must be a mapping and components a list')
    need(all(isinstance(c, str) for c in components) and len(set(components)) == len(components), 'requestHeaders.components contains invalid or duplicate roles')
    need(set(components) <= {'transactionId', 'userId', 'applicationName'} and 'transactionId' in components, 'requestHeaders needs a supported transactionId role')
    need(set(roles) == set(components), 'requestHeaders.roles must cover exactly the declared components')
    names = []
    for role in components:
        value = roles[role]
        need(isinstance(value, dict) and isinstance(value.get('header'), str) and bool(value['header']), f'header role {role} needs one explicit header name')
        names.append(value['header'].lower())
    need(len(set(names)) == len(names), 'ambiguous header roles: one header is assigned to multiple roles')
    return roles, components


def java_type(schema: dict) -> str:
    kind, fmt = schema.get('type'), schema.get('format')
    if kind == 'string' and fmt in (None, 'email', 'uuid', 'date-time', 'date'):
        return 'String'
    if kind == 'integer':
        return 'Long' if fmt == 'int64' else 'Integer'
    if kind == 'boolean':
        return 'Boolean'
    raise Unsupported(f'contract type {kind!r}/{fmt!r} is not supported for parameters')


def param_annotations(schema: dict) -> list:
    """Bean Validation annotations on a parameter, from declared constraints only."""
    need('enum' not in schema, 'enum constraints on parameters are not supported by this materializer version')
    out = []
    if schema.get('minLength') is not None or schema.get('maxLength') is not None:
        parts = [f'{k} = {schema[s]}' for k, s in (('min', 'minLength'), ('max', 'maxLength')) if schema.get(s) is not None]
        out.append(f'@Size({", ".join(parts)})')
    if schema.get('pattern'):
        out.append('@Pattern(regexp = "' + schema['pattern'].replace('\\', '\\\\').replace('"', '\\"') + '")')
    if schema.get('minimum') is not None:
        out.append(f'@Min({schema["minimum"]})')
    if schema.get('maximum') is not None:
        out.append(f'@Max({schema["maximum"]})')
    return out


def parse_numeric(sql_type: str):
    match = re.fullmatch(r'NUMBER\((\d+)(?:,\s*(\d+))?\)', str(sql_type or '').strip().upper())
    if not match or int(match.group(1)) == 0:
        return None
    precision, scale = int(match.group(1)), int(match.group(2) or 0)
    return {'integerDigits': precision - scale, 'scale': scale}


def example_of(response: dict):
    return (((response.get('content') or {}).get('application/json') or {}).get('example'))


def schema_ref(response: dict):
    node = (((response.get('content') or {}).get('application/json') or {}).get('schema') or {})
    ref = (node.get('source') or {}).get('$ref', '')
    return ref.rsplit('/', 1)[-1] if ref else None


def build(plan: dict) -> dict:
    svc = plan['service']
    files = plan['files']['generate']
    by_type = {}
    for entry in files:
        by_type.setdefault(entry['componentType'], []).append(entry['path'])
    has_select = any(o['actionKind'] == 'select' for o in plan['api']['operations'])
    has_page = any(o['actionKind'] == 'select' and (o.get('query') or {}).get('pagination') for o in plan['api']['operations'])
    required = ['contract-api-interface', 'controller-implementation', 'application-service-contract', 'application-service-implementation', 'business-validator', 'explicit-contract-data-mapper',
                'data-access-error-translator', 'central-contract-error-advice', 'jpa-entity', 'spring-data-jpa-repository', 'request-headers-model', 'internal-typed-exception',
                'activity-constants', 'archetype-activity-logger'] + (['jpa-specification', 'internal-query-model'] if has_select else []) + (['offset-based-pageable'] if has_page else [])
    for single in required:
        need(len(by_type.get(single, [])) == 1, f'the plan must contain exactly one {single} file')
    paths = {k: v[0] for k, v in by_type.items() if len(v) == 1}
    dto_paths = {class_of(p): p for p in by_type.get('contract-dto', [])}
    persistence = plan['persistenceModel']
    entity_fields = {}
    for field in persistence['fields']:
        need(field['javaType'] in ENTITY_TYPES, f'entity column type {field["javaType"]!r} is not supported')
        entity_fields[ident(field['property'], 'property')] = field
    keys = [f for f in persistence['fields'] if f['primaryKey']]
    need(len(keys) == 1 and keys[0]['javaType'] == 'Long', 'exactly one Long primary key is required')
    by_column = {f['physicalColumn']: f for f in persistence['fields']}
    entity_class = persistence['entityClass']
    entity_fqn = f'{package_of(paths["jpa-entity"])}.{entity_class}'

    models = {m['name']: m for m in plan['models']}
    for name, m in models.items():
        need(m['kind'] == 'contract-model', f'model {name} has the unsupported kind {m["kind"]!r}')
        need(name in dto_paths, f'model {name} has no planned contract-dto file')
        for f in m['fields']:
            base = f['javaType'].removeprefix('List<').removesuffix('>')
            need(f['javaType'] in DTO_TYPES or base in models, f'field {name}.{f["name"]} has the unsupported type {f["javaType"]!r}')
            ident(f['name'], 'field name')
            for annotation in f.get('validationAnnotations') or []:
                need(re.match(r'@(\w+)', annotation) and re.match(r'@(\w+)', annotation).group(1) in ANNOTATION_IMPORTS, f'annotation {annotation} is not supported')
    need(set(dto_paths) == set(models), 'planned DTO files and plan models differ')

    roles, components = header_roles(plan)
    need('transactionId' in components, 'a transactionId header role is required for corporate logging')
    logging_ops = {o['operationId']: o for o in plan['activityLogging']['operations']}

    ops = []
    for raw in plan['api']['operations']:
        ops.append(build_operation(raw, logging_ops, models, entity_fields, by_column, roles, components))
    kinds = [o['kind'] for o in ops]
    need(kinds.count('select') <= 1, 'more than one search operation is not supported by this materializer version')
    need(len({o['id'] for o in ops}) == len(ops), 'duplicate operation ids')
    return {'package': svc['package'], 'paths': paths, 'dtoPaths': dto_paths, 'models': models, 'entity': {'class': entity_class, 'table': (plan.get('persistenceModel') or {}).get('table'), 'fqn': entity_fqn, 'fields': entity_fields,
            'pk': keys[0]['property']}, 'ops': ops, 'headers': {'components': components, 'roles': {c: roles[c]['header'] for c in components}},
            'errors': build_errors(ops, models), 'activity': {'handlerValidation': plan['activityLogging']['handlerValidationActivity'],
                                                              'transactionHeader': plan['activityLogging']['transactionHeaderConstant']},
            'api': {'name': class_of(paths['contract-api-interface']), 'package': package_of(paths['contract-api-interface'])}}


def build_operation(raw, logging_ops, models, entity_fields, by_column, roles, components):
    contract = raw['contract']
    op_id, method = ident(raw['operationId'], 'operation id'), raw['method'].upper()
    need(method in HTTP_VERBS, f'HTTP method {method} is not supported')
    kind = raw['actionKind']
    need(kind in ('select', 'insert', 'update'), f'action kind {kind!r} is not supported')
    need((raw.get('contract') or {}).get('parameters', {}).get('cookie') in ([], None), 'cookie parameters are not supported')
    statuses = sorted(int(s) for s in raw['effectiveStatusCodes'])
    need(200 in statuses and all(s == 200 or s in STATUS_ENUM for s in statuses), f'{op_id}: unsupported HTTP statuses {statuses}')
    params = {'path': [], 'query': [], 'header': []}
    for where in params:
        for p in contract['parameters'].get(where) or []:
            schema = p['schema']
            need(p['name'] and p.get('in') == where, f'{op_id}: malformed parameter')
            params[where].append({'name': p['name'], 'java': ident(camel(p['name']), 'parameter name'), 'type': java_type(schema), 'required': bool(p.get('required')),
                                  'description': p.get('description') if isinstance(p.get('description'), str) else None,
                                  'annotations': param_annotations(schema)})
    java_names = [p['java'] for w in ('path', 'query', 'header') for p in params[w]]
    need(len(java_names) == len(set(java_names)), f'{op_id}: parameter names collide after normalization')
    header_by_role = {}
    for role in components:
        matches = [p for p in params['header'] if p['name'].lower() == roles[role]['header'].lower()]
        need(len(matches) == 1, f'{op_id}: the header {roles[role]["header"]} for {role} is missing or ambiguous in the operation')
        found = matches[0]
        header_by_role[role] = found['java']
    request_model = None
    body = contract.get('requestBody')
    if body:
        need(list((body.get('content') or {})) == ['application/json'], f'{op_id}: only application/json bodies are supported')
        request_model = schema_ref(body)
        need(request_model in models, f'{op_id}: the request model {request_model!r} is not in the plan')
    responses = {int(c): r for c, r in contract['responses'].items()}
    success_model = schema_ref(responses[200])
    need(success_model in models, f'{op_id}: the success response model is not in the plan')
    success_example = example_of(responses[200]) or {}
    need(isinstance(success_example.get('message'), str) and success_example['message'], f'{op_id}: the success message is not specified in the contract example')
    log = logging_ops[op_id]
    sequence = log['activitySequence']
    need([s['role'] for s in sequence] == ['validation', 'behavior'], f'{op_id}: only validation+behavior activity flows are supported')
    entry = log['requestEntryLogging']
    need(all(f in components for f in entry['metadataFields']), f'{op_id}: logging metadata uses an unknown header role')
    all_params = {p['name']: p for w in ('path', 'query') for p in params[w]}
    need(all(v in {p['java'] for p in params['path'] + params['query']} or v in all_params for v in entry['requestValues']), f'{op_id}: logging value is not a request parameter')
    rules = (raw['validation'] or [{}])[0].get('rules') or []
    for r in rules:
        need(r['kind'] in RULE_KINDS, f'{op_id}: validation rule kind {r["kind"]!r} is not supported')
        if r['kind'] == 'failed-validation-outcome':
            need(r['status'] == 400, f'{op_id}: failed validation must map to 400')
    op = {'id': op_id, 'method': method, 'path': raw['path'], 'kind': kind, 'summary': contract.get('summary'), 'description': contract.get('description'), 'params': params,
          'headerByRole': header_by_role, 'requestModel': request_model, 'successModel': success_model, 'successMessage': success_example['message'], 'statuses': statuses,
          'responses': {c: {'description': r.get('description') or '', 'model': schema_ref(r), 'example': example_of(r)} for c, r in responses.items()},
          'validationConstant': sequence[0]['constant'], 'behaviorConstant': sequence[1]['constant'],
          'logging': {'helper': entry['serviceHelper'], 'label': entry['metadataLabel'], 'metadata': entry['metadataFields'], 'values': entry['requestValues'],
                      'controllerMessage': entry['controller']['message'], 'controllerArgs': entry['controller']['arguments'],
                      'body': {'message': log['bodyLogging']['message'], 'type': log['bodyLogging']['type']} if log['bodyLogging']['applies'] else None}, 'rules': rules}
    need(op['logging']['body'] is None or op['logging']['body']['type'] == request_model, f'{op_id}: body logging type differs from the request model')
    if kind == 'select':
        need(request_model is None and method == 'GET', f'{op_id}: a search operation must be a GET without body')
        select_details(op, raw, models, entity_fields, by_column)
    else:
        need(request_model is not None and method in ('POST', 'PATCH', 'PUT'), f'{op_id}: write operations need a request body')
        write_details(op, raw, models, entity_fields, by_column, params, components)
    return op


def select_details(op, raw, models, entity_fields, by_column):
    query = raw['query']
    policy = query['filterPolicy']
    need(policy['combinator'] in ('OR', 'AND') and isinstance(policy['minimumActiveFilters'], int), f'{op["id"]}: unsupported filter policy')
    need(404 in op['statuses'], f'{op["id"]}: the empty-result outcome (404) is not declared; it will not be invented')
    filters, query_names = [], {p['name']: p for p in op['params']['query']}
    for f in query['filters']:
        need(f['effectiveMatch'] in ('exact', 'contains'), f'{op["id"]}: filter match {f["effectiveMatch"]!r} is not supported')
        param = query_names.get(f['parameter'])
        need(param is not None and f['modelProperty'] in entity_fields, f'{op["id"]}: filter {f["parameter"]} does not map to a declared parameter and entity property')
        entity_type = entity_fields[f['modelProperty']]['javaType']
        need(f['effectiveMatch'] == 'exact' or entity_type == 'String', f'{op["id"]}: contains matching needs a String property')
        need(param['type'] == 'String' and (entity_type == 'String' or entity_type in CONVERTIBLE), f'{op["id"]}: filter {param["name"]} needs an unsupported conversion')
        filters.append({'param': param['java'], 'prop': f['modelProperty'], 'type': entity_type, 'match': f['effectiveMatch'], 'sql': f.get('column', {}).get('dataType') or entity_fields[f['modelProperty']].get('sqlType')})
    need(filters, f'{op["id"]}: no filters')
    fixed = []
    for f in query.get('fixedPredicates') or []:
        prop = f['modelProperty']
        need(prop in entity_fields and f.get('operator') == '=', f'{op["id"]}: fixed predicate on {prop} is not supported')
        entity_type = entity_fields[prop]['javaType']
        value = f['value']
        need((entity_type in ('Integer', 'Long', 'String')) and isinstance(value, str if entity_type == 'String' else int) and not isinstance(value, bool), f'{op["id"]}: fixed predicate literal does not match {entity_type}')
        fixed.append({'prop': prop, 'type': entity_type, 'value': value})
    need(not fixed or policy['combinator'] == 'AND', f'{op["id"]}: fixed predicates require the AND combinator')
    pagination = query.get('pagination') or {}
    page_params = []
    if pagination:
        for key in ('limit', 'offset'):
            param = query_names.get((pagination.get(key) or {}).get('parameter'))
            need(param is not None and param['type'] == 'Integer', f'{op["id"]}: pagination parameter {key} must be a declared Integer parameter')
            page_params.append(param['java'])
    order = by_column.get(query['orderBy']['physicalColumn'])
    need(order is not None, f'{op["id"]}: order column is not an entity column')
    response = models[op['successModel']]
    fields = {f['name']: f for f in response['fields']}
    need({'code', 'message', 'data'} <= set(fields) and fields['code']['javaType'] == 'Integer' and fields['message']['javaType'] == 'String', f'{op["id"]}: unsupported response envelope')
    data_type = fields['data']['javaType']
    if data_type.startswith('List<'):
        data, lists, item_name = None, [{'name': None}], data_type[5:-1]
    else:
        data = models[data_type]
        lists = [f for f in data['fields'] if f['javaType'].startswith('List<')]
        need(len(data['fields']) == 1 and len(lists) == 1, f'{op["id"]}: the data model must hold exactly one list')
        item_name = lists[0]['javaType'][5:-1]
    need(item_name in models, f'{op["id"]}: list item model missing')
    items = {f['name']: f for f in models[item_name]['fields']}
    columns = []
    for c in query['selectedColumns']:
        target = c['responseField'].rsplit('.', 1)[-1]
        need(target in items and c['modelProperty'] in entity_fields, f'{op["id"]}: output mapping {c["responseField"]} does not match the response model')
        item_type, entity_type = items[target]['javaType'], entity_fields[c['modelProperty']]['javaType']
        need(item_type == entity_type or (item_type == 'String' and entity_type in CONVERTIBLE), f'{op["id"]}: output {target} needs an unsupported conversion')
        columns.append({'field': target, 'prop': c['modelProperty'], 'entityType': entity_type, 'itemType': item_type, 'enum': (items[target].get('declaredConstraints') or {}).get('enum')})
    need(columns, f'{op["id"]}: no selected columns')
    op.update({'filters': filters, 'fixed': fixed, 'policy': {'min': policy['minimumActiveFilters'], 'combinator': policy['combinator']}, 'page': page_params, 'orderProp': order['property'],
               'dataModel': data['name'] if data else None, 'listProp': lists[0]['name'], 'itemModel': item_name, 'columns': columns, 'criteriaType': None})


def write_details(op, raw, models, entity_fields, by_column, params, components):
    request = models[op['requestModel']]
    request_fields = {f['name']: f for f in request['fields']}
    need(404 in op['statuses'] or op['kind'] == 'insert', f'{op["id"]}: the not-found outcome (404) is not declared; it will not be invented')
    need(op['kind'] in ('insert', 'update'), f'{op["id"]}: unsupported write kind')
    response = models[op['successModel']]
    need({f['name'] for f in response['fields']} == {'code', 'message'}, f'{op["id"]}: the write response must be code + message only (extra fields such as a generated id need an approved decision)')
    fields, audit_user, date_prop = [], None, None
    for m in raw['modelMappings']:
        value, column = m['value'], m['column']
        prop = m['modelProperty']
        need(prop in entity_fields, f'{op["id"]}: mapped property {prop} is not an entity property')
        if value['kind'] == 'request-input' and value.get('origin') == 'request':
            need(value['input'] in request_fields, f'{op["id"]}: input {value["input"]} is not a request field')
            entity_type = entity_fields[prop]['javaType']
            need(request_fields[value['input']]['javaType'] == 'String' and (entity_type == 'String' or entity_type in CONVERTIBLE), f'{op["id"]}: input {value["input"]} needs an unsupported conversion')
            enum = (request_fields[value['input']].get('declaredConstraints') or {}).get('enum')
            fields.append({'input': value['input'], 'prop': prop, 'type': entity_type, 'enum': enum, 'numeric': parse_numeric(column.get('dataType')) if entity_type == 'BigDecimal' else None})
        elif value['kind'] == 'request-input' and value.get('origin') == 'headerRequest':
            need('userId' in components and entity_fields[prop]['javaType'] == 'String', f'{op["id"]}: the audit user needs a userId header role and a String property')
            audit_user = prop
        elif value['kind'] == 'database-function' and value.get('literal') == 'sysdate':
            need(entity_fields[prop]['javaType'] == 'LocalDateTime', f'{op["id"]}: the audit date needs a LocalDateTime property')
            date_prop = prop
        else:
            raise Unsupported(f'{op["id"]}: mapping value kind {value["kind"]!r} is not supported')
    need(fields, f'{op["id"]}: no request mappings')
    path_id = None
    if op['kind'] == 'update':
        need(len(params['path']) == 1 and params['path'][0]['type'] == 'String', f'{op["id"]}: an update needs exactly one String path identifier')
        path_id = params['path'][0]['java']
    op.update({'fields': fields, 'auditUser': audit_user, 'dateProp': date_prop, 'pathId': path_id, 'commandName': cap(op['id']) + 'Command'})


def build_errors(ops, models):
    """Error response contents taken only from the contract examples (per HTTP method, then any operation); missing texts stay null."""
    error_models = {r['model'] for o in ops for c, r in o['responses'].items() if c != 200 and r['model']}
    need(len(error_models) == 1, 'exactly one shared error response model is required')
    name = error_models.pop()
    fields = {f['name'] for f in models[name]['fields']}
    need({'code', 'status', 'message', 'type', 'subType', 'detail'} <= fields, 'the error model must declare code, status, message, type, subType and detail')
    by_status, by_method = {}, {}
    for o in ops:
        for code, r in o['responses'].items():
            example = r['example'] or {}
            if code == 200 or not example:
                continue
            by_status.setdefault(code, {}).setdefault(o['method'], example)
            by_method.setdefault(o['method'], example.get('message'))
    methods = {}
    for o in ops:
        methods.setdefault(o['method'], set()).update(c for c in o['statuses'] if c != 200)
    return {'model': name, 'byStatus': by_status, 'messageByMethod': {m: v for m, v in by_method.items() if v}, 'allowedByMethod': {m: sorted(s) for m, s in methods.items()}}
