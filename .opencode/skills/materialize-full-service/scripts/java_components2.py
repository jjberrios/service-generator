"""Java renderers, part 2: validator, mapper, service contract/implementation and exception advice (materializer v2)."""
import re
from renderers import Unsupported, class_of, package_of, java_string
from service_model import cap, snake, STATUS_ENUM
from java_components import header, fqn, dto_fqn, check_lines, string_expr, chunks

CONVERTERS = {'Long': 'toLong', 'Integer': 'toInteger'}


def getter(f):
    return 'get' + cap(f)


# ---------------------------------------------------------------------------------------------------------------------------------- validator
def validator(M, path):
    name = class_of(path)
    exc = class_of(M['paths']['internal-typed-exception'])
    imports = {f'{package_of(M["paths"]["internal-typed-exception"])}.{exc}', 'java.math.BigDecimal', 'java.util.Set', 'java.util.function.Supplier', 'java.util.Arrays', 'java.util.Objects',
               'org.springframework.stereotype.Component'}
    constants, commands, methods = [], [], []
    for op in M['ops']:
        if op['kind'] == 'select':
            crit = class_of(M['paths']['internal-query-model'])
            imports.add(f'{package_of(M["paths"]["internal-query-model"])}.{crit}')
            params = [p for p in op['params']['query']]
            filter_params = [f['param'] for f in op['filters']]
            constants.append(f'    private static final int {snake(op["id"])}_MINIMUM_FILTERS = {op["policy"]["min"]};')
            args = []
            for f in op['filters']:
                p = next(q for q in params if q['java'] == f['param'])
                args.append(conversion(f['type'], p['java'], p['name'], f.get('sql'), None, f['prop'], op, constants))
            if op['page']:
                args += op['page']
            decl = ', '.join(f'{p["type"]} {p["java"]}' for p in params)
            body = [f'        if (supplied({", ".join(filter_params)}) < {snake(op["id"])}_MINIMUM_FILTERS) {{\n            throw {exc}.badRequest("not enough search filters were supplied");\n        }}']
            for rule in op['rules']:
                if rule['kind'] == 'pagination-pairing':
                    lim, off = op['page']
                    body.append(f'        if (({lim} == null) != ({off} == null)) {{\n            throw {exc}.badRequest("pagination parameters must be supplied together");\n        }}')
            body.append(f'        return new {crit}(\n                ' + ',\n                '.join(args) + ');')
            methods.append(f'    public {crit} {op["id"]}({decl}) {{\n' + '\n'.join(body) + '\n    }')
        else:
            req = M['models'][op['requestModel']]
            imports.add(dto_fqn(M, op['requestModel']))
            cmd = op['commandName']
            comps = []
            if op['kind'] == 'update':
                comps.append('Long id')
            for f in op['fields']:
                comps.append((f'Field<{f["type"]}> ' if op['kind'] == 'update' else f'{f["type"]} ') + f['prop'])
            commands.append(f'    public record {cmd}(\n            ' + ',\n            '.join(comps) + ') {\n    }')
            body, args = [], []
            if op['kind'] == 'update':
                at_least = any(r['kind'] == 'at-least-one-of' for r in op['rules'])
                body.append('        Set<String> supplied = request.getSuppliedFields();')
                if at_least:
                    body.append(f'        if (supplied.isEmpty()) {{\n            throw {exc}.badRequest("at least one updatable field is required");\n        }}')
                args.append(conversion('Long', op['pathId'], op['params']['path'][0]['name'], None, None, 'id', op, constants))
            for r in op['rules']:
                if r['kind'] == 'conditional-required':
                    m = re.fullmatch(r'(\w+) is supplied', r['when'].strip())
                    if not m or m.group(1) not in {f['name'] for f in req['fields']} or not all(x in {f['name'] for f in req['fields']} for x in r['requires']):
                        raise Unsupported(f'{op["id"]}: conditional rule {r["when"]!r} cannot be mapped to request fields')
                    checks = ' || '.join(f'request.{getter(x)}() == null' for x in r['requires'])
                    body.append(f'        if (request.{getter(m.group(1))}() != null && ({checks})) {{\n            throw {exc}.badRequest("a conditionally required field is missing");\n        }}')
            for f in op['fields']:
                source = f'request.{getter(f["input"])}()'
                expr = conversion(f['type'], source, f['input'], None, f, f['prop'], op, constants, direct=True)
                if op['kind'] == 'update':
                    args.append(f'field(supplied, {java_string(f["input"])}, () -> {expr})')
                else:
                    args.append(expr)
            body.append(f'        return new {cmd}(\n                ' + ',\n                '.join(args) + ');')
            sig = (f'String {op["pathId"]}, ' if op['kind'] == 'update' else '') + f'{op["requestModel"]} request'
            methods.append(f'    public {cmd} {op["id"]}({sig}) {{\n' + '\n'.join(body) + '\n    }')
    helper_blocks = {
        'supplied': f'''    private static int supplied(Object... values) {{
        return (int) Arrays.stream(values).filter(Objects::nonNull).count();
    }}''',
        'field': f'''    private static <T> Field<T> field(Set<String> supplied, String name, Supplier<T> conversion) {{
        return supplied.contains(name) ? new Field<>(true, conversion.get()) : new Field<>(false, null);
    }}''',
        'toLong': f'''    private static Long toLong(String value, String field) {{
        if (value == null) {{
            return null;
        }}
        try {{
            return new BigDecimal(value).longValueExact();
        }} catch (NumberFormatException | ArithmeticException ex) {{
            throw {exc}.badRequest(field + " has an invalid value");
        }}
    }}''',
        'toInteger': f'''    private static Integer toInteger(String value, String field) {{
        if (value == null) {{
            return null;
        }}
        try {{
            return Integer.valueOf(value);
        }} catch (NumberFormatException ex) {{
            throw {exc}.badRequest(field + " has an invalid value");
        }}
    }}''',
        'toDecimal': f'''    private static BigDecimal toDecimal(String value, String field) {{
        if (value == null) {{
            return null;
        }}
        try {{
            return new BigDecimal(value);
        }} catch (NumberFormatException ex) {{
            throw {exc}.badRequest(field + " has an invalid value");
        }}
    }}''',
        'toBoundedDecimal': f'''    private static BigDecimal toBoundedDecimal(String value, String field, int integerDigits, int scale) {{
        BigDecimal parsed = toDecimal(value, field);
        if (parsed != null) {{
            BigDecimal normalized = parsed.stripTrailingZeros();
            if (normalized.scale() > scale || (long) normalized.precision() - normalized.scale() > integerDigits) {{
                throw {exc}.badRequest(field + " exceeds the column precision");
            }}
        }}
        return parsed;
    }}''',
        'oneOf': f'''    private static String oneOf(String value, Set<String> allowed, String field) {{
        if (value != null && !allowed.contains(value)) {{
            throw {exc}.badRequest(field + " is not an allowed value");
        }}
        return value;
    }}'''
    }
    scanned = '\n'.join(constants + commands + methods)
    needed = {n for n in helper_blocks if re.search(r'\b' + n + r'\(', scanned)}
    if 'toBoundedDecimal' in needed:
        needed.add('toDecimal')                      # toBoundedDecimal delegates to toDecimal
    helpers = '\n\n'.join(helper_blocks[n] for n in helper_blocks if n in needed)
    uses_field = 'field' in needed or any(op['kind'] == 'update' for op in M['ops'])
    field_record = '    public record Field<T>(boolean supplied, T value) {\n    }' if uses_field else ''
    text = (header(path, imports) + f'/** Cross-field rules and lossless conversions from contract values to typed commands; Bean Validation owns the declared contract annotations. */\n@Component\npublic class {name} {{\n'
            + '\n'.join(dict.fromkeys(constants)) + ('\n\n' if constants else '') + (field_record + '\n\n' if field_record else '') + ('\n\n'.join(commands) + '\n\n' if commands else '') + '\n\n'.join(methods) + ('\n\n' + helpers if helpers else '') + '\n}\n')
    return check_lines(text, name)


