"""Planner for the archetype profile `jar-springboot3-webmvc-webclient-bff` (Java 21 / Spring Boot 3 / JAR / WebMVC + WebClient).

Scope "structure + contract": the archetype technical files, DTOs/API interface/controller/service derived from the OpenAPI contract,
and a WebClient integration ONLY when the service-spec carries an explicit evidence-backed `bffBinding` (version 1).
Behavior without such a binding is never invented: it is recorded under `omittedBehavior` and the generated service method
fails explicitly. Reads `<ws>/service-spec.yml` + `<ws>/full-planning-input.yml`; writes `<ws>/generation-parameters.yml`
and `<ws>/implementation-plan.yml`.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import build_implementation_plan as base

PROFILE = 'jar-springboot3-webmvc-webclient-bff'
BINDING_VERSION = 1
JAVA_KEYWORDS = set('abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null var record'.split())
ENV_PARAMS = ('VAULT_NAME', 'OWNER_LABEL', 'PART_OF_LABEL')
RESERVED_CLASSES = {'ApiResponseData', 'ErrorResponse', 'ResponseAudit', 'WsResponseProperties', 'BusinessException', 'GlobalExceptionHandler',
                    'WebClientConfig', 'SecurityConfig', 'SwaggerConfig', 'JwtRequestFilter', 'JwtValidatorService', 'JwtValidatorServiceImpl',
                    'ActivityLogger', 'ConstanApi'}
STATUSES = {200: 'OK', 201: 'CREATED', 202: 'ACCEPTED', 204: 'NO_CONTENT'}
METHODS = {'GET': 'GetMapping', 'POST': 'PostMapping', 'PUT': 'PutMapping', 'DELETE': 'DeleteMapping', 'PATCH': 'PatchMapping'}
UNSUPPORTED_SCHEMA_KEYS = {'minimum', 'maximum', 'minLength', 'maxLength', 'pattern', 'minItems', 'maxItems', 'oneOf', 'allOf', 'anyOf',
                           'additionalProperties', 'nullable', 'readOnly', 'writeOnly', 'enum'}


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


class Models:
    """Walk resolved OpenAPI schemas into Java DTO descriptions."""

    def __init__(self):
        self.classes = {}

    def java_type(self, node, hint, parent, role, constraints=False):
        resolved = node.get('resolved', node)
        ref = (node.get('source') or {}).get('$ref')
        name = ref.rsplit('/', 1)[-1] if ref else None
        if 'properties' in resolved or resolved.get('type') == 'object':
            cname = name or (pascal(hint) + 'Type')
            check(re.fullmatch(r'[A-Z][A-Za-z0-9]*', cname) is not None and cname not in RESERVED_CLASSES,
                  f'unsupported-bff-binding: unsafe or reserved DTO name {cname!r}')
            signature = self.signature(resolved) + ('|request-validated' if constraints else '')
            if cname in self.classes and self.classes[cname]['signature'] != signature:
                cname = pascal(parent) + cname
            check(cname not in self.classes or self.classes[cname]['signature'] == signature,
                  'unsupported-bff-binding: incompatible duplicate DTO definition')
            if cname not in self.classes:
                self.classes[cname] = {'name': cname, 'role': role, 'fields': [], 'signature': signature}
                if resolved.get('additionalProperties') is True:
                    self.classes[cname]['additionalProperties'] = True
                if constraints:
                    self.classes[cname]['validated'] = True
                required = set(resolved.get('required') or []) if constraints else set()
                fields = []
                for prop, sub in (resolved.get('properties') or {}).items():
                    check(re.fullmatch(r'[a-z][A-Za-z0-9]*', prop) is not None and prop not in JAVA_KEYWORDS,
                          f'unsupported-bff-binding: unsafe DTO property {prop!r}')
                    field = {'name': prop, 'javaType': self.java_type(sub, prop, cname, 'type', constraints)}
                    if prop in required:
                        field['required'] = True
                    if constraints and isinstance(sub.get('resolved', sub).get('maxLength'), int):
                        field['maxLength'] = sub.get('resolved', sub)['maxLength']
                    fields.append(field)
                self.classes[cname]['fields'] = fields
            return cname
        if resolved.get('type') == 'array':
            return 'List<' + self.java_type(resolved.get('items') or {}, hint + 'Item', parent, 'type', constraints) + '>'
        return scalar_type(resolved, f'{parent}.{hint}')

    def signature(self, resolved):
        return json.dumps(resolved, sort_keys=True, separators=(',', ':'))


def scalar_type(resolved, where):
    kind, fmt = resolved.get('type'), resolved.get('format')
    if kind == 'integer':
        return 'Long' if fmt == 'int64' else 'Integer'
    if kind == 'number':
        return 'Double'
    if kind == 'boolean':
        return 'Boolean'
    check(kind in (None, 'string'), f'unsupported-bff-binding: schema type {kind!r} at {where}')
    return 'String'


def check_constraints(value, oid, allow_required=False):
    if isinstance(value, dict):
        unsupported = UNSUPPORTED_SCHEMA_KEYS & set(value)
        check(not unsupported, f'unsupported-bff-binding: {oid}: unsupported schema constraints {sorted(unsupported)}')
        check(allow_required or not value.get('required') or isinstance(value.get('required'), bool),
              f'unsupported-bff-binding: {oid}: required body fields are unsupported')
        for child in value.values():
            check_constraints(child, oid, allow_required)
    elif isinstance(value, list):
        for child in value:
            check_constraints(child, oid, allow_required)


REQUEST_ONLY_KEYS = {'maxLength', 'additionalProperties'}


def check_request_schema(node, oid, where='body'):
    """Request-body schemas accept `required`, `maxLength` (strings) and `additionalProperties: true` (objects); every other constraint stays unsupported."""
    if not isinstance(node, dict):
        return
    node = node.get('resolved', node)
    unsupported = (UNSUPPORTED_SCHEMA_KEYS - REQUEST_ONLY_KEYS) & set(node)
    check(not unsupported, f'unsupported-bff-binding: {oid}: unsupported schema constraints {sorted(unsupported)} at {where}')
    properties = node.get('properties') or {}
    required = node.get('required')
    check(required is None or (isinstance(required, list) and all(isinstance(r, str) and r in properties for r in required)),
          f'unsupported-bff-binding: {oid}: invalid required list at {where}')
    if 'maxLength' in node:
        check(node.get('type') == 'string' and isinstance(node['maxLength'], int) and not isinstance(node['maxLength'], bool) and node['maxLength'] >= 0,
              f'unsupported-bff-binding: {oid}: maxLength needs a string schema and a non-negative integer at {where}')
    if 'additionalProperties' in node:
        check(node['additionalProperties'] is True and node.get('type') == 'object',
              f'unsupported-bff-binding: {oid}: only additionalProperties: true on object schemas is supported at {where}')
    for prop, sub in properties.items():
        check_request_schema(sub, oid, f'{where}.{prop}')
    if node.get('items') is not None:
        check_request_schema(node['items'], oid, where + '[]')


def check_request_body(body, oid):
    check_constraints({k: v for k, v in (body or {}).items() if k != 'content'}, oid)
    for media in ((body or {}).get('content') or {}).values():
        check_constraints({k: v for k, v in media.items() if k != 'schema'}, oid)
        check_request_schema(media.get('schema'), oid)


def validate_binding(oid, binding, has_body, params=()):
    check(isinstance(binding, dict) and binding.get('version') == BINDING_VERSION, f'unsupported-bff-binding: {oid}: bffBinding version 1 required')
    evidence = binding.get('evidence')
    check(isinstance(evidence, list) and evidence and all(isinstance(e, str) and e for e in evidence), f'unsupported-bff-binding: {oid}: bffBinding.evidence is required')
    integration = binding.get('integration')
    check(isinstance(integration, dict), f'unsupported-bff-binding: {oid}: integration required')
    name, prefix, method = integration.get('name'), integration.get('propertyPrefix'), integration.get('method')
    check(isinstance(name, str) and re.fullmatch(r'[a-z][A-Za-z0-9]*', name) is not None and name not in JAVA_KEYWORDS, f'unsupported-bff-binding: {oid}: unsafe integration name')
    check(isinstance(prefix, str) and re.fullmatch(r'[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*', prefix) is not None, f'unsupported-bff-binding: {oid}: unsafe propertyPrefix')
    check(method in METHODS, f'unsupported-bff-binding: {oid}: unsupported integration method')
    forward = integration.get('forwardRequestBody')
    check(isinstance(forward, bool) and (not forward or has_body), f'unsupported-bff-binding: {oid}: forwardRequestBody must be boolean and requires a request body')
    check(not forward or method in ('POST', 'PUT', 'PATCH'), f'unsupported-bff-binding: {oid}: only POST/PUT/PATCH integrations may forward a body')
    check(integration.get('responseMapping') == 'identity', f'unsupported-bff-binding: {oid}: only responseMapping identity is supported')
    forward_parameters = integration.get('forwardParameters', False)
    check(isinstance(forward_parameters, bool), f'unsupported-bff-binding: {oid}: forwardParameters must be boolean')
    backend_path = integration.get('backendPath')
    check(backend_path is None or (forward_parameters and isinstance(backend_path, str) and re.fullmatch(r'/[A-Za-z0-9/_{}.-]*', backend_path) is not None),
          f'unsupported-bff-binding: {oid}: backendPath is optional, safe and requires forwardParameters')
    if backend_path is not None:
        placeholders = set(re.findall(r'\{([^{}]+)\}', backend_path))
        expected = {p['name'] for p in params if p['in'] == 'path'}
        check(placeholders == expected, f'unsupported-bff-binding: {oid}: backendPath placeholders {sorted(placeholders)} differ from the path parameters {sorted(expected)}')
    return {'name': name, 'propertyPrefix': prefix, 'method': method, 'forwardRequestBody': forward, 'forwardParameters': forward_parameters,
            'backendPath': backend_path, 'responseMapping': 'identity', 'evidence': list(evidence)}


def parameters_of(contract, oid):
    out, seen = [], set()
    for where in ('path', 'query', 'header'):
        for param in contract.get('parameters', {}).get(where) or []:
            name = param['name']
            check(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', name) is not None, f'unsupported-bff-binding: {oid}: unsafe parameter name {name!r}')
            schema = param.get('schema') or {}
            check(schema.get('type', 'string') != 'array' and 'enum' not in schema, f'unsupported-bff-binding: {oid}: unsupported parameter schema for {name}')
            var = camel(name)
            check(var and var not in JAVA_KEYWORDS and var not in seen and var != 'body', f'unsupported-bff-binding: {oid}: parameter variable collision for {name}')
            seen.add(var)
            required = True if where == 'path' else bool(param.get('required'))
            out.append({'name': name, 'in': where, 'variable': var, 'javaType': scalar_type(schema, f'{oid}.{name}'), 'required': required})
    cookies = contract.get('parameters', {}).get('cookie')
    check(not cookies, f'unsupported-bff-binding: {oid}: cookie parameters are unsupported')
    return out


def build(root: Path, yaml, input_path: Path):
    ws = (root / input_path).parent
    spec = base.read_yaml(ws / 'service-spec.yml', root, yaml)[0]
    config = base.read_yaml(root / input_path, root, yaml)[0]
    target = config['target']
    check(target['service'] == spec['service']['name'], 'Target and service-spec disagree.')
    archetype_root = root / target['archetype']
    archetype = base.read_yaml(archetype_root / 'archetype.yml', root, yaml)[0]
    identity = archetype.get('identity') or {}
    check(identity.get('generationEnabled') is True and identity.get('approved') is True, 'The selected archetype is not approved/enabled for generation.')
    check((archetype.get('generation') or {}).get('profile') == PROFILE, 'The archetype generation profile differs from this planner.')
    ready = spec.get('readiness', {})
    check(ready.get('contractComplete') is True and (ready.get('strictImplementationReady') is True or ready.get('scaffoldImplementationReady') is True),
          'service-spec has no complete active contract (contractComplete and scaffold/strict readiness are required).')
    check(re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+', target['base_package']) is not None, 'Unsafe Java package.')
    out_dir = Path(target['output_directory'])
    check(not out_dir.is_absolute() and out_dir.parts[:1] == ('output',) and '..' not in out_dir.parts and out_dir.as_posix() == f"output/{target['service']}",
          'Output must be output/<service>.')
    tpl = dict(config.get('template_parameters') or {})
    missing = [p for p in ENV_PARAMS if not tpl.get(p)]
    check(not missing, 'Unresolved parameters (provide them in template_parameters; never invented): ' + ', '.join(missing))
    app_class = tpl.get('APPLICATION_CLASS') or pascal(target['service']) + 'Application'
    check(re.fullmatch(r'[A-Z][A-Za-z0-9]*', app_class) is not None, 'Unsafe application class name.')
    values = {'GROUP_ID': target['group_id'], 'ARTIFACT_ID': base.technical_identifier(target['service']), 'PROJECT_VERSION': target['project_version'],
              'BASE_PACKAGE': target['base_package'], 'BASE_PACKAGE_PATH': target['base_package'].replace('.', '/'),
              'APPLICATION_CLASS': app_class, **{p: tpl[p] for p in ENV_PARAMS}}
    declared = archetype.get('parameters', [])
    declared = declared if isinstance(declared, list) else [{'name': k, **v} for k, v in declared.items()]
    for param in declared:
        pattern = param.get('pattern')
        check(param['name'] not in values or not pattern or re.fullmatch(pattern, str(values[param['name']])) is not None,
              f"Parameter {param['name']} violates the archetype pattern.")
    style = (archetype.get('generation') or {}).get('style')
    check(isinstance(style, dict) and style.get('constantsClass') == 'utils.ConstanApi' and style.get('externalPropertiesClass') == 'configuration.WsResponseProperties',
          'The archetype must declare generation.style with the supported constants/properties classes.')
    blocking = [i.get('id', 'unresolved') for k in ('conflicts', 'ambiguities', 'missingEvidence')
                for i in (spec.get('unresolved') or {}).get(k) or [] if isinstance(i, dict) and i.get('implementationBlocker') is not False]
    base_name = re.sub(r'Application$', '', app_class) or pascal(target['service'])
    names = {'controller': base_name + 'Controller', 'controllerImpl': base_name + 'ControllerImpl', 'service': base_name + 'Service',
             'serviceImpl': base_name + 'ServiceImpl'}
    models, operations, omitted, integrations = Models(), [], [], {}
    for op in spec['operations']:
        oid = op['operationId']
        check(isinstance(oid, str) and re.fullmatch(r'[a-z][A-Za-z0-9]*', oid) is not None and oid not in JAVA_KEYWORDS,
              'unsupported-bff-binding: unsafe operation identifier')
        contract = op['contract']
        check_constraints({k: v for k, v in contract.items() if k not in ('responses', 'requestBody')}, oid)
        check_request_body(contract.get('requestBody'), oid)
        check_constraints(contract.get('responses') or {}, oid, allow_required=True)  # response DTOs are decoded, never validated: `required` is lossless
        check(op['method'] in METHODS, f'unsupported-bff-binding: {oid}: unsupported HTTP method')
        content = (contract.get('requestBody') or {}).get('content', {})
        check(set(content) <= {'application/json'}, f'unsupported-bff-binding: {oid}: only JSON request bodies are supported')
        request = models.java_type(content['application/json']['schema'], oid + 'Request', oid, 'request', True) if content else None
        success = [code for code in contract.get('responses', {}) if re.fullmatch(r'2\d\d', str(code))]
        check(len(success) == 1 and int(success[0]) in STATUSES, f'unsupported-bff-binding: {oid}: exactly one 2xx response (200/201/202/204) is required')
        success_content = contract['responses'][success[0]].get('content', {}) or {}
        check(set(success_content) <= {'application/json'}, f'unsupported-bff-binding: {oid}: only JSON responses are supported')
        response = models.java_type(success_content['application/json']['schema'], oid + 'Response', oid, 'response') if success_content else None
        params = parameters_of(contract, oid)
        entry = {'operationId': oid, 'httpMethod': op['method'], 'path': op['path'], 'successStatus': int(success[0]), 'parameters': params,
                 'requestClass': request, 'requestRequired': bool((contract.get('requestBody') or {}).get('required')), 'responseClass': response, 'binding': None}
        action_list = (op.get('behavior') or {}).get('actions') or []
        if op.get('bffBinding') is not None:
            check(not blocking, f'unsupported-bff-binding: {oid}: unresolved blocking items in service-spec: {blocking[:5]}')
            check(len(action_list) == 1 and action_list[0].get('implementationComplete') is True, f'unsupported-bff-binding: {oid}: exactly one complete behavior action required for a binding')
            binding = validate_binding(oid, op['bffBinding'], request is not None, params)
            check(response is not None, f'unsupported-bff-binding: {oid}: an identity binding needs a response body')
            previous = integrations.get(binding['name'])
            check(previous is None or previous['propertyPrefix'] == binding['propertyPrefix'],
                  f'unsupported-bff-binding: integration {binding["name"]} is declared with different property prefixes')
            check(all(i['propertyPrefix'] != binding['propertyPrefix'] or n == binding['name'] for n, i in integrations.items()) and
                  all(n.lower() != binding['name'].lower() or n == binding['name'] for n in integrations),
                  f'unsupported-bff-binding: integration names/prefixes collide for {binding["name"]}')
            integrations.setdefault(binding['name'], {'propertyPrefix': binding['propertyPrefix'], 'client': pascal(binding['name']) + 'Client',
                                                      'config': pascal(binding['name']) + 'WebClientConfig'})
            entry['binding'] = binding
            earlier = [o['binding'] for o in operations if o['binding'] and o['binding']['name'] == binding['name']]
            check(not earlier or not (binding['forwardParameters'] or any(e['forwardParameters'] for e in earlier)),
                  f'unsupported-bff-binding: {oid}: an integration that forwards parameters serves exactly one operation (one url property per integration)')
        else:
            reason = 'no explicit bffBinding in service-spec' + ('; blocking unresolved items: ' + ', '.join(map(str, blocking[:5])) if blocking else '')
            omitted.append({'operationId': oid, 'reason': reason})
        operations.append(entry)
    check(len({o['operationId'] for o in operations}) == len(operations), 'Duplicate operation identifiers')
    check(len({(o['httpMethod'], o['path']) for o in operations}) == len(operations), 'Duplicate method/path pairs')
    generated = set(names.values()) | {i['client'] for i in integrations.values()} | {i['config'] for i in integrations.values()} | {app_class}
    check(not (generated | set(models.classes)) & RESERVED_CLASSES and not generated & set(models.classes) and len(generated) == len(names) + 2 * len(integrations) + 1,
          'Generated class names collide with DTO or archetype technical classes.')
    return spec, config, archetype, archetype_root, values, style, models, operations, omitted, integrations, names, app_class


def has_request_contract(c):
    return bool(c.get('validated') and (c.get('additionalProperties') or any(f.get('required') or f.get('maxLength') is not None for f in c['fields'])))


def request_contract_classes(models):
    return [c for _, c in sorted(models.classes.items()) if has_request_contract(c)]


def files_plan(base_pkg, models, operations, integrations, names):
    pp = base_pkg.replace('.', '/')
    main, test = f'src/main/java/{pp}', f'src/test/java/{pp}'
    files = []

    def add(path, ctype):
        files.append({'path': path, 'action': 'create', 'componentType': ctype})
    for cname, c in sorted(models.classes.items()):
        add(f"{main}/dto/{ {'request': 'request', 'response': 'response'}.get(c['role'], 'type') }/{cname}.java", 'contract-dto')
    add(f"{main}/controller/{names['controller']}.java", 'api-interface')
    add(f"{main}/controller/impl/{names['controllerImpl']}.java", 'controller')
    add(f"{main}/service/{names['service']}.java", 'service-interface')
    add(f"{main}/service/impl/{names['serviceImpl']}.java", 'service')
    for name, item in sorted(integrations.items()):
        add(f"{main}/client/{name.lower()}/{item['config']}.java", 'webclient-config')
        add(f"{main}/client/{name.lower()}/{item['client']}.java", 'webclient-client')
        if any(o['binding'] and o['binding']['name'] == name and o['binding']['forwardParameters'] for o in operations):
            add(f"{test}/client/{name.lower()}/{item['client']}Test.java", 'unit-test-junit5')
    add(f"{test}/controller/impl/{names['controllerImpl']}Test.java", 'unit-test-junit5')
    if request_contract_classes(models):
        add(f"{test}/dto/request/RequestContractTest.java", 'unit-test-junit5')
    add(f"{test}/service/impl/{names['serviceImpl']}Test.java", 'unit-test-junit5')
    return files


def artifacts(root: Path, yaml, input_path: Path):
    ws = (root / input_path).parent
    (spec, config, archetype, archetype_root, values, style, models, operations, omitted, integrations, names, app_class) = build(root, yaml, input_path)
    target = config['target']
    files = files_plan(target['base_package'], models, operations, integrations, names)
    render = lambda s: re.sub(r'@@([A-Z0-9_]+)@@', lambda m: str(values[m.group(1)]), s)
    from artifact_integrity import template_paths
    for relative in template_paths(archetype_root):
        path = render(relative)
        check(path not in {e['path'] for e in files}, f'Generated file {path} collides with an archetype template file.')
        files.append({'path': path, 'action': 'create', 'componentType': 'archetype-template'})
    spec_path = ws / 'service-spec.yml'
    params = {'version': 2, 'mode': 'full', 'service': target['service'], 'values': values, 'resolved': [], 'unresolved': [],
              'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'sha256': sha(spec_path.read_bytes())},
                         'archetype': {'path': target['archetype'], 'fingerprint': base.archetype_fingerprint(archetype_root)},
                         'planningInput': {'path': '.factory/full-planning-input.yml', 'sha256': sha((root / input_path).read_bytes())}},
              'functional': {'profile': PROFILE, 'scope': 'structure-and-contract'}, 'readiness': {'functionalGenerationReady': True},
              'secretsStored': False, 'validation': {'errors': []}}
    params_raw = base.dump_yaml(params, yaml)
    plan = {'plan': {'version': 3, 'mode': 'full', 'profile': PROFILE, 'bffBindingVersion': BINDING_VERSION, 'scope': 'structure-and-contract'},
            'service': {'name': target['service'], 'outputDirectory': target['output_directory'], 'basePackage': target['base_package'], 'applicationClass': app_class},
            'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'artifactSha256': sha(spec_path.read_bytes())},
                       'archetype': params['inputs']['archetype'],
                       'generationParameters': {'path': '.factory/generation-parameters.yml', 'sha256': sha(params_raw)},
                       'planningInput': params['inputs']['planningInput']},
            'technicalProfile': {'persistence': 'not-present-in-reference', 'jpa': False, 'activityLogger': 'template-utility-not-invoked-by-generated-code',
                                 'checkstyle': 'required-by-reference-unverified', 'tests': 'junit5+mockito', 'names': names, 'style': style,
                                 'java': str(archetype['platform']['java'])[:40]},
            'templateParameters': values,
            'models': [{'name': n, 'role': c['role'], 'fields': c['fields'], **({'validated': True} if has_request_contract(c) else {}),
                        **({'additionalProperties': True} if c.get('additionalProperties') else {})}
                       for n, c in sorted(models.classes.items())],
            'integrations': {n: i for n, i in sorted(integrations.items())},
            'operations': operations, 'omittedBehavior': omitted, 'incompleteOperations': [], 'assumptions': [],
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
    print({'mode': 'full', 'profile': PROFILE, 'operations': len(plan['operations']), 'omittedBehavior': [o['operationId'] for o in plan['omittedBehavior']],
           'models': len(plan['models']), 'plannedFiles': len(plan['files']['generate']), 'planSha256': sha((ws / 'implementation-plan.yml').read_bytes())})
    return 0
