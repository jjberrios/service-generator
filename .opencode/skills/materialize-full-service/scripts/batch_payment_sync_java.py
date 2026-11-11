"""Pure Java-8 renderers for the closed, plan-owned payment synchronization model.

No source discovery, network access, file writes or business inference occurs here.
Publication stays in batch_shell_materializer behind all shared FULL guards.
"""
import json


def literal(value):
    return json.dumps(value, ensure_ascii=True)


def source(plan, text):
    return text.replace('@@PACKAGE@@', plan['templateParameters']['BASE_PACKAGE']).replace(
        '@@SERVICE@@', plan['templateParameters']['SERVICE_INTERFACE'])


def readme(text, batch, plan):
    from batch_shell_materializer import required_keys, secret_keys
    text = text.replace('se entrega con todas las claves y valores vacíos;',
                        'incluye valores documentados no secretos; el resto queda vacío;')
    text = text.replace('- Accesos de red a los servidores SFTP/FTP indicados en la configuración',
                        '- Acceso a los servicios REST de autenticacion, Cobranzas y Financiamiento')
    text = text.replace('{{DESCRIPTION}}',
        'Sincroniza pagos: autenticacion REST, ventana temporal de consulta de Cobranzas, '
        'cruce por quoteNumber, actualizacion de cuotas y evaluacion del financiamiento terminado. '
        'Implementacion completa del modelo revisado; no incluye persistencia propia, SOAP, SFTP ni scheduler.')
    text = text.replace('{{PREREQUISITES}}',
        '- Repositorio Lib/ con eai:ebsConsultaClavesService-Client:1.0.0: dependencia de compilacion '
        'heredada y conservada, NO utilizada para autenticar.\n'
        '- URL REST real de autenticacion, bases REST, timeouts y propiedades externas.\n'
        '- Configuracion log4j externa indicada por log4j.file.dir y planificador externo si se requiere periodicidad.')
    text = text.replace('{{PROPERTIES}}', '\n'.join(
        '- `' + key + '`' + (' (secreta)' if key in secret_keys(batch) else '') for key in required_keys(batch)))
    text += ('\n\n## Decisiones delegadas y limites de validacion\n\n'
             'Las decisiones siguientes fueron tomadas por delegacion explicita del solicitante, '
             'no son hechos verificados del contrato externo. Se registran en el modelo, '
             'assumptions-register.yml y revision operacional vinculada al hash del contexto.\n\n')
    for decision in batch.get('decisions', []):
        text += '- **' + decision['id'] + '**: ' + decision['selection'] + '\n'
    text += ('\nEl transporte exige HTTP 200; no reintenta PATCH ni sigue redirects. Los NULL JSON '
             'son reales; los parametros de consulta NULL se omiten. El flujo procesa financiamientos '
             'secuencialmente y descarta el financiamiento actual ante claves de cuota duplicadas ambiguas.\n\n'
             'No se ejecutaron Maven, JaCoCo, sistemas externos, base de datos ni despliegue. '
             'Checkstyle no aplica al arquetipo. La compatibilidad real del contrato REST de '
             'autenticacion asumido debe comprobarse en el entorno antes de produccion. '
             'Los comandos de construccion/ejecucion anteriores son instrucciones para el operador, '
             'no evidencia de ejecucion.\n')
    if '{{' in text:
        raise ValueError('unresolved payment README marker')
    return text


def render(path, plan):
    if path.endswith('/PaymentHttpClient.java'):
        return http_client(plan)
    if path.endswith('/PaymentHttpClientTest.java'):
        from batch_payment_sync_tests import http_test
        return http_test(plan)
    raise ValueError('unrecognized payment synchronization file: ' + path)