def conversion(entity_type, source, field_name, sql, field, prop, op, constants, direct=False):
    """Expression that converts a contract String value to the entity type, with enum/precision checks taken from the plan."""
    label = java_string(field_name)
    if entity_type == 'String':
        expr = source
    elif entity_type == 'BigDecimal':
        numeric = (field or {}).get('numeric') if field else None
        if not numeric and sql:
            from service_model import parse_numeric
            numeric = parse_numeric(sql)
        if numeric:
            base = snake(prop)
            constants.append(f'    private static final int {base}_INTEGER_DIGITS = {numeric["integerDigits"]};')
            constants.append(f'    private static final int {base}_SCALE = {numeric["scale"]};')
            expr = f'toBoundedDecimal({source}, {label}, {base}_INTEGER_DIGITS, {base}_SCALE)'
        else:
            expr = f'toDecimal({source}, {label})'
    elif entity_type in CONVERTERS:
        expr = f'{CONVERTERS[entity_type]}({source}, {label})'
    else:
        raise Unsupported(f'conversion to {entity_type} is not supported')
    enum = (field or {}).get('enum') if field else None
    if enum:
        const = f'ALLOWED_{snake(prop)}'
        constants.append(f'    private static final Set<String> {const} = Set.of(' + ', '.join(java_string(str(v)) for v in enum) + ');')
        expr = expr.replace(source, f'oneOf({source}, {const}, {label})', 1)
    return expr


