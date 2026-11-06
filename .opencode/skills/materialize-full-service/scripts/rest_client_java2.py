"""Outbound REST client renderers and generated tests for the `rest-client-v1` variant (see rest_client_java.py)."""
from __future__ import annotations

import re

import renderers as rd
from rest_client_java import Gen, IMPORTS, jstr, lower_first, pascal


def prop(prefix: str, suffix: str) -> str:
    return '${' + f'{prefix}.{suffix}' + '}'


def config(g: Gen) -> str:
    lines = ['/** Outbound REST clients: one RestTemplate per integration with its base URL and timeouts (milliseconds) from environment-defined properties. */', '@Configuration',
             'public class IntegrationClientConfig {', '']
    for name, item in sorted(g.integrations.items()):
        bean = lower_first(pascal(name)) + 'RestTemplate'
        p = item['propertyPrefix']
        lines += [f'    @Bean({jstr(bean)})', f'    public RestTemplate {bean}(RestTemplateBuilder builder,', f"            @Value({jstr(prop(p, 'base-url'))}) String baseUrl,",
                  f"            @Value({jstr(prop(p, 'connect-timeout'))}) long connectTimeout,", f"            @Value({jstr(prop(p, 'read-timeout'))}) long readTimeout) {{",
                  '        return builder', '                .rootUri(baseUrl)', '                .connectTimeout(Duration.ofMillis(connectTimeout))', '                .readTimeout(Duration.ofMillis(readTimeout))',
                  '                .build();', '    }', '']
    lines += ['    @Bean', '    public Clock clock() {', '        return Clock.systemDefaultZone();', '    }', '}']
    return g.source(g.pkg['IntegrationClientConfig'], lines)


def support(g: Gen) -> str:
    lines = ['/** Shared outbound call support: executes a call and classifies its failures as IntegrationException kinds. */', 'public final class IntegrationSupport {', '',
             '    private static final int HTTP_OK = 200;', '', '    private IntegrationSupport() {', '    }', '',
             '    public static <T> T execute(String integration, Supplier<T> call) {', '        try {', '            return call.get();', '',
             '        } catch (IntegrationException ex) {', '            throw ex;', '',
             '        } catch (HttpStatusCodeException ex) {',
             '            throw new IntegrationException(IntegrationException.Kind.NON_OK_RESPONSE, integration, "HTTP " + ex.getStatusCode().value() + " " + ex.getStatusText(), ex);', '',
             '        } catch (ResourceAccessException ex) {',
             '            boolean timeout = ex.getCause() instanceof InterruptedIOException;',
             '            IntegrationException.Kind kind = timeout ? IntegrationException.Kind.TIMEOUT : IntegrationException.Kind.UNAVAILABLE;',
             '            throw new IntegrationException(kind, integration, ex.getMessage(), ex);', '',
             '        } catch (RestClientException ex) {', '            throw new IntegrationException(IntegrationException.Kind.UNEXPECTED, integration, ex.getMessage(), ex);', '        }', '    }', '',
             '    public static <T> T exchange(RestTemplate restTemplate, String url, HttpMethod method, HttpHeaders headers, Object body, Class<T> type, Map<String, Object> variables, Integer expectedStatus) {',
             '        ResponseEntity<T> response = restTemplate.exchange(url, method, new HttpEntity<>(body, headers), type, variables);',
             '        if (expectedStatus != null && response.getStatusCode().value() != expectedStatus) {',
             '            throw new IntegrationException(IntegrationException.Kind.NON_OK_RESPONSE, url, "HTTP " + response.getStatusCode().value(), null);', '        }',
             '        return response.getBody();', '    }', '',
             '    public static int okStatus() {', '        return HTTP_OK;', '    }', '}']
    return g.source(g.pkg['IntegrationSupport'], lines, extra=['java.io.InterruptedIOException'])


def cache(g: Gen) -> str:
    lines = ['/** Time-to-live holder for catalog responses (Sparx propRefreshCache, milliseconds). */', 'public class CatalogCache<T> {', '', '    private final Clock clock;', '', '    private final Duration ttl;', '',
             '    private T value;', '', '    private Instant loadedAt;', '', '    public CatalogCache(Clock clock, long refreshMillis) {', '        this.clock = clock;', '        this.ttl = Duration.ofMillis(refreshMillis);', '    }', '',
             '    public synchronized T get(Supplier<T> loader) {', '        Instant now = clock.instant();', '        if (value == null || loadedAt == null || now.isAfter(loadedAt.plus(ttl))) {',
             '            value = loader.get();', '            loadedAt = now;', '        }', '        return value;', '    }', '}']
    return g.source(g.pkg['CatalogCache'], lines)


