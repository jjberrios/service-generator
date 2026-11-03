"""FULL batch materialization. Pure rendering, then gate/hash/inventory/file guards."""
from pathlib import Path
import json
import re
import yaml

from batch_shell_contract import PROFILE, GENERIC_KEYS, features_of, require, validate, adapter_properties, adapter_kinds
import batch_shell_plan as planner

VERSION = 'batch-shell-materializer-2'

WS_KEYS = ('ws.ebsConsultaClavesWS.url', 'ws.ebsConsultaClavesWS.max.request.timeout',
           'ws.ebsConsultaClavesWS.max.connection.timeout', 'ws.ebsConsultaClavesWS.codigo.aplicacion')
LIB_PREREQUISITE = ('- Repositorio local `Lib/` con el cliente `eai:ebsConsultaClavesService-Client:1.0.0` '
                    '(servicio SOAP de descifrado de credenciales)\n'
                    '- Endpoint SOAP de descifrado accesible (`ws.ebsConsultaClavesWS.url`, timeouts y c\u00f3digo de aplicaci\u00f3n)')


def decrypt_used(batch):
    return any(c['credentialMode'] == 'decrypted-soap' for c in batch['connections'])


def required_keys(batch):
    return (sorted(GENERIC_KEYS | (set(WS_KEYS) if decrypt_used(batch) else set()))
            + [p['key'] for p in batch['properties']] + [p['key'] for p in adapter_properties(batch)])


def secret_keys(batch):
    return {p['key'] for p in list(batch['properties']) + adapter_properties(batch) if p['secret']}


def fill_readme(text, batch, plan):
    if ports_flow(batch):
        omitted = '\n'.join(f"- {i['id']}: {i['description']}" for i in batch['omittedBehavior'])
        kinds = adapter_kinds(batch)
        if kinds:
            description = ('Proceso batch cuyo flujo (segun la especificacion funcional, Sparx) esta orquestado en el servicio contra puertos '
                           '(`port`). Los adaptadores (' + ', '.join(sorted(kinds)) + ') se implementaron con SUPUESTOS deducidos de los nombres '
                           'de la especificacion (SQL, columnas, rutas y cuerpos REST, correo); deben validarse contra los sistemas reales. '
                           'La programacion periodica es externa al batch (planificador del entorno). Comportamiento no definido por la especificacion:\n\n' + omitted)
            pre = []
            if 'db' in kinds:
                pre.append('- Driver JDBC de la base de datos disponible en el classpath de ejecucion (no se incluye en el proyecto)')
            if 'rest' in kinds:
                pre.append('- Servicios REST accesibles (URL base por servicio en las propiedades `rest.*.url`)')
            if 'mail' in kinds:
                pre.append('- Servidor SMTP accesible (`mail.smtp.*`)')
            pre.append('- Planificador externo que invoque el jar segun la frecuencia requerida')
            pre = '\n' + '\n'.join(pre)
        else:
            description = ('Proceso batch cuyo flujo (segun la especificacion funcional, Sparx) esta orquestado en el servicio contra puertos '
                           '(`port`): cada puerto tiene una interfaz y un adaptador que lanza `OperacionNoImplementadaException` porque la '
                           'integracion concreta (persistencia, REST, correo) y la programacion periodica NO estan implementadas. '
                           'Comportamiento pendiente:\n\n' + omitted)
            pre = ''
        text = text.replace('{{DESCRIPTION}}', description).replace('\n{{PREREQUISITES}}', pre)
        secrets = secret_keys(batch)
        text = text.replace('{{PROPERTIES}}', '\n'.join(f'- `{k}`' + (' (secreta)' if k in secrets else '') for k in required_keys(batch)))
        require('{{' not in text, 'unresolved README marker')
        return text
    if structure_only(batch):
        omitted = '\n'.join(f"- {i['id']}: {i['description']}" for i in batch['omittedBehavior'])
        description = ('Proceso batch del que solo se ha generado la estructura (clase principal, servicio, propiedades externas y '
                       'prueba unitaria). El comportamiento funcional NO esta implementado y la ejecucion registra el resultado de '
                       'fallo configurado en lugar de simular exito. Comportamiento omitido segun la especificacion (Sparx):\n\n' + omitted)
        text = text.replace('{{DESCRIPTION}}', description).replace('\n{{PREREQUISITES}}', '')
        text = text.replace('{{PROPERTIES}}', '\n'.join(f'- `{k}`' for k in required_keys(batch)))
        require('{{' not in text, 'unresolved README marker')
        return text
    steps = [f"{s['kind']} ({s['id']})" for s in batch['steps']]
    description = ('Proceso batch que ejecuta, en orden, los pasos: ' + ', '.join(steps) + '. '
                   'El flujo se obtiene de la especificaci\u00f3n funcional (Sparx) y cada paso cita su evidencia en el registro de supuestos del workspace.')
    secrets = {p['key'] for p in batch['properties'] if p['secret']}
    lines = [f"- `{k}`" + (' (secreta: valor cifrado)' if k in secrets else '') for k in required_keys(batch)]
    text = text.replace('{{DESCRIPTION}}', description)
    text = text.replace('\n{{PREREQUISITES}}', ('\n' + LIB_PREREQUISITE) if decrypt_used(batch) else '')
    text = text.replace('{{PROPERTIES}}', '\n'.join(lines))
    require('{{' not in text, 'unresolved README marker')
    return text


