"""Pure rendering of the `ports-flow` batch scope: Sparx flow orchestrated against generated ports.

Adapters (`<Port>Impl`) raise OperacionNoImplementadaException: no persistence, REST, mail or scheduling is implemented
or simulated. Tests are derived from the flow paths (conditions) and failure policies only.
"""
import itertools
import json

from batch_shell_contract import require

MAX_PATHS = 16


def literal(value):
    return json.dumps(value, ensure_ascii=True)


def lower(name):
    return name[:1].lower() + name[1:]


def upper(name):
    return name[:1].upper() + name[1:]


def jtype(text):
    return f'java.util.List<{text[5:-1]}>' if text.startswith('List<') else text


def used_types(batch):
    names = set()
    for port in batch['ports']:
        for method in port['methods']:
            for t in [method['returns']] + [p['type'] for p in method['params']]:
                names.add(t[5:-1] if t.startswith('List<') else t)
    return {n for n in names if n in {d['name'] for d in batch['dtos']}}


def dto_source(plan, dto):
    package = plan['templateParameters']['BASE_PACKAGE']
    lines = [f'package {package}.dto;', '', f'public class {dto["name"]} {{']
    for f in dto['fields']:
        lines.append(f'  private {f["type"]} {f["name"]};')
    for f in dto['fields']:
        lines += ['', f'  public {f["type"]} get{upper(f["name"])}() {{', f'    return {f["name"]};', '  }', '',
                  f'  public void set{upper(f["name"])}({f["type"]} {f["name"]}) {{', f'    this.{f["name"]} = {f["name"]};', '  }']
    return '\n'.join(lines + ['}', ''])


def _sig(method):
    params = ', '.join(f'{jtype(p["type"])} {p["name"]}' for p in method['params'])
    return f'{"void" if method["returns"] == "void" else jtype(method["returns"])} {method["name"]}({params})'


def _port_types(port, dto_names):
    names = set()
    for m in port['methods']:
        for t in [m['returns']] + [p['type'] for p in m['params']]:
            base = t[5:-1] if t.startswith('List<') else t
            if base in dto_names:
                names.add(base)
    return sorted(names)


def port_source(plan, batch, port):
    package = plan['templateParameters']['BASE_PACKAGE']
    dtos = {d['name'] for d in batch['dtos']}
    lines = [f'package {package}.port;', '']
    lines += [f'import {package}.dto.{n};' for n in _port_types(port, dtos)]
    lines += ['', f'public interface {port["id"]} {{']
    for m in port['methods']:
        lines.append(f'  {_sig(m)};')
    return '\n'.join(lines + ['}', ''])


def port_impl_source(plan, batch, port):
    import batch_adapters
    concrete = batch_adapters.adapter_source(plan, batch, port)
    if concrete is not None:
        return concrete
    package = plan['templateParameters']['BASE_PACKAGE']
    dtos = {d['name'] for d in batch['dtos']}
    annotation = '@Repository' if port['kind'] == 'db' else '@Component'
    stereotype = 'org.springframework.stereotype.' + annotation[1:]
    lines = [f'package {package}.port;', '', f'import {stereotype};', f'import {package}.exception.OperacionNoImplementadaException;']
    lines += [f'import {package}.dto.{n};' for n in _port_types(port, dtos)]
    lines += ['', annotation, f'public class {port["id"]}Impl implements {port["id"]} {{']
    for m in port['methods']:
        message = (f'Adaptador {port["kind"]} no implementado: {port["id"]}.{m["name"]}. '
                   'PENDIENTE: la especificacion (Sparx) no define el detalle tecnico de esta integracion.')
        lines += ['', '  @Override', f'  public {_sig(m)} {{', f'    throw new OperacionNoImplementadaException({literal(message)});', '  }']
    return '\n'.join(lines + ['}', ''])


def exception_source(plan):
    package = plan['templateParameters']['BASE_PACKAGE']
    return '\n'.join([f'package {package}.exception;', '',
                      'public class OperacionNoImplementadaException extends RuntimeException {',
                      '  private static final long serialVersionUID = 1L;', '',
                      '  public OperacionNoImplementadaException(String message) {', '    super(message);', '  }', '}', ''])


def _operand(text):
    head, _, field = text.partition('.')
    return head if not field else f'{head}.get{upper(field)}()'


def _group(step):
    """Simple comparisons of a step condition and how they combine: (list, 'single'|'all'|'any')."""
    if 'all' in step:
        return step['all'], 'all'
    if 'any' in step:
        return step['any'], 'any'
    return [{k: step[k] for k in ('left', 'op', 'right') if k in step}], 'single'