def client(g: Gen, name: str) -> str:
    item = g.integrations[name]
    cls, p = item['client'], item['propertyPrefix']
    steps = [s for op in g.ops for s in op['activities'] if s['role'] == 'remote-call' and s['integration'] == name]
    methods = {}
    for s in steps:
        methods.setdefault(s['clientMethod'], s)
    cached = item['cache'] is not None
    needs_clock = cached or any(any(m['kind'] == 'timestamp' for m in s['headers'].get('mappings', [])) for s in methods.values())
    lines = ['@Component', f'public class {cls} {{', '', f'    private static final String INTEGRATION = {jstr(name)};', '']
    for mname, s in sorted(methods.items()):
        lines.append(f"    private static final String {const(mname)}_PATH = {jstr(s['path'])};")
        if s['query']:
            query = '&'.join(f"{q['to']}={{{q['to']}}}" for q in s['query'])
            lines.append(f"    private static final String {const(mname)}_URL = {const(mname)}_PATH + {jstr('?' + query)};")
    uses_timestamp = any(m['kind'] == 'timestamp' for s in methods.values() for m in s['headers'].get('mappings', []))
    consts = {m['to']: m['value'] for s in methods.values() for m in s['headers'].get('mappings', []) if m['kind'] == 'constant'}
    if uses_timestamp:
        pattern = next(m['pattern'] for s in methods.values() for m in s['headers'].get('mappings', []) if m['kind'] == 'timestamp')
        lines.append(f'    private static final DateTimeFormatter TIMESTAMP_FORMAT = DateTimeFormatter.ofPattern({jstr(pattern)});')
    for header, value in sorted(consts.items()):
        lines.append(f'    private static final String {const(header)}_VALUE = {jstr(value)};')
    lines += ['', '    private final RestTemplate restTemplate;', '']
    if needs_clock:
        lines += ['    private final Clock clock;', '']
    if cached:
        for mname, s in sorted(methods.items()):
            lines += [f"    private final CatalogCache<{s['responseClass']}> {mname}Cache;", '']
    ctor = [f"@Qualifier({jstr(lower_first(pascal(name)) + 'RestTemplate')}) RestTemplate restTemplate"]
    if needs_clock:
        ctor.append('Clock clock')
    if cached:
        ctor.append(f"@Value({jstr('${' + p + '.refresh-cache-ms:' + str(item['cache']['refreshMs']) + '}')}) long refreshCacheMs")
    lines += [f'    public {cls}(' + ',\n            '.join(ctor) + ') {', '        this.restTemplate = restTemplate;']
    if needs_clock:
        lines.append('        this.clock = clock;')
    if cached:
        for mname, s in sorted(methods.items()):
            lines.append(f"        this.{mname}Cache = new CatalogCache<>(clock, refreshCacheMs);")
    lines += ['    }', '']
    for mname, s in sorted(methods.items()):
        lines += method_text(g, name, mname, s, cached)
    lines += header_method(methods, consts, uses_timestamp)
    lines[-1:] = ['}']
    return g.source(g.pkg[cls], lines)


def const(method: str) -> str:
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', method).upper()


def method_text(g: Gen, name: str, mname: str, s: dict, cached: bool) -> list:
    args = ['CallerHeaders caller']
    variables = []
    if s['body']:
        args.append(f"{s['body']['class']} body")
    for q in s['query']:
        args.append(f"{q['backendType']} {q['to']}")
        variables.append(q['to'])
    template = f"{const(mname)}_URL" if variables else f"{const(mname)}_PATH"
    expected = 'IntegrationSupport.okStatus()' if s['outcome']['kind'] == 'http-status-200' else 'null'
    body = 'body' if s['body'] else 'null'
    lines = [f"    public {s['responseClass']} {mname}({', '.join(args)}) {{"]
    if variables:
        lines.append('        Map<String, Object> variables = new LinkedHashMap<>();')
        lines += [f'        variables.put({jstr(v)}, {v});' for v in variables]
    vars_arg = 'variables' if variables else 'Map.of()'
    call = ['IntegrationSupport.execute(INTEGRATION, () -> IntegrationSupport.exchange(', f"        restTemplate, {template}, HttpMethod.{s['httpMethod']}, headers(caller), {body}, {s['responseClass']}.class, {vars_arg}, {expected}))"]
    if cached and s['outcome']['kind'] == 'http-status-200':
        lines += [f'        return {mname}Cache.get(() -> ' + call[0], '                ' + call[1] + ');']
    else:
        lines += ['        return ' + call[0], '                ' + call[1] + ';']
    lines += ['    }', '']
    return lines


