"""Deterministic Java renderers for the `rest-client-v1` variant (claro-spring-ms: REST orchestration without persistence).

Pure functions of the implementation plan and the archetype templates. Output is UTF-8, LF, with no timestamps. The generated code follows
the archetype conventions: D-013 activity logging (ActivityLogger, ConstanApi activity constants, RequestHeaders, ejecutarActividad wrapper) and the
D-014 Checkstyle rules (4-space indentation, operators at line starts, braces everywhere, no magic numbers, no star/unused imports).
"""
from __future__ import annotations

import re

import renderers as rd

STATUS = {200: 'OK', 201: 'CREATED'}
MAPPING = {'GET': 'GetMapping', 'POST': 'PostMapping', 'PUT': 'PutMapping', 'DELETE': 'DeleteMapping', 'PATCH': 'PatchMapping'}
IMPORTS = {
    'List': 'java.util.List', 'ArrayList': 'java.util.ArrayList', 'Map': 'java.util.Map', 'LinkedHashMap': 'java.util.LinkedHashMap', 'Supplier': 'java.util.function.Supplier',
    'LocalDate': 'java.time.LocalDate', 'OffsetDateTime': 'java.time.OffsetDateTime', 'DateTimeFormatter': 'java.time.format.DateTimeFormatter',
    'DateTimeParseException': 'java.time.format.DateTimeParseException', 'Clock': 'java.time.Clock', 'Duration': 'java.time.Duration', 'Instant': 'java.time.Instant',
    'ZoneOffset': 'java.time.ZoneOffset', 'ZonedDateTime': 'java.time.ZonedDateTime', 'BigDecimal': 'java.math.BigDecimal', 'SocketTimeoutException': 'java.net.SocketTimeoutException',
    'ConnectException': 'java.net.ConnectException', 'InterruptedIOException': 'java.io.InterruptedIOException',
    'Valid': 'jakarta.validation.Valid', 'NotNull': 'jakarta.validation.constraints.NotNull', 'ConstraintViolationException': 'jakarta.validation.ConstraintViolationException',
    'ConstraintViolation': 'jakarta.validation.ConstraintViolation', 'Data': 'lombok.Data', 'Slf4j': 'lombok.extern.slf4j.Slf4j', 'RequiredArgsConstructor': 'lombok.RequiredArgsConstructor',
    'JsonInclude': 'com.fasterxml.jackson.annotation.JsonInclude',
    'ResponseEntity': 'org.springframework.http.ResponseEntity', 'HttpStatus': 'org.springframework.http.HttpStatus', 'HttpHeaders': 'org.springframework.http.HttpHeaders',
    'HttpStatusCode': 'org.springframework.http.HttpStatusCode', 'HttpMethod': 'org.springframework.http.HttpMethod', 'HttpEntity': 'org.springframework.http.HttpEntity',
    'MediaType': 'org.springframework.http.MediaType',
    'RestController': 'org.springframework.web.bind.annotation.RestController', 'RestControllerAdvice': 'org.springframework.web.bind.annotation.RestControllerAdvice',
    'ExceptionHandler': 'org.springframework.web.bind.annotation.ExceptionHandler', 'RequestHeader': 'org.springframework.web.bind.annotation.RequestHeader',
    'RequestParam': 'org.springframework.web.bind.annotation.RequestParam', 'RequestBody': 'org.springframework.web.bind.annotation.RequestBody',
    'GetMapping': 'org.springframework.web.bind.annotation.GetMapping', 'PostMapping': 'org.springframework.web.bind.annotation.PostMapping',
    'PutMapping': 'org.springframework.web.bind.annotation.PutMapping', 'DeleteMapping': 'org.springframework.web.bind.annotation.DeleteMapping',
    'PatchMapping': 'org.springframework.web.bind.annotation.PatchMapping', 'Service': 'org.springframework.stereotype.Service', 'Component': 'org.springframework.stereotype.Component',
    'Configuration': 'org.springframework.context.annotation.Configuration', 'Bean': 'org.springframework.context.annotation.Bean',
    'Value': 'org.springframework.beans.factory.annotation.Value', 'Qualifier': 'org.springframework.beans.factory.annotation.Qualifier',
    'RestTemplate': 'org.springframework.web.client.RestTemplate', 'RestClientException': 'org.springframework.web.client.RestClientException',
    'HttpStatusCodeException': 'org.springframework.web.client.HttpStatusCodeException', 'ResourceAccessException': 'org.springframework.web.client.ResourceAccessException',
    'HttpClientErrorException': 'org.springframework.web.client.HttpClientErrorException',
    'RestTemplateBuilder': 'org.springframework.boot.web.client.RestTemplateBuilder', 'Nullable': 'org.springframework.lang.Nullable',
    'WebRequest': 'org.springframework.web.context.request.WebRequest', 'ServletWebRequest': 'org.springframework.web.context.request.ServletWebRequest',
    'RequestAttributes': 'org.springframework.web.context.request.RequestAttributes', 'HandlerMapping': 'org.springframework.web.servlet.HandlerMapping',
    'ResponseEntityExceptionHandler': 'org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler',
    'MissingServletRequestParameterException': 'org.springframework.web.bind.MissingServletRequestParameterException',
    'MissingRequestHeaderException': 'org.springframework.web.bind.MissingRequestHeaderException',
    'MethodArgumentNotValidException': 'org.springframework.web.bind.MethodArgumentNotValidException',
    'MethodArgumentTypeMismatchException': 'org.springframework.web.method.annotation.MethodArgumentTypeMismatchException',
    'TypeMismatchException': 'org.springframework.beans.TypeMismatchException', 'HttpMessageNotReadableException': 'org.springframework.http.converter.HttpMessageNotReadableException',
    'Operation': 'io.swagger.v3.oas.annotations.Operation', 'ApiResponse': 'io.swagger.v3.oas.annotations.responses.ApiResponse',
    'ApiResponses': 'io.swagger.v3.oas.annotations.responses.ApiResponses', 'Content': 'io.swagger.v3.oas.annotations.media.Content', 'Schema': 'io.swagger.v3.oas.annotations.media.Schema',
    'Test': 'org.junit.jupiter.api.Test', 'BeforeEach': 'org.junit.jupiter.api.BeforeEach', 'Assertions': 'org.junit.jupiter.api.Assertions', 'Mockito': 'org.mockito.Mockito',
    'MockRestServiceServer': 'org.springframework.test.web.client.MockRestServiceServer', 'MockRestRequestMatchers': 'org.springframework.test.web.client.match.MockRestRequestMatchers',
    'MockRestResponseCreators': 'org.springframework.test.web.client.response.MockRestResponseCreators', 'ExpectedCount': 'org.springframework.test.web.client.ExpectedCount',
    'MockHttpServletRequest': 'org.springframework.mock.web.MockHttpServletRequest',
}


