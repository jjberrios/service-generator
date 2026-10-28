"""Generated tests, part 3: HTTP contract (MockMvc standalone), exception advice, corporate logging, entity mapping, JPA persistence, and the rule universe."""
from renderers import Unsupported, class_of, package_of, java_string
from service_model import cap, snake, STATUS_ENUM, parse_numeric
from java_components import header, fqn, dto_fqn, check_lines
from test_components import cls_name, getter, setter, typed_value, entity_sample, sample_for_input, email_aware, request_fields, filter_sample, mname, NUMERIC, expected_for_input
from test_components2 import entity_setup
from test_components4 import parameter_methods, body_methods, header_sample, header_mvc_methods

STATUS_BY_NAME = {v: k for k, v in STATUS_ENUM.items()}


def expected_error(M, method, status):
    """What the advice must answer for (method, status), taken only from the contract examples (same lookup order as the advice)."""
    errors = M['errors']
    examples = errors['byStatus'].get(status, {})
    first = next(iter(examples.values()), None) or {}
    detail = (examples.get(method) or {}).get('detail') or first.get('detail')
    return {'message': errors['messageByMethod'].get(method), 'type': first.get('type'), 'subType': first.get('subType'), 'detail': detail}


def op_uri(op):
    return op['path'].replace('{' + (op['params']['path'][0]['name'] if op['params']['path'] else '') + '}', '1') if op['params']['path'] else op['path']


def json_body(M, op):
    parts = []
    for f in op['fields']:
        raw, _ = sample_for_input(M, op, f)
        parts.append(f'"{f["input"]}":"{email_aware(M, op, f["input"], raw)}"')
    return '{' + ','.join(parts) + '}'


def any_args(op):
    n = 1 + len(op['params']['path']) + (len(op['params']['query']) if op['kind'] == 'select' else 0) + (1 if op['requestModel'] else 0)
    return ', '.join(['any()'] * n)


