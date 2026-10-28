"""Builds synthetic implementation plans with the same structure the real planner emits (temporary repositories only; no real service data).

Two shapes are provided so tests prove independence: a service with search + insert + patch (OR filters with contains/exact, pagination, conditional rule,
audit user and date, enum and bounded decimal) and a service with search + insert only (AND filters, no pagination, different headers/statuses/messages).
"""
import copy

ERROR_MODEL = {'name': 'ErrorResponse', 'kind': 'contract-model', 'requestResponseScope': ['response'], 'fields': [
    {'name': n, 'javaType': t, 'required': False, 'validationAnnotations': [], 'declaredConstraints': {}} for n, t in
    (('code', 'Integer'), ('detail', 'String'), ('message', 'String'), ('status', 'String'), ('subType', 'String'), ('type', 'String'))]}


def f(name, java='String', required=False, annotations=(), constraints=None):
    return {'name': name, 'javaType': java, 'required': required, 'validationAnnotations': list(annotations), 'declaredConstraints': constraints or {}}


def model(name, scope, fields):
    return {'name': name, 'kind': 'contract-model', 'requestResponseScope': [scope], 'fields': fields}


def ref(name):
    return {'source': {'kind': 'local-reference', '$ref': f'#/components/schemas/{name}'}}


def response(description, schema, example=None):
    node = {'schema': ref(schema)}
    if example is not None:
        node['example'] = example
    return {'description': description, 'content': {'application/json': node}}


def param(name, where, type_='string', required=False, **schema):
    return {'name': name, 'in': where, 'required': required, 'schema': {'type': type_, **schema}}


def headers(names, constraints=None):
    return [param(n, 'header', required=True, **(constraints or {}).get(n, {})) for n in names]


def error_example(status, code, message, kind, sub, detail):
    return {'code': code, 'detail': detail, 'message': message, 'status': status, 'subType': sub, 'type': kind}


def activity(op_id, label, constants, helper, values, body_type, controller_args, metadata):
    return {'operationId': op_id, 'requestEntryLogging': {'controller': {'message': f'{op_id} - transactionId: {{}}' + (', usuario: {}' if len(controller_args) > 1 else ''), 'arguments': controller_args},
                                                          'serviceHelper': helper, 'metadataLabel': label, 'metadataFields': metadata, 'requestValues': values},
            'bodyLogging': {'applies': bool(body_type), 'type': body_type, 'message': f'{label} body: {{}}'},
            'activitySequence': [{'order': 1, 'constant': constants[0], 'role': 'validation'}, {'order': 2, 'constant': constants[1], 'role': 'behavior'}]}


def build(spec: dict) -> dict:
    """spec keys: package, entity, table, fields, header_names, header_roles, ops (list of op specs), error_texts, catalogue."""
    ops, models, constants, activity_ops = [], [copy.deepcopy(ERROR_MODEL)], {}, []
    for o in spec['ops']:
        statuses = o['statuses']
        responses = {'200': response('OK', o['response'], {'code': 200, 'message': o['message']})}
        for s in statuses:
            if s == 200:
                continue
            ex = spec['errors'].get(s)
            responses[str(s)] = response(f'HTTP {s}', 'ErrorResponse', error_example(ex['status'], s, o['error_message'], ex['type'], ex['sub'], ex['detail']) if ex and not o.get('no_examples') else None)
        contract = {'summary': o.get('summary'), 'description': o.get('description'), 'parameters': {'path': o.get('path_params', []), 'query': o.get('query_params', []),
                                                                                                    'header': headers(spec['header_names'], spec.get('header_constraints')), 'cookie': []},
                    'requestBody': ({'content': {'application/json': {'schema': ref(o['request'])}}} if o.get('request') else None), 'responses': responses}
        op = {'operationId': o['id'], 'method': o['method'], 'path': o['path'], 'actionKind': o['kind'], 'contract': contract, 'effectiveStatusCodes': [str(s) for s in statuses],
              'validation': [{'rules': o.get('rules', [])}], 'modelMappings': o.get('mappings', []), 'query': o.get('query')}
        ops.append(op)
        for c in o['constants']:
            constants.setdefault(c, {'constant': c, 'value': c.split('_', 1)[1], **({'logMessages': {f'LOG_TIMEOUT_{c}': f'Timeout en {c}: ', f'LOG_ERROR_DATOS_{c}': f'Error de datos en {c}: '}} if c.startswith('ACT2') else {})})
        activity_ops.append(activity(o['id'], o['label'], o['constants'], o['helper'], o.get('log_values', []), o.get('request'), o['controller_args'], spec['metadata']))
    for m in spec['models']:
        models.append(copy.deepcopy(m))
    constants_list = [constants[k] for k in sorted(constants)]
    return {'ops': ops, 'models': models, 'activityOps': activity_ops, 'constants': constants_list}


def search_op(spec, with_page=True, combinator='OR'):
    filters, params = [], []
    for name, prop, entity_type, match, sql in spec['filters']:
        params.append(param(name, 'query', **spec.get('filter_constraints', {}).get(name, {})))
        filters.append({'parameter': name, 'modelProperty': prop, 'javaType': entity_type, 'effectiveMatch': match, 'column': {'dataType': sql}})
    page = {}
    if with_page:
        params += [param('limit', 'query', 'integer', format='int32', minimum=1, **spec.get('limit_constraints', {})), param('offset', 'query', 'integer', format='int32', minimum=0)]
        page = {'limit': {'parameter': 'limit'}, 'offset': {'parameter': 'offset'}}
    columns = [{'responseField': f'data.{spec["list"]}[].{field}', 'modelProperty': prop} for field, prop in spec['columns']]
    return params, {'filterPolicy': {'minimumActiveFilters': 1, 'combinator': combinator}, 'filters': filters, 'pagination': page, 'orderBy': {'physicalColumn': spec['order']}, 'selectedColumns': columns}


def mapping(prop, java, column, input_name=None, origin='request', kind='request-input', literal=None, sql=None):
    value = {'kind': kind}
    if kind == 'request-input':
        value.update({'input': input_name or prop, 'origin': origin})
    else:
        value['literal'] = literal
    return {'modelProperty': prop, 'javaType': java, 'physicalColumn': column, 'column': {'physicalColumn': column, 'dataType': sql}, 'value': value}
