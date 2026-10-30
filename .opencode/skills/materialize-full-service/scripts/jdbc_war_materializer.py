"""Materializer of the generation profile `war-jdbc-callablestatement-junit4`.

Rules of this profile come from its archetype (claro-spring-java-8): JDBC
CallableStatement through a JNDI DataSource, DAO interface + class, per-class
SLF4J logging (J8-D-003), JUnit 4 + Mockito, WAR. No JPA, ActivityLogger or
Checkstyle. Every behavior is read from the implementation plan; nothing is
invented here. The pure function `render_project` has no side effects.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

PROFILE = 'war-jdbc-callablestatement-junit4'
VERSION = 'jdbc-war-materializer-3-explicit-bindings'
TOKEN = re.compile(r'@@([A-Z0-9_]+)@@')
OBFUSC = '%%'
WORDS = ['CERO', 'UNO', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE', 'DIEZ', 'ONCE', 'DOCE', 'TRECE', 'CATORCE', 'QUINCE', 'DIECISEIS',
         'DIECISIETE', 'DIECIOCHO', 'DIECINUEVE', 'VEINTE', 'VEINTIUNO', 'VEINTIDOS', 'VEINTITRES', 'VEINTICUATRO']


def T(text: str, **kw) -> str:
    for key, value in kw.items():
        text = text.replace(f'%%{key}%%', value)
    return text


def jstr(value) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def cap(name: str) -> str:
    return name[0].upper() + name[1:]


def indent(lines, n=1):
    pad = '    ' * n
    return [(pad + line) if line else line for line in lines]


def package_of(path: str) -> str:
    rel = path.split('src/main/java/', 1)[1] if 'src/main/java/' in path else path.split('src/test/java/', 1)[1]
    return '.'.join(rel.split('/')[:-1])



class Ctx:
    """Generation context: plan data + registries of constants and external properties."""

    FIXED = (('SEPARADOR', '===================================================='), ('INICIO_ACTIVIDAD', '====[INICIO ACTIVIDAD]: '),
             ('FIN_ACTIVIDAD', ' ======== [ FIN ACTIVIDAD : '), ('SEPARADOR_ACTIVIDAD', ' ] ========'), ('CADENA_VACIA', ''),
             ('CADENA_CERO', '0'), ('PUNTO', '.'), ('COMA_ESPACIO', ', '), ('CALL', '{call '), ('TX_CIERRE', '] '), ('SEPARADOR_VALOR', ' = '),
             ('PARENTESIS_ABRE', '('), ('DATASOURCE_CRMLITE', 'dataSourceCRMLITE'))

    def __init__(self, plan: dict, repo: Path = None):
        self.plan = plan
        self.base = plan['service']['basePackage']
        self.pkg_of = {}
        for entry in plan['files']['generate']:
            path = entry['path']
            if path.endswith('.java'):
                self.pkg_of[Path(path).stem] = package_of(path)
        self.models = {m['name']: m for m in plan['models']}
        self.ops = plan['operations']
        self.style = plan['technicalProfile']['style']
        self.jndi_key = plan['technicalProfile']['jndiPropertyKey']
        self.consts = {}
        self.by_value = {}
        for name, value in self.FIXED:
            if name == 'DATASOURCE_CRMLITE':
                value = self.style['dataSourceBean']
            self.consts[name] = ('String', value)
            self.by_value[value] = name
        for name, value in (plan['technicalProfile'].get('utilityConstants') or {}).items():
            kind = 'int' if isinstance(value, int) and not isinstance(value, bool) else 'String'
            self.consts[name] = (kind, value)
            if kind == 'String':
                self.by_value.setdefault(value, name)
        self.props = {}
        self.P = {}
        self._build_props()
        self.template_config = {}
        if repo is not None:
            self._apply_template_config(repo)

    def _config_template_text(self, repo: Path):
        from artifact_integrity import template_paths, safe_path
        root = repo / self.plan['inputs']['archetype']['path'] / 'template'
        targets = {entry['path'] for entry in self.plan['files']['generate']
                   if entry['componentType'] == 'archetype-configuration' and entry['path'].endswith('.j2')}
        candidates = [rel for rel in template_paths(root.parent)
                      if TOKEN.sub(lambda m: str(self.plan['templateParameters'][m.group(1)]), rel) in targets]
        if len(candidates) > 1:
            raise ValueError('unsupported JDBC multiple property configuration templates; explicit adapter required')
        return safe_path(root, candidates[0]).read_text(encoding='utf-8') if candidates else None

    def _apply_template_config(self, repo: Path):
        text = self._config_template_text(repo)
        for line in (text or '').splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                self.template_config[key.strip()] = value
        for key, value in self.template_config.items():
            if key in self.props:
                self.props[key]['suggestedValue'] = value
                self.props[key]['source'] = 'archetype template config/properties.config.j2 (J8-D-009)'

    def properties_block(self) -> str:
        lines = ['', '# Claves propias del servicio (generadas; los valores sin dato deben definirse por el operador)']
        for rec in self.props.values():
            if rec['key'] in self.template_config:
                continue
            value = rec['suggestedValue']
            if value is None:
                lines.append('# DEFINIR: ' + rec['source'])
            lines.append(f"{rec['key']}={'' if value is None else value}")
        return '\n'.join(lines) + '\n'

    def imports_for(self, types, own_pkg):
        found = set()
        for t in types:
            for name in re.findall(r'[A-Z][A-Za-z0-9]*', t):
                if name in self.pkg_of and self.pkg_of[name] != own_pkg:
                    found.add(f'{self.pkg_of[name]}.{name}')
        return sorted(found)

    def k(self, text, prefix='', name=None) -> str:
        """Registers a String literal as a constant of Constantes and returns its Java reference."""
        text = str(text)
        if text in self.by_value:
            return 'Constantes.' + self.by_value[text]
        base = name or (prefix + slug(text))
        if base[0].isdigit():
            base = 'C_' + base
        nm, i = base, 1
        while nm in self.consts:
            i += 1
            nm = f'{base}_{i}'
        self.consts[nm] = ('String', text)
        self.by_value[text] = nm
        return 'Constantes.' + nm

    def ki(self, number: int) -> str:
        name = f'{WORDS[number]}_INT' if number < len(WORDS) else f'NUM_{number}_INT'
        self.consts[name] = ('int', number)
        return 'Constantes.' + name

    def _add_prop(self, key, field, value, source):
        if key not in self.props:
            self.props[key] = {'key': key, 'field': field, 'suggestedValue': value, 'source': source}
        return field

    def _resp(self, oid, suffix, value, source, per_op=False):
        base = 'ws.' + suffix
        if not per_op and (base not in self.props or self.props[base]['suggestedValue'] == value):
            return self._add_prop(base, suffix, value, source)
        return self._add_prop(f'ws.{oid}.{suffix}', oid + cap(suffix), value, source)

    def _build_props(self):
        for op in self.ops:
            oid = op['operationId']
            out = op.get('outcomes') or {}
            p = {}
            inv = out['invalidParameters']
            msg = inv['message']
            p['inv_code'] = self._resp(oid, 'codigoIdf1', inv['code'], 'service-spec jdbcBinding.outcomes', per_op=True)
            p['inv_msg'] = self._resp(oid, 'mensajeIdf1', msg, 'service-spec jdbcBinding.outcomes', per_op=True)
            if op.get('implemented'):
                proc = op['procedure']
                p['ok'] = self._resp(oid, 'codigoIdf0', out['success'], 'service-spec jdbcBinding.outcomes', per_op=True)
                fail = out['procedureFailure']
                p['fail_code'] = self._resp(oid, 'codigoIdf2', fail['code'], 'service-spec jdbcBinding.outcomes', per_op=True)
                text = fail.get('message')
                p['fail_msg'] = self._resp(oid, 'mensajeIdf2', text, 'service-spec jdbcBinding.outcomes', per_op=True)
                p['to_code'] = self._resp(oid, 'codigoIdt1', out['timeout']['code'], 'service-spec jdbcBinding.outcomes', per_op=True)
                p['to_msg'] = self._resp(oid, 'mensajeIdt1', out['timeout']['message'], 'service-spec jdbcBinding.outcomes', per_op=True)
                p['un_code'] = self._resp(oid, 'codigoIdt2', out['unavailable']['code'], 'service-spec jdbcBinding.outcomes', per_op=True)
                p['un_msg'] = self._resp(oid, 'mensajeIdt2', out['unavailable']['message'], 'service-spec jdbcBinding.outcomes', per_op=True)
                parts = proc['name'].split('.')
                sp = parts[-1]
                pkg = parts[-2] if len(parts) > 1 else None
                p['owner'] = self._add_prop(f'bd.jdbc.{oid}.owner', oid + 'Owner', parts[-3], 'service-spec jdbcBinding.procedure.name') if len(parts) > 2 else None
                prefix, rest = sp.lower().split('_', 1) if '_' in sp else ('sp', sp.lower())
                rest = rest.replace('_', '')
                p['sp'] = self._add_prop(f'bd.jdbc.{oid}.procedure', oid + 'Procedure', sp, 'service-spec jdbcBinding.procedure.name')
                p['timeout'] = self._add_prop(f'bd.jdbc.{oid}.timeout', oid + 'Timeout', None,
                                              'sin dato en las fuentes: definir por el operador (segundos)')
                if pkg:
                    pk = pkg.lower()
                    pk = pk[4:] if pk.startswith('pkg_') else pk
                    p['pkg'] = self._add_prop(f'bd.jdbc.{oid}.package', oid + 'Package', pkg, 'service-spec jdbcBinding.procedure.name')
                else:
                    p['pkg'] = None
            self.P[oid] = p
        self.props.setdefault(self.jndi_key, {'key': self.jndi_key, 'field': None, 'suggestedValue': None,
                                              'source': 'entorno: nombre JNDI del DataSource (definir por el operador); leido en JdbcConfig'})

    def constantes_class(self) -> str:
        out = [f'package {self.base}.common.property;', '', 'public final class Constantes {', '']
        for name, (kind, value) in self.consts.items():
            out.append(f'    public static final String {name} = {jstr(value)};' if kind == 'String' else f'    public static final int {name} = {value};')
        out += ['', '    private Constantes() {', '    }', '}', '']
        return '\n'.join(out)

    def properties_class(self) -> str:
        out = [f'package {self.base}.common.property;', '', 'import org.springframework.beans.factory.annotation.Value;',
               'import org.springframework.context.annotation.Configuration;', '', '@Configuration', 'public class PropertiesExternos {', '']
        for rec in self.props.values():
            if rec['field']:
                out += [f'    @Value("${{{rec["key"]}}}")', f'    public String {rec["field"]};', '']
        out += ['}', '']
        return '\n'.join(out)

    def test_values(self) -> dict:
        values = {}
        for rec in self.props.values():
            if rec['field']:
                value = rec['suggestedValue']
                if value is None:
                    value = '5' if 'timeout' in rec['key'] else 'valor-' + rec['field']
                values[rec['field']] = value
        return values


def slug(text):
    t = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode()
    t = re.sub(r'[^A-Za-z0-9]+', '_', t).strip('_').upper()
    return t[:48].rstrip('_') or 'VALOR'


def required_properties(plan: dict, repo: Path = None) -> dict:
    """Registry of the external properties the operator must define (the generator never writes application*.properties)."""
    ctx = Ctx(plan, repo)
    rows = [{'key': r['key'], 'javaField': r['field'], 'suggestedValue': r['suggestedValue'], 'source': r['source']} for r in ctx.props.values()]
    return {'schemaVersion': 1, 'class': f'{ctx.base}.common.property.PropertiesExternos', 'note': 'Define these keys in the environment configuration; null suggestedValue = no source value.',
            'properties': rows}


def header(pkg, imports):
    out = [f'package {pkg};', '']
    for imp in sorted(set(imports)):
        out.append(f'import {imp};')
    if imports:
        out.append('')
    return out


def dto(ctx: Ctx, model: dict, pkg: str) -> str:
    types = [f['javaType'] for f in model['fields']]
    imports = ctx.imports_for(types, pkg)
    if any(t.startswith('List<') for t in types):
        imports.append('java.util.List')
    out = header(pkg, imports) + [f'public class {model["name"]} {{', '']
    for f in model['fields']:
        out.append(f'    private {f["javaType"]} {f["name"]};')
    for f in model['fields']:
        out += ['', f'    public {f["javaType"]} get{cap(f["name"])}() {{', f'        return {f["name"]};', '    }', '',
                f'    public void set{cap(f["name"])}({f["javaType"]} {f["name"]}) {{', f'        this.{f["name"]} = {f["name"]};', '    }']
    out += ['}', '']
    return '\n'.join(out)


def exceptions(ctx: Ctx) -> dict:
    p = ctx.base + '.common.exception'
    files = {}
    files['BaseException'] = T('''package %%P%%;

public class BaseException extends Exception {

    private static final long serialVersionUID = 1L;

    public BaseException(String message) {
        super(message);
    }

    public BaseException(String message, Throwable cause) {
        super(message, cause);
    }
}
''', P=p)
    for name, parent in (('DBException', 'BaseException'), ('DBTimeoutException', 'DBException'), ('DBDisponibilidadException', 'DBException')):
        files[name] = T('''package %%P%%;

public class %%N%% extends %%PARENT%% {

    private static final long serialVersionUID = 1L;

    public %%N%%(String message) {
        super(message);
    }

    public %%N%%(String message, Throwable cause) {
        super(message, cause);
    }
}
''', P=p, N=name, PARENT=parent)
    files['OperacionNoImplementadaException'] = T('''package %%P%%;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

/** Operacion declarada en el contrato cuya implementacion funcional esta pendiente (nunca simula exito). */
@ResponseStatus(HttpStatus.NOT_IMPLEMENTED)
public class OperacionNoImplementadaException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public OperacionNoImplementadaException(String message) {
        super(message);
    }
}
''', P=p)
    return files


def beans(ctx: Ctx) -> dict:
    p = ctx.base + '.common.bean'
    cab = [('accept', 'String'), ('aplicacion', 'String'), ('idTransaccion', 'String'), ('msgid', 'String'), ('timestamp', 'String'), ('userId', 'String')]
    out = {'Cabecera': dto(ctx, {'name': 'Cabecera', 'fields': [{'name': n, 'javaType': t} for n, t in cab]}, p)}
    out['ResultadoProcedimiento'] = dto(ctx, {'name': 'ResultadoProcedimiento', 'fields': [
        {'name': 'codigo', 'javaType': 'String'}, {'name': 'mensaje', 'javaType': 'String'}, {'name': 'filas', 'javaType': 'List<Map<String, Object>>'}]}, p).replace(
        'import java.util.List;\n', 'import java.util.List;\nimport java.util.Map;\n')
    return out


def proc_ops(ctx):
    return [o for o in ctx.ops if o.get('procedure')]


def dao_params(op):
    seen, params = {}, []
    for inp in op['procedure']['inputs']:
        name = inp['source']
        seen[name] = seen.get(name, 0) + 1
        params.append((name if seen[name] == 1 else f'{name}{seen[name]}', inp['javaType'], inp))
    return params


def dao_signature(op):
    args = ', '.join(f'{t} {n}' for n, t, _ in dao_params(op))
    return f'ResultadoProcedimiento {op["operationId"]}(String idTransaccion{", " if args else ""}{args})'


def dao_interface(ctx: Ctx) -> str:
    p = ctx.base + '.repository'
    imports = [ctx.base + '.common.bean.ResultadoProcedimiento', ctx.base + '.common.exception.DBDisponibilidadException',
               ctx.base + '.common.exception.DBTimeoutException']
    out = header(p, imports) + ['public interface CRMLITEDAO {', '']
    for op in proc_ops(ctx):
        out += [f'    {dao_signature(op)}', '            throws DBTimeoutException, DBDisponibilidadException;', '']
    for o in [o for o in ctx.ops if not o.get('implemented')]:
        out += [f'    // {o["pending"]}', f'    // Operacion {o["operationId"]}: sin metodo de acceso a datos hasta que Sparx defina tabla/procedimiento y mapeo de salida.', '']
    out += ['}', '']
    return '\n'.join(out)


def dao_class(ctx: Ctx) -> str:
    k = ctx.k
    p = ctx.base + '.repository'
    imports = [ctx.base + '.common.bean.ResultadoProcedimiento', ctx.base + '.common.exception.DBDisponibilidadException',
               ctx.base + '.common.exception.DBTimeoutException', ctx.base + '.common.property.Constantes', ctx.base + '.common.property.PropertiesExternos',
               'java.sql.CallableStatement', 'java.sql.Connection', 'java.sql.ResultSet',
               'java.sql.SQLException', 'java.sql.SQLTimeoutException', 'java.sql.Types', 'java.util.ArrayList', 'java.util.LinkedHashMap',
               'java.util.List', 'java.util.Map', 'javax.sql.DataSource', 'org.apache.commons.lang3.StringUtils', 'org.hibernate.dialect.OracleTypesHelper', 'org.slf4j.Logger',
               'org.slf4j.LoggerFactory', 'org.springframework.beans.factory.annotation.Autowired', 'org.springframework.beans.factory.annotation.Qualifier',
               'org.springframework.stereotype.Repository']
    out = header(p, imports) + ['@Repository', 'public class CRMLITERepository implements CRMLITEDAO {', '',
                                '    private static final Logger logger = LoggerFactory.getLogger(CRMLITERepository.class);', '',
                                '    @Autowired', '    private PropertiesExternos prop;', '',
                                '    @Autowired', '    @Qualifier(Constantes.DATASOURCE_CRMLITE)', '    private DataSource dataSource;', '',
                                 '    private String nombreProcedimiento(String owner, String paquete, String procedimiento) {',
                                 '        StringBuilder nombre = new StringBuilder();', '        if (StringUtils.isNotBlank(owner)) {',
                                 '            nombre.append(owner).append(Constantes.PUNTO);', '        }', '        if (StringUtils.isNotBlank(paquete)) {',
                                '            nombre.append(paquete).append(Constantes.PUNTO);', '        }', '        return nombre.append(procedimiento).toString();', '    }', '']
    for op in proc_ops(ctx):
        proc = op['procedure']
        pp = ctx.P[op['operationId']]
        params = dao_params(op)
        marks = ', '.join('?' * 1 for _ in range(len(params) + 2 + (1 if proc.get('cursor') else 0)))
        n_in = len(params)
        i_code, i_msg, i_cur = n_in + 1, n_in + 2, n_in + 3
        oid = op['operationId']
        pkg_ref = f'prop.{pp["pkg"]}' if pp.get('pkg') else 'null'
        owner_ref = f'prop.{pp["owner"]}' if pp.get('owner') else 'null'
        body = ['    @Override', f'    public {dao_signature(op)}',
                '            throws DBTimeoutException, DBDisponibilidadException {',
                f'        String menTran = {k("[" + oid + " ", name="TX_" + slug(oid))} + idTransaccion + Constantes.TX_CIERRE;',
                '        long inicio = System.currentTimeMillis();',
                 f'        String sql = Constantes.CALL + nombreProcedimiento({owner_ref}, {pkg_ref}, prop.{pp["sp"]}) + {k("(" + marks + ")}", name="MARCAS_" + slug(oid))};',
                f'        logger.info(menTran + {k("Invocando procedimiento: ", "LOG_")} + sql);']
        for n, _, inp in params:
            body.append(f'        logger.info(menTran + {k("Parametro input: ", "LOG_")} + {k(inp["parameter"], "PI_")} + Constantes.SEPARADOR_VALOR + {n});')
        body += ['        ResultadoProcedimiento resultado = new ResultadoProcedimiento();',
                 '        try (Connection con = dataSource.getConnection();', '                CallableStatement cs = con.prepareCall(sql)) {',
                 f'            cs.setQueryTimeout(Integer.parseInt(prop.{pp["timeout"]}));']
        for idx, (n, t, _) in enumerate(params, 1):
            if t == 'Integer':
                body += [f'            if ({n} == null) {{', f'                cs.setNull({ctx.ki(idx)}, Types.INTEGER);', '            } else {', f'                cs.setInt({ctx.ki(idx)}, {n});', '            }']
            else:
                body.append(f'            cs.setString({ctx.ki(idx)}, {n});')
        body += [f'            cs.registerOutParameter({ctx.ki(i_code)}, Types.VARCHAR);', f'            cs.registerOutParameter({ctx.ki(i_msg)}, Types.VARCHAR);']
        if proc.get('cursor'):
            body.append(f'            cs.registerOutParameter({ctx.ki(i_cur)}, OracleTypesHelper.INSTANCE.getOracleCursorTypeSqlType());')
        body += ['            cs.execute();', f'            resultado.setCodigo(cs.getString({ctx.ki(i_code)}));', f'            resultado.setMensaje(cs.getString({ctx.ki(i_msg)}));',
                 '            List<Map<String, Object>> filas = new ArrayList<Map<String, Object>>();']
        if proc.get('cursor'):
            cols = ', '.join(k(c, 'COL_') for c in proc['columns'])
            body += [f'            try (ResultSet rs = (ResultSet) cs.getObject({ctx.ki(i_cur)})) {{', '                String[] columnas = {' + cols + '};',
                     '                while (rs != null && rs.next()) {', '                    Map<String, Object> fila = new LinkedHashMap<String, Object>();',
                     '                    for (String columna : columnas) {', '                        fila.put(columna, rs.getObject(columna));', '                    }',
                     '                    filas.add(fila);', '                }', '            }']
        body += ['            resultado.setFilas(filas);',
                 f'            logger.info(menTran + {k("Parametro output: ", "LOG_")} + {k(proc["codeOutput"], "PO_")} + Constantes.SEPARADOR_VALOR + resultado.getCodigo());',
                 f'            logger.info(menTran + {k("Parametro output: ", "LOG_")} + {k(proc["messageOutput"], "PO_")} + Constantes.SEPARADOR_VALOR + resultado.getMensaje());',
                 f'            logger.info(menTran + {k("Filas del cursor: ", "LOG_")} + filas.size());',
                 '        } catch (SQLTimeoutException e) {', f'            logger.error(menTran + {k("Timeout en el procedimiento ", "LOG_")} + sql, e);',
                 f'            throw new DBTimeoutException({k("Timeout en ", "MSG_")} + sql, e);', '        } catch (SQLException e) {',
                 f'            logger.error(menTran + {k("Error de base de datos en ", "LOG_")} + sql, e);',
                 f'            throw new DBDisponibilidadException({k("Error de disponibilidad en ", "MSG_")} + sql, e);',
                 '        } finally {', f'            logger.info(menTran + {k("Tiempo total (ms): ", "LOG_")} + (System.currentTimeMillis() - inicio));', '        }',
                 '        return resultado;', '    }', '']
        out += body
    out += ['}', '']
    return '\n'.join(out)


def jdbc_config(ctx: Ctx) -> str:
    return T('''package %%P%%;

import javax.sql.DataSource;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.lookup.JndiDataSourceLookup;

import %%B%%.common.property.Constantes;

/** DataSource de CRMLITE obtenido por JNDI; el nombre JNDI se define en la configuracion externa del entorno. */
@Configuration
public class JdbcConfig {

    @Value("${%%KEY%%}")
    public String crmlitejndiname;

    @Bean(name = Constantes.DATASOURCE_CRMLITE, destroyMethod = Constantes.CADENA_VACIA)
    public DataSource dataSourceCRMLITE() {
        return new JndiDataSourceLookup().getDataSource(crmlitejndiname);
    }
}
''', P=ctx.base + '.repository', KEY=ctx.jndi_key, B=ctx.base)


def out_cls(ctx, op):
    resp = ctx.models[op['responseClass']]
    f = {x['name']: x['javaType'] for x in resp['fields']}
    return f['responseAudit'], f['responseData']


def service_class(ctx: Ctx) -> str:
    k = ctx.k
    p = ctx.base + '.service'
    types = []
    for op in ctx.ops:
        types += [op['requestClass'], op['responseClass'], *out_cls(ctx, op)]
        if op.get('procedure') and op['procedure'].get('rowTarget'):
            types.append(op['procedure']['rowTarget']['rowClass'])
            if op['procedure']['rowTarget'].get('listItemClass'):
                types.append(op['procedure']['rowTarget']['listItemClass'])
    imports = ctx.imports_for(types, p) + [ctx.base + '.common.bean.Cabecera', ctx.base + '.common.bean.ResultadoProcedimiento',
              ctx.base + '.common.exception.OperacionNoImplementadaException', ctx.base + '.common.exception.DBDisponibilidadException',
              ctx.base + '.common.exception.DBTimeoutException', ctx.base + '.common.property.Constantes', ctx.base + '.common.util.ClaroUtil', ctx.base + '.common.property.PropertiesExternos',
              ctx.base + '.repository.CRMLITEDAO',
              'java.util.ArrayList', 'java.util.List', 'java.util.Map', 'org.apache.commons.lang3.StringUtils', 'org.slf4j.Logger', 'org.slf4j.LoggerFactory',
              'org.springframework.beans.factory.annotation.Autowired', 'org.springframework.stereotype.Component']
    tag_param = k('[PARAMETROS]', name='TAG_PARAMETROS')
    tag_po = k('[PO_MSG_RESPUESTA(Act.2.0)]', name='TAG_PO_MSG_RESPUESTA')
    out = header(p, imports) + ['@Component', 'public class AtencionService {', '',
                                '    private static final Logger logger = LoggerFactory.getLogger(AtencionService.class);',
                                '    @Autowired', '    private CRMLITEDAO crmlitedao;', '',
                                '    @Autowired', '    private PropertiesExternos prop;', '']
    log_req, log_resp = k('Request: ', 'LOG_'), k('Respuesta: ', 'LOG_')
    for op in ctx.ops:
        oid, req_c, resp_c = op['operationId'], op['requestClass'], op['responseClass']
        audit_c, data_c = out_cls(ctx, op)
        pp = ctx.P[oid]
        act_v, act_p = k(op['activities']['validate'], 'ACT_'), k(op['activities']['persist'], 'ACT_')
        body = [f'    public {resp_c} {oid}({req_c} request, Cabecera cabecera) {{',
                f'        String menTran = {k("[" + oid + " ", name="TX_" + slug(oid))} + cabecera.getIdTransaccion() + Constantes.TX_CIERRE;',
                '        logger.info(menTran + Constantes.SEPARADOR);', f'        logger.info(menTran + {log_req} + ClaroUtil.printJSONString(request));',
                f'        {resp_c} response = new {resp_c}();', f'        {audit_c} audit = new {audit_c}();', '        audit.setIdTransaccion(cabecera.getIdTransaccion());',
                '        response.setResponseAudit(audit);', f'        {data_c} data = new {data_c}();', '        response.setResponseData(data);',
                f'        logger.info(menTran + Constantes.INICIO_ACTIVIDAD + {act_v} + Constantes.SEPARADOR_ACTIVIDAD);',
                '        List<String> faltantes = new ArrayList<String>();']
        for q in op['requiredQueryParams']:
            body.append(f'        if (ClaroUtil.validParamNullOrEmpty(cabecera.get{cap(q)}())) {{\n            faltantes.add({k(q, "PARAM_")});\n        }}')
        body += [f'        logger.info(menTran + Constantes.FIN_ACTIVIDAD + {act_v} + Constantes.SEPARADOR_ACTIVIDAD);',
                 '        if (!faltantes.isEmpty()) {', f'            audit.setCodigoRespuesta(prop.{pp["inv_code"]});',
                 f'            audit.setMensajeRespuesta(prop.{pp["inv_msg"]}.replace({tag_param}, StringUtils.join(faltantes, Constantes.COMA_ESPACIO)));',
                 f'            logger.info(menTran + {log_resp} + ClaroUtil.printJSONString(response));', '            return response;', '        }',
                 f'        logger.info(menTran + Constantes.INICIO_ACTIVIDAD + {act_p} + Constantes.SEPARADOR_ACTIVIDAD);']
        if not op.get('implemented'):
            pend = k(f'{oid}: {op["pending"]}', name='MSG_PENDIENTE_' + slug(oid))
            body += [f'        // {op["pending"]}', f'        logger.error(menTran + {pend});', f'        throw new OperacionNoImplementadaException({pend});', '    }', '']
            out += body
            continue
        proc = op['procedure']
        args = ', '.join((f'cabecera.get{cap(i["source"])}()' if i['origin'] == 'header' else f'request.get{cap(i["source"])}()') for i in proc['inputs'])
        body += ['        try {', f'            ResultadoProcedimiento resultado = crmlitedao.{oid}(cabecera.getIdTransaccion(){", " if args else ""}{args});']
        cond = k(proc['successCode'], name='SP_SUCCESS_' + slug(oid)) + '.equals(resultado.getCodigo())' + (' && !resultado.getFilas().isEmpty()' if proc['requireRows'] else '')
        rt = proc.get('rowTarget')
        body += [f'            if ({cond}) {{', f'                audit.setCodigoRespuesta(prop.{pp["ok"]});', '                audit.setMensajeRespuesta(resultado.getMensaje());']
        if rt:
            mapping = proc['columnMapping']
            body.append('                for (Map<String, Object> fila : resultado.getFilas()) {' if rt['many'] else '                Map<String, Object> fila = resultado.getFilas().get(0);')
            pad = '                    ' if rt['many'] else '                '
            body.append(f'{pad}{rt["rowClass"]} row = new {rt["rowClass"]}();')
            for m in mapping:
                conv = 'toInteger' if m['javaType'] == 'Integer' else 'toStr'
                body.append(f'{pad}row.set{cap(m["field"])}({conv}(fila.get({k(m["column"], "COL_")})));')
            if rt['many']:
                body += [f'{pad}{rt["listItemClass"]} item = new {rt["listItemClass"]}();', f'{pad}item.set{cap(rt["wrapperProperty"])}(row);',
                         f'{pad}lista.add(item);', '                }']
                idx = body.index('                for (Map<String, Object> fila : resultado.getFilas()) {')
                body.insert(idx, f'                List<{rt["listItemClass"]}> lista = new ArrayList<{rt["listItemClass"]}>();')
                body.append(f'                data.set{cap(rt["property"])}(lista);')
            else:
                body.append(f'                data.set{cap(rt["property"])}(row);')
        fail_expr = (f'prop.{pp["fail_msg"]}.replace({tag_po}, StringUtils.defaultString(resultado.getMensaje()))' if pp['fail_msg'] else 'resultado.getMensaje()')
        body += ['            } else {', f'                audit.setCodigoRespuesta(prop.{pp["fail_code"]});', f'                audit.setMensajeRespuesta({fail_expr});', '            }',
                 '        } catch (DBTimeoutException e) {', f'            audit.setCodigoRespuesta(prop.{pp["to_code"]});',
                 f'            audit.setMensajeRespuesta(prop.{pp["to_msg"]});', f'            logger.error(menTran + {k("Timeout", "LOG_")}, e);',
                 '        } catch (DBDisponibilidadException e) {', f'            audit.setCodigoRespuesta(prop.{pp["un_code"]});',
                 f'            audit.setMensajeRespuesta(prop.{pp["un_msg"]});', f'            logger.error(menTran + {k("Disponibilidad", "LOG_")}, e);', '        }',
                 f'        logger.info(menTran + Constantes.FIN_ACTIVIDAD + {act_p} + Constantes.SEPARADOR_ACTIVIDAD);',
                 f'        logger.info(menTran + {log_resp} + ClaroUtil.printJSONString(response));', '        return response;', '    }', '']
        out += body
    out += ['    private static String toStr(Object value) {', '        return value == null ? null : value.toString();', '    }', '',
            '    private static Integer toInteger(Object value) {', '        if (value == null) {', '            return null;', '        }',
            '        if (value instanceof Number) {', '            return Integer.valueOf(((Number) value).intValue());', '        }', '        try {',
            '            return Integer.valueOf(value.toString().trim());', '        } catch (NumberFormatException e) {', '            return null;', '        }', '    }', '',
            '}', '']
    return '\n'.join(out)


def controller_class(ctx: Ctx) -> str:
    k = ctx.k
    p = ctx.base + '.controller'
    types = []
    for op in ctx.ops:
        types += [op['requestClass'], op['responseClass']]
    imports = ctx.imports_for(types, p) + [ctx.base + '.common.bean.Cabecera', ctx.base + '.common.property.Constantes', ctx.base + '.common.util.ClaroUtil', ctx.base + '.service.AtencionService',
              'com.fasterxml.jackson.core.JsonProcessingException', 'org.slf4j.Logger', 'org.slf4j.LoggerFactory',
              'org.springframework.beans.factory.annotation.Autowired', 'org.springframework.http.MediaType', 'org.springframework.web.bind.annotation.RequestBody',
              'org.springframework.web.bind.annotation.RequestMapping', 'org.springframework.web.bind.annotation.RequestMethod',
              'org.springframework.web.bind.annotation.RequestParam', 'org.springframework.web.bind.annotation.RestController']
    out = header(p, imports) + ['@RestController', 'public class AtencionController {', '',
                                '    private static final Logger logger = LoggerFactory.getLogger(AtencionController.class);',
                                '    @Autowired', '    private AtencionService atencionService;', '']
    for op in ctx.ops:
        oid = op['operationId']
        qs = op['requiredQueryParams']
        params = ', '.join(f'@RequestParam(value = {k(q, "PARAM_")}, required = false) String {q}' for q in qs)
        path = k(op['path'], name='PATH_' + slug(oid))
        out += [f'    @RequestMapping(value = {path}, method = RequestMethod.{op["httpMethod"]}, produces = MediaType.APPLICATION_JSON_VALUE)',
                f'    public {op["responseClass"]} {oid}({params},', f'            @RequestBody(required = false) {op["requestClass"]} request) {{',
                '        long inicio = System.currentTimeMillis();', f'        String menTran = {k("[" + oid + " ", name="TX_" + slug(oid))} + idTransaccion + Constantes.TX_CIERRE;',
                '        Cabecera cabecera = new Cabecera();']
        for q in qs:
            out.append(f'        cabecera.set{cap(q)}({q});')
        out += ['        logger.info(menTran + Constantes.SEPARADOR);', f'        logger.info(menTran + {k(f"[INICIO DEL METODO: {oid}]", "LOG_")});',
                f'        logger.info(menTran + {k("Header: ", "LOG_")} + toJson(cabecera));', f'        logger.info(menTran + {k("Body: ", "LOG_")} + toJson(request));',
                f'        {op["requestClass"]} entrada = request == null ? new {op["requestClass"]}() : request;',
                f'        {op["responseClass"]} response = atencionService.{oid}(entrada, cabecera);',
                f'        logger.info(menTran + {k("Response: ", "LOG_")} + toJson(response));',
                f'        logger.info(menTran + {k("Tiempo total (ms): ", "LOG_")} + (System.currentTimeMillis() - inicio));',
                f'        logger.info(menTran + {k(f"[FIN DEL METODO: {oid}]", "LOG_")});', '        return response;', '    }', '']
    out += ['    private static String toJson(Object value) {', '        try {', '            return ClaroUtil.printPrettyJSONString(value);',
            '        } catch (JsonProcessingException e) {', '            return Constantes.CADENA_VACIA;', '        }', '    }', '}', '']
    return '\n'.join(out)


def sample(java_type, column=None):
    return ('Integer.valueOf(7)', 'Integer.valueOf(7)') if java_type == 'Integer' else ('"valor"', '"valor"')


def props_setup(ctx: Ctx):
    return [f'        prop.{field} = {jstr(value)};' for field, value in ctx.test_values().items()]


def service_test(ctx: Ctx) -> str:
    p = ctx.base + '.service'
    types = []
    for op in ctx.ops:
        types += [op['requestClass'], op['responseClass']]
    imports = ctx.imports_for(types, p) + [ctx.base + '.common.bean.Cabecera', ctx.base + '.common.bean.ResultadoProcedimiento',
              ctx.base + '.common.exception.OperacionNoImplementadaException', ctx.base + '.common.exception.DBDisponibilidadException',
              ctx.base + '.common.exception.DBTimeoutException', ctx.base + '.common.property.PropertiesExternos', ctx.base + '.repository.CRMLITEDAO',
              'java.sql.SQLException', 'java.sql.SQLTimeoutException',
              'java.util.ArrayList', 'java.util.LinkedHashMap', 'java.util.List', 'java.util.Map', 'org.junit.Assert', 'org.junit.Before', 'org.junit.Test',
              'org.mockito.InjectMocks', 'org.mockito.Mock', 'org.mockito.Mockito', 'org.mockito.MockitoAnnotations', 'org.mockito.Spy']
    out = header(p, imports) + ['public class AtencionServiceTest {', '', '    @Mock', '    private CRMLITEDAO crmlitedao;', '', '    @Spy',
                                '    private PropertiesExternos prop = new PropertiesExternos();', '', '    @InjectMocks',
                                '    private AtencionService atencionService;', '', '    @Before', '    public void setUp() {', '        MockitoAnnotations.initMocks(this);',
                                *props_setup(ctx), '    }', '']
    out += ['    private Cabecera cabecera(String... faltantes) {', '        Cabecera c = new Cabecera();', '        c.setAccept("application/json");', '        c.setAplicacion("APP");',
            '        c.setIdTransaccion("TX1");', '        c.setMsgid("M1");', '        c.setTimestamp("2026-01-01T00:00:00Z");', '        c.setUserId("USR");',
            '        for (String faltante : faltantes) {', '            if ("accept".equals(faltante)) {', '                c.setAccept(null);', '            } else if ("aplicacion".equals(faltante)) {',
            '                c.setAplicacion(null);', '            } else if ("idTransaccion".equals(faltante)) {', '                c.setIdTransaccion(null);',
            '            } else if ("msgid".equals(faltante)) {', '                c.setMsgid(null);', '            } else if ("timestamp".equals(faltante)) {',
            '                c.setTimestamp(null);', '            } else if ("userId".equals(faltante)) {', '                c.setUserId(null);', '            }', '        }', '        return c;', '    }', '']
    for op in ctx.ops:
        oid, req, resp = op['operationId'], op['requestClass'], op['responseClass']
        pp = ctx.P[oid]
        first = op['requiredQueryParams'][0]
        out += ['    @Test', f'    public void {oid}ParametrosFaltantes() {{', f'        {resp} r = atencionService.{oid}(new {req}(), cabecera({jstr(first)}));',
                f'        Assert.assertEquals(prop.{pp["inv_code"]}, r.getResponseAudit().getCodigoRespuesta());',
                (f'        Assert.assertTrue(r.getResponseAudit().getMensajeRespuesta().contains({jstr(first)}));'
                 if '[PARAMETROS]' in op['outcomes']['invalidParameters']['message'] else
                 f'        Assert.assertEquals(prop.{pp["inv_msg"]}, r.getResponseAudit().getMensajeRespuesta());'),
                '    }', '']
        if not op.get('implemented'):
            out += ['    @Test(expected = OperacionNoImplementadaException.class)', f'    public void {oid}OperacionPendiente() {{', f'        atencionService.{oid}(new {req}(), cabecera());', '    }', '']
            continue
        proc = op['procedure']
        nargs = len(dao_params(op)) + 1
        anys = ', '.join(['Mockito.any()'] * nargs)
        call = f'crmlitedao.{oid}({anys})'
        rt = proc.get('rowTarget')
        out += ['    @Test', f'    public void {oid}Exito() throws Exception {{', '        ResultadoProcedimiento rp = new ResultadoProcedimiento();',
                f'        rp.setCodigo({jstr(proc["successCode"])});', '        rp.setMensaje("OK");', '        List<Map<String, Object>> filas = new ArrayList<Map<String, Object>>();']
        if proc.get('cursor'):
            out.append('        Map<String, Object> fila = new LinkedHashMap<String, Object>();')
            for m in proc['columnMapping']:
                out.append(f'        fila.put({jstr(m["column"])}, {sample(m["javaType"])[0]});')
            out.append('        filas.add(fila);')
        out += ['        rp.setFilas(filas);', f'        Mockito.when({call}).thenReturn(rp);', f'        {resp} r = atencionService.{oid}(new {req}(), cabecera());',
                f'        Assert.assertEquals(prop.{pp["ok"]}, r.getResponseAudit().getCodigoRespuesta());',
                '        Assert.assertEquals("TX1", r.getResponseAudit().getIdTransaccion());']
        if rt:
            access = f'r.getResponseData().get{cap(rt["property"])}()' + (f'.get(0).get{cap(rt["wrapperProperty"])}()' if rt['many'] else '')
            for m in proc['columnMapping']:
                out.append(f'        Assert.assertEquals({sample(m["javaType"])[1]}, {access}.get{cap(m["field"])}());')
        out += ['    }', '', '    @Test', f'    public void {oid}ErrorDelProcedimiento() throws Exception {{', '        ResultadoProcedimiento rp = new ResultadoProcedimiento();',
                f'        rp.setCodigo({jstr("!" + proc["successCode"])});', '        rp.setMensaje("fallo");', '        rp.setFilas(new ArrayList<Map<String, Object>>());', f'        Mockito.when({call}).thenReturn(rp);',
                f'        {resp} r = atencionService.{oid}(new {req}(), cabecera());', f'        Assert.assertEquals(prop.{pp["fail_code"]}, r.getResponseAudit().getCodigoRespuesta());', '    }', '',
                '    @Test', f'    public void {oid}Timeout() throws Exception {{',
                f'        Mockito.when({call}).thenThrow(new DBTimeoutException("t", new SQLTimeoutException()));',
                f'        {resp} r = atencionService.{oid}(new {req}(), cabecera());', f'        Assert.assertEquals(prop.{pp["to_code"]}, r.getResponseAudit().getCodigoRespuesta());', '    }', '',
                '    @Test', f'    public void {oid}Disponibilidad() throws Exception {{',
                f'        Mockito.when({call}).thenThrow(new DBDisponibilidadException("d", new SQLException()));',
                f'        {resp} r = atencionService.{oid}(new {req}(), cabecera());', f'        Assert.assertEquals(prop.{pp["un_code"]}, r.getResponseAudit().getCodigoRespuesta());', '    }', '']
    out += ['}', '']
    return '\n'.join(out)


def controller_test(ctx: Ctx) -> str:
    p = ctx.base + '.controller'
    types = []
    for op in ctx.ops:
        types += [op['requestClass'], op['responseClass']]
    imports = ctx.imports_for(types, p) + [ctx.base + '.common.bean.Cabecera', ctx.base + '.common.exception.OperacionNoImplementadaException', ctx.base + '.service.AtencionService',
              'org.junit.Assert', 'org.junit.Before', 'org.junit.Test', 'org.mockito.InjectMocks', 'org.mockito.Mock', 'org.mockito.Mockito', 'org.mockito.MockitoAnnotations']
    out = header(p, imports) + ['public class AtencionControllerTest {', '', '    @Mock', '    private AtencionService atencionService;', '', '    @InjectMocks',
                                '    private AtencionController atencionController;', '', '    @Before', '    public void setUp() {', '        MockitoAnnotations.initMocks(this);', '    }', '']
    for op in ctx.ops:
        oid, req, resp = op['operationId'], op['requestClass'], op['responseClass']
        args = ', '.join(['"v"'] * len(op['requiredQueryParams']))
        if op.get('implemented'):
            out += ['    @Test', f'    public void {oid}DelegaEnElServicio() {{', f'        {resp} esperado = new {resp}();',
                    f'        Mockito.when(atencionService.{oid}(Mockito.any({req}.class), Mockito.any(Cabecera.class))).thenReturn(esperado);',
                    f'        Assert.assertSame(esperado, atencionController.{oid}({args}, new {req}()));', '    }', '']
        else:
            out += ['    @Test(expected = OperacionNoImplementadaException.class)', f'    public void {oid}PropagaOperacionPendiente() {{',
                    f'        Mockito.when(atencionService.{oid}(Mockito.any({req}.class), Mockito.any(Cabecera.class))).thenThrow(new OperacionNoImplementadaException("pendiente"));',
                    f'        atencionController.{oid}({args}, new {req}());', '    }', '']
        out += ['    @Test', f'    public void {oid}ConCuerpoNuloUsaSolicitudVacia() {{',
                f'        Mockito.when(atencionService.{oid}(Mockito.any({req}.class), Mockito.any(Cabecera.class))).thenReturn(new {resp}());',
                f'        Assert.assertNotNull(atencionController.{oid}({args}, null));', '    }', '']
    out += ['}', '']
    return '\n'.join(out)


def repository_test(ctx: Ctx) -> str:
    p = ctx.base + '.repository'
    imports = [ctx.base + '.common.bean.ResultadoProcedimiento', ctx.base + '.common.exception.DBDisponibilidadException',
               ctx.base + '.common.exception.DBTimeoutException', ctx.base + '.common.property.PropertiesExternos', 'java.sql.CallableStatement',
               'java.sql.Connection', 'java.sql.ResultSet', 'java.sql.SQLException',
               'java.sql.SQLTimeoutException', 'javax.sql.DataSource', 'org.junit.Assert', 'org.junit.Before', 'org.junit.Test', 'org.mockito.InjectMocks', 'org.mockito.Mock',
               'org.mockito.Mockito', 'org.mockito.MockitoAnnotations', 'org.mockito.Spy']
    out = header(p, imports) + ['public class CRMLITERepositoryTest {', '', '    @Mock', '    private DataSource dataSource;', '', '    @Mock', '    private Connection connection;', '',
                                '    @Mock', '    private CallableStatement callableStatement;', '', '    @Mock', '    private ResultSet resultSet;', '', '    @Spy',
                                '    private PropertiesExternos prop = new PropertiesExternos();', '', '    @InjectMocks',
                                '    private CRMLITERepository repository;', '', '    @Before', '    public void setUp() throws Exception {', '        MockitoAnnotations.initMocks(this);',
                                *props_setup(ctx),
                                '        Mockito.when(dataSource.getConnection()).thenReturn(connection);', '        Mockito.when(connection.prepareCall(Mockito.anyString())).thenReturn(callableStatement);', '    }', '']
    for op in proc_ops(ctx):
        oid, proc = op['operationId'], op['procedure']
        params = dao_params(op)
        args = ', '.join(['"TX1"'] + ['Integer.valueOf(1)' if t == 'Integer' else '"x"' for _, t, _ in params])
        n = len(params)
        out += ['    @Test', f'    public void {oid}Exito() throws Exception {{', f'        Mockito.when(callableStatement.getString({n + 1})).thenReturn("0");',
                f'        Mockito.when(callableStatement.getString({n + 2})).thenReturn("OK");']
        if proc.get('cursor'):
            out += [f'        Mockito.when(callableStatement.getObject({n + 3})).thenReturn(resultSet);', '        Mockito.when(resultSet.next()).thenReturn(true, false);',
                    f'        Mockito.when(resultSet.getObject({jstr(proc["columns"][0])})).thenReturn("dato");']
        out += [f'        ResultadoProcedimiento r = repository.{oid}({args});', '        Assert.assertEquals("0", r.getCodigo());', '        Assert.assertEquals("OK", r.getMensaje());',
                f'        Assert.assertEquals({"1" if proc.get("cursor") else "0"}, r.getFilas().size());', '        Mockito.verify(callableStatement).execute();', '    }', '',
                '    @Test(expected = DBTimeoutException.class)', f'    public void {oid}Timeout() throws Exception {{',
                '        Mockito.when(callableStatement.execute()).thenThrow(new SQLTimeoutException("t"));', f'        repository.{oid}({args});', '    }', '',
                '    @Test(expected = DBDisponibilidadException.class)', f'    public void {oid}Disponibilidad() throws Exception {{',
                '        Mockito.when(callableStatement.execute()).thenThrow(new SQLException("d"));', f'        repository.{oid}({args});', '    }', '']
    out += ['}', '']
    return '\n'.join(out)


def render_template(repo: Path, plan: dict) -> dict:
    root = repo / plan['inputs']['archetype']['path'] / 'template'
    values = plan['templateParameters']
    files = {}
    from artifact_integrity import template_paths, safe_path
    for rel in template_paths(root.parent):
        path = safe_path(root, rel)
        text = path.read_text(encoding='utf-8')
        for source in (rel, text):
            missing = {t for t in TOKEN.findall(source) if t not in values}
            if missing:
                raise ValueError(f'template {rel}: unresolved parameter(s) {sorted(missing)}')
        rendered = TOKEN.sub(lambda m: str(values[m.group(1)]), text)
        files[TOKEN.sub(lambda m: str(values[m.group(1)]), rel)] = ('project-assembly', rendered)
    return files


LITERAL = re.compile(r'"(?:[^"\\\n]|\\.)*"')
COMMENTS = re.compile(r'/\*.*?\*/|//[^\n]*', re.S)
LITERAL_EXEMPT = ('common/property/Constantes.java', 'common/property/PropertiesExternos.java', 'repository/JdbcConfig.java')


def style_violations(java: dict) -> list:
    """Archetype style rule: no string literal in main code outside the constants/properties/config classes."""
    found = []
    for path, text in java.items():
        if '/src/test/' in '/' + path or path.endswith(LITERAL_EXEMPT) or '/canonical/' in path:
            continue
        code = COMMENTS.sub('', text)
        for match in LITERAL.finditer(code):
            found.append(f'{path}: {match.group(0)[:40]}')
    return found


def render_project(plan: dict, repo: Path) -> dict:
    """Returns {path: (componentType, text)} for the whole project (template + Java)."""
    import jdbc_contract
    if plan.get('plan', {}).get('jdbcBindingVersion') != 1:
        raise ValueError('unsupported-jdbc-binding: replan from explicit v1 bindings; legacy inferred plans cannot be materialized')
    names = jdbc_contract.naming({'technical': {'jdbcNames': plan['technicalProfile'].get('jdbcNames')}})
    model_index = {m['name']: m for m in plan['models']}
    for op in plan['operations']:
        jdbc_contract.validate({'version': 1, 'evidence': op.get('bindingEvidence'),
            'envelope': {'audit': 'responseAudit', 'data': 'responseData', 'code': 'codigoRespuesta', 'message': 'mensajeRespuesta', 'transaction': 'idTransaccion'},
            'policies': op['policies'], 'activities': op['activities'], 'outcomes': op['outcomes'], 'procedure': op['procedure']},
            {f['name']: f['javaType'] for f in model_index[op['requestClass']]['fields']},
            {f['name']: f['javaType'] for f in model_index[op['dataClass']]['fields']}, model_index)
    ctx = Ctx(plan, repo)
    out = dict(render_template(repo, plan))
    for path, (ctype, text) in list(out.items()):
        if path.endswith('.j2'):
            out[path] = (ctype, text.rstrip('\n') + '\n' + ctx.properties_block())
    java = {}
    planned = {e['path']: e for e in plan['files']['generate']}
    for path, entry in planned.items():
        name = Path(path).stem
        ct = entry['componentType']
        if ct == 'canonical-dto':
            java[path] = dto(ctx, ctx.models[name], package_of(path))
    for name, text in exceptions(ctx).items():
        java[f'src/main/java/{ctx.base.replace(".", "/")}/common/exception/{name}.java'] = text
    for name, text in beans(ctx).items():
        java[f'src/main/java/{ctx.base.replace(".", "/")}/common/bean/{name}.java'] = text
    b = ctx.base.replace('.', '/')
    java[f'src/main/java/{b}/repository/CRMLITEDAO.java'] = dao_interface(ctx)
    java[f'src/main/java/{b}/repository/CRMLITERepository.java'] = dao_class(ctx)
    java[f'src/main/java/{b}/repository/JdbcConfig.java'] = jdbc_config(ctx)
    java[f'src/main/java/{b}/service/AtencionService.java'] = service_class(ctx)
    java[f'src/main/java/{b}/controller/AtencionController.java'] = controller_class(ctx)
    java[f'src/test/java/{b}/service/AtencionServiceTest.java'] = service_test(ctx)
    java[f'src/test/java/{b}/controller/AtencionControllerTest.java'] = controller_test(ctx)
    java[f'src/test/java/{b}/repository/CRMLITERepositoryTest.java'] = repository_test(ctx)
    java[f'src/main/java/{b}/common/property/Constantes.java'] = ctx.constantes_class()
    java[f'src/main/java/{b}/common/property/PropertiesExternos.java'] = ctx.properties_class()
    # These are renderer-local role symbols, never defaults for a target service.
    # Only generated layer text is rewritten; contract DTO names remain source-owned.
    aliases = {'CRMLITEDAO': names['dao'], 'CRMLITERepository': names['repository'],
               'AtencionService': names['service'], 'AtencionController': names['controller']}
    substitutions = dict(aliases)
    substitutions.update({key + 'Test': value + 'Test' for key, value in aliases.items()})
    substitutions.update({'crmlitedao': names['dao'][0].lower() + names['dao'][1:],
                          'atencionService': names['service'][0].lower() + names['service'][1:],
                          'atencionController': names['controller'][0].lower() + names['controller'][1:]})
    pattern = re.compile(r'\b(' + '|'.join(map(re.escape, substitutions)) + r')\b')
    renamed = {}
    for path, text in java.items():
        if planned.get(path, {}).get('componentType') == 'canonical-dto':
            renamed[path] = text
            continue
        stem = Path(path).stem
        new_path = str(Path(path).with_name(substitutions.get(stem, stem) + '.java')).replace('\\', '/')
        renamed[new_path] = pattern.sub(lambda m: substitutions[m[0]], text)
    java = renamed
    violations = style_violations(java)
    if violations:
        raise ValueError('hard-coded literals outside Constantes/PropertiesExternos (archetype style J8-D-008): ' + '; '.join(violations[:10]))
    for path, text in java.items():
        if path not in planned:
            raise ValueError(f'generated file {path} is not planned')
        out[path] = (planned[path]['componentType'], text)
    missing = sorted(p for p in planned if p not in out and planned[p]['action'] != 'retain')
    if missing:
        raise ValueError(f'planned files without generator: {missing}')
    if set(out) != set(planned) or len(planned) != len(plan['files']['generate']):
        raise ValueError('rendered inventory differs from plan (including technical/configuration files)')
    if any(entry['action'] not in ('create', 'update') for entry in planned.values()):
        raise ValueError('unsupported JDBC file action')
    return out


def _load_plan(ws, repo, fm):
    import hashlib
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
    if plan.get('plan', {}).get('jdbcBindingVersion') != 1:
        raise fm.MaterializationError('unsupported', 'JDBC inferred legacy plan: explicit service-spec jdbcBinding v1 and replanning required; no files were changed')
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
    import jdbc_war_plan
    try:
        expected, parameters = jdbc_war_plan.artifacts(repo, yaml, ws.dir / 'full-planning-input.yml')
        if plan != expected or parameters != load_mapping(ws.dir / 'generation-parameters.yml'):
            raise ValueError('JDBC plan/parameters differ from current authorized inputs; replan required')
    except (ValueError, KeyError, TypeError) as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    return plan, raw


def _register(plan, ws, fm):
    decisions_file = ws.dir / 'sparx-reviewed-decisions.yml'
    approved = set()
    if decisions_file.is_file():
        data = yaml.safe_load(decisions_file.read_bytes()) or {}
        approved = {d.get('decisionId') for d in data.get('decisions', []) if d.get('humanReviewed') is True}
    rows = []
    for item in plan.get('assumptions', []):
        decision = item.get('decision')
        if decision not in ('archetype',) and decision not in approved:
            raise fm.MaterializationError('invalid-plan', f'assumption {item.get("id")} cites decision {decision!r} that is not human-approved in sparx-reviewed-decisions.yml')
        rows.append({'id': item['id'], 'decision': decision, 'statement': item['statement']})
    return {'schemaVersion': 1, 'service': ws.service, 'materializer': VERSION, 'assumptions': rows,
            'implementedBindings': [{'operationId': op['operationId'], 'evidence': op['bindingEvidence'],
                                     'procedure': op['procedure'], 'policies': op['policies'], 'outcomes': op['outcomes']}
                                    for op in plan['operations']],
            'incompleteOperations': plan.get('incompleteOperations', [])}


def materialize(repo: Path, service: str, dry_run: bool = False) -> dict:
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
    register = _register(plan, ws, fm)
    from artifact_integrity import prepare, publish, IntegrityError
    payload = {p: text.encode('utf-8') for p, (_, text) in rendered.items()}
    try:
        to_write, unchanged = prepare(out_dir, ws.dir, payload, reject_obsolete=True)
    except fp.ProtectedFileError as error:
        raise fm.MaterializationError('protected-files', str(error), getattr(error, 'details', {})) from error
    except IntegrityError as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    rows = {p: {'sha256': fm.sha(text.encode('utf-8')), 'action': 'generated', 'componentType': ct}
            for p, (ct, text) in rendered.items()}
    incomplete = list(plan.get('incompleteOperations', []))
    manifest = {'schemaVersion': 1, 'materializer': VERSION, 'complete': True, 'service': service,
                'inputs': {'implementationPlanSha256': fm.sha(plan_bytes), 'serviceSpecSha256': fm.sha((ws.dir / 'service-spec.yml').read_bytes()),
                           'archetypeFingerprint': plan['inputs']['archetype']['fingerprint']},
                'fileInventory': [{'path': p, **rows[p]} for p in sorted(rows)], 'unsupportedComponents': [],
                'incompleteOperations': plan.get('incompleteOperations', []),
                'payloadTreeSha256': fm.tree_hash({p: r['sha256'] for p, r in rows.items()})}
    dump = lambda v: yaml.safe_dump(v, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
    manifest_bytes = dump(manifest)
    report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'profile': PROFILE,
              'status': 'complete-with-incomplete-operations' if incomplete else 'complete',
              'written': sorted(to_write), 'unchanged': sorted(unchanged), 'excludedUntouched': ['src/main/resources/application*.properties'],
              'incompleteOperations': plan.get('incompleteOperations', []), 'unsupported': [], 'payloadTreeSha256': manifest['payloadTreeSha256'],
              'manifestSha256': fm.sha(manifest_bytes), 'dryRun': dry_run,
              'validation': {'maven': 'not-run', 'compilation': 'not-verified', 'checkstyle': 'not-applicable'}}
    if dry_run:
        return report
    publish(out_dir, ws.dir, payload, manifest_bytes)
    fm.write_atomic(ws.dir / 'assumptions-register.yml', dump(register))
    fm.write_atomic(ws.dir / 'required-properties.yml', dump(required_properties(plan, repo)))
    fm.write_atomic(ws.dir / fm.REPORT, dump(report))
    return report
