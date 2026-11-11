"""JUnit4/Mockito tests rendered from the same closed payment-sync plan."""
from batch_payment_sync_java import source


def http_test(plan):
    return source(plan, '''package @@PACKAGE@@.client;

import java.io.IOException;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import org.apache.http.ProtocolVersion;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpEntityEnclosingRequestBase;
import org.apache.http.client.methods.HttpUriRequest;
import org.apache.http.client.utils.URIBuilder;
import org.apache.http.entity.ContentType;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.message.BasicStatusLine;
import org.apache.http.util.EntityUtils;
import org.junit.Before;
import org.junit.Test;
import org.mockito.ArgumentCaptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class PaymentHttpClientTest {
  private CloseableHttpClient transport;
  private CloseableHttpResponse response;
  private PaymentHttpClient client;

  @Before
  public void setup() throws Exception {
    transport = mock(CloseableHttpClient.class);
    response = mock(CloseableHttpResponse.class);
    client = new PaymentHttpClient() {
      @Override protected CloseableHttpClient createClient() { return transport; }
    };
    when(response.getStatusLine()).thenReturn(new BasicStatusLine(new ProtocolVersion("HTTP", 1, 1), 200, "OK"));
    when(response.getEntity()).thenReturn(new StringEntity("{\\"data\\":[]}", ContentType.APPLICATION_JSON));
    when(transport.execute(any(HttpUriRequest.class))).thenReturn(response);
  }

  @Test
  public void omitsNullQueryAndPreservesOffsetEncodingAndHeaders() throws Exception {
    Map<String, String> query = new LinkedHashMap<String, String>();
    query.put("absent", null);
    query.put("dateBegin", "2026-11-11T13:00:00-05:00");
    Map<String, String> headers = Collections.singletonMap("user_key", "not-a-real-secret");
    assertTrue(client.exchange("GET", "http://example.invalid/payments", query, headers, null, 100, 100).get("data").isArray());
    ArgumentCaptor<HttpUriRequest> capture = ArgumentCaptor.forClass(HttpUriRequest.class);
    verify(transport).execute(capture.capture());
    assertEquals("not-a-real-secret", capture.getValue().getFirstHeader("user_key").getValue());
    assertEquals(1, new URIBuilder(capture.getValue().getURI()).getQueryParams().size());
    assertEquals(query.get("dateBegin"), new URIBuilder(capture.getValue().getURI()).getQueryParams().get(0).getValue());
    verify(response).close();
    verify(transport).close();
  }

  @Test
  public void patchSerializesRealNullAndArray() throws Exception {
    ObjectNode body = new ObjectMapper().createObjectNode();
    body.putNull("customerId");
    body.putArray("installments").addObject().put("paymentAmount", 12.75);
    client.exchange("PATCH", "http://example.invalid/financing", Collections.<String, String>emptyMap(),
        Collections.<String, String>emptyMap(), body, 100, 100);
    ArgumentCaptor<HttpUriRequest> capture = ArgumentCaptor.forClass(HttpUriRequest.class);
    verify(transport).execute(capture.capture());
    assertEquals("PATCH", capture.getValue().getMethod());
    String json = EntityUtils.toString(((HttpEntityEnclosingRequestBase) capture.getValue()).getEntity(), "UTF-8");
    assertTrue(new ObjectMapper().readTree(json).get("customerId").isNull());
    assertEquals(12.75, new ObjectMapper().readTree(json).get("installments").get(0).get("paymentAmount").asDouble(), 0.0);
  }

  @Test
  public void rejectsOther2xxWithoutLeakingResponseOrRetrying() throws Exception {
    when(response.getStatusLine()).thenReturn(new BasicStatusLine(new ProtocolVersion("HTTP", 1, 1), 201, "Created"));
    when(response.getEntity()).thenReturn(new StringEntity("sensitive-authentication-response"));
    try {
      client.exchange("POST", "http://example.invalid/auth", Collections.<String, String>emptyMap(),
          Collections.<String, String>emptyMap(), new ObjectMapper().createObjectNode(), 100, 100);
      fail("Only documented HTTP 200 is successful");
    } catch (IOException expected) {
      assertTrue(expected.getMessage().contains("201"));
      assertFalse(expected.getMessage().contains("sensitive"));
    }
    verify(transport, times(1)).execute(any(HttpUriRequest.class));
    verify(response).close();
    verify(transport).close();
  }

  @Test(expected = IllegalArgumentException.class)
  public void refusesEmbeddedCredentials() throws Exception {
    client.exchange("GET", "http://secret@example.invalid/path", Collections.<String, String>emptyMap(),
        Collections.<String, String>emptyMap(), null, 100, 100);
  }

  @Test(expected = IllegalArgumentException.class)
  public void refusesMissingTimeouts() throws Exception {
    client.exchange("GET", "http://example.invalid/path", Collections.<String, String>emptyMap(),
        Collections.<String, String>emptyMap(), null, 0, 100);
  }
}
''')
def service_test(plan):
    from batch_payment_sync_java import source, literal
    defaults = {p['name']: p.get('default') for p in plan['batch']['model']['properties']}
    init = []
    for prop in plan['batch']['properties']:
        value = defaults.get(prop['field'])
        if value is None:
            value = ('1000' if 'TimeoutMs' in prop['field'] else
                     'https://example.invalid' if 'url' in prop['field'] else 'fixture-' + prop['field'])
        init.append('    properties.' + prop['field'] + ' = ' + literal(str(value)) + ';')
    text = '''package @@PACKAGE@@.service;

import java.lang.reflect.Field;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.apache.log4j.Appender;
import org.apache.log4j.Logger;
import org.apache.log4j.spi.LoggingEvent;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import org.mockito.ArgumentCaptor;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import @@PACKAGE@@.client.PaymentHttpClient;
import @@PACKAGE@@.util.PropertiesExterno;

public class @@SERVICE@@ImplTest {
  private final ObjectMapper mapper = new ObjectMapper();
  private @@SERVICE@@Impl service;
  private PropertiesExterno properties;
  private RecordingClient client;
  private Appender appender;

  private static class Call {
    String method;
    String url;
    Map<String, String> query;
    Map<String, String> headers;
    JsonNode body;
    Call(String m, String u, Map<String, String> q, Map<String, String> h, JsonNode b) {
      method = m; url = u; query = q; headers = h; body = b;
    }
  }
  private static class RecordingClient extends PaymentHttpClient {
    List<Call> calls = new ArrayList<Call>();
    List<Object> responses = new ArrayList<Object>();
    @Override public JsonNode exchange(String method, String url, Map<String, String> query,
        Map<String, String> headers, JsonNode body, int connectMs, int readMs) throws Exception {
      calls.add(new Call(method, url, query, headers, body));
      Object response = responses.remove(0);
      if (response instanceof Exception) { throw (Exception) response; }
      return (JsonNode) response;
    }
  }
  @Before public void setup() throws Exception {
    service = new @@SERVICE@@Impl();
    properties = new PropertiesExterno();
@@PROPERTY_VALUES@@
    properties.idf0Codigo = "ok";
    properties.idf0Mensaje = "ok";
    properties.idt1Codigo = "error";
    properties.idt1Mensaje = "error";
    client = new RecordingClient();
    inject("properties", properties);
    inject("client", client);
    service.setClock(Clock.fixed(Instant.parse("2026-11-11T12:30:45Z"), ZoneId.of("America/Lima")));
    appender = mock(Appender.class);
    Logger.getLogger(@@SERVICE@@Impl.class).addAppender(appender);
  }
  @After public void cleanup() { Logger.getLogger(@@SERVICE@@Impl.class).removeAppender(appender); }
  private void inject(String name, Object value) throws Exception {
    Field field = @@SERVICE@@Impl.class.getDeclaredField(name);
    field.setAccessible(true);
    field.set(service, value);
  }
  private ObjectNode auth(Object code) {
    ObjectNode root = mapper.createObjectNode();
    ObjectNode body = root.putObject("desencriptarResponse");
    body.put("idTransaccion", "DIFFERENT-AUTH-RESPONSE-ID");
    body.put("usuarioAplicacion", "SENSITIVE-USER");
    body.put("clave", "SENSITIVE-KEY");
    body.put("mensajeResultado", "ok");
    body.set("codigoResultado", mapper.valueToTree(code));
    return root;
  }
  private ObjectNode quote(int id, int number, int state) {
    ObjectNode quote = mapper.createObjectNode();
    quote.put("quoteCodeId", id); quote.put("quoteNumber", number); quote.put("quoteStateCodeId", state);
    quote.put("paymentDate", "2026-11-10T13:14:15-05:00"); quote.put("paymentAmount", 12.75);
    return quote;
  }
  private ObjectNode record(int agreement, JsonNode... quotes) {
    ObjectNode record = mapper.createObjectNode();
    record.put("agreementCodeId", agreement);
    ArrayNode installments = record.putArray("installments");
    for (JsonNode quote : quotes) { installments.add(quote); }
    return record;
  }
  private ObjectNode data(JsonNode... rows) {
    ObjectNode root = mapper.createObjectNode();
    root.put("code", 99); // Downstream success is HTTP 200, NOT an invented code=0 check.
    ArrayNode data = root.putArray("data");
    for (JsonNode row : rows) { data.add(row); }
    return root;
  }
  private void run(Object... responses) {
    for (Object response : responses) { client.responses.add(response); }
    service.run("[cli-log-tx] ", "CLI-TRANSACTION");
  }
  @Test public void run_fullFlow_mapsFinancingIdsAndCollectionPayments() {
    run(auth("0"), data(record(10, quote(900, 0, 3), quote(901, 1, 3), quote(902, 2, 3))),
        data(quote(100, 0, 2), quote(101, 1, 2), quote(102, 2, 2)), data(), data());
    assertEquals(5, client.calls.size());
    Call patch = client.calls.get(3);
    assertEquals("PATCH", patch.method);
    assertEquals(2, patch.body.get("installments").size());
    JsonNode first = patch.body.get("installments").get(0);
    assertEquals(101, first.get("quoteCodeId").intValue());
    assertEquals(12.75, first.get("paymentAmount").doubleValue(), 0.0);
    assertEquals("2026-11-10T13:14:15-05:00", first.get("paymentDate").textValue());
    assertEquals(3, first.get("quoteStateCodeId").intValue());
    assertEquals(8, first.size());
    for (String field : new String[] {"quoteFormat", "quoteAmount", "quoteIssueDate", "quoteExpirationDate"}) {
      assertTrue(first.has(field)); assertTrue(first.get(field).isNull());
    }
    assertEquals(10, client.calls.get(4).body.get("agreementCodeId").intValue());
    assertEquals(5, client.calls.get(4).body.get("financingStateCodeId").intValue());
    assertEquals(9, client.calls.get(4).body.size());
    assertTrue(client.calls.get(4).body.get("imei").isNull());
    assertEquals("FINAN", patch.headers.get("x-app-id"));
    assertEquals("1.0", patch.headers.get("x-client-version-id"));
  }
  @Test public void run_datesAndCorrelation_areClockControlledAndIndependent() {
    run(auth(0), data());
    Call auth = client.calls.get(0);
    String audit = auth.body.get("desencriptarRequest").get("idTransaccion").textValue();
    assertEquals("2026111107300045", audit);
    assertEquals(8, auth.body.get("desencriptarRequest").size());
    Call payments = client.calls.get(1);
    assertEquals("2026-11-11T07:30:45-0500", payments.query.get("dateEnd"));
    assertEquals("2026-11-11T06:20:45-0500", payments.query.get("dateBegin"));
    assertEquals(audit, payments.headers.get("x-request-id"));
    assertNotEquals("DIFFERENT-AUTH-RESPONSE-ID", audit);
    assertNotEquals("CLI-TRANSACTION", audit);
    assertEquals("SENSITIVE-KEY", payments.headers.get("user_key"));
    assertEquals(6, payments.headers.size());
  }
  @Test public void run_noPayments_stopsAfterCollection() {
    run(auth(0), data()); assertEquals(2, client.calls.size());
  }
  @Test public void run_authRejectsNullBooleanAndNonzero() {
    for (Object code : new Object[] {null, true, false, 1, "00", "1"}) {
      client.calls.clear(); client.responses.clear(); run(auth(code));
      assertEquals(1, client.calls.size());
    }
  }
  @Test public void run_authTransportFailure_stopsWholeProcess() {
    run(new java.io.IOException("fixture")); assertEquals(1, client.calls.size());
  }
  @Test public void run_malformedCollection_stopsWholeProcess() {
    run(auth(0), mapper.createObjectNode()); assertEquals(2, client.calls.size());
  }
  @Test public void run_collectionFailure_stopsWholeProcess() {
    run(auth(0), new java.io.IOException("fixture")); assertEquals(2, client.calls.size());
  }
  @Test public void run_emptyFilterStillEvaluatesCompletion() {
    run(auth(0), data(record(10, quote(901, 1, 3))), data(quote(101, 1, 3)), data());
    assertEquals(4, client.calls.size());
    assertTrue(client.calls.get(3).url.endsWith("/api/v1/financingAgreement"));
  }
  @Test public void run_pendingUnsynchronized_doesNotComplete() {
    run(auth(0), data(record(10, quote(901, 1, 2))), data(quote(101, 1, 2)));
    assertEquals(3, client.calls.size());
  }
  @Test public void run_notAllPendingCovered_patchesButDoesNotComplete() {
    run(auth(0), data(record(10, quote(901, 1, 3))), data(quote(101, 1, 2), quote(102, 2, 2)), data());
    assertEquals(4, client.calls.size());
    assertTrue(client.calls.get(3).url.endsWith("/api/v1/financingInstallment"));
  }
  @Test public void run_duplicateCollection_failsClosedBeforeWrites() {
    run(auth(0), data(record(10, quote(901, 1, 3), quote(902, 1, 3))), data(quote(101, 1, 2)));
    assertEquals(3, client.calls.size());
  }
  @Test public void run_duplicateFinancing_failsClosedBeforeWrites() {
    run(auth(0), data(record(10, quote(901, 1, 3))), data(quote(101, 1, 2), quote(102, 1, 2)));
    assertEquals(3, client.calls.size());
  }
  @Test public void run_initialQuotesExcludedEvenIfDuplicated() {
    run(auth(0), data(record(10, quote(900, 0, 3), quote(901, 0, 3))), data(quote(100, 0, 2), quote(101, 0, 2)), data());
    assertEquals(4, client.calls.size());
    assertTrue(client.calls.get(3).url.endsWith("/api/v1/financingAgreement"));
  }
  @Test public void run_installmentFailure_preventsCompletionAndContinuesNextFinancing() {
    run(auth(0), data(record(10, quote(901, 1, 3)), record(20, quote(902, 2, 3))),
        data(quote(101, 1, 2)), new java.io.IOException("fixture"), data(quote(102, 2, 3)), data());
    assertEquals(6, client.calls.size());
    assertEquals("20", client.calls.get(4).query.get("agreementCodeId"));
    assertEquals(20, client.calls.get(5).body.get("agreementCodeId").intValue());
  }
  @Test public void run_financingReadFailure_continuesNextFinancing() {
    run(auth(0), data(record(10), record(20)), new java.io.IOException("fixture"), data(), data());
    assertEquals(5, client.calls.size());
    assertEquals("20", client.calls.get(3).query.get("agreementCodeId"));
  }
  @Test public void run_agreementFailure_continuesNextFinancing() {
    run(auth(0), data(record(10), record(20)), data(), new java.io.IOException("fixture"), data(), data());
    assertEquals(6, client.calls.size());
    assertEquals("20", client.calls.get(4).query.get("agreementCodeId"));
  }
  @Test public void run_missingPaymentAmount_neverDefaultsToZero() {
    ObjectNode quote = quote(901, 1, 3); quote.remove("paymentAmount");
    run(auth(0), data(record(10, quote)), data(quote(101, 1, 2)));
    assertEquals(3, client.calls.size());
  }
  @Test public void run_queryNullsOmitted_andStateAliasesConfigurable() {
    properties.propEstadoCuotaPagada = "30";
    properties.propEstadoCuotaNotificada = "20";
    properties.propEstadoFinanTerminada = "50";
    run(auth(0), data(record(10, quote(901, 1, 30))), data(quote(101, 1, 20)), data(), data());
    assertEquals(1, client.calls.get(2).query.size());
    assertEquals(30, client.calls.get(3).body.get("installments").get(0).get("quoteStateCodeId").intValue());
    assertEquals(50, client.calls.get(4).body.get("financingStateCodeId").intValue());
  }
  @Test public void run_logsDoNotExposeCredentialsOrRawPayloads() {
    run(auth(0), data());
    ArgumentCaptor<LoggingEvent> events = ArgumentCaptor.forClass(LoggingEvent.class);
    verify(appender, atLeastOnce()).doAppend(events.capture());
    for (LoggingEvent event : events.getAllValues()) {
      String log = event.getRenderedMessage();
      assertFalse(log.contains("SENSITIVE-KEY")); assertFalse(log.contains("SENSITIVE-USER"));
      assertFalse(log.contains("fixture-propClaveEncriptado"));
    }
  }
  @Test public void run_invalidTimeoutDoesNotCallClient() {
    properties.restConnectTimeoutMs = "0"; run(); assertEquals(0, client.calls.size());
  }
}
'''
    return source(plan, text.replace('@@PROPERTY_VALUES@@', '\n'.join(init)))