def check_quality(result, plan, batch):
    import re
    pom = [t for p, (_, t) in result.items() if p == 'pom.xml']
    for text in pom:
        require('sonar.exclusions' not in text and 'sonar.coverage.exclusions' not in text, 'Sonar exclusions are forbidden (SH-D-020)')
    main_prefix = 'src/main/java/'
    classes = {p: Path(p).stem for p in result if p.startswith(main_prefix) and p.endswith('.java')}
    texts = {p: t for p, (_, t) in result.items() if p.startswith('src/main/')}
    roots = {plan['templateParameters']['MAIN_CLASS'], plan['templateParameters']['SERVICE_INTERFACE'] + 'Impl'}
    for path, name in classes.items():
        if name in roots or re.search(r'@(Component|Service|Repository)\b', texts[path]):
            continue
        used = any(re.search(r'\b' + re.escape(name) + r'\b', t) for other, t in texts.items() if other != path)
        require(used, f'unused class {name}: generated services must not carry unused code (SH-D-019)')


def literal(value):
    return json.dumps(value, ensure_ascii=True)


def structure_only(batch):
    return batch.get('scope') == 'structure-only'


def ports_flow(batch):
    return batch.get('scope') == 'ports-flow'


def structure_service_source(plan, batch):
    values = plan['templateParameters']
    package, interface = values['BASE_PACKAGE'], values['SERVICE_INTERFACE']
    impl = interface + 'Impl'
    group = batch['outcomes']['generalFailure']
    ids = ', '.join(item['id'] for item in batch['omittedBehavior'])
    code, message = f'externalProperties.{group}Codigo', f'externalProperties.{group}Mensaje'
    return '\n'.join([
        f'package {package}.service;', '', 'import java.text.MessageFormat;', 'import org.apache.log4j.Logger;',
        'import org.springframework.beans.factory.annotation.Autowired;', 'import org.springframework.stereotype.Service;',
        f'import {package}.util.Constantes;', f'import {package}.util.PropertiesExterno;', '',
        '@Service', f'public class {impl} implements {interface} {{',
        f'  private static final Logger logger = Logger.getLogger({impl}.class);', '  @Autowired',
        '  private PropertiesExterno externalProperties;', '', '  @Override',
        '  public void run(String messageTransaction, String idTransaccion) {',
        '    String nomMetodoActual = Thread.currentThread().getStackTrace()[1].getMethodName();',
        '    String msjTrx = messageTransaction + "[" + nomMetodoActual + "] ";',
        '    long tiempoInicio = System.currentTimeMillis();',
        '    logger.info(MessageFormat.format(Constantes.INICIO_METODO, msjTrx, nomMetodoActual));',
        '    try {',
        '      // PENDIENTE: el comportamiento funcional no esta implementado (alcance solo estructura).',
        f'      // Comportamiento omitido segun Sparx: {ids}.',
        f'      logger.error(msjTrx + {code} + " " + {message} + " " + {literal("Comportamiento no implementado: " + ids)});',
        '    } finally {',
        '      logger.info(MessageFormat.format(Constantes.TIPO_TOTAL_PROCESO, msjTrx, System.currentTimeMillis() - tiempoInicio));',
        '      logger.info(MessageFormat.format(Constantes.FIN_METODO, msjTrx, nomMetodoActual));',
        '    }', '  }', '}', ''])


