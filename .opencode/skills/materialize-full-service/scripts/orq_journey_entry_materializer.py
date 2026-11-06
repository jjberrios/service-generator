"""Deterministic materializer of the orq-journeyEntry orchestrator (HTTP profile of claro-spring-ms, no persistence).

POST /api/v1/orq-orq-accountManagement/send reads the journal entry from dom-journeyEntry, calls the two SAP RFC services through the OSB
(registrarPedidoSinergia, registrarPagoSinergia) and records each stage in dom-journeyEntry. No database is accessed.

Usage: python orq_journey_entry_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import re
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402

PACKAGE = 'com.claro.orq.journeyentry'
for _name, _fqcn in {
        'ArgumentCaptor': 'org.mockito.ArgumentCaptor', 'InOrder': 'org.mockito.InOrder', 'MockHttpServletRequestBuilder': 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder',
        'RestClient': 'org.springframework.web.client.RestClient', 'SimpleClientHttpRequestFactory': 'org.springframework.http.client.SimpleClientHttpRequestFactory',
        'ResourceAccessException': 'org.springframework.web.client.ResourceAccessException', 'RestClientResponseException': 'org.springframework.web.client.RestClientResponseException',
        'SocketTimeoutException': 'java.net.SocketTimeoutException', 'IOException': 'java.io.IOException', 'MockRestServiceServer': 'org.springframework.test.web.client.MockRestServiceServer',
        'JsonProcessingException': 'com.fasterxml.jackson.core.JsonProcessingException', 'JsonNode': 'com.fasterxml.jackson.databind.JsonNode', 'Objects': 'java.util.Objects',
        'MediaType': 'org.springframework.http.MediaType', 'HttpMethod': 'org.springframework.http.HttpMethod', 'HttpHeaders': 'org.springframework.http.HttpHeaders',
        'Instant': 'java.time.Instant'}.items():
    dj.EXTERNAL.setdefault(_name, _fqcn)

REQUEST_DTOS = {'SendJourneyEntryRequest': [('Long', 'journalEntryId'), ('String', 'executionReason')]}
RESPONSE_DTOS = {'JourneyEntryResponse': [('Integer', 'code'), ('String', 'message')]}
CLIENT_DTOS = {
    'JourneyEntryData': [('Long', 'journalEntryId'), ('String', 'entryPayload'), ('String', 'firstRequest'), ('String', 'secondRequest'), ('Integer', 'attemptNumber')],
    'JourneyEntryResultRequest': [('String', 'stage'), ('String', 'expectedStatus'), ('String', 'firstResponse'), ('Integer', 'journalEntryStatusId'), ('Integer', 'attemptNumber'),
                                  ('String', 'attemptStartedAt'), ('String', 'sapOrderNumber'), ('String', 'sapDeliveryNumber'), ('String', 'sapInvoiceNumber'), ('String', 'secondResponse'),
                                  ('String', 'sapAccountingDocumentNumber')],
}

dj.register('dto.request', 'RequestHeaders', *REQUEST_DTOS)
dj.register('dto.response', 'ErrorResponse', *RESPONSE_DTOS)
dj.register('dto.mapper', 'JourneyEntryMapper', 'SapResponseReader')
dj.register('service', 'JourneyEntryService')
dj.register('service.impl', 'JourneyEntryServiceImpl')
dj.register('validation', 'JourneyEntryValidator')
dj.register('controller', 'JourneyEntryApi')
dj.register('controller.impl', 'JourneyEntryController')
dj.register('client', 'DomJourneyEntryClient', 'DomJourneyEntryClientImpl', 'SapClient', 'SapClientImpl', 'RemoteFailures')
dj.register('client.dto', *CLIENT_DTOS, 'JourneyEntryEnvelope', 'ForwardedHeaders')
dj.register('configuration', 'ClientConfig', 'StageSettings', 'StageSettingsConfig', 'ClockConfig')

FORWARDED_HEADERS = '''/** Headers received by the API that are forwarded to the dependencies. */
public record ForwardedHeaders(String traceparent, String xAppId, String xChannel, String xClientVersionId, String xCorrelationId, String xRequestId, String xUserId) {
    /** Copies the forwarded headers into the outgoing request. */
    public void applyTo(HttpHeaders target) {
        put(target, "traceparent", traceparent);
        put(target, "x-app-id", xAppId);
        put(target, "x-channel", xChannel);
        put(target, "x-client-version-id", xClientVersionId);
        put(target, "x-correlation-id", xCorrelationId);
        put(target, "x-request-id", xRequestId);
        put(target, "x-user-id", xUserId);
    }

    private static void put(HttpHeaders target, String name, String value) {
        if (value != null) {
            target.set(name, value);
        }
    }
}'''

REMOTE_FAILURES = '''/** Translation of remote call failures into the technical statuses of the service. */
public final class RemoteFailures {
    private static final String UNAVAILABLE = "El servicio %s no se encuentra disponible.";
    private static final String TIMEOUT = "El servicio %s no respondi\\u00f3 a tiempo.";
    private static final String INVALID = "El servicio %s devolvi\\u00f3 una respuesta no v\\u00e1lida.";
    private static final String NOT_FOUND = "No se encontr\\u00f3 el asiento contable indicado.";

    private RemoteFailures() {
    }

    /** Builds the exception that represents the failure; a remote 404 is a business not found only when the caller marks it so. */
    public static ServiceOperationException of(RuntimeException failure, String service, boolean notFoundIsBusiness) {
        if (failure instanceof ResourceAccessException) {
            return timedOut(failure) ? new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, String.format(TIMEOUT, service))
                    : new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, String.format(UNAVAILABLE, service));
        }
        if (failure instanceof RestClientResponseException remote) {
            int code = remote.getStatusCode().value();
            if (code == HttpStatus.NOT_FOUND.value() && notFoundIsBusiness) {
                return new ServiceOperationException(HttpStatus.NOT_FOUND, NOT_FOUND);
            }
            if (code == HttpStatus.GATEWAY_TIMEOUT.value() || code == HttpStatus.REQUEST_TIMEOUT.value()) {
                return new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, String.format(TIMEOUT, service));
            }
            if (code == HttpStatus.SERVICE_UNAVAILABLE.value() || code == HttpStatus.BAD_GATEWAY.value()) {
                return new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, String.format(UNAVAILABLE, service));
            }
        }
        return new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, String.format(INVALID, service));
    }

    private static boolean timedOut(Throwable failure) {
        Throwable current = failure;
        while (current != null) {
            if (current instanceof SocketTimeoutException) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }
}'''

DOM_CLIENT_IF = '''/** Client of the dom-journeyEntry service that owns the journal entry. */
public interface DomJourneyEntryClient {
    JourneyEntryData getEntry(ForwardedHeaders headers, Long journalEntryId);

    void updateResult(ForwardedHeaders headers, Long journalEntryId, JourneyEntryResultRequest result);
}'''

DOM_CLIENT_IMPL = '''/** HTTP client of dom-journeyEntry GET and PATCH /api/v1/dom-journeyEntry/{id}. */
@RequiredArgsConstructor
@Slf4j
public class DomJourneyEntryClientImpl implements DomJourneyEntryClient {
    private static final String PATH = "/api/v1/dom-journeyEntry/{id}";
    private static final String SERVICE = "dom-journeyEntry";
    private static final String INVALID = "El servicio dom-journeyEntry devolvi\\u00f3 una respuesta no v\\u00e1lida.";

    private final RestClient restClient;

    @Override
    public JourneyEntryData getEntry(ForwardedHeaders headers, Long journalEntryId) {
        try {
            JourneyEntryEnvelope response = restClient.get().uri(PATH, journalEntryId).headers(headers::applyTo).retrieve().body(JourneyEntryEnvelope.class);
            if (response == null || response.getData() == null) {
                throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, INVALID);
            }
            return response.getData();
        } catch (ResourceAccessException | RestClientResponseException e) {
            log.error("dom-journeyEntry GET fallo: {}", e.getMessage());
            throw RemoteFailures.of(e, SERVICE, true);
        }
    }

    @Override
    public void updateResult(ForwardedHeaders headers, Long journalEntryId, JourneyEntryResultRequest result) {
        try {
            restClient.patch().uri(PATH, journalEntryId).contentType(MediaType.APPLICATION_JSON).headers(headers::applyTo).body(result).retrieve().toBodilessEntity();
        } catch (ResourceAccessException | RestClientResponseException e) {
            log.error("dom-journeyEntry PATCH fallo: {}", e.getMessage());
            throw RemoteFailures.of(e, SERVICE, true);
        }
    }
}'''

SAP_CLIENT_IF = '''/** Client of the SAP RFC services exposed through the OSB (synchronous calls). */
public interface SapClient {
    String registrarPedidoSinergia(ForwardedHeaders headers, String payload);

    String registrarPagoSinergia(ForwardedHeaders headers, String payload);
}'''

SAP_CLIENT_IMPL = '''/** HTTP client of the OSB operations registrarPedidoSinergia (RFC_1) and registrarPagoSinergia (RFC_2). */
@RequiredArgsConstructor
@Slf4j
public class SapClientImpl implements SapClient {
    private static final String SERVICE = "OSB";

    private final RestClient restClient;
    private final String orderPath;
    private final String paymentPath;

    @Override
    public String registrarPedidoSinergia(ForwardedHeaders headers, String payload) {
        return call(orderPath, headers, payload);
    }

    @Override
    public String registrarPagoSinergia(ForwardedHeaders headers, String payload) {
        return call(paymentPath, headers, payload);
    }

    private String call(String path, ForwardedHeaders headers, String payload) {
        try {
            String body = restClient.post().uri(path).contentType(MediaType.APPLICATION_JSON).headers(headers::applyTo).body(payload).retrieve().body(String.class);
            return body == null ? "" : body;
        } catch (ResourceAccessException | RestClientResponseException e) {
            log.error("OSB {} fallo: {}", path, e.getMessage());
            throw RemoteFailures.of(e, SERVICE, false);
        }
    }
}'''

CLIENT_CONFIG = '''/** HTTP client configuration of the dependencies (base URLs, paths and timeout are environment parameters). */
@Configuration
public class ClientConfig {
    private static RestClient restClient(String baseUrl, int timeoutMs) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeoutMs);
        factory.setReadTimeout(timeoutMs);
        return RestClient.builder().baseUrl(baseUrl).requestFactory(factory).build();
    }

    @Bean
    public DomJourneyEntryClient domJourneyEntryClient(@Value("${dom-journey-entry.base-url:http://dom-journeyentry}") String baseUrl,
            @Value("${dom-journey-entry.timeout-ms:5000}") int timeoutMs) {
        return new DomJourneyEntryClientImpl(restClient(baseUrl, timeoutMs));
    }

    @Bean
    public SapClient sapClient(@Value("${osb.base-url:http://osb}") String baseUrl, @Value("${osb.timeout-ms:30000}") int timeoutMs,
            @Value("${osb.registrar-pedido-path:/registrarPedidoSinergia}") String orderPath,
            @Value("${osb.registrar-pago-path:/registrarPagoSinergia}") String paymentPath) {
        return new SapClientImpl(restClient(baseUrl, timeoutMs), orderPath, paymentPath);
    }
}'''

STAGE_SETTINGS = '''/** Journal entry status ids written to dom-journeyEntry after each RFC call. */
public record StageSettings(Integer firstCallStatusId, Integer secondCallStatusId) {
}'''

STAGE_SETTINGS_CONFIG = '''/** Environment parameters of the status ids recorded after each stage. */
@Configuration
public class StageSettingsConfig {
    @Bean
    public StageSettings stageSettings(@Value("${journey-entry.status-after-first-call:2}") Integer first, @Value("${journey-entry.status-after-second-call:3}") Integer second) {
        return new StageSettings(first, second);
    }
}'''

VALIDATOR = '''/** Declared contract rules of the send operation. */
@Component
public class JourneyEntryValidator {
    private static final String INVALID = "Par\\u00e1metros obligatorios incompletos o con valores no v\\u00e1lidos.";
    private static final Set<String> REASONS = Set.of("INITIAL", "AUTOMATIC_RETRY", "MANUAL_RESEND");

    public void validate(SendJourneyEntryRequest request) {
        if (request == null || request.getJournalEntryId() == null || request.getJournalEntryId() <= 0 || request.getExecutionReason() == null
                || !REASONS.contains(request.getExecutionReason())) {
            throw ServiceOperationException.badRequest(INVALID);
        }
    }
}'''

MAPPER = '''/** Explicit mapping of the success response. */
@Component
public class JourneyEntryMapper {
    private static final String SUCCESS_MESSAGE = "Operaci\\u00f3n exitosa";

    public JourneyEntryResponse success() {
        JourneyEntryResponse response = new JourneyEntryResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        return response;
    }
}'''

READER = '''/** Reads the SAP document numbers from the JSON answered by an RFC call; absent or non JSON values are null. */
@Component
public class SapResponseReader {
    private static final String CREATED_ITEMS = "itemDocCreados";

    private final ObjectMapper json = new ObjectMapper();

    public String find(String body, String field) {
        if (body == null || body.isBlank()) {
            return null;
        }
        try {
            JsonNode root = json.readTree(body);
            JsonNode direct = root.path(field);
            JsonNode node = direct.isMissingNode() || direct.isNull() ? root.path(CREATED_ITEMS).path(field) : direct;
            return node.isMissingNode() || node.isNull() || node.isContainerNode() ? null : node.asText();
        } catch (JsonProcessingException e) {
            return null;
        }
    }
}'''

SERVICE_IF = '''/** Orquestacion del envio de asientos contables a SAP. */
public interface JourneyEntryService {
    JourneyEntryResponse sendJourneyEntryToSap(RequestHeaders headers, ForwardedHeaders forwarded, SendJourneyEntryRequest request);
}'''

SERVICE_IMPL = '''/** Activity-logged orchestration; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class JourneyEntryServiceImpl implements JourneyEntryService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String NO_PAYLOAD = "El asiento contable no tiene la trama a enviar a SAP.";
    private static final String FIRST_STAGE = "RFC_1";
    private static final String SECOND_STAGE = "RFC_2";
    private static final String FIRST_EXPECTED = "LLAMADO_1_COMPLETO";
    private static final String SECOND_EXPECTED = "LLAMADO_2_COMPLETO";

    private final DomJourneyEntryClient entries;
    private final SapClient sap;
    private final JourneyEntryValidator validator;
    private final JourneyEntryMapper mapper;
    private final SapResponseReader reader;
    private final StageSettings stages;
    private final Clock clock;

    @Override
    public JourneyEntryResponse sendJourneyEntryToSap(RequestHeaders headers, ForwardedHeaders forwarded, SendJourneyEntryRequest request) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> {
            logRequest(headers, request);
            validator.validate(request);
            return Boolean.TRUE;
        });
        Long id = request.getJournalEntryId();
        JourneyEntryData entry = ejecutarActividad(menTran, ConstanApi.ACT2_CONSULTAR_ASIENTO_CONTABLE, () -> entries.getEntry(forwarded, id));
        final int attempt = (entry.getAttemptNumber() == null ? 0 : entry.getAttemptNumber()) + 1;
        final String startedAt = Instant.now(clock).toString();
        String firstPayload = payload(menTran, entry.getFirstRequest(), entry);
        String firstResponse = ejecutarActividad(menTran, ConstanApi.ACT3_INVOCAR_RFC_1, () -> sap.registrarPedidoSinergia(forwarded, firstPayload));
        JourneyEntryResultRequest first = new JourneyEntryResultRequest();
        first.setStage(FIRST_STAGE);
        first.setExpectedStatus(FIRST_EXPECTED);
        first.setFirstResponse(firstResponse);
        first.setJournalEntryStatusId(stages.firstCallStatusId());
        first.setAttemptNumber(attempt);
        first.setAttemptStartedAt(startedAt);
        first.setSapOrderNumber(reader.find(firstResponse, "pedido"));
        first.setSapDeliveryNumber(reader.find(firstResponse, "entrega"));
        first.setSapInvoiceNumber(reader.find(firstResponse, "factura"));
        ejecutarActividad(menTran, ConstanApi.ACT4_REGISTRAR_ETAPA_1, () -> {
            entries.updateResult(forwarded, id, first);
            return Boolean.TRUE;
        });
        String secondPayload = payload(menTran, entry.getSecondRequest(), entry);
        String secondResponse = ejecutarActividad(menTran, ConstanApi.ACT5_INVOCAR_RFC_2, () -> sap.registrarPagoSinergia(forwarded, secondPayload));
        JourneyEntryResultRequest second = new JourneyEntryResultRequest();
        second.setStage(SECOND_STAGE);
        second.setExpectedStatus(SECOND_EXPECTED);
        second.setSecondResponse(secondResponse);
        second.setJournalEntryStatusId(stages.secondCallStatusId());
        second.setAttemptNumber(attempt);
        second.setAttemptStartedAt(startedAt);
        ejecutarActividad(menTran, ConstanApi.ACT6_REGISTRAR_ETAPA_2, () -> {
            entries.updateResult(forwarded, id, second);
            return Boolean.TRUE;
        });
        return mapper.success();
    }

    private String payload(String menTran, String preferred, JourneyEntryData entry) {
        String selected = preferred != null && !preferred.isBlank() ? preferred : entry.getEntryPayload();
        if (selected == null || selected.isBlank()) {
            log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT3_INVOCAR_RFC_1, HttpStatus.INTERNAL_SERVER_ERROR.value(), NO_PAYLOAD);
            throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, NO_PAYLOAD);
        }
        return selected;
    }

    private void logRequest(RequestHeaders headers, SendJourneyEntryRequest request) {
        log.info("sendJourneyEntryToSap applicationName={}, transactionId={}, userId={}, journalEntryId={}, executionReason={}", headers != null ? headers.applicationName() : null,
                headers != null ? headers.transactionId() : null, headers != null ? headers.userId() : null, request != null ? request.getJournalEntryId() : null,
                request != null ? request.getExecutionReason() : null);
    }

    private String prefix(RequestHeaders headers) {
        String tx = headers != null ? headers.transactionId() : null;
        return tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
    }

    private <T> T ejecutarActividad(String menTran, String actividad, Supplier<T> accion) {
        try {
            ActivityLogger.inicioActividad(log, menTran, actividad);
            T result = accion.get();
            ActivityLogger.finActividad(log, menTran, actividad);
            return result;

        } catch (ServiceOperationException ex) {
            log.error("{} ERROR [{}] message={}", menTran, actividad, ex.getMessage());
            throw ex;

        } catch (Exception ex) {
            log.error("{} ERROR [{}] unexpected exception={}", menTran, actividad, ex.getMessage());
            throw ex;
        }
    }
}'''


def api():
    rows = ['    /**', '     * Envia un asiento contable a SAP segun el motivo de ejecucion indicado.', '     *', '     * @param request datos del asiento y motivo de ejecucion']
    rows += [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    rows += ['     * @return respuesta HTTP con el modelo JourneyEntryResponse definido en el contrato', '     */',
             '    @PostMapping(path = "/api/v1/orq-orq-accountManagement/send", consumes = {"application/json"}, produces = {"application/json"})',
             '    @Operation(summary = "Envia un asiento contable a SAP.")', '    @ApiResponses({',
             '      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = JourneyEntryResponse.class)))', '    })',
             '    ResponseEntity<JourneyEntryResponse> sendJourneyEntryToSap(']
    args = ['            @RequestBody SendJourneyEntryRequest request'] + [f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS]
    rows += [',\n'.join(args) + ');']
    return '/** Define el contrato del endpoint REST de envio de asientos contables a SAP (contrato OpenAPI). */\npublic interface JourneyEntryApi {\n' + '\n'.join(rows) + '\n}'


def controller():
    hdr = [f'            String {c}' for _, c, _ in dj.HEADERS]
    args = ',\n'.join(['            SendJourneyEntryRequest request'] + hdr)
    fwd = 'new ForwardedHeaders(traceparent, xAppId, xChannel, xClientVersionId, xCorrelationId, xRequestId, xUserId)'
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class JourneyEntryController implements JourneyEntryApi {', '    private final JourneyEntryService service;', '',
                      '    @Override', '    public ResponseEntity<JourneyEntryResponse> sendJourneyEntryToSap(', args + ') {',
                      '        log.info("sendJourneyEntryToSap - transactionId: {}", xCorrelationId);', '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);',
                      f'        return ResponseEntity.ok(service.sendJourneyEntryToSap(headers, {fwd}, request));', '    }', '}'])


def handler():
    text = dj.HANDLER
    text = re.sub(r'    private String operationMessage\(.*?\n    }\n\n    private String method',
                  '    private String operationMessage(String method, String uri, HttpStatus status) {\n        return "PROCESPOST_JOURNEY_ENTRY_SERVICE_ERROR";\n    }\n\n    private String method', text, flags=re.S)
    text = text.replace('Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.CONFLICT,', 'Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.NOT_FOUND,')
    text = re.sub(r'(case NOT_FOUND -> describe\(error, "ParameterValueNotFound", "IDF2", )"[^"]*"', lambda m: m.group(1) + '"No se encontr\u00f3 el asiento contable indicado."', text)
    return text


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    for cls, fields in REQUEST_DTOS.items():
        put('dto.request', cls, dj.dto(cls, fields))
    for cls, fields in RESPONSE_DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields, non_null=True))
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    for cls, fields in CLIENT_DTOS.items():
        put('client.dto', cls, dj.dto(cls, fields, non_null=cls.endswith('Request')))
    put('client.dto', 'JourneyEntryEnvelope', dj.envelope('JourneyEntryEnvelope', 'JourneyEntryData'))
    put('client.dto', 'ForwardedHeaders', FORWARDED_HEADERS)
    put('client', 'RemoteFailures', REMOTE_FAILURES)
    put('client', 'DomJourneyEntryClient', DOM_CLIENT_IF)
    put('client', 'DomJourneyEntryClientImpl', DOM_CLIENT_IMPL)
    put('client', 'SapClient', SAP_CLIENT_IF)
    put('client', 'SapClientImpl', SAP_CLIENT_IMPL)
    put('configuration', 'ClientConfig', CLIENT_CONFIG)
    put('configuration', 'StageSettings', STAGE_SETTINGS)
    put('configuration', 'StageSettingsConfig', STAGE_SETTINGS_CONFIG)
    put('configuration', 'ClockConfig', dj.CLOCK_CONFIG)
    put('dto.mapper', 'JourneyEntryMapper', MAPPER)
    put('dto.mapper', 'SapResponseReader', READER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', handler())
    put('service', 'JourneyEntryService', SERVICE_IF)
    put('service.impl', 'JourneyEntryServiceImpl', SERVICE_IMPL)
    put('validation', 'JourneyEntryValidator', VALIDATOR)
    put('controller', 'JourneyEntryApi', api())
    put('controller.impl', 'JourneyEntryController', controller())
    return files


ORIGINAL_CONSTANTS = dj.activity_constants


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False), ('ACT2_CONSULTAR_ASIENTO_CONTABLE', 'CONSULTAR_ASIENTO_CONTABLE', False),
                     ('ACT3_INVOCAR_RFC_1', 'INVOCAR_RFC_1', False), ('ACT4_REGISTRAR_ETAPA_1', 'REGISTRAR_ETAPA_1', False), ('ACT5_INVOCAR_RFC_2', 'INVOCAR_RFC_2', False),
                     ('ACT6_REGISTRAR_ETAPA_2', 'REGISTRAR_ETAPA_2', False)]
    try:
        return ORIGINAL_CONSTANTS()
    finally:
        dj.ACTIVITIES = saved


HEADER_CALLS = '''.header("traceparent", "t")
                .header("x-app-id", "app")
                .header("x-channel", "web")
                .header("x-client-version-id", "1")
                .header("x-correlation-id", "tx")
                .header("x-request-id", "req")
                .header("x-user-id", "user")'''

TESTS = {}
TESTS['JourneyEntryValidatorTest'] = ('validation', '''class JourneyEntryValidatorTest {
    private static final Long ID = 1234L;

    private final JourneyEntryValidator validator = new JourneyEntryValidator();

    private SendJourneyEntryRequest request(Long id, String reason) {
        SendJourneyEntryRequest request = new SendJourneyEntryRequest();
        request.setJournalEntryId(id);
        request.setExecutionReason(reason);
        return request;
    }

    @Test
    void acceptsTheDeclaredReasons() {
        for (String reason : new String[] {"INITIAL", "AUTOMATIC_RETRY", "MANUAL_RESEND"}) {
            validator.validate(request(ID, reason));
        }
    }

    @Test
    void rejectsMissingOrInvalidValues() {
        assertThrows(ServiceOperationException.class, () -> validator.validate(null));
        assertThrows(ServiceOperationException.class, () -> validator.validate(request(null, "INITIAL")));
        assertThrows(ServiceOperationException.class, () -> validator.validate(request(0L, "INITIAL")));
        assertThrows(ServiceOperationException.class, () -> validator.validate(request(ID, null)));
        assertThrows(ServiceOperationException.class, () -> validator.validate(request(ID, "OTHER")));
    }
}''')
TESTS['SapResponseReaderTest'] = ('dto.mapper', '''class SapResponseReaderTest {
    private final SapResponseReader reader = new SapResponseReader();

    @Test
    void readsTopLevelAndNestedValues() {
        assertEquals("P1", reader.find("{\\"pedido\\":\\"P1\\"}", "pedido"));
        assertEquals("E1", reader.find("{\\"itemDocCreados\\":{\\"entrega\\":\\"E1\\"}}", "entrega"));
    }

    @Test
    void absentOrInvalidBodiesGiveNull() {
        assertNull(reader.find(null, "pedido"));
        assertNull(reader.find(" ", "pedido"));
        assertNull(reader.find("not json", "pedido"));
        assertNull(reader.find("{\\"pedido\\":null}", "pedido"));
        assertNull(reader.find("{\\"pedido\\":{\\"a\\":1}}", "pedido"));
    }
}''')
TESTS['GlobalExceptionHandlerTest'] = ('exception', '''class GlobalExceptionHandlerTest {
    private static final String URI = "/api/v1/orq-orq-accountManagement/send";

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request() {
        return new ServletWebRequest(new MockHttpServletRequest("POST", URI));
    }

    @Test
    void badRequestUsesTheContractShapeAndTheOperationMessage() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request());
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF1", response.getBody().getSubType());
        assertEquals("PROCESPOST_JOURNEY_ENTRY_SERVICE_ERROR", response.getBody().getMessage());
    }

    @Test
    void notFoundAndTechnicalStatusesAreAllowed() {
        assertEquals(HttpStatus.NOT_FOUND.value(), handler.operationFailure(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"), request()).getStatusCode().value());
        assertEquals("IDT2", handler.operationFailure(new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, "down"), request()).getBody().getSubType());
        assertEquals("IDT1", handler.operationFailure(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"), request()).getBody().getSubType());
    }

    @Test
    void conflictIsNotDeclaredAndUnexpectedFailuresAreInternalErrors() {
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(),
                handler.operationFailure(new ServiceOperationException(HttpStatus.CONFLICT, "dup"), request()).getStatusCode().value());
        ResponseEntity<ErrorResponse> unexpected = handler.unexpectedFailure(new IllegalStateException("boom"), request());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), unexpected.getStatusCode().value());
        assertEquals("IDT3", unexpected.getBody().getSubType());
    }
}''')
TESTS['JourneyEntryServiceImplTest'] = ('service.impl', '''class JourneyEntryServiceImplTest {
    private static final Long ID = 1234L;
    private static final Integer FIRST_STATUS = 2;
    private static final Integer SECOND_STATUS = 3;
    private static final Integer PREVIOUS_ATTEMPT = 1;
    private static final String FIRST_RESPONSE = "{\\"pedido\\":\\"P1\\",\\"entrega\\":\\"E1\\",\\"factura\\":\\"F1\\"}";
    private static final String SECOND_RESPONSE = "{\\"ok\\":true}";

    private final DomJourneyEntryClient entries = Mockito.mock(DomJourneyEntryClient.class);
    private final SapClient sap = Mockito.mock(SapClient.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-12T10:15:30Z"), ZoneOffset.UTC);
    private final JourneyEntryServiceImpl service = new JourneyEntryServiceImpl(entries, sap, new JourneyEntryValidator(), new JourneyEntryMapper(), new SapResponseReader(),
            new StageSettings(FIRST_STATUS, SECOND_STATUS), clock);
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");
    private final ForwardedHeaders forwarded = new ForwardedHeaders("t", "app", "web", "1", "tx", "req", "user");

    private SendJourneyEntryRequest request() {
        SendJourneyEntryRequest request = new SendJourneyEntryRequest();
        request.setJournalEntryId(ID);
        request.setExecutionReason("INITIAL");
        return request;
    }

    private JourneyEntryData entry(String first, String second, String payload) {
        JourneyEntryData data = new JourneyEntryData();
        data.setJournalEntryId(ID);
        data.setFirstRequest(first);
        data.setSecondRequest(second);
        data.setEntryPayload(payload);
        data.setAttemptNumber(PREVIOUS_ATTEMPT);
        return data;
    }

    @Test
    void runsBothStagesInOrderAndRecordsEachOne() {
        Mockito.when(entries.getEntry(forwarded, ID)).thenReturn(entry("req1", null, "full"));
        Mockito.when(sap.registrarPedidoSinergia(forwarded, "req1")).thenReturn(FIRST_RESPONSE);
        Mockito.when(sap.registrarPagoSinergia(forwarded, "full")).thenReturn(SECOND_RESPONSE);
        JourneyEntryResponse response = service.sendJourneyEntryToSap(headers, forwarded, request());
        assertEquals(HttpStatus.OK.value(), response.getCode());
        InOrder order = Mockito.inOrder(entries, sap);
        ArgumentCaptor<JourneyEntryResultRequest> first = ArgumentCaptor.forClass(JourneyEntryResultRequest.class);
        ArgumentCaptor<JourneyEntryResultRequest> second = ArgumentCaptor.forClass(JourneyEntryResultRequest.class);
        order.verify(entries).getEntry(forwarded, ID);
        order.verify(sap).registrarPedidoSinergia(forwarded, "req1");
        order.verify(entries).updateResult(Mockito.eq(forwarded), Mockito.eq(ID), first.capture());
        order.verify(sap).registrarPagoSinergia(forwarded, "full");
        order.verify(entries).updateResult(Mockito.eq(forwarded), Mockito.eq(ID), second.capture());
        assertEquals("RFC_1", first.getValue().getStage());
        assertEquals(FIRST_STATUS, first.getValue().getJournalEntryStatusId());
        assertEquals("P1", first.getValue().getSapOrderNumber());
        assertEquals("E1", first.getValue().getSapDeliveryNumber());
        assertEquals("F1", first.getValue().getSapInvoiceNumber());
        assertEquals(FIRST_RESPONSE, first.getValue().getFirstResponse());
        assertEquals("2026-10-12T10:15:30Z", first.getValue().getAttemptStartedAt());
        assertEquals(Integer.valueOf(PREVIOUS_ATTEMPT + 1), first.getValue().getAttemptNumber());
        assertEquals("RFC_2", second.getValue().getStage());
        assertEquals(SECOND_STATUS, second.getValue().getJournalEntryStatusId());
        assertEquals(SECOND_RESPONSE, second.getValue().getSecondResponse());
    }

    @Test
    void invalidRequestsStopBeforeAnyCall() {
        SendJourneyEntryRequest invalid = request();
        invalid.setExecutionReason("OTHER");
        assertThrows(ServiceOperationException.class, () -> service.sendJourneyEntryToSap(headers, forwarded, invalid));
        Mockito.verifyNoInteractions(entries, sap);
    }

    @Test
    void aFirstCallFailureDoesNotRecordAnyStage() {
        Mockito.when(entries.getEntry(forwarded, ID)).thenReturn(entry("req1", "req2", null));
        Mockito.when(sap.registrarPedidoSinergia(forwarded, "req1")).thenThrow(new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, "down"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.sendJourneyEntryToSap(headers, forwarded, request()));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, failure.getStatus());
        Mockito.verify(entries, Mockito.never()).updateResult(Mockito.any(), Mockito.any(), Mockito.any());
    }

    @Test
    void aSecondCallFailureKeepsTheFirstStageRecorded() {
        Mockito.when(entries.getEntry(forwarded, ID)).thenReturn(entry("req1", "req2", null));
        Mockito.when(sap.registrarPedidoSinergia(forwarded, "req1")).thenReturn(FIRST_RESPONSE);
        Mockito.when(sap.registrarPagoSinergia(forwarded, "req2")).thenThrow(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"));
        assertThrows(ServiceOperationException.class, () -> service.sendJourneyEntryToSap(headers, forwarded, request()));
        Mockito.verify(entries, Mockito.times(1)).updateResult(Mockito.eq(forwarded), Mockito.eq(ID), Mockito.any());
    }

    @Test
    void anEntryWithoutPayloadIsAnInternalError() {
        Mockito.when(entries.getEntry(forwarded, ID)).thenReturn(entry(" ", null, null));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.sendJourneyEntryToSap(headers, forwarded, request()));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, failure.getStatus());
        Mockito.verifyNoInteractions(sap);
    }

    @Test
    void aMissingAttemptNumberStartsAtOneAndHeadersMayBeAbsent() {
        JourneyEntryData data = entry("req1", "req2", null);
        data.setAttemptNumber(null);
        Mockito.when(entries.getEntry(forwarded, ID)).thenReturn(data);
        Mockito.when(sap.registrarPedidoSinergia(forwarded, "req1")).thenReturn("");
        Mockito.when(sap.registrarPagoSinergia(forwarded, "req2")).thenReturn("");
        service.sendJourneyEntryToSap(null, forwarded, request());
        ArgumentCaptor<JourneyEntryResultRequest> captor = ArgumentCaptor.forClass(JourneyEntryResultRequest.class);
        Mockito.verify(entries, Mockito.times(2)).updateResult(Mockito.eq(forwarded), Mockito.eq(ID), captor.capture());
        assertEquals(Integer.valueOf(1), captor.getAllValues().get(0).getAttemptNumber());
        assertNull(captor.getAllValues().get(0).getSapOrderNumber());
    }
}''')
TESTS['DomJourneyEntryClientImplTest'] = ('client', '''class DomJourneyEntryClientImplTest {
    private static final String URL = "http://dom/api/v1/dom-journeyEntry/1234";
    private static final Long ID = 1234L;

    private final RestClient.Builder builder = RestClient.builder().baseUrl("http://dom");
    private final MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    private final DomJourneyEntryClientImpl client = new DomJourneyEntryClientImpl(builder.build());
    private final ForwardedHeaders headers = new ForwardedHeaders("t", "app", "web", "1", "tx", "req", null);

    @Test
    void getsTheEntryForwardingTheHeaders() {
        server.expect(requestTo(URL)).andExpect(method(HttpMethod.GET)).andExpect(header("x-correlation-id", "tx"))
                .andRespond(withSuccess("{\\"code\\":200,\\"data\\":{\\"journalEntryId\\":1234,\\"attemptNumber\\":2,\\"unknown\\":\\"x\\"}}", MediaType.APPLICATION_JSON));
        JourneyEntryData data = client.getEntry(headers, ID);
        assertEquals(ID, data.getJournalEntryId());
        server.verify();
    }

    @Test
    void anEmptyEnvelopeIsAnInternalError() {
        server.expect(requestTo(URL)).andRespond(withSuccess("{\\"code\\":200}", MediaType.APPLICATION_JSON));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> client.getEntry(headers, ID)).getStatus());
    }

    @Test
    void patchesTheResultAsJson() {
        server.expect(requestTo(URL)).andExpect(method(HttpMethod.PATCH)).andExpect(content().json("{\\"stage\\":\\"RFC_1\\",\\"journalEntryStatusId\\":2}")).andRespond(withSuccess());
        JourneyEntryResultRequest result = new JourneyEntryResultRequest();
        result.setStage("RFC_1");
        result.setJournalEntryStatusId(2);
        client.updateResult(headers, ID, result);
        server.verify();
    }

    @Test
    void remoteFailuresAreMappedToTheTechnicalStatuses() {
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.NOT_FOUND));
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> client.getEntry(headers, ID)).getStatus());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.BAD_GATEWAY));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, assertThrows(ServiceOperationException.class, () -> client.getEntry(headers, ID)).getStatus());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.GATEWAY_TIMEOUT));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> client.getEntry(headers, ID)).getStatus());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.BAD_REQUEST));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> client.getEntry(headers, ID)).getStatus());
    }

    @Test
    void connectionFailuresAreUnavailableAndSocketTimeoutsAreGatewayTimeouts() {
        server.expect(requestTo(URL)).andRespond(withException(new IOException("refused")));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, assertThrows(ServiceOperationException.class, () -> client.getEntry(headers, ID)).getStatus());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withException(new SocketTimeoutException("slow")));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> client.updateResult(headers, ID, new JourneyEntryResultRequest())).getStatus());
    }
}''')
TESTS['SapClientImplTest'] = ('client', '''class SapClientImplTest {
    private static final String ORDER_URL = "http://osb/order";
    private static final String PAYMENT_URL = "http://osb/payment";

    private final RestClient.Builder builder = RestClient.builder().baseUrl("http://osb");
    private final MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    private final SapClientImpl client = new SapClientImpl(builder.build(), "/order", "/payment");
    private final ForwardedHeaders headers = new ForwardedHeaders("t", "app", "web", "1", "tx", "req", "user");

    @Test
    void postsThePayloadsToTheConfiguredPaths() {
        server.expect(requestTo(ORDER_URL)).andExpect(method(HttpMethod.POST)).andExpect(header("x-user-id", "user")).andExpect(content().json("{\\"a\\":1}"))
                .andRespond(withSuccess("{\\"pedido\\":\\"P1\\"}", MediaType.APPLICATION_JSON));
        server.expect(requestTo(PAYMENT_URL)).andExpect(method(HttpMethod.POST)).andRespond(withSuccess());
        assertEquals("{\\"pedido\\":\\"P1\\"}", client.registrarPedidoSinergia(headers, "{\\"a\\":1}"));
        assertEquals("", client.registrarPagoSinergia(headers, "{\\"b\\":2}"));
        server.verify();
    }

    @Test
    void gatewayFailuresAreMappedAndNotFoundIsNotABusinessError() {
        server.expect(requestTo(ORDER_URL)).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, assertThrows(ServiceOperationException.class, () -> client.registrarPedidoSinergia(headers, "{}")).getStatus());
        server.reset();
        server.expect(requestTo(ORDER_URL)).andRespond(withStatus(HttpStatus.GATEWAY_TIMEOUT));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> client.registrarPedidoSinergia(headers, "{}")).getStatus());
        server.reset();
        server.expect(requestTo(PAYMENT_URL)).andRespond(withStatus(HttpStatus.NOT_FOUND));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> client.registrarPagoSinergia(headers, "{}")).getStatus());
    }

    @Test
    void timeoutsAreGatewayTimeouts() {
        server.expect(requestTo(ORDER_URL)).andRespond(withException(new SocketTimeoutException("slow")));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> client.registrarPedidoSinergia(headers, "{}")).getStatus());
    }
}''')
TESTS['JourneyEntryApiContractTest'] = ('controller', '''class JourneyEntryApiContractTest {
    private static final String PATH = "/api/v1/orq-orq-accountManagement/send";

    private final JourneyEntryService service = Mockito.mock(JourneyEntryService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new JourneyEntryController(service))
            .setControllerAdvice(new GlobalExceptionHandler(new PersistenceExceptionTranslator()))
            .build();

    private MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder) {
        return builder__HEADERS__;
    }

    @Test
    void postReturnsTheEnvelope() throws Exception {
        Mockito.when(service.sendJourneyEntryToSap(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class),
                ArgumentMatchers.any(SendJourneyEntryRequest.class))).thenReturn(new JourneyEntryMapper().success());
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("{\\"journalEntryId\\": 1234, \\"executionReason\\": \\"INITIAL\\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(HttpStatus.OK.value()));
    }

    @Test
    void failuresAndMissingHeadersUseTheContractErrors() throws Exception {
        Mockito.when(service.sendJourneyEntryToSap(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class),
                ArgumentMatchers.any(SendJourneyEntryRequest.class))).thenThrow(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"));
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isGatewayTimeout()).andExpect(jsonPath("$.subType").value("IDT1"));
        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.subType").value("IDF1"));
    }
}'''.replace('__HEADERS__', HEADER_CALLS))

MOCK_REST = ['org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo', 'org.springframework.test.web.client.match.MockRestRequestMatchers.method',
             'org.springframework.test.web.client.match.MockRestRequestMatchers.header', 'org.springframework.test.web.client.match.MockRestRequestMatchers.content',
             'org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess', 'org.springframework.test.web.client.response.MockRestResponseCreators.withStatus',
             'org.springframework.test.web.client.response.MockRestResponseCreators.withException']


def build_tests(pkg):
    import dom_cpe_request_tests as dt
    files = {}
    for name, (suffix, body) in TESTS.items():
        statics = list(dt.MVC_STATICS) if name.endswith('ContractTest') else dt.ASSERT + (MOCK_REST if name.endswith('ClientImplTest') else [])
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.orq.journeyentry and application class OrqJourneyEntryApplication are technical choices; no source defines them. The service accesses no database (Sparx lists no tables).'),
    ('A-02', 'Only the 200 response is declared by the OpenAPI (swagger-governs); the Sparx 400/404/409/5xx end events are not contract. Technical failures use the archetype error shape with 400/404/500/503/504 and the message PROCESPOST_JOURNEY_ENTRY_SERVICE_ERROR; no 401/403 handling and no 409/502 (409 becomes 500).'),
    ('A-03', 'The eligibility check of Sparx activity 3 (journal entry status/stage validation) has no defined rule and is not implemented; every valid request is processed whatever executionReason (INITIAL, AUTOMATIC_RETRY, MANUAL_RESEND) it carries.'),
    ('A-04', 'The OSB/SAP contract (URL, payloads, response shape) is not defined by the sources: registrarPedidoSinergia and registrarPagoSinergia are called as POST application/json with base URL osb.base-url (default http://osb), paths osb.registrar-pedido-path/registrar-pago-path and timeout osb.timeout-ms. The body is the stored firstRequest / secondRequest of the entry (entryPayload when empty). The raw answer is stored as firstResponse/secondResponse.'),
    ('A-05', 'SAP numbers are read from the answer as pedido, entrega and factura (top level or itemDocCreados). The accounting document number of RFC_2 has no defined origin and is not sent. The success criterion of an RFC call is an HTTP 2xx answer; the normalization/classification of Sparx activities 5 and 8 is not defined and is not implemented.'),
    ('A-06', 'dom-journeyEntry is called at dom-journey-entry.base-url (default http://dom-journeyentry, timeout dom-journey-entry.timeout-ms): GET and PATCH /api/v1/dom-journeyEntry/{id}. Its data object (Swagger) is read, not the data array of Sparx. All seven received headers are forwarded to both dependencies.'),
    ('A-07', 'Stage values follow the dom-journeyEntry example: stage RFC_1/RFC_2, expectedStatus LLAMADO_1_COMPLETO/LLAMADO_2_COMPLETO (the second one is by analogy). journalEntryStatusId after each call is the parameter journey-entry.status-after-first-call (default 2) / status-after-second-call (default 3); the real status catalog must be confirmed. attemptNumber = current attempt + 1 and attemptStartedAt comes from the injectable Clock (UTC).'),
    ('A-08', 'Remote failures: connection errors, 502 and 503 -> 503; timeouts and 504/408 -> 504; dom-journeyEntry 404 -> 404; any other remote status -> 500. If the second call fails the first stage stays recorded (no compensation is defined).'),
]


def main(argv=None):
    sys.modules['dom_invoice_java'] = types.SimpleNamespace()
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, 'OrqJourneyEntryApplication', ASSUMPTIONS, 'orq-journey-entry-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': 'OrqJourneyEntryApplication'}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'orq_journey_entry_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main(argv) if argv is not None else dm.main()


if __name__ == '__main__':
    sys.exit(main())
