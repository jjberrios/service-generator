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


def validate(batch, features=frozenset()):
    """Validate normalized functional spec; evidence uses source binding ids, e.g. ea#node."""
    decrypt = DECRYPT_FEATURE in features
    keys(batch, ('version', 'properties', 'connections', 'steps', 'outcomes', 'sourceBindings'),
         ('version', 'properties', 'connections', 'steps', 'outcomes', 'sourceBindings'))
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