def structure_test_source(plan, batch):
    v = plan['templateParameters']
    package, impl = v['BASE_PACKAGE'], v['SERVICE_INTERFACE'] + 'Impl'
    group = batch['outcomes']['generalFailure']
    lines = [f'package {package}.service;', '', 'import org.junit.After;', 'import org.junit.Assert;', 'import org.junit.Before;',
             'import org.junit.Test;', 'import org.junit.runner.RunWith;', 'import org.mockito.ArgumentCaptor;',
             'import org.mockito.InjectMocks;', 'import org.mockito.Mock;', 'import org.mockito.Spy;',
             'import org.mockito.junit.MockitoJUnitRunner;', 'import org.apache.log4j.Appender;', 'import org.apache.log4j.Logger;',
             'import org.apache.log4j.spi.LoggingEvent;',
             'import static org.mockito.Mockito.atLeastOnce;', 'import static org.mockito.Mockito.verify;',
             f'import {package}.util.PropertiesExterno;', '',
             '@RunWith(MockitoJUnitRunner.Silent.class)', f'public class {impl}Test {{',
             '  @Spy', '  private PropertiesExterno externalProperties = new PropertiesExterno();',
             '  @Spy', '  @InjectMocks', f'  private {impl} service = new {impl}();',
             '  @Mock', '  private Appender appender;', '', '  @Before', '  public void setUp() {',
             f'    externalProperties.{group}Codigo = "{group}_code";', f'    externalProperties.{group}Mensaje = "{group}_message";',
             f'    Logger.getLogger({impl}.class).addAppender(appender);', '  }', '',
             '  @After', '  public void tearDown() {', f'    Logger.getLogger({impl}.class).removeAppender(appender);', '  }', '',
             '  @Test', '  public void run_cuandoComportamientoNoImplementado_noDebeSimularExito() {',
             '    service.run("[idTx=test]", "test");',
             '    ArgumentCaptor<LoggingEvent> logs = ArgumentCaptor.forClass(LoggingEvent.class);',
             '    verify(appender, atLeastOnce()).doAppend(logs.capture());',
             '    boolean found = false;', '    for (LoggingEvent event : logs.getAllValues()) {',
             f'      found = found || event.getRenderedMessage().contains("{group}_code");', '    }',
             f'    Assert.assertTrue("{group}_code", found);', '  }', '}', '']
    return '\n'.join(lines)


