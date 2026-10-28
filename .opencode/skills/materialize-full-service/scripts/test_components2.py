"""Generated tests, part 2: mapper, specification, service, controller contract, exception advice, logging, entity mapping and JPA persistence."""
import re

from renderers import Unsupported, class_of, package_of, java_string
from service_model import cap, snake, STATUS_ENUM, parse_numeric
from java_components import header, fqn, dto_fqn, check_lines
from test_components import (expected_for_input, cls_name, getter, setter, typed_value, entity_sample, sample_for_input, email_aware, build_request, request_fields, select_args, filter_sample, mname,
                             NUMERIC)


def entity_setup(M, var='entity', skip=(), enums=None, sentinel=False):
    lines = [f'        {M["entity"]["class"]} {var} = new {M["entity"]["class"]}();']
    for prop, f in M['entity']['fields'].items():
        if prop == M['entity']['pk'] or prop in skip:
            continue
        enum = (enums or {}).get(prop)
        lines.append(f'        {var}.{setter(prop)}({typed_value(f["javaType"], prop, enum, sentinel)});')
    return '\n'.join(lines)


def command_args(op, enums=None, supplied=None):
    """Constructor arguments of an insert/update command with typed sample values (update: Field wrappers)."""
    args = []
    if op['kind'] == 'update':
        args.append('Long.valueOf(1)')
    for f in op['fields']:
        value = typed_value(f['type'], f['prop'], f['enum'])
        if op['kind'] == 'update':
            on = supplied is None or f['prop'] in supplied
            args.append(f'new Val.Field<>({"true" if on else "false"}, {value if on else "null"})')
        else:
            args.append(value)
    return (',\n' + ' ' * 20).join(args) if len(args) > 2 else ', '.join(args)


