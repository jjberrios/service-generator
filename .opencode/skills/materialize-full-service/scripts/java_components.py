"""Java renderers for the functional components (materializer v2). Pure functions of the typed service model from service_model.build.

Formatting follows the reference checkstyle.xml (indent 4, annotation-array children at +2, wrapped lines +8, no magic numbers, constants for literals,
switch expressions assigned to locals). All business texts come from the model (contract examples / plan); nothing is domain specific.
"""
import re

from renderers import Unsupported, class_of, package_of, java_string
from service_model import cap, snake, ANNOTATION_IMPORTS, HTTP_VERBS, STATUS_ENUM

MAX_LINE = 240


def imports_block(names) -> str:
    lines = sorted({n for n in names if n})
    return '\n'.join(f'import {n};' for n in lines)


def header(path, names) -> str:
    block = imports_block(names)
    return f'package {package_of(path)};\n\n' + (block + '\n\n' if block else '')


def chunks(text: str, size=110) -> list:
    words, lines, current = text.split(' '), [], ''
    for word in words:
        if current and len(current) + len(word) + 1 > size:
            lines.append(current + ' ')
            current = word
        else:
            current = f'{current} {word}' if current else word
    lines.append(current)
    return lines


def string_expr(text: str, first_indent: int, plus_indent: int) -> str:
    """A Java string literal; long text is split into `+` continuation lines (operator at line start, indent per OperatorWrap/Indentation)."""
    parts = chunks(text)
    out = java_string(parts[0])
    for part in parts[1:]:
        out += '\n' + ' ' * plus_indent + '+ ' + java_string(part)
    return out


def check_lines(text, label):
    for line in text.split('\n'):
        if len(line) > MAX_LINE:
            raise Unsupported(f'{label}: a generated line exceeds {MAX_LINE} characters')
    return text


def fqn(M, kind):
    p = M['paths'][kind]
    return f'{package_of(p)}.{class_of(p)}'


def dto_fqn(M, name):
    p = M['dtoPaths'][name]
    return f'{package_of(p)}.{name}'


# ------------------------------------------------------------------------------------------------------------------------------ DTOs
IGNORED_NUMBERS = {-1, 0, 1, 2, 4, 200, 201, 400, 401, 403, 404, 418, 500, 1000}


def constantize(annotation, base, constants):
    """Numbers in @Size/@Min/@Max that the reference Checkstyle MagicNumber does not ignore become named constants (declared limits are unchanged)."""
    m = re.fullmatch(r'@(Size|Min|Max)\((.*)\)', annotation.strip(), re.S)
    if not m:
        return annotation
    kind, args = m.group(1), m.group(2)
    kind_type = 'int' if kind == 'Size' else 'long'

    def literal(n):
        return f'{n}L' if not -2147483648 <= n <= 2147483647 else str(n)

    def declare(name, n):
        constants[name] = f'{kind_type} {name} = {literal(n)};'
        return name
    if re.fullmatch(r'-?\d+', args.strip()):
        n = int(args)
        return annotation if n in IGNORED_NUMBERS else f'@{kind}({declare(f"{base}_{kind.upper()}", n)})'

    def each(mm):
        n = int(mm.group(2))
        return mm.group(0) if n in IGNORED_NUMBERS else f'{mm.group(1)} = {declare(f"{base}_{kind.upper()}_{mm.group(1).upper()}", n)}'
    return f'@{kind}(' + re.sub(r'(\w+) = (-?\d+)', each, args) + ')'


