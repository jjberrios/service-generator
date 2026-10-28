"""Generated tests, part 4: declared parameter/body constraints executed through Bean Validation (method validation for controller parameters, bean validation for request DTOs)."""
import re

from renderers import java_string, Unsupported
from test_components import mname, setter

PALETTE = ('a', 'A', '1', 'x', '0', 'z', '-', '_')
PATTERN_VALID = ('a', 'A', '1', 'abc', 'ABC', '123', 'a1', 'A1', 'abc123', 'ABC123', 'a-b', '1-2', 'x@y.co', '2020-01-01', '00000000', 'ab', '12', '1234567890', 'true', 'S', 'N', 'Y', '0', 'x_y')
PATTERN_INVALID = ('', ' ', '!', '#', '@@', '*', '~', '%%', 'zzz-zzz', '###', ' a ', '--', '/', '?')
INLINE_MAX = 120
NUMERIC_LITERAL = {'Integer': 'Integer.valueOf("{n}")', 'Long': 'Long.valueOf("{n}")', 'BigDecimal': 'new BigDecimal("{n}")'}
EMAIL_OK, EMAIL_BAD = 'a@b.co', 'not-an-email'


def parse(annotations):
    """[(name, args)] from the Bean Validation strings of a parameter or DTO field; only what the sources declared."""
    out = []
    for text in annotations or []:
        m = re.fullmatch(r'@(\w+)(?:\((.*)\))?', text.strip(), re.S)
        if not m:
            continue
        name, raw = m.group(1), m.group(2) or ''
        args = {}
        if name == 'Pattern':
            r = re.fullmatch(r'regexp\s*=\s*"(.*)"', raw, re.S)
            args['regexp'] = re.sub(r'\\(.)', r'\1', r.group(1)) if r else None
        else:
            for k, v in re.findall(r'(\w+)\s*=\s*(-?\d+)', raw):
                args[k] = int(v)
            if name in ('Min', 'Max') and raw.strip().lstrip('-').isdigit():
                args['value'] = int(raw.strip())
        out.append((name, args))
    return out


def satisfies(constraints, text):
    for name, args in constraints:
        if name == 'Size' and not (args.get('min', 0) <= len(text) <= args.get('max', 1 << 31)):
            return False
        if name == 'Pattern':
            try:
                if args.get('regexp') is None or not re.fullmatch(args['regexp'], text):
                    return False
            except re.error:
                return False
        if name == 'NotBlank' and not text.strip():
            return False
        if name == 'Email' and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[A-Za-z]+', text):
            return False
    return True


def of_length(constraints, length):
    """A string of exactly that length satisfying every declared constraint, or None."""
    for ch in PALETTE:
        if satisfies(constraints, ch * length):
            return ch * length
    if length >= 1:
        for seed in PATTERN_VALID + (EMAIL_OK,):
            if len(seed) <= length and satisfies(constraints, (seed + 'a' * length)[:length]):
                return (seed + 'a' * length)[:length]
    return None


def any_valid(constraints):
    for seed in (EMAIL_OK,) + PATTERN_VALID:
        if satisfies(constraints, seed):
            return seed
    lo = max((a.get('min', 1) for n, a in constraints if n == 'Size'), default=1)
    return of_length(constraints, max(lo, 1))


def literal(text, consts):
    if len(text) <= INLINE_MAX:
        return java_string(text)
    name = f'LENGTH_{len(consts) + 1}'
    consts[name] = len(text)
    return f'"{text[0]}".repeat({name})'


