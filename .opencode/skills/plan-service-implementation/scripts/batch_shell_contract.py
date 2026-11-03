"""Closed, evidence-backed batch IR. No Java snippets or implicit business defaults."""
import re

PROFILE = 'batch-shell-jar-spring-xml-log4j-sftp-junit4'
KEYWORDS = set(('abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while true false null _').split())
IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
PROPERTY = re.compile(r'^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$')
GENERIC_KEYS = {'log4j.file.dir', *(f'{code}.{part}' for code in ('idf0', 'idf1', 'idt1', 'idt2', 'idt3') for part in ('codigo', 'mensaje'))}
DECRYPT_FEATURE = 'credential-decrypt-soap'
DECRYPT_FIELDS = {'wsEbsConsultaClavesWSUrl', 'wsEbsConsultaClavesWSMaxRequestTimeout',
                  'wsEbsConsultaClavesWSMaxConnectionTimeout', 'wsEbsConsultaClavesWSCodigoAplicacion'}
STRUCTURE_ONLY = 'structure-only'
PORTS_FLOW = 'ports-flow'
RESERVED_LOCALS = {'msjTrx', 'nomMetodoActual', 'tiempoInicio', 'messageTransaction', 'idTransaccion', 'e', 'logger',
                   'externalProperties', 'service', 'appender'}
PRIMITIVES = ('String', 'Integer', 'Long', 'Boolean')
GENERIC_FIELDS = {'log4jDir', *(code + part for code in ('idf0', 'idf1', 'idt1', 'idt2', 'idt3') for part in ('Codigo', 'Mensaje'))}


def require(ok, message):
    if not ok:
        raise ValueError('batch: ' + message)


def identifier(value):
    require(isinstance(value, str) and IDENTIFIER.fullmatch(value) and value not in KEYWORDS,
            f'invalid Java identifier {value!r}')
    return value


def keys(obj, allowed, required):
    require(isinstance(obj, dict), 'expected a mapping')
    require(not set(obj) - set(allowed), f'unsupported fields {sorted(set(obj) - set(allowed))}')
    require(set(required) <= set(obj), f'missing fields {sorted(set(required) - set(obj))}')


def features_of(generation):
    """Feature modules the selected archetype declares AND this backend implements."""
    return frozenset(m['id'] for m in (generation or {}).get('featureModules', ())
                     if isinstance(m, dict) and str(m.get('backendSupport', '')).startswith('supported'))


