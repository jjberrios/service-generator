"""Java generator of the remote-orchestration pattern: everything that depends on the plan (contract, validations, flows, clients, constants).

Pure text generation: nothing here reads the file system. `build_main(plan)` returns {relative path: Java source}.
"""
import re
import unicodedata

import remote_orchestration_runtime as rt

PKG_TOKEN = '__P__'
EXTERNAL = {
    'Data': 'lombok.Data', 'RequiredArgsConstructor': 'lombok.RequiredArgsConstructor', 'Slf4j': 'lombok.extern.slf4j.Slf4j', 'Logger': 'org.slf4j.Logger',
    'JsonNode': 'com.fasterxml.jackson.databind.JsonNode', 'ObjectNode': 'com.fasterxml.jackson.databind.node.ObjectNode', 'ArrayNode': 'com.fasterxml.jackson.databind.node.ArrayNode',
    'NullNode': 'com.fasterxml.jackson.databind.node.NullNode', 'MissingNode': 'com.fasterxml.jackson.databind.node.MissingNode', 'ObjectMapper': 'com.fasterxml.jackson.databind.ObjectMapper',
    'JsonInclude': 'com.fasterxml.jackson.annotation.JsonInclude',
    'List': 'java.util.List', 'Map': 'java.util.Map', 'Set': 'java.util.Set', 'HashMap': 'java.util.HashMap', 'HashSet': 'java.util.HashSet', 'ArrayList': 'java.util.ArrayList',
    'LinkedHashMap': 'java.util.LinkedHashMap', 'Collection': 'java.util.Collection', 'Comparator': 'java.util.Comparator', 'Optional': 'java.util.Optional',
    'BigDecimal': 'java.math.BigDecimal', 'RoundingMode': 'java.math.RoundingMode', 'LocalDate': 'java.time.LocalDate', 'LocalDateTime': 'java.time.LocalDateTime',
    'OffsetDateTime': 'java.time.OffsetDateTime', 'Instant': 'java.time.Instant', 'Clock': 'java.time.Clock', 'Duration': 'java.time.Duration', 'ZoneId': 'java.time.ZoneId',
    'DateTimeFormatter': 'java.time.format.DateTimeFormatter', 'DateTimeParseException': 'java.time.format.DateTimeParseException',
    'Supplier': 'java.util.function.Supplier', 'Consumer': 'java.util.function.Consumer', 'Function': 'java.util.function.Function',
    'IOException': 'java.io.IOException', 'InputStream': 'java.io.InputStream', 'SocketTimeoutException': 'java.net.SocketTimeoutException',
    'HttpStatus': 'org.springframework.http.HttpStatus', 'HttpMethod': 'org.springframework.http.HttpMethod', 'HttpHeaders': 'org.springframework.http.HttpHeaders',
    'MediaType': 'org.springframework.http.MediaType', 'ResponseEntity': 'org.springframework.http.ResponseEntity', 'HttpStatusCode': 'org.springframework.http.HttpStatusCode',
    'RestClient': 'org.springframework.web.client.RestClient', 'RestClientException': 'org.springframework.web.client.RestClientException',
    'ResourceAccessException': 'org.springframework.web.client.ResourceAccessException',
    'SimpleClientHttpRequestFactory': 'org.springframework.http.client.SimpleClientHttpRequestFactory',
    'Component': 'org.springframework.stereotype.Component', 'Service': 'org.springframework.stereotype.Service', 'Value': 'org.springframework.beans.factory.annotation.Value',
    'Configuration': 'org.springframework.context.annotation.Configuration', 'Bean': 'org.springframework.context.annotation.Bean',
    'PostMapping': 'org.springframework.web.bind.annotation.PostMapping', 'RequestHeader': 'org.springframework.web.bind.annotation.RequestHeader',
    'RequestBody': 'org.springframework.web.bind.annotation.RequestBody', 'RestController': 'org.springframework.web.bind.annotation.RestController',
    'RestControllerAdvice': 'org.springframework.web.bind.annotation.RestControllerAdvice', 'ExceptionHandler': 'org.springframework.web.bind.annotation.ExceptionHandler',
    'Operation': 'io.swagger.v3.oas.annotations.Operation', 'Content': 'io.swagger.v3.oas.annotations.media.Content', 'Schema': 'io.swagger.v3.oas.annotations.media.Schema',
    'ApiResponse': 'io.swagger.v3.oas.annotations.responses.ApiResponse', 'ApiResponses': 'io.swagger.v3.oas.annotations.responses.ApiResponses',
    'ConstraintViolationException': 'jakarta.validation.ConstraintViolationException',
    'HttpMessageNotReadableException': 'org.springframework.http.converter.HttpMessageNotReadableException',
    'MissingRequestHeaderException': 'org.springframework.web.bind.MissingRequestHeaderException', 'WebRequest': 'org.springframework.web.context.request.WebRequest',
    'ResponseEntityExceptionHandler': 'org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler', 'Nullable': 'org.springframework.lang.Nullable',
    'MethodArgumentTypeMismatchException': 'org.springframework.web.method.annotation.MethodArgumentTypeMismatchException',
}
INTERNAL = {}
STATIC_CALLS = {}


def register(suffix, *names):
    for name in names:
        INTERNAL[name] = suffix