def service_source(plan):
    values, batch = plan['templateParameters'], validate(plan['batch'], features_of(plan['technicalProfile']))
    if ports_flow(batch):
        import batch_ports_flow as pf
        return pf.service_source(plan, batch)
    if structure_only(batch):
        return structure_service_source(plan, batch)
    package, interface = values['BASE_PACKAGE'], values['SERVICE_INTERFACE']
    impl = interface + 'Impl'
    props = {p['key']: 'externalProperties.' + p['field'] for p in batch['properties']}
    outcome = batch['outcomes']
    def response(kind, part):
        return 'externalProperties.' + outcome[kind] + part
    def fail():
        return 'throw new SFTPException(' + response('sftpFailure', 'Codigo') + ', ' + response('sftpFailure', 'Mensaje') + ', "");'
    def conn(name):
        return 'batchConn_' + name
    body = []
    def emit(level, line):
        body.append('  ' * level + line)
    def walk(steps, level=3, item=None):
        for step in steps:
            kind, sid = step['kind'], step['id']
            emit(level, '// Sparx step: ' + sid)
            if kind == 'connect':
                emit(level, f'{conn(step["connection"])} = crearConexion{step["connection"]}(msjTrx);')
            elif kind == 'disconnect':
                emit(level, f'{conn(step["connection"])}.disconnect();')
                emit(level, f'{conn(step["connection"])} = null;')
            elif kind.startswith('list-'):
                method = 'listarArchivos' if kind == 'list-mtime' else 'listarArchivosPorNombreFecha'
                args = ', '.join(props[step[k]] for k in ('remoteDirectory', 'date', 'dateFormat'))
                var = 'batchList_' + sid
                emit(level, f'java.util.List<String> {var} = {conn(step["connection"])}.{method}({args});')
                condition = f'{var} == null' + (f' || {var}.isEmpty()' if step['emptyPolicy'] == 'abort' else '')
                emit(level, f'if ({condition}) {{')
                emit(level + 1, fail())
                emit(level, '}')
            elif kind == 'for-each':
                element = 'batchItem_' + sid
                emit(level, f'for (String {element} : batchList_{step["list"]}) {{')
                walk(step['steps'], level + 1, element)
                emit(level, '}')
            else:
                filename = item if step['filename'] == '$item' else props[step['filename']]
                if kind == 'download':
                    args = ', '.join((props[step['remoteDirectory']], filename, props[step['localDirectory']]))
                    call = f'{conn(step["connection"])}.obtenerArchivo({args})'
                    condition = f'!Constantes.SUCCESS.equals({call})'
                else:
                    args = ', '.join((props[step['localDirectory']] + ' + ' + filename, props[step['remoteDirectory']], filename))
                    condition = f'!{conn(step["connection"])}.enviarArchivo({args})'
                emit(level, f'if ({condition}) {{')
                emit(level + 1, fail())
                emit(level, '}')
    walk(batch['steps'])
    lines = [f'package {package}.service;', '', 'import java.text.MessageFormat;',
             'import org.apache.log4j.Logger;', 'import org.springframework.beans.factory.annotation.Autowired;',
             'import org.springframework.stereotype.Service;', f'import {package}.util.Constantes;',
             f'import {package}.util.PropertiesExterno;', f'import {package}.util.SFTPConnectionManager;',
             f'import {package}.exception.SFTPException;', '', '@Service', f'public class {impl} implements {interface} {{',
             f'  private static final Logger logger = Logger.getLogger({impl}.class);', '  @Autowired',
             '  private PropertiesExterno externalProperties;', '', '  @Override',
             '  public void run(String messageTransaction, String idTransaccion) {',
             '    String nomMetodoActual = Thread.currentThread().getStackTrace()[1].getMethodName();',
             '    String msjTrx = messageTransaction + "[" + nomMetodoActual + "] ";',
             '    long tiempoInicio = System.currentTimeMillis();',
             '    logger.info(MessageFormat.format(Constantes.INICIO_METODO, msjTrx, nomMetodoActual));']
    for c in batch['connections']:
        lines.append(f'    SFTPConnectionManager {conn(c["id"])} = null;')
    lines += ['    try {', *body, f'      logger.info(msjTrx + {response("success", "Codigo")} + " " + {response("success", "Mensaje")});',
              '    } catch (SFTPException e) {',
              f'      logger.error(msjTrx + {response("sftpFailure", "Codigo")} + " " + {response("sftpFailure", "Mensaje")}, e);',
              '    } catch (Exception e) {',
              f'      logger.error(msjTrx + {response("generalFailure", "Codigo")} + " " + {response("generalFailure", "Mensaje")}, e);',
              '    } finally {']
    for c in reversed(batch['connections']):
        lines += [f'      if ({conn(c["id"])} != null) {{', f'        {conn(c["id"])}.disconnect();', '      }']
    lines += ['      logger.info(MessageFormat.format(Constantes.TIPO_TOTAL_PROCESO, msjTrx, System.currentTimeMillis() - tiempoInicio));',
              '      logger.info(MessageFormat.format(Constantes.FIN_METODO, msjTrx, nomMetodoActual));', '    }', '  }', '']
    decrypting = False
    for c in batch['connections']:
        port = 'Integer.parseInt(' + props[c['port']] + ')'
        if c['credentialMode'] == 'decrypted-soap':
            decrypting = True
            lines += [f'  protected SFTPConnectionManager crearConexion{c["id"]}(String msjTrx) throws SFTPException, WSException {{',
                      f'    DesencriptarResponse credenciales = desencriptarCredenciales(msjTrx, {props[c["username"]]}, {props[c["password"]]});',
                      '    try {',
                      f'      return new SFTPConnectionManager(msjTrx, credenciales.getUsuarioAplicacion(), {props[c["host"]]}, {port}, credenciales.getClave());',
                      '    } catch (Exception e) {', '      ' + fail(), '    }', '  }', '']
        else:
            args = ', '.join((props[c['username']], props[c['host']], port, props[c['password']]))
            lines += [f'  protected SFTPConnectionManager crearConexion{c["id"]}(String msjTrx) throws SFTPException {{',
                      '    try {', f'      return new SFTPConnectionManager(msjTrx, {args});', '    } catch (Exception e) {',
                      '      ' + fail(), '    }', '  }', '']
    if decrypting:
        lines += ['  protected DesencriptarResponse desencriptarCredenciales(String msjTrx, String usuarioCifrado, String claveCifrada) throws WSException {',
                  '    DesencriptarRequest request = new DesencriptarRequest();',
                  '    request.setIdTransaccion(msjTrx);',
                  '    request.setCodigoAplicacion(externalProperties.wsEbsConsultaClavesWSCodigoAplicacion);',
                  '    request.setUsuarioAplicacionEncriptado(usuarioCifrado);',
                  '    request.setClaveEncriptado(claveCifrada);',
                  '    DesencriptarResponse response = ebsConsultaClavesWSService.desencriptar(msjTrx, request);',
                  '    if (response == null || !Constantes.WS_EXITO.equals(response.getCodigoResultado())) {',
                  '      throw new WSException(response == null ? null : response.getCodigoResultado(), response == null ? null : response.getMensajeResultado());',
                  '    }',
                  '    return response;', '  }', '']
    imports = ['import pe.com.claro.eai.ebs.operaciones.consultaclaves.DesencriptarRequest;',
               'import pe.com.claro.eai.ebs.operaciones.consultaclaves.DesencriptarResponse;',
               f'import {package}.proxy.EbsConsultaClavesWSService;', f'import {package}.exception.WSException;'] if decrypting else []
    if decrypting:
        at = lines.index(f'import {package}.exception.SFTPException;') + 1
        lines[at:at] = imports
        at = lines.index('  private PropertiesExterno externalProperties;') + 1
        lines[at:at] = ['  @Autowired', '  private EbsConsultaClavesWSService ebsConsultaClavesWSService;']
        at = lines.index('    } catch (Exception e) {')
        lines[at:at] = ['    } catch (WSException e) {',
                        f'      logger.error(msjTrx + "[" + e.getCodigo() + "] " + e.getMensaje(), e);',
                        f'      logger.error(msjTrx + {response("generalFailure", "Codigo")} + " " + {response("generalFailure", "Mensaje")});']
    return '\n'.join(lines + ['}', ''])