# ------------------------------------------------------------------------------------------------------------------------------- mapper
def mapper_test(M, path, cov):
    test, mp, val = class_of(path), cls_name(M, 'explicit-contract-data-mapper'), cls_name(M, 'business-validator')
    entity = M['entity']['class']
    imports = {M['entity']['fqn'], fqn(M, 'business-validator'), fqn(M, 'internal-typed-exception'), 'java.math.BigDecimal', 'java.time.LocalDateTime', 'java.util.List', 'org.junit.jupiter.api.Test',
               'org.springframework.http.HttpStatus', 'static org.junit.jupiter.api.Assertions.assertEquals', 'static org.junit.jupiter.api.Assertions.assertThrows',
               'static org.junit.jupiter.api.Assertions.assertNull', 'static org.junit.jupiter.api.Assertions.assertNotNull'}
    exc = cls_name(M, 'internal-typed-exception')
    methods = []

    def add(rule, name, body):
        methods.append(f'    @Test\n    void {name}() {{\n{body}\n    }}')
        cov.append((rule, f'{test}#{name}'))

    for op in M['ops']:
        oid = op['id']
        if op['kind'] == 'select':
            for t in (op['successModel'], op['dataModel'], op['itemModel']):
                imports.add(dto_fqn(M, t))
            enums = {c['prop']: c['enum'] for c in op['columns'] if c['enum']}
            row = entity_setup(M, 'row', enums=enums).replace('        ' + entity + ' row', '        ' + entity + ' row', 1)
            checks = []
            for c in op['columns']:
                prop_f = M['entity']['fields'][c['prop']]
                if c['entityType'] == c['itemType']:
                    checks.append(f'        assertEquals(row.{getter(c["prop"])}(), item.{getter(c["field"])}());')
                elif c['entityType'] == 'BigDecimal':
                    checks.append(f'        assertEquals(row.{getter(c["prop"])}().toPlainString(), item.{getter(c["field"])}());')
                else:
                    checks.append(f'        assertEquals(String.valueOf(row.{getter(c["prop"])}()), item.{getter(c["field"])}());')
            lp = cap(op['listProp'])
            body = (row + f'\n        row.{setter(M["entity"]["pk"])}(Long.valueOf(1));\n        {op["successModel"]} response = mapper.{oid}Response(List.of(row));\n'
                    f'        assertEquals(HttpStatus.OK.value(), response.getCode());\n        assertEquals({java_string(op["successMessage"])}, response.getMessage());\n'
                    f'        assertEquals(1, response.getData().get{lp}().size());\n        {op["itemModel"]} item = response.getData().get{lp}().get(0);\n' + '\n'.join(checks))
            add(f'{oid}:mapping:response', mname(oid, 'maps', 'rows', 'to', 'the', 'declared', 'response'), body)
            add(f'{oid}:outcome:200', mname(oid, 'reports', 'the', 'success', 'code', 'and', 'message'),
                f'        {op["successModel"]} response = mapper.{oid}Response(List.of());\n        assertEquals(HttpStatus.OK.value(), response.getCode());\n        assertEquals({java_string(op["successMessage"])}, response.getMessage());\n        assertEquals(0, response.getData().get{lp}().size());')
            for c in op['columns']:
                if c['enum'] and c['entityType'] == 'Integer':
                    bad = row.replace(f'row.{setter(c["prop"])}({typed_value("Integer", c["prop"], c["enum"])});', f'row.{setter(c["prop"])}(Integer.MAX_VALUE);')
                    add(f'{oid}:enum:{c["field"]}', mname(oid, 'refuses', 'a', 'stored', c['field'], 'outside', 'the', 'declared', 'enum'),
                        bad + f'\n        List<{entity}> rows = List.of(row);\n        ServiceOperationException error = assertThrows(ServiceOperationException.class, () -> mapper.{oid}Response(rows));\n        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, error.getStatus());'.replace('ServiceOperationException', exc))
        elif op['kind'] == 'insert':
            checks = [f'        assertEquals({typed_value(f["type"], f["prop"], f["enum"])}, entity.{getter(f["prop"])}());' for f in op['fields']]
            if op['auditUser']:
                checks.append(f'        assertEquals("audit-user", entity.{getter(op["auditUser"])}());')
            add(f'{oid}:mapping:entity', mname(oid, 'maps', 'the', 'command', 'to', 'the', 'entity'),
                f'        {entity} entity = mapper.{oid}Entity(new {val}.{op["commandName"]}({command_args(op)}), "audit-user");\n' + '\n'.join(checks))
            if op['auditUser']:
                add(f'{oid}:audit:user', mname(oid, 'leaves', 'the', 'audit', 'user', 'empty', 'without', 'a', 'header'),
                    f'        {entity} entity = mapper.{oid}Entity(new {val}.{op["commandName"]}({command_args(op)}), null);\n        assertNull(entity.{getter(op["auditUser"])}());')
        else:
            first = op['fields'][0]
            others = [f for f in op['fields'][1:]]
            sentinel = entity_setup(M, 'entity', sentinel=True)
            body = (sentinel + f'\n        {val}.{op["commandName"]} command = new {val}.{op["commandName"]}({command_args(op, supplied={first["prop"]})});\n        mapper.{oid}Patch(entity, command, "audit-user");\n'
                    f'        assertEquals({typed_value(first["type"], first["prop"], first["enum"])}, entity.{getter(first["prop"])}());\n'
                    + ''.join(f'        assertEquals({typed_value(f["type"], f["prop"], f["enum"], True)}, entity.{getter(f["prop"])}());\n' for f in others).rstrip('\n'))
            add(f'{oid}:presence', mname(oid, 'applies', 'only', 'the', 'supplied', 'fields'), body)
            body = (entity_setup(M, 'entity', sentinel=True) + f'\n        {val}.{op["commandName"]} command = new {val}.{op["commandName"]}({command_args(op, supplied=set())});\n        mapper.{oid}Patch(entity, command, "audit-user");\n'
                    + ''.join(f'        assertEquals({typed_value(f["type"], f["prop"], f["enum"], True)}, entity.{getter(f["prop"])}());\n' for f in op['fields']).rstrip('\n'))
            add(f'{oid}:presence:absent', mname(oid, 'keeps', 'every', 'property', 'that', 'was', 'not', 'supplied'), body)
            if op['auditUser']:
                add(f'{oid}:audit:user', mname(oid, 'records', 'the', 'audit', 'user', 'on', 'update'),
                    f'        {entity} entity = new {entity}();\n        {val}.{op["commandName"]} command = new {val}.{op["commandName"]}({command_args(op, supplied=set())});\n        mapper.{oid}Patch(entity, command, "audit-user");\n        assertEquals("audit-user", entity.{getter(op["auditUser"])}());')
    text = (header(path, imports).replace('Val.Field', f'{val}.Field') + f'class {test} {{\n    private final {mp} mapper = new {mp}();\n\n' + '\n\n'.join(methods) + '\n}\n').replace('new Val.Field', f'new {val}.Field')
    return check_lines(text, test)