def header_method(methods: dict, consts: dict, uses_timestamp: bool) -> list:
    modes = {json_key(s['headers']) for s in methods.values()}
    if len(modes) != 1:
        raise rd.Unsupported('every method of one integration must use the same header mapping')
    spec = next(iter(methods.values()))['headers']
    lines = ['    private HttpHeaders headers(CallerHeaders caller) {', '        HttpHeaders headers = new HttpHeaders();', '        Map<String, String> source = caller.toMap();']
    if spec['mode'] == 'forward-all-request-headers':
        lines.append('        source.forEach(headers::set);')
    else:
        for m in spec['mappings']:
            if m['kind'] == 'request-header':
                lines.append(f"        headers.set({jstr(m['to'])}, source.get({jstr(m['from'])}));")
            elif m['kind'] == 'timestamp':
                lines.append(f"        headers.set({jstr(m['to'])}, ZonedDateTime.now(clock).format(TIMESTAMP_FORMAT));")
            elif m['kind'] == 'constant':
                lines.append(f"        headers.set({jstr(m['to'])}, {const(m['to'])}_VALUE);")
    lines += ['        return headers;', '    }', '']
    return lines


def json_key(value) -> str:
    return repr(sorted(value.items(), key=lambda kv: kv[0]))


# ------------------------------------------------------------------------------------------------------------------ tests
def sample(java_type: str, g: Gen) -> str:
    simple = {'String': '"x"', 'Integer': '1', 'Long': '1L', 'Double': 'Double.valueOf(1)', 'Boolean': 'Boolean.TRUE', 'BigDecimal': 'BigDecimal.ONE', 'LocalDate': 'LocalDate.EPOCH',
              'OffsetDateTime': 'OffsetDateTime.MAX'}
    if java_type in simple:
        return simple[java_type]
    if java_type.startswith('List<'):
        return 'new ArrayList<>()'
    return f'new {java_type}()'


def param_sample(p: dict) -> str:
    if p['javaType'] == 'String' and p.get('declaredType') == 'OffsetDateTime':
        return jstr('2026-10-15T19:00:00-05:00')
    return sample(p['javaType'], None)


def body_setup(g: Gen, op: dict) -> list:
    if not op['requestClass']:
        return []
    cls = op['requestClass']
    lines = [f'        {cls} body = new {cls}();']
    for f in g.models[cls]['fields']:
        if f['required']:
            lines.append(f"        body.set{pascal(f['name'])}({sample(f['javaType'], g)});")
    return lines


def op_args(g: Gen, op: dict) -> str:
    return ', '.join(['headers', 'caller'] + [param_sample(p) if p['in'] != 'header' else p['variable'] for p in op['parameters']] + (['body'] if op['requestClass'] else []))


def success_response(g: Gen, cls: str, listpath: list, var: str) -> list:
    """Statements building a backend response with success code and one element in the list named by listpath."""
    lines = [f'        {cls} {var} = new {cls}();', '        ResponseAudit audit = new ResponseAudit();', '        audit.setCodigoRespuesta("0");', f'        {var}.setResponseAudit(audit);']
    if not listpath:
        return lines
    current_cls, current_var = cls, var
    for depth, seg in enumerate(listpath):
        name, array = seg.removesuffix('[]'), seg.endswith('[]')
        ftype = next(f['javaType'] for f in g.backend[current_cls]['fields'] if f['name'] == name)
        if array:
            item_cls = ftype[5:-1]
            lines += [f'        List<{item_cls}> list{depth} = new ArrayList<>();', f'        {item_cls} item{depth} = new {item_cls}();', f'        list{depth}.add(item{depth});',
                      f'        {current_var}.set{pascal(name)}(list{depth});']
            current_cls, current_var = item_cls, f'item{depth}'
        else:
            lines += [f'        {ftype} child{depth} = new {ftype}();', f'        {current_var}.set{pascal(name)}(child{depth});']
            current_cls, current_var = ftype, f'child{depth}'
    return lines