def string_cases(constraints, consts):
    """({annotation: [(label, kind, expr)]}, {annotation: reason}) for a String value. kind is 'valid' or 'invalid'."""
    cases, reasons = {}, {}
    for name, args in constraints:
        rows = cases.setdefault(name, [])
        others = [c for c in constraints if c[0] != name]
        if name == 'Size':
            lo, hi = args.get('min', 0), args.get('max')
            for label, length in (('lower-bound', lo), ('upper-bound', hi)):
                if length is None or (label == 'lower-bound' and length == 0 and any(n == 'Pattern' for n, _ in constraints)):
                    continue
                sample = of_length(constraints, length)
                if sample is None:
                    reasons[name] = f'no string of length {length} satisfies the other declared constraints'
                else:
                    rows.append((label, 'valid', literal(sample, consts)))
            if lo >= 1:
                rows.append(('below-minimum', 'invalid', literal('a' * (lo - 1), consts)))
            if hi is not None:
                rows.append(('above-maximum', 'invalid', literal('a' * (hi + 1), consts)))
        elif name == 'Pattern':
            regexp = args.get('regexp')
            try:
                valid = next((s for s in PATTERN_VALID if satisfies(constraints, s)), None)
                invalid = next((s for s in PATTERN_INVALID if regexp is not None and not re.fullmatch(regexp, s)), None)
            except re.error:
                valid = invalid = None
            if valid is not None:
                rows.append(('matching-value', 'valid', literal(valid, consts)))
            if invalid is not None:
                rows.append(('non-matching-value', 'invalid', literal(invalid, consts)))
            if valid is None or invalid is None:
                reasons[name] = 'no sample could be derived from the declared pattern' if not rows else 'only one side of the declared pattern could be sampled'
        elif name == 'NotBlank':
            base = any_valid(others + [('NotBlank', {})])
            if base:
                rows.append(('present-value', 'valid', literal(base, consts)))
            rows += [('empty-value', 'invalid', '""'), ('blank-value', 'invalid', '"   "')]
        elif name == 'Email':
            rows += [('well-formed-address', 'valid', java_string(EMAIL_OK)), ('malformed-address', 'invalid', java_string(EMAIL_BAD))]
        elif name in ('Min', 'Max'):
            reasons[name] = f'@{name} on a string value is not exercised'
        if not rows and name not in reasons and name != 'NotNull':
            reasons[name] = 'no sample could be derived from the declared constraint'
        if name == 'NotNull':
            cases.pop(name, None)
    return {k: v for k, v in cases.items() if v}, reasons


def numeric_cases(ptype, constraints):
    cases, reasons = {}, {}
    template = NUMERIC_LITERAL.get(ptype)
    for name, args in constraints:
        value = args.get('value')
        if name not in ('Min', 'Max') or value is None or template is None:
            reasons[name] = f'@{name} on {ptype} is not exercised' if template is None else f'@{name} without an integer value is not exercised'
            continue
        edge, beyond = (value, value - 1) if name == 'Min' else (value, value + 1)
        cases[name] = [('boundary-value', 'valid', template.format(n=edge)), ('beyond-boundary', 'invalid', template.format(n=beyond))]
    return cases, reasons


# ---------------------------------------------------------------------------------------------------------------------------------- emission
def parameter_methods(M, op, api_cls, add, cov, imports, consts, test):
    """Methods exercising the constraints declared on path/query parameters through method validation."""
    declared = [p for kind in ('path', 'query', 'header') for p in op['params'][kind]]
    positions = len(declared) + (1 if op['requestModel'] else 0)
    oid = op['id']
    any_declared = False
    for index, p in enumerate(declared):
        constraints = parse(p['annotations'])
        if not constraints:
            continue
        any_declared = True
        cases, reasons = string_cases(constraints, consts) if p['type'] == 'String' else numeric_cases(p['type'], constraints)
        for name, reason in reasons.items():
            cov.append((f'{oid}:param:{p["name"]}:{name}', None, reason))
        for name, rows in cases.items():
            imports.add(f'jakarta.validation.constraints.{name}')
            if p['type'] == 'BigDecimal':
                imports.add('java.math.BigDecimal')
            for label, kind, expr in rows:
                args = ', '.join(expr if i == index else 'null' for i in range(positions))
                call = f'violations({java_string(oid)}, new Object[] {{{args}}})'
                if kind == 'valid':
                    body = f'        assertFalse(violates({call}, null, {name}.class));'
                    title = mname(oid, p['name'], 'accepts', label, 'for', name)
                else:
                    body = f'        assertTrue(violates({call}, null, {name}.class));'
                    title = mname(oid, p['name'], 'rejects', label, 'for', name)
                add(f'{oid}:param:{p["name"]}:{name}', title, body)
    if any_declared:
        absent = ', '.join(['null'] * positions)
        add(f'{oid}:param:absent', mname(oid, 'accepts', 'absent', 'optional', 'parameters'), f'        assertTrue(violations({java_string(oid)}, new Object[] {{{absent}}}).isEmpty());')


