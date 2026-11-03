"""Pure rendering of concrete `ports-flow` adapters (JDBC, REST, mail) and their technical helpers.

Every SQL statement, column, path, payload field and placeholder comes from the explicit normalized IR (`batch.adapters`,
all `assumed: true`); nothing is inferred here. Environment values are external properties (`PropertiesExterno`).
"""
import batch_ports_flow as pf

NUMERIC = {'Integer': 'entero', 'Long': 'largo', 'Boolean': 'logico'}


def adapter_for(batch, port_id):
    for adapter in batch.get('adapters') or []:
        if adapter['port'] == port_id:
            return adapter
    return None


def _by_name(adapter):
    return {m['name']: m for m in adapter['methods']}


def _ref(text):
    return pf._operand(text)


def conexion_bd_source(plan):
    package = plan['templateParameters']['BASE_PACKAGE']
    return '\n'.join([
        f'package {package}.util;', '',
        'import java.sql.Connection;', 'import java.sql.DriverManager;', 'import java.sql.SQLException;', '',
        'import org.springframework.beans.factory.annotation.Autowired;', 'import org.springframework.stereotype.Component;', '',
        '@Component', 'public class ConexionBd {', '',
        '  @Autowired', '  private PropertiesExterno externalProperties;', '',
        '  public Connection abrir() throws SQLException {',
        '    return DriverManager.getConnection(externalProperties.bdUrl, externalProperties.bdUser, externalProperties.bdPassword);',
        '  }', '}', ''])


def rest_cliente_source(plan):
    package = plan['templateParameters']['BASE_PACKAGE']
    return '\n'.join([
        f'package {package}.util;', '',
        'import org.apache.http.client.config.RequestConfig;', 'import org.apache.http.client.methods.CloseableHttpResponse;',
        'import org.apache.http.client.methods.HttpGet;', 'import org.apache.http.client.methods.HttpPatch;',
        'import org.apache.http.client.methods.HttpPost;', 'import org.apache.http.client.methods.HttpRequestBase;',
        'import org.apache.http.client.methods.HttpEntityEnclosingRequestBase;',
        'import org.apache.http.entity.ContentType;', 'import org.apache.http.entity.StringEntity;',
        'import org.apache.http.impl.client.CloseableHttpClient;', 'import org.apache.http.impl.client.HttpClients;',
        'import org.apache.http.util.EntityUtils;',
        'import org.springframework.beans.factory.annotation.Autowired;', 'import org.springframework.stereotype.Component;', '',
        '@Component', 'public class RestClienteHttp {', '',
        '  @Autowired', '  private PropertiesExterno externalProperties;', '',
        '  private HttpRequestBase crear(String metodo, String url, String cuerpoJson) throws Exception {',
        '    int tiempo = externalProperties.restTimeoutMs == null || externalProperties.restTimeoutMs.trim().isEmpty()',
        '        ? 0 : Integer.parseInt(externalProperties.restTimeoutMs.trim());',
        '    RequestConfig configuracion = RequestConfig.custom().setConnectTimeout(tiempo).setSocketTimeout(tiempo).build();',
        '    HttpRequestBase peticion;',
        '    if ("POST".equals(metodo)) {', '      peticion = new HttpPost(url);',
        '    } else if ("PATCH".equals(metodo)) {', '      peticion = new HttpPatch(url);',
        '    } else {', '      peticion = new HttpGet(url);', '    }',
        '    peticion.setConfig(configuracion);',
        '    if (cuerpoJson != null && peticion instanceof HttpEntityEnclosingRequestBase) {',
        '      ((HttpEntityEnclosingRequestBase) peticion).setEntity(new StringEntity(cuerpoJson, ContentType.APPLICATION_JSON));',
        '    }',
        '    return peticion;', '  }', '',
        '  public int ejecutarEstado(String metodo, String url, String cuerpoJson) throws Exception {',
        '    HttpRequestBase peticion = crear(metodo, url, cuerpoJson);',
        '    try (CloseableHttpClient cliente = HttpClients.createDefault(); CloseableHttpResponse respuesta = cliente.execute(peticion)) {',
        '      return respuesta.getStatusLine().getStatusCode();', '    }', '  }', '',
        '  public String ejecutar(String metodo, String url, String cuerpoJson) throws Exception {',
        '    HttpRequestBase peticion = crear(metodo, url, cuerpoJson);',
        '    try (CloseableHttpClient cliente = HttpClients.createDefault(); CloseableHttpResponse respuesta = cliente.execute(peticion)) {',
        '      int estado = respuesta.getStatusLine().getStatusCode();',
        '      if (estado == 404) {', '        return null;', '      }',
        '      String cuerpo = respuesta.getEntity() == null ? null : EntityUtils.toString(respuesta.getEntity(), "UTF-8");',
        '      if (estado >= 400) {',
        '        throw new IllegalStateException("Respuesta HTTP " + estado + " en " + metodo + " " + url);', '      }',
        '      return cuerpo == null || cuerpo.trim().isEmpty() ? null : cuerpo;', '    }', '  }', '}', ''])


