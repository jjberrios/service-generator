"""Closed evidence-backed JDBC binding; no domain names or default business rules."""
import re


class JdbcContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise JdbcContractError('unsupported-jdbc-binding: ' + message)


def naming(config):
    names = (config.get('technical') or {}).get('jdbcNames')
    require(isinstance(names, dict) and set(names) == {'dao', 'repository', 'service', 'controller'},
            'technical.jdbcNames must explicitly declare dao/repository/service/controller')
    require(len(set(names.values())) == 4 and all(isinstance(v, str) and re.fullmatch(r'[A-Z][A-Za-z0-9]*', v) for v in names.values()),
            'distinct safe Java class names are required')
    return dict(names)


def validate(binding, fields, data_fields, classes):
    require(isinstance(binding, dict), 'operation.jdbcBinding v1 is required; prose is not an executable binding')
    required = {'version', 'evidence', 'envelope', 'policies', 'activities', 'outcomes', 'procedure'}
    require(set(binding) == required and binding['version'] == 1, 'unknown or missing binding fields/version')
    require(isinstance(binding['evidence'], list) and binding['evidence'] and
            all(isinstance(v, str) and v.strip() for v in binding['evidence']), 'source citations are required')
    require(binding['envelope'] == {'audit': 'responseAudit', 'data': 'responseData',
            'code': 'codigoRespuesta', 'message': 'mensajeRespuesta', 'transaction': 'idTransaccion'},
            'only the explicitly bound audit/data envelope is supported')
    require(binding['policies'] == {'validation': 'required-query-nonempty', 'absentBody': 'empty-request',
            'successMessage': 'procedure-message', 'invalidParameterPlaceholder': '[PARAMETROS]',
            'procedureMessagePlaceholder': '[PO_MSG_RESPUESTA(Act.2.0)]'},
            'unsupported or missing validation/body/message policies')
    require(set(binding['activities']) == {'validate', 'persist'} and
            all(isinstance(v, str) and v.strip() for v in binding['activities'].values()), 'activity names must be specified')
    outcomes = binding['outcomes']
    require(set(outcomes) == {'success', 'invalidParameters', 'procedureFailure', 'timeout', 'unavailable'}, 'all outcomes must be explicit')
    require(isinstance(outcomes['success'], str) and bool(outcomes['success']), 'success code must be explicit')
    for key in ('invalidParameters', 'procedureFailure', 'timeout', 'unavailable'):
        require(isinstance(outcomes[key], dict) and set(outcomes[key]) == {'code', 'message'} and
                all(isinstance(v, str) and v.strip() for v in outcomes[key].values()), key + ' code/message must be explicit')
    p = binding['procedure']
    expected = {'name', 'inputs', 'codeOutput', 'messageOutput', 'cursor', 'columns', 'rowTarget', 'columnMapping',
                'singleRowOnly', 'parameterOrder', 'successCode', 'requireRows', 'unmappedFields', 'outputSqlType', 'exceptionPolicy'}
    require(isinstance(p, dict) and set(p) == expected, 'procedure fields must be explicit; no cursor/order/mapping inference')
    require(isinstance(p['name'], str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){1,2}', p['name']), 'qualified procedure name required')
    require(p['outputSqlType'] == 'VARCHAR' and p['exceptionPolicy'] == 'sql-timeout-otherwise-unavailable', 'unsupported output type or exception policy')
    require(isinstance(p['successCode'], str) and p['successCode'] and isinstance(p['requireRows'], bool), 'procedure success predicate required')
    require(isinstance(p['inputs'], list) and isinstance(p['columns'], list), 'inputs/columns must be lists')
    for i in p['inputs']:
        require(set(i) == {'parameter', 'source', 'origin', 'javaType'}, 'unknown input fields')
        require(i['origin'] in {'request', 'header'}, 'unsupported input origin')
        allowed = fields if i['origin'] == 'request' else {'accept': 'String', 'aplicacion': 'String', 'idTransaccion': 'String', 'msgid': 'String', 'timestamp': 'String', 'userId': 'String'}
        require(i['source'] in allowed and i['javaType'] == allowed[i['source']], 'input source/type mismatch')
        require(i['javaType'] in {'String', 'Integer'}, 'only String/Integer procedure inputs are supported')
    ordered = [i['parameter'] for i in p['inputs']] + [p['codeOutput'], p['messageOutput']] + ([p['cursor']] if p['cursor'] else [])
    require(p['parameterOrder'] == ordered and len(set(ordered)) == len(ordered), 'only inputs then code/message/cursor positional order is supported')
    require(all(isinstance(v, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', v) for v in ordered + p['columns']), 'unsafe SQL parameter/column')
    require(len(set(p['columns'])) == len(p['columns']), 'duplicate cursor columns')
    rt = p['rowTarget']
    require(isinstance(p['singleRowOnly'], bool), 'singleRowOnly must be boolean')
    if p['cursor']:
        require(isinstance(rt, dict) and set(rt) == {'property', 'many', 'wrapperProperty', 'rowClass', 'listItemClass'}, 'explicit row destination required')
        require(rt['rowClass'] in classes and isinstance(rt['many'], bool), 'invalid row class/cardinality')
        require(p['singleRowOnly'] == (not rt['many']), 'row cardinality disagreement')
        if rt['many']:
            require(rt['listItemClass'] in classes and data_fields.get(rt['property']) == 'List<' + rt['listItemClass'] + '>', 'list target mismatch')
            item_fields = {f['name']: f['javaType'] for f in classes[rt['listItemClass']]['fields']}
            require(item_fields.get(rt['wrapperProperty']) == rt['rowClass'], 'wrapper target mismatch')
        else:
            require(data_fields.get(rt['property']) == rt['rowClass'] and rt['wrapperProperty'] is None and rt['listItemClass'] is None, 'single row target mismatch')
            require(p['requireRows'] is True, 'single-row extraction requires explicit nonempty-result success predicate')
        row_fields = {f['name']: f['javaType'] for f in classes[rt['rowClass']]['fields']}
        mapped = []
        for m in p['columnMapping']:
            require(set(m) == {'field', 'javaType', 'column'} and m['column'] in p['columns'] and
                    m['field'] in row_fields and row_fields[m['field']] == m['javaType'] and m['javaType'] in {'String', 'Integer'}, 'unsupported column mapping/type')
            mapped.append(m['field'])
        require(len(set(mapped)) == len(mapped) and set(mapped).isdisjoint(p['unmappedFields']) and
                set(mapped) | set(p['unmappedFields']) == set(row_fields), 'every response field must be mapped or explicitly null')
    else:
        require(rt is None and not p['columns'] and not p['columnMapping'] and not p['unmappedFields'] and
                p['requireRows'] is False and p['singleRowOnly'] is False, 'cursor semantics without cursor')
    return binding