# --------------------------------------------------------------------------------------------------------------------------- specification
def specification_test(M, path, cov):
    test, spec = class_of(path), cls_name(M, 'jpa-specification')
    op = next(o for o in M['ops'] if o['kind'] == 'select')
    oid, entity, crit = op['id'], M['entity']['class'], cls_name(M, 'internal-query-model')
    imports = {M['entity']['fqn'], fqn(M, 'internal-query-model'), 'jakarta.persistence.criteria.CriteriaBuilder', 'jakarta.persistence.criteria.CriteriaQuery', 'jakarta.persistence.criteria.Expression',
               'jakarta.persistence.criteria.Path', 'jakarta.persistence.criteria.Predicate', 'jakarta.persistence.criteria.Root', 'java.math.BigDecimal', 'org.junit.jupiter.api.BeforeEach', 'org.junit.jupiter.api.Test',
               'static org.mockito.ArgumentMatchers.any', 'static org.mockito.ArgumentMatchers.anyChar', 'static org.mockito.ArgumentMatchers.anyString', 'static org.mockito.ArgumentMatchers.eq',
               'static org.mockito.Mockito.doReturn', 'static org.mockito.Mockito.mock', 'static org.mockito.Mockito.never', 'static org.mockito.Mockito.verify', 'static org.mockito.Mockito.when'}
    combinator = op['policy']['combinator']
    combine, empty = ('or', 'disjunction') if combinator == 'OR' else ('and', 'conjunction')
    methods = []

    def add(rule, name, body):
        methods.append(f'    @Test\n    void {name}() {{\n{body}\n    }}')
        cov.append((rule, f'{test}#{name}'))

    def criteria(values):
        args = [values.get(f['prop'], 'null') for f in op['filters']] + (['null', 'null'] if op['page'] else [])
        return f'new {crit}({", ".join(args)})'
    setup = ''
    fields = (f'    private Root<{entity}> root;\n    private CriteriaQuery<?> query;\n    private CriteriaBuilder builder;\n    private Path<Object> path;\n    private Predicate predicate;\n    private Predicate combined;\n'
              '    private Expression<String> lowered;\n\n    @BeforeEach\n    void mocks() {\n        root = mock(Root.class);\n        query = mock(CriteriaQuery.class);\n        builder = mock(CriteriaBuilder.class);\n'
              '        path = mock(Path.class);\n        predicate = mock(Predicate.class);\n        combined = mock(Predicate.class);\n        lowered = mock(Expression.class);\n'
              '        doReturn(path).when(root).get(anyString());\n        when(builder.equal(any(Expression.class), any(Object.class))).thenReturn(predicate);\n'
              '        when(builder.lower(any())).thenReturn(lowered);\n        when(builder.like(any(Expression.class), anyString(), anyChar())).thenReturn(predicate);\n'
              f'        when(builder.{combine}(any(Predicate[].class))).thenReturn(combined);\n    }}\n\n')
    for f in op['filters']:
        raw, expected = filter_sample(f)
        if f['match'] == 'exact':
            body = setup + f'        {spec}.matching({criteria({f["prop"]: expected})}).toPredicate(root, query, builder);\n        verify(builder).equal(path, {expected});\n        verify(builder, never()).like(any(Expression.class), anyString(), anyChar());'
            add(f'{oid}:match:{f["param"]}:spec', mname(oid, 'uses', 'equality', 'for', f['prop']), body)
        else:
            body = (setup + f'        {spec}.matching({criteria({f["prop"]: java_string("A%B_")})}).toPredicate(root, query, builder);\n'
                    f'        verify(builder).like(eq(lowered), eq("%a\\\\%b\\\\_%"), eq(\'\\\\\'));\n        verify(builder, never()).equal(any(Expression.class), any(Object.class));')
            add(f'{oid}:match:{f["param"]}:spec', mname(oid, 'uses', 'a', 'lowered', 'escaped', 'literal', 'substring', 'for', f['prop']), body)
    first = op['filters'][0]
    _, ex = filter_sample(first)
    add(f'{oid}:filter-policy:combinator', mname(oid, 'combines', 'supplied', 'filters', 'with', combinator), setup + f'        {spec}.matching({criteria({first["prop"]: ex})}).toPredicate(root, query, builder);\n        verify(builder).{combine}(any(Predicate[].class));')
    add(f'{oid}:filter-policy:empty', mname(oid, 'handles', 'empty', 'criteria', 'with', empty),
        setup + f'        when(builder.{empty}()).thenReturn(combined);\n        {spec}.matching({criteria({})}).toPredicate(root, query, builder);\n        verify(builder).{empty}();\n        verify(builder, never()).{combine}(any(Predicate[].class));')
    text = header(path, imports) + f'@SuppressWarnings("unchecked")\nclass {test} {{\n' + fields + '\n\n'.join(methods) + '\n}\n'
    return check_lines(text, test)