def _validate_ports_flow(batch, evidence):
    """Orchestration of the Sparx flow against generated ports; no concrete integration is implied."""
    omitted = batch['omittedBehavior']
    require(isinstance(omitted, list) and omitted, 'ports-flow scope requires explicit omittedBehavior')
    ids = set()
    for item in omitted:
        keys(item, ('id', 'description', 'evidence'), ('id', 'description', 'evidence'))
        require(identifier(item['id']) not in ids and isinstance(item['description'], str) and item['description'].strip(),
                'omitted behavior needs a unique id and description')
        ids.add(item['id'])
        evidence(item)
    require(batch['connections'] == [] and batch['steps'] == [] and batch['properties'] == [],
            'ports-flow scope declares no properties, connections or steps')
    outcomes = batch['outcomes']
    keys(outcomes, ('success', 'generalFailure', 'evidence'), ('success', 'generalFailure', 'evidence'))
    evidence(outcomes)
    require(outcomes['success'] in ('idf0', 'idf1') and outcomes['generalFailure'] in ('idt1', 'idt2', 'idt3'),
            'unsupported outcome property group')

    dtos = {}
    require(isinstance(batch['dtos'], list) and batch['dtos'], 'dtos required')
    for dto in batch['dtos']:
        keys(dto, ('name', 'fields', 'evidence'), ('name', 'fields', 'evidence'))
        name = identifier(dto['name'])
        require(name[0].isupper() and name not in dtos and name not in PRIMITIVES, 'invalid or duplicate dto name')
        evidence(dto)
        require(isinstance(dto['fields'], list) and dto['fields'], 'dto fields required')
        fnames = set()
        for field in dto['fields']:
            keys(field, ('name', 'type'), ('name', 'type'))
            require(identifier(field['name']) not in fnames and field['type'] in PRIMITIVES, 'invalid dto field')
            fnames.add(field['name'])
        dtos[name] = {f['name']: f['type'] for f in dto['fields']}

    def ptype(text):
        require(isinstance(text, str), 'type expected')
        inner = text[5:-1] if text.startswith('List<') and text.endswith('>') else text
        require(inner in dtos or (inner in PRIMITIVES and inner == text), f'unknown type {text!r}')
        return text

    ports = {}
    require(isinstance(batch['ports'], list) and batch['ports'], 'ports required')
    for port in batch['ports']:
        keys(port, ('id', 'kind', 'methods', 'evidence'), ('id', 'kind', 'methods', 'evidence'))
        pid = identifier(port['id'])
        require(pid[0].isupper() and pid not in ports and pid not in dtos, 'invalid or duplicate port id')
        require(port['kind'] in ('db', 'rest', 'mail'), 'unsupported port kind')
        evidence(port)
        methods = {}
        require(isinstance(port['methods'], list) and port['methods'], 'port methods required')
        for method in port['methods']:
            keys(method, ('name', 'params', 'returns', 'evidence'), ('name', 'params', 'returns', 'evidence'))
            mname = identifier(method['name'])
            require(mname not in methods, 'duplicate port method')
            evidence(method)
            params = []
            require(isinstance(method['params'], list), 'params must be a list')
            for param in method['params']:
                keys(param, ('name', 'type'), ('name', 'type'))
                identifier(param['name'])
                params.append(ptype(param['type']))
            returns = method['returns']
            require(returns == 'void' or ptype(returns), 'invalid return type')
            methods[mname] = (params, returns)
        ports[pid] = methods

    seen = set()
    used_methods = set()
    port_fields = {pid[:1].lower() + pid[1:] for pid in ports}

    def operand(text, env):
        require(isinstance(text, str), 'operand expected')
        head, _, field = text.partition('.')
        require(head in env, f'unknown variable {head!r}')
        vtype = env[head]
        if not field:
            return vtype
        require(vtype in dtos and field in dtos[vtype], f'unknown field {text!r}')
        return dtos[vtype][field]

    def simple(cond, env):
        keys(cond, ('left', 'op', 'right'), ('left', 'op'))
        op = cond['op']
        require(op in ('<', 'present', 'nonempty', 'equals', 'true'), 'unsupported condition operator')
        if op == '<':
            require('right' in cond and operand(cond['left'], env) == 'Integer'
                    and operand(cond['right'], env) == 'Integer', 'comparison needs Integer operands')
        elif op == 'present':
            require('right' not in cond and cond['left'] in env and env[cond['left']] in dtos,
                    'present needs a dto variable')
        elif op == 'nonempty':
            require('right' not in cond and cond['left'] in env and env[cond['left']].startswith('List<'),
                    'nonempty needs a list variable')
        elif op == 'equals':
            vtype = operand(cond['left'], env)
            require(vtype in ('Integer', 'Long', 'String') and 'right' in cond, 'equals needs an Integer, Long or String operand')
            if vtype == 'String':
                require(isinstance(cond['right'], str), 'equals literal must be a string')
            else:
                require(isinstance(cond['right'], int) and not isinstance(cond['right'], bool),
                        'equals literal must be an integer')
        else:
            require('right' not in cond and operand(cond['left'], env) == 'Boolean', 'true needs a Boolean operand')

    def condition(step, env):
        """A step condition is either one simple comparison or all/any of several."""
        if 'all' in step or 'any' in step:
            require(('all' in step) != ('any' in step) and not ({'left', 'op', 'right'} & set(step)),
                    'condition is a simple comparison or exactly one of all/any')
            group = step.get('all', step.get('any'))
            require(isinstance(group, list) and len(group) >= 2, 'all/any need at least two comparisons')
            for cond in group:
                simple(cond, env)
        else:
            simple({k: step[k] for k in ('left', 'op', 'right') if k in step}, env)

    def walk(steps, env, depth):
        require(isinstance(steps, list) and steps, 'nonempty explicit flow steps required')
        in_loop = depth > 0
        for step in steps:
            kind = step.get('kind') if isinstance(step, dict) else None
            common = {'id', 'kind', 'evidence'}
            cond_keys = {'left', 'op', 'right', 'all', 'any'}
            extra = {'call': {'port', 'method', 'args', 'result', 'onFailure'}, 'for-each': {'list', 'item', 'steps'},
                     'if': cond_keys | {'then', 'else'}, 'guard': cond_keys}
            require(kind in extra, f'unsupported flow step kind {kind!r}')
            required = {'call': {'port', 'method', 'args', 'onFailure'}, 'for-each': {'list', 'item', 'steps'},
                        'if': {'then'}, 'guard': set()}[kind]
            keys(step, common | extra[kind], common | required)
            require(identifier(step['id']) not in seen, 'duplicate flow step id')
            seen.add(step['id'])
            evidence(step)
            if kind == 'call':
                require(step['port'] in ports and step['method'] in ports[step['port']], 'unknown port method')
                params, returns = ports[step['port']][step['method']]
                require(isinstance(step['args'], list) and len(step['args']) == len(params), 'argument count mismatch')
                for arg, expected in zip(step['args'], params):
                    require(operand(arg, env) == expected, 'argument type mismatch')
                require(step['onFailure'] in ('abort', 'skip-item', 'log'), 'unsupported failure policy')
                require(step['onFailure'] != 'skip-item' or in_loop, 'skip-item only inside for-each')
                require(step['onFailure'] != 'abort' or not in_loop, 'abort is not supported inside for-each; use skip-item or log')
                used_methods.add((step['port'], step['method']))
                if 'result' in step:
                    require(returns != 'void' and identifier(step['result']) not in env, 'invalid call result variable')
                    require(step['result'] not in RESERVED_LOCALS and step['result'] not in port_fields,
                            'call result variable collides with a generated name')
                    env[step['result']] = returns
                else:
                    require(returns == 'void', 'non-void call needs a result variable')
            elif kind == 'for-each':
                require(depth < 2, 'loops nested deeper than two levels are unsupported')
                require(step['list'] in env and env[step['list']].startswith('List<'), 'for-each needs a list variable')
                item_type = env[step['list']][5:-1]
                require(identifier(step['item']) not in env, 'loop variable already declared')
                require(step['item'] not in RESERVED_LOCALS and step['item'] not in port_fields, 'loop variable collides with a generated name')
                walk(step['steps'], {**env, step['item']: item_type}, depth + 1)
            elif kind == 'guard':
                require(in_loop, 'guard only inside for-each')
                condition(step, env)
            else:
                condition(step, env)
                walk(step['then'], dict(env), depth)
                if 'else' in step:
                    walk(step['else'], dict(env), depth)

    walk(batch['flow'], {}, 0)
    require({(p, m) for p, ms in ports.items() for m in ms} == used_methods, 'every declared port method must be used by the flow')
    if 'adapters' in batch:
        validate_adapters(batch, evidence)