def _dto_fields(batch):
    return {d['name']: {f['name']: f['type'] for f in d['fields']} for d in batch['dtos']}


def _elem(returns):
    return returns[5:-1] if returns.startswith('List<') else returns


def _db_method(batch, port, pm, am, needed):
    ret = pm['returns']
    sig = pf._sig(pm)
    const = 'SQL_' + ''.join(c if c.isalnum() else '_' for c in pm['name']).upper()
    binds = ''.join(f'\n      sentencia.setObject({i}, {_ref(b)});' for i, b in enumerate(am['bind'], 1))
    fields = _dto_fields(batch)
    head = [f'  private static final String {const} = {pf.literal(am["sql"])};', '',
            '  @Override', f'  public {sig} {{',
            f'    try (Connection conexion = conexionBd.abrir(); PreparedStatement sentencia = conexion.prepareStatement({const})) {{']
    if binds:
        head.append(binds.lstrip('\n'))
    result = am['result']
    body = []
    if result == 'none':
        body.append('      sentencia.executeUpdate();')
    else:
        body.append('      try (ResultSet filas = sentencia.executeQuery()) {')
        if result == 'scalar':
            needed.add(ret)
            body += ['        if (!filas.next()) {', '          return null;', '        }',
                     f'        return {_read(ret, "1")};']
        else:
            dto = _elem(ret)
            item = ['          ' + f'{dto} elemento = new {dto}();']
            for c in am['columns']:
                ftype = fields[dto][c['field']]
                needed.add(ftype)
                item.append(f'          elemento.set{pf.upper(c["field"])}({_read(ftype, pf.literal(c["column"]))});')
            if result == 'single':
                body += ['        if (!filas.next()) {', '          return null;', '        }']
                body += [l[2:] for l in item] + ['        return elemento;']
            else:
                body.append(f'        java.util.List<{dto}> lista = new java.util.ArrayList<>();')
                body.append('        while (filas.next()) {')
                body += item + ['          lista.add(elemento);', '        }', '        return lista;']
        body.append('      }')
    tail = ['    } catch (SQLException e) {',
            f'      throw new IllegalStateException({pf.literal("Error de base de datos en " + port["id"] + "." + pm["name"])}, e);',
            '    }', '  }']
    return head + body + tail


def _read(ftype, column):
    if ftype == 'String':
        return f'filas.getString({column})'
    return f'{NUMERIC[ftype]}(filas.getObject({column}))'


def _helper(ftype):
    if ftype == 'Integer':
        return ['  private static Integer entero(Object valor) {',
                '    return valor == null ? null : Integer.valueOf(((Number) valor).intValue());', '  }']
    if ftype == 'Long':
        return ['  private static Long largo(Object valor) {',
                '    return valor == null ? null : Long.valueOf(((Number) valor).longValue());', '  }']
    return ['  private static Boolean logico(Object valor) {',
            '    return valor == null ? null : Boolean.valueOf(valor instanceof Boolean ? (Boolean) valor : ((Number) valor).intValue() != 0);',
            '  }']