def strip(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return re.sub(r'//[^\n]*', '', text)


def ascii_escape(text):
    return ''.join(c if ord(c) < 128 else '\\u%04x' % ord(c) for c in text)


def finalize(pkg, suffix, body, statics=(), extra=None, hoist=False):
    own = pkg + ('.' + suffix if suffix else '')
    code = strip(body)
    words = set(re.findall(r'\b[A-Z][A-Za-z0-9_]*\b', code))
    imports = set()
    external = {**EXTERNAL, **(extra or {})}
    for word in words:
        if word in INTERNAL:
            package = pkg + '.' + INTERNAL[word]
            if package != own:
                imports.add(f'{package}.{word}')
        elif word in external:
            imports.add(external[word])
    lines = [f'package {own};', '']
    statics = [s for s in statics if re.search(r'\b' + s.rsplit('.', 1)[1] + r'\b', code)]
    if statics:
        lines += [f'import static {s};' for s in sorted(statics)] + ['']
    if imports:
        lines += [f'import {i};' for i in sorted(imports)] + ['']
    text = '\n'.join(lines) + '\n' + body.strip('\n') + '\n'
    text = text.replace('\r\n', '\n').replace(PKG_TOKEN, pkg)
    return wrap_long(ascii_escape(hoist_numbers(text) if hoist else text))


BREAKS = re.compile(r'(?<=\))(\.(?:put|list|on|ok|otherwise|compensate|emptyList|contentType|body)\()')


def wrap_long(text, limit=150):
    """Breaks very long fluent chains before each call so that no line exceeds the style limit (indentation = statement indent + 16)."""
    out = []
    for line in text.split('\n'):
        if len(line) <= limit or line.lstrip().startswith(('*', '/')):
            out.append(line)
            continue
        pad = ' ' * (len(line) - len(line.lstrip()) + 16)
        parts = BREAKS.split(line)
        pieces, current = [], parts[0]
        for i in range(1, len(parts), 2):
            piece = parts[i] + parts[i + 1]
            if len(current) + len(piece) > limit:
                pieces.append(current)
                current = pad + piece
            else:
                current += piece
        pieces.append(current)
        for piece in pieces:
            out.extend(split_commas(piece))
    return '\n'.join(out)


def split_commas(line, limit=230):
    if len(line) <= limit:
        return [line]
    pad = ' ' * (len(line) - len(line.lstrip()) + 8)
    segments, last = [], 0
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|, ', line):
        if match.group(0) == ', ':
            segments.append(line[last:match.end() - 1])
            last = match.end()
    segments.append(line[last:])
    result, current = [], segments[0]
    for segment in segments[1:]:
        if len(current) + len(segment) + 1 > limit:
            result.append(current)
            current = pad + segment
        else:
            current += ' ' + segment
    result.append(current)
    return result


IGNORED_NUMBERS = {'-1', '0', '1', '2', '4', '200', '201', '400', '401', '403', '404', '418', '500', '1000'}
STRING = re.compile(r'"(?:\\.|[^"\\])*"')
NUMBER = re.compile(r'(?<![\w.$])(\d+)([lL]?)(?![\w.])')


def hoist_numbers(text):
    """Test sources: every numeric literal outside the approved ignore list becomes a named constant (MagicNumber is enforced on tests too)."""
    lines, found = text.split('\n'), {}
    for index, line in enumerate(lines):
        if 'static final' in line or line.lstrip().startswith(('*', '/', 'import', 'package')):
            continue
        pieces, last = [], 0
        for match in STRING.finditer(line):
            pieces.append((line[last:match.start()], False))
            pieces.append((match.group(0), True))
            last = match.end()
        pieces.append((line[last:], False))
        rebuilt = []
        for chunk, is_string in pieces:
            if not is_string:
                def swap(m):
                    if m.group(1) in IGNORED_NUMBERS and not m.group(2):
                        return m.group(0)
                    name = 'VALUE_' + m.group(1) + ('_L' if m.group(2) else '')
                    found[name] = ('long' if m.group(2) else 'int', m.group(1) + m.group(2))
                    return name
                chunk = NUMBER.sub(swap, chunk)
            rebuilt.append(chunk)
        lines[index] = ''.join(rebuilt)
    if not found:
        return text
    for index, line in enumerate(lines):
        if re.match(r'^(public )?(final )?class \w+ \{$', line):
            decl = [f'    private static final {kind} {name} = {value};' for name, (kind, value) in sorted(found.items())]
            return '\n'.join(lines[:index + 1] + decl + [''] + lines[index + 1:])
    return text


def jstr(text):
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"') + '"'


def cap(name):
    return name[0].upper() + name[1:]


def fold(text):
    text = unicodedata.normalize('NFKD', str(text or ''))
    return ''.join(c for c in text if not unicodedata.combining(c))


def slug(text, limit=48):
    text = re.sub(r'^[\d.\s]+', '', fold(text).replace('&quot;', ''))
    text = re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_').upper()
    return text[:limit].rstrip('_')


def const_name(key, activity_name):
    return 'ACT_' + key.replace('.', '_').upper() + '_' + slug(activity_name)


def prop_const(name):
    return 'PROP_' + re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', re.sub(r'^prop', '', name)).upper()


JAVA_TYPES = {'integer': 'Long', 'number': 'BigDecimal', 'string': 'String', 'boolean': 'Boolean'}
CONTROLLER_PACKAGES = {'AgreementApi': 'controller', 'AgreementController': 'controller.impl'}
register('dto.request', 'AgreementRequest', 'RequestHeaders')
register('dto.response', 'AgreementResponse', 'AgreementResponseData', 'AgreementInstallmentDto', 'ErrorResponse')
register('exception', 'ServiceOperationException', 'ErrorCatalog', 'GlobalExceptionHandler')
register('service', 'AgreementService')
register('service.impl', 'AgreementServiceImpl')
register('validation', 'AgreementRequestValidator')
register('controller', 'AgreementApi')
register('controller.impl', 'AgreementController')
register('orchestration', 'Json', 'Body', 'Rules', 'Calculations', 'StepOutcome', 'FlowContext', 'AgreementFlow', 'SystemSettings', 'InstallmentSynchronization')
register('client', 'RemoteGateway', 'RemoteResponse', 'ForwardedHeaders')
register('configuration', 'ClientConfig', 'ClockConfig', 'FinancingProperties')
register('utils', 'ActivityLogger', 'ConstanApi')


# ----------------------------------------------------------------------------- expressions
class Expr:
    def __init__(self, plan):
        self.props = plan['orchestration']['properties']

    def __call__(self, e, element='element'):
        if isinstance(e, list):
            op, args = e[0], e[1:]
            if op == 'size':
                return f'Rules.size({self(args[0], element)})'
            if op in ('add', 'eq', 'gt', 'ge', 'le'):
                return f'Rules.{op}({self(args[0], element)}, {self(args[1], element)})'
            if op == 'empty':
                return f'Rules.empty({self(args[0], element)})'
            if op == 'round2':
                return f'Rules.round2({self(args[0], element)})'
            if op == 'hours-exceed':
                return f'ctx.hoursExceed({self(args[0], element)}, {self(args[1], element)})'
            if op == 'and':
                return '(' + ' && '.join(self(a, element) for a in args) + ')'
            if op == 'or':
                return '(' + ' || '.join(self(a, element) for a in args) + ')'
            if op == 'not':
                return f'!{self(args[0], element)}'
            raise ValueError(f'unknown expression operator {op}')
        if e == 'null':
            return 'null'
        if e == 'today':
            return 'ctx.today()'
        if e == 'now':
            return 'ctx.timestamp()'
        kind, _, rest = e.partition(':')
        if kind == 'int':
            return rest
        if kind == 'lit':
            return jstr(rest)
        if kind == 'req':
            return f'request.get{cap(rest)}()'
        if kind in ('act', 'val', 'lst'):
            key, _, name = rest.rpartition(':')
            if kind == 'act':
                return f'ctx.field({jstr(key)}, {jstr(name)})'
            if kind == 'val':
                return f'ctx.value({jstr(key)}, {jstr(name)})'
            return f'ctx.list({jstr(key)}, {jstr(name)})'
        if kind == 'ins':
            return f'ctx.installments({jstr(rest)})'
        if kind == 'prop':
            if rest not in self.props:
                raise ValueError(f'unknown property {rest}')
            return f'FinancingProperties.{prop_const(rest)}'
        if kind == 'cfg':
            return f'ctx.setting({jstr(rest)})'
        if kind == 'hdr':
            return f'ctx.header({jstr(rest)})'
        if kind == 'el':
            return f'Json.at({element}, {jstr(rest)})'
        raise ValueError(f'unknown expression {e}')

    def list_source(self, e):
        kind, _, rest = e.partition(':')
        key, _, name = rest.rpartition(':')
        if kind == 'val':
            return f'ctx.valueList({jstr(key)}, {jstr(name)})'
        return self(e)


# ----------------------------------------------------------------------------- flows
class FlowWriter:
    def __init__(self, plan):
        self.plan = plan
        self.orch = plan['orchestration']
        self.expr = Expr(plan)
        self.constants = {}
        self.client_fields = {}
        for service, info in self.orch['clients'].items():
            self.client_fields[service] = info['className'][0].lower() + info['className'][1:]

    def activity(self, key, name):
        const = const_name(key, name)
        self.constants[const] = slug(name, 90) or key
        return f'ConstanApi.{const}'

    # --- remote calls
    def call(self, step, indent):
        client = self.client_fields[step['client']]
        pad = ' ' * indent
        headers = 'ctx.forwarded()::applyTo' if step['headers']['forward'] else None
        if headers is None:
            fields = ''.join(f'.put({jstr(k)}, {self.expr(v)})' for k, v in step['headers']['map'].items())
            headers = f'ctx.headers(Body.of(){fields}.toStrings())'
        path = self.map_expr(step['pathParams'])
        query = self.map_expr(step['query'])
        body = self.body_expr(step)
        return f'{client}.{step["operation"]}({headers}, {path}, {query}, {body})'

    def map_expr(self, mapping):
        if not mapping:
            return 'Map.of()'
        return 'Body.of()' + ''.join(f'.put({jstr(k)}, {self.expr(v)})' for k, v in mapping.items()) + '.toMap()'

    def body_expr(self, step):
        if not step['body'] and not step['bodyList']:
            return 'null'
        text = 'Body.of()' + ''.join(f'.put({jstr(k)}, {self.expr(v)})' for k, v in step['body'].items())
        listed = step['bodyList']
        if listed:
            source = self.expr.list_source(listed['source'])
            flt = step.get('bodyListFilter')
            if flt:
                source = f'Calculations.without({source}, {jstr(flt["field"])}, {flt["ne"]})'
            element = 'Body.of()' + ''.join(f'.put({jstr(k)}, {self.expr(v)})' for k, v in listed['element'].items())
            text += f'.list({jstr(listed["root"])}, {source}, element -> {element})'
        return text + '.build()'

    def outcome(self, step, flow):
        out = step['outcome']
        text = f'StepOutcome.of({jstr(step["client"])})'
        if out['ok']:
            text += '.ok(' + ', '.join(str(s) for s in out['ok']) + ')'
        for status, code in out['byStatus'].items():
            text += f'.on({status}, {jstr(code)})'
        if out['otherwise']:
            text += f'.otherwise({jstr(out["otherwise"])})'
        if out.get('emptyIs'):
            text += f'.emptyList({jstr(out["emptyIs"])})'
        if out['compensation'] != out['technicalCompensation']:
            raise ValueError(f'step {step["key"]}: different business and technical compensation is not supported')
        if out['compensation']:
            text += f'.compensate(() -> {self.chain_method(flow, out["compensation"])}(ctx))'
        return text

    def chain_method(self, flow, keys):
        for name, chain in flow['chains'].items():
            if chain == keys:
                self.used_chains.add(name)
                return 'compensate' + ''.join(cap(w) for w in re.sub(r'[^a-z0-9 ]', '', fold(name)).split())
        raise ValueError(f'no compensation chain named for {keys}')

    # --- statements
    def statements(self, items, flow, indent, response_type='AgreementResponseData'):
        lines = []
        pad = ' ' * indent
        for step in items:
            kind = step['t']
            if kind == 'remote':
                act = self.activity(step['key'], step['activity']['name'])
                lines.append(f'{pad}ctx.step({jstr(step["key"])}, {act},')
                lines.append(f'{pad}        () -> {self.call(step, indent + 8)},')
                lines.append(f'{pad}        {self.outcome(step, flow)});')
                if step['outcome']['logOnly']:
                    raise ValueError('logOnly step must be a best-effort call')
            elif kind == 'notify':
                pass
            elif kind == 'compute':
                lines += self.compute(step, flow, indent)
            elif kind == 'decide':
                lines.append(f'{pad}if ({self.negate(step["when"])}) {{')
                lines.append(f'{pad}    throw ctx.fail({jstr(step["fail"])});')
                lines.append(f'{pad}}}')
            elif kind == 'branch':
                lines.append(f'{pad}if ({self.cond(step["when"], strip=True)}) {{')
                lines += self.statements(step['then'], flow, indent + 4)
                if step['else']:
                    lines.append(f'{pad}}} else {{')
                    lines += self.statements(step['else'], flow, indent + 4)
                lines.append(f'{pad}}}')
            elif kind == 'respond':
                lines += self.respond(step, indent)
            else:
                raise ValueError(f'unknown step kind {kind}')
        return lines

    def negate(self, when):
        text = self.expr(when)
        if text.startswith('!') and not text.startswith('!('):
            return text[1:]
        if text.startswith('!('):
            return text[2:-1]
        return '!' + text

    def cond(self, when, strip=False):
        text = self.expr(when)
        if strip and text.startswith('(') and text.endswith(')') and when[0] in ('and', 'or'):
            return text[1:-1]
        return text

    def compute(self, step, flow, indent):
        pad = ' ' * indent
        act = self.activity(step['key'], step['activity']['name'])
        code = jstr(step['fail']) if step.get('fail') else 'null'
        compensation = f'() -> {self.chain_method(flow, step["compensation"])}(ctx)' if step.get('compensation') else 'FlowContext.NO_COMPENSATION'
        calls = []
        key = jstr(step['key'])
        for op in step['ops']:
            args = [self.expr.list_source(a) if a.startswith('lst:') else self.expr(a) for a in op['args']]
            fn, out = op['fn'], op['out']
            if fn == 'subtract':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.subtract({args[0]}, {args[1]}));')
            elif fn == 'add':
                calls.append(f'ctx.put({key}, {jstr(out)}, Rules.add({args[0]}, {args[1]}));')
            elif fn == 'divide-money':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.divideMoney({args[0]}, {args[1]}));')
            elif fn == 'percentage':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.percentage({args[0]}, {args[1]}));')
            elif fn == 'minimum-percentage':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.minimumPercentage({", ".join(args)}));')
            elif fn == 'classify-installments':
                calls.append(f'ctx.put({key}, {jstr(out[0])}, Calculations.byState({args[0]}, {args[1]}));')
                calls.append(f'ctx.put({key}, {jstr(out[1])}, Calculations.byState({args[0]}, {args[2]}));')
            elif fn == 'sum-quotes':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.sumQuotes({args[0]}));')
            elif fn == 'has-ineligible-installments':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.hasIneligible({", ".join(args)}));')
            elif fn == 'cancellation-transform':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.cancellationTransform({", ".join(args)}));')
            elif fn == 'filter-for-service-cancellation':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.filterForServiceCancellation({", ".join(args)}));')
            elif fn == 'filter-paid-for-sync':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.filterPaidForSync({", ".join(args)}));')
            elif fn == 'billing-cycle-dates':
                calls.append(f'ctx.put({key}, {jstr(out)}, Calculations.billingCycleDates({", ".join(args)}));')
            else:
                raise ValueError(f'unknown calculation {fn}')
        lines = [f'{pad}ctx.compute({act}, {code}, {compensation},']
        if len(calls) == 1:
            lines.append(f'{pad}        () -> {calls[0][:-1]});')
        else:
            lines.append(f'{pad}        () -> {{')
            lines += [f'{pad}            {c}' for c in calls]
            lines.append(f'{pad}        }});')
        return lines

    def respond(self, step, indent):
        pad = ' ' * indent
        fields = {f['name']: f['type'] for f in self.orch['contract_response_fields']}
        lines = [f'{pad}AgreementResponseData data = new AgreementResponseData();']
        for name, e in step['data'].items():
            jtype = fields[name]
            value = self.expr(e)
            if jtype == 'Long':
                value = f'Json.toLong({value})'
            elif jtype == 'BigDecimal':
                value = f'Json.toDecimal({value})'
            lines.append(f'{pad}data.set{cap(name)}({value});')
        lines.append(f'{pad}return data;')
        return lines

    # --- compensation chains
    def chain_body(self, flow, name):
        pad = '        '
        lines = []
        for key in flow['chains'][name]:
            step = flow['compensations'][key]
            act = self.activity(key if key[0] != 'R' else key, step['activity']['name'])
            lines.append(f'{pad}ctx.bestEffort({act},')
            lines.append(f'{pad}        () -> {self.call(step, 16)});')
        return lines

    def notifications(self, step, indent):
        pad = ' ' * indent
        act = self.activity(step['key'], step['activity']['name'])
        return [f'{pad}ctx.bestEffort({act},', f'{pad}        () -> {self.call(step, indent + 8)});']

    def flow_class(self, class_name, flow, type_id, sync):
        self.used_chains = set()
        steps = flow['steps']
        # notifications (logOnly) are best-effort calls
        body = self.statements_with_notify(steps, flow, 8)
        clients = set()

        def collect(items):
            for step in items:
                if step['t'] == 'remote':
                    clients.add(step['client'])
                if step['t'] == 'branch':
                    collect(step['then'])
                    collect(step['else'])
        collect(steps)
        compensation_methods = []
        for name in sorted(self.used_chains):
            for key in flow['chains'][name]:
                clients.add(flow['compensations'][key]['client'])
        fields = [f'    private final {self.orch["clients"][c]["className"]} {self.client_fields[c]};' for c in sorted(clients)]
        out = ['@Component', '@RequiredArgsConstructor', f'public class {class_name} implements AgreementFlow {{', f'    private static final int REQUEST_TYPE = {type_id};', ''] if not sync else ['@Component', '@RequiredArgsConstructor', f'public class {class_name} {{']
        out += fields + ['']
        if not sync:
            out += ['    @Override', '    public int requestTypeId() {', '        return REQUEST_TYPE;', '    }', '', '    @Override', '    public boolean synchronizesInstallments() {',
                    f'        return {"true" if flow.get("prerequisite") else "false"};', '    }', '', '    @Override', '    public AgreementResponseData execute(FlowContext ctx) {']
        else:
            out += ['    /** Synchronizes the installments of the financing with collections before the request flow. */', '    public void run(FlowContext ctx) {']
        out += ['        final AgreementRequest request = ctx.request();'] + body + ['    }']
        for name in sorted(self.used_chains):
            method = 'compensate' + ''.join(cap(w) for w in re.sub(r'[^a-z0-9 ]', '', fold(name)).split())
            out += ['', f'    private void {method}(FlowContext ctx) {{', '        final AgreementRequest request = ctx.request();'] + self.chain_body(flow, name) + ['    }']
        out.append('}')
        return '\n'.join(out)

    def statements_with_notify(self, items, flow, indent):
        lines = []
        for step in items:
            if step['t'] == 'remote' and step['outcome']['logOnly']:
                lines += self.notifications(step, indent)
            elif step['t'] == 'branch':
                pad = ' ' * indent
                lines.append(f'{pad}if ({self.cond(step["when"], strip=True)}) {{')
                lines += self.statements_with_notify(step['then'], flow, indent + 4)
                if step['else']:
                    lines.append(f'{pad}}} else {{')
                    lines += self.statements_with_notify(step['else'], flow, indent + 4)
                lines.append(f'{pad}}}')
            else:
                lines += self.statements([step], flow, indent)
        return lines