def body_methods(M, op, add, cov, imports, consts, seen):
    """Methods exercising String constraints declared on request DTO fields through Bean Validation."""
    model = op['requestModel']
    if not model or model in seen:
        return
    seen.add(model)
    oid = op['id']
    for f in M['models'][model]['fields']:
        constraints = [c for c in parse(f.get('validationAnnotations')) if c[0] != 'NotNull']
        if not constraints:
            continue
        if f['javaType'] != 'String':
            for name, _ in constraints:
                cov.append((f'{oid}:body:{f["name"]}:{name}', None, f'@{name} on {f["javaType"]} is not exercised'))
            continue
        cases, reasons = string_cases(constraints, consts)
        for name, reason in reasons.items():
            cov.append((f'{oid}:body:{f["name"]}:{name}', None, reason))
        for name, rows in cases.items():
            imports.add(f'jakarta.validation.constraints.{name}')
            for label, kind, expr in rows:
                setup = f'        {model} body = new {model}();\n        body.{setter(f["name"])}({expr});\n'
                check = f'violates(validator.validate(body), {java_string(f["name"])}, {name}.class)'
                body = setup + (f'        assertFalse({check});' if kind == 'valid' else f'        assertTrue({check});')
                add(f'{oid}:body:{f["name"]}:{name}', mname(oid, 'body', f['name'], 'accepts' if kind == 'valid' else 'rejects', label, 'for', name), body)


# ---------------------------------------------------------------------------------------------------------------------------- header constraints
def header_constraints(M, name):
    """Every constraint the contract declares for a header name, across all operations (only declared ones)."""
    seen, out = set(), []
    for op in M['ops']:
        for p in op['params']['header']:
            if p['name'] == name:
                for c in parse(p['annotations']):
                    key = (c[0], tuple(sorted(c[1].items())))
                    if key not in seen:
                        seen.add(key)
                        out.append(c)
    return out


def header_sample(M, p, consts):
    """Java expression of a header value that satisfies every declared constraint of that header; unconstrained headers keep the neutral sample."""
    constraints = header_constraints(M, p['name'])
    if not constraints:
        return java_string('value-of-' + p['java'])
    if p['type'] != 'String' or any(n in ('Min', 'Max') for n, _ in constraints):
        raise Unsupported(f'header {p["name"]}: constraints on a non-text header or @Min/@Max on a header value are not supported by this materializer version')
    sample = any_valid(constraints)
    if sample is None or not satisfies(constraints, sample):
        raise Unsupported(f'header {p["name"]}: no value satisfying every declared constraint could be derived')
    return literal(sample, consts)


def header_mvc_methods(M, op, add, imports, consts, perform_with, stub, success, test_kinds=('valid', 'invalid')):
    """MockMvc tests (controller behind MethodValidationInterceptor, like MethodValidationPostProcessor in production): invalid header -> 400 and no service call; boundary header -> 200."""
    oid = op['id']
    for p in op['params']['header']:
        constraints = parse(p['annotations'])
        if not constraints or p['type'] != 'String':
            continue
        cases, _ = string_cases(constraints, consts)
        for name, rows in cases.items():
            picked = {}
            for label, kind, expr in rows:
                picked.setdefault(kind, (label, expr))
            if 'invalid' in picked:
                label, expr = picked['invalid']
                add(f'{oid}:param:{p["name"]}:{name}', mname(oid, 'header', p['name'], 'over', 'http', 'rejects', label, 'for', name),
                    f'        {perform_with(p["name"], expr)}\n                .andExpect(status().isBadRequest())\n                .andExpect(jsonPath("$.code").value(HttpStatus.BAD_REQUEST.value()));\n        verifyNoInteractions(service);')
            if 'valid' in picked:
                label, expr = picked['valid']
                add(f'{oid}:param:{p["name"]}:{name}', mname(oid, 'header', p['name'], 'over', 'http', 'accepts', label, 'for', name),
                    f'        {success}\n        {stub}.thenReturn(body);\n        {perform_with(p["name"], expr)}\n                .andExpect(status().isOk());')