# ============================================================================================================================== controller
def controller_test(M, path, cov):
    test = class_of(path)
    ctl, svc, advice, trans = (cls_name(M, k) for k in ('controller-implementation', 'application-service-contract', 'central-contract-error-advice', 'data-access-error-translator'))
    exc = cls_name(M, 'internal-typed-exception')
    names = {p['name']: p for op in M['ops'] for p in op['params']['header']}
    imports = {fqn(M, 'controller-implementation'), fqn(M, 'application-service-contract'), fqn(M, 'central-contract-error-advice'), fqn(M, 'data-access-error-translator'), fqn(M, 'internal-typed-exception'),
               fqn(M, 'request-headers-model'), 'org.junit.jupiter.api.BeforeEach', 'org.junit.jupiter.api.Test', 'org.junit.jupiter.api.extension.ExtendWith', 'org.mockito.ArgumentCaptor', 'org.mockito.Mock',
               'org.mockito.junit.jupiter.MockitoExtension', 'org.springframework.http.HttpStatus', 'org.springframework.http.MediaType', 'org.springframework.test.web.servlet.MockMvc',
               'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder', 'org.springframework.test.web.servlet.setup.MockMvcBuilders',
               'org.springframework.validation.beanvalidation.LocalValidatorFactoryBean', 'static org.junit.jupiter.api.Assertions.assertEquals', 'static org.mockito.ArgumentMatchers.any',
               'static org.mockito.Mockito.verify', 'static org.mockito.Mockito.when', 'static org.mockito.Mockito.never', 'static org.mockito.Mockito.verifyNoInteractions',
               'static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.request', 'static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath',
               'static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status'}
    methods = []
    test_name = test
    api = cls_name(M, 'contract-api-interface')
    consts, seen_models, used_constraints = {}, set(), False
    hv = {p['java']: header_sample(M, p, consts) for p in names.values()}          # valid value per header: neutral unless the contract declares constraints

    def add(rule, name, body, throws=True):
        methods.append(f'    @Test\n    void {name}() throws Exception {{\n{body}\n    }}')
        cov.append((rule, f'{test_name}#{name}'))

    for op in M['ops']:
        oid = op['id']
        imports.add(dto_fqn(M, op['successModel']))
        if op['requestModel']:
            imports.add(dto_fqn(M, op['requestModel']))
        uri, verb = op_uri(op), op['method']
        body_clause = f'\n                .contentType(MediaType.APPLICATION_JSON)\n                .content({java_string(json_body(M, op))})' if op['requestModel'] else ''
        perform = lambda extra='': f'mvc.perform(withHeaders(request(HttpMethod.valueOf({java_string(verb)}), {java_string(uri)}){body_clause}{extra}))'
        perform_with = lambda header_name, value: f'mvc.perform(withHeaders(request(HttpMethod.valueOf({java_string(verb)}), {java_string(uri)}){body_clause}, null, {java_string(header_name)}, {value}))'
        success = f'{op["successModel"]} body = new {op["successModel"]}();\n        body.setCode(HttpStatus.OK.value());\n        body.setMessage({java_string(op["successMessage"])});'
        stub = f'when(service.{oid}({any_args(op)}))'
        header_roles = op['headerByRole']
        add(f'{oid}:outcome:200', mname(oid, 'answers', 'the', 'declared', 'success', 'response'),
            f'        {success}\n        {stub}.thenReturn(body);\n        {perform()}\n                .andExpect(status().isOk())\n                .andExpect(jsonPath("$.code").value(HttpStatus.OK.value()))\n'
            f'                .andExpect(jsonPath("$.message").value({java_string(op["successMessage"])}));')
        role_checks = ''.join(f'        assertEquals({hv[header_roles[c]]}, captor.getValue().{c}());\n' for c in M['headers']['components'])
        add(f'{oid}:headers:roles', mname(oid, 'builds', 'the', 'request', 'headers', 'from', 'the', 'mapped', 'header', 'roles'),
            f'        {success}\n        {stub}.thenReturn(body);\n        {perform()}.andExpect(status().isOk());\n        ArgumentCaptor<RequestHeaders> captor = ArgumentCaptor.forClass(RequestHeaders.class);\n'
            f'        verify(service).{oid}(captor.capture(), {", ".join(["any()"] * (len(any_args(op).split(", ")) - 1))});\n' + role_checks.rstrip('\n'))
        required = [p for p in op['params']['header'] if p['required']]
        if required:
            miss = required[0]
            add(f'{oid}:contract:required-header', mname(oid, 'rejects', 'a', 'request', 'without', 'the', 'required', miss['java']),
                f'        mvc.perform(withHeaders(request(HttpMethod.valueOf({java_string(verb)}), {java_string(uri)}){body_clause}, {java_string(miss["name"])}))\n                .andExpect(status().isBadRequest())\n'
                f'                .andExpect(jsonPath("$.code").value(HttpStatus.BAD_REQUEST.value()));\n        verifyNoInteractions(service);')
        if op['requestModel']:
            add(f'{oid}:contract:malformed-body', mname(oid, 'rejects', 'a', 'malformed', 'body'),
                f'        mvc.perform(withHeaders(request(HttpMethod.valueOf({java_string(verb)}), {java_string(uri)})\n                .contentType(MediaType.APPLICATION_JSON)\n                .content("{{not-json")))\n                .andExpect(status().isBadRequest());\n        verifyNoInteractions(service);')
            add(f'{oid}:contract:null-field', mname(oid, 'rejects', 'an', 'explicit', 'null', 'field'),
                f'        mvc.perform(withHeaders(request(HttpMethod.valueOf({java_string(verb)}), {java_string(uri)})\n                .contentType(MediaType.APPLICATION_JSON)\n                .content("{{\\"{op["fields"][0]["input"]}\\":null}}")))\n                .andExpect(status().isBadRequest());\n        verifyNoInteractions(service);')
            mandatory = [f['name'] for f in M['models'][op['requestModel']]['fields'] if '@NotNull' in ' '.join(f.get('validationAnnotations') or [])]
            if mandatory:
                add(f'{oid}:contract:required-body-field', mname(oid, 'rejects', 'a', 'body', 'without', 'the', 'required', mandatory[0]),
                    f'        mvc.perform(withHeaders(request(HttpMethod.valueOf({java_string(verb)}), {java_string(uri)})\n                .contentType(MediaType.APPLICATION_JSON)\n                .content("{{}}")))\n                .andExpect(status().isBadRequest());\n        verifyNoInteractions(service);')
        declared = [s for s in op['statuses'] if s != 200]
        for status in declared:
            exp = expected_error(M, verb, status)
            checks = f'                .andExpect(jsonPath("$.code").value(HttpStatus.{STATUS_ENUM[status]}.value()))\n                .andExpect(jsonPath("$.status").value({java_string(STATUS_ENUM[status])}))'
            if exp['message']:
                checks += f'\n                .andExpect(jsonPath("$.message").value({java_string(exp["message"])}))'
            if exp['detail']:
                checks += f'\n                .andExpect(jsonPath("$.detail").value({java_string(exp["detail"])}))'
            if exp['type']:
                checks += f'\n                .andExpect(jsonPath("$.type").value({java_string(exp["type"])}))'
            if exp['subType']:
                checks += f'\n                .andExpect(jsonPath("$.subType").value({java_string(exp["subType"])}))'
            add(f'{oid}:outcome:{status}', mname(oid, 'answers', str(status), 'as', 'declared', 'by', 'the', 'contract'),
                f'        {stub}.thenThrow(new {exc}(HttpStatus.{STATUS_ENUM[status]}, "failure"));\n        {perform()}\n                .andExpect(status().is(HttpStatus.{STATUS_ENUM[status]}.value()))\n{checks};')
        undeclared = [s for s in STATUS_ENUM if s not in op['statuses'] and s not in (400, 500)]
        if undeclared:
            status = undeclared[0]
            exp = expected_error(M, verb, 500)
            add(f'{oid}:outcome:undeclared', mname(oid, 'never', 'answers', str(status), 'because', 'it', 'is', 'not', 'declared'),
                f'        {stub}.thenThrow(new {exc}(HttpStatus.{STATUS_ENUM[status]}, "failure"));\n        {perform()}\n                .andExpect(status().isInternalServerError())\n                .andExpect(jsonPath("$.code").value(HttpStatus.INTERNAL_SERVER_ERROR.value()));')
        before = len(methods)
        parameter_methods(M, op, api, add, cov, imports, consts, test_name)
        body_methods(M, op, add, cov, imports, consts, seen_models)
        header_mvc_methods(M, op, add, imports, consts, perform_with, stub, success)
        used_constraints = used_constraints or len(methods) > before
    helper = ('    private static MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder) {\n        return withHeaders(builder, null);\n    }\n\n'
              '    private static MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder, String omitted) {\n        return withHeaders(builder, omitted, null, null);\n    }\n\n'
              '    private static MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder, String omitted, String overridden, String value) {\n' + ''.join(
                  f'        if (!{java_string(n)}.equals(omitted)) {{\n            builder.header({java_string(n)}, {java_string(n)}.equals(overridden) ? value : {hv[p["java"]]});\n        }}\n' for n, p in names.items()) + '        return builder;\n    }')
    imports.add('org.springframework.http.HttpMethod')
    if used_constraints:
        imports |= {fqn(M, 'contract-api-interface'), 'jakarta.validation.ConstraintViolation', 'java.lang.annotation.Annotation', 'java.lang.reflect.Method', 'java.util.Arrays', 'java.util.Set',
                    'static org.junit.jupiter.api.Assertions.assertFalse', 'static org.junit.jupiter.api.Assertions.assertTrue'}
        helper += (f'\n\n    private Set<ConstraintViolation<{ctl}>> violations(String operation, Object[] arguments) {{\n'
                   f'        Method method = Arrays.stream({api}.class.getMethods()).filter(candidate -> candidate.getName().equals(operation)).findFirst().orElseThrow();\n'
                   '        return validator.forExecutables().validateParameters(controller, method, arguments);\n    }\n\n'
                   '    private static boolean violates(Set<? extends ConstraintViolation<?>> found, String property, Class<? extends Annotation> constraint) {\n'
                   '        return found.stream().anyMatch(violation -> violation.getConstraintDescriptor().getAnnotation().annotationType().equals(constraint)\n'
                   '                && (property == null || violation.getPropertyPath().toString().equals(property)));\n    }')
    if used_constraints:
        imports |= {'jakarta.validation.Validator', 'org.springframework.aop.framework.ProxyFactory', 'org.springframework.validation.beanvalidation.MethodValidationInterceptor'}
        mvc_target = ('ProxyFactory factory = new ProxyFactory(controller);\n        factory.setProxyTargetClass(true);\n        factory.addAdvice(new MethodValidationInterceptor((Validator) validator));\n'
                      '        mvc = MockMvcBuilders.standaloneSetup(factory.getProxy())')          # the controller behind method validation, as MethodValidationPostProcessor wires it in production
    else:
        mvc_target = 'mvc = MockMvcBuilders.standaloneSetup(controller)'
    constant_lines = ''.join(f'    private static final int {k} = {v};\n' for k, v in sorted(consts.items()))
    text = (header(path, imports) + f'@ExtendWith(MockitoExtension.class)\nclass {test} {{\n{constant_lines}    @Mock\n    private {svc} service;\n    private {ctl} controller;\n    private LocalValidatorFactoryBean validator;\n    private MockMvc mvc;\n\n    @BeforeEach\n    void setup() {{\n'
            f'        controller = new {ctl}(service);\n        validator = new LocalValidatorFactoryBean();\n        validator.afterPropertiesSet();\n        {mvc_target}\n'
            f'                .setControllerAdvice(new {advice}(new {trans}()))\n                .setValidator(validator)\n                .build();\n    }}\n\n' + '\n\n'.join(methods) + '\n\n' + helper + '\n}\n')
    return check_lines(text, test)