def service_test(g: Gen) -> str:
    n = g.names
    used = sorted({s['integration'] for op in g.ops for s in op['activities'] if s['role'] == 'remote-call'})
    clients = [(g.integrations[i]['client'], lower_first(g.integrations[i]['client'])) for i in used]
    lines = [f"class {n['serviceImpl']}Test {{", '']
    for cls, var in clients:
        lines += [f'    private {cls} {var};', '']
    lines += [f"    private {n['serviceImpl']} service;", '', '    private RequestHeaders headers;', '', '    private CallerHeaders caller;', '', '    @BeforeEach', '    void setUp() {']
    for cls, var in clients:
        lines.append(f'        {var} = Mockito.mock({cls}.class);')
    ctor = [f"new {n['validator']}()", f"new {n['backendMapper']}()", f"new {n['responseMapper']}()"] + [var for _, var in clients]
    lines += [f"        service = new {n['serviceImpl']}({', '.join(ctor)});", f"        headers = new RequestHeaders({', '.join(chr(34) + 'x' + chr(34) for _ in g.rh_components)});",
              f"        caller = new CallerHeaders({', '.join(chr(34) + 'x' + chr(34) for _ in g.caller)});", '    }', '']
    for op in g.ops:
        lines += op_tests(g, op)
    lines[-1:] = ['}']
    return g.source(g.pkg[n['serviceImpl']], lines)