def jstr(value) -> str:
    return rd.java_string(str(value))


def pascal(text: str) -> str:
    return ''.join(part[:1].upper() + part[1:] for part in re.split(r'[^A-Za-z0-9]+', text) if part)


def camel(text: str) -> str:
    value = pascal(text)
    return value[:1].lower() + value[1:]


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def wrap_text(text: str, width: int = 100) -> list:
    words, lines, current = ' '.join(str(text or '').split()).split(' '), [], ''
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = (current + ' ' + word).strip()
    if current:
        lines.append(current)
    return lines


def doc(indent: str, text: str) -> list:
    return [indent + '/**'] + [f'{indent} * {line}' for line in wrap_text(text)] + [indent + ' */']


def scrub(text: str) -> str:
    """Code with comments and string/char literals blanked, for import discovery."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return re.sub(r'//[^\n]*', '', text)


class Gen:
    def __init__(self, plan: dict):
        self.plan = plan
        self.base = plan['service']['package']
        self.pp = plan['service']['packagePath']
        self.names = plan['technicalProfile']['names']
        self.ops = plan['operations']
        self.integrations = plan['integrations']
        self.models = {m['name']: m for m in plan['contract']['models']}
        self.backend = {c['name']: c for c in plan['backendDtos']}
        self.errors = plan['errors']
        self.logging = plan['activityLogging']
        self.roles = self.logging['requestHeaders']['roles']
        self.rh_components = self.logging['requestHeaders']['components']
        self.caller = self.logging['callerHeaders']['components']
        self.constants = {c['constant']: c for c in self.logging['activityConstants']}
        self.pkg = {}
        for n, m in self.models.items():
            self.pkg[n] = f"{self.base}.dto.{'request' if m['role'] == 'request' else 'response'}"
        for n in self.backend:
            self.pkg[n] = f'{self.base}.client.dto'
        for key, sub in (('api', 'controller'), ('controller', 'controller.impl'), ('service', 'service'), ('serviceImpl', 'service.impl'), ('validator', 'validation'),
                         ('backendMapper', 'mapper'), ('responseMapper', 'mapper')):
            self.pkg[self.names[key]] = f'{self.base}.{sub}'
        for n in ('RequestHeaders', 'CallerHeaders'):
            self.pkg[n] = f'{self.base}.dto.request'
        for n in ('ServiceError', 'ErrorCatalog', 'ServiceOperationException', 'IntegrationException', 'GlobalExceptionHandler'):
            self.pkg[n] = f'{self.base}.exception'
        for n in ('ActivityLogger', 'ConstanApi'):
            self.pkg[n] = f'{self.base}.utils'
        for n in ('IntegrationSupport', 'CatalogCache'):
            self.pkg[n] = f'{self.base}.client'
        self.pkg['IntegrationClientConfig'] = f'{self.base}.client.config'
        for item in self.integrations.values():
            self.pkg[item['client']] = f'{self.base}.client'
        self.validation_constant = self.single_validation_constant()
        self.tx_header = self.roles['transactionId']['header']

    def single_validation_constant(self):
        found = {a['constant'] for op in self.ops for a in op['activities'] if a['role'] == 'validation'}
        if len(found) != 1:
            raise rd.Unsupported('the handler needs one shared validation activity constant')
        return next(iter(found))

    # --------------------------------------------------------------------------------------------------------- source assembly
    def source(self, pkg: str, lines: list, extra=()) -> str:
        body = '\n'.join(lines)
        used = set(re.findall(r'\b[A-Z][A-Za-z0-9]*\b', scrub(body)))
        imports = set(extra)
        for name in used:
            if name in self.pkg:
                if self.pkg[name] != pkg:
                    imports.add(f'{self.pkg[name]}.{name}')
            elif name in IMPORTS:
                imports.add(IMPORTS[name])
        out = [f'package {pkg};', '']
        ordered = sorted(imports)
        out += [f'import {i};' for i in ordered]
        if ordered:
            out.append('')
        return '\n'.join(out + lines) + '\n'

    def pkg_of(self, name: str) -> str:
        return self.pkg[name]

    # --------------------------------------------------------------------------------------------------------- helpers over the plan
    def sig_params(self, op, annotated: bool) -> list:
        out = []
        for p in op['parameters']:
            if annotated:
                ann = {'query': f"@RequestParam(name = {jstr(p['name'])}, required = {str(p['required']).lower()})",
                       'path': f"@PathVariable(name = {jstr(p['name'])})"}[p['in']]
                out.append(f"{ann} {p['javaType']} {p['variable']}")
            else:
                out.append(f"{p['javaType']} {p['variable']}")
        if op['requestClass']:
            ann = '@Valid @RequestBody ' if annotated else ''
            out.append(f"{ann}{op['requestClass']} body")
        for h in self.caller:
            if annotated:
                out.append(f"@RequestHeader(name = {jstr(h['name'])}, required = true) String {h['variable']}")
            else:
                out.append(f"String {h['variable']}")
        return out

    def business_args(self, op) -> list:
        return [p['variable'] for p in op['parameters']] + (['body'] if op['requestClass'] else [])

    def header_var(self, header_name: str) -> str:
        return next(h['variable'] for h in self.caller if h['name'] == header_name)

    # --------------------------------------------------------------------------------------------------------- contract DTOs
    def dto(self, name: str) -> str:
        model = self.models[name]
        is_request = model['role'] == 'request'
        lines = ['@Data', f'public class {name} {{', '']
        for f in model['fields']:
            if is_request:
                if f['required']:
                    lines.append('    @NotNull')
                if re.search(r'^List<[A-Z]', f['javaType']) or f['javaType'] in self.models:
                    lines.append('    @Valid')
            lines.append(f"    private {f['javaType']} {f['name']};")
            lines.append('')
        lines.pop()
        lines.append('}')
        return self.source(self.pkg[name], lines)

    def request_headers_all(self) -> str:
        components = ',\n'.join(f"        String {h['variable']}" for h in self.caller)
        lines = ['/**', ' * All request headers declared by the contract, carried to the outbound calls exactly as the Sparx INPUT tables require.', ' */',
                 'public record CallerHeaders(', components, ') {', '', '    public Map<String, String> toMap() {', '        Map<String, String> headers = new LinkedHashMap<>();']
        lines += [f"        headers.put({jstr(h['name'])}, {h['variable']});" for h in self.caller]
        lines += ['        return headers;', '    }', '}']
        return self.source(self.pkg['CallerHeaders'], lines)

    # --------------------------------------------------------------------------------------------------------- API + controller
    def api_interface(self) -> str:
        n = self.names
        lines = ['/**', ' * Contrato de los endpoints REST expuestos por el microservicio, con los parametros, encabezados y modelos definidos en el contrato OpenAPI.', ' */',
                 f"public interface {n['api']} {{", '']
        for op in self.ops:
            mapping = MAPPING[op['httpMethod']]
            consumes = ', consumes = {"application/json"}' if op['requestClass'] else ''
            lines += doc('    ', op['description'] or op['summary'] or op['operationId'])
            lines += [f"    @{mapping}(path = {jstr(op['path'])}, produces = {{\"application/json\"}}{consumes})", f"    @Operation(summary = {jstr(op['summary'] or op['operationId'])})",
                      '    @ApiResponses({']
            rows = []
            for code in op['declaredResponses']:
                schema = op['responseClass'] if code == op['successStatus'] else 'ErrorResponse'
                rows.append(f"      @ApiResponse(responseCode = \"{code}\", description = \"{self.status_text(code)}\", "
                            f"content = @Content(mediaType = \"application/json\", schema = @Schema(implementation = {schema}.class)))")
            lines += [',\n'.join(rows), '    })']
            params = self.sig_params(op, True)
            lines.append(f"    ResponseEntity<{op['responseClass']}> {op['method']}(")
            lines.append(',\n'.join('            ' + p for p in params) + ');')
            lines.append('')
        lines[-1:] = ['}']
        return self.source(self.pkg[n['api']], lines)

    @staticmethod
    def status_text(code: int) -> str:
        return {200: 'OK', 201: 'Created', 400: 'Bad request', 404: 'Not Found', 500: 'Internal server error', 503: 'Service unavailable', 504: 'Gateway Timeout'}.get(code, 'Response')

    def rh_args(self) -> str:
        return ', '.join(self.header_var(self.roles[c]['header']) for c in self.rh_components)

    def caller_args(self) -> str:
        return ', '.join(h['variable'] for h in self.caller)

    def controller(self) -> str:
        n = self.names
        lines = ['@RestController', '@Slf4j', '@RequiredArgsConstructor', f"public class {n['controller']} implements {n['api']} {{", '', f"    private final {n['service']} service;", '']
        tx_var = self.header_var(self.tx_header)
        user_var = self.header_var(self.roles['userId']['header']) if 'userId' in self.roles else None
        for op in self.ops:
            params = self.sig_params(op, False)
            lines += ['    @Override', f"    public ResponseEntity<{op['responseClass']}> {op['method']}("]
            lines += [',\n'.join('            ' + p for p in params) + ') {']
            if op['httpMethod'] != 'GET' and user_var:
                lines.append(f"        log.info(\"{op['operationId']} - transactionId: {{}}, usuario: {{}}\", {tx_var}, {user_var});")
            else:
                lines.append(f"        log.info(\"{op['operationId']} - transactionId: {{}}\", {tx_var});")
            lines += [f'        RequestHeaders headers = new RequestHeaders({self.rh_args()});', f'        CallerHeaders caller = new CallerHeaders({self.caller_args()});',
                      f"        {op['responseClass']} result = service.{op['method']}({', '.join(['headers', 'caller'] + self.business_args(op))});",
                      f"        return ResponseEntity.status(HttpStatus.{STATUS[op['successStatus']]}).body(result);", '    }', '']
        lines[-1:] = ['}']
        return self.source(self.pkg[n['controller']], lines)

    def service_interface(self) -> str:
        lines = [f"public interface {self.names['service']} {{", '']
        for op in self.ops:
            args = ['RequestHeaders headers', 'CallerHeaders caller'] + [f"{p['javaType']} {p['variable']}" for p in op['parameters']] + ([f"{op['requestClass']} body"] if op['requestClass'] else [])
            lines.append(f"    {op['responseClass']} {op['method']}({', '.join(args)});")
            lines.append('')
        lines[-1:] = ['}']
        return self.source(self.pkg[self.names['service']], lines)

    # --------------------------------------------------------------------------------------------------------- validator
    def validator(self) -> str:
        n = self.names
        lines = ['@Component', f"public class {n['validator']} {{", '']
        for op in self.ops:
            args = ['CallerHeaders caller'] + [f"{p['javaType']} {p['variable']}" for p in op['parameters']] + ([f"{op['requestClass']} body"] if op['requestClass'] else [])
            lines.append(f"    public void validate{pascal(op['operationId'])}({', '.join(args)}) {{")
            lines.append('        validateHeaders(caller);')
            for p in op['parameters']:
                if p['required']:
                    lines.append(f"        {self.require_call(p['javaType'])}({jstr(p['name'])}, {p['variable']});")
            if op['requestClass']:
                lines.append('        requireValue("body", body);')
                for f in self.models[op['requestClass']]['fields']:
                    if f['required']:
                        lines.append(f"        {self.require_call(f['javaType'])}({jstr(f['name'])}, body.get{pascal(f['name'])}());")
            step = next(a for a in op['activities'] if a['role'] == 'validation')
            if step.get('dateRange'):
                dr = step['dateRange']
                lines.append(f"        validateDateRange({jstr(dr['begin'])}, {dr['begin']}, {jstr(dr['end'])}, {dr['end']});")
            lines += ['    }', '']
        lines += ['    private void validateHeaders(CallerHeaders caller) {']
        for h in self.logging['callerHeaders']['components']:
            lines.append(f"        requireText({jstr(h['name'])}, caller.{h['variable']}());")
        lines += ['    }', '',
                  '    private void requireText(String field, String value) {', '        if (value == null || value.isBlank()) {',
                  '            throw invalid(field);', '        }', '    }', '',
                  '    private void requireValue(String field, Object value) {', '        if (value == null) {', '            throw invalid(field);', '        }', '    }', '',
                  '    private void validateDateRange(String beginField, String begin, String endField, String end) {',
                  '        OffsetDateTime from = parse(beginField, begin);', '        OffsetDateTime to = parse(endField, end);', '        if (to.isBefore(from)) {',
                  '            throw new ServiceOperationException(ServiceError.IDF126, Map.of("FIELD_NAME", endField));', '        }', '    }', '',
                  '    private OffsetDateTime parse(String field, String value) {', '        try {', '            return OffsetDateTime.parse(value);', '        } catch (DateTimeParseException ex) {',
                  '            throw invalid(field);', '        }', '    }', '',
                  '    private ServiceOperationException invalid(String field) {', '        return new ServiceOperationException(ServiceError.IDF101, Map.of("FIELD_NAME", field));', '    }', '}']
        text = '\n'.join(lines)
        if 'validateDateRange(' not in text.split('private void validateHeaders')[0]:
            lines = self.drop_date_helpers(lines)
        return self.source(self.pkg[n['validator']], lines)

    @staticmethod
    def require_call(java_type: str) -> str:
        return 'requireText' if java_type == 'String' else 'requireValue'

    @staticmethod
    def drop_date_helpers(lines: list) -> list:
        text = '\n'.join(lines)
        start = text.index('    private void validateDateRange(')
        end = text.index('    private ServiceOperationException invalid(')
        return (text[:start] + text[end:]).split('\n')

    # --------------------------------------------------------------------------------------------------------- errors
    def service_error(self) -> str:
        catalog = self.errors['catalog']
        lines = ['/** Errors declared by the OpenAPI contract: HTTP status, type and default texts (per-operation texts live in ErrorCatalog). */', 'public enum ServiceError {', '']
        rows = []
        for code in sorted(catalog):
            c = catalog[code]
            rows.append(f"    {code}(HttpStatus.{c['status']}, {jstr(c['type'])})")
        lines += [',\n'.join(rows) + ';', '', '    private final HttpStatus status;', '', '    private final String type;', '',
                  '    ServiceError(HttpStatus status, String type) {', '        this.status = status;', '        this.type = type;', '    }', '',
                  '    public HttpStatus getStatus() {', '        return status;', '    }', '', '    public String getType() {', '        return type;', '    }', '}']
        return self.source(self.pkg['ServiceError'], lines)

    def error_catalog(self) -> str:
        per = self.errors['perOperationText']
        defaults = {}
        for code, texts in per.items():
            defaults[code] = texts[next(iter(texts))]
        default_message = defaults[next(iter(defaults))]['message']
        keys = {op['operationId']: f"{op['httpMethod']} {op['path']}" for op in self.ops}
        message_rows, detail_rows = [], []
        for code in sorted(per):
            for oid, texts in per[code].items():
                key = keys[oid]
                if texts['message'] != default_message:
                    message_rows.append(f"            Map.entry({jstr(key + '|' + code)}, {jstr(texts['message'])})")
                if texts['detail'] != defaults[code]['detail']:
                    detail_rows.append(f"            Map.entry({jstr(key + '|' + code)}, {jstr(texts['detail'])})")
        lines = ['/** Message and detail texts of the contract errors. Defaults come from the first declaring operation; differing operation texts are kept verbatim. */',
                 'public final class ErrorCatalog {', '', f'    private static final String DEFAULT_MESSAGE = {jstr(default_message)};', '']
        lines += ['    private static final Map<String, String> DEFAULT_DETAILS = Map.ofEntries(']
        lines += [',\n'.join(f"            Map.entry({jstr(code)}, {jstr(defaults[code]['detail'])})" for code in sorted(defaults)) + ');', '']
        lines += ['    private static final Map<String, String> MESSAGES = Map.ofEntries(' + (')' if not message_rows else '')]
        if message_rows:
            lines.append(',\n'.join(message_rows) + ');')
        lines += ['', '    private static final Map<String, String> DETAILS = Map.ofEntries(' + (')' if not detail_rows else '')]
        if detail_rows:
            lines.append(',\n'.join(detail_rows) + ');')
        lines += ['', '    private ErrorCatalog() {', '    }', '',
                  '    public static String message(String operationKey, ServiceError error) {',
                  '        return MESSAGES.getOrDefault(operationKey + "|" + error.name(), DEFAULT_MESSAGE);', '    }', '',
                  '    public static String detail(String operationKey, ServiceError error, Map<String, String> values) {',
                  '        String text = DETAILS.getOrDefault(operationKey + "|" + error.name(), DEFAULT_DETAILS.get(error.name()));',
                  '        for (Map.Entry<String, String> value : values.entrySet()) {',
                  '            text = text.replace("[" + value.getKey() + "]", value.getValue());', '        }',
                  '        return text.replaceAll("\\\\[[A-Z_]+\\\\]", "");', '    }', '}']
        return self.source(self.pkg['ErrorCatalog'], lines)

    def service_operation_exception(self) -> str:
        lines = ['/** Application failure carrying the contract error decided by the approved behavior and the values for its detail placeholders. */',
                 'public class ServiceOperationException extends RuntimeException {', '', '    private final ServiceError error;', '', '    private final Map<String, String> values;', '',
                 '    public ServiceOperationException(ServiceError error, Map<String, String> values) {', '        super(error.name() + ' + '" " + values);',
                 '        this.error = error;', '        this.values = Map.copyOf(values);', '    }', '',
                 '    public ServiceError getError() {', '        return error;', '    }', '', '    public Map<String, String> getValues() {', '        return values;', '    }', '}']
        return self.source(self.pkg['ServiceOperationException'], lines)

    def integration_exception(self) -> str:
        lines = ['/** Failure of an outbound call: a non-accepted response, a timeout, an unavailable service or an unexpected error. */',
                 'public class IntegrationException extends RuntimeException {', '', '    public enum Kind {', '        NON_OK_RESPONSE,', '        TIMEOUT,', '        UNAVAILABLE,', '        UNEXPECTED', '    }', '',
                 '    private final Kind kind;', '', '    private final String integration;', '',
                 '    public IntegrationException(Kind kind, String integration, String message, Throwable cause) {', '        super(message, cause);', '        this.kind = kind;',
                 '        this.integration = integration;', '    }', '', '    public Kind getKind() {', '        return kind;', '    }', '', '    public String getIntegration() {', '        return integration;', '    }', '}']
        return self.source(self.pkg['IntegrationException'], lines)

    def handler(self) -> str:
        v = self.validation_constant
        tx = self.tx_header
        lines = ['@RestControllerAdvice', '@Slf4j', 'public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {', '',
                 '    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";', f'    private static final String TRANSACTION_HEADER = {jstr(tx)};', '',
                 '    @ExceptionHandler(ServiceOperationException.class)', '    public ResponseEntity<ErrorResponse> operationFailure(ServiceOperationException failure, WebRequest request) {',
                 '        return respond(failure.getError(), failure.getValues(), request);', '    }', '',
                 '    @ExceptionHandler(ConstraintViolationException.class)', '    public ResponseEntity<ErrorResponse> constraintFailure(ConstraintViolationException failure, WebRequest request) {',
                 '        String field = failure.getConstraintViolations().stream().map(ConstraintViolation::getPropertyPath).map(String::valueOf).findFirst().orElse("");',
                 '        logValidationFailure(request, failure.getMessage());', '        return respond(ServiceError.IDF101, Map.of("FIELD_NAME", field), request);', '    }', '',
                 '    @ExceptionHandler(RuntimeException.class)', '    public ResponseEntity<ErrorResponse> unexpectedFailure(RuntimeException failure, WebRequest request) {',
                 '        log.error("{} unexpected failure: {}", transactionPrefix(request), failure.getMessage());',
                 '        return respond(ServiceError.IDT3, Map.of("ERROR_DETAIL", String.valueOf(failure.getMessage())), request);', '    }', '',
                 '    @Override', '    protected ResponseEntity<Object> handleExceptionInternal(Exception ex, @Nullable Object body,',
                 '            HttpHeaders headers, HttpStatusCode status, WebRequest request) {',
                 '        ServiceError error = status.value() == HttpStatus.BAD_REQUEST.value() ? ServiceError.IDF101 : ServiceError.IDT3;',
                 '        Map<String, String> values = error == ServiceError.IDF101 ? Map.of("FIELD_NAME", fieldOf(ex)) : Map.of("ERROR_DETAIL", ex.getClass().getSimpleName());',
                 '        if (error == ServiceError.IDF101) {', '            logValidationFailure(request, ex.getClass().getSimpleName());', '        }',
                 '        return new ResponseEntity<>(body(error, values, request), headers, error.getStatus());', '    }', '',
                 '    private ResponseEntity<ErrorResponse> respond(ServiceError error, Map<String, String> values, WebRequest request) {',
                 '        return ResponseEntity.status(error.getStatus()).body(body(error, values, request));', '    }', '',
                 '    private ErrorResponse body(ServiceError error, Map<String, String> values, WebRequest request) {',
                 '        ErrorResponse response = new ErrorResponse();', '        response.setStatus(error.getStatus().name());', '        response.setCode(error.getStatus().value());',
                 '        response.setSubType(error.name());', '        response.setType(error.getType());', '        String key = operationKey(request);', '        response.setMessage(ErrorCatalog.message(key, error));',
                 '        response.setDetail(ErrorCatalog.detail(key, error, values));', '        return response;', '    }', '',
                 '    private String operationKey(WebRequest request) {', '        if (request instanceof ServletWebRequest servlet) {',
                 '            Object pattern = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, RequestAttributes.SCOPE_REQUEST);',
                 '            String path = pattern != null ? String.valueOf(pattern) : servlet.getRequest().getRequestURI();', '            return servlet.getRequest().getMethod() + " " + path;', '        }',
                 '        return "";', '    }', '',
                 '    private String transactionPrefix(WebRequest request) {', '        String tx = request.getHeader(TRANSACTION_HEADER);', '        return tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;', '    }', '',
                 '    private void logValidationFailure(WebRequest request, String reason) {', '        String menTran = transactionPrefix(request);',
                 f'        ActivityLogger.inicioActividad(log, menTran, ConstanApi.{v});',
                 f'        log.error("{{}} ERROR [{{}}] code={{}} detail={{}}", menTran, ConstanApi.{v}, HttpStatus.BAD_REQUEST.value(), reason);',
                 f'        ActivityLogger.finActividad(log, menTran, ConstanApi.{v});', '    }', '',
                 '    private String fieldOf(Exception ex) {', '        String field = "";',
                 '        if (ex instanceof MissingServletRequestParameterException missing) {', '            field = missing.getParameterName();',
                 '        } else if (ex instanceof MissingRequestHeaderException header) {', '            field = header.getHeaderName();',
                 '        } else if (ex instanceof MethodArgumentNotValidException invalid && invalid.getBindingResult().getFieldError() != null) {',
                 '            field = invalid.getBindingResult().getFieldError().getField();', '        } else if (ex instanceof MethodArgumentTypeMismatchException mismatch) {',
                 '            field = mismatch.getName();', '        } else if (ex instanceof TypeMismatchException mismatch) {', '            field = String.valueOf(mismatch.getPropertyName());',
                 '        } else if (ex instanceof HttpMessageNotReadableException) {', '            field = "body";', '        }', '        return field;', '    }', '}']
        return self.source(self.pkg['GlobalExceptionHandler'], lines)

    # --------------------------------------------------------------------------------------------------------- backend DTOs, mappers
    def backend_dto(self, name: str) -> str:
        c = self.backend[name]
        request = name.endswith('Request') or name.endswith('ListaCuotasItem') and any(name == f['javaType'][5:-1] for r in self.backend.values() if r['name'].endswith('Request') for f in r['fields'])
        lines = (['@JsonInclude(JsonInclude.Include.NON_NULL)'] if request else []) + ['@Data', f'public class {name} {{', '']
        for f in c['fields']:
            lines += [f"    private {f['javaType']} {f['name']};", '']
        lines[-1:] = ['}']
        return self.source(self.pkg[name], lines)

    @staticmethod
    def conversion(expr: str, kind: str) -> str:
        if kind == 'identity':
            return expr
        if kind == 'valueOf':
            return f'{expr} != null ? String.valueOf({expr}) : null'
        if kind == 'toString':
            return f'{expr} != null ? {expr}.toString() : null'
        raise rd.Unsupported(f'unsupported conversion {kind}')

    def backend_mapper(self) -> str:
        n = self.names
        lines = ['@Component', f"public class {n['backendMapper']} {{", '']
        for op in self.ops:
            for step in op['activities']:
                body = step.get('body')
                if not body:
                    continue
                cls = body['class']
                lookup = [a for a in body['assignments'] if a['kind'] == 'catalog-lookup']
                args = [f"{op['requestClass']} source"] + [f"String {a['to']}" for a in lookup]
                lines += [f"    public {cls} to{cls}({', '.join(args)}) {{", f'        {cls} target = new {cls}();']
                for a in body['assignments']:
                    setter = f"target.set{pascal(a['to'])}"
                    if a['kind'] == 'catalog-lookup':
                        lines.append(f"        {setter}({a['to']});")
                    else:
                        lines.append(f"        {setter}({self.conversion(f'source.get{pascal(a['from'])}()', a['conversion'])});")
                for group in body['lists']:
                    item_cls = self.backend_list_class(cls, group['to'])
                    lines += [f"        if (source.get{pascal(group['sourceList'])}() != null) {{", f"            List<{item_cls}> items = new ArrayList<>();",
                              f"            for ({group['sourceClass']} item : source.get{pascal(group['sourceList'])}()) {{", f'                items.add(to{item_cls}(item));', '            }',
                              f"            target.set{pascal(group['to'])}(items);", '        }']
                lines += ['        return target;', '    }', '']
                for group in body['lists']:
                    item_cls = self.backend_list_class(cls, group['to'])
                    lines += [f"    private {item_cls} to{item_cls}({group['sourceClass']} source) {{", f'        {item_cls} target = new {item_cls}();']
                    for f in group['fields']:
                        lines.append(f"        target.set{pascal(f['to'])}({self.conversion(f'source.get{pascal(f['from'])}()', f['conversion'])});")
                    lines += ['        return target;', '    }', '']
        lines[-1:] = ['}']
        return self.source(self.pkg[n['backendMapper']], lines)

    def backend_list_class(self, cls: str, field: str) -> str:
        type_ = next(f['javaType'] for f in self.backend[cls]['fields'] if f['name'] == field)
        return type_[5:-1]

    def response_mapper(self) -> str:
        n = self.names
        lines = ['/**', ' * Backend-to-contract response mapping. Sparx documents the backend OUTPUT rows without any destination, so the mapping is not specified', ' * and is NOT approximated: every method fails explicitly until the specification defines it (see omittedBehavior in the plan).',
                 ' */', '@Component', f"public class {n['responseMapper']} {{", '']
        for op in self.ops:
            primary = next(a for a in op['activities'] if a.get('primary'))
            lines += [f"    public {op['responseClass']} to{op['responseClass']}({primary['responseClass']} backend) {{",
                      f"        throw new UnsupportedOperationException({jstr('Response mapping not specified by Sparx for ' + op['operationId'] + '; see omittedBehavior of the plan')});", '    }', '']
        lines[-1:] = ['}']
        return self.source(self.pkg[n['responseMapper']], lines)

    # --------------------------------------------------------------------------------------------------------- service implementation
    def count_lines(self, var, cls, segments, depth, indent) -> list:
        seg = segments[0]
        name, array = seg.removesuffix('[]'), seg.endswith('[]')
        getter = f'{var}.get{pascal(name)}()'
        field_type = next(f['javaType'] for f in self.backend[cls]['fields'] if f['name'] == name)
        if len(segments) == 1:
            if not array:
                raise rd.Unsupported('the list named by the outcome rule must be an array')
            return [f'{indent}if ({getter} != null) {{', f'{indent}    total += {getter}.size();', f'{indent}}}']
        if array:
            item_cls, item = field_type[5:-1], f'item{depth}'
            inner = self.count_lines(item, item_cls, segments[1:], depth + 1, indent + '            ')
            return [f'{indent}if ({getter} != null) {{', f'{indent}    for ({item_cls} {item} : {getter}) {{', f'{indent}        if ({item} != null) {{'] + inner + [f'{indent}        }}', f'{indent}    }}', f'{indent}}}']
        child = f'child{depth}'
        inner = self.count_lines(child, field_type, segments[1:], depth + 1, indent + '    ')
        return [f'{indent}{field_type} {child} = {getter};', f'{indent}if ({child} != null) {{'] + inner + [f'{indent}}}']

    def service_impl(self) -> str:
        n = self.names
        used_integrations = sorted({s['integration'] for op in self.ops for s in op['activities'] if s['role'] == 'remote-call'})
        clients = [(self.integrations[i]['client'], lower_first(self.integrations[i]['client'])) for i in used_integrations]
        lines = ['/** Activity-logged service implementation; logging is instrumentation only and never changes statuses or return values. */', '@Service', '@RequiredArgsConstructor', '@Slf4j',
                 f"public class {n['serviceImpl']} implements {n['service']} {{", '', '    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";',
                 '    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";', '    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";',
                 '    private static final String SUCCESS_CODE = "0";', '',
                 f"    private final {n['validator']} validator;", '', f"    private final {n['backendMapper']} backendMapper;", '', f"    private final {n['responseMapper']} responseMapper;", '']
        for cls, var in clients:
            lines += [f'    private final {cls} {var};', '']
        for op in self.ops:
            lines += self.operation_method(op)
        for op in self.ops:
            lines += self.entry_log_method(op)
        for op in self.ops:
            primary = next(a for a in op['activities'] if a.get('primary'))
            lines += self.outcome_methods(op, primary)
        lines += self.service_helpers()
        lines[-1:] = ['}']
        return self.source(self.pkg[n['serviceImpl']], lines)

    def client_var(self, integration: str) -> str:
        return lower_first(self.integrations[integration]['client'])

    def operation_method(self, op) -> list:
        args = ['RequestHeaders headers', 'CallerHeaders caller'] + [f"{p['javaType']} {p['variable']}" for p in op['parameters']] + ([f"{op['requestClass']} body"] if op['requestClass'] else [])
        lines = ['    @Override', f"    public {op['responseClass']} {op['method']}({', '.join(args)}) {{", '        String tx = headers != null ? headers.transactionId() : null;',
                 '        String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;', '']
        lookups = {}
        for step in op['activities']:
            c = step['constant']
            label = self.constants[c]['value'].replace('_', ' ')
            if step['role'] == 'validation':
                call = ', '.join(['headers'] + [p['variable'] for p in op['parameters']])
                vargs = ', '.join(['caller'] + self.business_args(op))
                lines += [f"        // ACTIVIDAD {step['order']}: {label} / LOG DE ENTRADA", '        ejecutarActividad(', '                menTran,', f'                ConstanApi.{c},', '                () -> {',
                          f"                    log{pascal(op['operationId'])}({call});"]
                if op['requestClass']:
                    lines.append(f"                    ActivityLogger.logContenido(log, \"{op['operationId']} body: {{}}\", body, {op['requestClass']}.class);")
                lines += [f"                    validator.validate{pascal(op['operationId'])}({vargs});", '                    return Boolean.TRUE;', '                }', '        );', '']
                continue
            client = self.client_var(step['integration'])
            tm, er = f"ConstanApi.LOG_TIMEOUT_{c}", f"ConstanApi.LOG_ERROR_INTEGRACION_{c}"
            error = step['outcome']['otherwiseError']
            if step['primary']:
                call_args = self.primary_call_args(op, step, lookups)
                lines += [f'        // ACTIVIDAD {step["order"]}: {label}', f"        {step['responseClass']} backend = ejecutarActividad(", '                menTran,', f'                ConstanApi.{c},',
                          f"                () -> evaluate{pascal(op['operationId'])}(", '                        menTran,', f'                        ConstanApi.{c},',
                          f"                        consultar(menTran, {tm}, {er}, ServiceError.{error},", f"                                () -> {client}.{step['clientMethod']}({call_args}))));",
                          f"        return responseMapper.to{op['responseClass']}(backend);"]
            elif step['lookupConsumers']:
                consumer = step['lookupConsumers'][0]
                lines += [f'        // ACTIVIDAD {step["order"]}: {label}', f"        {step['responseClass']} catalog{step['order']} = ejecutarActividad(", '                menTran,', f'                ConstanApi.{c},',
                          f"                () -> consultar(menTran, {tm}, {er}, ServiceError.{error},", f"                        () -> {client}.{step['clientMethod']}(caller)));",
                          f"        String {consumer['to']} = buscarTipoDocumento(catalog{step['order']}, {self.match_expr(op, consumer['matchField'])});"]
                lookups[step['order']] = consumer['to']
            else:
                lines += [f'        // ACTIVIDAD {step["order"]}: {label}', '        ejecutarActividad(', '                menTran,', f'                ConstanApi.{c},',
                          f"                () -> consultar(menTran, {tm}, {er}, ServiceError.{error},", f"                        () -> {client}.{step['clientMethod']}(caller)));"]
            lines.append('')
        if lines[-1] == '':
            lines.pop()
        lines += ['    }', '']
        return lines

    def match_expr(self, op, field: str) -> str:
        if any(p['variable'] == field for p in op['parameters']):
            return field
        if op['requestClass'] and any(f['name'] == field for f in self.models[op['requestClass']]['fields']):
            return f'body.get{pascal(field)}()'
        raise rd.Unsupported(f"{op['operationId']}: the catalog match field {field!r} is neither a parameter nor a request field")

    def primary_call_args(self, op, step, lookups) -> str:
        args = ['caller']
        if step['body']:
            lookup_args = [lookups[a['activityOrder']] for a in step['body']['assignments'] if a['kind'] == 'catalog-lookup']
            args.append(f"backendMapper.to{step['body']['class']}({', '.join(['body'] + lookup_args)})")
        for q in step['query']:
            if q['kind'] == 'catalog-lookup':
                args.append(lookups[q['activityOrder']])
            else:
                args.append(self.conversion_inline(q['variable'], q['conversion']))
        return ', '.join(args)

    @staticmethod
    def conversion_inline(var: str, kind: str) -> str:
        return {'identity': var, 'valueOf': f'String.valueOf({var})', 'toString': f'{var}.toString()'}[kind]

    def entry_log_method(self, op) -> list:
        args = ['RequestHeaders h'] + [f"{p['javaType']} {p['variable']}" for p in op['parameters']]
        names = {'applicationName': 'h != null ? h.applicationName() : null', 'transactionId': 'h != null ? h.transactionId() : null', 'userId': 'h != null ? h.userId() : null'}
        parts = [f'{r}={{}}' for r in ('applicationName', 'transactionId', 'userId') if r in self.roles] + [f"{p['variable']}={{}}" for p in op['parameters']]
        values = [names[r] for r in ('applicationName', 'transactionId', 'userId') if r in self.roles] + [p['variable'] for p in op['parameters']]
        lines = [f"    private void log{pascal(op['operationId'])}({', '.join(args)}) {{", '        log.info(',
                 f"                \"{op['operationId']} {', '.join(parts)}\",", ',\n'.join('                ' + v for v in values), '        );', '    }', '']
        return lines

    def outcome_methods(self, op, step) -> list:
        o = step['outcome']
        cls = step['responseClass']
        name = pascal(op['operationId'])
        lines = [f'    private {cls} evaluate{name}(String menTran, String actividad, {cls} response) {{', '        ResponseAudit audit = response != null ? response.getResponseAudit() : null;',
                 '        if (audit == null || !SUCCESS_CODE.equals(audit.getCodigoRespuesta())) {', f"            throw negocio(menTran, actividad, ServiceError.{o['otherwiseError']}, mensaje(audit));", '        }']
        if o.get('emptyListError'):
            lines += [f'        if (count{name}(response) == 0) {{', f"            throw negocio(menTran, actividad, ServiceError.{o['emptyListError']}, mensaje(audit));", '        }']
        lines += ['        return response;', '    }', '']
        if o.get('emptyListError'):
            lines += [f'    private static int count{name}({cls} response) {{', '        int total = 0;'] + self.count_lines('response', cls, o['listPath'], 0, '        ') + ['        return total;', '    }', '']
        return lines

    def service_helpers(self) -> list:
        return ['    private <T> T consultar(String menTran, String logTimeout, String logError, ServiceError otherwise, Supplier<T> llamada) {', '        try {',
                '            return llamada.get();', '', '        } catch (IntegrationException e) {', '            return fallar(menTran, logTimeout, logError, otherwise, e);', '        }', '    }', '',
                '    private <T> T fallar(String menTran, String logTimeout, String logError, ServiceError otherwise, IntegrationException e) {',
                '        Map<String, String> values = Map.of("SERVICE_NAME", e.getIntegration(), "ERROR_DETAIL", String.valueOf(e.getMessage()), "OUTPUT_DETAIL", String.valueOf(e.getMessage()));',
                '        ServiceError error = switch (e.getKind()) {', '            case NON_OK_RESPONSE -> otherwise;', '            case TIMEOUT -> ServiceError.IDT1;', '            case UNAVAILABLE -> ServiceError.IDT2;',
                '            default -> ServiceError.IDT3;', '        };', '        String logMessage = e.getKind() == IntegrationException.Kind.TIMEOUT ? logTimeout : logError;',
                '        log.error(ERROR_TECHNICAL_PATTERN, menTran, logMessage, e.getMessage());', '        throw new ServiceOperationException(error, values);', '    }', '',
                '    private String buscarTipoDocumento(GetIdentificationTypesResponse catalog, Integer documentCodeId) {',
                '        if (catalog != null && catalog.getData() != null) {', '            for (GetIdentificationTypesDataItem item : catalog.getData()) {',
                '                if (item != null && documentCodeId != null && documentCodeId.equals(item.getId()) && item.getName() != null) {', '                    return item.getName();',
                '                }', '            }', '        }', '        throw new ServiceOperationException(ServiceError.IDF101, Map.of("FIELD_NAME", "documentCodeId"));', '    }', '',
                '    private ServiceOperationException negocio(String menTran, String actividad, ServiceError error, String outputDetail) {',
                '        log.error(ERROR_BUSINESS_PATTERN, menTran, actividad, error.getStatus().value(), outputDetail);',
                '        return new ServiceOperationException(error, Map.of("OUTPUT_DETAIL", outputDetail));', '    }', '',
                '    private String mensaje(ResponseAudit audit) {', '        return audit != null && audit.getMensajeRespuesta() != null ? audit.getMensajeRespuesta() : "";', '    }', '',
                '    private <T> T ejecutarActividad(String menTran, String actividad, Supplier<T> accion) {', '        try {', '            ActivityLogger.inicioActividad(log, menTran, actividad);',
                '            T result = accion.get();', '            ActivityLogger.finActividad(log, menTran, actividad);', '            return result;', '',
                '        } catch (ServiceOperationException ex) {', '            log.error("{} ERROR [{}] message={}", menTran, actividad, ex.getMessage());', '            throw ex;', '',
                '        } catch (Exception ex) {', '            log.error("{} ERROR [{}] unexpected exception={}", menTran, actividad, ex.getMessage());', '            throw ex;', '        }', '    }', '']