# ------------------------------------------------------------------------------------------------------------------------------------ mapper
def mapper(M, path):
    name = class_of(path)
    entity = M['entity']['class']
    exc = class_of(M['paths']['internal-typed-exception'])
    val = class_of(M['paths']['business-validator'])
    imports = {M['entity']['fqn'], f'{package_of(M["paths"]["internal-typed-exception"])}.{exc}', f'{package_of(M["paths"]["business-validator"])}.{val}', 'java.math.BigDecimal',
               'java.util.List', 'java.util.Set', 'org.springframework.http.HttpStatus', 'org.springframework.stereotype.Component'}
    constants = []
    methods = []
    for op in M['ops']:
        cmd = f'{val}.{op["commandName"]}' if op['kind'] != 'select' else None
        if op['kind'] == 'select':
            for t in (op['successModel'], op['dataModel'], op['itemModel']):
                imports.add(dto_fqn(M, t))
            constants.append(f'    private static final String {snake(op["id"])}_SUCCESS_MESSAGE = {java_string(op["successMessage"])};')
            sets = []
            for c in op['columns']:
                getter_expr = f'row.get{cap(c["prop"])}()'
                if c['entityType'] == c['itemType']:
                    value = getter_expr
                else:
                    value = f'text({getter_expr})'
                if c['enum']:
                    const = f'{snake(op["id"])}_ALLOWED_{snake(c["field"])}'
                    constants.append(f'    private static final Set<String> {const} = Set.of(' + ', '.join(java_string(str(v)) for v in c['enum']) + ');')
                    value = f'checked({value}, {const})'
                sets.append(f'        result.set{cap(c["field"])}({value});')
            methods.append(f'    public {op["successModel"]} {op["id"]}Response(List<{entity}> rows) {{\n        {op["dataModel"]} data = new {op["dataModel"]}();\n'
                           f'        data.set{cap(op["listProp"])}(rows.stream().map(this::{op["id"]}Item).toList());\n        {op["successModel"]} response = new {op["successModel"]}();\n'
                           f'        response.setCode(HttpStatus.OK.value());\n        response.setMessage({snake(op["id"])}_SUCCESS_MESSAGE);\n        response.setData(data);\n        return response;\n    }}')
            methods.append(f'    private {op["itemModel"]} {op["id"]}Item({entity} row) {{\n        {op["itemModel"]} result = new {op["itemModel"]}();\n' + '\n'.join(sets) + '\n        return result;\n    }')
        elif op['kind'] == 'insert':
            sets = [f'        entity.set{cap(f["prop"])}(command.{f["prop"]}());' for f in op['fields']]
            audit = f'        entity.set{cap(op["auditUser"])}(auditUser);\n' if op['auditUser'] else ''
            methods.append(f'    public {entity} {op["id"]}Entity({cmd} command, String auditUser) {{\n        {entity} entity = new {entity}();\n' + '\n'.join(sets) + f'\n{audit}        return entity;\n    }}')
        else:
            ifs = [f'        if (command.{f["prop"]}().supplied()) {{\n            entity.set{cap(f["prop"])}(command.{f["prop"]}().value());\n        }}' for f in op['fields']]
            audit = f'        entity.set{cap(op["auditUser"])}(auditUser);\n' if op['auditUser'] else ''
            methods.append(f'    public void {op["id"]}Patch({entity} entity, {cmd} command, String auditUser) {{\n' + '\n'.join(ifs) + f'\n{audit}    }}')
    helpers = (f'    private static String text(Object value) {{\n        return value == null ? null : value.toString();\n    }}\n\n'
               f'    private static String text(BigDecimal value) {{\n        return value == null ? null : value.toPlainString();\n    }}\n\n'
               f'    private static String checked(String value, Set<String> allowed) {{\n        if (value != null && !allowed.contains(value)) {{\n'
               f'            throw new {exc}(HttpStatus.INTERNAL_SERVER_ERROR, "A stored value cannot satisfy the response contract.");\n        }}\n        return value;\n    }}')
    text = (header(path, imports) + f'/** Explicit mappings between the API contract, typed commands and the JPA entity; nothing relies on name coincidence. */\n@Component\npublic class {name} {{\n'
            + '\n'.join(constants) + ('\n\n' if constants else '') + '\n\n'.join(methods) + '\n\n' + helpers + '\n}\n')
    return check_lines(text, name)