def op_tests(g: Gen, op: dict) -> list:
    oid, m = op['operationId'], op['method']
    steps = [s for s in op['activities'] if s['role'] == 'remote-call']
    primary = next(s for s in steps if s['primary'])
    catalog = [s for s in steps if not s['primary'] and s['lookupConsumers']]
    lookups_consumer = catalog[0]['lookupConsumers'][0] if catalog else None
    lines = []
    call = f'service.{m}({op_args(g, op)})'

    def setup_common():
        out = body_setup(g, op)
        for s in steps:
            if s['primary']:
                continue
            cvar = g.client_var(s['integration'])
            if s['lookupConsumers']:
                out += ['        GetIdentificationTypesDataItem type = new GetIdentificationTypesDataItem();', '        type.setId(1);', '        type.setName("x");',
                        '        GetIdentificationTypesResponse types = new GetIdentificationTypesResponse();', '        types.setData(List.of(type));',
                        f"        Mockito.when({cvar}.{s['clientMethod']}(caller)).thenReturn(types);"]
            else:
                out += [f"        Mockito.when({cvar}.{s['clientMethod']}(caller)).thenReturn(new {s['responseClass']}());"]
        return out

    def primary_stub(value_expr=None, throws=None):
        cvar = g.client_var(primary['integration'])
        matcher = ', '.join(['Mockito.eq(caller)'] + (['Mockito.any()'] if primary['body'] else []) + ['Mockito.any()' for q in primary['query']])
        if throws:
            return [f"        Mockito.when({cvar}.{primary['clientMethod']}({matcher})).thenThrow({throws});"]
        return [f"        Mockito.when({cvar}.{primary['clientMethod']}({matcher})).thenReturn({value_expr});"]

    lines += ['    @Test', f'    void {m}RejectsBlankHeader() {{']
    lines += body_setup(g, op)
    lines.append('        CallerHeaders blank = new CallerHeaders(' + ', '.join('" "' for _ in g.caller) + ');')
    blank_args = op_args(g, op).replace('caller', 'blank', 1)
    lines += [f'        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> service.{m}({blank_args}));', '        Assertions.assertEquals(ServiceError.IDF101, error.getError());', '    }', '']
    for s in steps:
        if s['primary']:
            continue
        if not s['lookupConsumers'] and not s['outcome']:
            continue
        cvar = g.client_var(s['integration'])
        err = s['outcome']['otherwiseError']
        lines += ['    @Test', f"    void {m}MapsFailureOfStep{s['order']}() {{"] + body_setup(g, op)
        for prev in steps:
            if prev['order'] < s['order'] and not prev['primary']:
                pv = g.client_var(prev['integration'])
                lines.append(f"        Mockito.when({pv}.{prev['clientMethod']}(caller)).thenReturn(new {prev['responseClass']}());")
        lines += [f"        Mockito.when({cvar}.{s['clientMethod']}(caller)).thenThrow(new IntegrationException(IntegrationException.Kind.NON_OK_RESPONSE, \"{s['integration']}\", \"HTTP 500\", null));",
                  f'        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> {call});', f'        Assertions.assertEquals(ServiceError.{err}, error.getError());', '    }', '']
    lines += ['    @Test', f'    void {m}MapsTimeoutAndUnavailableOfBackend() {{'] + setup_common()
    lines += primary_stub(throws='new IntegrationException(IntegrationException.Kind.TIMEOUT, "backend", "timeout", null)')
    lines += [f'        ServiceOperationException timeout = Assertions.assertThrows(ServiceOperationException.class, () -> {call});', '        Assertions.assertEquals(ServiceError.IDT1, timeout.getError());']
    lines += primary_stub(throws='new IntegrationException(IntegrationException.Kind.UNAVAILABLE, "backend", "down", null)')
    lines += [f'        ServiceOperationException unavailable = Assertions.assertThrows(ServiceOperationException.class, () -> {call});', '        Assertions.assertEquals(ServiceError.IDT2, unavailable.getError());', '    }', '']
    o = primary['outcome']
    lines += ['    @Test', f'    void {m}MapsBackendFailureCode() {{'] + setup_common()
    lines += [f"        {primary['responseClass']} failed = new {primary['responseClass']}();", '        ResponseAudit audit = new ResponseAudit();', '        audit.setCodigoRespuesta("1");', '        failed.setResponseAudit(audit);']
    lines += primary_stub('failed')
    lines += [f'        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> {call});', f"        Assertions.assertEquals(ServiceError.{o['otherwiseError']}, error.getError());", '    }', '']
    if o.get('emptyListError'):
        lines += ['    @Test', f'    void {m}MapsEmptyResult() {{'] + setup_common()
        lines += [f"        {primary['responseClass']} empty = new {primary['responseClass']}();", '        ResponseAudit audit = new ResponseAudit();', '        audit.setCodigoRespuesta("0");', '        empty.setResponseAudit(audit);']
        lines += primary_stub('empty')
        lines += [f'        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> {call});', f"        Assertions.assertEquals(ServiceError.{o['emptyListError']}, error.getError());", '    }', '']
    lines += ['    @Test', f'    void {m}FailsExplicitlyBecauseResponseMappingIsUnspecified() {{'] + setup_common()
    lines += success_response(g, primary['responseClass'], o.get('listPath') or [], 'ok')
    lines += primary_stub('ok')
    lines += [f'        Assertions.assertThrows(UnsupportedOperationException.class, () -> {call});', '    }', '']
    if lookups_consumer:
        lines += ['    @Test', f'    void {m}RejectsUnknownDocumentType() {{'] + body_setup(g, op)
        for s in steps:
            if s['primary']:
                continue
            cvar = g.client_var(s['integration'])
            if s['lookupConsumers']:
                lines += ['        GetIdentificationTypesResponse types = new GetIdentificationTypesResponse();', '        types.setData(new ArrayList<>());', f"        Mockito.when({cvar}.{s['clientMethod']}(caller)).thenReturn(types);"]
            else:
                lines += [f"        Mockito.when({cvar}.{s['clientMethod']}(caller)).thenReturn(new {s['responseClass']}());"]
        lines += [f'        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> {call});', '        Assertions.assertEquals(ServiceError.IDF101, error.getError());', '    }', '']
    return lines


def controller_test(g: Gen) -> str:
    n = g.names
    lines = [f"class {n['controller']}Test {{", '', f"    private {n['service']} service;", '', f"    private {n['controller']} controller;", '', '    @BeforeEach', '    void setUp() {',
             f"        service = Mockito.mock({n['service']}.class);", f"        controller = new {n['controller']}(service);", '    }', '']
    hdr = ', '.join('"x"' for _ in g.caller)
    rh = ', '.join('"x"' for _ in g.rh_components)
    for op in g.ops:
        m = op['method']
        arg_values = [param_sample(p) for p in op['parameters']] + (['body'] if op['requestClass'] else [])
        lines += ['    @Test', f'    void {m}ReturnsDeclaredStatus() {{'] + body_setup(g, op)
        lines += [f"        {op['responseClass']} expected = new {op['responseClass']}();", f'        RequestHeaders headers = new RequestHeaders({rh});', f'        CallerHeaders caller = new CallerHeaders({hdr});',
                  f"        Mockito.when(service.{m}({', '.join(['headers', 'caller'] + arg_values)})).thenReturn(expected);",
                  f"        ResponseEntity<{op['responseClass']}> result = controller.{m}({', '.join(arg_values + ['\"x\"' for _ in g.caller])});",
                  '        Assertions.assertSame(expected, result.getBody());', f"        Assertions.assertEquals(HttpStatus.{ {200: 'OK', 201: 'CREATED'}[op['successStatus']] }, result.getStatusCode());", '    }', '']
    lines[-1:] = ['}']
    return g.source(g.pkg[n['controller']], lines)