def http_client(plan):
    return source(plan, '''package @@PACKAGE@@.client;

import java.io.IOException;
import java.net.URI;
import java.util.Map;
import org.apache.http.client.config.RequestConfig;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpRequestBase;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.client.methods.HttpPatch;
import org.apache.http.client.utils.URIBuilder;
import org.apache.http.entity.StringEntity;
import org.apache.http.entity.ContentType;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.apache.http.util.EntityUtils;
import org.springframework.stereotype.Component;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.NullNode;

/** No retries, redirects or relaxed TLS; PATCH failures cannot be replayed safely. */
@Component
public class PaymentHttpClient {
  private final ObjectMapper mapper = new ObjectMapper();

  protected CloseableHttpClient createClient() {
    return HttpClients.custom().disableAutomaticRetries().disableRedirectHandling().build();
  }

  public JsonNode exchange(String method, String url, Map<String, String> query,
      Map<String, String> headers, JsonNode body, int connectMs, int readMs) throws Exception {
    if (connectMs <= 0 || readMs <= 0) {
      throw new IllegalArgumentException("Timeouts REST deben ser positivos");
    }
    URIBuilder builder = new URIBuilder(url);
    URI base = builder.build();
    if (base.getHost() == null || base.getUserInfo() != null || base.getFragment() != null
        || !("http".equalsIgnoreCase(base.getScheme()) || "https".equalsIgnoreCase(base.getScheme()))) {
      throw new IllegalArgumentException("URL REST absoluta requerida, sin credenciales ni fragmentos");
    }
    for (Map.Entry<String, String> value : query.entrySet()) {
      // NULL semantico del contrato: parametro ausente, nunca la cadena "NULL".
      if (value.getValue() != null) {
        builder.addParameter(value.getKey(), value.getValue());
      }
    }
    URI uri = builder.build();
    HttpRequestBase request;
    if ("GET".equals(method)) {
      if (body != null) {
        throw new IllegalArgumentException("GET no admite cuerpo");
      }
      request = new HttpGet(uri);
    } else if ("POST".equals(method)) {
      HttpPost post = new HttpPost(uri);
      post.setEntity(new StringEntity(mapper.writeValueAsString(body), ContentType.APPLICATION_JSON));
      request = post;
    } else if ("PATCH".equals(method)) {
      HttpPatch patch = new HttpPatch(uri);
      patch.setEntity(new StringEntity(mapper.writeValueAsString(body), ContentType.APPLICATION_JSON));
      request = patch;
    } else {
      throw new IllegalArgumentException("Verbo REST no soportado");
    }
    request.setConfig(RequestConfig.custom().setConnectTimeout(connectMs)
        .setConnectionRequestTimeout(connectMs).setSocketTimeout(readMs).build());
    request.setHeader("Accept", "application/json");
    for (Map.Entry<String, String> header : headers.entrySet()) {
      if (header.getValue() == null || header.getValue().trim().isEmpty()) {
        throw new IllegalArgumentException("Header REST requerido ausente: " + header.getKey());
      }
      request.setHeader(header.getKey(), header.getValue());
    }
    try (CloseableHttpClient client = createClient();
        CloseableHttpResponse response = client.execute(request)) {
      int status = response.getStatusLine().getStatusCode();
      if (status != 200) {
        // No cuerpo/headers/URL en excepciones: autenticacion contiene secretos.
        throw new IOException("Respuesta REST no exitosa; HTTP " + status);
      }
      String content = response.getEntity() == null ? "" : EntityUtils.toString(response.getEntity(), "UTF-8");
      return content.trim().isEmpty() ? NullNode.getInstance() : mapper.readTree(content);
    } finally {
      request.releaseConnection();
    }
  }
}
''')


