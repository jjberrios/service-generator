"""Deterministic generators of JUnit 5 / Mockito tests (materializer v3). Pure functions of the typed service model; they add (rule, test) pairs to a coverage list.

Nothing here names a service, field, endpoint or message: every value comes from the model built from the plan (contract examples, plan rules, column types).
Behavior the sources do not define is never asserted. Formatting follows the reference checkstyle.xml (constants for literals, indent 4, wrapped lines +8).
"""
import re

from renderers import Unsupported, class_of, package_of, java_string
from service_model import cap, snake, STATUS_ENUM
from java_components import header, fqn, dto_fqn, check_lines

NUMERIC = {'Long', 'Integer', 'BigDecimal'}


def mname(*parts) -> str:
    text = ''.join(cap(str(p).replace('-', ' ').replace('_', ' ').title().replace(' ', '')) if i else str(p)[:1].lower() + str(p)[1:] for i, p in enumerate(parts))
    return ''.join(c for c in text if c.isalnum())


def entity_sample(f_type, prop, enum=None, numeric=None):
    """Contract String sample for a mapped property and the typed Java expression it must convert to."""
    if f_type == 'String':
        v = f'value-{prop}'
        return v, java_string(v)
    if f_type == 'Long':
        return '1', 'Long.valueOf(1)'
    if f_type == 'Integer':
        v = str(enum[0]) if enum else '1'
        if not v.lstrip('-').isdigit():
            raise Unsupported(f'enum value {v!r} of an Integer property is not numeric')
        return v, f'Integer.valueOf({v})'
    if f_type == 'BigDecimal':
        v = '1.5' if (numeric is None or numeric['scale'] >= 1) else '1'
        return v, f'new BigDecimal("{v}")'
    raise Unsupported(f'no test sample for {f_type}')


def typed_value(f_type, prop, enum=None, sentinel=False):
    """A typed Java value for an entity/command property. The sentinel variant differs from the request samples, so unchanged properties are distinguishable."""
    if f_type == 'String':
        return java_string(f'{"stored" if sentinel else "value"}-{prop}')
    if f_type == 'Long':
        return 'Long.valueOf(2)' if sentinel else 'Long.valueOf(1)'
    if f_type == 'Integer':
        if sentinel:
            return 'Integer.valueOf(2)'
        return f'Integer.valueOf({str(enum[0]) if enum else "1"})'
    if f_type == 'BigDecimal':
        return 'new BigDecimal("2.5")' if sentinel else 'new BigDecimal("1.5")'
    if f_type == 'LocalDateTime':
        return 'LocalDateTime.parse("2020-01-01T00:00:00")'
    raise Unsupported(f'no sample for {f_type}')


def expected_for_input(M, op, f):
    """Typed expression a contract sample of an input field converts to (email fields use their valid address)."""
    raw = email_aware(M, op, f['input'], None)
    return java_string(raw) if raw else sample_for_input(M, op, f)[1]


def overflow_value(numeric):
    return '9' * (numeric['integerDigits'] + 1)


def boundary_value(numeric):
    return '9' * numeric['integerDigits'] + ('.' + '9' * numeric['scale'] if numeric['scale'] else '')


def getter(name):
    return 'get' + cap(name)


def setter(name):
    return 'set' + cap(name)


def request_fields(M, op):
    return {f['name']: f for f in M['models'][op['requestModel']]['fields']}


def sample_for_input(M, op, fld):
    enum = fld['enum']
    return entity_sample(fld['type'], fld['prop'], enum, fld.get('numeric'))


def email_aware(M, op, name, default):
    annotations = ' '.join(request_fields(M, op)[name].get('validationAnnotations') or [])
    return 'a@b.co' if '@Email' in annotations else default