def test_source(plan):
    """Reference-shaped JUnit4/Mockito tests; no real network or Spring context."""
    v, batch = plan['templateParameters'], plan['batch']
    if ports_flow(batch):
        import batch_ports_flow as pf
        return pf.test_source(plan, batch)
    if structure_only(batch):
        return structure_test_source(plan, batch)
    package, impl = v['BASE_PACKAGE'], v['SERVICE_INTERFACE'] + 'Impl'
    lines = [f'package {package}.service;', '', 'import org.junit.Before;', 'import org.junit.Test;',
             'import org.junit.runner.RunWith;', 'import org.mockito.Mock;', 'import org.mockito.Spy;',
             'import org.mockito.InjectMocks;', 'import org.mockito.junit.MockitoJUnitRunner;',
             *['import static org.mockito.Mockito.' + name + ';' for name in ('doReturn', 'doThrow', 'when', 'verify', 'anyString', 'atLeastOnce', 'never')],
             'import org.junit.After;', 'import org.junit.Assert;', 'import org.apache.log4j.Appender;',
             'import org.apache.log4j.Logger;', 'import org.apache.log4j.spi.LoggingEvent;', 'import org.mockito.ArgumentCaptor;',
             f'import {package}.util.PropertiesExterno;',
             f'import {package}.util.SFTPConnectionManager;', f'import {package}.util.Constantes;',
             '', '@RunWith(MockitoJUnitRunner.Silent.class)', f'public class {impl}Test {{',
             '  @Spy', '  private PropertiesExterno externalProperties = new PropertiesExterno();',
             '  @Spy', '  @InjectMocks', f'  private {impl} service = new {impl}();',
             '  @Mock', '  private Appender appender;']
    for c in batch['connections']:
        lines += ['  @Mock', f'  private SFTPConnectionManager conn_{c["id"]};']
    lines += ['  @Before', '  public void setUp() throws Exception {']
    for group in ('idf0', 'idf1', 'idt1', 'idt2', 'idt3'):
        lines += [f'    externalProperties.{group}Codigo = "{group}_code";', f'    externalProperties.{group}Mensaje = "{group}_message";']
    lines += [f'    Logger.getLogger({impl}.class).addAppender(appender);']
    for p in batch['properties']:
        lines += [f'    externalProperties.{p["field"]} = "test";']
    for c in batch['connections']:
        name = 'conn_' + c['id']
        lines += [f'    doReturn({name}).when(service).crearConexion{c["id"]}(anyString());',
                  f'    when({name}.listarArchivos(anyString(), anyString(), anyString())).thenReturn(java.util.Arrays.asList("file"));',
                  f'    when({name}.listarArchivosPorNombreFecha(anyString(), anyString(), anyString())).thenReturn(java.util.Arrays.asList("file"));',
                  f'    when({name}.obtenerArchivo(anyString(), anyString(), anyString())).thenReturn(Constantes.SUCCESS);',
                  f'    when({name}.enviarArchivo(anyString(), anyString(), anyString())).thenReturn(true);']
    lines += ['  }', '', '  @After', '  public void tearDown() {',
              f'    Logger.getLogger({impl}.class).removeAppender(appender);', '  }', '',
              '  private void assertOutcome(String code) {',
              '    ArgumentCaptor<LoggingEvent> logs = ArgumentCaptor.forClass(LoggingEvent.class);',
              '    verify(appender, atLeastOnce()).doAppend(logs.capture());',
              '    boolean found = false;',
              '    for (LoggingEvent event : logs.getAllValues()) {',
              '      found = found || event.getRenderedMessage().contains(code);', '    }',
              '    Assert.assertTrue(code, found);', '  }', '',
              '  @Test', '  public void run_cuandoFlujoExitoso_debeCerrarConexiones() throws Exception {',
              '    service.run("[idTx=test]", "test");']
    # Verify every planned utility call, not merely cleanup after a swallowed exception.
    def checks(steps):
        out = []
        methods = {'list-mtime': 'listarArchivos', 'list-name': 'listarArchivosPorNombreFecha',
                   'download': 'obtenerArchivo', 'upload': 'enviarArchivo'}
        for s in steps:
            if s['kind'] == 'for-each':
                out += checks(s['steps'])
            elif s['kind'] in methods:
                out += [f'    verify(conn_{s["connection"]}, atLeastOnce()).{methods[s["kind"]]}(anyString(), anyString(), anyString());']
        return out
    lines += checks(batch['steps'])
    lines += [f'    assertOutcome(externalProperties.{batch["outcomes"]["success"]}Codigo);']
    for c in batch['connections']:
        lines += [f'    verify(conn_{c["id"]}, atLeastOnce()).disconnect();']
    first = next(s['connection'] for s in batch['steps'] if s['kind'] == 'connect')
    lines += ['  }', '', '  @Test', '  public void run_cuandoFallaConexion_noDebePropagar() throws Exception {',
              f'    doThrow(new {package}.exception.SFTPException("test", "test", "test")).when(service).crearConexion{first}(anyString());',
              '    service.run("[idTx=test]", "test");', f'    verify(conn_{first}, never()).disconnect();',
              f'    assertOutcome(externalProperties.{batch["outcomes"]["sftpFailure"]}Codigo);', '  }', '']
    def failure_tests(steps):
        for s in steps:
            kind = s['kind']
            if kind == 'for-each':
                failure_tests(s['steps'])
                continue
            method = {'list-mtime': 'listarArchivos', 'list-name': 'listarArchivosPorNombreFecha',
                      'download': 'obtenerArchivo', 'upload': 'enviarArchivo'}.get(kind)
            if not method:
                continue
            call = f'conn_{s["connection"]}.{method}(anyString(), anyString(), anyString())'
            failure = 'null' if kind.startswith('list-') else ('"ERROR: test"' if kind == 'download' else 'false')
            lines.extend(['  @Test', f'  public void run_falla_{s["id"]}_cierraConexion() throws Exception {{',
                          f'    when({call}).thenReturn({failure});', '    service.run("[idTx=test]", "test");',
                          f'    verify(conn_{s["connection"]}, atLeastOnce()).disconnect();',
                          f'    assertOutcome(externalProperties.{batch["outcomes"]["sftpFailure"]}Codigo);', '  }', ''])
    failure_tests(batch['steps'])
    lines += ['}', '']
    return '\n'.join(lines)