def _simple_java(cond):
    left, op = _operand(cond['left']), cond['op']
    if op == '<':
        return f'{left}.intValue() < {_operand(cond["right"])}.intValue()'
    if op == 'present':
        return f'{left} != null'
    if op == 'nonempty':
        return f'{left} != null && !{left}.isEmpty()'
    if op == 'true':
        return f'Boolean.TRUE.equals({left})'
    right = cond['right']
    if isinstance(right, str):
        return f'{literal(right)}.equals({left})'
    return f'{literal(str(right))}.equals(String.valueOf({left}))'


def _cond_java(step):
    group, mode = _group(step)
    if mode == 'single':
        return _simple_java(group[0])
    return (' && ' if mode == 'all' else ' || ').join(f'({_simple_java(c)})' for c in group)


def _calls(batch):
    """Flat index of port methods by (port, method)."""
    return {(p['id'], m['name']): m for p in batch['ports'] for m in p['methods']}


def service_source(plan, batch):
    values = plan['templateParameters']
    package, interface = values['BASE_PACKAGE'], values['SERVICE_INTERFACE']
    impl = interface + 'Impl'
    outcome = batch['outcomes']
    ok_code, ok_msg = (f'externalProperties.{outcome["success"]}{p}' for p in ('Codigo', 'Mensaje'))
    ko_code, ko_msg = (f'externalProperties.{outcome["generalFailure"]}{p}' for p in ('Codigo', 'Mensaje'))
    methods = _calls(batch)
    body, used_ports, used_dtos = [], set(), set()

    def emit(level, line):
        body.append('  ' * level + line)

    def walk(steps, env, level, in_loop):
        for step in steps:
            kind = step['kind']
            emit(level, '// Sparx step: ' + step['id'])
            if kind == 'call':
                port, name = step['port'], step['method']
                method = methods[(port, name)]
                used_ports.add(port)
                call = f'{lower(port)}.{name}({", ".join(_operand(a) for a in step["args"])})'
                label = literal(f'{port}.{name}')
                emit(level, f'logger.info(msjTrx + {label});')
                result = step.get('result')
                if result:
                    returns = method['returns']
                    base = returns[5:-1] if returns.startswith('List<') else returns
                    if base in {d['name'] for d in batch['dtos']}:
                        used_dtos.add(base)
                    env[result] = returns
                if step['onFailure'] == 'log':
                    if result:
                        emit(level, f'{jtype(method["returns"])} {result} = null;')
                    emit(level, 'try {')
                    emit(level + 1, (f'{result} = ' if result else '') + call + ';')
                    emit(level, '} catch (Exception e) {')
                    emit(level + 1, f'logger.error(msjTrx + {label} + " " + e.getMessage(), e);')
                    emit(level, '}')
                else:
                    emit(level, (f'{jtype(method["returns"])} {result} = ' if result else '') + call + ';')
            elif kind == 'for-each':
                item_type = env[step['list']][5:-1]
                used_dtos.add(item_type)
                emit(level, f'for ({item_type} {step["item"]} : {step["list"]}) {{')
                emit(level + 1, 'try {')
                walk(step['steps'], {**env, step['item']: item_type}, level + 2, True)
                emit(level + 1, '} catch (Exception e) {')
                emit(level + 2, f'logger.error(msjTrx + {literal("Se omite el elemento tras el fallo en el paso: " + step["id"])} + " " + e.getMessage(), e);')
                emit(level + 1, '}')
                emit(level, '}')
            elif kind == 'guard':
                emit(level, f'if (!({_cond_java(step)})) {{')
                emit(level + 1, f'logger.info(msjTrx + {literal("Se omite el elemento: guarda " + step["id"])});')
                emit(level + 1, 'continue;')
                emit(level, '}')
            else:
                emit(level, f'if ({_cond_java(step)}) {{')
                walk(step['then'], dict(env), level + 1, in_loop)
                if step.get('else'):
                    emit(level, '} else {')
                    walk(step['else'], dict(env), level + 1, in_loop)
                emit(level, '}')

    walk(batch['flow'], {}, 3, False)
    lines = [f'package {package}.service;', '', 'import java.text.MessageFormat;', 'import org.apache.log4j.Logger;',
             'import org.springframework.beans.factory.annotation.Autowired;', 'import org.springframework.stereotype.Service;',
             f'import {package}.util.Constantes;', f'import {package}.util.PropertiesExterno;']
    lines += [f'import {package}.dto.{n};' for n in sorted(used_dtos)]
    lines += [f'import {package}.port.{n};' for n in sorted(used_ports)]
    lines += ['', '@Service', f'public class {impl} implements {interface} {{',
              f'  private static final Logger logger = Logger.getLogger({impl}.class);', '  @Autowired',
              '  private PropertiesExterno externalProperties;']
    for port in sorted(used_ports):
        lines += ['  @Autowired', f'  private {port} {lower(port)};']
    lines += ['', '  @Override', '  public void run(String messageTransaction, String idTransaccion) {',
              '    String nomMetodoActual = Thread.currentThread().getStackTrace()[1].getMethodName();',
              '    String msjTrx = messageTransaction + "[" + nomMetodoActual + "] ";',
              '    long tiempoInicio = System.currentTimeMillis();',
              '    logger.info(MessageFormat.format(Constantes.INICIO_METODO, msjTrx, nomMetodoActual));',
              '    try {', *body, f'      logger.info(msjTrx + {ok_code} + " " + {ok_msg});',
              '    } catch (Exception e) {', f'      logger.error(msjTrx + {ko_code} + " " + {ko_msg}, e);', '    } finally {',
              '      logger.info(MessageFormat.format(Constantes.TIPO_TOTAL_PROCESO, msjTrx, System.currentTimeMillis() - tiempoInicio));',
              '      logger.info(MessageFormat.format(Constantes.FIN_METODO, msjTrx, nomMetodoActual));', '    }', '  }', '}', '']
    return '\n'.join(lines)