def dto(M, path):
    name = class_of(path)
    model = M['models'][name]
    scope = model['requestResponseScope']
    patch = any(o['kind'] == 'update' and o['requestModel'] == name for o in M['ops'])
    request = 'request' in scope
    imports = set()
    members, accessors, consts = [], [], {}
    for f in model['fields']:
        fname, ftype = f['name'], f['javaType']
        for a in f.get('validationAnnotations') or []:
            imports.add(ANNOTATION_IMPORTS[re.match(r'@(\w+)', a).group(1)])
        if ftype == 'BigDecimal':
            imports.add('java.math.BigDecimal')
        if ftype.startswith('List<'):
            imports.add('java.util.List')
        lines = [f'    {constantize(a, snake(fname), consts)}' for a in f.get('validationAnnotations') or []]
        enum = (f.get('declaredConstraints') or {}).get('enum')
        if request and enum:
            imports.add('io.swagger.v3.oas.annotations.media.Schema')
            lines.append('    @Schema(allowableValues = {' + ', '.join(java_string(str(v)) for v in enum) + '})')
        lines.append(f'    private {ftype} {fname};')
        members.append('\n'.join(lines))
        getter = f'    public {ftype} get{cap(fname)}() {{\n        return {fname};\n    }}\n'
        if request:
            imports |= {'com.fasterxml.jackson.annotation.JsonSetter', 'com.fasterxml.jackson.annotation.Nulls'}
            nullable = (f.get('declaredConstraints') or {}).get('nullable') is True
            annotation = '' if nullable else '    @JsonSetter(nulls = Nulls.FAIL)\n'
            track = f'        suppliedFields.add({java_string(fname)});\n' if patch else ''
            setter = f'{annotation}    public void set{cap(fname)}({ftype} {fname}) {{\n{track}        this.{fname} = {fname};\n    }}\n'
        else:
            setter = f'    public void set{cap(fname)}({ftype} {fname}) {{\n        this.{fname} = {fname};\n    }}\n'
        accessors.append(getter + '\n' + setter)
    top = ''
    if request:
        imports.add('com.fasterxml.jackson.annotation.JsonInclude')
        top = '@JsonInclude(JsonInclude.Include.NON_NULL)\n'
    if patch:
        imports |= {'com.fasterxml.jackson.annotation.JsonIgnore', 'java.util.LinkedHashSet', 'java.util.Set'}
        members.insert(0, '    @JsonIgnore\n    private final Set<String> suppliedFields = new LinkedHashSet<>();')
        accessors.append('    @JsonIgnore\n    public Set<String> getSuppliedFields() {\n        return suppliedFields;\n    }\n')
    body = '\n\n'.join(members) + '\n\n' + '\n'.join(accessors)
    constant_block = ''.join(f'    private static final {consts[k][:-1]};\n' for k in sorted(consts)) + ('\n' if consts else '')
    return header(path, imports) + top + f'public class {name} {{\n' + constant_block + body.rstrip('\n') + '\n}\n'


# ------------------------------------------------------------------------------------------------------------------------ API and controller
def param_decl(p, kind):
    annotations = ' '.join(p['annotations'])
    prefix = annotations + ' ' if annotations else ''
    if kind == 'query':
        return f'{prefix}@RequestParam(name = "{p["name"]}", required = {str(p["required"]).lower()}) {p["type"]} {p["java"]}'
    if kind == 'header':
        return f'{prefix}@RequestHeader(name = "{p["name"]}", required = {str(p["required"]).lower()}) {p["type"]} {p["java"]}'
    return f'{prefix}@PathVariable(name = "{p["name"]}", required = true) {p["type"]} {p["java"]}'


def signature_params(op, constants=None):
    def shown(p):
        if constants is None:
            return p
        return dict(p, annotations=[constantize(a, f'{snake(op["id"])}_{snake(p["java"])}', constants) for a in p['annotations']])
    out = [(param_decl(shown(p), 'path'), p) for p in op['params']['path']] + [(param_decl(shown(p), 'query'), p) for p in op['params']['query']]
    out += [(param_decl(shown(p), 'header'), p) for p in op['params']['header']]
    return out


def _doc_text(text) -> str:
    return ' '.join(str(text).split()).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('*/', '*&#47;').replace('@', '&#64;')


def _doc_lines(prefix: str, text, indent: str = '     * ') -> list:
    words = [prefix + _doc_text(text)] if prefix else [_doc_text(text)]
    parts = chunks(words[0], 110)
    first = indent[:-2] if False else indent
    return [first + parts[0].strip()] + [indent + ('  ' if prefix else '') + p.strip() for p in parts[1:]]


