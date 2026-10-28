"""Planner for the archetype profile `war-jdbc-callablestatement-junit4` (Java 8 / WAR / JDBC CallableStatement over JNDI).

Everything here follows the selected archetype (`generation` block + reference conventions): no JPA, no ActivityLogger, no Checkstyle.
Reads the workspace service-spec + planning input and writes `<ws>/generation-parameters.yml` and `<ws>/implementation-plan.yml`.
Nothing is invented: unresolved environment values stop the plan; documented assumptions are recorded in `assumptions`.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import build_implementation_plan as base

PROFILE = 'war-jdbc-callablestatement-junit4'
CODES = {'IDF0': '0', 'IDF1': '1', 'IDF2': '2', 'IDT': '-1', 'IDT1': '-1', 'IDT2': '-2'}
ENV_PARAMS = ('CONFIG_ROOT_PROPERTY', 'CONFIG_SUBDIRECTORY', 'LOG_DIRECTORY', 'CONTEXT_ROOT', 'CORPORATE_REPOSITORY_URL')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(cond, msg):
    if not cond:
        raise base.PlanError(msg)


def pascal(text: str) -> str:
    return text[:1].upper() + text[1:]


def norm(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())


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
            if cname in self.classes and self.classes[cname]['signature'] != self.signature(resolved):
                cname = pascal(parent) + cname
            if cname not in self.classes:
                self.classes[cname] = {'name': cname, 'role': role, 'fields': [], 'signature': self.signature(resolved)}
                fields = []
                for prop, sub in (resolved.get('properties') or {}).items():
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
        return repr(sorted((resolved.get('properties') or {}).keys()))


def find_class(models, java_type):
    return models.classes[java_type.replace('List<', '').replace('>', '')]


def row_target(models, data_class):
    """Locate the SP-row destination inside responseData: array of objects (optionally wrapped) or single object."""
    for field in data_class['fields']:
        if field['name'] == 'listaOpcional':
            continue
        jt = field['javaType']
        inner = find_class(models, jt) if jt.replace('List<', '').replace('>', '') in models.classes else None
        if inner is None:
            continue
        many = jt.startswith('List<')
        wrapper = None
        if many and len(inner['fields']) == 1 and inner['fields'][0]['javaType'] in models.classes:
            wrapper = inner['fields'][0]['name']
            inner = models.classes[inner['fields'][0]['javaType']]
        return {'property': field['name'], 'many': many, 'wrapperProperty': wrapper, 'rowClass': inner['name'],
                'listItemClass': find_class(models, jt)['name'] if many else None}
    return None


def map_columns(columns, fields):
    cols = {norm(c): c for c in columns}
    mapped, unmapped = [], []
    for field in fields:
        key = norm(field['name'])
        column = cols.get(key)
        if column is None:
            prefixed = [c for k, c in cols.items() if k.startswith(key)]
            column = prefixed[0] if len(prefixed) == 1 else None
        if column and field['javaType'] in ('String', 'Integer', 'Long', 'Double', 'Boolean'):
            mapped.append({'field': field['name'], 'javaType': field['javaType'], 'column': column})
        else:
            unmapped.append(field['name'])
    return mapped, unmapped


def parse_outputs(outputs):
    code = msg = cursor = None
    columns = []
    for text in outputs:
        text = str(text)
        if text.startswith('PO_COD'):
            code = text.split()[0]
        elif text.startswith('PO_MS'):
            msg = text.split()[0]
        elif 'CURSOR' in text:
            cursor = text.split('[')[0].split()[0]
            tail = re.search(r'(?:\[|:\s*)([A-Z0-9_, ]+)\]?$', text)
            if tail:
                columns += [c.strip() for c in tail.group(1).split(',') if c.strip()]
        elif re.fullmatch(r'[A-Z0-9_]+', text):
            columns.append(text)
    if cursor is None and columns and 'PO_CURSOR' in ' '.join(map(str, outputs)) + ' PO_CURSOR':
        cursor = 'PO_CURSOR'
    return code, msg, cursor, columns


def input_types(model_fields, request_class):
    types = {f['name']: f['javaType'] for f in request_class['fields']} if request_class else {}
    return types


def build(root: Path, yaml, input_path: Path):
    ws = (root / input_path).parent
    spec_path = ws / 'service-spec.yml'
    spec = base.read_yaml(spec_path, root, yaml)[0]
    config = base.read_yaml(root / input_path, root, yaml)[0]
    target = config['target']
    archetype_root = root / target['archetype']
    archetype = base.read_yaml(archetype_root / 'archetype.yml', root, yaml)[0]
    check((archetype.get('identity') or {}).get('generationEnabled') is True, 'The selected archetype is not enabled for generation.')
    check((archetype.get('generation') or {}).get('profile') == PROFILE, 'The archetype generation profile differs from this planner.')
    ready = spec.get('readiness', {})
    check(ready.get('functionalCodeGenerationReady') is True and ready.get('strictImplementationReady') is True, 'service-spec is not functionally ready.')
    covered = {str(o.get('operationId') if isinstance(o, dict) else o).split(' ')[0] for o in (ready.get('incompleteOperations') or [])}
    check(not any(isinstance(i, dict) and i.get('implementationBlocker') is not False and str(i.get('operation', '')).rsplit('/', 1)[-1] not in covered
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
    jndi_key = style['jndiPropertyKey']

    models = Models()
    operations, assumptions, incomplete = [], [], []
    for op in spec['operations']:
        oid = op['operationId']
        action = op['behavior']['actions'][0]
        contract = op['contract']
        body = next(iter((contract.get('requestBody') or {}).get('content', {}).values()), None)
        request = models.java_type(body['schema'], oid + 'Request', oid, 'request') if body else None
        resp_schema = contract['responses']['200']['content']['application/json']['schema']
        response = models.java_type(resp_schema, oid + 'Response', oid, 'response')
        resp_class = models.classes[response]
        data_field = next(f for f in resp_class['fields'] if f['name'] == 'responseData')
        data_class = models.classes[data_field['javaType']]
        persistence = action['persistence']
        errors = {e['code']: e['literal'] for e in action.get('errors', [])}
        queries = [q['name'] for q in contract['parameters']['query'] if q.get('required')]
        implemented = op['behavior'].get('actions') and action.get('implementationComplete') is True and oid != 'consultarCodigoAtencion'
        entry = {'operationId': oid, 'httpMethod': op['method'], 'path': op['path'], 'requestClass': request, 'responseClass': response,
                 'dataClass': data_class['name'], 'requiredQueryParams': queries, 'implemented': bool(implemented),
                 'activities': {'validate': action['validation'].get('activity'), 'persist': persistence.get('activity')},
                 'errors': {k: v for k, v in errors.items()}}
        if implemented:
            code, msg, cursor, columns = parse_outputs(persistence['outputs'])
            inputs = []
            req_fields = {f['name']: f['javaType'] for f in models.classes[request]['fields']} if request else {}
            for m in persistence['inputMapping']:
                header = 'header' in str(m['origin']).lower()
                inputs.append({'parameter': m['destination'], 'source': m['source'], 'origin': 'header' if header else 'request',
                               'javaType': 'String' if header else req_fields[m['source']]})
                check(header or m['source'] in req_fields, f'{oid}: input {m["source"]} not in the request schema.')
            target_row = row_target(models, data_class) if cursor else None
            mapped, unmapped = ([], [])
            if target_row:
                mapped, unmapped = map_columns(columns, models.classes[target_row['rowClass']]['fields'])
                if unmapped:
                    assumptions.append({'id': f'{oid}:unmapped-response-fields', 'decision': 'D-F',
                                        'statement': f'Response fields without a same-name stored-procedure column stay null: {", ".join(unmapped)}.'})
            entry['procedure'] = {'name': persistence['operation'], 'inputs': inputs, 'codeOutput': code, 'messageOutput': msg,
                                  'cursor': cursor, 'columns': columns, 'rowTarget': target_row, 'columnMapping': mapped,
                                  'singleRowOnly': bool(target_row and not target_row['many'])}
            literal = lambda c: errors.get(c)
            entry['outcomes'] = {'success': CODES['IDF0'], 'invalidParameters': {'code': CODES['IDF1'], 'message': literal('IDF1') or 'Parametros incorrectos: [PARAMETROS]'},
                                 'procedureFailure': {'code': CODES['IDF2'], 'message': literal('IDF2')},
                                 'timeout': {'code': CODES['IDT1'] if 'IDT1/IDT2' in errors else CODES['IDT'], 'message': errors.get('IDT1/IDT2') or errors.get('IDT')},
                                 'unavailable': {'code': CODES['IDT2'] if 'IDT1/IDT2' in errors else CODES['IDT'], 'message': errors.get('IDT1/IDT2') or errors.get('IDT')}}
        else:
            incomplete.append(oid)
            entry['pending'] = ('PENDIENTE: la consulta a BD - CMRLITE no esta definida en Sparx (rama 0.13, EA550). '
                                'Falta tabla/procedimiento y mapeo de salida.')
        operations.append(entry)
    assumptions += [
        {'id': 'sp-positional-call', 'decision': 'archetype', 'statement': 'The stored procedure is called positionally (ojdbc14): Sparx inputs in listed order, then the code output, the message output and the cursor; the exact positional order is not defined in Sparx.'},
        {'id': 'jndi-name-external', 'decision': 'archetype', 'statement': f'The JNDI DataSource name is read from the external property {jndi_key}; the operator provides its value.'},
        {'id': 'response-codes', 'decision': 'D-G', 'statement': 'codigoRespuesta: IDF0=0, IDF1=1, IDF2=2, IDT/IDT1=-1, IDT2=-2 (enum of the OpenAPI); messages are the Sparx literals; HTTP status is always 200 (the only declared status).'},
        {'id': 'mandatory-validation', 'decision': 'D-E', 'statement': 'Mandatory validation follows the OpenAPI required query parameters; Sparx body-field lists are not enforced.'},
        {'id': 'check-first-row', 'decision': 'D-F', 'statement': 'Single-object responses take the first cursor row.'},
        {'id': 'oracle-out-types', 'decision': 'archetype', 'statement': 'Code/message outputs are registered as VARCHAR (Oracle converts); timeout = SQLTimeoutException, any other SQLException = unavailable.'},
        {'id': 'consultarCodigoAtencion-pending', 'decision': 'D-C', 'statement': 'consultarCodigoAtencion: contract + validation only; the database query is PENDING and raises OperacionNoImplementadaException (HTTP 501), never a simulated success.'},
    ]
    return spec, config, archetype, archetype_root, values, jndi_key, models, operations, assumptions, incomplete, app_class


def files_plan(base_pkg, app_class, operations, models):
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
                              ('CRMLITEDAO', 'repository', 'dao-interface'), ('CRMLITERepository', 'repository', 'dao-jdbc-callable-statement'),
                              ('JdbcConfig', 'repository', 'jndi-datasource-config'), ('AtencionService', 'service', 'service'),
                              ('AtencionController', 'controller', 'controller')):
        add(f'{main}/{pkg}/{name}.java', ctype)
    for name in ('AtencionServiceTest', 'AtencionControllerTest', 'CRMLITERepositoryTest'):
        add(f'{test}/{"controller" if "Controller" in name else "service" if "Service" in name else "repository"}/{name}.java', 'unit-test-junit4')
    return files


def write_plan(root: Path, yaml, input_path: Path) -> int:
    ws = (root / input_path).parent
    (spec, config, archetype, archetype_root, values, jndi_key, models, operations, assumptions, incomplete, app_class) = build(root, yaml, input_path)
    target = config['target']
    files = files_plan(target['base_package'], app_class, operations, models)
    style = archetype['generation']['style']
    utilities = (archetype['generation'].get('utilities') or {}).get('items') or []
    configuration = (archetype['generation'].get('configuration') or {}).get('items') or []
    render = lambda s: re.sub(r'@@([A-Z0-9_]+)@@', lambda m: str(values[m.group(1)]), s)
    for item in utilities:
        files.append({'path': render(item['template']), 'action': 'create', 'componentType': 'archetype-utility'})
    for item in configuration:
        files.append({'path': render(item['template']), 'action': 'create', 'componentType': 'archetype-configuration'})
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
    (ws / 'generation-parameters.yml').write_bytes(base.dump_yaml(params, yaml))
    plan = {'plan': {'version': 3, 'mode': 'full', 'profile': PROFILE},
            'service': {'name': target['service'], 'outputDirectory': target['output_directory'], 'basePackage': target['base_package'], 'applicationClass': app_class},
            'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'artifactSha256': sha(spec_path.read_bytes())},
                       'archetype': params['inputs']['archetype'],
                       'generationParameters': {'path': '.factory/generation-parameters.yml', 'sha256': sha((ws / 'generation-parameters.yml').read_bytes())},
                       'planningInput': params['inputs']['planningInput']},
            'technicalProfile': {'persistence': 'jdbc-callable-statement-jndi-oracle', 'jpa': False, 'activityLogger': False, 'checkstyle': 'not-applicable',
                                 'logging': 'slf4j-per-class (J8-D-003)', 'tests': 'junit4+mockito', 'jndiPropertyKey': jndi_key, 'style': style, 'utilityConstants': required_constants, 'utilities': [i['class'] for i in utilities],
                                 'java': str(archetype['platform']['java'])[:40]},
            'templateParameters': values,
            'models': [{'name': n, 'role': c['role'], 'fields': c['fields']} for n, c in sorted(models.classes.items())],
            'operations': operations, 'incompleteOperations': incomplete, 'assumptions': assumptions,
            'files': {'generate': files}, 'planningBlockers': [],
            'generation': {'functionalGenerationReady': True, 'javaWritten': False, 'mavenRun': False, 'deploymentGenerationAuthorized': False}}
    (ws / 'implementation-plan.yml').write_bytes(base.dump_yaml(plan, yaml))
    print({'mode': 'full', 'profile': PROFILE, 'operations': len(operations), 'incomplete': incomplete, 'models': len(models.classes), 'plannedFiles': len(files),
           'planSha256': sha((ws / 'implementation-plan.yml').read_bytes())})
    return 0