# ------------------------------------------------------------------------------------------------------------------------------ service
def service_params(op):
    out = []
    if op['kind'] == 'select':
        out = [f'{p["type"]} {p["java"]}' for p in op['params']['query']]
    elif op['kind'] == 'update':
        out = [f'{op["params"]["path"][0]["type"]} {op["pathId"]}', f'{op["requestModel"]} request']
    else:
        out = [f'{op["requestModel"]} request']
    return ', '.join(['RequestHeaders headers'] + out)


def service_interface(M, path):
    imports = {fqn(M, 'request-headers-model')}
    lines = []
    for op in M['ops']:
        imports.add(dto_fqn(M, op['successModel']))
        if op['requestModel']:
            imports.add(dto_fqn(M, op['requestModel']))
        lines.append(f'    {op["successModel"]} {op["id"]}({service_params(op)});')
    return check_lines(header(path, imports) + f'public interface {class_of(path)} {{\n' + '\n\n'.join(lines) + '\n}\n', class_of(path))


def service_impl(M, path):
    name = class_of(path)
    ent, entity = M['entity']['fqn'], M['entity']['class']
    exc = class_of(M['paths']['internal-typed-exception'])
    val, mp, repo, trans = (class_of(M['paths'][k]) for k in ('business-validator', 'explicit-contract-data-mapper', 'spring-data-jpa-repository', 'data-access-error-translator'))
    imports = {ent, fqn(M, 'request-headers-model'), fqn(M, 'internal-typed-exception'), fqn(M, 'business-validator'), fqn(M, 'explicit-contract-data-mapper'), fqn(M, 'spring-data-jpa-repository'),
               fqn(M, 'data-access-error-translator'), fqn(M, 'application-service-contract'),
               'java.util.function.Supplier', 'lombok.RequiredArgsConstructor', 'lombok.extern.slf4j.Slf4j', 'org.springframework.dao.DataAccessException', 'org.springframework.dao.QueryTimeoutException',
               'org.springframework.http.HttpStatus', 'org.springframework.stereotype.Service'}
    imports |= {fqn(M, 'archetype-activity-logger'), fqn(M, 'activity-constants')}
    constants = ['    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";', '    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";',
                 '    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";', '    private static final String NOT_FOUND_DETAIL = "No matching record.";']
    uses_dates = any(o['dateProp'] for o in M['ops'] if o['kind'] != 'select')
    methods, helpers = [], []
    select = next((o for o in M['ops'] if o['kind'] == 'select'), None)
    if uses_dates:
        imports |= {'java.time.Clock', 'java.time.LocalDateTime', 'org.springframework.beans.factory.annotation.Autowired'}
    if select:
        crit = class_of(M['paths']['internal-query-model'])
        spec = class_of(M['paths']['jpa-specification'])
        imports |= {fqn(M, 'internal-query-model'), fqn(M, 'jpa-specification'), 'java.util.List', 'org.springframework.data.domain.Sort', 'org.springframework.data.jpa.domain.Specification'}
        constants.append(f'    private static final Sort ORDER = Sort.by(Sort.Direction.ASC, {java_string(select["orderProp"])});')
        if select['page']:
            imports.add(fqn(M, 'offset-based-pageable'))
    if any(o['kind'] == 'update' for o in M['ops']):
        imports.add('java.util.Optional')
    for op in M['ops']:
        imports.add(dto_fqn(M, op['successModel']))
        if op['requestModel']:
            imports.add(dto_fqn(M, op['requestModel']))
        val_c, beh_c = f'ConstanApi.{op["validationConstant"]}', f'ConstanApi.{op["behaviorConstant"]}'
        timeout, errdata = f'ConstanApi.LOG_TIMEOUT_{op["behaviorConstant"]}', f'ConstanApi.LOG_ERROR_DATOS_{op["behaviorConstant"]}'
        prelude = ('        String tx = headers != null ? headers.transactionId() : null;\n        String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;\n\n')
        log = op['logging']
        call_args = ['headers'] + ([op['pathId']] if op['kind'] == 'update' else []) + ([p['java'] for p in op['params']['query']] if op['kind'] == 'select' else [])
        call_args += ['request'] if op['requestModel'] else []
        log_decl = ['RequestHeaders h'] + [next(f'{p["type"]} {p["java"]}' for p in op['params']['path'] + op['params']['query'] if p['java'] == v or p['name'] == v) for v in log['values']] + ([f'{op["requestModel"]} body'] if log['body'] else [])
        value_names = [next(p['java'] for p in op['params']['path'] + op['params']['query'] if p['java'] == v or p['name'] == v) for v in log['values']]
        log_args = ['headers'] + value_names + (['request'] if log['body'] else [])
        meta = {'applicationName': 'h != null ? h.applicationName() : null', 'transactionId': 'h != null ? h.transactionId() : null', 'userId': 'h != null ? h.userId() : null'}
        for m_ in log['metadata']:
            if m_ not in meta:
                raise Unsupported(f'{op["id"]}: logging metadata {m_} is not a RequestHeaders accessor known to the renderer')
        fields = [f'{m_}={{}}' for m_ in log['metadata']] + [f'{v}={{}}' for v in value_names]
        fmt = log['label'] + ' ' + ', '.join(fields)
        arg_lines = ',\n                '.join([meta[m_] for m_ in log['metadata']] + value_names)
        body_log = ''
        if log['body']:
            body_log = (f'\n\n        ActivityLogger.logContenido(\n                log,\n                {java_string(log["body"]["message"])},\n                body,\n                {log["body"]["type"]}.class\n        );')
        helpers.append(f'    private void {log["helper"]}({", ".join(log_decl)}) {{\n        log.info(\n                {string_expr(fmt, 16, 24)},\n                {arg_lines}\n        );{body_log}\n    }}')
        val_call = {'select': f'validator.{op["id"]}({", ".join(p["java"] for p in op["params"]["query"])})', 'insert': f'validator.{op["id"]}(request)',
                    'update': f'validator.{op["id"]}({op["pathId"] if op["kind"] == "update" else ""}, request)'}[op['kind']]
        log_call = f'{log["helper"]}({", ".join(log_args)});'
        if op['kind'] == 'select':
            result_type = f'{crit}'
            second = (f'        List<{entity}> rows = ejecutarActividad(\n                menTran,\n                {beh_c},\n                () -> {{\n                    List<{entity}> found = accederDatos(\n                            menTran,\n'
                      f'                            {timeout},\n                            {errdata},\n                            () -> search(criteria));\n                    if (found.isEmpty()) {{\n'
                      f'                        log.error(ERROR_BUSINESS_PATTERN, menTran, {beh_c}, HttpStatus.NOT_FOUND.value(), NOT_FOUND_DETAIL);\n                        throw new {exc}(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);\n'
                      f'                    }}\n                    return found;\n                }}\n        );\n        return mapper.{op["id"]}Response(rows);')
            var = 'criteria'
        else:
            result_type = f'{val}.{op["commandName"]}'
            user = 'headers != null ? headers.userId() : null'
            date_line = lambda prop: f'                    entity.set{cap(prop)}(LocalDateTime.now(clock));\n' if prop else ''
            if op['kind'] == 'insert':
                second = (f'        ejecutarActividad(\n                menTran,\n                {beh_c},\n                () -> {{\n                    {entity} entity = mapper.{op["id"]}Entity(command, {user});\n{date_line(op["dateProp"])}'
                          f'                    return accederDatos(\n                            menTran,\n                            {timeout},\n                            {errdata},\n                            () -> repository.save(entity));\n                }}\n        );\n')
            else:
                second = (f'        ejecutarActividad(\n                menTran,\n                {beh_c},\n                () -> {{\n                    Optional<{entity}> found = accederDatos(\n                            menTran,\n                            {timeout},\n'
                          f'                            {errdata},\n                            () -> repository.findById(command.id()));\n                    if (found.isEmpty()) {{\n'
                          f'                        log.error(ERROR_BUSINESS_PATTERN, menTran, {beh_c}, HttpStatus.NOT_FOUND.value(), NOT_FOUND_DETAIL);\n                        throw new {exc}(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);\n                    }}\n'
                          f'                    {entity} entity = found.get();\n                    mapper.{op["id"]}Patch(entity, command, {user});\n{date_line(op["dateProp"])}'
                          f'                    return accederDatos(\n                            menTran,\n                            {timeout},\n                            {errdata},\n                            () -> repository.save(entity));\n                }}\n        );\n')
            constants.append(f'    private static final String {snake(op["id"])}_SUCCESS_MESSAGE = {java_string(op["successMessage"])};')
            second += (f'\n        {op["successModel"]} response = new {op["successModel"]}();\n        response.setCode(HttpStatus.OK.value());\n        response.setMessage({snake(op["id"])}_SUCCESS_MESSAGE);\n        return response;')
            var = 'command'
        methods.append(f'    @Override\n    public {op["successModel"]} {op["id"]}({service_params(op)}) {{\n{prelude}        // ACTIVIDAD 1: VALIDAR PARAMETROS / LOG DE ENTRADA\n'
                       f'        {result_type} {var} = ejecutarActividad(\n                menTran,\n                {val_c},\n                () -> {{\n                    {log_call}\n                    return {val_call};\n                }}\n        );\n\n'
                       f'        // ACTIVIDAD 2: {op["behaviorConstant"]}\n{second}\n    }}')
    if select:
        page = (f'        if (criteria.limit() == null) {{\n            return repository.findAll(specification, ORDER);\n        }}\n        return repository.findAll(specification, new {class_of(M["paths"]["offset-based-pageable"])}(criteria.offset(), criteria.limit(), ORDER)).getContent();'
                if select['page'] else '        return repository.findAll(specification, ORDER);')
        helpers.insert(0, f'    private List<{entity}> search({class_of(M["paths"]["internal-query-model"])} criteria) {{\n        Specification<{entity}> specification = {class_of(M["paths"]["jpa-specification"])}.matching(criteria);\n{page}\n    }}')
    tail = f'''    private <T> T accederDatos(String menTran, String logTimeout, String logErrorDatos, Supplier<T> acceso) {{
        try {{
            return acceso.get();

        }} catch (QueryTimeoutException e) {{
            log.error(ERROR_TECHNICAL_PATTERN, menTran, logTimeout, e.getMessage());
            throw translator.translate(e);

        }} catch (DataAccessException e) {{
            log.error(ERROR_TECHNICAL_PATTERN, menTran, logErrorDatos, e.getMessage());
            throw translator.translate(e);
        }}
    }}

    private <T> T ejecutarActividad(String menTran, String actividad, Supplier<T> accion) {{
        try {{
            ActivityLogger.inicioActividad(log, menTran, actividad);
            T result = accion.get();
            ActivityLogger.finActividad(log, menTran, actividad);
            return result;

        }} catch ({exc} ex) {{
            log.error("{{}} ERROR [{{}}] message={{}}", menTran, actividad, ex.getMessage());
            throw ex;

        }} catch (Exception ex) {{
            log.error("{{}} ERROR [{{}}] unexpected exception={{}}", menTran, actividad, ex.getMessage());
            throw ex;
        }}
    }}'''
    clock_member = ('    private Clock clock = Clock.systemDefaultZone();\n\n    /** Audit timestamps use the system default zone unless the application defines a Clock bean; tests install a fixed Clock. */\n'
                    '    @Autowired(required = false)\n    void setClock(Clock clock) {\n        this.clock = clock;\n    }\n\n') if uses_dates else ''
    text = (header(path, imports) + f'/** Activity-logged service implementation; logging is instrumentation only and never changes statuses or return values. */\n@Service\n@RequiredArgsConstructor\n@Slf4j\n'
            f'public class {name} implements {class_of(M["paths"]["application-service-contract"])} {{\n' + '\n'.join(constants) + f'\n\n    private final {repo} repository;\n    private final {val} validator;\n'
            f'    private final {mp} mapper;\n    private final {trans} translator;\n\n' + clock_member + '\n\n'.join(methods) + '\n\n' + '\n\n'.join(helpers) + '\n\n' + tail + '\n}\n')
    return check_lines(text, name)