def api_javadoc(op, params):
    summary = op['summary'] or f'Expone la operación {op["id"]} del contrato.'
    lines = ['    /**'] + _doc_lines('', summary)
    if op['description'] and op['description'].strip() != summary.strip():
        lines += ['     * <p>'] + _doc_lines('', op['description']) + ['     * </p>']
    lines.append('     *')
    for p in params:
        text = p.get('description') or f'Valor de {p["name"]} definido en el contrato.'
        lines += _doc_lines(f'@param {p["java"]} ', text)
    if op['requestModel']:
        lines += _doc_lines('@param request ', 'cuerpo de la solicitud definido en el contrato')
    lines += _doc_lines('@return ', f'respuesta HTTP con el modelo {op["successModel"]} definido en el contrato')
    lines.append('     */')
    return lines


def api_interface(M, path):
    name = class_of(path)
    imports = {'org.springframework.http.ResponseEntity', 'io.swagger.v3.oas.annotations.Operation', 'io.swagger.v3.oas.annotations.media.Content', 'io.swagger.v3.oas.annotations.media.Schema',
               'io.swagger.v3.oas.annotations.responses.ApiResponse', 'io.swagger.v3.oas.annotations.responses.ApiResponses', 'org.springframework.web.bind.annotation.RequestHeader'}
    validated = False
    methods = []
    api_constants = {}
    for op in M['ops']:
        imports.add(f'org.springframework.web.bind.annotation.{HTTP_VERBS[op["method"]]}')
        mapping = f'@{HTTP_VERBS[op["method"]]}(path = {java_string(op["path"])}' + (', consumes = {"application/json"}' if op['requestModel'] else '') + ', produces = {"application/json"})'
        flat_params = [p for w in ('path', 'query', 'header') for p in op['params'][w]]
        lines = api_javadoc(op, flat_params) + ['    ' + mapping]
        if op['summary'] or op['description']:
            parts = []
            if op['summary']:
                parts.append(f'summary = {java_string(op["summary"])}')
            if op['description']:
                parts.append('description = ' + string_expr(op['description'], 12, 20))
            lines.append('    @Operation(' + (',\n            '.join(parts)) + ')')
        lines.append('    @ApiResponses({')
        entries = []
        for code in sorted(op['statuses']):
            r = op['responses'].get(code)
            model = (r or {}).get('model')
            description = (r or {}).get('description') or 'Effective contract response'
            if not model:
                raise Unsupported(f'{op["id"]}: response {code} has no schema in the plan')
            imports.add(dto_fqn(M, model))
            entries.append(f'      @ApiResponse(responseCode = "{code}", description = {java_string(description)}, content = @Content(mediaType = "application/json", schema = @Schema(implementation = {model}.class)))')
        lines.append(',\n'.join(entries))
        lines.append('    })')
        imports.add(dto_fqn(M, op['successModel']))
        decls = []
        for text, p in signature_params(op, api_constants):
            kind = 'path' if p in op['params']['path'] else 'query' if p in op['params']['query'] else 'header'
            if p['annotations']:
                validated = True
                for a in p['annotations']:
                    imports.add(ANNOTATION_IMPORTS[re.match(r'@(\w+)', a).group(1)])
            imports.add({'path': 'org.springframework.web.bind.annotation.PathVariable', 'query': 'org.springframework.web.bind.annotation.RequestParam', 'header': 'org.springframework.web.bind.annotation.RequestHeader'}[kind])
            decls.append(text)
        if op['requestModel']:
            imports |= {'jakarta.validation.Valid', 'org.springframework.web.bind.annotation.RequestBody', dto_fqn(M, op['requestModel'])}
            decls.append(f'@Valid @RequestBody {op["requestModel"]} request')
        lines.append(f'    ResponseEntity<{op["successModel"]}> {op["id"]}(\n' + ',\n'.join('            ' + d for d in decls) + ');')
        methods.append('\n'.join(lines))
    top = '@Validated\n' if validated else ''
    if validated:
        imports.add('org.springframework.validation.annotation.Validated')
    constant_block = ''.join(f'    public static final {api_constants[k]}\n' for k in sorted(api_constants)) + ('\n' if api_constants else '')
    doc = ['/**', ' * Define el contrato de los endpoints REST expuestos por el microservicio.', ' * <p>', ' * Agrupa las operaciones disponibles para los consumidores externos, con los parámetros,',
           ' * encabezados y modelos de respuesta definidos en el contrato OpenAPI.', ' * </p>', ' */']
    text = header(path, imports) + '\n'.join(doc) + '\n' + top + f'public interface {name} {{\n' + constant_block + '\n\n'.join(methods) + '\n}\n'
    return check_lines(text, name)