FLOW_CLASSES = {'1': 'PreFinancingFlow', '2': 'FinancingFlow', '3': 'PreRefinancingFlow', '4': 'RefinancingFlow', '5': 'InstallmentCancellationFlow',
                '6': 'InstallmentTransferFlow', '7': 'ServiceCancellationFlow', '8': 'BillingCycleChangeFlow'}
for _name in FLOW_CLASSES.values():
    register('orchestration', _name)
register('client', 'AgreementRequestClient', 'FinancingAgreementClient', 'FinancingInstallmentClient', 'ParametersClient', 'RangeQuoteClient', 'CollectionIntegrationClient',
         'InstallmentSynchronizationClient')


def error_catalog(plan):
    errors = plan['contract']['errors']
    names = {400: 'BAD_REQUEST', 404: 'NOT_FOUND', 409: 'CONFLICT', 422: 'UNPROCESSABLE_ENTITY', 500: 'INTERNAL_SERVER_ERROR', 503: 'SERVICE_UNAVAILABLE', 504: 'GATEWAY_TIMEOUT'}
    rows = []
    for code in sorted(errors):
        entry = errors[code]
        detail = jstr(entry['detail'])
        rows.append(f'            Map.entry({jstr(code)}, new Entry(HttpStatus.{names[entry["status"]]}, {jstr(entry["type"])},\n                    {detail}))')
    return f'''/** Error catalog declared by the contract: subType, status, type and detail template. */
public final class ErrorCatalog {{
    public static final String TIMEOUT = "IDT1";
    public static final String UNAVAILABLE = "IDT2";
    public static final String INTERNAL = "IDT3";
    public static final String MESSAGE = {jstr(next(iter(errors.values()))['message'])};
    private static final Map<String, Entry> ENTRIES = Map.ofEntries(
{(',' + chr(10)).join(rows)});

    private ErrorCatalog() {{
    }}

    /** Catalog entry of one error code. */
    public record Entry(HttpStatus status, String type, String detail) {{
    }}

    public static Entry entry(String code) {{
        return ENTRIES.get(code);
    }}

    /** Builds the failure of a code, replacing the placeholders of the contract detail. */
    public static ServiceOperationException build(String code, String service, String detail, String field) {{
        Entry entry = ENTRIES.get(code);
        String text = entry.detail()
                .replace("[FIELD_NAME]", field == null ? "" : field)
                .replace("[OUTPUT_DETAIL]", detail == null ? "" : detail)
                .replace("[OUTPU_DETAIL]", detail == null ? "" : detail)
                .replace("[ERROR_DETAIL]", detail == null ? "" : detail)
                .replace("[SERVICE_NAME]", service == null ? "" : service);
        return new ServiceOperationException(entry.status(), code, entry.type(), text);
    }}
}}'''