def db_adapter_source(plan, batch, port, adapter):
    package = plan['templateParameters']['BASE_PACKAGE']
    named = _by_name(adapter)
    dtos = {d['name'] for d in batch['dtos']}
    needed = set()
    methods = []
    for pm in port['methods']:
        methods += [''] + _db_method(batch, port, pm, named[pm['name']], needed)
    query = any(named[m['name']]['result'] != 'none' for m in port['methods'])
    lines = [f'package {package}.port;', '', 'import java.sql.Connection;', 'import java.sql.PreparedStatement;']
    if query:
        lines.append('import java.sql.ResultSet;')
    lines += ['import java.sql.SQLException;', '', 'import org.springframework.beans.factory.annotation.Autowired;',
              'import org.springframework.stereotype.Repository;', f'import {package}.util.ConexionBd;']
    lines += [f'import {package}.dto.{n};' for n in pf._port_types(port, dtos)]
    lines += ['', '@Repository', f'public class {port["id"]}Impl implements {port["id"]} {{', '',
              '  @Autowired', '  private ConexionBd conexionBd;']
    lines += methods
    for t in ('Integer', 'Long', 'Boolean'):
        if t in needed:
            lines += [''] + _helper(t)
    return '\n'.join(lines + ['}', ''])


def _rest_method(port, pm, am, dtos):
    sig = pf._sig(pm)
    url = f'externalProperties.rest{port["id"]}Url + {pf.literal(am["path"])}'
    if am['query']:
        for n, q in enumerate(am['query']):
            sep = '?' if n == 0 else '&'
            if 'from' in q:
                url += f' + {pf.literal(sep + q["name"] + "=")} + {_ref(q["from"])}'
            else:
                url += f' + {pf.literal(sep + q["name"] + "=" + q["value"])}'
    lines = ['  @Override', f'  public {sig} {{', '    try {']
    if am['body']:
        lines.append('      java.util.Map<String, Object> cuerpo = new java.util.LinkedHashMap<>();')
        lines += [f'      cuerpo.put({pf.literal(b["json"])}, {pf.literal(b["value"]) if "value" in b else _ref(b["from"])});' for b in am['body']]
        lines.append('      String cuerpoJson = MAPPER.writeValueAsString(cuerpo);')
        call = f'restCliente.ejecutar({pf.literal(am["httpMethod"])}, {url}, cuerpoJson)'
    else:
        call = f'restCliente.ejecutar({pf.literal(am["httpMethod"])}, {url}, null)'
    ret = pm['returns']
    if ret == 'Boolean':
        ok = ' || '.join(f'estado == {s}' for s in am.get('okStatus', []))
        test = 'estado >= 200 && estado < 300' + (f' || {ok}' if ok else '')
        call = call.replace('restCliente.ejecutar(', 'restCliente.ejecutarEstado(')
        lines.append(f'      int estado = {call};')
        lines += [f'      return Boolean.valueOf({test});', '    } catch (Exception e) {', '      return Boolean.FALSE;', '    }', '  }']
        return lines
    if ret == 'void':
        lines.append(f'      {call};')
    else:
        lines.append(f'      String respuesta = {call};')
        lines += ['      if (respuesta == null) {', '        return null;', '      }']
        if ret.startswith('List<'):
            lines.append(f'      return MAPPER.readValue(respuesta, new TypeReference<java.util.List<{_elem(ret)}>>() {{}});')
        else:
            lines.append(f'      return MAPPER.readValue(respuesta, {ret}.class);')
    lines += ['    } catch (Exception e) {',
              f'      throw new IllegalStateException({pf.literal("Error REST en " + port["id"] + "." + pm["name"])}, e);',
              '    }', '  }']
    return lines