def controller(M, path):
    name = class_of(path)
    api, svc_path = M['api'], M['paths']['application-service-contract']
    service_type = class_of(svc_path)
    imports = {f'{api["package"]}.{api["name"]}', f'{package_of(svc_path)}.{service_type}', fqn(M, 'request-headers-model'), 'org.springframework.http.ResponseEntity',
               'org.springframework.web.bind.annotation.RestController', 'lombok.extern.slf4j.Slf4j', 'lombok.RequiredArgsConstructor'}
    methods = []
    components = M['headers']['components']
    for op in M['ops']:
        imports.add(dto_fqn(M, op['successModel']))
        plain = []
        for _, p in signature_params(op):
            plain.append(f'{p["type"]} {p["java"]}')
        if op['requestModel']:
            imports.add(dto_fqn(M, op['requestModel']))
            plain.append(f'{op["requestModel"]} request')
        args = ',\n            '.join(plain)
        log = op['logging']
        role_args = [op['headerByRole'][a] for a in log['controllerArgs']]
        entry = f'        log.info({java_string(log["controllerMessage"])}, {", ".join(role_args)});'
        headers_args = ', '.join(op['headerByRole'][c] for c in components)
        call_args = ['headers'] + [p['java'] for p in op['params']['path']] + [p['java'] for p in op['params']['query']] + (['request'] if op['requestModel'] else [])
        methods.append(f'    @Override\n    public ResponseEntity<{op["successModel"]}> {op["id"]}(\n            {args}) {{\n{entry}\n'
                       f'        RequestHeaders headers = new RequestHeaders({headers_args});\n        return ResponseEntity.ok(service.{op["id"]}({", ".join(call_args)}));\n    }}')
    text = (header(path, imports) + f'@RestController\n@Slf4j\n@RequiredArgsConstructor\npublic class {name} implements {api["name"]} {{\n    private final {service_type} service;\n\n' + '\n\n'.join(methods) + '\n}\n')
    return check_lines(text, name)


# ------------------------------------------------------------------------------------------------------------------------ query model etc.
def query_model(M, path):
    op = next(o for o in M['ops'] if o['kind'] == 'select')
    imports = set()
    comps = []
    for f in op['filters']:
        if f['type'] == 'BigDecimal':
            imports.add('java.math.BigDecimal')
        comps.append(f'{f["type"]} {f["prop"]}')
    if op['page']:
        comps += ['Integer limit', 'Integer offset']
    return header(path, imports) + f'/** Internal typed query values; pagination controls are not business filters. */\npublic record {class_of(path)}(\n        ' + ',\n        '.join(comps) + ') {\n}\n'