# ================================================================================================================================ advice
def handler_test(M, path, cov):
    test, advice, trans = class_of(path), cls_name(M, 'central-contract-error-advice'), cls_name(M, 'data-access-error-translator')
    err, exc = M['errors']['model'], cls_name(M, 'internal-typed-exception')
    imports = {fqn(M, 'internal-typed-exception'), fqn(M, 'central-contract-error-advice'), fqn(M, 'data-access-error-translator'), dto_fqn(M, err), 'jakarta.validation.ConstraintViolationException',
               'java.util.Set', 'org.junit.jupiter.api.Test', 'org.springframework.dao.QueryTimeoutException', 'org.springframework.http.HttpStatus', 'org.springframework.http.ResponseEntity',
               'org.springframework.mock.web.MockHttpServletRequest', 'org.springframework.web.context.request.ServletWebRequest', 'static org.junit.jupiter.api.Assertions.assertEquals',
               'static org.junit.jupiter.api.Assertions.assertNull'}
    methods = []

    def add(rule, name, body):
        methods.append(f'    @Test\n    void {name}() {{\n{body}\n    }}')
        cov.append((rule, f'{test}#{name}'))

    by_method = {}
    for op in M['ops']:
        by_method.setdefault(op['method'], []).append(op)
    for verb, ops in sorted(by_method.items()):
        statuses = sorted({s for o in ops for s in o['statuses'] if s != 200})
        for status in statuses:
            exp = expected_error(M, verb, status)
            asserts = (f'        assertEquals(HttpStatus.{STATUS_ENUM[status]}, response.getStatusCode());\n        assertEquals(Integer.valueOf(HttpStatus.{STATUS_ENUM[status]}.value()), response.getBody().getCode());\n'
                       f'        assertEquals({java_string(STATUS_ENUM[status])}, response.getBody().getStatus());\n')
            if exp['message']:
                asserts += f'        assertEquals({java_string(exp["message"])}, response.getBody().getMessage());\n'
            for key, getter_name in (('type', 'getType'), ('subType', 'getSubType'), ('detail', 'getDetail')):
                if exp[key]:
                    asserts += f'        assertEquals({java_string(exp[key])}, response.getBody().{getter_name}());\n'
            if not exp['type']:
                asserts += '        assertNull(response.getBody().getType());\n'
            body = (f'        ResponseEntity<{err}> response = advice.operationFailure(new {exc}(HttpStatus.{STATUS_ENUM[status]}, "failure"), request({java_string(verb)}));\n' + asserts.rstrip('\n'))
            for o in ops:
                if status in o['statuses']:
                    add(f'{o["id"]}:outcome:{status}:advice', mname(verb.lower(), 'failure', str(status), 'uses', 'the', 'contract', 'texts'), body) if o is ops[0] else cov.append((f'{o["id"]}:outcome:{status}:advice', f'{test}#{mname(verb.lower(), "failure", str(status), "uses", "the", "contract", "texts")}'))
        undeclared = [s for s in STATUS_ENUM if s not in statuses and s not in (400, 500)]
        if undeclared:
            status = undeclared[0]
            add(f'{ops[0]["id"]}:outcome:undeclared:advice', mname(verb.lower(), 'status', str(status), 'becomes', 'an', 'internal', 'error'),
                f'        ResponseEntity<{err}> response = advice.operationFailure(new {exc}(HttpStatus.{STATUS_ENUM[status]}, "failure"), request({java_string(verb)}));\n        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, response.getStatusCode());\n'
                f'        assertEquals(Integer.valueOf(HttpStatus.INTERNAL_SERVER_ERROR.value()), response.getBody().getCode());')
    verb = sorted(by_method)[0]
    add(f'{by_method[verb][0]["id"]}:outcome:400:constraint', mname('constraint', 'violations', 'are', 'bad', 'requests'),
        f'        ResponseEntity<{err}> response = advice.constraintFailure(new ConstraintViolationException("invalid", Set.of()), request({java_string(verb)}));\n        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());')
    add(f'{by_method[verb][0]["id"]}:outcome:translation', mname('unexpected', 'data', 'access', 'failures', 'are', 'translated', 'before', 'answering'),
        f'        ResponseEntity<{err}> response = advice.unexpectedFailure(new QueryTimeoutException("timeout"), request({java_string(verb)}));\n'
        f'        HttpStatus expected = response.getStatusCode() == HttpStatus.GATEWAY_TIMEOUT ? HttpStatus.GATEWAY_TIMEOUT : HttpStatus.INTERNAL_SERVER_ERROR;\n        assertEquals(expected, response.getStatusCode());')
    helper = '    private static ServletWebRequest request(String method) {\n        return new ServletWebRequest(new MockHttpServletRequest(method, "/resource"));\n    }'
    text = header(path, imports) + f'class {test} {{\n    private final {advice} advice = new {advice}(new {trans}());\n\n' + '\n\n'.join(methods) + '\n\n' + helper + '\n}\n'
    return check_lines(text, test)