def dto(cls, fields, doc=None, non_null=False):
    out = []
    if doc:
        out.append(f'/** {doc} */')
    if non_null:
        out.append('@JsonInclude(JsonInclude.Include.NON_NULL)')
    out += ['@Data', f'public class {cls} {{']
    for jtype, name in fields:
        out.append(f'    private {jtype} {name};')
    out.append('}')
    return '\n'.join(out)


def validator(plan):
    orch = plan['orchestration']
    fields = {f['name']: f for f in plan['contract']['request']['fields']}
    ex = Expr(plan)

    def val(name):
        return f'request.get{cap(name)}()'
    out = ['/** Declared rules of the request: mandatory fields and value rules per requestTypeId (Sparx activity 1), evaluated in the order of the evidence. */', '@Component',
           '@RequiredArgsConstructor', 'public class AgreementRequestValidator {', '    private static final int FIRST_TYPE = 1;', '    private static final int LAST_TYPE = 8;', '    private static final int DELIVERED = 1;', '',
           '    private final Clock clock;', '    private final List<Consumer<AgreementRequest>> rules = List.of(__RULES__);', '', '    /** Validates the request; the first violated rule is reported with its contract code. */', '    public void validate(AgreementRequest request) {',
           '        if (request == null || request.getRequestTypeId() == null) {', '            throw ErrorCatalog.build("IDF101", null, null, "requestTypeId");', '        }',
           '        long type = request.getRequestTypeId();', '        if (type < FIRST_TYPE || type > LAST_TYPE) {', '            throw ErrorCatalog.build("IDF102", null, null, null);', '        }',
           '        rules.get((int) type - FIRST_TYPE).accept(request);', '    }', '']
    out = [line.replace('__RULES__', ', '.join(f'this::type{n}' for n in sorted(int(k) for k in orch['validations']))) for line in out]
    for type_id in sorted(int(k) for k in orch['validations']):
        spec = orch['validations'][str(type_id)]
        out.append(f'    private void type{type_id}(AgreementRequest request) {{')
        for item in spec['required']:
            check = f'require({jstr(item["field"])}, {val(item["field"])});'
            if item['when'] == 'delivered':
                out += [f'        if (isDelivered(request)) {{', f'            {check}', '        }']
            elif item['when'] == 'notDelivered':
                out += ['        if (!isDelivered(request)) {', f'            {check}', '        }']
            else:
                out.append(f'        {check}')
        for rule in spec['rules']:
            for line in rule_lines(rule, val):
                out.append('        ' + line)
        out.append('    }')
        out.append('')
    out += ['    private boolean isDelivered(AgreementRequest request) {', '        return request.getIsDelivered() != null && request.getIsDelivered() == DELIVERED;', '    }', '',
            '    private void require(String field, Object value) {', '        if (Json.isEmpty(value)) {', '            throw ErrorCatalog.build("IDF101", null, null, field);', '        }', '    }', '',
            '    private void reject(String code) {', '        throw ErrorCatalog.build(code, null, null, null);', '    }', '',
            '    private LocalDate date(String text, String code) {', '        try {', '            return LocalDate.parse(text);', '        } catch (DateTimeParseException | NullPointerException failure) {',
            '            throw ErrorCatalog.build(code, null, null, null);', '        }', '    }', '}']
    return '\n'.join(out)