def validator_test(g: Gen) -> str:
    n = g.names
    lines = [f"class {n['validator']}Test {{", '', f"    private final {n['validator']} validator = new {n['validator']}();", '',
             '    private final CallerHeaders caller = new CallerHeaders(' + ', '.join('"x"' for _ in g.caller) + ');', '']
    for op in g.ops:
        name = pascal(op['operationId'])
        args = [param_sample(p) for p in op['parameters']] + (['body'] if op['requestClass'] else [])
        lines += ['    @Test', f'    void {op["method"]}AcceptsInformedValues() {{'] + body_setup(g, op) + [f"        Assertions.assertDoesNotThrow(() -> validator.validate{name}({', '.join(['caller'] + args)}));", '    }', '']
        first_text = next((i for i, p in enumerate(op['parameters']) if p['javaType'] == 'String' and p['required']), None)
        if first_text is not None:
            blank = list(args)
            blank[first_text] = '" "'
            lines += ['    @Test', f'    void {op["method"]}RejectsBlankText() {{'] + body_setup(g, op)
            lines += [f"        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> validator.validate{name}({', '.join(['caller'] + blank)}));",
                      '        Assertions.assertEquals(ServiceError.IDF101, error.getError());', '    }', '']
        step = next(a for a in op['activities'] if a['role'] == 'validation')
        if step.get('dateRange'):
            dr = step['dateRange']
            names = [p['name'] for p in op['parameters']]
            reversed_args = list(args)
            reversed_args[names.index(dr['begin'])] = '"2026-10-15T20:00:00-05:00"'
            reversed_args[names.index(dr['end'])] = '"2026-10-15T19:00:00-05:00"'
            invalid_args = list(args)
            invalid_args[names.index(dr['begin'])] = '"not-a-date"'
            lines += ['    @Test', f'    void {op["method"]}RejectsEndBeforeBegin() {{',
                      f"        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> validator.validate{name}({', '.join(['caller'] + reversed_args)}));",
                      f"        Assertions.assertEquals(ServiceError.{dr['errorCode']}, error.getError());", '    }', '',
                      '    @Test', f'    void {op["method"]}RejectsUnparseableDate() {{',
                      f"        ServiceOperationException error = Assertions.assertThrows(ServiceOperationException.class, () -> validator.validate{name}({', '.join(['caller'] + invalid_args)}));",
                      '        Assertions.assertEquals(ServiceError.IDF101, error.getError());', '    }', '']
    lines[-1:] = ['}']
    return g.source(g.pkg[n['validator']], lines)