def pageable(M, path):
    return (f'package {package_of(path)};\n\nimport org.springframework.data.domain.Pageable;\nimport org.springframework.data.domain.Sort;\n\n'
            f'/** Pageable with an arbitrary absolute offset; the page size is the requested limit. */\npublic class {class_of(path)} implements Pageable {{\n'
            '    private final long offset;\n    private final int limit;\n    private final Sort sort;\n\n'
            f'    public {class_of(path)}(long offset, int limit, Sort sort) {{\n        if (offset < 0 || limit < 1) {{\n            throw new IllegalArgumentException("offset must be non-negative and limit positive.");\n        }}\n'
            '        this.offset = offset;\n        this.limit = limit;\n        this.sort = sort;\n    }\n\n'
            '    @Override\n    public int getPageNumber() {\n        return (int) (offset / limit);\n    }\n\n'
            '    @Override\n    public int getPageSize() {\n        return limit;\n    }\n\n'
            '    @Override\n    public long getOffset() {\n        return offset;\n    }\n\n'
            '    @Override\n    public Sort getSort() {\n        return sort;\n    }\n\n'
            f'    @Override\n    public Pageable next() {{\n        return new {class_of(path)}(offset + limit, limit, sort);\n    }}\n\n'
            f'    @Override\n    public Pageable previousOrFirst() {{\n        return hasPrevious() ? new {class_of(path)}(Math.max(0, offset - limit), limit, sort) : first();\n    }}\n\n'
            f'    @Override\n    public Pageable first() {{\n        return new {class_of(path)}(0, limit, sort);\n    }}\n\n'
            f'    @Override\n    public Pageable withPage(int pageNumber) {{\n        return new {class_of(path)}((long) pageNumber * limit, limit, sort);\n    }}\n\n'
            '    @Override\n    public boolean hasPrevious() {\n        return offset > 0;\n    }\n}\n')


def specification(M, path):
    op = next(o for o in M['ops'] if o['kind'] == 'select')
    entity, name = M['entity']['class'], class_of(path)
    crit = class_of(M['paths']['internal-query-model'])
    imports = {M['entity']['fqn'], f'{package_of(M["paths"]["internal-query-model"])}.{crit}', 'jakarta.persistence.criteria.CriteriaBuilder', 'jakarta.persistence.criteria.Expression',
               'jakarta.persistence.criteria.Predicate', 'jakarta.persistence.criteria.Root', 'java.util.ArrayList', 'java.util.List', 'java.util.Locale', 'org.springframework.data.jpa.domain.Specification'}
    body = []
    for fx in op['fixed']:
        lit = java_string(fx['value']) if fx['type'] == 'String' else (f'{fx["value"]}L' if fx['type'] == 'Long' else str(fx['value']))
        body.append(f'            predicates.add(builder.equal(root.get({java_string(fx["prop"])}), {lit}));')
    for f in op['filters']:
        if f['match'] == 'exact':
            body.append(f'            if (criteria.{f["prop"]}() != null) {{\n                predicates.add(builder.equal(root.get({java_string(f["prop"])}), criteria.{f["prop"]}()));\n            }}')
        else:
            body.append(f'            contains(predicates, builder, root, {java_string(f["prop"])}, criteria.{f["prop"]}());')
    combine = 'builder.or' if op['policy']['combinator'] == 'OR' else 'builder.and'
    empty = 'builder.disjunction()' if op['policy']['combinator'] == 'OR' else 'builder.conjunction()'
    has_contains = any(f['match'] == 'contains' for f in op['filters'])
    kinds = 'equality for exact filters' + ('; text filters are case-insensitive literal substring matches' if has_contains else '')
    escape_const = "    private static final char ESCAPE = '\\\\';\n\n" if has_contains else ''
    contains_helpers = (f'\n\n    private static void contains(List<Predicate> predicates, CriteriaBuilder builder, Root<{entity}> root, String attribute, String value) {{\n        if (value != null) {{\n'
                        '            Expression<String> path = root.get(attribute);\n            predicates.add(builder.like(builder.lower(path), "%" + escape(value.toLowerCase(Locale.ROOT)) + "%", ESCAPE));\n        }\n    }\n\n'
                        '    static String escape(String value) {\n        return value.replace("\\\\", "\\\\\\\\").replace("%", "\\\\%").replace("_", "\\\\_");\n    }') if has_contains else ''
    return (header(path, imports) + f'/** Dynamic search specification: fixed and supplied filters are combined with {op["policy"]["combinator"]}; {kinds}. */\n'
            f'public final class {name} {{\n{escape_const}    private {name}() {{\n    }}\n\n'
            f'    public static Specification<{entity}> matching({crit} criteria) {{\n        return (root, query, builder) -> {{\n            List<Predicate> predicates = new ArrayList<>();\n'
            + '\n'.join(body) + f'\n            return predicates.isEmpty() ? {empty} : {combine}(predicates.toArray(new Predicate[0]));\n        }};\n    }}'
            + contains_helpers + '\n}\n')