def rule_lines(rule, val):
    code, kind, field = rule['code'], rule['kind'], rule['field']
    v = val(field)
    cond = {'positive': f'!Rules.gt({v}, 0)', 'min': f'!Rules.ge({v}, {rule.get("min")})'}.get(kind)
    lines = []
    if kind in ('positive', 'min'):
        if rule.get('unlessChannel'):
            lines += [f'if (!{jstr(rule["unlessChannel"])}.equals(request.getSaleChannel()) && {cond}) {{', f'    reject({jstr(code)});', '}']
        elif rule.get('onlyChannel'):
            lines += [f'if ({jstr(rule["onlyChannel"])}.equals(request.getSaleChannel()) && {cond}) {{', f'    reject({jstr(code)});', '}']
        else:
            lines += [f'if ({cond}) {{', f'    reject({jstr(code)});', '}']
    elif kind == 'enum':
        values = ', '.join(jstr(x) for x in rule['values'])
        lines += [f'if (!Set.of({values}).contains(String.valueOf({v}))) {{', f'    reject({jstr(code)});', '}']
    elif kind == 'range':
        lines += [f'if ({v} == null || {v} < {rule["min"]} || {v} > {rule["max"]}) {{', f'    reject({jstr(code)});', '}']
    elif kind == 'date-format':
        wrap = ('if (!isDelivered(request)) {', '}') if rule.get('when') == 'notDelivered' else None
        stmt = f'date({v}, {jstr(code)});'
        lines += [wrap[0], f'    {stmt}', wrap[1]] if wrap else [stmt]
    elif kind == 'date-gt-today':
        lines += [f'if (!date({v}, "IDF113").isAfter(LocalDate.now(clock))) {{', f'    reject({jstr(code)});', '}']
    elif kind == 'date-gte-today':
        lines += [f'if (date({v}, "IDF113").isBefore(LocalDate.now(clock))) {{', f'    reject({jstr(code)});', '}']
    elif kind == 'date-max-month':
        lines += [f'if (date({v}, "IDF113").isAfter(LocalDate.now(clock).plusMonths(1))) {{', f'    reject({jstr(code)});', '}']
    else:
        raise ValueError(f'unknown rule kind {kind}')
    return lines