def handler_test(g: Gen) -> str:
    op = g.ops[0]
    key_method, key_path = op['httpMethod'], op['path']
    lines = ['class GlobalExceptionHandlerTest {', '', '    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();', '',
             '    private ServletWebRequest request() {', f'        return new ServletWebRequest(new MockHttpServletRequest({jstr(key_method)}, {jstr(key_path)}));', '    }', '',
             '    @Test', '    void operationFailureUsesTheContractErrorOfTheOperation() {',
             '        ResponseEntity<ErrorResponse> response = handler.operationFailure(new ServiceOperationException(ServiceError.IDF385, Map.of()), request());',
             '        Assertions.assertEquals(HttpStatus.NOT_FOUND, response.getStatusCode());', '        Assertions.assertEquals("IDF385", response.getBody().getSubType());',
             '        Assertions.assertEquals("NOT_FOUND", response.getBody().getStatus());', '    }', '',
             '    @Test', '    void placeholdersAreReplacedWithTheProvidedValues() {',
             '        ResponseEntity<ErrorResponse> response = handler.operationFailure(new ServiceOperationException(ServiceError.IDF101, Map.of("FIELD_NAME", "clientCode")), request());',
             '        Assertions.assertTrue(response.getBody().getDetail().contains("clientCode"));', '        Assertions.assertFalse(response.getBody().getDetail().contains("["));', '    }', '',
             '    @Test', '    void unexpectedFailureBecomesInternalError() {',
             '        ResponseEntity<ErrorResponse> response = handler.unexpectedFailure(new IllegalStateException("boom"), request());',
             '        Assertions.assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, response.getStatusCode());', '        Assertions.assertEquals("IDT3", response.getBody().getSubType());',
             '        Assertions.assertTrue(response.getBody().getDetail().contains("boom"));', '    }', '',
             '    @Test', '    void missingParameterBecomesMissingParametersError() {',
             '        ResponseEntity<Object> response = handler.handleExceptionInternal(new MissingServletRequestParameterException("clientCode", "String"), null, new HttpHeaders(), HttpStatus.BAD_REQUEST, request());',
             '        ErrorResponse body = (ErrorResponse) response.getBody();', '        Assertions.assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());',
             '        Assertions.assertEquals("IDF101", body.getSubType());', '        Assertions.assertTrue(body.getDetail().contains("clientCode"));', '    }', '',
             '    @Test', '    void otherFrameworkStatusesBecomeInternalError() {',
             '        ResponseEntity<Object> response = handler.handleExceptionInternal(new IllegalStateException("x"), null, new HttpHeaders(), HttpStatus.METHOD_NOT_ALLOWED, request());',
             '        Assertions.assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, response.getStatusCode());', '    }', '}']
    return g.source(g.pkg['GlobalExceptionHandler'], lines)