VERBS = ('GET', 'POST', 'PATCH')
RESULTS = ('none', 'scalar', 'single', 'list')
MAIL_FIELDS = ('subject', 'to', 'cc', 'bcc', 'bodyFormat', 'body')


def _ref(text, params, dtos):
    require(isinstance(text, str), 'argument reference expected')
    name, _, field = text.partition('.')
    require(name in params, f'unknown argument {name!r}')
    kind = params[name]
    if field:
        require(kind in dtos and field in dtos[kind], f'unknown field {text!r}')
        return dtos[kind][field]
    require(kind in PRIMITIVES, f'argument {name!r} is not a primitive')
    return kind


def validate_adapters(batch, evidence):
    """Concrete integrations for declared ports; everything derived from names is an explicit assumption."""
    dtos = {d['name']: {f['name']: f['type'] for f in d['fields']} for d in batch['dtos']}
    ports = {p['id']: p for p in batch['ports']}
    adapters = batch['adapters']
    require(isinstance(adapters, list) and adapters, 'adapters must be a non-empty list')
    seen = set()
    for adapter in adapters:
        keys(adapter, ('port', 'methods', 'evidence'), ('port', 'methods', 'evidence'))
        require(adapter['port'] in ports and adapter['port'] not in seen, 'adapter needs a unique declared port')
        seen.add(adapter['port'])
        evidence(adapter)
        port = ports[adapter['port']]
        declared = {m['name']: m for m in port['methods']}
        require(isinstance(adapter['methods'], list)
                and [m.get('name') for m in adapter['methods']] and
                sorted(m.get('name') for m in adapter['methods']) == sorted(declared),
                'adapter must implement every method of its port exactly once')
        for method in adapter['methods']:
            spec = declared[method['name']]
            params = {p['name']: p['type'] for p in spec['params']}
            returns = spec['returns']
            inner = returns[5:-1] if returns.startswith('List<') else returns
            require(method.get('assumed') is True, 'adapter methods must be marked assumed')
            evidence(method)
            if port['kind'] == 'db':
                keys(method, ('name', 'sql', 'bind', 'result', 'columns', 'assumed', 'evidence'),
                     ('name', 'sql', 'bind', 'result', 'columns', 'assumed', 'evidence'))
                require(isinstance(method['sql'], str) and method['sql'].strip(), 'sql required')
                require(isinstance(method['bind'], list) and method['sql'].count('?') == len(method['bind']),
                        'bind must match the sql placeholders')
                for ref in method['bind']:
                    _ref(ref, params, dtos)
                result = method['result']
                require(result in RESULTS, 'unsupported result kind')
                expected = {'none': returns == 'void', 'scalar': returns in PRIMITIVES,
                            'single': returns in dtos, 'list': returns.startswith('List<')}[result]
                require(expected, 'result kind does not match the port return type')
                cols = method['columns']
                require(isinstance(cols, list), 'columns must be a list')
                if result in ('single', 'list'):
                    require(cols, 'columns required for dto results')
                    fields = set()
                    for col in cols:
                        keys(col, ('column', 'field'), ('column', 'field'))
                        require(isinstance(col['column'], str) and col['column'].strip()
                                and col['field'] in dtos[inner] and col['field'] not in fields, 'invalid column mapping')
                        fields.add(col['field'])
                else:
                    require(cols == [], 'columns only apply to dto results')
            elif port['kind'] == 'rest':
                keys(method, ('name', 'httpMethod', 'path', 'query', 'body', 'assumed', 'evidence', 'okStatus'),
                     ('name', 'httpMethod', 'path', 'query', 'body', 'assumed', 'evidence'))
                require(method['httpMethod'] in VERBS, 'unsupported http method')
                require(isinstance(method['path'], str) and method['path'].startswith('/') and ' ' not in method['path'],
                        'path must start with /')
                require(returns in ('void', 'Boolean') or inner in dtos, 'rest methods return void, Boolean or dto types')
                require(isinstance(method['query'], list), 'query must be a list')
                if 'okStatus' in method:
                    require(returns == 'Boolean' and isinstance(method['okStatus'], list) and method['okStatus']
                            and all(isinstance(s, int) and 100 <= s <= 599 for s in method['okStatus']),
                            'okStatus only applies to Boolean rest methods and lists HTTP statuses')
                for q in method['query']:
                    keys(q, ('name', 'value', 'from'), ('name',))
                    require(all(isinstance(q[k], str) and q[k] for k in q), 'query entries need text')
                    require(('from' in q) != ('value' in q), 'query entry needs exactly one of from/value')
                    if 'from' in q:
                        _ref(q['from'], params, dtos)
                require(isinstance(method['body'], list) and (not method['body'] or method['httpMethod'] != 'GET'),
                        'only POST/PATCH carry a body')
                for item in method['body']:
                    keys(item, ('json', 'from', 'value'), ('json',))
                    require(isinstance(item['json'], str) and item['json'], 'json name required')
                    require(('from' in item) != ('value' in item), 'body item needs exactly one of from/value')
                    if 'value' in item:
                        require(isinstance(item['value'], str) and item['value'], 'literal body value must be text')
                    else:
                        _ref(item['from'], params, dtos)
            else:
                keys(method, ('name', 'placeholders', 'assumed', 'evidence'),
                     ('name', 'placeholders', 'assumed', 'evidence'))
                require(returns == 'void' and spec['params'], 'mail methods return void and take the configuration dto')
                cfg = dtos.get(spec['params'][0]['type'])
                require(cfg and all(cfg.get(f) == 'String' for f in MAIL_FIELDS),
                        'first mail argument must be a dto with subject,to,cc,bcc,bodyFormat,body strings')
                tokens = set()
                for ph in method['placeholders']:
                    keys(ph, ('token', 'from'), ('token', 'from'))
                    require(isinstance(ph['token'], str) and re.fullmatch(r'\{[A-Za-z]+\}', ph['token'])
                            and ph['token'] not in tokens, 'placeholder token like {name}')
                    tokens.add(ph['token'])
                    _ref(ph['from'], params, dtos)
    return batch


