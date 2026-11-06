"""Deterministic materializer of the sod-customerBillStatus service (JPA profile of claro-spring-ms).

Two PATCH operations update FACEL.EPDREQUEST and register the history snapshot through the emission-cpehist HTTP service; the POST non transient error
operation has no authoritative Sparx logic and is generated as an explicit, documented failure (never invented persistence).

Usage: python sod_customer_bill_status_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import re
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402

PACKAGE = 'com.claro.sod.customerbillstatus'
for _name, _fqcn in {
        'ArgumentCaptor': 'org.mockito.ArgumentCaptor', 'InOrder': 'org.mockito.InOrder', 'MockHttpServletRequestBuilder': 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder',
        'RestClient': 'org.springframework.web.client.RestClient', 'SimpleClientHttpRequestFactory': 'org.springframework.http.client.SimpleClientHttpRequestFactory',
        'ResourceAccessException': 'org.springframework.web.client.ResourceAccessException', 'RestClientResponseException': 'org.springframework.web.client.RestClientResponseException',
        'SocketTimeoutException': 'java.net.SocketTimeoutException', 'IOException': 'java.io.IOException', 'MockRestServiceServer': 'org.springframework.test.web.client.MockRestServiceServer',
        'JsonProcessingException': 'com.fasterxml.jackson.core.JsonProcessingException', 'Objects': 'java.util.Objects', 'OffsetDateTime': 'java.time.OffsetDateTime',
        'DateTimeParseException': 'java.time.format.DateTimeParseException', 'MediaType': 'org.springframework.http.MediaType', 'HttpMethod': 'org.springframework.http.HttpMethod'}.items():
    dj.EXTERNAL.setdefault(_name, _fqcn)

ENTITIES = {
    'EpdRequestEntity': ('EPDREQUEST', [
        ('Long', 'id', 'ID', 'id'), ('String', 'series', 'SERIES', ''), ('Long', 'correlative', 'CORRELATIVE', ''), ('Integer', 'epdTypeId', 'EPDTYPEID', ''),
        ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''), ('String', 'inputPayload', 'INPUTPAYLOAD', 'lob'),
        ('String', 'installmentSchedulePayload', 'INSTALLMENTSCHEDULEPAYLOAD', 'lob'), ('Integer', 'attemptNumber', 'ATTEMPTNUMBER', ''),
        ('Integer', 'disagreementFlag', 'DISAGREEMENTFLAG', ''), ('String', 'lastModifiedUser', 'LASTMODIFIEDUSER', ''),
        ('LocalDateTime', 'lastModifiedDate', 'LASTMODIFIEDDATE', '')]),
    'DocumentTypeEntity': ('ELECTRONICDOCUMENTTYPE', [('Long', 'id', 'ID', 'id'), ('String', 'sunatDocumentTypeCode', 'SUNATDOCUMENTTYPECODE', '')]),
}
REQUEST_DTOS = {
    'UpdateCustomerBillStatusRequest': [('Long', 'id'), ('Integer', 'epdQueryStatusId'), ('String', 'plotsovos'), ('String', 'installmentsSchedulePayload'),
                                        ('Integer', 'attemptNumber'), ('Integer', 'disagreementFlag'), ('String', 'lastModifiedUser')],
    'UpdateCpeDisagreementRequest': [('Boolean', 'disagreementFlag')],
}
DTOS = {
    'UpdateCustomerBillStatusData': [('Integer', 'updated')],
    'UpdateCpeDisagreementData': [('Long', 'id'), ('Long', 'epdRequestId'), ('LocalDateTime', 'snapshotDate')],
    'CreateNonTransientErrorData': [('Long', 'generatedId')],
}
RESPONSES = {'UpdateCustomerBillStatusResponse': 'UpdateCustomerBillStatusData', 'UpdateCpeDisagreementResponse': 'UpdateCpeDisagreementData',
             'CreateNonTransientErrorResponse': 'CreateNonTransientErrorData'}
CLIENT_DTOS = {'EmissionCpeHistRequest': [('Long', 'epdRequestId')], 'EmissionCpeHistData': [('Long', 'id'), ('Long', 'epdRequestId'), ('String', 'snapshotDate')]}
dj.register('model', *ENTITIES)
dj.register('dto.request', *REQUEST_DTOS)
dj.register('dto.response', *DTOS, *RESPONSES)
dj.register('dto.mapper', 'CustomerBillStatusMapper')
dj.register('repository', 'EpdRequestRepository', 'DocumentTypeRepository')
dj.register('service', 'CustomerBillStatusService')
dj.register('service.impl', 'CustomerBillStatusServiceImpl')
dj.register('validation', 'CustomerBillStatusValidator')
dj.register('controller', 'CustomerBillStatusApi')
dj.register('controller.impl', 'CustomerBillStatusController')
dj.register('client', 'EmissionCpeHistClient', 'EmissionCpeHistClientImpl')
dj.register('client.dto', 'EmissionCpeHistRequest', 'EmissionCpeHistData', 'EmissionCpeHistResponse', 'ForwardedHeaders')

REPOS = {
    'EpdRequestRepository': '''@Repository
public interface EpdRequestRepository extends JpaRepository<EpdRequestEntity, Long> {
    List<EpdRequestEntity> findBySeriesAndCorrelativeAndEpdTypeId(String series, Long correlative, Integer epdTypeId);
}''',
    'DocumentTypeRepository': '''@Repository
public interface DocumentTypeRepository extends JpaRepository<DocumentTypeEntity, Long> {
    Optional<DocumentTypeEntity> findBySunatDocumentTypeCode(String sunatDocumentTypeCode);
}''',
}

FORWARDED_HEADERS = '''/** Headers received by the API that are forwarded to the history service. */
public record ForwardedHeaders(String traceparent, String xAppId, String xChannel, String xClientVersionId, String xCorrelationId, String xRequestId, String xUserId) {
}'''

CLIENT_IF = '''/** Client of the emission-cpehist service that registers the history snapshot of a CPE request. */
public interface EmissionCpeHistClient {
    EmissionCpeHistData createSnapshot(ForwardedHeaders headers, Long epdRequestId);
}'''

CLIENT_IMPL = '''/** HTTP client of emission-cpehist POST /api/v1/emisioneshist; failures become the technical statuses declared by the contract. */
@Component
@RequiredArgsConstructor
@Slf4j
public class EmissionCpeHistClientImpl implements EmissionCpeHistClient {
    private static final String PATH = "/api/v1/emisioneshist";
    private static final String UNAVAILABLE_DETAIL = "El servicio emission-cpehist no se encuentra disponible.";
    private static final String TIMEOUT_DETAIL = "El servicio emission-cpehist no respondi\\u00f3 a tiempo.";
    private static final String FAILURE_DETAIL = "El servicio emission-cpehist devolvi\\u00f3 una respuesta no v\\u00e1lida.";

    private final RestClient restClient;

    @Override
    public EmissionCpeHistData createSnapshot(ForwardedHeaders headers, Long epdRequestId) {
        EmissionCpeHistRequest body = new EmissionCpeHistRequest();
        body.setEpdRequestId(epdRequestId);
        try {
            EmissionCpeHistResponse response = restClient.post()
                    .uri(PATH)
                    .contentType(MediaType.APPLICATION_JSON)
                    .headers(target -> {
                        put(target, "traceparent", headers.traceparent());
                        put(target, "x-app-id", headers.xAppId());
                        put(target, "x-channel", headers.xChannel());
                        put(target, "x-client-version-id", headers.xClientVersionId());
                        put(target, "x-correlation-id", headers.xCorrelationId());
                        put(target, "x-request-id", headers.xRequestId());
                        put(target, "x-user-id", headers.xUserId());
                    })
                    .body(body)
                    .retrieve()
                    .body(EmissionCpeHistResponse.class);
            if (response == null || response.getData() == null || response.getData().getId() == null) {
                throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, FAILURE_DETAIL);
            }
            return response.getData();
        } catch (ResourceAccessException e) {
            log.error("emission-cpehist no accesible: {}", e.getMessage());
            throw new ServiceOperationException(timedOut(e) ? HttpStatus.GATEWAY_TIMEOUT : HttpStatus.SERVICE_UNAVAILABLE, timedOut(e) ? TIMEOUT_DETAIL : UNAVAILABLE_DETAIL);
        } catch (RestClientResponseException e) {
            int code = e.getStatusCode().value();
            log.error("emission-cpehist respondio con estado {}", code);
            if (code == HttpStatus.GATEWAY_TIMEOUT.value() || code == HttpStatus.REQUEST_TIMEOUT.value()) {
                throw new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, TIMEOUT_DETAIL);
            }
            if (code == HttpStatus.SERVICE_UNAVAILABLE.value() || code == HttpStatus.BAD_GATEWAY.value()) {
                throw new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, UNAVAILABLE_DETAIL);
            }
            throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, FAILURE_DETAIL);
        }
    }

    private static void put(HttpHeaders target, String name, String value) {
        if (value != null) {
            target.set(name, value);
        }
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

CLIENT_CONFIG = '''/** HTTP client configuration of the emission-cpehist dependency (base URL and timeout are environment parameters). */
@Configuration
public class EmissionCpeHistClientConfig {
    @Bean
    public RestClient emissionCpeHistRestClient(
            @Value("${emission-cpehist.base-url:http://emission-cpehist}") String baseUrl,
            @Value("${emission-cpehist.timeout-ms:5000}") int timeoutMs) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeoutMs);
        factory.setReadTimeout(timeoutMs);
        return RestClient.builder().baseUrl(baseUrl).requestFactory(factory).build();
    }
}'''

TRANSACTION_CONFIG = '''/** Programmatic transaction boundary used for the single-table update. */
@Configuration
public class TransactionConfig {
    @Bean
    public TransactionTemplate transactionTemplate(PlatformTransactionManager manager) {
        return new TransactionTemplate(manager);
    }
}'''

SERVICE_IF = '''/** Actualizacion de estado y disconformidad de solicitudes CPE. */
public interface CustomerBillStatusService {
    UpdateCustomerBillStatusResponse updateCustomerBillStatus(RequestHeaders headers, ForwardedHeaders forwarded, UpdateCustomerBillStatusRequest request);

    UpdateCpeDisagreementResponse updateCpeDisagreement(RequestHeaders headers, ForwardedHeaders forwarded, String documentType, String series, Long sequential,
            UpdateCpeDisagreementRequest request);

    CreateNonTransientErrorResponse createNonTransientError(RequestHeaders headers, Long epdRequestId, String messagePayload, String creationUser);
}'''

VALIDATOR = '''/** Declared contract rules of the three operations. */
@Component
public class CustomerBillStatusValidator {
    private static final String INVALID = "Par\\u00e1metros obligatorios incompletos o con valores no v\\u00e1lidos.";
    private static final int FLAG_ON = 1;
    private static final int FLAG_OFF = 0;

    private final ObjectMapper json = new ObjectMapper();

    public void statusUpdate(UpdateCustomerBillStatusRequest request) {
        if (request == null || request.getId() == null || request.getId() <= 0 || blank(request.getLastModifiedUser())) {
            throw ServiceOperationException.badRequest(INVALID);
        }
        Integer flag = request.getDisagreementFlag();
        if (flag != null && flag != FLAG_ON && flag != FLAG_OFF) {
            throw ServiceOperationException.badRequest(INVALID);
        }
        validJson(request.getPlotsovos());
        validJson(request.getInstallmentsSchedulePayload());
    }

    public boolean disagreement(String documentType, String series, Long sequential, UpdateCpeDisagreementRequest request) {
        if (blank(documentType) || blank(series) || sequential == null || sequential <= 0 || request == null || request.getDisagreementFlag() == null) {
            throw ServiceOperationException.badRequest(INVALID);
        }
        return request.getDisagreementFlag();
    }

    public void nonTransientError(Long epdRequestId, String messagePayload, String creationUser) {
        if (epdRequestId == null || epdRequestId <= 0 || blank(messagePayload) || blank(creationUser)) {
            throw ServiceOperationException.badRequest(INVALID);
        }
    }

    private void validJson(String text) {
        if (text == null) {
            return;
        }
        try {
            json.readTree(text);
        } catch (JsonProcessingException e) {
            throw ServiceOperationException.badRequest(INVALID);
        }
    }

    private boolean blank(String text) {
        return text == null || text.isBlank();
    }
}'''

MAPPER = '''/** Explicit mapping between rows, history service data and the API contract. */
@Component
public class CustomerBillStatusMapper {
    private static final String SUCCESS_MESSAGE = "Operaci\\u00f3n exitosa";

    public UpdateCustomerBillStatusResponse statusResponse(int updated) {
        UpdateCustomerBillStatusData data = new UpdateCustomerBillStatusData();
        data.setUpdated(updated);
        UpdateCustomerBillStatusResponse response = new UpdateCustomerBillStatusResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    public UpdateCpeDisagreementResponse disagreementResponse(Long epdRequestId, EmissionCpeHistData history) {
        UpdateCpeDisagreementData data = new UpdateCpeDisagreementData();
        data.setEpdRequestId(epdRequestId);
        if (history != null) {
            data.setId(history.getId());
            data.setSnapshotDate(parse(history.getSnapshotDate()));
        }
        UpdateCpeDisagreementResponse response = new UpdateCpeDisagreementResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private LocalDateTime parse(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return OffsetDateTime.parse(text).toLocalDateTime();
        } catch (DateTimeParseException offsetless) {
            try {
                return LocalDateTime.parse(text);
            } catch (DateTimeParseException invalid) {
                return null;
            }
        }
    }
}'''

SERVICE_IMPL = '''/** Activity-logged service; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class CustomerBillStatusServiceImpl implements CustomerBillStatusService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String REQUEST_NOT_FOUND = "No se encontr\\u00f3 la solicitud CPE indicada.";
    private static final String CPE_NOT_FOUND = "No se encontr\\u00f3 el comprobante de pago electr\\u00f3nico indicado.";
    private static final String AMBIGUOUS_CPE = "Existe m\\u00e1s de un comprobante de pago electr\\u00f3nico con los datos indicados.";
    private static final String NOT_SPECIFIED = "La operaci\\u00f3n no tiene l\\u00f3gica de negocio definida en la especificaci\\u00f3n funcional.";
    private static final int ONE_ROW = 1;
    private static final int FLAG_ON = 1;
    private static final int FLAG_OFF = 0;

    private final EpdRequestRepository requests;
    private final DocumentTypeRepository documentTypes;
    private final EmissionCpeHistClient historyClient;
    private final CustomerBillStatusMapper mapper;
    private final CustomerBillStatusValidator validator;
    private final PersistenceExceptionTranslator translator;
    private final TransactionTemplate transaction;
    private final Clock clock;

    @Override
    public UpdateCustomerBillStatusResponse updateCustomerBillStatus(RequestHeaders headers, ForwardedHeaders forwarded, UpdateCustomerBillStatusRequest request) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> {
            logRequest("updateCustomerBillStatus", headers);
            validator.statusUpdate(request);
            return Boolean.TRUE;
        });
        EpdRequestEntity current = ejecutarActividad(menTran, ConstanApi.ACT2_BUSCAR_SOLICITUD_CPE, () -> buscarPorId(menTran, request.getId()));
        ejecutarActividad(menTran, ConstanApi.ACT3_REGISTRAR_SNAPSHOT_HISTORICO, () -> {
            boolean statusChanges = request.getEpdQueryStatusId() != null && !Objects.equals(request.getEpdQueryStatusId(), current.getEpdQueryStatusId());
            return statusChanges ? historyClient.createSnapshot(forwarded, current.getId()) : null;
        });
        int updated = ejecutarActividad(menTran, ConstanApi.ACT4_ACTUALIZAR_SOLICITUD, () -> actualizarEstado(menTran, request, current));
        return mapper.statusResponse(updated);
    }

    @Override
    public UpdateCpeDisagreementResponse updateCpeDisagreement(RequestHeaders headers, ForwardedHeaders forwarded, String documentType, String series, Long sequential,
            UpdateCpeDisagreementRequest request) {
        String menTran = prefix(headers);
        boolean requested = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> {
            logRequest("updateCpeDisagreement", headers);
            return validator.disagreement(documentType, series, sequential, request);
        });
        EpdRequestEntity current = ejecutarActividad(menTran, ConstanApi.ACT2_BUSCAR_SOLICITUD_CPE, () -> buscarCpe(menTran, documentType, series, sequential));
        int target = requested ? FLAG_ON : FLAG_OFF;
        if (current.getDisagreementFlag() != null && current.getDisagreementFlag() == target) {
            return mapper.disagreementResponse(current.getId(), null);
        }
        EmissionCpeHistData history = ejecutarActividad(menTran, ConstanApi.ACT3_REGISTRAR_SNAPSHOT_HISTORICO, () -> historyClient.createSnapshot(forwarded, current.getId()));
        ejecutarActividad(menTran, ConstanApi.ACT4_ACTUALIZAR_SOLICITUD, () -> actualizarDisconformidad(menTran, headers, current, target));
        return mapper.disagreementResponse(current.getId(), history);
    }

    @Override
    public CreateNonTransientErrorResponse createNonTransientError(RequestHeaders headers, Long epdRequestId, String messagePayload, String creationUser) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> {
            logRequest("createNonTransientError", headers);
            validator.nonTransientError(epdRequestId, messagePayload, creationUser);
            return Boolean.TRUE;
        });
        log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, HttpStatus.INTERNAL_SERVER_ERROR.value(), NOT_SPECIFIED);
        throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, NOT_SPECIFIED);
    }

    private void logRequest(String operation, RequestHeaders headers) {
        log.info("{} applicationName={}, transactionId={}, userId={}", operation, headers != null ? headers.applicationName() : null,
                headers != null ? headers.transactionId() : null, headers != null ? headers.userId() : null);
    }

    private EpdRequestEntity buscarPorId(String menTran, Long id) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_BUSCAR_SOLICITUD_CPE, ConstanApi.LOG_ERROR_DATOS_ACT2_BUSCAR_SOLICITUD_CPE, () -> requests.findById(id).orElseThrow(() -> {
            log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT2_BUSCAR_SOLICITUD_CPE, HttpStatus.NOT_FOUND.value(), REQUEST_NOT_FOUND);
            return new ServiceOperationException(HttpStatus.NOT_FOUND, REQUEST_NOT_FOUND);
        }));
    }

    private EpdRequestEntity buscarCpe(String menTran, String documentType, String series, Long sequential) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_BUSCAR_SOLICITUD_CPE, ConstanApi.LOG_ERROR_DATOS_ACT2_BUSCAR_SOLICITUD_CPE, () -> {
            DocumentTypeEntity type = documentTypes.findBySunatDocumentTypeCode(documentType).orElseThrow(() -> notFound(menTran));
            List<EpdRequestEntity> found = requests.findBySeriesAndCorrelativeAndEpdTypeId(series, sequential, type.getId().intValue());
            if (found.isEmpty()) {
                throw notFound(menTran);
            }
            if (found.size() > ONE_ROW) {
                log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT2_BUSCAR_SOLICITUD_CPE, HttpStatus.INTERNAL_SERVER_ERROR.value(), AMBIGUOUS_CPE);
                throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, AMBIGUOUS_CPE);
            }
            return found.get(0);
        });
    }

    private ServiceOperationException notFound(String menTran) {
        log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT2_BUSCAR_SOLICITUD_CPE, HttpStatus.NOT_FOUND.value(), CPE_NOT_FOUND);
        return new ServiceOperationException(HttpStatus.NOT_FOUND, CPE_NOT_FOUND);
    }

    private Integer actualizarEstado(String menTran, UpdateCustomerBillStatusRequest request, EpdRequestEntity current) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT4_ACTUALIZAR_SOLICITUD, ConstanApi.LOG_ERROR_DATOS_ACT4_ACTUALIZAR_SOLICITUD, () -> transaction.execute(status -> {
            if (request.getEpdQueryStatusId() != null) {
                current.setEpdQueryStatusId(request.getEpdQueryStatusId());
            }
            if (request.getPlotsovos() != null) {
                current.setInputPayload(request.getPlotsovos());
            }
            if (request.getInstallmentsSchedulePayload() != null) {
                current.setInstallmentSchedulePayload(request.getInstallmentsSchedulePayload());
            }
            if (request.getAttemptNumber() != null) {
                current.setAttemptNumber(request.getAttemptNumber());
            }
            if (request.getDisagreementFlag() != null) {
                current.setDisagreementFlag(request.getDisagreementFlag());
            }
            current.setLastModifiedUser(request.getLastModifiedUser());
            current.setLastModifiedDate(LocalDateTime.now(clock));
            requests.save(current);
            return ONE_ROW;
        }));
    }

    private Integer actualizarDisconformidad(String menTran, RequestHeaders headers, EpdRequestEntity current, int target) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT4_ACTUALIZAR_SOLICITUD, ConstanApi.LOG_ERROR_DATOS_ACT4_ACTUALIZAR_SOLICITUD, () -> transaction.execute(status -> {
            current.setDisagreementFlag(target);
            current.setLastModifiedUser(headers != null ? headers.userId() : null);
            current.setLastModifiedDate(LocalDateTime.now(clock));
            requests.save(current);
            return ONE_ROW;
        }));
    }

    private String prefix(RequestHeaders headers) {
        String tx = headers != null ? headers.transactionId() : null;
        return tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
    }

    private <T> T accederDatos(String menTran, String logTimeout, String logErrorDatos, Supplier<T> acceso) {
        try {
            return acceso.get();

        } catch (QueryTimeoutException e) {
            log.error(ERROR_TECHNICAL_PATTERN, menTran, logTimeout, e.getMessage());
            throw translator.translate(e);

        } catch (DataAccessException e) {
            log.error(ERROR_TECHNICAL_PATTERN, menTran, logErrorDatos, e.getMessage());
            throw translator.translate(e);
        }
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


def responses(codes, resp):
    rows = [f'      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = {resp}.class)))']
    rows += [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS[c]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for c in codes]
    return ',\n'.join(rows)


def api_op(name, summary, mapping, resp, params, codes):
    """params: list of (docName, declaration)."""
    out = ['    /**', f'     * {summary}', '     *']
    out += [f'     * @param {n} parametro {n}' for n, _ in params]
    out += [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    out += [f'     * @return respuesta HTTP con el modelo {resp} definido en el contrato', '     */', f'    {mapping}', f'    @Operation(summary = "{summary}")', '    @ApiResponses({',
            responses(codes, resp), '    })', f'    ResponseEntity<{resp}> {name}(']
    args = [f'            {d}' for _, d in params] + [f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS]
    out += [',\n'.join(args) + ');']
    return '\n'.join(out)


def api():
    ops = [
        api_op('updateCustomerBillStatus', 'Actualiza el estado y los datos complementarios de una solicitud CPE.',
               '@PatchMapping(path = "/api/v1/sod-customerBillStatus", consumes = {"application/json"}, produces = {"application/json"})', 'UpdateCustomerBillStatusResponse',
               [('request', '@RequestBody UpdateCustomerBillStatusRequest request')], ('400', '404', '409', '500', '503', '504')),
        api_op('updateCpeDisagreement', 'Marca o revierte la disconformidad de un CPE.',
               '@PatchMapping(path = "/api/v1/sod-customerBillStatus/{documentType}/{series}/{sequential}/disagreement", consumes = {"application/json"}, produces = {"application/json"})',
               'UpdateCpeDisagreementResponse',
               [('documentType', '@PathVariable("documentType") String documentType'), ('series', '@PathVariable("series") String series'),
                ('sequential', '@PathVariable("sequential") Long sequential'), ('request', '@RequestBody UpdateCpeDisagreementRequest request')],
               ('400', '404', '500', '503', '504')),
        api_op('createNonTransientError', 'Registra un error no transitorio producido durante los procesos.',
               '@PostMapping(path = "/api/v1/nonTransientError", produces = {"application/json"})', 'CreateNonTransientErrorResponse',
               [('epdRequestId', '@RequestParam(name = "epdRequestId", required = true) Long epdRequestId'),
                ('messagePayload', '@RequestParam(name = "messagePayload", required = true) String messagePayload'),
                ('creationUser', '@RequestParam(name = "creationUser", required = true) String creationUser')], ('400', '404', '500', '503', '504')),
    ]
    return '/** Define el contrato de los endpoints REST de estado de solicitudes CPE (contrato OpenAPI). */\npublic interface CustomerBillStatusApi {\n' + '\n\n'.join(ops) + '\n}'


def controller():
    hdr = [f'            String {c}' for _, c, _ in dj.HEADERS]
    fwd = 'new ForwardedHeaders(traceparent, xAppId, xChannel, xClientVersionId, xCorrelationId, xRequestId, xUserId)'
    new_headers = '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);'

    def method(name, resp, params, call, log_name):
        args = [f'            {p}' for p in params] + hdr
        return '\n'.join(['    @Override', f'    public ResponseEntity<{resp}> {name}(', ',\n'.join(args) + ') {', f'        log.info("{log_name} - transactionId: {{}}", xCorrelationId);',
                          new_headers, f'        return ResponseEntity.ok({call});', '    }'])
    body = [
        method('updateCustomerBillStatus', 'UpdateCustomerBillStatusResponse', ['UpdateCustomerBillStatusRequest request'],
               f'service.updateCustomerBillStatus(headers, {fwd}, request)', 'updateCustomerBillStatus'),
        method('updateCpeDisagreement', 'UpdateCpeDisagreementResponse', ['String documentType', 'String series', 'Long sequential', 'UpdateCpeDisagreementRequest request'],
               f'service.updateCpeDisagreement(headers, {fwd}, documentType, series, sequential, request)', 'updateCpeDisagreement'),
        method('createNonTransientError', 'CreateNonTransientErrorResponse', ['Long epdRequestId', 'String messagePayload', 'String creationUser'],
               'service.createNonTransientError(headers, epdRequestId, messagePayload, creationUser)', 'createNonTransientError'),
    ]
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class CustomerBillStatusController implements CustomerBillStatusApi {',
                      '    private final CustomerBillStatusService service;', '', '\n\n'.join(body), '}'])


def handler():
    text = dj.HANDLER
    text = re.sub(r'    private String operationMessage\(.*?\n    }\n\n    private String method',
                  '    private String operationMessage(String method, String uri, HttpStatus status) {\n'
                  '        if (uri.endsWith("/disagreement")) {\n            return "PROCESPATCH_DISAGREEMENT_SERVICE_ERROR";\n        }\n'
                  '        if (uri.endsWith("/nonTransientError")) {\n            return "PROCESPOST_NON_TRANSIENT_ERROR_SERVICE_ERROR";\n        }\n'
                  '        return "PROCESPATCH_CUSTOMER_BILL_STATUS_SERVICE_ERROR";\n    }\n\n    private String method', text, flags=re.S)
    text = text.replace('Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.CONFLICT,', 'Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.NOT_FOUND,')
    not_found = 'uri(request).endsWith("/disagreement") ? "No se encontr\u00f3 el comprobante de pago electr\u00f3nico indicado." : "No se encontr\u00f3 la solicitud CPE indicada."'
    text = re.sub(r'(case NOT_FOUND -> describe\(error, "ParameterValueNotFound", "IDF2", )"[^"]*"', lambda m: m.group(1) + not_found, text)
    text = re.sub(r'(case CONFLICT -> describe\(error, "Conflict", "IDF3", )"[^"]*"', lambda m: m.group(1) + '"La solicitud presenta un conflicto que impide su actualizaci\u00f3n."', text)
    return text


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    for cls, (table, fields) in ENTITIES.items():
        put('model', cls, dj.entity(cls, table, fields).replace('    @GeneratedValue(strategy = GenerationType.IDENTITY)\n', ''))
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    for cls, fields in REQUEST_DTOS.items():
        put('dto.request', cls, dj.dto(cls, fields))
    for cls, fields in DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields, non_null=True))
    for resp, data in RESPONSES.items():
        put('dto.response', resp, dj.envelope(resp, data))
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    for cls, fields in CLIENT_DTOS.items():
        put('client.dto', cls, dj.dto(cls, fields))
    put('client.dto', 'EmissionCpeHistResponse', dj.envelope('EmissionCpeHistResponse', 'EmissionCpeHistData'))
    put('client.dto', 'ForwardedHeaders', FORWARDED_HEADERS)
    put('client', 'EmissionCpeHistClient', CLIENT_IF)
    put('client', 'EmissionCpeHistClientImpl', CLIENT_IMPL)
    put('configuration', 'EmissionCpeHistClientConfig', CLIENT_CONFIG)
    put('configuration', 'TransactionConfig', TRANSACTION_CONFIG)
    put('configuration', 'ClockConfig', dj.CLOCK_CONFIG)
    put('dto.mapper', 'CustomerBillStatusMapper', MAPPER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', handler())
    for cls, body in REPOS.items():
        put('repository', cls, body)
    put('service', 'CustomerBillStatusService', SERVICE_IF)
    put('service.impl', 'CustomerBillStatusServiceImpl', SERVICE_IMPL)
    put('validation', 'CustomerBillStatusValidator', VALIDATOR)
    put('controller', 'CustomerBillStatusApi', api())
    put('controller.impl', 'CustomerBillStatusController', controller())
    return files


ORIGINAL_CONSTANTS = dj.activity_constants


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False), ('ACT2_BUSCAR_SOLICITUD_CPE', 'BUSCAR_SOLICITUD_CPE', True),
                     ('ACT3_REGISTRAR_SNAPSHOT_HISTORICO', 'REGISTRAR_SNAPSHOT_HISTORICO', False), ('ACT4_ACTUALIZAR_SOLICITUD', 'ACTUALIZAR_SOLICITUD', True)]
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
TESTS['CustomerBillStatusValidatorTest'] = ('validation', '''class CustomerBillStatusValidatorTest {
    private static final Long ID = 1526L;
    private static final Long SEQUENTIAL = 1412L;

    private final CustomerBillStatusValidator validator = new CustomerBillStatusValidator();

    private UpdateCustomerBillStatusRequest request() {
        UpdateCustomerBillStatusRequest request = new UpdateCustomerBillStatusRequest();
        request.setId(ID);
        request.setLastModifiedUser("USERMOD");
        return request;
    }

    private void assertBadRequest(Runnable action) {
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, action::run).getStatus());
    }

    @Test
    void acceptsAMinimalAndAFullStatusUpdate() {
        validator.statusUpdate(request());
        UpdateCustomerBillStatusRequest full = request();
        full.setPlotsovos("{\\"codigo\\":\\"0000\\"}");
        full.setInstallmentsSchedulePayload("[1,2]");
        full.setDisagreementFlag(1);
        validator.statusUpdate(full);
    }

    @Test
    void rejectsMissingRequiredFieldsAndInvalidValues() {
        assertBadRequest(() -> validator.statusUpdate(null));
        UpdateCustomerBillStatusRequest noId = request();
        noId.setId(null);
        assertBadRequest(() -> validator.statusUpdate(noId));
        UpdateCustomerBillStatusRequest noUser = request();
        noUser.setLastModifiedUser(" ");
        assertBadRequest(() -> validator.statusUpdate(noUser));
        UpdateCustomerBillStatusRequest badFlag = request();
        badFlag.setDisagreementFlag(2);
        assertBadRequest(() -> validator.statusUpdate(badFlag));
        UpdateCustomerBillStatusRequest badJson = request();
        badJson.setPlotsovos("{not json");
        assertBadRequest(() -> validator.statusUpdate(badJson));
        UpdateCustomerBillStatusRequest badSchedule = request();
        badSchedule.setInstallmentsSchedulePayload("{not json");
        assertBadRequest(() -> validator.statusUpdate(badSchedule));
    }

    @Test
    void disagreementRequiresPathValuesAndTheFlag() {
        UpdateCpeDisagreementRequest body = new UpdateCpeDisagreementRequest();
        body.setDisagreementFlag(true);
        assertTrue(validator.disagreement("01", "F001", SEQUENTIAL, body));
        assertBadRequest(() -> validator.disagreement(" ", "F001", SEQUENTIAL, body));
        assertBadRequest(() -> validator.disagreement("01", null, SEQUENTIAL, body));
        assertBadRequest(() -> validator.disagreement("01", "F001", 0L, body));
        assertBadRequest(() -> validator.disagreement("01", "F001", SEQUENTIAL, new UpdateCpeDisagreementRequest()));
        assertBadRequest(() -> validator.disagreement("01", "F001", SEQUENTIAL, null));
    }

    @Test
    void nonTransientErrorRequiresItsThreeParameters() {
        validator.nonTransientError(ID, "message", "BATCH");
        assertBadRequest(() -> validator.nonTransientError(null, "message", "BATCH"));
        assertBadRequest(() -> validator.nonTransientError(ID, "", "BATCH"));
        assertBadRequest(() -> validator.nonTransientError(ID, "message", null));
    }
}''')
TESTS['CustomerBillStatusMapperTest'] = ('dto.mapper', '''class CustomerBillStatusMapperTest {
    private static final Long ID = 12345L;
    private static final Long HIST_ID = 5001L;

    private final CustomerBillStatusMapper mapper = new CustomerBillStatusMapper();

    @Test
    void statusResponseCarriesTheUpdatedCount() {
        UpdateCustomerBillStatusResponse response = mapper.statusResponse(1);
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertEquals(1, response.getData().getUpdated());
    }

    @Test
    void disagreementResponseParsesOffsetAndLocalDates() {
        EmissionCpeHistData history = new EmissionCpeHistData();
        history.setId(HIST_ID);
        history.setSnapshotDate("2026-10-12T16:00:00Z");
        UpdateCpeDisagreementResponse offset = mapper.disagreementResponse(ID, history);
        assertEquals(HIST_ID, offset.getData().getId());
        assertEquals(ID, offset.getData().getEpdRequestId());
        assertEquals(LocalDateTime.parse("2026-10-12T16:00:00"), offset.getData().getSnapshotDate());
        history.setSnapshotDate("2026-10-12T16:00:00");
        assertEquals(LocalDateTime.parse("2026-10-12T16:00:00"), mapper.disagreementResponse(ID, history).getData().getSnapshotDate());
        history.setSnapshotDate("garbage");
        assertNull(mapper.disagreementResponse(ID, history).getData().getSnapshotDate());
        history.setSnapshotDate(null);
        assertNull(mapper.disagreementResponse(ID, history).getData().getSnapshotDate());
    }

    @Test
    void unchangedDisagreementHasNoHistoryData() {
        UpdateCpeDisagreementResponse response = mapper.disagreementResponse(ID, null);
        assertEquals(ID, response.getData().getEpdRequestId());
        assertNull(response.getData().getId());
        assertNull(response.getData().getSnapshotDate());
    }
}''')
TESTS['GlobalExceptionHandlerTest'] = ('exception', '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request(String method, String uri) {
        return new ServletWebRequest(new MockHttpServletRequest(method, uri));
    }

    @Test
    void badRequestUsesTheContractShapeAndTheOperationMessage() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request("PATCH", "/api/v1/sod-customerBillStatus"));
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF1", response.getBody().getSubType());
        assertEquals("PROCESPATCH_CUSTOMER_BILL_STATUS_SERVICE_ERROR", response.getBody().getMessage());
    }

    @Test
    void notFoundDetailDependsOnTheOperation() {
        ServiceOperationException none = new ServiceOperationException(HttpStatus.NOT_FOUND, "none");
        ErrorResponse status = handler.operationFailure(none, request("PATCH", "/api/v1/sod-customerBillStatus")).getBody();
        ErrorResponse cpe = handler.operationFailure(none, request("PATCH", "/api/v1/sod-customerBillStatus/01/F001/1/disagreement")).getBody();
        assertEquals("PROCESPATCH_DISAGREEMENT_SERVICE_ERROR", cpe.getMessage());
        assertTrue(status.getDetail().contains("solicitud CPE"));
        assertTrue(cpe.getDetail().contains("comprobante"));
    }

    @Test
    void conflictIsDeclaredOnlyForThePatchOperations() {
        ServiceOperationException conflict = new ServiceOperationException(HttpStatus.CONFLICT, "dup");
        assertEquals(HttpStatus.CONFLICT.value(), handler.operationFailure(conflict, request("PATCH", "/api/v1/sod-customerBillStatus")).getStatusCode().value());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), handler.operationFailure(conflict, request("POST", "/api/v1/nonTransientError")).getStatusCode().value());
    }

    @Test
    void nonTransientErrorHasItsOwnMessageAndAllowsNotFound() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"), request("POST", "/api/v1/nonTransientError"));
        assertEquals(HttpStatus.NOT_FOUND.value(), response.getStatusCode().value());
        assertEquals("PROCESPOST_NON_TRANSIENT_ERROR_SERVICE_ERROR", response.getBody().getMessage());
    }

    @Test
    void unexpectedFailuresBecomeInternalErrorAndTimeoutsGatewayTimeout() {
        ResponseEntity<ErrorResponse> unexpected = handler.unexpectedFailure(new IllegalStateException("boom"), request("PATCH", "/api/v1/sod-customerBillStatus"));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), unexpected.getStatusCode().value());
        assertEquals("IDT3", unexpected.getBody().getSubType());
        ResponseEntity<ErrorResponse> slow = handler.operationFailure(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"), request("PATCH", "/api/v1/sod-customerBillStatus"));
        assertEquals("IDT1", slow.getBody().getSubType());
    }
}''')
TESTS['CustomerBillStatusServiceImplTest'] = ('service.impl', '''class CustomerBillStatusServiceImplTest {
    private static final Long ID = 1526L;
    private static final Long SEQUENTIAL = 1412L;
    private static final Long HIST_ID = 5001L;
    private static final Long TYPE_ID = 1L;
    private static final Integer OLD_STATUS = 1;
    private static final Integer NEW_STATUS = 2;
    private static final Integer ATTEMPTS = 3;

    private final EpdRequestRepository requests = Mockito.mock(EpdRequestRepository.class);
    private final DocumentTypeRepository documentTypes = Mockito.mock(DocumentTypeRepository.class);
    private final EmissionCpeHistClient historyClient = Mockito.mock(EmissionCpeHistClient.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-12T10:15:30Z"), ZoneOffset.UTC);
    private final CustomerBillStatusServiceImpl service = new CustomerBillStatusServiceImpl(requests, documentTypes, historyClient, new CustomerBillStatusMapper(),
            new CustomerBillStatusValidator(), new PersistenceExceptionTranslator(), new TransactionTemplate(Mockito.mock(PlatformTransactionManager.class)), clock);
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");
    private final ForwardedHeaders forwarded = new ForwardedHeaders("t", "app", "web", "1", "tx", "req", "user");

    private EpdRequestEntity current(Integer flag) {
        EpdRequestEntity entity = new EpdRequestEntity();
        entity.setId(ID);
        entity.setEpdQueryStatusId(OLD_STATUS);
        entity.setDisagreementFlag(flag);
        return entity;
    }

    private UpdateCustomerBillStatusRequest statusRequest() {
        UpdateCustomerBillStatusRequest request = new UpdateCustomerBillStatusRequest();
        request.setId(ID);
        request.setLastModifiedUser("USERMOD");
        return request;
    }

    private void stubCpe(EpdRequestEntity entity) {
        DocumentTypeEntity type = new DocumentTypeEntity();
        type.setId(TYPE_ID);
        Mockito.when(documentTypes.findBySunatDocumentTypeCode("01")).thenReturn(Optional.of(type));
        Mockito.when(requests.findBySeriesAndCorrelativeAndEpdTypeId("F001", SEQUENTIAL, TYPE_ID.intValue())).thenReturn(List.of(entity));
    }

    private UpdateCpeDisagreementRequest disagreementRequest(boolean flag) {
        UpdateCpeDisagreementRequest request = new UpdateCpeDisagreementRequest();
        request.setDisagreementFlag(flag);
        return request;
    }

    private EmissionCpeHistData history() {
        EmissionCpeHistData data = new EmissionCpeHistData();
        data.setId(HIST_ID);
        data.setEpdRequestId(ID);
        data.setSnapshotDate("2026-10-12T16:00:00");
        return data;
    }

    @Test
    void updatesOnlyTheSentFieldsAndTheAuditWithoutHistory() {
        EpdRequestEntity entity = current(0);
        entity.setInputPayload("old");
        Mockito.when(requests.findById(ID)).thenReturn(Optional.of(entity));
        UpdateCustomerBillStatusRequest request = statusRequest();
        request.setAttemptNumber(ATTEMPTS);
        UpdateCustomerBillStatusResponse response = service.updateCustomerBillStatus(headers, forwarded, request);
        assertEquals(1, response.getData().getUpdated());
        Mockito.verifyNoInteractions(historyClient);
        ArgumentCaptor<EpdRequestEntity> captor = ArgumentCaptor.forClass(EpdRequestEntity.class);
        Mockito.verify(requests).save(captor.capture());
        assertEquals(ATTEMPTS, captor.getValue().getAttemptNumber());
        assertEquals("old", captor.getValue().getInputPayload());
        assertEquals(OLD_STATUS, captor.getValue().getEpdQueryStatusId());
        assertEquals("USERMOD", captor.getValue().getLastModifiedUser());
        assertEquals(LocalDateTime.parse("2026-10-12T10:15:30"), captor.getValue().getLastModifiedDate());
    }

    @Test
    void aStatusChangeRegistersTheHistoryBeforeTheUpdate() {
        Mockito.when(requests.findById(ID)).thenReturn(Optional.of(current(0)));
        Mockito.when(historyClient.createSnapshot(forwarded, ID)).thenReturn(history());
        UpdateCustomerBillStatusRequest request = statusRequest();
        request.setEpdQueryStatusId(NEW_STATUS);
        request.setPlotsovos("{}");
        request.setInstallmentsSchedulePayload("[]");
        request.setDisagreementFlag(1);
        service.updateCustomerBillStatus(headers, forwarded, request);
        InOrder order = Mockito.inOrder(historyClient, requests);
        order.verify(historyClient).createSnapshot(forwarded, ID);
        order.verify(requests).save(ArgumentMatchers.any(EpdRequestEntity.class));
        ArgumentCaptor<EpdRequestEntity> captor = ArgumentCaptor.forClass(EpdRequestEntity.class);
        Mockito.verify(requests).save(captor.capture());
        assertEquals(NEW_STATUS, captor.getValue().getEpdQueryStatusId());
        assertEquals("{}", captor.getValue().getInputPayload());
        assertEquals("[]", captor.getValue().getInstallmentSchedulePayload());
        assertEquals(1, captor.getValue().getDisagreementFlag());
    }

    @Test
    void theSameStatusDoesNotRegisterHistory() {
        Mockito.when(requests.findById(ID)).thenReturn(Optional.of(current(0)));
        UpdateCustomerBillStatusRequest request = statusRequest();
        request.setEpdQueryStatusId(OLD_STATUS);
        service.updateCustomerBillStatus(headers, forwarded, request);
        Mockito.verifyNoInteractions(historyClient);
    }

    @Test
    void anUnknownRequestIsNotFound() {
        Mockito.when(requests.findById(ID)).thenReturn(Optional.empty());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.updateCustomerBillStatus(headers, forwarded, statusRequest())).getStatus());
    }

    @Test
    void aHistoryFailureStopsTheUpdate() {
        Mockito.when(requests.findById(ID)).thenReturn(Optional.of(current(0)));
        Mockito.when(historyClient.createSnapshot(forwarded, ID)).thenThrow(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"));
        UpdateCustomerBillStatusRequest request = statusRequest();
        request.setEpdQueryStatusId(NEW_STATUS);
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> service.updateCustomerBillStatus(headers, forwarded, request)).getStatus());
        Mockito.verify(requests, Mockito.never()).save(ArgumentMatchers.any(EpdRequestEntity.class));
    }

    @Test
    void invalidInputFailsBeforeTheDatabaseAndTimeoutsAreTranslated() {
        UpdateCustomerBillStatusRequest invalid = statusRequest();
        invalid.setPlotsovos("{bad");
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.updateCustomerBillStatus(headers, forwarded, invalid)).getStatus());
        Mockito.verifyNoInteractions(requests);
        Mockito.when(requests.findById(ID)).thenThrow(new QueryTimeoutException("slow"));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> service.updateCustomerBillStatus(headers, forwarded, statusRequest())).getStatus());
    }

    @Test
    void disagreementIsUpdatedAfterTheHistorySnapshot() {
        EpdRequestEntity entity = current(0);
        stubCpe(entity);
        Mockito.when(historyClient.createSnapshot(forwarded, ID)).thenReturn(history());
        UpdateCpeDisagreementResponse response = service.updateCpeDisagreement(headers, forwarded, "01", "F001", SEQUENTIAL, disagreementRequest(true));
        assertEquals(HIST_ID, response.getData().getId());
        assertEquals(ID, response.getData().getEpdRequestId());
        InOrder order = Mockito.inOrder(historyClient, requests);
        order.verify(historyClient).createSnapshot(forwarded, ID);
        order.verify(requests).save(entity);
        assertEquals(1, entity.getDisagreementFlag());
        assertEquals("user", entity.getLastModifiedUser());
        assertEquals(OLD_STATUS, entity.getEpdQueryStatusId());
    }

    @Test
    void theSameDisagreementValueChangesNothing() {
        stubCpe(current(0));
        UpdateCpeDisagreementResponse response = service.updateCpeDisagreement(headers, forwarded, "01", "F001", SEQUENTIAL, disagreementRequest(false));
        assertEquals(ID, response.getData().getEpdRequestId());
        assertNull(response.getData().getId());
        Mockito.verifyNoInteractions(historyClient);
        Mockito.verify(requests, Mockito.never()).save(ArgumentMatchers.any(EpdRequestEntity.class));
    }

    @Test
    void aMissingCpeOrDocumentTypeIsNotFoundAndAmbiguityIsAnInternalError() {
        Mockito.when(documentTypes.findBySunatDocumentTypeCode("01")).thenReturn(Optional.empty());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class,
                () -> service.updateCpeDisagreement(headers, forwarded, "01", "F001", SEQUENTIAL, disagreementRequest(true))).getStatus());
        DocumentTypeEntity type = new DocumentTypeEntity();
        type.setId(TYPE_ID);
        Mockito.when(documentTypes.findBySunatDocumentTypeCode("01")).thenReturn(Optional.of(type));
        Mockito.when(requests.findBySeriesAndCorrelativeAndEpdTypeId("F001", SEQUENTIAL, TYPE_ID.intValue())).thenReturn(List.of());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class,
                () -> service.updateCpeDisagreement(headers, forwarded, "01", "F001", SEQUENTIAL, disagreementRequest(true))).getStatus());
        Mockito.when(requests.findBySeriesAndCorrelativeAndEpdTypeId("F001", SEQUENTIAL, TYPE_ID.intValue())).thenReturn(List.of(current(0), current(1)));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class,
                () -> service.updateCpeDisagreement(headers, forwarded, "01", "F001", SEQUENTIAL, disagreementRequest(true))).getStatus());
    }

    @Test
    void aHistoryFailureStopsTheDisagreementUpdate() {
        stubCpe(current(0));
        Mockito.when(historyClient.createSnapshot(forwarded, ID)).thenThrow(new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, "down"));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, assertThrows(ServiceOperationException.class,
                () -> service.updateCpeDisagreement(headers, forwarded, "01", "F001", SEQUENTIAL, disagreementRequest(true))).getStatus());
        Mockito.verify(requests, Mockito.never()).save(ArgumentMatchers.any(EpdRequestEntity.class));
    }

    @Test
    void nonTransientErrorValidatesAndThenReportsThatItHasNoDefinedLogic() {
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.createNonTransientError(headers, null, "m", "u")).getStatus());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> service.createNonTransientError(headers, ID, "m", "u")).getStatus());
    }
}''')
TESTS['EmissionCpeHistClientImplTest'] = ('client', '''class EmissionCpeHistClientImplTest {
    private static final String URL = "http://emission-cpehist/api/v1/emisioneshist";
    private static final Long ID = 12345L;
    private static final Long HIST_ID = 5001L;

    private final RestClient.Builder builder = RestClient.builder().baseUrl("http://emission-cpehist");
    private final MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    private final EmissionCpeHistClientImpl client = new EmissionCpeHistClientImpl(builder.build());
    private final ForwardedHeaders headers = new ForwardedHeaders("t", "app", "web", "1", "tx", "req", null);

    @Test
    void postsTheRequestIdWithTheForwardedHeadersAndReturnsTheData() {
        server.expect(requestTo(URL)).andExpect(method(HttpMethod.POST)).andExpect(header("x-correlation-id", "tx")).andExpect(header("traceparent", "t"))
                .andExpect(content().json("{\\"epdRequestId\\":12345}"))
                .andRespond(withSuccess("{\\"code\\":200,\\"message\\":\\"ok\\",\\"data\\":{\\"id\\":5001,\\"epdRequestId\\":12345,\\"snapshotDate\\":\\"2026-10-12T16:00:00\\"}}", MediaType.APPLICATION_JSON));
        EmissionCpeHistData data = client.createSnapshot(headers, ID);
        assertEquals(HIST_ID, data.getId());
        server.verify();
    }

    @Test
    void anEmptyBodyIsAnInternalError() {
        server.expect(requestTo(URL)).andRespond(withSuccess("{\\"code\\":200}", MediaType.APPLICATION_JSON));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> client.createSnapshot(headers, ID)).getStatus());
    }

    @Test
    void remoteStatusesAreMappedToTheTechnicalStatuses() {
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, assertThrows(ServiceOperationException.class, () -> client.createSnapshot(headers, ID)).getStatus());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.GATEWAY_TIMEOUT));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> client.createSnapshot(headers, ID)).getStatus());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.NOT_FOUND));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> client.createSnapshot(headers, ID)).getStatus());
    }

    @Test
    void connectionFailuresAreUnavailableAndSocketTimeoutsAreGatewayTimeouts() {
        server.expect(requestTo(URL)).andRespond(withException(new IOException("refused")));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, assertThrows(ServiceOperationException.class, () -> client.createSnapshot(headers, ID)).getStatus());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withException(new SocketTimeoutException("slow")));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> client.createSnapshot(headers, ID)).getStatus());
    }
}''')
TESTS['CustomerBillStatusApiContractTest'] = ('controller', '''class CustomerBillStatusApiContractTest {
    private static final Long SEQUENTIAL = 1412L;

    private final CustomerBillStatusService service = Mockito.mock(CustomerBillStatusService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new CustomerBillStatusController(service))
            .setControllerAdvice(new GlobalExceptionHandler(new PersistenceExceptionTranslator()))
            .build();

    private MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder) {
        return builder__HEADERS__;
    }

    private UpdateCustomerBillStatusResponse statusResponse() {
        UpdateCustomerBillStatusData data = new UpdateCustomerBillStatusData();
        data.setUpdated(1);
        UpdateCustomerBillStatusResponse response = new UpdateCustomerBillStatusResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("ok");
        response.setData(data);
        return response;
    }

    @Test
    void patchStatusReturnsTheEnvelope() throws Exception {
        Mockito.when(service.updateCustomerBillStatus(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class),
                ArgumentMatchers.any(UpdateCustomerBillStatusRequest.class))).thenReturn(statusResponse());
        mvc.perform(withHeaders(patch("/api/v1/sod-customerBillStatus")).contentType(MediaType.APPLICATION_JSON).content("{\\"id\\": 1, \\"lastModifiedUser\\": \\"u\\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.updated").value(1));
    }

    @Test
    void patchStatusConflictAndMissingHeadersUseTheContractErrors() throws Exception {
        Mockito.when(service.updateCustomerBillStatus(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class),
                ArgumentMatchers.any(UpdateCustomerBillStatusRequest.class))).thenThrow(new ServiceOperationException(HttpStatus.CONFLICT, "dup"));
        mvc.perform(withHeaders(patch("/api/v1/sod-customerBillStatus")).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.subType").value("IDF3"));
        mvc.perform(patch("/api/v1/sod-customerBillStatus").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.subType").value("IDF1"));
    }

    @Test
    void patchDisagreementPassesThePathValues() throws Exception {
        UpdateCpeDisagreementData data = new UpdateCpeDisagreementData();
        data.setEpdRequestId(1L);
        UpdateCpeDisagreementResponse response = new UpdateCpeDisagreementResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("ok");
        response.setData(data);
        Mockito.when(service.updateCpeDisagreement(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class), ArgumentMatchers.eq("01"),
                ArgumentMatchers.eq("F001"), ArgumentMatchers.eq(SEQUENTIAL), ArgumentMatchers.any(UpdateCpeDisagreementRequest.class))).thenReturn(response);
        mvc.perform(withHeaders(patch("/api/v1/sod-customerBillStatus/01/F001/1412/disagreement")).contentType(MediaType.APPLICATION_JSON).content("{\\"disagreementFlag\\": true}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.epdRequestId").value(1));
    }

    @Test
    void postNonTransientErrorTakesQueryParameters() throws Exception {
        Mockito.when(service.createNonTransientError(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(1L), ArgumentMatchers.eq("m"), ArgumentMatchers.eq("u")))
                .thenThrow(new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, "none"));
        mvc.perform(withHeaders(post("/api/v1/nonTransientError")).param("epdRequestId", "1").param("messagePayload", "m").param("creationUser", "u"))
                .andExpect(status().isInternalServerError()).andExpect(jsonPath("$.message").value("PROCESPOST_NON_TRANSIENT_ERROR_SERVICE_ERROR"));
        mvc.perform(withHeaders(post("/api/v1/nonTransientError")).param("epdRequestId", "x").param("messagePayload", "m").param("creationUser", "u"))
                .andExpect(status().isBadRequest());
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
        statics = list(dt.MVC_STATICS) if name.endswith('ContractTest') else dt.ASSERT + (MOCK_REST if name.startswith('EmissionCpeHistClient') else [])
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.sod.customerbillstatus and application class SodCustomerBillStatusApplication are technical choices; no source defines them.'),
    ('A-02', 'EPDREQUEST is mapped in schema FACEL with the columns the operations use. Sparx names V_SERIE/V_CORRELATIVO are not table columns; the table definition columns SERIES and CORRELATIVE are used.'),
    ('A-03', 'Sparx lists a 404 end event only; the OpenAPI declares 409 for updateCustomerBillStatus without any Sparx rule that produces it (swagger-governs): the handler can emit it but no service rule does.'),
    ('A-04', 'updateCpeDisagreement: Sparx says more than one matching CPE is a 409, but the OpenAPI does not declare 409 for it (swagger-governs); the service answers 500 with an explicit detail.'),
    ('A-05', 'The history snapshot is requested to emission-cpehist (RestClient, base URL emission-cpehist.base-url default http://emission-cpehist, timeout emission-cpehist.timeout-ms default 5000) before the local update; all seven received headers are forwarded. Remote 503/502 or connection failures -> 503, timeouts or 504/408 -> 504, any other failure -> 500 (Sparx IDT2/IDT1/IDT3). The update and the remote history call cannot share one database transaction.'),
    ('A-06', 'updateCustomerBillStatus: the history snapshot is registered only when epdQueryStatusId is informed and differs from the current status; the new status is not validated against EPDQUERYSTATUS (no Sparx rule); data.updated is 1 (single row update by id).'),
    ('A-07', 'plotsovos is written to INPUTPAYLOAD as stated by Sparx and installmentsSchedulePayload to INSTALLMENTSCHEDULEPAYLOAD; ATTEMPTNUMBER and DISAGREEMENTFLAG are written whenever sent (the RF1.6/RF1.9 caller conditions are the caller responsibility).'),
    ('A-08', 'updateCpeDisagreement response: when the flag already has the requested value data contains only epdRequestId (no history was generated); otherwise id/snapshotDate come from the history service (snapshotDate accepts offset or local date-time).'),
    ('A-09', 'updateCpeDisagreement: documentType (SUNAT code) is resolved in ELECTRONICDOCUMENTTYPE and used as EPDTYPEID; LASTMODIFIEDUSER is the x-user-id header (Sparx: authenticated identity); LASTMODIFIEDDATE uses the injectable Clock, never SYSDATE.'),
    ('A-10', 'createNonTransientError: the authoritative Sparx branch has no logic and the NONTRANSIENTERROR table has no data definition. Parameters are validated (400) and the operation then fails with 500 and an explicit detail; no persistence is invented. Needs Sparx owner input to be implemented.'),
    ('A-11', 'Only the statuses declared by the OpenAPI are emitted; no 401/403 handling (swagger-governs). Error messages and details come from the Swagger examples.'),
]


def main(argv=None):
    sys.modules['dom_invoice_java'] = types.SimpleNamespace()
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, 'SodCustomerBillStatusApplication', ASSUMPTIONS, 'sod-customer-bill-status-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': 'SodCustomerBillStatusApplication'}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'sod_customer_bill_status_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main(argv) if argv is not None else dm.main()


if __name__ == '__main__':
    sys.exit(main())