def build_request(M, op, var='request', only=None, skip=()):
    """Statements that create a request DTO with valid sample values for the chosen fields (all by default)."""
    cls = op['requestModel']
    lines = [f'        {cls} {var} = new {cls}();']
    for f in op['fields']:
        if (only is not None and f['input'] not in only) or f['input'] in skip:
            continue
        raw, _ = sample_for_input(M, op, f)
        raw = email_aware(M, op, f['input'], raw)
        lines.append(f'        {var}.{setter(f["input"])}({java_string(raw)});')
    return '\n'.join(lines)


def select_args(op, chosen=None, values=None):
    """Argument list for a search call: every parameter null except the chosen ones."""
    out = []
    for p in op['params']['query']:
        if values and p['java'] in values:
            out.append(values[p['java']])
        else:
            out.append('null')
    return ', '.join(out)


def filter_sample(f):
    return entity_sample(f['type'], f['prop'], None, None)


def cls_name(M, kind):
    return class_of(M['paths'][kind])


def import_for(M, kind):
    return fqn(M, kind)


# =============================================================================================================================== validator
def validator_test(M, path, cov):
    val = cls_name(M, 'business-validator')
    test = class_of(path)
    exc = cls_name(M, 'internal-typed-exception')
    imports = {fqn(M, 'internal-typed-exception'), 'org.junit.jupiter.api.Test', 'org.springframework.http.HttpStatus', 'java.math.BigDecimal',
               'static org.junit.jupiter.api.Assertions.assertEquals', 'static org.junit.jupiter.api.Assertions.assertThrows', 'static org.junit.jupiter.api.Assertions.assertFalse',
               'static org.junit.jupiter.api.Assertions.assertTrue', 'static org.junit.jupiter.api.Assertions.assertNull'}
    methods = []

    def add(rule, name, body):
        methods.append(f'    @Test\n    void {name}() {{\n{body}\n    }}')
        cov.append((rule, f'{test}#{name}'))

    for op in M['ops']:
        oid = op['id']
        if op['kind'] == 'select':
            crit = cls_name(M, 'internal-query-model')
            imports.add(fqn(M, 'internal-query-model'))
            for f in op['filters']:
                raw, expected = filter_sample(f)
                param = f['param']
                body = (f'        {crit} criteria = validator.{oid}({select_args(op, values={param: java_string(raw)})});\n        assertEquals({expected}, criteria.{f["prop"]}());')
                add(f'{oid}:filter:{param}', mname(oid, 'accepts', param, 'filter'), body)
                add(f'{oid}:match:{param}', mname(oid, 'keeps', param, 'for', f['match'], 'matching'), body)
                if f['type'] in NUMERIC:
                    bad = (f'        ServiceOperationException error = assertThrows(ServiceOperationException.class,\n                () -> validator.{oid}({select_args(op, values={param: java_string("not-a-number")})}));\n'
                           '        assertEquals(HttpStatus.BAD_REQUEST, error.getStatus());').replace('ServiceOperationException', exc)
                    add(f'{oid}:conversion:{param}', mname(oid, 'rejects', 'non', 'numeric', param), bad)
                if f['type'] == 'BigDecimal':
                    from service_model import parse_numeric
                    num = parse_numeric(f.get('sql'))
                    if num:
                        over = (f'        assertThrows({exc}.class, () -> validator.{oid}({select_args(op, values={param: java_string(overflow_value(num))})}));\n'
                                f'        assertEquals(new BigDecimal({java_string(boundary_value(num))}), validator.{oid}({select_args(op, values={param: java_string(boundary_value(num))})}).{f["prop"]}());')
                        add(f'{oid}:range:{param}', mname(oid, 'enforces', param, 'column', 'precision'), over)
            if op['policy']['min'] == 0:
                add(f'{oid}:filter-policy:min', mname(oid, 'accepts', 'search', 'without', 'filters'),
                    f'        {crit} criteria = validator.{oid}({select_args(op)});\n        assertNull(criteria.{op["filters"][0]["prop"]}());')
            else:
                add(f'{oid}:filter-policy:min', mname(oid, 'rejects', 'search', 'without', 'filters'),
                    f'        ServiceOperationException error = assertThrows(ServiceOperationException.class, () -> validator.{oid}({select_args(op)}));\n        assertEquals(HttpStatus.BAD_REQUEST, error.getStatus());'.replace('ServiceOperationException', exc))
            first = op['filters'][0]
            raw, _ = filter_sample(first)
            for rule in op['rules']:
                if rule['kind'] == 'pagination-pairing':
                    lim, off = op['page']
                    only_limit = select_args(op, values={first['param']: java_string(raw), lim: 'Integer.valueOf(1)'})
                    only_offset = select_args(op, values={first['param']: java_string(raw), off: 'Integer.valueOf(1)'})
                    both = select_args(op, values={first['param']: java_string(raw), lim: 'Integer.valueOf(1)', off: 'Integer.valueOf(0)'})
                    body = (f'        assertThrows({exc}.class, () -> validator.{oid}({only_limit}));\n        assertThrows({exc}.class, () -> validator.{oid}({only_offset}));\n'
                            f'        {cls_name(M, "internal-query-model")} criteria = validator.{oid}({both});\n        assertEquals(Integer.valueOf(1), criteria.limit());\n        assertEquals(Integer.valueOf(0), criteria.offset());')
                    add(f'{oid}:rule:{rule["ruleId"]}', mname(oid, 'requires', 'pagination', 'parameters', 'together'), body)
                elif rule['kind'] == 'failed-validation-outcome':
                    cov.append((f'{oid}:rule:{rule["ruleId"]}', f'{test}#{mname(oid, "rejects", "search", "without", "filters")}'))
                elif rule['kind'] == 'validation-success-continues':
                    cov.append((f'{oid}:rule:{rule["ruleId"]}', f'{test}#{mname(oid, "accepts", first["param"], "filter")}'))
        else:
            cmd = f'{val}.{op["commandName"]}'
            req_cls = op['requestModel']
            imports.add(dto_fqn(M, req_cls))
            call = lambda r: f'validator.{oid}({"" if op["kind"] == "insert" else chr(34) + "1" + chr(34) + ", "}{r})'
            if op['kind'] == 'insert':
                checks = []
                for f in op['fields']:
                    _, expected = sample_for_input(M, op, f)
                    raw = email_aware(M, op, f['input'], None)
                    if raw:
                        expected = java_string(raw)
                    checks.append(f'        assertEquals({expected}, command.{f["prop"]}());')
                add(f'{oid}:mapping:fields', mname(oid, 'maps', 'every', 'request', 'field'), build_request(M, op) + f'\n        {cmd} command = {call("request")};\n' + '\n'.join(checks))
                for rule in op['rules']:
                    if rule['kind'] == 'conditional-required':
                        trigger = re.fullmatch(r'(\w+) is supplied', rule['when'].strip()).group(1)
                        req_fields = rule['requires']
                        trig_field = next(f for f in op['fields'] if f['input'] == trigger)
                        neg = (build_request(M, op, only={trigger}) + f'\n        assertThrows({exc}.class, () -> {call("request")});')
                        pos_ok = build_request(M, op, skip={trigger, *req_fields}) + f'\n        {cmd} command = {call("request")};\n        assertNull(command.{trig_field["prop"]}());'
                        add(f'{oid}:rule:{rule["ruleId"]}', mname(oid, 'requires', ' '.join(req_fields), 'when', trigger, 'is', 'supplied'), neg)
                        add(f'{oid}:rule:{rule["ruleId"]}', mname(oid, 'accepts', 'request', 'without', trigger, 'and', 'its', 'dependents'), pos_ok)
                    elif rule['kind'] == 'failed-validation-outcome':
                        cov.append((f'{oid}:rule:{rule["ruleId"]}', f'{test}#{mname(oid, "maps", "every", "request", "field")}'))
                    elif rule['kind'] == 'validation-success-continues':
                        cov.append((f'{oid}:rule:{rule["ruleId"]}', f'{test}#{mname(oid, "maps", "every", "request", "field")}'))
            else:
                add(f'{oid}:rule:at-least-one', mname(oid, 'rejects', 'an', 'empty', 'patch'),
                    f'        {req_cls} request = new {req_cls}();\n        ServiceOperationException error = assertThrows(ServiceOperationException.class, () -> {call("request")});\n        assertEquals(HttpStatus.BAD_REQUEST, error.getStatus());'.replace('ServiceOperationException', exc))
                first = op['fields'][0]
                raw, _ = sample_for_input(M, op, first)
                raw = email_aware(M, op, first['input'], raw)
                body = (f'        {req_cls} request = new {req_cls}();\n        request.{setter(first["input"])}({java_string(raw)});\n        {cmd} command = {call("request")};\n'
                        f'        assertEquals(Long.valueOf(1), command.id());\n        assertTrue(command.{first["prop"]}().supplied());\n'
                        + ''.join(f'        assertFalse(command.{f["prop"]}().supplied());\n' for f in op['fields'][1:]) .rstrip('\n'))
                add(f'{oid}:presence', mname(oid, 'tracks', 'only', 'the', 'supplied', 'fields'), body)
                add(f'{oid}:conversion:id', mname(oid, 'rejects', 'a', 'non', 'numeric', 'identifier'),
                    f'        {req_cls} request = new {req_cls}();\n        request.{setter(first["input"])}({java_string(raw)});\n        assertThrows({exc}.class, () -> validator.{oid}("not-a-number", request));')
                for rule in op['rules']:
                    if rule['kind'] == 'at-least-one-of':
                        cov.append((f'{oid}:rule:{rule["ruleId"]}', f'{test}#{mname(oid, "rejects", "an", "empty", "patch")}'))
                    elif rule['kind'] in ('failed-validation-outcome', 'validation-success-continues'):
                        cov.append((f'{oid}:rule:{rule["ruleId"]}', f'{test}#{mname(oid, "tracks", "only", "the", "supplied", "fields")}'))
            for f in op['fields']:
                if f['type'] in NUMERIC:
                    bad = (f'        {req_cls} request = new {req_cls}();\n        request.{setter(f["input"])}("not-a-number");\n'
                           f'        assertThrows({exc}.class, () -> {call("request")});')
                    add(f'{oid}:conversion:{f["input"]}', mname(oid, 'rejects', 'non', 'numeric', f['input']), bad)
                if f.get('numeric'):
                    num = f['numeric']
                    body = (build_request(M, op, 'request', skip={f['input']}) + f'\n        request.{setter(f["input"])}({java_string(overflow_value(num))});\n        assertThrows({exc}.class, () -> {call("request")});\n'
                            + build_request(M, op, 'fits', skip={f['input']}) + f'\n        fits.{setter(f["input"])}({java_string(boundary_value(num))});\n'
                            f'        assertEquals(new BigDecimal({java_string(boundary_value(num))}), {call("fits")}.{f["prop"]}(){".value()" if op["kind"] == "update" else ""});')
                    add(f'{oid}:range:{f["input"]}', mname(oid, 'enforces', f['input'], 'column', 'precision'), body)
                if f['enum']:
                    body = (f'        {req_cls} request = new {req_cls}();\n        request.{setter(f["input"])}("not-allowed");\n        assertThrows({exc}.class, () -> {call("request")});')
                    add(f'{oid}:enum:{f["input"]}', mname(oid, 'rejects', 'a', 'value', 'outside', 'the', f['input'], 'enum'), body)
    text = (header(path, imports) + f'/** Generated from the plan rules and the typed contract; every case is traced to a rule in the test traceability register. */\nclass {test} {{\n    private final {val} validator = new {val}();\n\n'
            + '\n\n'.join(methods) + '\n}\n')
    return check_lines(text, test)