# ================================================================================================================================ logging
def logging_test(M, path, cov):
    test = class_of(path)
    imports = {fqn(M, 'archetype-activity-logger'), fqn(M, 'activity-constants'), 'ch.qos.logback.classic.Level', 'ch.qos.logback.classic.Logger', 'ch.qos.logback.classic.spi.ILoggingEvent',
               'ch.qos.logback.core.read.ListAppender', 'org.junit.jupiter.api.AfterEach', 'org.junit.jupiter.api.BeforeEach', 'org.junit.jupiter.api.Test', 'org.slf4j.LoggerFactory',
               'static org.junit.jupiter.api.Assertions.assertEquals', 'static org.junit.jupiter.api.Assertions.assertFalse', 'static org.junit.jupiter.api.Assertions.assertTrue'}
    methods = []

    def add(rule, name, body):
        methods.append(f'    @Test\n    void {name}() {{\n{body}\n    }}')
        cov.append((rule, f'{test}#{name}'))

    seen = set()
    for op in M['ops']:
        if not op['requestModel'] or op['requestModel'] in seen:
            continue
        seen.add(op['requestModel'])
        imports.add(dto_fqn(M, op['requestModel']))
        f = op['fields'][0]
        raw, _ = sample_for_input(M, op, f)
        raw = email_aware(M, op, f['input'], raw)
        add(f'{op["id"]}:logging:body', mname('sparse', op['requestModel'], 'is', 'logged', 'without', 'a', 'serialization', 'error'),
            f'        {op["requestModel"]} body = new {op["requestModel"]}();\n        body.{setter(f["input"])}({java_string(raw)});\n        ActivityLogger.logContenido(logger, "body: {{}}", body, {op["requestModel"]}.class);\n'
            f'        assertEquals(1, appender.list.size());\n        assertEquals(Level.INFO, appender.list.get(0).getLevel());\n        assertFalse(appender.list.get(0).getFormattedMessage().contains("suppliedFields"));')
    first = M['ops'][0]
    add(f'{first["id"]}:logging:activity-markers', mname('activity', 'markers', 'carry', 'the', 'transaction', 'prefix'),
        f'        ActivityLogger.inicioActividad(logger, "[tx-1] ", ConstanApi.{first["validationConstant"]});\n        ActivityLogger.finActividad(logger, "[tx-1] ", ConstanApi.{first["validationConstant"]});\n'
        '        assertFalse(appender.list.isEmpty());\n        assertTrue(appender.list.stream().allMatch(event -> event.getLevel() == Level.INFO));\n        assertTrue(appender.list.stream().anyMatch(event -> event.getFormattedMessage().contains("[tx-1]")));')
    text = (header(path, imports) + f'class {test} {{\n    private Logger logger;\n    private ListAppender<ILoggingEvent> appender;\n\n    @BeforeEach\n    void attach() {{\n'
            f'        logger = (Logger) LoggerFactory.getLogger({test}.class);\n        logger.setLevel(Level.INFO);\n        appender = new ListAppender<>();\n        appender.start();\n        logger.addAppender(appender);\n    }}\n\n'
            '    @AfterEach\n    void detach() {\n        logger.detachAppender(appender);\n    }\n\n' + '\n\n'.join(methods) + '\n}\n')
    return check_lines(text, test)