def adapter_kinds(batch):
    ports = {p['id']: p['kind'] for p in batch.get('ports', ())}
    return sorted({ports[a['port']] for a in batch.get('adapters', ())})


def adapter_properties(batch):
    """Operator-provided keys derived from the adapter kinds; never carry values."""
    out = []
    ports = {p['id']: p['kind'] for p in batch.get('ports', ())}
    kinds = adapter_kinds(batch)
    if 'db' in kinds:
        out += [('bd.url', 'bdUrl', False), ('bd.user', 'bdUser', False), ('bd.password', 'bdPassword', True)]
    if 'rest' in kinds:
        for adapter in batch['adapters']:
            if ports[adapter['port']] == 'rest':
                pid = adapter['port']
                out.append((f'rest.{pid.lower()}.url', f'rest{pid}Url', False))
        out.append(('rest.timeout.ms', 'restTimeoutMs', False))
    if 'mail' in kinds:
        out += [('mail.smtp.host', 'mailSmtpHost', False), ('mail.smtp.port', 'mailSmtpPort', False),
                ('mail.smtp.user', 'mailSmtpUser', False), ('mail.smtp.password', 'mailSmtpPassword', True),
                ('mail.from', 'mailFrom', False)]
    return [{'key': k, 'field': f, 'secret': s} for k, f, s in out]