# --------------------------------------------------------------------------------------------------------------------------------- service
def service_test(M, path, cov):
    test = class_of(path)
    impl, val, mp, repo, trans = cls_name(M, 'application-service-implementation'), cls_name(M, 'business-validator'), cls_name(M, 'explicit-contract-data-mapper'), cls_name(M, 'spring-data-jpa-repository'), cls_name(M, 'data-access-error-translator')
    entity, exc = M['entity']['class'], cls_name(M, 'internal-typed-exception')
    comps = M['headers']['components']
    headers_new = 'new RequestHeaders(' + ', '.join(java_string(f'{c}-value') for c in comps) + ')'
    imports = {M['entity']['fqn'], fqn(M, 'request-headers-model'), fqn(M, 'internal-typed-exception'), fqn(M, 'business-validator'), fqn(M, 'explicit-contract-data-mapper'), fqn(M, 'spring-data-jpa-repository'),
               fqn(M, 'data-access-error-translator'), fqn(M, 'application-service-implementation'), 'java.math.BigDecimal', 'java.sql.SQLException', 'java.time.LocalDateTime', 'java.util.List', 'java.util.Optional',
               'org.junit.jupiter.api.BeforeEach', 'org.junit.jupiter.api.Test', 'org.junit.jupiter.api.extension.ExtendWith', 'org.mockito.ArgumentCaptor', 'org.mockito.Mock',
               'org.mockito.junit.jupiter.MockitoExtension', 'org.springframework.dao.DataIntegrityViolationException', 'org.springframework.dao.DataRetrievalFailureException',
               'org.springframework.dao.DataAccessResourceFailureException', 'org.springframework.dao.QueryTimeoutException', 'org.springframework.data.domain.Page', 'org.springframework.data.domain.PageImpl',
               'org.springframework.data.domain.Pageable', 'org.springframework.data.domain.Sort', 'org.springframework.data.jpa.domain.Specification', 'org.springframework.http.HttpStatus',
               'static org.junit.jupiter.api.Assertions.assertEquals', 'static org.junit.jupiter.api.Assertions.assertNotNull', 'static org.junit.jupiter.api.Assertions.assertNull',
               'static org.junit.jupiter.api.Assertions.assertThrows', 'static org.mockito.ArgumentMatchers.any', 'static org.mockito.Mockito.never', 'static org.mockito.Mockito.verify',
               'static org.mockito.Mockito.verifyNoInteractions', 'static org.mockito.Mockito.when'}
    for model_name in sorted({m for o in M['ops'] for m in (o['requestModel'], o['successModel']) if m}):
        imports.add(dto_fqn(M, model_name))
    methods, constants = [], []
    uses_dates = any(o['dateProp'] for o in M['ops'] if o['kind'] != 'select')
    if uses_dates:
        imports |= {'java.time.Clock', 'java.time.Instant', 'java.time.ZoneId', 'java.time.ZoneOffset', 'static org.junit.jupiter.api.Assertions.assertFalse'}
        constants += ['    private static final String FIXED_INSTANT = "2020-06-15T10:15:30Z";', '    private static final LocalDateTime FIXED_LOCAL = LocalDateTime.parse("2020-06-15T10:15:30");',
                      '    private static final String OTHER_ZONE = "Asia/Tokyo";', '    private static final LocalDateTime OTHER_ZONE_LOCAL = LocalDateTime.parse("2020-06-15T19:15:30");']
    new_service = f'new {impl}(repository, new {val}(), new {mp}(), new {trans}())'
    zone_clock = 'Clock.fixed(Instant.parse(FIXED_INSTANT), ZoneId.of(OTHER_ZONE))'

    def add(rule, name, body):
        methods.append(f'    @Test\n    void {name}() {{\n{body}\n    }}')
        cov.append((rule, f'{test}#{name}'))

    def status_cases(oid, call, stub, kinds):
        for rule_tag, thrown, status in kinds:
            add(f'{oid}:outcome:{status.value}', mname(oid, 'translates', rule_tag),
                f'        {stub.replace("THROW", thrown).lstrip()}\n        ServiceOperationException error = assertThrows(ServiceOperationException.class, () -> {call});\n        assertEquals(HttpStatus.{status.name}, error.getStatus());'.replace('ServiceOperationException', exc))
    from collections import namedtuple
    S = namedtuple('S', 'name value')
    timeout = ('a data access timeout to 504', 'new QueryTimeoutException("timeout")', S('GATEWAY_TIMEOUT', 504))
    unavailable = ('an unavailable database to 503', 'new DataAccessResourceFailureException("down")', S('SERVICE_UNAVAILABLE', 503))
    other = ('any other data access failure to 500', 'new DataRetrievalFailureException("other")', S('INTERNAL_SERVER_ERROR', 500))
    unique = ('a unique constraint violation to 409', 'new DataIntegrityViolationException("duplicate", new SQLException("duplicate", "23000", 1))', S('CONFLICT', 409))
    for op in M['ops']:
        oid = op['id']
        if op['kind'] == 'select':
            crit = cls_name(M, 'internal-query-model')
            first = op['filters'][0]
            raw, expected = filter_sample(first)
            args = select_args(op, values={first['param']: java_string(raw)})
            call = f'service.{oid}(HEADERS, {args})'
            row = entity_setup(M, 'found', enums={c['prop']: c['enum'] for c in op['columns'] if c['enum']})
            lp = cap(op['listProp'])
            add(f'{oid}:outcome:200', mname(oid, 'returns', 'the', 'mapped', 'rows'),
                row + f'\n        when(repository.findAll(any(Specification.class), any(Sort.class))).thenReturn(List.of(found));\n        {op["successModel"]} response = {call};\n'
                f'        assertEquals(HttpStatus.OK.value(), response.getCode());\n        assertEquals(1, response.getData().get{lp}().size());')
            add(f'{oid}:outcome:404', mname(oid, 'reports', 'not', 'found', 'when', 'no', 'row', 'matches'),
                f'        when(repository.findAll(any(Specification.class), any(Sort.class))).thenReturn(List.of());\n        ServiceOperationException error = assertThrows(ServiceOperationException.class, () -> {call});\n        assertEquals(HttpStatus.NOT_FOUND, error.getStatus());'.replace('ServiceOperationException', exc))
            add(f'{oid}:filter-policy:min', mname(oid, 'stops', 'before', 'the', 'repository', 'when', 'no', 'filter', 'is', 'supplied'),
                f'        assertThrows({exc}.class, () -> service.{oid}(HEADERS, {select_args(op)}));\n        verifyNoInteractions(repository);')
            add(f'{oid}:logging:null-headers', mname(oid, 'works', 'without', 'request', 'headers'),
                row + f'\n        when(repository.findAll(any(Specification.class), any(Sort.class))).thenReturn(List.of(found));\n        assertNotNull(service.{oid}(null, {args}));')
            if op['page']:
                lim, off = op['page']
                paged = select_args(op, values={first['param']: java_string(raw), lim: 'Integer.valueOf(REQUESTED_LIMIT)', off: 'Integer.valueOf(REQUESTED_OFFSET)'})
                constants += ['    private static final int REQUESTED_LIMIT = 2;', '    private static final int REQUESTED_OFFSET = 4;']
                add(f'{oid}:pagination', mname(oid, 'uses', 'the', 'absolute', 'offset', 'and', 'limit'),
                    row + f'\n        Page<{entity}> page = new PageImpl<>(List.of(found));\n        when(repository.findAll(any(Specification.class), any(Pageable.class))).thenReturn(page);\n        service.{oid}(HEADERS, {paged});\n'
                    f'        ArgumentCaptor<Pageable> pageable = ArgumentCaptor.forClass(Pageable.class);\n        verify(repository).findAll(any(Specification.class), pageable.capture());\n'
                    f'        assertEquals(REQUESTED_OFFSET, pageable.getValue().getOffset());\n        assertEquals(REQUESTED_LIMIT, pageable.getValue().getPageSize());\n        assertNotNull(pageable.getValue().getSort());')
            status_cases(oid, call, 'when(repository.findAll(any(Specification.class), any(Sort.class))).thenThrow(THROW);', [timeout, unavailable, other])
        elif op['kind'] == 'insert':
            req = build_request(M, op)
            call = f'service.{oid}(HEADERS, request)'
            captured = [f'        assertEquals({expected_for_input(M, op, f)}, saved.{getter(f["prop"])}());' for f in op['fields']]
            if op['auditUser']:
                captured.append(f'        assertEquals({java_string(f"userId-value")}, saved.{getter(op["auditUser"])}());')
            if op['dateProp']:
                captured.append(f'        assertEquals(FIXED_LOCAL, saved.{getter(op["dateProp"])}());')
                cov.append((f'{oid}:audit:date', f'{test}#{mname(oid, "persists", "the", "mapped", "entity", "once")}'))
            add(f'{oid}:outcome:200', mname(oid, 'persists', 'the', 'mapped', 'entity', 'once'),
                req.replace('        ' + op['requestModel'] + ' request', f'        {op["requestModel"]} request') + f'\n        {op["successModel"]} response = {call};\n        ArgumentCaptor<{entity}> captor = ArgumentCaptor.forClass({entity}.class);\n'
                f'        verify(repository).save(captor.capture());\n        {entity} saved = captor.getValue();\n        assertEquals(HttpStatus.OK.value(), response.getCode());\n        assertEquals({java_string(op["successMessage"])}, response.getMessage());\n' + '\n'.join(captured))
            if op['auditUser']:
                add(f'{oid}:audit:user', mname(oid, 'accepts', 'a', 'request', 'without', 'headers'),
                    req + f'\n        service.{oid}(null, request);\n        ArgumentCaptor<{entity}> captor = ArgumentCaptor.forClass({entity}.class);\n        verify(repository).save(captor.capture());\n        assertNull(captor.getValue().{getter(op["auditUser"])}());')
            if op['dateProp']:
                capture = f'        ArgumentCaptor<{entity}> captor = ArgumentCaptor.forClass({entity}.class);\n        verify(repository).save(captor.capture());\n'
                add(f'{oid}:audit:clock-zone', mname(oid, 'stamps', 'the', 'date', 'in', 'the', 'zone', 'of', 'the', 'clock'),
                    req + f'\n        service.setClock({zone_clock});\n        service.{oid}(HEADERS, request);\n' + capture + f'        assertEquals(OTHER_ZONE_LOCAL, captor.getValue().{getter(op["dateProp"])}());')
                add(f'{oid}:audit:default-clock', mname(oid, 'stamps', 'the', 'date', 'with', 'the', 'system', 'default', 'clock'),
                    req + f'\n        service = {new_service};\n        LocalDateTime before = LocalDateTime.now();\n        service.{oid}(HEADERS, request);\n        LocalDateTime after = LocalDateTime.now();\n        assertFalse(after.isBefore(before));\n' + capture
                    + f'        LocalDateTime stamped = captor.getValue().{getter(op["dateProp"])}();\n        assertFalse(stamped.isBefore(before));\n        assertFalse(stamped.isAfter(after));')
            bad_field = next((f for f in op['fields'] if f['type'] in NUMERIC), None)
            if bad_field:
                add(f'{oid}:conversion:{bad_field["input"]}', mname(oid, 'does', 'not', 'persist', 'an', 'invalid', bad_field['input']),
                    f'        {op["requestModel"]} request = new {op["requestModel"]}();\n        request.{setter(bad_field["input"])}("not-a-number");\n        assertThrows({exc}.class, () -> {call});\n        verify(repository, never()).save(any(Object.class));'.replace('any(Object.class)', f'any({entity}.class)'))
            stub = f'when(repository.save(any({entity}.class))).thenThrow(THROW);'
            status_cases(oid, call, req + '\n        ' + stub, [unique, timeout, unavailable, other])
        else:
            first = op['fields'][0]
            raw, _ = sample_for_input(M, op, first)
            raw = email_aware(M, op, first['input'], raw)
            one = f'        {op["requestModel"]} request = new {op["requestModel"]}();\n        request.{setter(first["input"])}({java_string(raw)});'
            call = f'service.{oid}(HEADERS, "1", request)'
            sentinel = entity_setup(M, 'stored', sentinel=True)
            others = [f for f in op['fields'][1:]]
            add(f'{oid}:outcome:200', mname(oid, 'changes', 'only', 'the', 'supplied', 'properties', 'of', 'the', 'loaded', 'entity'),
                sentinel + '\n' + one + f'\n        when(repository.findById(Long.valueOf(1))).thenReturn(Optional.of(stored));\n        {op["successModel"]} response = {call};\n        verify(repository).save(stored);\n'
                f'        assertEquals(HttpStatus.OK.value(), response.getCode());\n        assertEquals({java_string(op["successMessage"])}, response.getMessage());\n'
                f'        assertEquals({expected_for_input(M, op, first)}, stored.{getter(first["prop"])}());\n'
                + ''.join(f'        assertEquals({typed_value(f["type"], f["prop"], f["enum"], True)}, stored.{getter(f["prop"])}());\n' for f in others)
                + (f'        assertEquals("userId-value", stored.{getter(op["auditUser"])}());\n' if op['auditUser'] else '') + (f'        assertEquals(FIXED_LOCAL, stored.{getter(op["dateProp"])}());\n' if op['dateProp'] else '')
                + ''.join(f'        assertEquals({typed_value("LocalDateTime", p, None, True)}, stored.{getter(p)}());\n' for p, f in M['entity']['fields'].items() if f['javaType'] == 'LocalDateTime' and p != op['dateProp']).rstrip('\n'))
            if op['dateProp']:
                cov.append((f'{oid}:audit:date', f'{test}#{mname(oid, "changes", "only", "the", "supplied", "properties", "of", "the", "loaded", "entity")}'))
                found_stub = f'        when(repository.findById(Long.valueOf(1))).thenReturn(Optional.of(stored));\n'
                add(f'{oid}:audit:clock-zone', mname(oid, 'stamps', 'the', 'date', 'in', 'the', 'zone', 'of', 'the', 'clock'),
                    sentinel + '\n' + one + '\n' + found_stub + f'        service.setClock({zone_clock});\n        {call};\n        assertEquals(OTHER_ZONE_LOCAL, stored.{getter(op["dateProp"])}());')
                add(f'{oid}:audit:default-clock', mname(oid, 'stamps', 'the', 'date', 'with', 'the', 'system', 'default', 'clock'),
                    sentinel + '\n' + one + '\n' + found_stub + f'        service = {new_service};\n        LocalDateTime before = LocalDateTime.now();\n        {call};\n        LocalDateTime after = LocalDateTime.now();\n        assertFalse(after.isBefore(before));\n'
                    f'        assertFalse(stored.{getter(op["dateProp"])}().isBefore(before));\n        assertFalse(stored.{getter(op["dateProp"])}().isAfter(after));')
            add(f'{oid}:outcome:404', mname(oid, 'reports', 'not', 'found', 'and', 'does', 'not', 'save', 'a', 'missing', 'target'),
                one + f'\n        when(repository.findById(Long.valueOf(1))).thenReturn(Optional.empty());\n        ServiceOperationException error = assertThrows(ServiceOperationException.class, () -> {call});\n'
                f'        assertEquals(HttpStatus.NOT_FOUND, error.getStatus());\n        verify(repository, never()).save(any({entity}.class));'.replace('ServiceOperationException', exc))
            add(f'{oid}:rule:at-least-one', mname(oid, 'stops', 'before', 'the', 'repository', 'on', 'an', 'empty', 'patch'),
                f'        {op["requestModel"]} request = new {op["requestModel"]}();\n        assertThrows({exc}.class, () -> {call});\n        verifyNoInteractions(repository);')
            add(f'{oid}:conversion:id', mname(oid, 'rejects', 'an', 'invalid', 'identifier', 'before', 'any', 'data', 'access'),
                one + f'\n        assertThrows({exc}.class, () -> service.{oid}(HEADERS, "not-a-number", request));\n        verifyNoInteractions(repository);')
            status_cases(oid, call, sentinel + '\n' + one + f'\n        when(repository.findById(Long.valueOf(1))).thenReturn(Optional.of(stored));\n        when(repository.save(any({entity}.class))).thenThrow(THROW);', [unique, timeout, unavailable, other])
    clock_setup = '        service.setClock(Clock.fixed(Instant.parse(FIXED_INSTANT), ZoneOffset.UTC));\n' if uses_dates else ''
    text = (header(path, imports) + f'@ExtendWith(MockitoExtension.class)\nclass {test} {{\n    private static final RequestHeaders HEADERS = {headers_new};\n' + '\n'.join(dict.fromkeys(constants)) +
            f'\n    @Mock\n    private {repo} repository;\n    private {impl} service;\n\n    @BeforeEach\n    void setup() {{\n        service = {new_service};\n{clock_setup}    }}\n\n' + '\n\n'.join(methods) + '\n}\n')
    return check_lines(text, test)