# ------------------------------------------------------------------------------------------------------------------------------ advice
def handler(M, path):
    name = class_of(path)
    exc = class_of(M['paths']['internal-typed-exception'])
    trans = class_of(M['paths']['data-access-error-translator'])
    err = M['errors']['model']
    imports = {fqn(M, 'internal-typed-exception'), fqn(M, 'data-access-error-translator'), dto_fqn(M, err), fqn(M, 'archetype-activity-logger'), fqn(M, 'activity-constants'), 'jakarta.validation.ConstraintViolationException',
               'lombok.extern.slf4j.Slf4j', 'org.springframework.http.HttpHeaders', 'org.springframework.http.HttpStatus', 'org.springframework.http.HttpStatusCode', 'org.springframework.http.ResponseEntity',
               'org.springframework.lang.Nullable', 'org.springframework.web.bind.annotation.ExceptionHandler', 'org.springframework.web.bind.annotation.RestControllerAdvice',
               'org.springframework.web.context.request.ServletWebRequest', 'org.springframework.web.context.request.WebRequest', 'org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler'}
    errors = M['errors']
    messages = errors['messageByMethod']
    msg_cases = ''.join(f'            case {java_string(m)} -> {java_string(t)};\n' for m, t in sorted(messages.items()))
    allowed = []
    for method, statuses in sorted(errors['allowedByMethod'].items()):
        cond = '\n                    || '.join(f'status == HttpStatus.{STATUS_ENUM[s]}' for s in statuses) or 'false'
        allowed.append(f'            case {java_string(method)} -> {cond};')
    blocks = []
    for status in sorted(s for s in {c for o in M['ops'] for c in o['statuses']} if s != 200):
        examples = errors['byStatus'].get(status, {})
        first = next(iter(examples.values()), None) or {}
        sets = []
        for key, setter in (('type', 'setType'), ('subType', 'setSubType')):
            if first.get(key):
                sets.append(f'                error.{setter}({java_string(first[key])});')
        details = {m: e.get('detail') for m, e in examples.items() if e.get('detail')}
        if details:
            fallback = first.get('detail')
            cases = ''.join(f'                    case {java_string(m)} -> {java_string(d)};\n' for m, d in sorted(details.items()))
            sets.append(f'                String detail = switch (method) {{\n{cases}                    default -> {java_string(fallback)};\n                }};\n                error.setDetail(detail);')
        if not sets:
            sets.append('                error.setDetail(status.getReasonPhrase());')
        blocks.append(f'            case {STATUS_ENUM[status]} -> {{\n' + '\n'.join(sets) + '\n            }')
    text = (header(path, imports) + f'''@RestControllerAdvice
@Slf4j
public class {name} extends ResponseEntityExceptionHandler {{
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String TRANSACTION_HEADER = {java_string(M['activity']['transactionHeader'])};

    private final {trans} translator;

    public {name}({trans} translator) {{
        this.translator = translator;
    }}

    @ExceptionHandler({exc}.class)
    public ResponseEntity<{err}> operationFailure({exc} failure, WebRequest request) {{
        HttpStatus status = declared(failure.getStatus(), method(request));
        logValidationFailure(request, status, failure.getMessage());
        return ResponseEntity.status(status).body(error(status, request));
    }}

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<{err}> constraintFailure(ConstraintViolationException failure, WebRequest request) {{
        logValidationFailure(request, HttpStatus.BAD_REQUEST, failure.getMessage());
        return ResponseEntity.badRequest().body(error(HttpStatus.BAD_REQUEST, request));
    }}

    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<{err}> unexpectedFailure(RuntimeException failure, WebRequest request) {{
        return operationFailure(translator.translate(failure), request);
    }}

    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception ex, @Nullable Object body,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {{
        HttpStatus resolved = declared(HttpStatus.valueOf(status.value()), method(request));
        logValidationFailure(request, resolved, ex.getClass().getSimpleName());
        return new ResponseEntity<>(error(resolved, request), headers, status);
    }}

    /** A status that the operation does not declare is never emitted: it becomes an internal error. */
    private HttpStatus declared(HttpStatus status, String method) {{
        boolean allowed = switch (method) {{
{chr(10).join(allowed)}
            default -> true;
        }};
        return allowed ? status : HttpStatus.INTERNAL_SERVER_ERROR;
    }}

    private void logValidationFailure(WebRequest request, HttpStatus status, String reason) {{
        if (status != HttpStatus.BAD_REQUEST) {{
            return;
        }}
        String tx = request.getHeader(TRANSACTION_HEADER);
        String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
        ActivityLogger.inicioActividad(log, menTran, ConstanApi.{M['activity']['handlerValidation']});
        log.error("{{}} ERROR [{{}}] code={{}} detail={{}}", menTran, ConstanApi.{M['activity']['handlerValidation']}, status.value(), reason);
        ActivityLogger.finActividad(log, menTran, ConstanApi.{M['activity']['handlerValidation']});
    }}

    private {err} error(HttpStatus status, WebRequest request) {{
        {err} error = new {err}();
        error.setCode(status.value());
        error.setStatus(status.name());
        String method = method(request);
        String message = switch (method) {{
{msg_cases}            default -> status.getReasonPhrase();
        }};
        error.setMessage(message);
        switch (status) {{
''' + '\n'.join(blocks) + '''
            default -> error.setDetail(status.getReasonPhrase());
        }
        return error;
    }

    private String method(WebRequest request) {
        return request instanceof ServletWebRequest servlet ? servlet.getRequest().getMethod() : "";
    }
}
''')
    return check_lines(text, name)