def render_project(plan, repo):
    values, batch = plan['templateParameters'], validate(plan['batch'], features_of(plan['technicalProfile']))
    root = repo / plan['inputs']['archetype']['path'] / 'template'
    result = {}
    for entry in plan['files']['generate']:
        path, ct = planner.safe_path(entry['path']), entry['componentType']
        require(entry['action'] in ('create', 'update'), 'unsupported file action')
        if ct == 'batch-archetype-template':
            rel = planner.safe_path(entry['template'])
            source = root / rel
            require(source.resolve().is_relative_to(root.resolve()), 'template symlink escapes archetype')
            text = source.read_text(encoding='utf-8').replace('\r\n', '\n')
            usage = plan.get('usage') or {}
            for line in usage.get('prunedLines', []):
                if line['template'] == rel:
                    kept = [l for l in text.split('\n') if line['text'] not in l]
                    require(len(kept) < len(text.split('\n')), 'pruned line not found in template')
                    text = '\n'.join(kept)
            text = planner.substitute(text, values)
            if rel.endswith('/PropertiesExterno.java'):
                for field in usage.get('prunedPropertiesFields', []):
                    text, n = re.subn(r'[ \t]*@Value\("[^"]*"\)\n[ \t]*public String ' + re.escape(field) + r';\n\n?', '', text)
                    require(n == 1, 'pruned properties field not found in template')
                addition = '\n'.join(f'  @org.springframework.beans.factory.annotation.Value("${{{p["key"]}}}")\n  public String {p["field"]};\n'
                                     for p in list(batch['properties']) + adapter_properties(batch))
                if addition:
                    before, tail = text.rsplit('}', 1)
                    text = before.rstrip('\n') + '\n\n' + addition + '}' + tail
            elif rel == 'README.MD':
                text = fill_readme(text, batch, plan)
            elif rel == 'pom.xml' and plan.get('mavenAdditions'):
                deps = ''.join(
                    f'      <!-- adicion justificada: {a["justification"]} (requerida por {a["requiredBy"]}) -->\n'
                    f'      <dependency>\n         <groupId>{a["groupId"]}</groupId>\n         <artifactId>{a["artifactId"]}</artifactId>\n'
                    f'         <version>{a["version"]}</version>\n      </dependency>\n' for a in plan['mavenAdditions'])
                require(text.count('</dependencies>') == 1, 'pom must have exactly one dependencies block')
                text = text.replace('   </dependencies>', deps + '   </dependencies>')
        elif ct == 'batch-config':
            secrets = set(secret_keys(batch))
            lines = ['# Configuracion externa del batch. Completar los valores del entorno; no versionar secretos.']
            for key in sorted(required_keys(batch)):
                if key in secrets:
                    lines.append('# secreta: definir fuera del control de versiones')
                lines.append(key + '=')
            text = '\n'.join(lines) + '\n'
        elif ct == 'batch-service':
            text = service_source(plan)
        elif ct == 'batch-unit-test':
            text = test_source(plan)
        elif ct in ('batch-dto', 'batch-port', 'batch-port-impl', 'batch-exception') and ports_flow(batch):
            import batch_ports_flow as pf
            stem = Path(path).stem
            if ct == 'batch-exception':
                text = pf.exception_source(plan)
            elif ct == 'batch-dto':
                text = pf.dto_source(plan, next(d for d in batch['dtos'] if d['name'] == stem))
            else:
                port = next(p for p in batch['ports'] if p['id'] == stem.removesuffix('Impl') and (ct == 'batch-port-impl') == stem.endswith('Impl'))
                text = (pf.port_impl_source if ct == 'batch-port-impl' else pf.port_source)(plan, batch, port)
        elif ct in ('batch-support', 'batch-adapter-test') and ports_flow(batch):
            import batch_adapters as ba
            stem = Path(path).stem
            if ct == 'batch-support':
                text = {'ConexionBd': ba.conexion_bd_source, 'RestClienteHttp': ba.rest_cliente_source}[stem](plan)
            else:
                port = next(p for p in batch['ports'] if p['id'] + 'ImplTest' == stem)
                text = ba.adapter_test_source(plan, batch, port)
        else:
            raise ValueError('unsupported batch component ' + str(ct))
        require(path not in result, 'duplicate rendered path')
        result[path] = (ct, text.replace('\r\n', '\n'))
    check_quality(result, plan, batch)
    return result