def api(plan):
    contract = plan['contract']
    reasons = {200: 'OK', 400: 'Bad request', 404: 'Not Found', 409: 'Conflict', 422: 'Unprocessable Entity', 500: 'Internal server error', 503: 'Service unavailable', 504: 'Gateway Timeout'}
    headers = [(h['name'], re.sub(r'-(\w)', lambda m: m.group(1).upper(), h['name'])) for h in contract['headers']]
    rows = [f'      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = AgreementResponse.class)))']
    rows += [f'      @ApiResponse(responseCode = "{s}", description = "{reasons[s]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for s in contract['statuses'] if s != 200]
    out = ['/** Define el contrato del endpoint REST de transacciones de financiamiento (contrato OpenAPI). */', 'public interface AgreementApi {', '    /**',
           '     * Ejecuta una transaccion de negocio del modulo de Financiamiento segun el tipo de solicitud informado.', '     *', '     * @param request solicitud con el tipo de transaccion y sus datos']
    out += [f'     * @param {camel} header {name}' for name, camel in headers]
    out += ['     * @return respuesta HTTP con el modelo AgreementResponse definido en el contrato', '     */',
            f'    @PostMapping(path = "{contract["path"]}", consumes = {{"application/json"}}, produces = {{"application/json"}})',
            '    @Operation(summary = "Ejecutar transaccion de financiamiento")', '    @ApiResponses({', ',\n'.join(rows), '    })', f'    ResponseEntity<AgreementResponse> {contract["operationId"][0].lower()}{contract["operationId"][1:]}(']
    args = ['            @RequestBody AgreementRequest request'] + [f'            @RequestHeader(name = "{name}", required = true) String {camel}' for name, camel in headers]
    out += [',\n'.join(args) + ');', '}']
    return '\n'.join(out)


def controller(plan):
    contract = plan['contract']
    method = contract['operationId'][0].lower() + contract['operationId'][1:]
    headers = [re.sub(r'-(\w)', lambda m: m.group(1).upper(), h['name']) for h in contract['headers']]
    args = ',\n'.join(['            AgreementRequest request'] + [f'            String {h}' for h in headers])
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class AgreementController implements AgreementApi {', '    private final AgreementService service;', '',
                      '    @Override', f'    public ResponseEntity<AgreementResponse> {method}(', args + ') {', f'        log.info("{method} - transactionId: {{}}", xCorrelationId);',
                      '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);',
                      f'        return ResponseEntity.ok(service.{method}(headers, new ForwardedHeaders(traceparent, xAppId, xChannel, xClientVersionId, xCorrelationId, xRequestId, xUserId), request));',
                      '    }', '}'])


def service_if(plan):
    method = plan['contract']['operationId'][0].lower() + plan['contract']['operationId'][1:]
    return f'/** Orquestacion de las transacciones de financiamiento. */\npublic interface AgreementService {{\n    AgreementResponse {method}(RequestHeaders headers, ForwardedHeaders forwarded, AgreementRequest request);\n}}'


