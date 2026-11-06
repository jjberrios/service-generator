"""M1a contract fixture: synthetic service-spec -> unmodified FULL planner CLI.

This is NOT an EA end-to-end fixture. Behavior and technical inputs are explicit
test specifications; no final plan/model inventory is constructed here. Never uses
the frozen mailing-info fixture. All artifacts and approvals are temp-test-only.
"""
import copy
import shutil
from pathlib import Path

import yaml

import synth as fx
import plan_builder as pb


def specification(name):
    shape = fx.SERVICES[name]
    ops, models = fx.SHAPES[name](shape, shape['fields'])
    models = [copy.deepcopy(pb.ERROR_MODEL), *models]
    definitions = {}
    scalar = {'String': 'string', 'Integer': 'integer', 'Long': 'integer',
              'BigDecimal': 'number', 'Boolean': 'boolean'}

    def schema(type_):
        if type_.startswith('List<'):
            return {'type': 'array', 'items': schema(type_[5:-1])}
        if type_ not in scalar:
            return {'source': {'$ref': '#/components/schemas/' + type_},
                    'resolved': copy.deepcopy(definitions[type_])}
        return {'type': scalar[type_], **({'format': 'int64'} if type_ == 'Long' else {})}

    def model_schema(model):
        properties = {}
        for f in model['fields']:
            value = schema(f['javaType'])
            value.update(f.get('declaredConstraints') or {})
            for a in f.get('validationAnnotations') or []:
                if a == '@Email':
                    value['format'] = 'email'
            properties[f['name']] = value
        return {'type': 'object', 'properties': properties,
                'required': [f['name'] for f in model['fields'] if f['required']]}

    # Topological schema expansion, matching normalized OpenAPI local refs.
    pending = list(models)
    while pending:
        progressed = False
        for model in list(pending):
            try:
                definitions[model['name']] = model_schema(model)
            except KeyError:
                continue
            pending.remove(model)
            progressed = True
        assert progressed, 'cyclic synthetic schemas'

    sql = {'Long': 'NUMBER(0)', 'Integer': 'NUMBER(1)', 'BigDecimal': 'NUMBER(10,2)',
           'String': 'VARCHAR2(80)', 'LocalDateTime': 'DATE'}
    cols = [{'column': c, 'dataType': t or ('CLOB' if lob else sql[java]),
             'description': 'Synthetic column', 'evidenceId': f'{name}:column:{c}'}
            for c, prop, java, lob, pk, *rest in [tuple(f) + (None,) * (6 - len(f)) for f in shape['fields']]
            for t in [rest[0]]]
    by_prop = {f[1]: c['column'] for f, c in zip(shape['fields'], cols)}
    by_col = {c['column']: c for c in cols}
    pk = next(f[0] for f in shape['fields'] if f[4])

    def col_ref(prop):
        col = by_prop[prop]
        return {'physicalColumn': col, 'dataType': by_col[col]['dataType'],
                'columnEvidenceId': by_col[col]['evidenceId']}

    result = []
    for op in ops:
        responses = {'200': pb.response('OK', op['response'], {'code': 200, 'message': op['message']})}
        for code in op['statuses']:
            if code == 200:
                continue
            error = shape['errors'].get(code)
            responses[str(code)] = pb.response('Failure', 'ErrorResponse',
                pb.error_example(error['status'], code, op['error_message'], error['type'], error['sub'], error['detail']) if error else None)
        body = {'content': {'application/json': {'schema': schema(op['request'])}}} if op.get('request') else None
        for response in responses.values():
            node = response['content']['application/json']['schema']
            node['resolved'] = copy.deepcopy(definitions[node['source']['$ref'].rsplit('/', 1)[-1]])
        headers = pb.headers(shape['header_names'], shape.get('header_constraints'))
        contract = {'summary': op.get('summary'), 'description': op.get('description'),
                    'parameters': {'path': op.get('path_params', []), 'query': op.get('query_params', []), 'header': headers, 'cookie': []},
                    'headers': {'request': headers, 'responses': {}}, 'requestBody': body,
                    'responses': responses, 'effectiveResponses': [{'status': str(s)} for s in op['statuses']], 'contractDeltas': []}
        source = lambda label: {'name': label, 'uuid': f'{name}:{op["id"]}:{label}',
                                'page': f'test-evidence/{op["id"]}.htm', 'pageSha256': 'a' * 64}
        validation, behavior = source('1. Validar'), source('2. Procesar')
        flow = {'normal': [
            {'from': 'Start', 'fromRole': 'startEvent', 'to': validation['name'], 'toRole': 'activity', 'evidence': ['test:start']},
            {'from': validation['name'], 'fromRole': 'activity', 'to': behavior['name'], 'toRole': 'activity', 'evidence': ['test:next']},
            {'from': behavior['name'], 'fromRole': 'activity', 'to': '200', 'toRole': 'endEvent', 'evidence': ['test:end']}], 'errorPaths': []}
        persistence = {'actionKind': op['kind']}
        if op['kind'] == 'select':
            q = op['query']
            persistence['query'] = {'filterPolicy': copy.deepcopy(q['filterPolicy']),
                'businessFilters': [dict(f, column=col_ref(f['modelProperty'])) for f in q['filters']],
                'selectedColumns': [dict(f, column=col_ref(f['modelProperty'])) for f in q['selectedColumns']],
                'pagination': q['pagination'], 'orderBy': q['orderBy']}
        else:
            writes = [dict(m, column=col_ref(m['modelProperty'])) for m in op['mappings']]
            persistence['columnValues' if op['kind'] == 'insert' else 'assignments'] = writes
            persistence['suppliedValuesOnly'] = {'rule': 'explicit synthetic supplied-only policy'}
            if op['kind'] == 'update':
                persistence['whereClause'] = [{'column': {'physicalColumn': pk}, 'parameter': 'id', 'origin': 'path', 'operator': '=', 'value': '<id>'}]
                persistence['noMatchingRecordOutcome'] = {'status': 404, 'condition': 'identifier not found'}
        outcomes = {'byStatus': {str(s): {'status': s, 'condition': f'explicit synthetic outcome {s}'} for s in op['statuses']}}
        result.append({'operationId': op['id'], 'method': op['method'], 'path': op['path'], 'contract': contract,
            'behavior': {'authoritativeBranch': {'branchRootId': 'test-branch'},
                'sources': {'validationActivity': validation, 'behaviorActivity': behavior},
                'processes': [{'flow': flow}], 'persistence': [persistence], 'validations': [{'rules': op.get('rules', [])}],
                'mappings': [{'headerDerivedMappings': []}], 'errors': [outcomes]}})
    return {'service': {'name': name}, 'operations': result,
            'behaviorContext': {'architecturalEvidence': {'dataDefinitions': [{'identity': {'name': shape['table']}, 'columns': cols,
                'keyAndIndexDeclarations': [{'kind': 'primaryKey', 'parameters': pk + ':NUMBER'}]}]}},
            'readiness': {'functionalCodeGenerationReady': True, 'strictImplementationReady': True},
            'inactive': {'operations': []}, 'unresolved': {'conflicts': [], 'ambiguities': [], 'missingEvidence': []}}