def translator(M, path):
    exc = class_of(M['paths']['internal-typed-exception'])
    return (header(path, {f'{package_of(M["paths"]["internal-typed-exception"])}.{exc}', 'java.sql.SQLException', 'java.sql.SQLNonTransientConnectionException', 'java.sql.SQLRecoverableException',
                          'java.sql.SQLTimeoutException', 'java.sql.SQLTransientConnectionException', 'java.util.ArrayDeque', 'java.util.Collections', 'java.util.IdentityHashMap', 'java.util.Set',
                          'org.hibernate.exception.JDBCConnectionException', 'org.springframework.dao.DataAccessResourceFailureException', 'org.springframework.dao.QueryTimeoutException',
                          'org.springframework.dao.TransientDataAccessResourceException', 'org.springframework.http.HttpStatus', 'org.springframework.stereotype.Component',
                          'org.springframework.transaction.CannotCreateTransactionException'})
            + f'/** Classifies data-access failures (cause chains included) into HTTP statuses: timeout, unique violation, unavailability, otherwise internal error. */\n@Component\npublic class {class_of(path)} {{\n'
            f'    private static final int ORACLE_UNIQUE_VIOLATION = 1;\n\n    public {exc} translate(RuntimeException failure) {{\n        boolean unique = false;\n        boolean unavailable = false;\n        boolean timeout = false;\n'
            '        Set<Throwable> seen = Collections.newSetFromMap(new IdentityHashMap<>());\n        ArrayDeque<Throwable> queue = new ArrayDeque<>();\n        queue.add(failure);\n        while (!queue.isEmpty()) {\n'
            '            Throwable cause = queue.removeFirst();\n            if (!seen.add(cause)) {\n                continue;\n            }\n'
            '            timeout |= cause instanceof SQLTimeoutException\n                    || cause instanceof QueryTimeoutException\n                    || cause instanceof jakarta.persistence.QueryTimeoutException;\n'
            '            unavailable |= cause instanceof DataAccessResourceFailureException\n                    || cause instanceof TransientDataAccessResourceException\n                    || cause instanceof CannotCreateTransactionException\n'
            '                    || cause instanceof JDBCConnectionException\n                    || cause instanceof SQLNonTransientConnectionException\n                    || cause instanceof SQLTransientConnectionException\n                    || cause instanceof SQLRecoverableException;\n'
            '            if (cause instanceof SQLException sql) {\n                unique |= sql.getErrorCode() == ORACLE_UNIQUE_VIOLATION;\n                if (sql.getNextException() != null) {\n                    queue.add(sql.getNextException());\n                }\n            }\n'
            '            if (cause.getCause() != null) {\n                queue.add(cause.getCause());\n            }\n        }\n'
            '        HttpStatus status = timeout ? HttpStatus.GATEWAY_TIMEOUT\n                : unique ? HttpStatus.CONFLICT\n                : unavailable ? HttpStatus.SERVICE_UNAVAILABLE : HttpStatus.INTERNAL_SERVER_ERROR;\n'
            f'        return new {exc}(status, "Persistence operation failed.", failure);\n    }}\n}}\n')


def prune_imports(text: str) -> str:
    """Drop imports whose simple name is not used in the code (UnusedImports); deterministic."""
    lines = text.split('\n')
    body = '\n'.join(l for l in lines if not l.startswith('import '))
    own = re.match(r'package ([\w.]+);', text)
    own = own.group(1) if own else None

    def redundant(line):
        # an import of a top-level class of the file's own package (RedundantImport); static and nested imports are not affected
        m = re.fullmatch(r'import ([\w.]+)\.([A-Z]\w*);', line)
        return bool(m) and m.group(1) == own
    kept = [l for l in lines if not l.startswith('import ') or (not redundant(l) and re.search(r'\b' + re.escape(l.rstrip(';').rsplit('.', 1)[-1]) + r'\b', body))]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(kept))