def service_impl(plan):
    contract = plan['contract']
    method = contract['operationId'][0].lower() + contract['operationId'][1:]
    return f'''/** Activity-logged orchestration; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class AgreementServiceImpl implements AgreementService {{
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String SUCCESS_MESSAGE = {jstr(contract['successMessage'])};

    private final AgreementRequestValidator validator;
    private final SystemSettings settings;
    private final InstallmentSynchronization synchronization;
    private final List<AgreementFlow> flows;
    private final Clock clock;

    @Override
    public AgreementResponse {method}(RequestHeaders headers, ForwardedHeaders forwarded, AgreementRequest request) {{
        final String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_RECIBE_PARAMETROS, () -> {{
            ActivityLogger.logContenido(log, "{method} request: {{}}", request, AgreementRequest.class);
            validator.validate(request);
            return Boolean.TRUE;
        }});
        Map<String, String> configuration = ejecutarActividad(menTran, ConstanApi.ACT1_1_OBTENER_CONFIGURACIONES, () -> settings.load(forwarded));
        FlowContext ctx = new FlowContext(headers, forwarded, request, clock, menTran, configuration);
        AgreementFlow flow = flows.stream().filter(candidate -> candidate.requestTypeId() == request.getRequestTypeId())
                .findFirst().orElseThrow(() -> ErrorCatalog.build("IDF102", null, null, null));
        if (flow.synchronizesInstallments()) {{
            synchronization.run(ctx);
        }}
        AgreementResponseData data = flow.execute(ctx);
        AgreementResponse response = new AgreementResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }}

    private String prefix(RequestHeaders headers) {{
        String tx = headers != null ? headers.transactionId() : null;
        return tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
    }}

    private <T> T ejecutarActividad(String menTran, String actividad, Supplier<T> accion) {{
        try {{
            ActivityLogger.inicioActividad(log, menTran, actividad);
            T result = accion.get();
            ActivityLogger.finActividad(log, menTran, actividad);
            return result;
        }} catch (ServiceOperationException ex) {{
            log.error("{{}} ERROR [{{}}] code={{}} subType={{}}", menTran, actividad, ex.getStatus().value(), ex.getSubType());
            throw ex;
        }} catch (RuntimeException ex) {{
            log.error("{{}} ERROR [{{}}] unexpected exception={{}}", menTran, actividad, ex.getMessage());
            throw ex;
        }}
    }}
}}'''


def handler(plan):
    allowed = ', '.join('HttpStatus.' + {400: 'BAD_REQUEST', 404: 'NOT_FOUND', 409: 'CONFLICT', 422: 'UNPROCESSABLE_ENTITY', 500: 'INTERNAL_SERVER_ERROR', 503: 'SERVICE_UNAVAILABLE',
                                         504: 'GATEWAY_TIMEOUT'}[s] for s in plan['contract']['statuses'] if s != 200)
    allowed = allowed.replace(', HttpStatus.INTERNAL', ',\n            HttpStatus.INTERNAL')
    return f'''@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {{
    private static final Set<HttpStatus> DECLARED = Set.of({allowed});

    @ExceptionHandler(ServiceOperationException.class)
    public ResponseEntity<ErrorResponse> operationFailure(ServiceOperationException failure) {{
        HttpStatus status = DECLARED.contains(failure.getStatus()) ? failure.getStatus() : HttpStatus.INTERNAL_SERVER_ERROR;
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(error(status, failure.getSubType(), failure.getType(), failure.getMessage()));
    }}

    @ExceptionHandler(MissingRequestHeaderException.class)
    public ResponseEntity<ErrorResponse> missingHeader(MissingRequestHeaderException failure) {{
        return operationFailure(ErrorCatalog.build("IDF101", null, null, failure.getHeaderName()));
    }}

    @ExceptionHandler({{ConstraintViolationException.class, MethodArgumentTypeMismatchException.class}})
    public ResponseEntity<ErrorResponse> invalidValue(Exception failure) {{
        log.error("Invalid request value: {{}}", failure.getMessage());
        return operationFailure(ErrorCatalog.build("IDF101", null, null, failure.getMessage()));
    }}

    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<ErrorResponse> unexpectedFailure(RuntimeException failure) {{
        log.error("Unexpected failure: {{}}", failure.getMessage(), failure);
        return operationFailure(ErrorCatalog.build(ErrorCatalog.INTERNAL, null, failure.getMessage(), null));
    }}

    @Override
    protected ResponseEntity<Object> handleHttpMessageNotReadable(HttpMessageNotReadableException failure, HttpHeaders headers, HttpStatusCode status, WebRequest request) {{
        log.error("Unreadable request body: {{}}", failure.getMessage());
        ServiceOperationException invalid = ErrorCatalog.build("IDF101", null, null, "body");
        return ResponseEntity.status(invalid.getStatus()).contentType(MediaType.APPLICATION_JSON).<Object>body(error(invalid.getStatus(), invalid.getSubType(), invalid.getType(), invalid.getMessage()));
    }}

    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception failure, @Nullable Object body, HttpHeaders headers, HttpStatusCode status, WebRequest request) {{
        log.error("Request failure: {{}}", failure.getMessage());
        ServiceOperationException internal = ErrorCatalog.build(ErrorCatalog.INTERNAL, null, failure.getMessage(), null);
        return ResponseEntity.status(internal.getStatus()).contentType(MediaType.APPLICATION_JSON).<Object>body(error(internal.getStatus(), internal.getSubType(), internal.getType(), internal.getMessage()));
    }}

    private ErrorResponse error(HttpStatus status, String subType, String type, String detail) {{
        ErrorResponse error = new ErrorResponse();
        error.setStatus(status.name());
        error.setCode(status.value());
        error.setSubType(subType);
        error.setType(type);
        error.setMessage(ErrorCatalog.MESSAGE);
        error.setDetail(detail);
        return error;
    }}
}}'''


def properties_class(plan):
    rows = []
    for name, value in sorted(plan['orchestration']['properties'].items()):
        if isinstance(value, int):
            rows.append(f'    public static final int {prop_const(name)} = {value};')
        else:
            rows.append(f'    public static final String {prop_const(name)} = {jstr(value)};')
    return ('/** Constants named by the Sparx "VARIABLES PROPERTIES" tables: financing and installment states and fixed values. */\npublic final class FinancingProperties {\n'
            + '\n'.join(rows) + '\n\n    private FinancingProperties() {\n    }\n}')


def clients(plan):
    """One facade class per dependency; every path is an environment parameter (injected by ClientConfig) whose default is the Sparx text."""
    files = {}
    for service, info in plan['orchestration']['clients'].items():
        cls = info['className']
        ops = info['operations']
        params = ', '.join(f'String {op}Path' for op in ops)
        out = [f'/** HTTP client of the dependency {service}. */', f'public class {cls} {{', '    private final RemoteGateway gateway;']
        out += [f'    private final String {op}Path;' for op in ops]
        out += ['', f'    public {cls}(RemoteGateway gateway, {params}) {{', '        this.gateway = gateway;']
        out += [f'        this.{op}Path = {op}Path;' for op in ops]
        out += ['    }', '', '    public String service() {', '        return gateway.service();', '    }']
        for op, meta in ops.items():
            out += ['', f'    /** {meta["method"]} {meta["path"]}. */',
                    f'    public RemoteResponse {op}(Consumer<HttpHeaders> headers, Map<String, Object> pathVariables, Map<String, Object> query, JsonNode body) {{',
                    f'        return gateway.send(HttpMethod.{meta["method"]}, {op}Path, headers, pathVariables, query, body);', '    }']
        out.append('}')
        files[cls] = '\n'.join(out)
    return files