def rest_adapter_source(plan, batch, port, adapter):
    package = plan['templateParameters']['BASE_PACKAGE']
    named = _by_name(adapter)
    dtos = {d['name'] for d in batch['dtos']}
    reads = any(m['returns'] != 'void' for m in port['methods'])
    lines = [f'package {package}.port;', '']
    if reads:
        lines.append('import com.fasterxml.jackson.core.type.TypeReference;')
    lines += ['import com.fasterxml.jackson.databind.DeserializationFeature;', 'import com.fasterxml.jackson.databind.ObjectMapper;',
              'import org.springframework.beans.factory.annotation.Autowired;', 'import org.springframework.stereotype.Component;',
              f'import {package}.util.PropertiesExterno;', f'import {package}.util.RestClienteHttp;']
    lines += [f'import {package}.dto.{n};' for n in pf._port_types(port, dtos)]
    lines += ['', '@Component', f'public class {port["id"]}Impl implements {port["id"]} {{', '',
              '  private static final ObjectMapper MAPPER = new ObjectMapper()',
              '      .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);', '',
              '  @Autowired', '  private RestClienteHttp restCliente;', '', '  @Autowired', '  private PropertiesExterno externalProperties;']
    for pm in port['methods']:
        lines += [''] + _rest_method(port, pm, named[pm['name']], dtos)
    return '\n'.join(lines + ['}', ''])


def mail_adapter_source(plan, batch, port, adapter):
    package = plan['templateParameters']['BASE_PACKAGE']
    named = _by_name(adapter)
    dtos = {d['name'] for d in batch['dtos']}
    lines = [f'package {package}.port;', '',
             'import java.util.Properties;', '', 'import javax.mail.Authenticator;', 'import javax.mail.Message;',
             'import javax.mail.MessagingException;', 'import javax.mail.PasswordAuthentication;', 'import javax.mail.Session;',
             'import javax.mail.Transport;', 'import javax.mail.internet.InternetAddress;', 'import javax.mail.internet.MimeMessage;', '',
             'import org.springframework.beans.factory.annotation.Autowired;', 'import org.springframework.stereotype.Component;',
             f'import {package}.util.PropertiesExterno;']
    lines += [f'import {package}.dto.{n};' for n in pf._port_types(port, dtos)]
    lines += ['', '@Component', f'public class {port["id"]}Impl implements {port["id"]} {{', '',
              '  @Autowired', '  private PropertiesExterno externalProperties;']
    for pm in port['methods']:
        am = named[pm['name']]
        cfg = pm['params'][0]['name']
        lines += ['', '  @Override', f'  public {pf._sig(pm)} {{',
                  f'    String asunto = {cfg}.getSubject();', f'    String cuerpo = {cfg}.getBody();']
        for ph in am['placeholders']:
            token, value = pf.literal(ph['token']), _ref(ph['from'])
            lines += [f'    asunto = reemplazar(asunto, {token}, {value});', f'    cuerpo = reemplazar(cuerpo, {token}, {value});']
        lines += ['    try {', '      MimeMessage mensaje = new MimeMessage(sesion());',
                  '      mensaje.setFrom(new InternetAddress(externalProperties.mailFrom));',
                  f'      destinatarios(mensaje, Message.RecipientType.TO, {cfg}.getTo());',
                  f'      destinatarios(mensaje, Message.RecipientType.CC, {cfg}.getCc());',
                  f'      destinatarios(mensaje, Message.RecipientType.BCC, {cfg}.getBcc());',
                  '      mensaje.setSubject(asunto);',
                  f'      String formato = {cfg}.getBodyFormat() != null && {cfg}.getBodyFormat().toLowerCase().contains("html") ? "html" : "plain";',
                  '      mensaje.setText(cuerpo, "UTF-8", formato);', '      Transport.send(mensaje);',
                  '    } catch (MessagingException e) {',
                  f'      throw new IllegalStateException({pf.literal("Error de correo en " + port["id"] + "." + pm["name"])}, e);',
                  '    }', '  }']
    lines += ['', '  private Session sesion() {', '    Properties propiedades = new Properties();',
              '    propiedades.put("mail.smtp.host", externalProperties.mailSmtpHost);',
              '    propiedades.put("mail.smtp.port", externalProperties.mailSmtpPort);',
              '    String usuario = externalProperties.mailSmtpUser;',
              '    if (usuario == null || usuario.isEmpty()) {', '      return Session.getInstance(propiedades);', '    }',
              '    propiedades.put("mail.smtp.auth", "true");',
              '    return Session.getInstance(propiedades, new Authenticator() {', '      @Override',
              '      protected PasswordAuthentication getPasswordAuthentication() {',
              '        return new PasswordAuthentication(usuario, externalProperties.mailSmtpPassword);', '      }', '    });', '  }', '',
              '  private static void destinatarios(MimeMessage mensaje, Message.RecipientType tipo, String lista) throws MessagingException {',
              '    if (lista != null && !lista.trim().isEmpty()) {',
              '      mensaje.setRecipients(tipo, InternetAddress.parse(lista.replace(\';\', \',\')));', '    }', '  }', '',
              '  private static String reemplazar(String texto, String marca, Object valor) {',
              '    return texto == null ? null : texto.replace(marca, valor == null ? "" : String.valueOf(valor));', '  }']
    return '\n'.join(lines + ['}', ''])


