"""Deterministic Java renderers for the FULL materializer (first version).

Every renderer is a pure function of the structured plan data and (for archetype files) the archetype template text. No domain names,
endpoints or business rules live here. Output is UTF-8 with LF line endings and no timestamps so identical inputs give identical bytes.
Anything outside the supported set raises Unsupported, which makes the materializer stop instead of writing incomplete code.
"""
import re


class Unsupported(Exception):
    """A planned component or attribute that this materializer version cannot generate faithfully."""


JAVA_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
ENTITY_TYPES = {'String': None, 'Long': None, 'Integer': None, 'BigDecimal': 'java.math.BigDecimal', 'LocalDateTime': 'java.time.LocalDateTime'}
CONTENT_TOKENS = ('__BASE_PACKAGE__', '__BASE_PACKAGE_PATH__')


def lf(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n')


def ident(value, what):
    if not isinstance(value, str) or not JAVA_IDENT.match(value):
        raise Unsupported(f'{what} {value!r} is not a safe Java identifier')
    return value


def java_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def package_of(path: str) -> str:
    for root in ('src/main/java/', 'src/test/java/'):
        if path.startswith(root):
            return path[len(root):].rsplit('/', 1)[0].replace('/', '.')
    raise Unsupported(f'{path} is not under src/main/java or src/test/java')


def class_of(path: str) -> str:
    return ident(path.rsplit('/', 1)[-1].removesuffix('.java'), 'class name')


# ------------------------------------------------------------------------------------------------------------ archetype templates
def from_template(template_text: str, base_package: str, base_package_path: str) -> str:
    text = lf(template_text).replace('__BASE_PACKAGE_PATH__', base_package_path).replace('__BASE_PACKAGE__', base_package)
    left = [t for t in CONTENT_TOKENS if t in text]
    if left or re.search(r'__[A-Z][A-Z_]+__', text):
        raise Unsupported('archetype template still contains unresolved tokens')
    return text


def constants_file(template_text: str, base_package: str, base_package_path: str, constants: list, marker: str) -> str:
    """ConstanApi: template plus the activity constants and log messages derived from the plan (inserted after the template marker)."""
    text = from_template(template_text, base_package, base_package_path)
    if text.count(marker) != 1:
        raise Unsupported('the constants template does not contain the expected insertion marker exactly once')
    lines = []
    for item in constants:
        lines.append(f'    public static final String {ident(item["constant"], "constant")} = {java_string(item["value"])};')
    messages = [(k, v) for item in constants for k, v in (item.get('logMessages') or {}).items()]
    if messages:
        lines += ['', '    // Mensajes log (actividades con acceso a datos)']
        for name, value in messages:
            lines += [f'    public static final String {ident(name, "message constant")} =', f'            {java_string(value)};', '']
        lines.pop()
    return text.replace(marker, marker + '\n' + '\n'.join(lines))


# ------------------------------------------------------------------------------------------------------------------ generated types
def request_headers(path: str, components: list) -> str:
    if not components:
        raise Unsupported('request headers record without components')
    body = ',\n'.join(f'        String {ident(c, "header component")}' for c in components)
    return (f'package {package_of(path)};\n\n/**\n * Technical request headers carried to the service layer. Components are the roles that have a declared target header; '
            f'they are technical identifiers, never business fields.\n */\npublic record {class_of(path)}(\n{body}\n) {{\n\n}}\n')


def typed_exception(path: str) -> str:
    name = class_of(path)
    return (f'package {package_of(path)};\n\nimport org.springframework.http.HttpStatus;\n\n'
            f'/** Application failure that carries the HTTP status decided by the approved behavior. */\n'
            f'public class {name} extends RuntimeException {{\n    private final HttpStatus status;\n\n'
            f'    public {name}(HttpStatus status, String message) {{\n        super(message);\n        this.status = status;\n    }}\n\n'
            f'    public {name}(HttpStatus status, String message, Throwable cause) {{\n        super(message, cause);\n        this.status = status;\n    }}\n\n'
            f'    public static {name} badRequest(String message) {{\n        return new {name}(HttpStatus.BAD_REQUEST, message);\n    }}\n\n'
            f'    public HttpStatus getStatus() {{\n        return status;\n    }}\n}}\n')


def jpa_entity(path: str, model: dict, identity: bool, dynamic_dml: bool) -> str:
    name, table = class_of(path), model.get('table')
    if class_of(path) != model.get('entityClass'):
        raise Unsupported(f'entity file {name} differs from the planned entity class {model.get("entityClass")}')
    ident(table, 'table name')
    fields = model.get('fields') or []
    keys = [f for f in fields if f.get('primaryKey')]
    if len(keys) != 1 or keys[0].get('javaType') != 'Long':
        raise Unsupported('this version supports exactly one Long primary key')
    if not identity:
        raise Unsupported('the plan does not select the IDENTITY key generation this version implements')
    imports = {'jakarta.persistence.Column', 'jakarta.persistence.Entity', 'jakarta.persistence.Id', 'jakarta.persistence.Table', 'jakarta.persistence.GeneratedValue',
               'jakarta.persistence.GenerationType', 'lombok.AllArgsConstructor', 'lombok.Data', 'lombok.NoArgsConstructor'}
    if dynamic_dml:
        imports |= {'org.hibernate.annotations.DynamicInsert', 'org.hibernate.annotations.DynamicUpdate'}
    members = []
    for field in fields:
        java_type = field.get('javaType')
        if java_type not in ENTITY_TYPES:
            raise Unsupported(f'column {field.get("physicalColumn")} has the unsupported Java type {java_type!r}')
        if ENTITY_TYPES[java_type]:
            imports.add(ENTITY_TYPES[java_type])
        lines = []
        if field.get('primaryKey'):
            lines += ['    @Id', '    @GeneratedValue(strategy = GenerationType.IDENTITY)']
        if field.get('lob'):
            if java_type != 'String':
                raise Unsupported('@Lob is supported only on String columns')
            imports.add('jakarta.persistence.Lob')
            lines.append('    @Lob')
        lines += [f'    @Column(name = {java_string(ident(field["physicalColumn"], "column"))})', f'    private {java_type} {ident(field["property"], "property")};']
        members.append('\n'.join(lines))
    annotations = ['@Data', '@NoArgsConstructor', '@AllArgsConstructor', '@Entity'] + (['@DynamicInsert', '@DynamicUpdate'] if dynamic_dml else []) + [f'@Table(name = {java_string(table)})']
    import_lines = '\n'.join(f'import {i};' for i in sorted(imports))
    return f'package {package_of(path)};\n\n{import_lines}\n\n' + '\n'.join(annotations) + f'\npublic class {name} {{\n\n' + '\n\n'.join(members) + '\n}\n'


def jpa_repository(path: str, entity_fqn: str, specification: bool) -> str:
    name = class_of(path)
    extra = ', JpaSpecificationExecutor<{}>'.format(entity_fqn.rsplit('.', 1)[-1]) if specification else ''
    imports = [entity_fqn, 'org.springframework.data.jpa.repository.JpaRepository']
    if specification:
        imports.append('org.springframework.data.jpa.repository.JpaSpecificationExecutor')
    imports.append('org.springframework.stereotype.Repository')
    entity = entity_fqn.rsplit('.', 1)[-1]
    return (f'package {package_of(path)};\n\n' + '\n'.join(f'import {i};' for i in sorted(imports)) +
            f'\n\n@Repository\npublic interface {name} extends JpaRepository<{entity}, Long>{extra} {{\n}}\n')