def prepare(repo, name):
    """Run the actual guarded planner CLI, then publish its exact artifacts to the temp service workspace."""
    ws = fx.clear_gate(repo, name, fx.SERVICES[name]['route'])
    shape = fx.SERVICES[name]
    spec = specification(name)
    technical = {k: fx.ASSEMBLY_VALUES[k] for k in ('application_log_level', 'corporate_logger_level', 'http_log_level', 'root_log_level', 'log_time_zone', 'jwt_roles_claim')}
    technical.update(database_product='oracle', jdbc_url='${DB_URL}', generated_id_assumption='Synthetic test: database provides an IDENTITY key.',
        header_roles={c: shape['header_names'][fx.ROLE_HEADERS[c]] for c in shape['headers']})
    config = {'version': 1, 'mode': 'full', 'target': {'service': name, 'base_package': shape['package'], 'group_id': shape['package'],
        'project_version': '1.0.0-SNAPSHOT', 'output_directory': f'output/{name}', 'archetype': fx.ARCHETYPE},
        'naming': {'domain_prefix': shape['prefix'], 'table_models': {shape['table']: {'class_name': shape['entity'], 'properties': {f[0]: f[1] for f in shape['fields']}}}},
        'technical': technical}
    # Use the same service-local reviewed workspace as production. A flat copy of
    # .factory cannot carry a worktree-scoped approval into another directory.
    fx.wfx.dump(ws.dir / 'service-spec.yml', spec)
    fx.wfx.dump(ws.dir / 'full-planning-input.yml', config)
    fx.wfx.simulate_manual(repo, name)
    local_skills = repo / '.opencode/skills'
    shutil.copytree(fx.SKILLS, local_skills, ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
    script = local_skills / 'plan-service-implementation/scripts/build_implementation_plan.py'
    done = fx.wsm.run_script(ws, script, ['--mode', 'full', '--planning-input', '.factory/full-planning-input.yml'])
    if done.returncode:
        raise AssertionError(f'real planner failed ({done.returncode}): {done.stdout}\n{done.stderr}')
    return ws