def clients_test(g: Gen) -> str:
    lines = ['class IntegrationClientsTest {', '', '    private static final String ROOT = "http://localhost";', '', '    private final RestTemplate restTemplate = new RestTemplateBuilder().rootUri(ROOT).build();', '',
             '    private final MockRestServiceServer server = MockRestServiceServer.bindTo(restTemplate).build();', '',
             '    private final Clock clock = Clock.fixed(Instant.EPOCH, ZoneOffset.UTC);', '',
             '    private final CallerHeaders caller = new CallerHeaders(' + ', '.join(jstr(h['name']) for h in g.caller) + ');', '']
    for name, item in sorted(g.integrations.items()):
        steps = {}
        for op in g.ops:
            for s in op['activities']:
                if s['role'] == 'remote-call' and s['integration'] == name:
                    steps.setdefault(s['clientMethod'], s)
        cls = item['client']
        var = lower_first(cls)
        needs_clock = item['cache'] is not None or any(m['kind'] == 'timestamp' for s in steps.values() for m in s['headers'].get('mappings', []))
        ctor = ['restTemplate'] + (['clock'] if needs_clock else []) + (['Duration.ofHours(1).toMillis()'] if item['cache'] else [])
        for mname, s in sorted(steps.items()):
            query = s['query']
            values = []
            for q in query:
                if q['backendType'] not in ('String', 'Integer'):
                    raise rd.Unsupported(f"client test: unsupported query type {q['backendType']}")
                values.append('"x"' if q['backendType'] == 'String' else '1')
            url = f"ROOT + {jstr(s['path'])}" + ((' + ' + jstr('?' + '&'.join(f"{q['to']}={'x' if q['backendType'] == 'String' else '1'}" for q in query))) if query else '')
            args = ['caller'] + (['body'] if s['body'] else []) + values
            lines += ['    @Test', f'    void {var}{pascal(mname)}SendsTheSpecifiedRequest() {{']
            if s['body']:
                lines.append(f"        {s['body']['class']} body = new {s['body']['class']}();")
            expectations = [f'MockRestRequestMatchers.requestTo({url})', f"MockRestRequestMatchers.method(HttpMethod.{s['httpMethod']})"]
            if s['headers']['mode'] == 'forward-all-request-headers':
                expectations += [f"MockRestRequestMatchers.header({jstr(h['name'])}, {jstr(h['name'])})" for h in g.caller]
            else:
                for m in s['headers']['mappings']:
                    if m['kind'] == 'request-header':
                        expectations.append(f"MockRestRequestMatchers.header({jstr(m['to'])}, {jstr(m['from'])})")
                    elif m['kind'] == 'timestamp':
                        expectations.append(f"MockRestRequestMatchers.header({jstr(m['to'])}, \"1970-01-01T00:00:00+0000\")")
                    elif m['kind'] == 'constant':
                        expectations.append(f"MockRestRequestMatchers.header({jstr(m['to'])}, {jstr(m['value'])})")
            lines += [f'        {cls} client = new {cls}({", ".join(ctor)});']
            lines += ['        server.expect(MockRestRequestMatchers.requestTo(' + url + '))']
            lines += [f'                .andExpect({e})' for e in expectations[1:]]
            lines += ['                .andRespond(MockRestResponseCreators.withSuccess("{}", MediaType.APPLICATION_JSON));',
                      f"        {s['responseClass']} response = client.{mname}({', '.join(args)});", '        Assertions.assertNotNull(response);', '        server.verify();', '    }', '']
            if s['outcome']['kind'] == 'http-status-200':
                lines += ['    @Test', f'    void {var}{pascal(mname)}RejectsNonOkStatus() {{', f'        {cls} client = new {cls}({", ".join(ctor)});',
                          f'        server.expect(MockRestRequestMatchers.requestTo({url}))', '                .andRespond(MockRestResponseCreators.withStatus(HttpStatus.INTERNAL_SERVER_ERROR));',
                          f"        IntegrationException error = Assertions.assertThrows(IntegrationException.class, () -> client.{mname}({', '.join(args)}));",
                          '        Assertions.assertEquals(IntegrationException.Kind.NON_OK_RESPONSE, error.getKind());', '    }', '']
                if item['cache']:
                    lines += ['    @Test', f'    void {var}{pascal(mname)}ReusesTheCachedCatalog() {{', f'        {cls} client = new {cls}({", ".join(ctor)});',
                              f'        server.expect(ExpectedCount.once(), MockRestRequestMatchers.requestTo({url}))',
                              '                .andRespond(MockRestResponseCreators.withSuccess("{}", MediaType.APPLICATION_JSON));',
                              f"        {s['responseClass']} first = client.{mname}({', '.join(args)});", f"        {s['responseClass']} second = client.{mname}({', '.join(args)});",
                              '        Assertions.assertSame(first, second);', '        server.verify();', '    }', '']
    lines += ['    @Test', '    void executeClassifiesFailures() {',
              '        IntegrationException nonOk = Assertions.assertThrows(IntegrationException.class,',
              '                () -> IntegrationSupport.execute("x", () -> {', '                    throw new HttpClientErrorException(HttpStatus.BAD_REQUEST);', '                }));',
              '        Assertions.assertEquals(IntegrationException.Kind.NON_OK_RESPONSE, nonOk.getKind());',
              '        IntegrationException timeout = Assertions.assertThrows(IntegrationException.class,',
              '                () -> IntegrationSupport.execute("x", () -> {', '                    throw new ResourceAccessException("t", new SocketTimeoutException());', '                }));',
              '        Assertions.assertEquals(IntegrationException.Kind.TIMEOUT, timeout.getKind());',
              '        IntegrationException unavailable = Assertions.assertThrows(IntegrationException.class,',
              '                () -> IntegrationSupport.execute("x", () -> {', '                    throw new ResourceAccessException("u", new ConnectException());', '                }));',
              '        Assertions.assertEquals(IntegrationException.Kind.UNAVAILABLE, unavailable.getKind());',
              '        IntegrationException unexpected = Assertions.assertThrows(IntegrationException.class,',
              '                () -> IntegrationSupport.execute("x", () -> {', '                    throw new RestClientException("e");', '                }));',
              '        Assertions.assertEquals(IntegrationException.Kind.UNEXPECTED, unexpected.getKind());', '    }', '',
              '    @Test', '    void catalogCacheExpiresAfterTheRefreshInterval() {', '        Clock mutable = Mockito.mock(Clock.class);',
              '        Mockito.when(mutable.instant()).thenReturn(Instant.EPOCH, Instant.EPOCH.plusMillis(1), Instant.EPOCH.plusSeconds(2));',
              '        CatalogCache<Integer> catalog = new CatalogCache<>(mutable, 1000);', '        AtomicInteger loads = new AtomicInteger();',
              '        catalog.get(loads::incrementAndGet);', '        catalog.get(loads::incrementAndGet);', '        Assertions.assertEquals(1, loads.get());',
              '        catalog.get(loads::incrementAndGet);', '        Assertions.assertEquals(2, loads.get());', '    }', '}']
    return g.source(f'{g.base}.client', lines, extra=['java.util.concurrent.atomic.AtomicInteger'])