def materialize(repo, service, dry_run=False):
    import feasibility_preflight
    feasibility_preflight.enforce(repo, service)
    return _materialize_checked(repo, service, dry_run)


def _materialize_checked(repo, service, dry_run=False):
    import full_materializer as fm
    repo = Path(repo).resolve()
    ws = fm.wsm.Workspace(repo, service)
    fm.gate.check_cleared(ws.dir, repo, service)
    plan_raw = (ws.dir / 'implementation-plan.yml').read_bytes()
    plan = yaml.safe_load(plan_raw)
    try:
        require(plan['plan'] == {'version': 3, 'mode': 'full', 'profile': PROFILE}, 'wrong plan version/mode/profile')
        inputs = plan['inputs']
        for key, filename, hashkey in (('serviceSpec', 'service-spec.yml', 'artifactSha256'),
                                       ('planningInput', 'full-planning-input.yml', 'sha256'),
                                       ('generationParameters', 'generation-parameters.yml', 'sha256')):
            require(inputs[key][hashkey] == fm.sha((ws.dir / filename).read_bytes()), f'stale {filename}')
            if key != 'serviceSpec':
                require(inputs[key]['path'] == '.factory/' + filename, 'wrong artifact binding')
        cfg = yaml.safe_load((ws.dir / 'full-planning-input.yml').read_bytes())
        spec = yaml.safe_load((ws.dir / 'service-spec.yml').read_bytes())
        require(cfg['target']['service'] == service, 'wrong workspace service')
        state = yaml.safe_load((ws.dir / 'service-generation-state.yml').read_bytes())
        require(cfg['target']['archetype'] == state['archetype']['path'], 'selected archetype mismatch')
        expected = planner.build(repo, spec, cfg)
        require(inputs['archetype'] == expected['inputs']['archetype'], 'stale archetype')
        for key in set(expected) - {'inputs', 'files'}:
            require(plan[key] == expected[key], f'plan differs from authorized inputs: {key}')
        def inventory(p):
            return [{k: v for k, v in e.items() if k != 'action'} for e in p['files']['generate']]
        require(inventory(plan) == inventory(expected), 'unplanned or missing component')
        params = yaml.safe_load((ws.dir / 'generation-parameters.yml').read_bytes())
        require(params == {'parameters': {'version': 2, 'profile': PROFILE}, 'values': plan['templateParameters']}, 'parameter conflict')
        rendered = render_project(plan, repo)
        output = repo / cfg['target']['output_directory']
        require(output.resolve().is_relative_to((repo / 'output').resolve()), 'output escapes configured directory')
        for path in [*rendered, fm.MANIFEST]:
            require(not fm.fp.is_excluded(path), 'protected configuration cannot be generated')
            require((output / path).resolve().is_relative_to(output.resolve()), 'output symlink escapes service directory')
        previous = fm.fp.generated_hashes(output)
        require(not set(previous) - set(rendered), 'obsolete tracked files require explicit migration; nothing written')
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    payload = {p: text.encode('utf-8') for p, (_, text) in rendered.items()}
    from artifact_integrity import prepare, publish, IntegrityError
    try:
        changed_payload, unchanged = prepare(output, ws.dir, payload, reject_obsolete=True)
    except fm.fp.ProtectedFileError as error:
        raise fm.MaterializationError('protected-files', str(error), getattr(error, 'details', {})) from error
    except IntegrityError as error:
        raise fm.MaterializationError('invalid-plan', str(error)) from error
    rows = [{'path': p, 'sha256': fm.sha(payload[p]), 'action': 'generated', 'componentType': rendered[p][0]} for p in sorted(payload)]
    tree_hash = fm.tree_hash({r['path']: r['sha256'] for r in rows})
    dump = lambda obj: yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')
    manifest = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'complete': True,
                'inputs': {'implementationPlanSha256': fm.sha(plan_raw), 'serviceSpecSha256': inputs['serviceSpec']['artifactSha256'],
                           'archetypeFingerprint': inputs['archetype']['fingerprint']},
                'fileInventory': rows, 'payloadTreeSha256': tree_hash, 'unsupportedComponents': []}
    changed = sorted(changed_payload)
    report = {'schemaVersion': 1, 'materializer': VERSION, 'service': service, 'profile': PROFILE, 'status': 'ports-flow-incomplete' if ports_flow(plan['batch']) else ('structure-only-incomplete' if structure_only(plan['batch']) else 'complete'),
              'written': changed, 'unchanged': sorted(set(payload) - set(changed)), 'dryRun': dry_run,
              'payloadTreeSha256': tree_hash, 'manifestSha256': fm.sha(dump(manifest)), 'unsupported': [],
              'validation': {'maven': 'not-run', 'compilation': 'not-verified', 'tests': 'not-run',
                             'jacoco': 'not-verified', 'checkstyle': 'not-applicable'}}
    if dry_run:
        return report
    # Manifest is guarded too. Excluded local environment files are never enumerated/read.
    publish(output, ws.dir, payload, dump(manifest))
    declared = [p['key'] for p in plan['batch']['properties']]
    adapters_keys = {p['key'] for p in adapter_properties(plan['batch'])}
    properties = {'schemaVersion': 1, 'service': service, 'keys': [
        {'key': k, 'source': 'adapters-assumption' if k in adapters_keys else 'archetype', 'secret': k in secret_keys(plan['batch']),
         'value': 'operator-required'} for k in required_keys(plan['batch']) if k not in declared] +
        [{'key': p['key'], 'secret': p['secret'], 'evidence': p['evidence'], 'value': 'operator-required'} for p in plan['batch']['properties']]}
    trace = {'schemaVersion': 1, 'service': service, 'tests': [
        {'method': 'run_cuandoFlujoExitoso_debeCerrarConexiones', 'evidence': plan['batch']['sourceBindings'], 'status': 'generated-not-executed'},
        {'method': 'run_cuandoFallaConexion_noDebePropagar', 'source': 'archetype-error-lifecycle', 'status': 'generated-not-executed'}],
        'limitations': ['Error branches for individual transfers require additional scenario-specific tests.']}
    test_text = test_source(plan)
    import re
    trace['tests'] = [{'method': method, 'source': 'normalized-Sparx-and-archetype', 'evidence': plan['batch']['sourceBindings'],
                       'status': 'generated-not-executed'} for method in re.findall(r'public void (run_\w+)\(', test_text)]
    trace['limitations'] = ['No network, credential-decryption or real Spring/runtime tests are generated.']
    assumptions = [{'port': a['port'], 'method': m['name'], 'status': 'assumed-validate-against-real-system',
                    'detail': {k: v for k, v in m.items() if k not in ('evidence', 'name')}, 'evidence': m['evidence']}
                   for a in plan['batch'].get('adapters', []) for m in a['methods']]
    register = {'schemaVersion': 1, 'service': service, 'materializer': VERSION, 'assumptions': assumptions,
                'mavenAdditions': plan.get('mavenAdditions', []),
                'rules': {'owner': 'Sparx', 'sourceBindings': plan['batch']['sourceBindings'], 'steps': plan['batch']['steps'],
                          'omittedBehavior': plan['batch'].get('omittedBehavior', [])},
                'technicalBaseline': plan['inputs']['archetype'], 'limitations': plan['limitations']}
    fm.write_atomic(ws.dir / 'assumptions-register.yml', dump(register))
    fm.write_atomic(ws.dir / 'required-properties.yml', dump(properties))
    fm.write_atomic(ws.dir / 'tests-traceability.yml', dump(trace))
    fm.write_atomic(ws.dir / fm.REPORT, dump(report))
    return report