def traceability(plan):
    """Explicit source-rule -> generated scenario mapping, never a coverage percentage."""
    rules = {
        'authentication': ['run_authRejectsNullBooleanAndNonzero', 'run_authTransportFailure_stopsWholeProcess'],
        'collections': ['run_noPayments_stopsAfterCollection', 'run_collectionFailure_stopsWholeProcess',
                        'run_malformedCollection_stopsWholeProcess'],
        'query-window-and-audit': ['run_datesAndCorrelation_areClockControlledAndIndependent'],
        'join-financing-ids-payment-values': ['run_fullFlow_mapsFinancingIdsAndCollectionPayments'],
        'initial-installment-exclusion': ['run_initialQuotesExcludedEvenIfDuplicated'],
        'duplicate-fail-closed': ['run_duplicateCollection_failsClosedBeforeWrites', 'run_duplicateFinancing_failsClosedBeforeWrites'],
        'installments-array-and-nulls': ['run_fullFlow_mapsFinancingIdsAndCollectionPayments'],
        'completion-snapshot-and-empty-filter': ['run_emptyFilterStillEvaluatesCompletion',
            'run_pendingUnsynchronized_doesNotComplete', 'run_notAllPendingCovered_patchesButDoesNotComplete'],
        'financing-error-continuation': ['run_installmentFailure_preventsCompletionAndContinuesNextFinancing',
            'run_financingReadFailure_continuesNextFinancing', 'run_agreementFailure_continuesNextFinancing'],
        'malformed-data-no-defaults': ['run_missingPaymentAmount_neverDefaultsToZero'],
        'configurable-state-and-null-query': ['run_queryNullsOmitted_andStateAliasesConfigurable'],
        'sensitive-trace-policy': ['run_logsDoNotExposeCredentialsOrRawPayloads'],
        'timeouts': ['run_invalidTimeoutDoesNotCallClient']}
    return {'schemaVersion': 2, 'service': plan['service']['name'], 'rules': [
        {'id': key, 'source': 'normalized-Sparx-or-explicit-delegated-decision', 'methods': methods,
         'status': 'generated-not-executed'} for key, methods in rules.items()],
        'sourceBindings': plan['batch']['sourceBindings'],
        'limitations': ['Transport scenarios also cover HTTP status, JSON null and resource cleanup.',
                        'No real network, Spring context startup, provider interoperability or baseline Maven execution.']}