def maven_additions(batch):
    kinds = adapter_kinds(batch)
    out = []
    if 'rest' in kinds:
        out += [{'groupId': 'com.fasterxml.jackson.core', 'artifactId': 'jackson-databind', 'version': '2.9.10.8',
                 'justification': 'JSON body/response handling of the REST adapters', 'requiredBy': 'util/RestClienteHttp'},
                {'groupId': 'org.apache.httpcomponents', 'artifactId': 'httpclient', 'version': '4.5.13',
                 'justification': 'HTTP client with PATCH support for the REST adapters', 'requiredBy': 'util/RestClienteHttp'}]
    if 'mail' in kinds:
        out.append({'groupId': 'com.sun.mail', 'artifactId': 'javax.mail', 'version': '1.6.2',
                    'justification': 'SMTP notification adapter', 'requiredBy': 'port mail adapter'})
    return out


def validate(batch, features=frozenset()):
    """Validate normalized functional spec; evidence uses source binding ids, e.g. ea#node."""
    decrypt = DECRYPT_FEATURE in features
    base = ('version', 'properties', 'connections', 'steps', 'outcomes', 'sourceBindings')
    structure = isinstance(batch, dict) and batch.get('scope') == STRUCTURE_ONLY
    ports_flow = isinstance(batch, dict) and batch.get('scope') == PORTS_FLOW
    extra_keys = ('scope', 'omittedBehavior') if structure else (
        ('scope', 'omittedBehavior', 'dtos', 'ports', 'flow') if ports_flow else ())
    keys(batch, base + extra_keys + (('adapters',) if ports_flow else ()), base + extra_keys)
    require(batch['version'] == 1, 'unsupported IR version')
    require(isinstance(batch['sourceBindings'], list) and batch['sourceBindings'], 'source bindings required')
    bindings = set()
    for binding in batch['sourceBindings']:
        keys(binding, ('id', 'path', 'sha256'), ('id', 'path', 'sha256'))
        name = identifier(binding['id'])
        require(name not in bindings, 'duplicate source binding')
        bindings.add(name)
        path = binding['path']
        require(isinstance(path, str) and path.startswith('input/sparx/') and '\\' not in path
                and not set(path.split('/')) & {'', '.', '..'} and ':' not in path, 'unsafe Sparx source path')
        require(re.fullmatch('[a-f0-9]{64}', str(binding['sha256'])), 'source SHA-256 required')

    def evidence(obj):
        refs = obj.get('evidence')
        require(isinstance(refs, list) and refs and all(isinstance(r, str) and '#' in r
                and r.split('#', 1)[0] in bindings and r.split('#', 1)[1].strip() for r in refs), 'bound evidence required')

    require(isinstance(batch['properties'], list), 'properties must be a list')
    props, fields = {}, set(GENERIC_FIELDS) | (DECRYPT_FIELDS if decrypt else set())
    for prop in batch['properties']:
        keys(prop, ('key', 'field', 'secret', 'evidence'), ('key', 'field', 'secret', 'evidence'))
        key, field = prop['key'], identifier(prop['field'])
        require(PROPERTY.fullmatch(str(key)) and key not in GENERIC_KEYS and key not in props, 'duplicate/invalid property key')
        require(field not in fields and isinstance(prop['secret'], bool), 'duplicate field or missing secret classification')
        evidence(prop)
        props[key] = prop
        fields.add(field)

    def prop(key, secret=False):
        require(isinstance(key, str) and key in props, f'unknown property {key!r}')
        require(props[key]['secret'] is secret, f'property {key!r} has wrong secret classification')

    if ports_flow:
        _validate_ports_flow(batch, evidence)
        return batch
    if structure:
        omitted = batch['omittedBehavior']
        require(isinstance(omitted, list) and omitted, 'structure-only scope requires explicit omittedBehavior')
        ids = set()
        for item in omitted:
            keys(item, ('id', 'description', 'evidence'), ('id', 'description', 'evidence'))
            require(identifier(item['id']) not in ids and isinstance(item['description'], str) and item['description'].strip(),
                    'omitted behavior needs a unique id and description')
            ids.add(item['id'])
            evidence(item)
        require(batch['connections'] == [] and batch['steps'] == [] and batch['properties'] == [],
                'structure-only scope declares no properties, connections or steps')
        outcomes = batch['outcomes']
        keys(outcomes, ('generalFailure', 'evidence'), ('generalFailure', 'evidence'))
        evidence(outcomes)
        require(outcomes['generalFailure'] in ('idt1', 'idt2', 'idt3'), 'unsupported outcome property group')
        return batch

    require(isinstance(batch['connections'], list) and batch['connections'], 'SFTP connections required')
    connections = set()
    for conn in batch['connections']:
        keys(conn, ('id', 'username', 'host', 'port', 'password', 'credentialMode', 'evidence'),
             ('id', 'username', 'host', 'port', 'password', 'credentialMode', 'evidence'))
        name = identifier(conn['id'])
        require(name not in connections, 'duplicate connection')
        connections.add(name)
        evidence(conn)
        mode = conn['credentialMode']
        require(mode == 'resolved-external' or (mode == 'decrypted-soap' and decrypt),
                'unsupported credential mode: resolved-external, or decrypted-soap only when the selected archetype '
                'implements the credential-decrypt-soap feature')
        for key in ('username', 'host', 'port', 'password'):
            prop(conn[key], secret=(key == 'password' or (mode == 'decrypted-soap' and key == 'username')))

    outcomes = batch['outcomes']
    keys(outcomes, ('success', 'sftpFailure', 'generalFailure', 'evidence'), ('success', 'sftpFailure', 'generalFailure', 'evidence'))
    evidence(outcomes)
    for key in ('success', 'sftpFailure', 'generalFailure'):
        require(outcomes[key] in ('idf0', 'idf1', 'idt1', 'idt2', 'idt3'), 'unsupported outcome property group')

    seen, connected, used = set(), set(), set()
    def walk(steps, lists, in_loop=False):
        require(isinstance(steps, list) and steps, 'nonempty explicit steps required')
        for step in steps:
            kind = step.get('kind') if isinstance(step, dict) else None
            common = {'id', 'kind', 'evidence'}
            extra = {'connect': {'connection'}, 'disconnect': {'connection'},
                     'list-mtime': {'connection', 'remoteDirectory', 'date', 'dateFormat', 'onFailure', 'emptyPolicy'},
                     'list-name': {'connection', 'remoteDirectory', 'date', 'dateFormat', 'onFailure', 'emptyPolicy'},
                     'for-each': {'list', 'steps'},
                     'download': {'connection', 'remoteDirectory', 'filename', 'localDirectory', 'onFailure'},
                     'upload': {'connection', 'localDirectory', 'remoteDirectory', 'filename', 'onFailure'}}
            require(kind in extra, f'unsupported step kind {kind!r}')
            keys(step, common | extra[kind], common | extra[kind])
            name = identifier(step['id'])
            require(name not in seen, 'duplicate step id')
            seen.add(name)
            evidence(step)
            if 'onFailure' in step:
                require(step['onFailure'] == 'abort', 'only explicitly specified abort-on-failure is supported')
            if 'connection' in step:
                conn = step['connection']
                require(conn in connections, 'unknown connection')
                if kind == 'connect':
                    require(not in_loop and conn not in connected, 'connect must occur once outside loops')
                    connected.add(conn)
                    used.add(conn)
                elif kind == 'disconnect':
                    require(not in_loop and conn in connected, 'disconnect requires an open connection outside loops')
                    connected.remove(conn)
                else:
                    require(conn in connected, 'SFTP operation before connect or after disconnect')
            if kind.startswith('list-'):
                require(not in_loop, 'nested listing unsupported')
                require(step['emptyPolicy'] in ('success', 'abort'), 'explicit empty-list policy required')
                for key in ('remoteDirectory', 'date', 'dateFormat'):
                    prop(step[key])
                lists.add(name)
            elif kind == 'for-each':
                require(not in_loop and step['list'] in lists, 'loop needs a preceding list; nested loops unsupported')
                walk(step['steps'], set(lists), True)
            elif kind in ('download', 'upload'):
                for key in ('remoteDirectory', 'localDirectory'):
                    prop(step[key])
                filename = step['filename']
                if filename == '$item':
                    require(in_loop, '$item outside loop')
                else:
                    prop(filename)
    walk(batch['steps'], set())
    require(used == connections, 'unused connection declarations are not an implemented integration')
    return batch