def service_source(plan):
    """Render the complete closed orchestration; every integration mapping is model-owned."""
    model = plan['batch']['model']
    calls = {call['id']: call for call in model['calls']}
    properties = {p['name']: p for p in model['properties']}
    fields = {p['key']: p['field'] for p in plan['batch']['properties']}

    def prop(name):
        return 'properties.' + fields[properties[name]['key']]

    def config(key):
        return 'requiredConfig(properties.' + fields[key] + ')'

    def url(call):
        endpoint = calls[call]['endpoint']
        base = config(endpoint['property'])
        return base if endpoint['mode'] == 'full-url' else (
            'endpoint(' + base + ', ' + literal(endpoint['path']) + ')')

    # The semantic fingerprint rejects unimplemented sources/mappings before rendering.
    auth = calls['authenticate']
    auth_lines = []
    for field in auth['body']['fields']:
        value = 'auditId' if field['from'] == 'audit.requestId' else (
            'requiredConfig(' + prop(field['from'].split('.', 1)[1]) + ')')
        auth_lines.append('    payload.put(' + literal(field['name']) + ', ' + value + ');')
    header_lines = []
    for header in calls['getCollectedPayments']['headers']:
        origin = header['from']
        value = ('requiredConfig(' + prop(origin.split('.', 1)[1]) + ')' if origin.startswith('properties.')
                 else 'auditId' if origin == 'audit.requestId' else 'userKey')
        header_lines.append('    result.put(' + literal(header['name']) + ', ' + value + ');')
    null_quote = [f['name'].split('[].')[1] for f in calls['patchFinancingInstallments']['body']['fields']
                  if f['type'] == 'null']
    null_agreement = [f['name'] for f in calls['patchFinancingAgreement']['body']['fields'] if f['type'] == 'null']
    text = '''package @@PACKAGE@@.service;

import java.time.Clock;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.TimeZone;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.apache.log4j.Logger;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import @@PACKAGE@@.client.PaymentHttpClient;
import @@PACKAGE@@.service.@@SERVICE@@;
import @@PACKAGE@@.util.PropertiesExterno;

/** FULL sequential orchestration. External REST assumptions are in the reviewed plan. */
@Service
public class @@SERVICE@@Impl implements @@SERVICE@@ {
  private static final Logger LOGGER = Logger.getLogger(@@SERVICE@@Impl.class);
  private final ObjectMapper mapper = new ObjectMapper();
  private Clock clock = Clock.systemDefaultZone();
  @Autowired private PropertiesExterno properties;
  @Autowired private PaymentHttpClient client;

  public void setClock(Clock value) {
    if (value == null) { throw new IllegalArgumentException("Clock requerido"); }
    clock = value;
  }

  @Override
  public void run(String messageTransaction, String idTransaccion) {
    String trace = messageTransaction == null ? "" : messageTransaction;
    LOGGER.info(trace + "Inicio synchronizePayments");
    try {
      OffsetDateTime now = OffsetDateTime.now(clock);
      // Source uses four 's' (seconds padded to four digits), NOT milliseconds.
      // SimpleDateFormat preserves that literal legacy pattern; DateTimeFormatter rejects it.
      SimpleDateFormat auditFormat = new SimpleDateFormat(@@AUDIT_PATTERN@@);
      auditFormat.setTimeZone(TimeZone.getTimeZone(clock.getZone()));
      String auditId = auditFormat.format(Date.from(now.toInstant()));
      JsonNode auth = authenticate(auditId);
      String userKey = text(auth, "clave");
      // Keep response correlation separate; it is not necessarily an echo of the audit id.
      String authResponseId = text(auth, "idTransaccion");
      text(auth, "usuarioAplicacion");
      text(auth, "mensajeResultado");
      if (authResponseId.isEmpty()) { throw malformed(); }
      int range = positive(@@RANGE@@);
      OffsetDateTime dateEnd = OffsetDateTime.now(clock);
      DateTimeFormatter queryFormat = DateTimeFormatter.ofPattern(@@QUERY_PATTERN@@);
      Map<String, String> query = new LinkedHashMap<String, String>();
      query.put("dateEnd", dateEnd.format(queryFormat));
      query.put("dateBegin", dateEnd.minusMinutes(range).format(queryFormat));
      LOGGER.info(trace + "Consulta Cobranzas");
      JsonNode collected = exchange("GET", @@COLLECTION_URL@@, query, headers(userKey, auditId), null);
      ArrayNode records = array(collected, "data");
      if (records.size() == 0) {
        LOGGER.info(trace + "Cobranzas sin pagos; fin synchronizePayments");
        return;
      }
      for (JsonNode record : records) {
        try {
          synchronizeFinancing(record, userKey, auditId, trace);
        } catch (Exception failure) {
          // No raw request, response, credentials, URL or exception message in the log.
          LOGGER.error(trace + "Financiamiento omitido por error: " + failure.getClass().getSimpleName());
        }
      }
      LOGGER.info(trace + "Fin synchronizePayments");
    } catch (Exception failure) {
      LOGGER.error(trace + "Proceso detenido: " + failure.getClass().getSimpleName());
    }
  }

  private JsonNode authenticate(String auditId) throws Exception {
    ObjectNode root = mapper.createObjectNode();
    ObjectNode payload = root.putObject(@@AUTH_REQUEST@@);
@@AUTH_FIELDS@@
    JsonNode response = exchange("POST", @@AUTH_URL@@, new LinkedHashMap<String, String>(),
        new LinkedHashMap<String, String>(), root);
    JsonNode auth = response.get(@@AUTH_RESPONSE@@);
    if (auth == null || !auth.isObject()) { throw malformed(); }
    JsonNode code = auth.get("codigoResultado");
    boolean zero = code != null && ((code.isNumber() && code.decimalValue().signum() == 0)
        || (code.isTextual() && "0".equals(code.textValue())));
    if (!zero) { throw new IllegalStateException("Autenticacion rechazada"); }
    return auth;
  }

  private void synchronizeFinancing(JsonNode record, String key, String auditId, String trace) throws Exception {
    int agreement = integer(record, "agreementCodeId");
    ArrayNode collection = array(record, "installments");
    Map<String, String> query = new LinkedHashMap<String, String>();
    query.put("agreementCodeId", Integer.toString(agreement));
    // Source query NULLs are omitted, not encoded as the string NULL.
    LOGGER.info(trace + "Consulta cuotas Financiamiento");
    JsonNode response = exchange("GET", @@INSTALLMENTS_URL@@, query, headers(key, auditId), null);
    ArrayNode snapshot = array(response, "data");
    Map<Integer, JsonNode> payments = index(collection);
    index(snapshot); // Ambiguity check for BOTH systems, before any write.
    ArrayNode filtered = mapper.createArrayNode();
    int paid = number(@@PAID@@);
    int notified = number(@@NOTIFIED@@);
    for (JsonNode installment : snapshot) {
      int quoteNumber = integer(installment, "quoteNumber");
      if (quoteNumber == 0) { continue; }
      int state = integer(installment, "quoteStateCodeId");
      JsonNode payment = payments.get(quoteNumber);
      if (payment != null && integer(payment, "quoteStateCodeId") == paid && state == notified) {
        ObjectNode update = filtered.addObject();
        update.put("quoteCodeId", integer(installment, "quoteCodeId"));
        update.put("paymentDate", text(payment, "paymentDate"));
        update.put("paymentAmount", decimal(payment, "paymentAmount"));
        update.put("quoteStateCodeId", paid);
@@QUOTE_NULLS@@
      }
    }
    if (filtered.size() > 0) {
      ObjectNode body = mapper.createObjectNode();
      body.set("installments", filtered);
      LOGGER.info(trace + "Sincroniza cuotas pagadas");
      exchange("PATCH", @@INSTALLMENTS_URL@@, new LinkedHashMap<String, String>(), headers(key, auditId), body);
    }
    // IMPORTANT: an empty filtered list STILL reaches completion (including 0 == 0).
    int pending = 0;
    for (JsonNode installment : snapshot) {
      if (integer(installment, "quoteNumber") != 0 && integer(installment, "quoteStateCodeId") != paid) {
        pending++;
      }
    }
    if (pending == filtered.size()) {
      ObjectNode body = mapper.createObjectNode();
      body.put("agreementCodeId", agreement);
      body.put("financingStateCodeId", number(@@COMPLETED@@));
@@AGREEMENT_NULLS@@
      LOGGER.info(trace + "Actualiza financiamiento terminado");
      exchange("PATCH", @@AGREEMENT_URL@@, new LinkedHashMap<String, String>(), headers(key, auditId), body);
    }
  }

  private Map<Integer, JsonNode> index(ArrayNode values) {
    Map<Integer, JsonNode> result = new HashMap<Integer, JsonNode>();
    Set<Integer> seen = new HashSet<Integer>();
    for (JsonNode value : values) {
      int quoteNumber = integer(value, "quoteNumber");
      if (quoteNumber == 0) { continue; }
      if (!seen.add(quoteNumber)) { throw new IllegalStateException("quoteNumber ambiguo"); }
      result.put(quoteNumber, value);
    }
    return result;
  }

  private Map<String, String> headers(String userKey, String auditId) {
    Map<String, String> result = new LinkedHashMap<String, String>();
@@HEADERS@@
    return result;
  }

  private JsonNode exchange(String method, String url, Map<String, String> query,
      Map<String, String> headers, JsonNode body) throws Exception {
    return client.exchange(method, url, query, headers, body,
        positive(properties.restConnectTimeoutMs), positive(properties.restReadTimeoutMs));
  }

  private static String endpoint(String base, String path) {
    if (base.indexOf('?') >= 0 || base.indexOf('#') >= 0) {
      throw new IllegalArgumentException("Base REST sin query ni fragmento requerida");
    }
    return (base.endsWith("/") ? base.substring(0, base.length() - 1) : base) + path;
  }
  private static ArrayNode array(JsonNode parent, String field) {
    JsonNode value = parent == null ? null : parent.get(field);
    if (value == null || !value.isArray()) { throw malformed(); }
    return (ArrayNode) value;
  }
  private static int integer(JsonNode parent, String field) {
    JsonNode value = parent == null ? null : parent.get(field);
    if (value == null || !value.isIntegralNumber() || !value.canConvertToInt()) { throw malformed(); }
    return value.intValue();
  }
  private static double decimal(JsonNode parent, String field) {
    JsonNode value = parent == null ? null : parent.get(field);
    if (value == null || !value.isNumber() || !Double.isFinite(value.doubleValue())) { throw malformed(); }
    return value.doubleValue();
  }
  private static String text(JsonNode parent, String field) {
    JsonNode value = parent == null ? null : parent.get(field);
    if (value == null || !value.isTextual()) { throw malformed(); }
    return value.textValue();
  }
  private static IllegalArgumentException malformed() {
    return new IllegalArgumentException("Datos de integracion invalidos");
  }
  private static String requiredConfig(String value) {
    if (value == null || value.trim().isEmpty()) { throw new IllegalArgumentException("Configuracion externa requerida"); }
    return value;
  }
  private static int number(String value) { return Integer.parseInt(requiredConfig(value)); }
  private static int positive(String value) {
    int result = number(value);
    if (result <= 0) { throw new IllegalArgumentException("Configuracion positiva requerida"); }
    return result;
  }
}
'''
    replacements = {
        'AUDIT_PATTERN': model['process']['steps'][0]['idTransaccion']['pattern'],
        'QUERY_PATTERN': model['algorithms'][1]['steps'][2]['pattern'],
        'AUTH_REQUEST': auth['body']['wrapper'], 'AUTH_RESPONSE': auth['response']['wrapper']}
    for key, value in replacements.items():
        text = text.replace('@@' + key + '@@', literal(value))
    for key, value in {'AUTH_URL': url('authenticate'), 'COLLECTION_URL': url('getCollectedPayments'),
                       'INSTALLMENTS_URL': url('getFinancingInstallments'), 'AGREEMENT_URL': url('patchFinancingAgreement'),
                       'RANGE': prop('propRangoQueryMin'), 'PAID': prop('propEstadoCuotaPagada'),
                       'NOTIFIED': prop('propEstadoCuotaNotificada'), 'COMPLETED': prop('propEstadoFinanTerminada'),
                       'AUTH_FIELDS': '\n'.join(auth_lines), 'HEADERS': '\n'.join(header_lines),
                       'QUOTE_NULLS': '\n'.join('        update.putNull(' + literal(name) + ');' for name in null_quote),
                       'AGREEMENT_NULLS': '\n'.join('      body.putNull(' + literal(name) + ');' for name in null_agreement)}.items():
        text = text.replace('@@' + key + '@@', value)
    return source(plan, text)