# ---------------------------------------------------------------- test derivation

def _opts(step):
    kind = step['kind']
    if kind == 'for-each':
        return [(a, False) for a, _ in _scen(step['steps'])]
    if kind == 'if':
        out = []
        for polarity, branch in ((True, step['then']), (False, step.get('else') or [])):
            out += [({step['id']: polarity, **a}, t) for a, t in _scen(branch)]
        return out
    if kind == 'guard':
        return [({step['id']: True}, False), ({step['id']: False}, True)]
    return [({}, False)]


def _scen(steps):
    """(polarity assignment {cond_id: bool}, terminated) for every reachable combination of conditions."""
    result = [({}, False)]
    for step in steps:
        options = _opts(step)
        following = []
        for acc, done in result:
            if done:
                following.append((acc, True))
                continue
            following += [({**acc, **a}, t) for a, t in options]
        result = following
    return result


def _paths(steps):
    return [a for a, _ in _scen(steps)]


def _walk_reached(steps, polarity, acc, trail):
    for step in steps:
        kind = step['kind']
        if kind == 'call':
            acc['calls'].append((step, trail))
        elif kind == 'for-each':
            _walk_reached(step['steps'], polarity, acc, trail + ('loop',))
        elif kind == 'guard':
            acc['conds'].append(step)
            if not polarity[step['id']]:
                return True
        else:
            acc['conds'].append(step)
            if _walk_reached(step['then'] if polarity[step['id']] else (step.get('else') or []), polarity, acc, trail):
                return True
    return False


def _reached(steps, polarity):
    """Call steps reached under `polarity`: [(step, enclosing for-each markers)]."""
    acc = {'calls': [], 'conds': []}
    _walk_reached(steps, polarity, acc, ())
    return acc['calls']


def _ifs(steps, polarity):
    """Condition steps (if/guard) reached under `polarity`."""
    acc = {'calls': [], 'conds': []}
    _walk_reached(steps, polarity, acc, ())
    return acc['conds']


def _other(right):
    if isinstance(right, int):
        return -1 if right != -1 else -2
    return 'otro' if right != 'otro' else 'otro2'


def _constraints(batch, polarity):
    found = {}

    def put(key, value):
        require(found.setdefault(key, value) == value, 'ambiguous scenario: contradictory conditions on one operand')

    def apply(cond, wanted):
        op = cond['op']
        if op == '<':
            left, right = (0, 1) if wanted else (1, 0)
            put(tuple(cond['left'].partition('.')[::2]), left)
            put(tuple(cond['right'].partition('.')[::2]), right)
        elif op == 'present':
            put((cond['left'], ''), 'present' if wanted else 'absent')
        elif op == 'nonempty':
            put((cond['left'], ''), 'nonempty' if wanted else 'empty')
        elif op == 'equals':
            put(tuple(cond['left'].partition('.')[::2]), cond['right'] if wanted else _other(cond['right']))
        else:
            put(tuple(cond['left'].partition('.')[::2]), bool(wanted))
    for step in _ifs(batch['flow'], polarity):
        group, mode = _group(step)
        wanted = polarity[step['id']]
        if mode == 'single':
            apply(group[0], wanted)
        elif mode == 'all':
            for n, cond in enumerate(group):
                apply(cond, True if wanted else n != 0)
        elif wanted:
            apply(group[0], True)
        else:
            for cond in group:
                apply(cond, False)
    return found