def client_config(plan):
    out = ['/** HTTP client configuration of the dependencies: base URLs, paths and timeouts are environment parameters (defaults: the Sparx text). */', '@Configuration', 'public class ClientConfig {',
           '    private static RemoteGateway gateway(String service, String baseUrl, int timeoutMs, ObjectMapper mapper) {',
           '        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();', '        factory.setConnectTimeout(timeoutMs);', '        factory.setReadTimeout(timeoutMs);',
           '        return new RemoteGateway(RestClient.builder().baseUrl(baseUrl).requestFactory(factory).build(), mapper, service);', '    }']
    for service, info in plan['orchestration']['clients'].items():
        cls = info['className']
        prop = service.replace('_', '-')
        method = cls[0].lower() + cls[1:]
        params = [f'            @Value("${{agreement-orquestation.{prop}.base-url:http://{prop}}}") String baseUrl',
                  f'            @Value("${{agreement-orquestation.{prop}.timeout-ms:5000}}") int timeoutMs', '            ObjectMapper mapper']
        for op, meta in info['operations'].items():
            kebab = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '-', op).lower()
            params.append(f'            @Value("${{agreement-orquestation.{prop}.{kebab}-path:{meta["path"]}}}") String {op}Path')
        args = ', '.join(f'{op}Path' for op in info['operations'])
        out += ['', '    @Bean', f'    public {cls} {method}(', ',\n'.join(params) + ') {',
                f'        return new {cls}(gateway({jstr(service)}, baseUrl, timeoutMs, mapper), {args});', '    }']
    out.append('}')
    return '\n'.join(out)


# ----------------------------------------------------------------------------- assembly
def build_main(plan):
    """Returns ({path: java}, activity constants {NAME: value})."""
    pkg = plan['service']['package']
    base = f'src/main/java/{pkg.replace(".", "/")}/'
    files = {}
    contract = plan['contract']
    plan['orchestration']['contract_response_fields'] = [{'name': f['name'], 'type': 'Long' if f['type'] == 'integer' else 'BigDecimal' if f['type'] == 'number' else 'List' if f['type'] == 'array' else 'String'}
                                                          for f in contract['response']['dataFields']]

    def put(suffix, name, body, statics=(), extra=None):
        files[f'{base}{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = finalize(pkg, suffix, body, statics, extra)
    for name, body in (('Json', rt.JSON), ('Body', rt.BODY), ('Rules', rt.RULES), ('Calculations', rt.CALCULATIONS + ''), ('StepOutcome', rt.STEP_OUTCOME), ('FlowContext', rt.FLOW_CONTEXT),
                       ('AgreementFlow', rt.FLOW_INTERFACE)):
        put('orchestration', name, body)
    code = plan['orchestration']['config']['outcome']['otherwise']
    put('orchestration', 'SystemSettings', rt.SYSTEM_SETTINGS.replace('__CONFIG_CODE__', code))
    put('client', 'RemoteResponse', rt.REMOTE_RESPONSE)
    put('client', 'ForwardedHeaders', rt.FORWARDED_HEADERS)
    put('client', 'RemoteGateway', rt.GATEWAY)
    for cls, body in clients(plan).items():
        put('client', cls, body)
    put('configuration', 'ClientConfig', client_config(plan))
    put('configuration', 'ClockConfig', rt.CLOCK_CONFIG)
    put('configuration', 'FinancingProperties', properties_class(plan))
    put('exception', 'ServiceOperationException', rt.SERVICE_OPERATION_EXCEPTION)
    put('exception', 'ErrorCatalog', error_catalog(plan))
    put('exception', 'GlobalExceptionHandler', handler(plan))
    put('dto.request', 'RequestHeaders', rt.REQUEST_HEADERS)
    fields = [(JAVA_TYPES[f['type']], f['name']) for f in contract['request']['fields']]
    put('dto.request', 'AgreementRequest', dto('AgreementRequest', fields, 'Request of a financing transaction; requestTypeId selects the flow.'))
    inst = [(JAVA_TYPES[f['type']], f['name']) for f in contract['response']['installmentFields']]
    put('dto.response', 'AgreementInstallmentDto', dto('AgreementInstallmentDto', inst, non_null=True))
    data = [('List<AgreementInstallmentDto>' if f['type'] == 'array' else JAVA_TYPES[f['type']], f['name']) for f in contract['response']['dataFields']]
    put('dto.response', 'AgreementResponseData', dto('AgreementResponseData', data, non_null=False))
    put('dto.response', 'AgreementResponse', dto('AgreementResponse', [('Integer', 'code'), ('String', 'message'), ('AgreementResponseData', 'data')]))
    put('dto.response', 'ErrorResponse', rt.ERROR_RESPONSE)
    put('validation', 'AgreementRequestValidator', validator(plan))
    put('controller', 'AgreementApi', api(plan))
    put('controller.impl', 'AgreementController', controller(plan))
    put('service', 'AgreementService', service_if(plan))
    put('service.impl', 'AgreementServiceImpl', service_impl(plan))
    writer = FlowWriter(plan)
    orch = plan['orchestration']
    sync_flow = {'steps': orch['sync'], 'chains': {}, 'compensations': {}, 'prerequisite': None}
    put('orchestration', 'InstallmentSynchronization', writer.flow_class('InstallmentSynchronization', sync_flow, None, True))
    for type_id, flow in orch['flows'].items():
        cls = FLOW_CLASSES[type_id]
        put('orchestration', cls, writer.flow_class(cls, flow, int(type_id), False))
    constants = {'ACT1_RECIBE_PARAMETROS': 'RECIBE_PARAMETROS', 'ACT1_1_OBTENER_CONFIGURACIONES': 'OBTENER_CONFIGURACIONES', **writer.constants}
    return files, constants


def activity_constants(constants):
    return '\n'.join(f'    public static final String {name} = {jstr(value)};' for name, value in constants.items())