# ================================================================================================================================= entity
def entity_test(M, path, cov):
    test, entity = class_of(path), M['entity']['class']
    table = M['entity']['table']
    imports = {M['entity']['fqn'], 'jakarta.persistence.Column', 'jakarta.persistence.Entity', 'jakarta.persistence.Id', 'jakarta.persistence.Lob', 'jakarta.persistence.Table', 'org.junit.jupiter.api.Test',
               'static org.junit.jupiter.api.Assertions.assertEquals', 'static org.junit.jupiter.api.Assertions.assertNotNull', 'static org.junit.jupiter.api.Assertions.assertNull'}
    checks = []
    for prop, f in M['entity']['fields'].items():
        line = f'        assertEquals({java_string(f["physicalColumn"])}, {entity}.class.getDeclaredField({java_string(prop)}).getAnnotation(Column.class).name());'
        checks.append(line)
        if f.get('lob'):
            checks.append(f'        assertNotNull({entity}.class.getDeclaredField({java_string(prop)}).getAnnotation(Lob.class));')
        elif f['javaType'] == 'String':
            checks.append(f'        assertNull({entity}.class.getDeclaredField({java_string(prop)}).getAnnotation(Lob.class));')
    pk = M['entity']['pk']
    body = (f'        assertNotNull({entity}.class.getAnnotation(Entity.class));\n        assertEquals({java_string(table)}, {entity}.class.getAnnotation(Table.class).name());\n'
            f'        assertNotNull({entity}.class.getDeclaredField({java_string(pk)}).getAnnotation(Id.class));\n' + '\n'.join(checks))
    cov.append((f'entity:mapping', f'{test}#entityMapsTheTableAndEveryColumn'))
    return check_lines(header(path, imports) + f'class {test} {{\n    @Test\n    void entityMapsTheTableAndEveryColumn() throws NoSuchFieldException {{\n{body}\n    }}\n}}\n', test)