def _default(type_, dtos):
    if type_ == 'String':
        return '"test"'
    if type_ == 'Integer':
        return 'Integer.valueOf(0)'
    if type_ == 'Long':
        return 'Long.valueOf(0L)'
    if type_ == 'Boolean':
        return 'Boolean.TRUE'
    return f'new {type_}()'


def _matcher(type_):
    return f'org.mockito.ArgumentMatchers.<{jtype(type_)}>any()'


def _setter_value(dto_fields, type_, value):
    if type_ == 'Boolean':
        return 'Boolean.TRUE' if value else 'Boolean.FALSE'
    if type_ == 'String':
        return literal(str(value))
    if type_ == 'Integer':
        return f'Integer.valueOf({int(value)})'
    return f'Long.valueOf({int(value)}L)'


def test_source(plan, batch):
    v = plan['templateParameters']
    package, impl = v['BASE_PACKAGE'], v['SERVICE_INTERFACE'] + 'Impl'
    outcome = batch['outcomes']
    methods = _calls(batch)
    dto_fields = {d['name']: {f['name']: f['type'] for f in d['fields']} for d in batch['dtos']}
    calls = []

    def collect(steps, env):
        for s in steps:
            if s['kind'] == 'call':
                calls.append(s)
                if 'result' in s:
                    env[s['result']] = s
            elif s['kind'] == 'for-each':
                collect(s['steps'], env)
            elif s['kind'] == 'if':
                collect(s['then'], env)
                collect(s.get('else') or [], env)
    producers = {}
    collect(batch['flow'], producers)
    item_source = {}

    def items(steps):
        for s in steps:
            if s['kind'] == 'for-each':
                item_source[s['item']] = s['list']
                items(s['steps'])
            elif s['kind'] == 'if':
                items(s['then'])
                items(s.get('else') or [])
    items(batch['flow'])

    paths = _paths(batch['flow'])
    require(len(paths) <= MAX_PATHS, 'too many flow paths to derive tests')
    ports = sorted({s['port'] for s in calls})
    imports = sorted({m['returns'][5:-1] if m['returns'].startswith('List<') else m['returns'] for m in methods.values()
                      if (m['returns'][5:-1] if m['returns'].startswith('List<') else m['returns']) in dto_fields})
    lines = [f'package {package}.service;', '', 'import org.junit.After;', 'import org.junit.Assert;', 'import org.junit.Before;',
             'import org.junit.Test;', 'import org.junit.runner.RunWith;', 'import org.mockito.ArgumentCaptor;',
             'import org.mockito.InjectMocks;', 'import org.mockito.Mock;', 'import org.mockito.Spy;',
             'import org.mockito.junit.MockitoJUnitRunner;', 'import org.apache.log4j.Appender;', 'import org.apache.log4j.Logger;',
             'import org.apache.log4j.spi.LoggingEvent;',
             *['import static org.mockito.Mockito.' + n + ';' for n in ('atLeastOnce', 'doReturn', 'doThrow', 'times', 'verify')],
             f'import {package}.util.PropertiesExterno;']
    used_dtos = set(imports)
    for s in calls:
        for a in methods[(s['port'], s['method'])]['params']:
            base = a['type'][5:-1] if a['type'].startswith('List<') else a['type']
            if base in dto_fields:
                used_dtos.add(base)
    lines = lines[:-1] + [f'import {package}.dto.{n};' for n in sorted(used_dtos)] + \
        [f'import {package}.port.{n};' for n in ports] + [lines[-1]]
    lines += ['', '@RunWith(MockitoJUnitRunner.Silent.class)', f'public class {impl}Test {{',
              '  @Spy', '  private PropertiesExterno externalProperties = new PropertiesExterno();']
    for p in ports:
        lines += ['  @Mock', f'  private {p} {lower(p)};']
    lines += ['  @Spy', '  @InjectMocks', f'  private {impl} service = new {impl}();', '  @Mock', '  private Appender appender;', '',
              '  @Before', '  public void setUp() {']
    for group in ('idf0', 'idf1', 'idt1', 'idt2', 'idt3'):
        lines += [f'    externalProperties.{group}Codigo = "{group}_code";', f'    externalProperties.{group}Mensaje = "{group}_message";']
    lines += [f'    Logger.getLogger({impl}.class).addAppender(appender);', '  }', '', '  @After', '  public void tearDown() {',
              f'    Logger.getLogger({impl}.class).removeAppender(appender);', '  }', '',
              '  private void assertOutcome(String code) {',
              '    ArgumentCaptor<LoggingEvent> logs = ArgumentCaptor.forClass(LoggingEvent.class);',
              '    verify(appender, atLeastOnce()).doAppend(logs.capture());', '    boolean found = false;',
              '    for (LoggingEvent event : logs.getAllValues()) {',
              '      found = found || event.getRenderedMessage().contains(code);', '    }', '    Assert.assertTrue(code, found);', '  }', '']

    def args(step):
        return ', '.join(_matcher(p['type']) for p in methods[(step['port'], step['method'])]['params'])

    def stub(step):
        return f'{lower(step["port"])}).{step["method"]}({args(step)})'

    def prepare(index, polarity):
        constraints = _constraints(batch, polarity)
        out = [f'  private void preparar{index}() {{']
        for s in calls:
            if 'result' not in s:
                continue
            returns = methods[(s['port'], s['method'])]['returns']
            var = s['result']
            if returns.startswith('List<'):
                dto = returns[5:-1]
                item = next((i for i, l in item_source.items() if l == var), None)
                names = []
                if constraints.get((var, '')) == 'empty':
                    out.append(f'    doReturn(java.util.Collections.<{dto}>emptyList()).when({stub(s)};')
                    continue
                for n in (1, 2):
                    obj = f'{var}Item{n}'
                    names.append(obj)
                    out.append(f'    {dto} {obj} = new {dto}();')
                    for (head, field), value in sorted(constraints.items()):
                        if head == item and field:
                            out.append(f'    {obj}.set{upper(field)}({_setter_value(dto_fields, dto_fields[dto][field], value)});')
                value = f'java.util.Arrays.asList({", ".join(names)})'
            elif returns in dto_fields:
                state = constraints.get((var, ''))
                if state == 'absent':
                    value = None
                else:
                    value = f'{var}Value'
                    out.append(f'    {returns} {value} = new {returns}();')
                    for (head, field), val in sorted(constraints.items()):
                        if head == var and field:
                            out.append(f'    {value}.set{upper(field)}({_setter_value(dto_fields, dto_fields[returns][field], val)});')
            else:
                if (var, '') in constraints:
                    value = _setter_value(None, returns, constraints[(var, '')])
                else:
                    value = _default(returns, dto_fields)
            out.append(f'    doReturn({value if value is not None else "null"}).when({stub(s)};')
        return out + ['  }', '']

    def label(polarity):
        return '_'.join(f'{k}{"Si" if v else "No"}' for k, v in polarity.items()) or 'unico'

    trace = []
    for index, polarity in enumerate(paths, 1):
        lines += prepare(index, polarity)
        reached = _reached(batch['flow'], polarity)
        name = f'run_ruta_{label(polarity)}_debeRegistrarExito'
        trace.append(name)
        lines += ['  @Test', f'  public void {name}() {{', f'    preparar{index}();', '    service.run("[idTx=test]", "test");']
        for s, _ in reached:
            lines.append(f'    verify({stub(s).replace(").", ", atLeastOnce()).", 1)};')
        lines += [f'    assertOutcome(externalProperties.{outcome["success"]}Codigo);', '  }', '']
    handled = set()
    for index, polarity in enumerate(paths, 1):
        for s, trail in _reached(batch['flow'], polarity):
            if s['id'] in handled:
                continue
            handled.add(s['id'])
            name = f'run_falla_{s["id"]}_{ {"abort": "debeRegistrarFalloGeneral", "log": "noDebeInterrumpir", "skip-item": "debeContinuarConSiguiente"}[s["onFailure"]] }'
            lines += ['  @Test', f'  public void {name}() {{', f'    preparar{index}();',
                      f'    doThrow(new RuntimeException("test")).when({stub(s)};', '    service.run("[idTx=test]", "test");']
            if s['onFailure'] == 'skip-item':
                lines.append(f'    verify({stub(s).replace(").", f", times({2 ** len(trail)})).", 1)};')
                lines.append(f'    assertOutcome(externalProperties.{outcome["success"]}Codigo);')
            elif s['onFailure'] == 'log':
                lines.append(f'    assertOutcome(externalProperties.{outcome["success"]}Codigo);')
            else:
                lines.append(f'    assertOutcome(externalProperties.{outcome["generalFailure"]}Codigo);')
            lines += ['  }', '']
    return '\n'.join(lines + ['}', ''])
