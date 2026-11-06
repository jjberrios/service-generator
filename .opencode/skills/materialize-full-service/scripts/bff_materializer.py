"""Deterministic materializer for the archetype profile `jar-springboot3-webmvc-webclient-bff`.

Renders the archetype technical files (@@TOKEN@@) and the Java derived from the implementation plan (scope structure + contract):
DTOs, API interface, controller, service, optional WebClient integrations (only with an explicit bffBinding) and JUnit 5/Mockito tests.
Behavior without a binding is generated as an explicit failure (UnsupportedOperationException) and reported in `omittedBehavior`.
Checkstyle required by the reference is never claimed as passed: it stays `unverified`.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

PROFILE = 'jar-springboot3-webmvc-webclient-bff'
VERSION = 'bff-materializer-1-structure-contract'
TOKEN = re.compile(r'@@([A-Z0-9_]+)@@')
STATUS = {200: 'OK', 201: 'CREATED', 202: 'ACCEPTED', 204: 'NO_CONTENT'}
MAPPING = {'GET': 'GetMapping', 'POST': 'PostMapping', 'PUT': 'PutMapping', 'DELETE': 'DeleteMapping', 'PATCH': 'PatchMapping'}
STATIC_IMPORTS = {
    'List': 'java.util.List', 'Valid': 'jakarta.validation.Valid', 'ResponseEntity': 'org.springframework.http.ResponseEntity',
    'HttpStatus': 'org.springframework.http.HttpStatus', 'RequestHeader': 'org.springframework.web.bind.annotation.RequestHeader',
    'RequestParam': 'org.springframework.web.bind.annotation.RequestParam', 'PathVariable': 'org.springframework.web.bind.annotation.PathVariable',
    'RequestBody': 'org.springframework.web.bind.annotation.RequestBody', 'RestController': 'org.springframework.web.bind.annotation.RestController',
    'GetMapping': 'org.springframework.web.bind.annotation.GetMapping', 'PostMapping': 'org.springframework.web.bind.annotation.PostMapping',
    'PutMapping': 'org.springframework.web.bind.annotation.PutMapping', 'DeleteMapping': 'org.springframework.web.bind.annotation.DeleteMapping',
    'PatchMapping': 'org.springframework.web.bind.annotation.PatchMapping', 'Service': 'org.springframework.stereotype.Service',
    'Component': 'org.springframework.stereotype.Component', 'Qualifier': 'org.springframework.beans.factory.annotation.Qualifier',
    'Value': 'org.springframework.beans.factory.annotation.Value', 'Configuration': 'org.springframework.context.annotation.Configuration',
    'Bean': 'org.springframework.context.annotation.Bean', 'WebClient': 'org.springframework.web.reactive.function.client.WebClient',
    'ReactorClientHttpConnector': 'org.springframework.http.client.reactive.ReactorClientHttpConnector', 'Duration': 'java.time.Duration',
    'ChannelOption': 'io.netty.channel.ChannelOption', 'ReadTimeoutHandler': 'io.netty.handler.timeout.ReadTimeoutHandler',
    'WriteTimeoutHandler': 'io.netty.handler.timeout.WriteTimeoutHandler', 'HttpClient': 'reactor.netty.http.client.HttpClient',
    'Data': 'lombok.Data', 'NoArgsConstructor': 'lombok.NoArgsConstructor', 'AllArgsConstructor': 'lombok.AllArgsConstructor',
    'Test': 'org.junit.jupiter.api.Test', 'BeforeEach': 'org.junit.jupiter.api.BeforeEach', 'Assertions': 'org.junit.jupiter.api.Assertions',
    'Mockito': 'org.mockito.Mockito', 'UriBuilder': 'org.springframework.web.util.UriBuilder', 'Map': 'java.util.Map', 'HashMap': 'java.util.HashMap',
    'ClientRequest': 'org.springframework.web.reactive.function.client.ClientRequest',
    'ClientResponse': 'org.springframework.web.reactive.function.client.ClientResponse',
    'ExchangeFunction': 'org.springframework.web.reactive.function.client.ExchangeFunction', 'Mono': 'reactor.core.publisher.Mono',
    'AtomicReference': 'java.util.concurrent.atomic.AtomicReference',
    'NotNull': 'jakarta.validation.constraints.NotNull', 'Size': 'jakarta.validation.constraints.Size',
    'JsonInclude': 'com.fasterxml.jackson.annotation.JsonInclude', 'JsonIgnore': 'com.fasterxml.jackson.annotation.JsonIgnore',
    'JsonAnyGetter': 'com.fasterxml.jackson.annotation.JsonAnyGetter', 'JsonAnySetter': 'com.fasterxml.jackson.annotation.JsonAnySetter',
    'ObjectMapper': 'com.fasterxml.jackson.databind.ObjectMapper', 'Validation': 'jakarta.validation.Validation',
    'Validator': 'jakarta.validation.Validator', 'ConstraintViolation': 'jakarta.validation.ConstraintViolation', 'Set': 'java.util.Set',
    'ArrayList': 'java.util.ArrayList',
}
SAMPLES = {'String': ('"sample"', 'sample'), 'Long': ('1L', '1'), 'Integer': ('1', '1'), 'Double': ('1.0', '1.0'), 'Boolean': ('true', 'true')}


def pascal(text):
    return ''.join(part[:1].upper() + part[1:] for part in re.split(r'[^A-Za-z0-9]+', text) if part)


def camel(text):
    value = pascal(text)
    return value[:1].lower() + value[1:]


def upper_snake(text):
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', text).upper()


def lower_first(text):
    return text[:1].lower() + text[1:]


EXTRA_JSON = '"{\\"extra\\":\\"v\\"}"'
EXTRA_FRAGMENT = '"extra":"v"'
WRAP_AT = 160


def wrap_line(line):
    """Wrap an over-long declaration/call after the commas of its outermost parentheses (SeparatorWrap EOL, wrapping indentation 8)."""
    if len(line) <= WRAP_AT:
        return [line]
    indent = len(line) - len(line.lstrip(' '))
    pieces, start, depth, quote, last = [], 0, 0, False, None
    for i, ch in enumerate(line):
        if ch == '"' and (i == 0 or line[i - 1] != '\\'):
            quote = not quote
        elif quote:
            continue
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 1:
            if i + 1 - start > WRAP_AT - (0 if not pieces else indent + 8) and last is not None:
                pieces.append(line[start:last + 1])
                start = last + 2
            last = i
    pieces.append(line[start:])
    return [pieces[0]] + [' ' * (indent + 8) + piece for piece in pieces[1:]]


def jstr(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


class Ctx:
    def __init__(self, plan):
        self.plan = plan
        self.base = plan['service']['basePackage']
        self.pp = self.base.replace('.', '/')
        self.names = plan['technicalProfile']['names']
        self.models = {m['name']: m for m in plan['models']}
        self.ops = plan['operations']
        self.integrations = plan['integrations']
        self.model_pkg = {n: self.package_for(m['role']) for n, m in self.models.items()}
        self.local = {self.names['controller']: f'{self.base}.controller',
                      self.names['controllerImpl']: f'{self.base}.controller.impl',
                      self.names['service']: f'{self.base}.service',
                      self.names['serviceImpl']: f'{self.base}.service.impl'}
    def package_for(self, role):
        return f"{self.base}.dto.{ {'request': 'request', 'response': 'response'}.get(role, 'type') }"

    def classes_in(self, text, own_pkg):
        found = set()
        for name in set(re.findall(r'\b[A-Z][A-Za-z0-9]*\b', text)):
            if name in self.models:
                if self.model_pkg[name] != own_pkg:
                    found.add(f'{self.model_pkg[name]}.{name}')
            elif name in self.local:
                if self.local[name] != own_pkg:
                    found.add(f'{self.local[name]}.{name}')
            elif name in STATIC_IMPORTS:
                found.add(STATIC_IMPORTS[name])
        return found

    def source(self, pkg, body_lines, extra_imports=()):
        body_lines = [wrapped for line in body_lines for wrapped in wrap_line(line)]
        body = '\n'.join(body_lines)
        imports = sorted(self.classes_in(body, pkg) | set(extra_imports))
        out = [f'package {pkg};', '']
        out += [f'import {i};' for i in imports]
        if imports:
            out.append('')
        return '\n'.join(out + body_lines) + '\n'

    def dto(self, model):
        pkg = self.model_pkg[model['name']]
        validated = model.get('validated', False)
        lines = ['@Data', '@NoArgsConstructor', '@AllArgsConstructor']
        if validated:
            lines.append('@JsonInclude(JsonInclude.Include.NON_NULL)')
        lines += [f"public class {model['name']} {{", '']
        constants = [f"    private static final int {upper_snake(f['name'])}_MAX_LENGTH = {f['maxLength']};" for f in model['fields'] if f.get('maxLength') is not None]
        lines += constants + [''] * bool(constants)
        for f in model['fields']:
            annotations = []
            if f.get('required'):
                annotations.append('    @NotNull')
            if f.get('maxLength') is not None:
                annotations.append(f"    @Size(max = {upper_snake(f['name'])}_MAX_LENGTH)")
            nested = self.models.get(f['javaType'])
            if nested and nested.get('validated'):
                annotations.append('    @Valid')
            lines += annotations + [f"    private {f['javaType']} {f['name']};"]
            if annotations:
                lines.append('')
        if model.get('additionalProperties'):
            lines += ([] if lines[-1] == '' else ['']) + ['    @JsonIgnore', '    private Map<String, Object> additionalProperties = new HashMap<>();', '',
                      '    @JsonAnyGetter', '    public Map<String, Object> anyProperties() {', '        return additionalProperties;', '    }', '',
                      '    @JsonAnySetter', '    public void putAnyProperty(String key, Object value) {', '        additionalProperties.put(key, value);', '    }']
        elif model['fields'] and lines[-1] == '':
            lines.pop()
        lines.append('}')
        return self.source(pkg, lines)

    def response_type(self, op):
        return op['responseClass']

    def signature(self, op, annotated):
        params = []
        for p in op['parameters']:
            if annotated:
                ann = {'header': f"@RequestHeader(name = {jstr(p['name'])}, required = {str(p['required']).lower()})",
                       'query': f"@RequestParam(name = {jstr(p['name'])}, required = {str(p['required']).lower()})",
                       'path': f"@PathVariable(name = {jstr(p['name'])})"}[p['in']]
                params.append(f"{ann} {p['javaType']} {p['variable']}")
            else:
                params.append(f"{p['javaType']} {p['variable']}")
        if op['requestClass']:
            ann = ('@Valid @RequestBody' if op['requestRequired'] else '@Valid @RequestBody(required = false)') if annotated else ''
            params.append(f"{ann} {op['requestClass']} body".strip())
        return ', '.join(params)

    def call_args(self, op):
        names = [p['variable'] for p in op['parameters']] + (['body'] if op['requestClass'] else [])
        return ', '.join(names)

    def api_interface(self):
        n = self.names
        lines = [f"public interface {n['controller']} {{", '']
        for op in self.ops:
            mapping = MAPPING[op['httpMethod']]
            ret = f"ResponseEntity<{op['responseClass'] or 'Void'}>"
            lines += [f"    @{mapping}({jstr(op['path'])})", f"    {ret} {op['operationId']}({self.signature(op, True)});", '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.controller', lines)

    def controller_impl(self):
        n = self.names
        field = lower_first(n['service'])
        lines = ['@RestController', f"public class {n['controllerImpl']} implements {n['controller']} {{", '',
                 f"    private final {n['service']} {field};", '',
                 f"    public {n['controllerImpl']}({n['service']} {field}) {{", f'        this.{field} = {field};', '    }', '']
        for op in self.ops:
            status = f"HttpStatus.{STATUS[op['successStatus']]}"
            lines += ['    @Override', f"    public ResponseEntity<{op['responseClass'] or 'Void'}> {op['operationId']}({self.signature(op, False)}) {{"]
            if op['responseClass']:
                lines += [f"        {op['responseClass']} result = {field}.{op['operationId']}({self.call_args(op)});",
                          f'        return ResponseEntity.status({status}).body(result);']
            else:
                lines += [f"        {field}.{op['operationId']}({self.call_args(op)});", f'        return ResponseEntity.status({status}).build();']
            lines += ['    }', '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.controller.impl', lines)

    def service_interface(self):
        lines = [f"public interface {self.names['service']} {{", '']
        for op in self.ops:
            lines.append(f"    {op['responseClass'] or 'void'} {op['operationId']}({self.signature(op, False)});")
            lines.append('')
        lines[-1:] = ['}']
        return self.source(f'{self.base}.service', lines)

    def used_integrations(self):
        return sorted({op['binding']['name'] for op in self.ops if op['binding']})

    def service_impl(self):
        n = self.names
        used = self.used_integrations()
        lines = ['@Service', f"public class {n['serviceImpl']} implements {n['service']} {{", '']
        extra = []
        for name in used:
            client = self.integrations[name]['client']
            lines.append(f'    private final {client} {lower_first(client)};')
            extra.append(f"{self.base}.client.{name.lower()}.{client}")
        if used:
            lines.append('')
            ctor = ', '.join(f"{self.integrations[x]['client']} {lower_first(self.integrations[x]['client'])}" for x in used)
            lines += [f"    public {n['serviceImpl']}({ctor}) {{"]
            lines += [f"        this.{lower_first(self.integrations[x]['client'])} = {lower_first(self.integrations[x]['client'])};" for x in used]
            lines += ['    }', '']
        for op in self.ops:
            lines += ['    @Override', f"    public {op['responseClass'] or 'void'} {op['operationId']}({self.signature(op, False)}) {{"]
            if op['binding']:
                client = lower_first(self.integrations[op['binding']['name']]['client'])
                lines.append(f"        return {client}.{op['operationId']}({self.client_args(op)});")
            else:
                lines.append(f"        throw new UnsupportedOperationException({jstr('Behavior omitted (no explicit specification): ' + op['operationId'])});")
            lines += ['    }', '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.service.impl', lines, extra)

    def client_args(self, op, values=False):
        binding = op['binding']
        args = []
        if binding['forwardParameters']:
            args += [p['variable'] for p in op['parameters']] if not values else ['null' for _ in op['parameters']]
        if binding['forwardRequestBody']:
            args.append('request' if values else 'body')
        return ', '.join(args)

    def client_signature(self, op):
        binding = op['binding']
        params = [f"{p['javaType']} {p['variable']}" for p in op['parameters']] if binding['forwardParameters'] else []
        if binding['forwardRequestBody']:
            params.append(f"{op['requestClass']} body")
        return ', '.join(params)

    def forwarding_method(self, op, binding):
        params = op['parameters']
        lines = [f"        return webClient.{binding['method'].lower()}()", '                .uri(uriBuilder -> {',
                 '                    Map<String, Object> variables = new HashMap<>();']
        lines += [f"                    variables.put({jstr(p['name'])}, {p['variable']});" for p in params if p['in'] == 'path']
        lines.append('                    UriBuilder builder = uriBuilder.path(url);')
        for p in params:
            if p['in'] == 'query':
                condition = f"{p['variable']} != null"
                lines += [f"                    if ({condition}) {{", f"                        builder.queryParam({jstr(p['name'])}, {jstr('{' + p['name'] + '}')});",
                          f"                        variables.put({jstr(p['name'])}, {p['variable']});", '                    }']
        lines += ['                    return builder.build(variables);', '                })']
        headers = [p for p in params if p['in'] == 'header']
        if headers:
            lines.append('                .headers(headers -> {')
            for p in headers:
                value = p['variable'] if p['javaType'] == 'String' else f"String.valueOf({p['variable']})"
                lines += [f"                    if ({p['variable']} != null) {{", f"                        headers.add({jstr(p['name'])}, {value});", '                    }']
            lines.append('                })')
        return lines

    def web_client_config(self, name):
        item, prefix = self.integrations[name], self.integrations[name]['propertyPrefix']
        bean = name + 'WebClient'
        pkg = f'{self.base}.client.{name.lower()}'
        lines = ['@Configuration', f"public class {item['config']} {{", '', f'    @Bean({jstr(bean)})',
                 f"    public WebClient {bean}(@Value({jstr('${' + prefix + '.baseurl}')}) String baseUrl,",
                 f"            @Value({jstr('${' + prefix + '.rest-client.connect-timeout}')}) int connectTimeout,",
                 f"            @Value({jstr('${' + prefix + '.rest-client.read-timeout}')}) int readTimeout) {{",
                 '        HttpClient httpClient = HttpClient.create()',
                 '                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, (int) Duration.ofSeconds(connectTimeout).toMillis())',
                 '                .responseTimeout(Duration.ofSeconds(readTimeout))',
                 '                .doOnConnected(conn -> conn.addHandlerLast(new ReadTimeoutHandler(readTimeout))',
                 '                        .addHandlerLast(new WriteTimeoutHandler(readTimeout)));',
                 '        return WebClient.builder()', '                .baseUrl(baseUrl)',
                 '                .clientConnector(new ReactorClientHttpConnector(httpClient))', '                .build();', '    }', '}']
        return self.source(pkg, lines)

    def web_client(self, name):
        item, prefix = self.integrations[name], self.integrations[name]['propertyPrefix']
        lines = ['@Component', f"public class {item['client']} {{", '', '    private final WebClient webClient;', '', '    private final String url;', '',
                 f"    public {item['client']}(@Qualifier({jstr(name + 'WebClient')}) WebClient webClient,",
                 f"            @Value({jstr('${' + prefix + '.url}')}) String url) {{",
                 '        this.webClient = webClient;', '        this.url = url;', '    }', '']
        for op in self.ops:
            binding = op['binding']
            if not binding or binding['name'] != name:
                continue
            verb = binding['method'].lower()
            lines.append(f"    public {op['responseClass']} {op['operationId']}({self.client_signature(op)}) {{")
            lines += self.forwarding_method(op, binding) if binding['forwardParameters'] else [f"        return webClient.{verb}()", '                .uri(url)']
            if binding['forwardRequestBody']:
                lines.append('                .bodyValue(body)')
            lines += ['                .retrieve()', f"                .bodyToMono({op['responseClass']}.class)", '                .block();', '    }', '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.client.{name.lower()}', lines)

    def arg_values(self, op):
        values = ['null' for _ in op['parameters']]
        if op['requestClass']:
            values.append('request')
        return ', '.join(values)

    def request_setup(self, op):
        return [f"        {op['requestClass']} request = new {op['requestClass']}();"] if op['requestClass'] else []

    def service_test(self):
        n = self.names
        used = self.used_integrations()
        cls = n['serviceImpl']
        lines = [f'public class {cls}Test {{', '']
        extra = []
        for x in used:
            client = self.integrations[x]['client']
            lines.append(f'    private {client} {lower_first(client)};')
            extra.append(f'{self.base}.client.{x.lower()}.{client}')
        lines += [f'    private {cls} service;', '', '    @BeforeEach', '    void setUp() {']
        for x in used:
            client = self.integrations[x]['client']
            lines.append(f'        {lower_first(client)} = Mockito.mock({client}.class);')
        args = ', '.join(lower_first(self.integrations[x]['client']) for x in used)
        lines += [f'        service = new {cls}({args});', '    }', '']
        for op in self.ops:
            oid = op['operationId']
            if op['binding']:
                client = lower_first(self.integrations[op['binding']['name']]['client'])
                lines += ['    @Test', f'    void {oid}DelegatesToIntegration() {{'] + self.request_setup(op)
                lines += [f"        {op['responseClass']} expected = new {op['responseClass']}();",
                          f"        Mockito.when({client}.{oid}({self.client_args(op, True)})).thenReturn(expected);",
                          f"        Assertions.assertSame(expected, service.{oid}({self.arg_values(op)}));", '    }', '']
            else:
                lines += ['    @Test', f'    void {oid}BehaviorOmitted() {{'] + self.request_setup(op)
                lines += [f"        Assertions.assertThrows(UnsupportedOperationException.class, () -> service.{oid}({self.arg_values(op)}));", '    }', '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.service.impl', lines, extra)

    def forwarding_ops(self, name):
        return [op for op in self.ops if op['binding'] and op['binding']['name'] == name and op['binding']['forwardParameters']]

    def client_test(self, name):
        item = self.integrations[name]
        ops = self.forwarding_ops(name)
        cls = item['client']
        first = ops[0]
        path = first['binding']['backendPath'] or '/' + first['operationId'] + ''.join('/{' + p['name'] + '}' for p in first['parameters'] if p['in'] == 'path')
        lines = [f'public class {cls}Test {{', '', '    private static final String BASE_URL = "http://backend.test";', '',
                 f'    private static final String PATH = {jstr(path)};', '', '    private final AtomicReference<ClientRequest> captured = new AtomicReference<>();', '',
                 f'    private {cls} client;', '', '    @BeforeEach', '    void setUp() {', '        ExchangeFunction exchange = request -> {',
                 '            captured.set(request);',
                 '            return Mono.just(ClientResponse.create(HttpStatus.OK).header("Content-Type", "application/json").body("{}").build());',
                 '        };', '        WebClient webClient = WebClient.builder().baseUrl(BASE_URL).exchangeFunction(exchange).build();',
                 f'        client = new {cls}(webClient, PATH);', '    }', '']
        for op in ops:
            oid = op['operationId']
            sample = {p['name']: SAMPLES[p['javaType']] for p in op['parameters']}
            resolved = path
            for p in op['parameters']:
                if p['in'] == 'path':
                    resolved = resolved.replace('{' + p['name'] + '}', sample[p['name']][1])
            full = [sample[p['name']][0] for p in op['parameters']] + (['request'] if op['binding']['forwardRequestBody'] else [])
            lines += ['    @Test', f'    void {oid}ForwardsDeclaredParameters() {{'] + self.request_setup(op)
            lines += [f"        client.{oid}({', '.join(full)});", '        ClientRequest sent = captured.get();',
                      f"        Assertions.assertEquals({jstr(op['binding']['method'])}, sent.method().name());",
                      f'        Assertions.assertEquals({jstr(resolved)}, sent.url().getPath());']
            for p in op['parameters']:
                if p['in'] == 'header':
                    lines.append(f"        Assertions.assertEquals({jstr(sample[p['name']][1])}, sent.headers().getFirst({jstr(p['name'])}));")
                elif p['in'] == 'query':
                    lines.append(f"        Assertions.assertTrue(sent.url().getQuery().contains({jstr(p['name'] + '=' + sample[p['name']][1])}));")
            lines += ['    }', '']
            optional = [p for p in op['parameters'] if p['in'] != 'path' and not p['required']]
            if optional:
                absent = [('null' if p in optional else sample[p['name']][0]) for p in op['parameters']] + (['request'] if op['binding']['forwardRequestBody'] else [])
                lines += ['    @Test', f'    void {oid}OmitsAbsentOptionalParameters() {{'] + self.request_setup(op)
                lines += [f"        client.{oid}({', '.join(absent)});", '        ClientRequest sent = captured.get();']
                for p in optional:
                    if p['in'] == 'header':
                        lines.append(f"        Assertions.assertNull(sent.headers().getFirst({jstr(p['name'])}));")
                    else:
                        lines.append(f"        Assertions.assertFalse(String.valueOf(sent.url().getQuery()).contains({jstr(p['name'] + '=')}));")
                lines += ['    }', '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.client.{name.lower()}', lines)

    def controller_test(self):
        n = self.names
        cls = n['controllerImpl']
        lines = [f'public class {cls}Test {{', '', f"    private {n['service']} service;", '', f'    private {cls} controller;', '',
                 '    @BeforeEach', '    void setUp() {', f"        service = Mockito.mock({n['service']}.class);", f'        controller = new {cls}(service);', '    }', '']
        for op in self.ops:
            oid = op['operationId']
            lines += ['    @Test', f'    void {oid}ReturnsDeclaredStatus() {{'] + self.request_setup(op)
            if op['responseClass']:
                lines += [f"        {op['responseClass']} expected = new {op['responseClass']}();",
                          f"        Mockito.when(service.{oid}({self.arg_values(op)})).thenReturn(expected);",
                          f"        ResponseEntity<{op['responseClass']}> result = controller.{oid}({self.arg_values(op)});",
                          '        Assertions.assertSame(expected, result.getBody());']
            else:
                lines += [f"        ResponseEntity<Void> result = controller.{oid}({self.arg_values(op)});"]
            lines += [f"        Assertions.assertEquals(HttpStatus.{STATUS[op['successStatus']]}.value(), result.getStatusCode().value());", '    }', '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.controller.impl', lines)

    def contract_classes(self):
        return [m for _, m in sorted(self.models.items())
                if m.get('validated') and (m.get('additionalProperties') or any(f.get('required') or f.get('maxLength') is not None for f in m['fields']))]

    def sample_expression(self, java_type):
        if java_type in SAMPLES:
            return SAMPLES[java_type][0]
        if java_type in self.models:
            return f'valid{java_type}()'
        return 'new ArrayList<>()'

    def request_contract_test(self):
        classes = self.contract_classes()
        helpers, queue = {}, [m['name'] for m in classes]
        while queue:
            name = queue.pop(0)
            if name in helpers:
                continue
            helpers[name] = [f for f in self.models[name]['fields'] if f.get('required')]
            queue += [f['javaType'] for f in helpers[name] if f['javaType'] in self.models]
        lines = ['public class RequestContractTest {', '']
        constants = [f"    private static final int {upper_snake(m['name'])}_{upper_snake(f['name'])}_MAX_LENGTH = {f['maxLength']};"
                     for m in classes for f in m['fields'] if f.get('maxLength') is not None]
        lines += constants + [''] * bool(constants)
        lines += ['    private final ObjectMapper mapper = new ObjectMapper();', '', '    private Validator validator;', '',
                 '    @BeforeEach', '    void setUp() {', '        validator = Validation.buildDefaultValidatorFactory().getValidator();', '    }', '']
        for name in sorted(helpers):
            lines += [f'    private static {name} valid{name}() {{', f'        {name} value = new {name}();']
            lines += [f"        value.set{f['name'][:1].upper()}{f['name'][1:]}({self.sample_expression(f['javaType'])});" for f in helpers[name]]
            lines += ['        return value;', '    }', '']
        for m in classes:
            name, prefix = m['name'], lower_first(m['name'])
            required = [f for f in m['fields'] if f.get('required')]
            if required:
                lines += ['    @Test', f'    void {prefix}RejectsMissingRequiredFields() {{',
                          f'        Set<ConstraintViolation<{name}>> violations = validator.validate(new {name}());',
                          f'        Assertions.assertEquals({len(required)}, violations.size());', '    }', '',
                          '    @Test', f'    void {prefix}AcceptsDeclaredRequiredFields() {{',
                          f'        Assertions.assertTrue(validator.validate(valid{name}()).isEmpty());', '    }', '']
            for f in m['fields']:
                if f.get('maxLength') is None:
                    continue
                setter = f"set{f['name'][:1].upper()}{f['name'][1:]}"
                limit = f"{upper_snake(name)}_{upper_snake(f['name'])}_MAX_LENGTH"
                lines += ['    @Test', f"    void {prefix}{f['name'][:1].upper()}{f['name'][1:]}EnforcesMaxLength() {{", f'        {name} value = valid{name}();',
                          f'        value.{setter}("x".repeat({limit}));', '        Assertions.assertTrue(validator.validate(value).isEmpty());',
                          f'        value.{setter}("x".repeat({limit} + 1));', '        Assertions.assertEquals(1, validator.validate(value).size());', '    }', '']
            lines += ['    @Test', f'    void {prefix}OmitsAbsentFieldsWhenSerialized() throws Exception {{',
                      f'        Assertions.assertEquals("{{}}", mapper.writeValueAsString(new {name}()));', '    }', '']
            if m.get('additionalProperties'):
                lines += ['    @Test', f'    void {prefix}KeepsUnmodeledProperties() throws Exception {{',
                          f'        {name} value = mapper.readValue({EXTRA_JSON}, {name}.class);',
                          '        Assertions.assertEquals("v", value.anyProperties().get("extra"));',
                          '        Assertions.assertTrue(mapper.writeValueAsString(value).contains(' + jstr(EXTRA_FRAGMENT) + '));', '    }', '']
        lines[-1:] = ['}']
        return self.source(f'{self.base}.dto.request', lines)

    def request_contract_present(self):
        return bool(self.contract_classes())

    def backend_path(self, name):
        return next((op['binding']['backendPath'] for op in self.ops if op['binding'] and op['binding']['name'] == name and op['binding']['backendPath']), None)

    def properties_block(self):
        lines = []
        for name in sorted(self.integrations):
            prefix = self.integrations[name]['propertyPrefix']
            lines += ['', f'# Integration {name} (generated from an explicit bffBinding; define the operator values)']
            lines += [f'{prefix}.baseurl=', f"{prefix}.url={self.backend_path(name) or ''}", f'{prefix}.rest-client.connect-timeout=', f'{prefix}.rest-client.read-timeout=']
        return '\n'.join(lines) + '\n' if lines else ''


def required_properties(plan):
    ctx = Ctx(plan)
    rows = []
    for name in sorted(ctx.integrations):
        prefix = ctx.integrations[name]['propertyPrefix']
        for suffix, note in (('baseurl', 'integration base URL'), ('url', 'integration path'), ('rest-client.connect-timeout', 'seconds'), ('rest-client.read-timeout', 'seconds')):
            rows.append({'key': f'{prefix}.{suffix}', 'integration': name, 'note': note, 'suggestedValue': ctx.backend_path(name) if suffix == 'url' else None})
    rows.append({'key': 'JWT_SECRET_KEY', 'integration': None, 'note': 'environment variable consumed by security.jwt.secret-key', 'suggestedValue': None})
    return {'schemaVersion': 1, 'note': 'The generator never writes application*.properties; define these keys in the environment.', 'properties': rows}


def render_template(repo: Path, plan: dict) -> dict:
    root = repo / plan['inputs']['archetype']['path'] / 'template'
    values = plan['templateParameters']
    from artifact_integrity import template_paths, safe_path
    files = {}
    for rel in template_paths(root.parent):
        text = safe_path(root, rel).read_text(encoding='utf-8')
        for source in (rel, text):
            missing = {t for t in TOKEN.findall(source) if t not in values}
            if missing:
                raise ValueError(f'template {rel}: unresolved parameter(s) {sorted(missing)}')
        files[TOKEN.sub(lambda m: str(values[m.group(1)]), rel)] = ('project-assembly', TOKEN.sub(lambda m: str(values[m.group(1)]), text))
    return files


def render_project(plan: dict, repo: Path) -> dict:
    if plan.get('plan', {}).get('bffBindingVersion') != 1:
        raise ValueError('unsupported-bff-binding: replan with the BFF planner (binding version 1)')
    ctx = Ctx(plan)
    out = dict(render_template(repo, plan))
    for path, (ctype, text) in list(out.items()):
        if path.endswith('configmap.yml.j2') and ctx.properties_block():
            out[path] = (ctype, text.rstrip('\n') + '\n' + ctx.properties_block())
    n, main, test = ctx.names, f'src/main/java/{ctx.pp}', f'src/test/java/{ctx.pp}'
    java = {}
    for name, model in ctx.models.items():
        java[f"{main}/dto/{ {'request': 'request', 'response': 'response'}.get(model['role'], 'type') }/{name}.java"] = ctx.dto(model)
    java[f"{main}/controller/{n['controller']}.java"] = ctx.api_interface()
    java[f"{main}/controller/impl/{n['controllerImpl']}.java"] = ctx.controller_impl()
    java[f"{main}/service/{n['service']}.java"] = ctx.service_interface()
    java[f"{main}/service/impl/{n['serviceImpl']}.java"] = ctx.service_impl()
    for name in sorted(ctx.integrations):
        java[f"{main}/client/{name.lower()}/{ctx.integrations[name]['config']}.java"] = ctx.web_client_config(name)
        java[f"{main}/client/{name.lower()}/{ctx.integrations[name]['client']}.java"] = ctx.web_client(name)
        if ctx.forwarding_ops(name):
            java[f"{test}/client/{name.lower()}/{ctx.integrations[name]['client']}Test.java"] = ctx.client_test(name)
    java[f"{test}/controller/impl/{n['controllerImpl']}Test.java"] = ctx.controller_test()
    if ctx.request_contract_present():
        java[f"{test}/dto/request/RequestContractTest.java"] = ctx.request_contract_test()
    java[f"{test}/service/impl/{n['serviceImpl']}Test.java"] = ctx.service_test()
    planned = {e['path']: e for e in plan['files']['generate']}
    for path, text in java.items():
        if path not in planned:
            raise ValueError(f'generated file {path} is not planned')
        out[path] = (planned[path]['componentType'], text)
    if set(out) != set(planned) or len(planned) != len(plan['files']['generate']):
        raise ValueError('rendered inventory differs from plan (including technical/configuration files)')
    if any(entry['action'] not in ('create', 'update') for entry in planned.values()):
        raise ValueError('unsupported BFF file action')
    return out


def _load_plan(ws, repo, fm):
    plan_file = ws.dir / 'implementation-plan.yml'
    if not plan_file.is_file():
        raise fm.MaterializationError('invalid-plan', 'the workspace has no implementation-plan.yml')
    raw = plan_file.read_bytes()
    plan = yaml.safe_load(raw)
    sha = fm.sha
    svc = plan.get('service') or {}
    if (plan.get('plan') or {}).get('mode') != 'full' or (plan.get('generation') or {}).get('functionalGenerationReady') is not True:
        raise fm.MaterializationError('invalid-plan', 'the plan is not a ready full plan')
    if svc.get('name') != ws.service or svc.get('outputDirectory') != f'output/{ws.service}':
        raise fm.MaterializationError('invalid-plan', 'the plan belongs to another service or output directory')
    if plan.get('plan', {}).get('bffBindingVersion') != 1:
        raise fm.MaterializationError('unsupported', 'plan without BFF binding version 1; replan required; no files were changed')
    spec = ws.dir / 'service-spec.yml'
    inputs = plan.get('inputs') or {}
    if not spec.is_file() or (inputs.get('serviceSpec') or {}).get('artifactSha256') != sha(spec.read_bytes()):
        raise fm.MaterializationError('stale-plan', 'the plan was not built from the current service-spec of this workspace')
    arch = inputs.get('archetype') or {}
    root = repo / str(arch.get('path'))
    if not root.is_dir() or fm.planner_base.archetype_fingerprint(root) != arch.get('fingerprint'):
        raise fm.MaterializationError('stale-plan', 'the archetype differs from the one used for planning')
    for key, filename in (('generationParameters', 'generation-parameters.yml'), ('planningInput', 'full-planning-input.yml')):
        binding = inputs.get(key)
        artifact = ws.dir / filename
        if not isinstance(binding, dict) or binding.get('path') != f'.factory/{filename}' or not artifact.is_file() or binding.get('sha256') != sha(artifact.read_bytes()):
            raise fm.MaterializationError('stale-plan', f'{filename} is missing or changed since planning')
    for entry in plan['files']['generate']:
        fm.safe_relative(entry['path'])
    from generation_context import load_mapping
    import bff_plan
    try:
        expected, parameters = bff_plan.artifacts(repo, yaml, ws.dir / 'full-planning-input.yml')
        if plan != expected or parameters != load_mapping(ws.dir / 'generation-parameters.yml'):
            raise ValueError('BFF plan/parameters differ from current authorized inputs; replan required')
    except (ValueError, KeyError, TypeError) as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    return plan, raw


def materialize(repo: Path, service: str, dry_run: bool = False) -> dict:
    import feasibility_preflight
    feasibility_preflight.enforce(repo, service)
    return _materialize_checked(repo, service, dry_run)


def _materialize_checked(repo: Path, service: str, dry_run: bool = False) -> dict:
    import full_materializer as fm
    fp, gate, wsm = fm.fp, fm.gate, fm.wsm
    repo = Path(repo).resolve()
    ws = wsm.Workspace(repo, service)
    gate.check_cleared(ws.dir, repo, service)
    plan, plan_bytes = _load_plan(ws, repo, fm)
    out_dir = repo / plan['service']['outputDirectory']
    try:
        rendered = render_project(plan, repo)
    except (KeyError, TypeError, ValueError) as error:
        raise fm.MaterializationError('invalid-plan', f'cannot render the plan ({type(error).__name__}: {error})') from error
    rendered = {p: v for p, v in rendered.items() if not fp.is_excluded(p)}
    from artifact_integrity import prepare, publish, IntegrityError
    payload = {p: text.encode('utf-8') for p, (_, text) in rendered.items()}
    try:
        to_write, unchanged = prepare(out_dir, ws.dir, payload, reject_obsolete=True)
    except fp.ProtectedFileError as error:
        raise fm.MaterializationError('protected-files', str(error), getattr(error, 'details', {})) from error
    except IntegrityError as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    rows = {p: {'sha256': fm.sha(text.encode('utf-8')), 'action': 'generated', 'componentType': ct} for p, (ct, text) in rendered.items()}
    omitted = list(plan.get('omittedBehavior', []))
    manifest = {'schemaVersion': 1, 'materializer': VERSION, 'complete': True, 'service': service,
                'inputs': {'implementationPlanSha256': fm.sha(plan_bytes), 'serviceSpecSha256': fm.sha((ws.dir / 'service-spec.yml').read_bytes()),
                           'archetypeFingerprint': plan['inputs']['archetype']['fingerprint']},
                'fileInventory': [{'path': p, **rows[p]} for p in sorted(rows)], 'unsupportedComponents': [], 'omittedBehavior': omitted,
                'payloadTreeSha256': fm.tree_hash({p: r['sha256'] for p, r in rows.items()})}
    dump = lambda v: yaml.safe_dump(v, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
    manifest_bytes = dump(manifest)
    report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'profile': PROFILE, 'status': 'complete',
              'scope': 'structure-and-contract', 'written': sorted(to_write), 'unchanged': sorted(unchanged),
              'excludedUntouched': ['src/main/resources/application*.properties'], 'omittedBehavior': omitted, 'unsupported': [],
              'payloadTreeSha256': manifest['payloadTreeSha256'], 'manifestSha256': fm.sha(manifest_bytes), 'dryRun': dry_run,
              'validation': {'maven': 'not-run', 'compilation': 'not-verified', 'checkstyle': 'unverified', 'jacoco': 'not-verified'}}
    if dry_run:
        return report
    publish(out_dir, ws.dir, payload, manifest_bytes)
    fm.write_atomic(ws.dir / 'assumptions-register.yml', dump({
        'schemaVersion': 1, 'service': service, 'materializer': VERSION, 'assumptions': [],
        'implementedBindings': [{'operationId': op['operationId'], 'evidence': op['binding'].get('evidence'),
                                 'binding': op['binding']} for op in plan['operations'] if op.get('binding')],
        'omittedBehavior': plan.get('omittedBehavior', [])}))
    fm.write_atomic(ws.dir / 'required-properties.yml', dump(required_properties(plan)))
    fm.write_atomic(ws.dir / fm.REPORT, dump(report))
    return report
