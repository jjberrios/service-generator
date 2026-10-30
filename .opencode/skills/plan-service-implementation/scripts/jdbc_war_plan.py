"""Planner for the archetype profile `war-jdbc-callablestatement-junit4` (Java 8 / WAR / JDBC CallableStatement over JNDI).

Everything here follows the selected archetype (`generation` block + reference conventions): no JPA, no ActivityLogger, no Checkstyle.
Reads the workspace service-spec + planning input and writes `<ws>/generation-parameters.yml` and `<ws>/implementation-plan.yml`.
Nothing is invented: unresolved environment values stop the plan; documented assumptions are recorded in `assumptions`.
"""
from __future__ import annotations

import hashlib
import re
import json
from pathlib import Path

import build_implementation_plan as base
import jdbc_contract

PROFILE = 'war-jdbc-callablestatement-junit4'
JAVA_KEYWORDS = set('abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null'.split())
ENV_PARAMS = ('CONFIG_ROOT_PROPERTY', 'CONFIG_SUBDIRECTORY', 'LOG_DIRECTORY', 'CONTEXT_ROOT', 'CORPORATE_REPOSITORY_URL')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(cond, msg):
    if not cond:
        raise base.PlanError(msg)


def pascal(text: str) -> str:
    return text[:1].upper() + text[1:]


class Models:
    """Walk resolved OpenAPI schemas into Java POJO descriptions."""

    def __init__(self):
        self.classes = {}

    def java_type(self, node, hint, parent, role):
        resolved = node.get('resolved', node)
        ref = (node.get('source') or {}).get('$ref')
        name = ref.rsplit('/', 1)[-1] if ref else None
        if 'properties' in resolved or resolved.get('type') == 'object':
            cname = name or (pascal(hint) + 'Type')
            check(re.fullmatch(r'[A-Z][A-Za-z0-9]*', cname) is not None, 'unsupported-jdbc-binding: unsafe DTO name')
            if cname in self.classes and self.classes[cname]['signature'] != self.signature(resolved):
                cname = pascal(parent) + cname
            check(cname not in self.classes or self.classes[cname]['signature'] == self.signature(resolved),
                  'unsupported-jdbc-binding: incompatible duplicate DTO definition')
            if cname not in self.classes:
                self.classes[cname] = {'name': cname, 'role': role, 'fields': [], 'signature': self.signature(resolved)}
                fields = []
                for prop, sub in (resolved.get('properties') or {}).items():
                    check(re.fullmatch(r'[a-z][A-Za-z0-9]*', prop) is not None and prop not in JAVA_KEYWORDS,
                          'unsupported-jdbc-binding: unsafe DTO property')
                    fields.append({'name': prop, 'javaType': self.java_type(sub, prop, cname, 'type')})
                self.classes[cname]['fields'] = fields
            return cname
        if resolved.get('type') == 'array':
            return 'List<' + self.java_type(resolved.get('items') or {}, hint + 'Item', parent, 'type') + '>'
        kind, fmt = resolved.get('type'), resolved.get('format')
        if kind == 'integer':
            return 'Long' if fmt == 'int64' else 'Integer'
        if kind == 'number':
            return 'Double'
        if kind == 'boolean':
            return 'Boolean'
        check(kind in (None, 'string'), f'unsupported schema type {kind!r} at {parent}.{hint}')
        return 'String'

    def signature(self, resolved):
        return json.dumps(resolved, sort_keys=True, separators=(',', ':'))