def adapter_source(plan, batch, port):
    adapter = adapter_for(batch, port['id'])
    if adapter is None:
        return None
    render = {'db': db_adapter_source, 'rest': rest_adapter_source, 'mail': mail_adapter_source}[port['kind']]
    return render(plan, batch, port, adapter)


def _sample(ftype):
    return {'String': '"x"', 'Integer': 'Integer.valueOf(1)', 'Long': 'Long.valueOf(1L)', 'Boolean': 'Boolean.TRUE'}.get(ftype, f'new {ftype}()')


def _args(pm):
    return ', '.join(_sample(p['type']) for p in pm['params'])


def _json_value(ftype):
    return {'String': '"valor"', 'Integer': '3', 'Long': '3', 'Boolean': 'true'}[ftype]


def adapter_test_source(plan, batch, port):
    adapter = adapter_for(batch, port['id'])
    if adapter is None or port['kind'] == 'mail':
        return None
    package = plan['templateParameters']['BASE_PACKAGE']
    named = _by_name(adapter)
    dtos = {d['name'] for d in batch['dtos']}
    fields = _dto_fields(batch)
    name = f'{port["id"]}ImplTest'
    db = port['kind'] == 'db'
    lines = [f'package {package}.port;', '']
    if db:
        lines += ['import static org.junit.Assert.assertEquals;', 'import static org.junit.Assert.assertNotNull;',
                  'import static org.junit.Assert.assertNull;', 'import static org.mockito.ArgumentMatchers.anyString;',
                  'import static org.mockito.Mockito.verify;', 'import static org.mockito.Mockito.when;', '',
                  'import java.sql.Connection;', 'import java.sql.PreparedStatement;', 'import java.sql.ResultSet;',
                  'import java.sql.SQLException;', '']
    else:
        lines += ['import static org.junit.Assert.assertEquals;', 'import static org.junit.Assert.assertNotNull;',
                  'import static org.junit.Assert.assertNull;', 'import static org.mockito.ArgumentMatchers.any;',
                  'import static org.mockito.ArgumentMatchers.anyString;', 'import static org.mockito.ArgumentMatchers.contains;',
                  'import static org.mockito.ArgumentMatchers.eq;', 'import static org.mockito.Mockito.verify;',
                  'import static org.mockito.Mockito.when;', '']
    lines += ['import org.junit.Before;', 'import org.junit.Test;', 'import org.junit.runner.RunWith;', 'import org.mockito.InjectMocks;',
              'import org.mockito.Mock;']
    if not db:
        lines.append('import org.mockito.Spy;')
    lines += ['import org.mockito.junit.MockitoJUnitRunner;']
    lines += [f'import {package}.dto.{n};' for n in pf._port_types(port, dtos)]
    lines.append(f'import {package}.util.' + ('ConexionBd;' if db else 'PropertiesExterno;'))
    if not db:
        lines.append(f'import {package}.util.RestClienteHttp;')
    lines += ['', '@RunWith(MockitoJUnitRunner.Silent.class)', f'public class {name} {{', '']
    if db:
        lines += ['  @Mock', '  private ConexionBd conexionBd;', '', '  @Mock', '  private Connection conexion;', '',
                  '  @Mock', '  private PreparedStatement sentencia;', '', '  @Mock', '  private ResultSet filas;', '',
                  '  @InjectMocks', f'  private {port["id"]}Impl adaptador;', '', '  @Before',
                  '  public void setUp() throws Exception {', '    when(conexionBd.abrir()).thenReturn(conexion);',
                  '    when(conexion.prepareStatement(anyString())).thenReturn(sentencia);',
                  '    when(sentencia.executeQuery()).thenReturn(filas);', '  }']
    else:
        lines += ['  @Mock', '  private RestClienteHttp restCliente;', '', '  @Spy', '  private PropertiesExterno externalProperties = new PropertiesExterno();', '',
                  '  @InjectMocks', f'  private {port["id"]}Impl adaptador;', '', '  @Before', '  public void setUp() {',
                  f'    externalProperties.rest{port["id"]}Url = "http://localhost";', '  }']
    for pm in port['methods']:
        am, mn, ret = named[pm['name']], pm['name'], pm['returns']
        call = f'adaptador.{mn}({_args(pm)})'
        if db:
            res = am['result']
            if res == 'none':
                lines += ['', '  @Test', f'  public void {mn}_ejecutaLaSentencia() throws Exception {{', f'    {call};',
                          '    verify(sentencia).executeUpdate();', '  }']
            elif res == 'scalar':
                get = ('filas.getString(1)' if ret == 'String' else 'filas.getObject(1)')
                value = '"valor"' if ret == 'String' else {'Integer': 'Integer.valueOf(3)', 'Long': 'Long.valueOf(3L)', 'Boolean': 'Boolean.TRUE'}[ret]
                lines += ['', '  @Test', f'  public void {mn}_devuelveElValorEscalar() throws Exception {{',
                          '    when(filas.next()).thenReturn(true);', f'    when({get}).thenReturn({value});',
                          f'    assertEquals({value}, {call});', '  }',
                          '', '  @Test', f'  public void {mn}_sinFilasDevuelveNull() throws Exception {{',
                          '    when(filas.next()).thenReturn(false);', f'    assertNull({call});', '  }']
            else:
                dto = _elem(ret)
                stubs = []
                for c in am['columns']:
                    ft = fields[dto][c['field']]
                    if ft == 'String':
                        stubs.append(f'    when(filas.getString({pf.literal(c["column"])})).thenReturn("valor");')
                    else:
                        v = {'Integer': 'Integer.valueOf(3)', 'Long': 'Long.valueOf(3L)', 'Boolean': 'Boolean.TRUE'}[ft]
                        stubs.append(f'    when(filas.getObject({pf.literal(c["column"])})).thenReturn({v});')
                first = am['columns'][0] if am['columns'] else None
                check = []
                if first:
                    ft = fields[dto][first['field']]
                    exp = '"valor"' if ft == 'String' else {'Integer': 'Integer.valueOf(3)', 'Long': 'Long.valueOf(3L)', 'Boolean': 'Boolean.TRUE'}[ft]
                    getter = f'get{pf.upper(first["field"])}()'
                if res == 'single':
                    lines += ['', '  @Test', f'  public void {mn}_mapeaLaFila() throws Exception {{', '    when(filas.next()).thenReturn(true);'] + stubs
                    lines += [f'    {dto} resultado = {call};', '    assertNotNull(resultado);']
                    if first:
                        lines.append(f'    assertEquals({exp}, resultado.{getter});')
                    lines += ['  }', '', '  @Test', f'  public void {mn}_sinFilasDevuelveNull() throws Exception {{',
                              '    when(filas.next()).thenReturn(false);', f'    assertNull({call});', '  }']
                else:
                    lines += ['', '  @Test', f'  public void {mn}_mapeaTodasLasFilas() throws Exception {{',
                              '    when(filas.next()).thenReturn(true, false);'] + stubs
                    lines += [f'    java.util.List<{dto}> resultado = {call};', '    assertEquals(1, resultado.size());']
                    if first:
                        lines.append(f'    assertEquals({exp}, resultado.get(0).{getter});')
                    lines.append('  }')
            lines += ['', '  @Test(expected = IllegalStateException.class)',
                      f'  public void {mn}_traduceLosErroresSql() throws Exception {{',
                      '    when(conexionBd.abrir()).thenThrow(new SQLException("fallo"));', f'    {call};', '  }']
        else:
            verb = pf.literal(am['httpMethod'])
            body = 'anyString()' if am['body'] else 'any()'
            if ret == 'Boolean':
                ok = am.get('okStatus', [])
                est = f'eq({verb}), contains({pf.literal(am["path"])}), {body}'
                lines += ['', '  @Test', f'  public void {mn}_exitoConEstado2xx() throws Exception {{',
                          f'    when(restCliente.ejecutarEstado({est})).thenReturn(200);', f'    assertEquals(Boolean.TRUE, {call});', '  }',
                          '', '  @Test', f'  public void {mn}_falloConEstado500() throws Exception {{',
                          f'    when(restCliente.ejecutarEstado({est})).thenReturn(500);', f'    assertEquals(Boolean.FALSE, {call});', '  }']
                for s in ok:
                    lines += ['', '  @Test', f'  public void {mn}_aceptaElEstado{s}() throws Exception {{',
                              f'    when(restCliente.ejecutarEstado({est})).thenReturn({s});', f'    assertEquals(Boolean.TRUE, {call});', '  }']
                lines += ['', '  @Test', f'  public void {mn}_unErrorDeComunicacionEsFallo() throws Exception {{',
                          f'    when(restCliente.ejecutarEstado({est})).thenThrow(new Exception("fallo"));',
                          f'    assertEquals(Boolean.FALSE, {call});', '  }']
                continue
            if ret == 'void':
                lines += ['', '  @Test', f'  public void {mn}_invocaElServicio() throws Exception {{', f'    {call};',
                          f'    verify(restCliente).ejecutar(eq({verb}), contains({pf.literal(am["path"])}), {body});', '  }']
            else:
                dto = _elem(ret)
                payload = '"[{}]"' if ret.startswith('List<') else '"{}"'
                lines += ['', '  @Test', f'  public void {mn}_interpretaLaRespuesta() throws Exception {{',
                          f'    when(restCliente.ejecutar(eq({verb}), contains({pf.literal(am["path"])}), {body})).thenReturn({payload});',
                          f'    assertNotNull({call});']
                if ret.startswith('List<'):
                    lines.append(f'    assertEquals(1, {call}.size());')
                lines += ['  }', '', '  @Test', f'  public void {mn}_respuestaVaciaDevuelveNull() throws Exception {{',
                          f'    when(restCliente.ejecutar(eq({verb}), contains({pf.literal(am["path"])}), {body})).thenReturn(null);',
                          f'    assertNull({call});', '  }']
            lines += ['', '  @Test(expected = IllegalStateException.class)',
                      f'  public void {mn}_traduceLosErrores() throws Exception {{',
                      f'    when(restCliente.ejecutar(eq({verb}), contains({pf.literal(am["path"])}), {body})).thenThrow(new Exception("fallo"));',
                      f'    {call};', '  }']
    return '\n'.join(lines + ['}', ''])