def build(root: Path, yaml, input_path: Path):
    ws = (root / input_path).parent
    spec_path = ws / 'service-spec.yml'
    spec = base.read_yaml(spec_path, root, yaml)[0]
    config = base.read_yaml(root / input_path, root, yaml)[0]
    target = config['target']
    names = jdbc_contract.naming(config)
    check(target['service'] == spec['service']['name'], 'Target and service-spec disagree.')
    archetype_root = root / target['archetype']
    archetype = base.read_yaml(archetype_root / 'archetype.yml', root, yaml)[0]
    check((archetype.get('identity') or {}).get('generationEnabled') is True, 'The selected archetype is not enabled for generation.')
    check((archetype.get('generation') or {}).get('profile') == PROFILE, 'The archetype generation profile differs from this planner.')
    ready = spec.get('readiness', {})
    check(ready.get('functionalCodeGenerationReady') is True and ready.get('strictImplementationReady') is True, 'service-spec is not functionally ready.')
    check(not ready.get('incompleteOperations'), 'unsupported-jdbc-binding: incomplete operations require a separate explicitly supported partial-generation profile.')
    check(not any(isinstance(i, dict) and i.get('implementationBlocker') is not False
                  for k in ('conflicts', 'ambiguities', 'missingEvidence') for i in (spec.get('unresolved') or {}).get(k) or []),
          'service-spec carries unresolved blocking conflicts, ambiguities or missing evidence.')
    check(re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+', target['base_package']) is not None, 'Unsafe Java package.')
    out_dir = Path(target['output_directory'])
    check(not out_dir.is_absolute() and out_dir.parts[:1] == ('output',) and '..' not in out_dir.parts and out_dir.as_posix() == f"output/{target['service']}",
          'Output must be output/<service>.')
    tpl = dict(config.get('template_parameters') or {})
    missing = [p for p in ENV_PARAMS if not tpl.get(p)]
    check(not missing, 'Unresolved environment parameters (provide them in template_parameters; never invented): ' + ', '.join(missing))
    app_class = tpl.get('APPLICATION_CLASS') or pascal(re.sub(r'-(\w)', lambda m: m.group(1).upper(), target['service'])) + 'Application'
    values = {'GROUP_ID': target['group_id'], 'ARTIFACT_ID': target['service'], 'PROJECT_VERSION': target['project_version'],
              'BASE_PACKAGE': target['base_package'], 'BASE_PACKAGE_PATH': target['base_package'].replace('.', '/'),
              'APPLICATION_CLASS': app_class, **{p: tpl[p] for p in ENV_PARAMS}}
    for spec_param in archetype.get('parameters', []) if isinstance(archetype.get('parameters'), list) else [{'name': k, **v} for k, v in archetype['parameters'].items()]:
        pattern = spec_param.get('pattern')
        check(spec_param['name'] not in values or not pattern or re.fullmatch(pattern, str(values[spec_param['name']])) is not None,
              f"Parameter {spec_param['name']} violates the archetype pattern.")
    style = (archetype.get('generation') or {}).get('style')
    check(isinstance(style, dict) and style.get('constantsClass') and style.get('externalPropertiesClass') and style.get('hardcodedLiterals') == 'forbidden',
          'The archetype generation profile must declare generation.style (constantsClass, externalPropertiesClass, jndiPropertyKey, hardcodedLiterals: forbidden).')
    check(style['constantsClass'] == 'common.property.Constantes' and
          style['externalPropertiesClass'] == 'common.property.PropertiesExternos' and style.get('dataSourceBean'),
          'unsupported-jdbc-binding: unsupported constants/properties packages or missing DataSource bean convention')
    jndi_key = style['jndiPropertyKey']

    models = Models()
    operations, assumptions, incomplete = [], [], []
    for op in spec['operations']:
        oid = op['operationId']
        check(isinstance(oid, str) and re.fullmatch(r'[a-z][A-Za-z0-9]*', oid) is not None and oid not in JAVA_KEYWORDS,
              'unsupported-jdbc-binding: unsafe operation identifier')
        def check_constraints(value):
            if isinstance(value, dict):
                unsupported = {'minimum', 'maximum', 'minLength', 'maxLength', 'pattern', 'minItems', 'maxItems',
                               'oneOf', 'allOf', 'anyOf', 'additionalProperties', 'nullable', 'readOnly', 'writeOnly'} & set(value)
                check(not unsupported, f'unsupported-jdbc-binding: {oid}: unsupported schema constraints {sorted(unsupported)}')
                check(not value.get('required') or isinstance(value.get('required'), bool),
                      f'unsupported-jdbc-binding: {oid}: required body fields are unsupported')
                for child in value.values():
                    check_constraints(child)
            elif isinstance(value, list):
                for child in value:
                    check_constraints(child)
        check_constraints(op['contract'])
        actions = op.get('behavior', {}).get('actions', [])
        check(len(actions) == 1 and actions[0].get('implementationComplete') is True,
              f'unsupported-jdbc-binding: {oid}: exactly one complete behavior action required')
        action = actions[0]
        contract = op['contract']
        content = (contract.get('requestBody') or {}).get('content', {})
        check(not (contract.get('requestBody') or {}).get('required'), f'unsupported-jdbc-binding: {oid}: required body unsupported')
        check(set(content) == {'application/json'}, f'unsupported-jdbc-binding: {oid}: JSON request body required')
        check(set(contract.get('responses', {})) == {'200'} and
              set(contract['responses']['200'].get('content', {})) == {'application/json'},
              f'unsupported-jdbc-binding: {oid}: only explicitly declared HTTP 200 JSON responses are supported')
        body = content['application/json']
        request = models.java_type(body['schema'], oid + 'Request', oid, 'request') if body else None
        resp_schema = contract['responses']['200']['content']['application/json']['schema']
        response = models.java_type(resp_schema, oid + 'Response', oid, 'response')
        resp_class = models.classes[response]
        response_fields = {f['name']: f['javaType'] for f in resp_class['fields']}
        check(set(response_fields) == {'responseData', 'responseAudit'}, f'unsupported-jdbc-binding: {oid}: unsupported envelope')
        data_field = next(f for f in resp_class['fields'] if f['name'] == 'responseData')
        data_class = models.classes[data_field['javaType']]
        audit = models.classes[response_fields['responseAudit']]
        check({f['name']: f['javaType'] for f in audit['fields']} ==
              {'codigoRespuesta': 'String', 'mensajeRespuesta': 'String', 'idTransaccion': 'String'},
              f'unsupported-jdbc-binding: {oid}: unsupported audit fields')
        binding = jdbc_contract.validate(op.get('jdbcBinding'),
                   {f['name']: f['javaType'] for f in models.classes[request]['fields']},
                   {f['name']: f['javaType'] for f in data_class['fields']}, models.classes)
        audit_node = resp_schema.get('resolved', resp_schema)['properties']['responseAudit']
        code_node = audit_node.get('resolved', audit_node)['properties']['codigoRespuesta']
        code_enum = code_node.get('resolved', code_node).get('enum')
        codes = [binding['outcomes']['success']] + [binding['outcomes'][key]['code'] for key in
                 ('invalidParameters', 'procedureFailure', 'timeout', 'unavailable')]
        check(code_enum is None or set(codes).issubset(code_enum), f'{oid}: JDBC response codes disagree with the contract enum')
        persistence = action.get('persistence', {})
        check(persistence.get('operation') == binding['procedure']['name'], f'{oid}: JDBC binding disagrees with persistence evidence')
        check(op['method'] == 'POST', f'unsupported-jdbc-binding: {oid}: only POST is supported')
        queries = [q['name'] for q in contract['parameters']['query'] if q.get('required')]
        check('idTransaccion' in queries and len(set(queries)) == len(queries) and
              all(q.get('required') for q in contract['parameters']['query']),
              f'unsupported-jdbc-binding: {oid}: required idTransaccion and unique required queries only')
        check(all(i['source'] in queries for i in binding['procedure']['inputs'] if i['origin'] == 'header'),
              f'unsupported-jdbc-binding: {oid}: procedure header source is not in declared queries')
        allowed_queries = {'accept', 'aplicacion', 'idTransaccion', 'msgid', 'timestamp', 'userId'}
        check(all(q['name'] in allowed_queries and q.get('schema', {}).get('type', 'string') == 'string'
                  for q in contract['parameters']['query']) and not contract['parameters'].get('header') and
                  not contract['parameters'].get('path') and not contract['parameters'].get('cookie'),
              f'unsupported-jdbc-binding: {oid}: unsupported request parameters')
        entry = {'operationId': oid, 'httpMethod': op['method'], 'path': op['path'], 'requestClass': request, 'responseClass': response,
                 'dataClass': data_class['name'], 'requiredQueryParams': queries, 'implemented': True,
                 'activities': binding['activities'], 'errors': {}, 'procedure': binding['procedure'],
                 'outcomes': binding['outcomes'], 'policies': binding['policies'], 'bindingEvidence': binding['evidence']}
        operations.append(entry)
    check(len({o['operationId'] for o in operations}) == len(operations), 'Duplicate operation identifiers')
    reserved = {'BaseException', 'DBException', 'DBTimeoutException', 'DBDisponibilidadException', 'OperacionNoImplementadaException',
                'Cabecera', 'ResultadoProcedimiento', 'Constantes', 'PropertiesExternos', 'JdbcConfig', 'ClaroUtil', app_class}
    check(not set(names.values()) & (reserved | set(models.classes)), 'JDBC class names collide with model/technical classes')
    check(not set(models.classes) & reserved, 'DTO names collide with technical classes')
    return spec, config, archetype, archetype_root, values, jndi_key, models, operations, assumptions, incomplete, app_class


def files_plan(base_pkg, app_class, operations, models, names):
    pp = base_pkg.replace('.', '/')
    main = f'src/main/java/{pp}'
    test = f'src/test/java/{pp}'
    files = []

    def add(path, ctype):
        files.append({'path': path, 'action': 'create', 'componentType': ctype})
    for cname, c in sorted(models.classes.items()):
        pkg = {'request': 'canonical/request', 'response': 'canonical/response'}.get(c['role'], 'canonical/type')
        add(f'{main}/{pkg}/{cname}.java', 'canonical-dto')
    for name, pkg, ctype in (('BaseException', 'common/exception', 'exception'), ('DBException', 'common/exception', 'exception'), ('DBTimeoutException', 'common/exception', 'exception'),
                              ('DBDisponibilidadException', 'common/exception', 'exception'), ('OperacionNoImplementadaException', 'common/exception', 'exception'),
                              ('Cabecera', 'common/bean', 'bean'), ('ResultadoProcedimiento', 'common/bean', 'bean'), ('Constantes', 'common/property', 'constants'),
                              ('PropertiesExternos', 'common/property', 'external-properties'),
                               (names['dao'], 'repository', 'dao-interface'), (names['repository'], 'repository', 'dao-jdbc-callable-statement'),
                               ('JdbcConfig', 'repository', 'jndi-datasource-config'), (names['service'], 'service', 'service'),
                               (names['controller'], 'controller', 'controller')):
        add(f'{main}/{pkg}/{name}.java', ctype)
    for role in ('service', 'controller', 'repository'):
        add(f'{test}/{role}/{names[role]}Test.java', 'unit-test-junit4')
    return files


def artifacts(root: Path, yaml, input_path: Path):
    ws = (root / input_path).parent
    (spec, config, archetype, archetype_root, values, jndi_key, models, operations, assumptions, incomplete, app_class) = build(root, yaml, input_path)
    target = config['target']
    names = jdbc_contract.naming(config)
    files = files_plan(target['base_package'], app_class, operations, models, names)
    style = archetype['generation']['style']
    utilities = (archetype['generation'].get('utilities') or {}).get('items') or []
    configuration = (archetype['generation'].get('configuration') or {}).get('items') or []
    render = lambda s: re.sub(r'@@([A-Z0-9_]+)@@', lambda m: str(values[m.group(1)]), s)
    for item in utilities:
        files.append({'path': render(item['template']), 'action': 'create', 'componentType': 'archetype-utility'})
    for item in configuration:
        files.append({'path': render(item['template']), 'action': 'create', 'componentType': 'archetype-configuration'})
    # Technical files are part of the authorized plan too, not implicit extras.
    from artifact_integrity import template_paths
    for relative in template_paths(archetype_root):
        path = render(relative)
        if path not in {entry['path'] for entry in files}:
            files.append({'path': path, 'action': 'create', 'componentType': 'archetype-template'})
    required_constants = {}
    for item in utilities:
        required_constants.update(item.get('requiredConstants') or {})
    spec_path = ws / 'service-spec.yml'
    params = {'version': 2, 'mode': 'full', 'service': target['service'], 'values': values, 'resolved': [], 'unresolved': [],
              'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'sha256': sha(spec_path.read_bytes())},
                         'archetype': {'path': target['archetype'], 'fingerprint': base.archetype_fingerprint(archetype_root)},
                         'planningInput': {'path': '.factory/full-planning-input.yml', 'sha256': sha((root / input_path).read_bytes())}},
              'functional': {'profile': PROFILE, 'jndiPropertyKey': jndi_key}, 'readiness': {'functionalGenerationReady': True},
              'secretsStored': False, 'validation': {'errors': []}}
    params_raw = base.dump_yaml(params, yaml)
    plan = {'plan': {'version': 3, 'mode': 'full', 'profile': PROFILE, 'jdbcBindingVersion': 1},
            'service': {'name': target['service'], 'outputDirectory': target['output_directory'], 'basePackage': target['base_package'], 'applicationClass': app_class},
            'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'artifactSha256': sha(spec_path.read_bytes())},
                       'archetype': params['inputs']['archetype'],
                        'generationParameters': {'path': '.factory/generation-parameters.yml', 'sha256': sha(params_raw)},
                       'planningInput': params['inputs']['planningInput']},
            'technicalProfile': {'persistence': 'jdbc-callable-statement-jndi-oracle', 'jpa': False, 'activityLogger': False, 'checkstyle': 'not-applicable',
                                  'logging': 'slf4j-per-class', 'tests': 'junit4+mockito', 'jdbcNames': names, 'jndiPropertyKey': jndi_key, 'style': style, 'utilityConstants': required_constants, 'utilities': [i['class'] for i in utilities],
                                 'java': str(archetype['platform']['java'])[:40]},
            'templateParameters': values,
            'models': [{'name': n, 'role': c['role'], 'fields': c['fields']} for n, c in sorted(models.classes.items())],
            'operations': operations, 'incompleteOperations': incomplete, 'assumptions': assumptions,
            'files': {'generate': files}, 'planningBlockers': [],
            'generation': {'functionalGenerationReady': True, 'javaWritten': False, 'mavenRun': False, 'deploymentGenerationAuthorized': False}}
    return plan, params


def write_plan(root: Path, yaml, input_path: Path) -> int:
    from artifact_integrity import write_atomic, safe_path
    plan, params = artifacts(root, yaml, input_path)
    ws = (root / input_path).parent
    plan_raw, params_raw = base.dump_yaml(plan, yaml), base.dump_yaml(params, yaml)
    destinations = [safe_path(ws, name) for name in ('generation-parameters.yml', 'implementation-plan.yml')]
    for destination, data in zip(destinations, (params_raw, plan_raw)):
        write_atomic(destination, data)
    print({'mode': 'full', 'profile': PROFILE, 'operations': len(plan['operations']), 'incomplete': plan['incompleteOperations'], 'models': len(plan['models']), 'plannedFiles': len(plan['files']['generate']),
           'planSha256': sha((ws / 'implementation-plan.yml').read_bytes())})
    return 0
