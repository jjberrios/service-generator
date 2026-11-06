"""Deterministic materializer of the orq-customerBillCases service (JPA profile of claro-spring-ms): one POST that resolves a non transient error case in a single local transaction.

Reuses the machinery of dom_cpe_request_materializer (gate recomputed first, archetype assembly, file protection, per-service lock, manifest last).

Usage: python orq_customer_bill_cases_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402

PACKAGE = 'com.claro.orq.customerbillcases'
dj.EXTERNAL['SequenceGenerator'] = 'jakarta.persistence.SequenceGenerator'
dj.EXTERNAL['ObjectNode'] = 'com.fasterxml.jackson.databind.node.ObjectNode'
dj.EXTERNAL['JsonNode'] = 'com.fasterxml.jackson.databind.JsonNode'
dj.EXTERNAL['ArgumentCaptor'] = 'org.mockito.ArgumentCaptor'
dj.EXTERNAL['InOrder'] = 'org.mockito.InOrder'
dj.EXTERNAL['MockHttpServletRequestBuilder'] = 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder'

ENTITIES = {
    'NonTransientErrorEntity': ('NONTRANSIENTERROR', [('Long', 'id', 'ID', 'id'), ('Long', 'epdRequestId', 'EPDREQUESTID', '')]),
    'EpdQueryStatusEntity': ('EPDQUERYSTATUS', [('Long', 'id', 'ID', 'id'), ('String', 'value', 'VALUE', '')]),
    'ErrorCaseEvidenceEntity': ('ERRORCASEEVIDENCE', [
        ('Long', 'id', 'ID', 'id'), ('String', 'comentReference', 'COMENTREFERENCE', ''), ('String', 'assignedUserId', 'ASSIGNEDUSERID', ''),
        ('Long', 'nonTransientErrorId', 'NONTRANSIENTERRORID', ''), ('String', 'dataCorrected', 'DATACORRECTED', 'lob'),
        ('String', 'creationUser', 'CREATIONUSER', ''), ('LocalDateTime', 'creationDate', 'CREATIONDATE', '')]),
    'EpdRequestEntity': ('EPDREQUEST', [
        ('Long', 'id', 'ID', 'id'), ('Integer', 'epdTypeId', 'EPDTYPEID', ''), ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''),
        ('Integer', 'generationType', 'GENERATIONTYPE', ''), ('Integer', 'actionType', 'ACTIONTYPE', ''),
        ('String', 'inputPayload', 'INPUTPAYLOAD', 'lob'), ('String', 'plotSovos', 'PLOTSOVOS', 'lob'),
        ('String', 'installmentSchedulePayload', 'INSTALLMENTSCHEDULEPAYLOAD', 'lob'),
        ('Integer', 'attemptNumber', 'ATTEMPTNUMBER', ''), ('Integer', 'disagreementFlag', 'DISAGREEMENTFLAG', ''), ('String', 'application', 'APPLICATION', ''),
        ('String', 'operationId', 'OPERATIONID', ''), ('String', 'operation', 'OPERATION', ''), ('String', 'channel', 'CHANNEL', ''),
        ('String', 'lastModifiedUser', 'LASTMODIFIEDUSER', ''), ('LocalDateTime', 'lastModifiedDate', 'LASTMODIFIEDDATE', '')]),
    'EpdRequestHistEntity': ('EPDREQUESTHIST', [
        ('Long', 'id', 'ID', 'id'), ('Long', 'epdRequestId', 'EPDREQUESTID', ''), ('Integer', 'generationType', 'GENERATIONTYPE', ''), ('Integer', 'actionType', 'ACTIONTYPE', ''),
        ('String', 'inputPayload', 'INPUTPAYLOAD', 'lob'), ('String', 'installmentSchedulePayload', 'INSTALLMENTSCHEDULEPAYLOAD', 'lob'),
        ('Integer', 'attemptNumber', 'ATTEMPTNUMBER', ''), ('Integer', 'disagreementFlag', 'DISAGREEMENTFLAG', ''), ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''),
        ('Integer', 'epdTypeId', 'EPDTYPEID', ''), ('String', 'application', 'APPLICATION', ''), ('String', 'operationId', 'OPERATIONID', ''),
        ('String', 'channel', 'CHANNEL', ''), ('String', 'operation', 'OPERATION', ''), ('String', 'creationUser', 'CREATIONUSER', ''),
        ('LocalDateTime', 'creationDate', 'CREATIONDATE', ''), ('String', 'lastModifiedUser', 'LASTMODIFIEDUSER', ''), ('LocalDateTime', 'lastModifiedDate', 'LASTMODIFIEDDATE', '')]),
}
REQUEST_DTOS = {'ResolveCustomerBillCaseRequest': [('String', 'note'), ('String', 'assignedUserId'), ('Map<String, Object>', 'dataCorrected')]}
DTOS = {'ResolveCustomerBillCaseData': [('Boolean', 'success'), ('Long', 'epdRequestId'), ('Long', 'epdRequestHistId'), ('String', 'previousStatus'), ('String', 'status')],
        'ErrorItem': [('String', 'code'), ('String', 'message')]}
dj.register('model', *ENTITIES)
dj.register('dto.request', *REQUEST_DTOS)
dj.register('dto.response', *DTOS, 'ResolveCustomerBillCaseResponse', 'ErrorResponse')
dj.register('dto.mapper', 'CustomerBillCasesMapper')
dj.register('repository', 'NonTransientErrorRepository', 'EpdQueryStatusRepository', 'ErrorCaseEvidenceRepository', 'EpdRequestRepository', 'EpdRequestHistRepository')
dj.register('service', 'CustomerBillCasesService')
dj.register('service.impl', 'CustomerBillCasesServiceImpl')
dj.register('validation', 'CustomerBillCasesValidator')
dj.register('controller', 'CustomerBillCasesApi')
dj.register('controller.impl', 'CustomerBillCasesController')

REPOS = {
    'NonTransientErrorRepository': '''@Repository
public interface NonTransientErrorRepository extends JpaRepository<NonTransientErrorEntity, Long> {
}''',
    'EpdQueryStatusRepository': '''@Repository
public interface EpdQueryStatusRepository extends JpaRepository<EpdQueryStatusEntity, Long> {
    Optional<EpdQueryStatusEntity> findFirstByValue(String value);
}''',
    'ErrorCaseEvidenceRepository': '''@Repository
public interface ErrorCaseEvidenceRepository extends JpaRepository<ErrorCaseEvidenceEntity, Long> {
}''',
    'EpdRequestRepository': '''@Repository
public interface EpdRequestRepository extends JpaRepository<EpdRequestEntity, Long> {
}''',
    'EpdRequestHistRepository': '''@Repository
public interface EpdRequestHistRepository extends JpaRepository<EpdRequestHistEntity, Long> {
}''',
}

SERVICE_IF = '''/** Subsanacion de casos de error no transitorio. */
public interface CustomerBillCasesService {
    ResolveCustomerBillCaseResponse resolveCustomerBillCase(RequestHeaders headers, Long id, ResolveCustomerBillCaseRequest request);
}'''

VALIDATOR = '''/** Declared contract rules: identifier, assigned user, corrected data object and the note length. */
@Component
public class CustomerBillCasesValidator {
    private static final int NOTE_MAX_LENGTH = 255;
    private static final String INVALID_REQUEST = "Los datos de la solicitud no son v\u00e1lidos.";

    public void resolution(Long id, ResolveCustomerBillCaseRequest request) {
        if (id == null || id <= 0 || request == null) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
        if (request.getAssignedUserId() == null || request.getAssignedUserId().isBlank()) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
        if (request.getNote() != null && request.getNote().length() > NOTE_MAX_LENGTH) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
        if (request.getDataCorrected() == null) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
        text(request.getDataCorrected().get(CustomerBillCasesMapper.NAME));
        text(request.getDataCorrected().get(CustomerBillCasesMapper.ADDRESS));
    }

    private void text(Object value) {
        if (value != null && (!(value instanceof String text) || text.isBlank())) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
    }
}'''

MAPPER = '''/** Explicit mapping between the case rows, the corrected data and the API contract. */
@Component
public class CustomerBillCasesMapper {
    public static final String NAME = "nombre";
    public static final String ADDRESS = "direccion";
    private static final String SUCCESS_MESSAGE = "Operaci\u00f3n exitosa";
    private static final String BUYER_SECTION = "EN";
    private static final String BUYER_NAME_FIELD = "EN19_RazonSocialAdquiriente";
    private static final String BUYER_ADDRESS_FIELD = "EN20_DireccionAdquiriente";
    private static final String INVALID_PLOT = "La trama vigente del CPE no es un JSON v\u00e1lido.";

    private final ObjectMapper json = new ObjectMapper();

    public ErrorCaseEvidenceEntity evidence(ResolveCustomerBillCaseRequest request, Long caseId, String user, LocalDateTime now) {
        ErrorCaseEvidenceEntity evidence = new ErrorCaseEvidenceEntity();
        evidence.setComentReference(request.getNote());
        evidence.setAssignedUserId(request.getAssignedUserId());
        evidence.setNonTransientErrorId(caseId);
        evidence.setDataCorrected(serialize(request.getDataCorrected()));
        evidence.setCreationUser(user);
        evidence.setCreationDate(now);
        return evidence;
    }

    public EpdRequestHistEntity snapshot(EpdRequestEntity current, String user, LocalDateTime now) {
        EpdRequestHistEntity snapshot = new EpdRequestHistEntity();
        snapshot.setEpdRequestId(current.getId());
        snapshot.setGenerationType(current.getGenerationType());
        snapshot.setActionType(current.getActionType());
        snapshot.setInputPayload(current.getInputPayload());
        snapshot.setInstallmentSchedulePayload(current.getInstallmentSchedulePayload());
        snapshot.setAttemptNumber(current.getAttemptNumber());
        snapshot.setDisagreementFlag(current.getDisagreementFlag());
        snapshot.setEpdQueryStatusId(current.getEpdQueryStatusId());
        snapshot.setEpdTypeId(current.getEpdTypeId());
        snapshot.setApplication(current.getApplication());
        snapshot.setOperationId(current.getOperationId());
        snapshot.setChannel(current.getChannel());
        snapshot.setOperation(current.getOperation());
        snapshot.setLastModifiedUser(current.getLastModifiedUser());
        snapshot.setLastModifiedDate(current.getLastModifiedDate());
        snapshot.setCreationUser(user);
        snapshot.setCreationDate(now);
        return snapshot;
    }

    /** Applies only the informed corrections to the current SOVOS plot and keeps every other property. */
    public String correctedPlot(String currentPlot, Map<String, Object> corrected) {
        try {
            JsonNode parsed = currentPlot == null || currentPlot.isBlank() ? json.createObjectNode() : json.readTree(currentPlot);
            if (!(parsed instanceof ObjectNode root)) {
                throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, INVALID_PLOT);
            }
            JsonNode section = root.get(BUYER_SECTION);
            ObjectNode buyer = section instanceof ObjectNode existing ? existing : root.putObject(BUYER_SECTION);
            if (corrected.get(NAME) instanceof String name) {
                buyer.put(BUYER_NAME_FIELD, name);
            }
            if (corrected.get(ADDRESS) instanceof String address) {
                buyer.put(BUYER_ADDRESS_FIELD, address);
            }
            return json.writeValueAsString(root);
        } catch (JsonProcessingException e) {
            throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, INVALID_PLOT, e);
        }
    }

    public ResolveCustomerBillCaseResponse response(Long epdRequestId, Long historyId, String previousStatus, String status) {
        ResolveCustomerBillCaseData data = new ResolveCustomerBillCaseData();
        data.setSuccess(Boolean.TRUE);
        data.setEpdRequestId(epdRequestId);
        data.setEpdRequestHistId(historyId);
        data.setPreviousStatus(previousStatus);
        data.setStatus(status);
        ResolveCustomerBillCaseResponse response = new ResolveCustomerBillCaseResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private String serialize(Map<String, Object> value) {
        try {
            return json.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw ServiceOperationException.badRequest(INVALID_PLOT);
        }
    }
}'''

SERVICE_IMPL = '''/** Activity-logged service; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class CustomerBillCasesServiceImpl implements CustomerBillCasesService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String CASE_NOT_FOUND = "No se encontr\u00f3 el caso de error no transitorio indicado.";
    private static final String REQUEST_NOT_FOUND = "No se encontr\u00f3 la solicitud CPE asociada al caso.";
    private static final String STATUS_NOT_FOUND = "No existe el estado REGISTRADO en EPDQUERYSTATUS.";
    private static final String REGISTERED_STATUS = "REGISTRADO";

    private final NonTransientErrorRepository cases;
    private final ErrorCaseEvidenceRepository evidences;
    private final EpdRequestRepository requests;
    private final EpdRequestHistRepository history;
    private final EpdQueryStatusRepository statuses;
    private final CustomerBillCasesMapper mapper;
    private final CustomerBillCasesValidator validator;
    private final PersistenceExceptionTranslator translator;
    private final TransactionTemplate transaction;
    private final Clock clock;

    @Override
    public ResolveCustomerBillCaseResponse resolveCustomerBillCase(RequestHeaders headers, Long id, ResolveCustomerBillCaseRequest request) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validar(headers, id, request));
        NonTransientErrorEntity found = ejecutarActividad(menTran, ConstanApi.ACT2_VALIDAR_CASO_Y_OBTENER_SOLICITUD, () -> buscarCaso(menTran, id));
        return transaction.execute(status -> subsanar(menTran, headers, request, found));
    }

    private ResolveCustomerBillCaseResponse subsanar(String menTran, RequestHeaders headers, ResolveCustomerBillCaseRequest request, NonTransientErrorEntity found) {
        String user = headers != null ? headers.userId() : null;
        LocalDateTime now = LocalDateTime.now(clock);
        ejecutarActividad(menTran, ConstanApi.ACT3_GUARDAR_CASO_DE_SUBSANACION, () -> guardarEvidencia(menTran, request, found.getId(), user, now));
        EpdRequestEntity current = ejecutarActividad(menTran, ConstanApi.ACT4_OBTENER_TRAMA_VIGENTE_DEL_CPE, () -> obtenerVigente(menTran, found.getEpdRequestId()));
        Integer previousId = current.getEpdQueryStatusId();
        EpdRequestHistEntity snapshot = ejecutarActividad(menTran, ConstanApi.ACT5_REGISTRAR_SNAPSHOT_HISTORICO, () -> registrarSnapshot(menTran, current, user, now));
        String previousStatus = ejecutarActividad(menTran, ConstanApi.ACT6_ACTUALIZAR_SOLICITUD_CPE, () -> actualizar(menTran, request, current, user, now));
        return mapper.response(current.getId(), snapshot.getId(), previousStatus != null ? previousStatus : String.valueOf(previousId), REGISTERED_STATUS);
    }

    private Boolean validar(RequestHeaders headers, Long id, ResolveCustomerBillCaseRequest request) {
        log.info("resolveCustomerBillCase applicationName={}, transactionId={}, userId={}, caseId={}", headers != null ? headers.applicationName() : null,
                headers != null ? headers.transactionId() : null, headers != null ? headers.userId() : null, id);
        validator.resolution(id, request);
        return Boolean.TRUE;
    }

    private NonTransientErrorEntity buscarCaso(String menTran, Long id) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_VALIDAR_CASO_Y_OBTENER_SOLICITUD, ConstanApi.LOG_ERROR_DATOS_ACT2_VALIDAR_CASO_Y_OBTENER_SOLICITUD,
                () -> cases.findById(id).orElseThrow(() -> notFound(menTran, ConstanApi.ACT2_VALIDAR_CASO_Y_OBTENER_SOLICITUD, CASE_NOT_FOUND)));
    }

    private Boolean guardarEvidencia(String menTran, ResolveCustomerBillCaseRequest request, Long caseId, String user, LocalDateTime now) {
        ErrorCaseEvidenceEntity evidence = mapper.evidence(request, caseId, user, now);
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT3_GUARDAR_CASO_DE_SUBSANACION, ConstanApi.LOG_ERROR_DATOS_ACT3_GUARDAR_CASO_DE_SUBSANACION, () -> {
            evidences.save(evidence);
            return Boolean.TRUE;
        });
    }

    private EpdRequestEntity obtenerVigente(String menTran, Long epdRequestId) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT4_OBTENER_TRAMA_VIGENTE_DEL_CPE, ConstanApi.LOG_ERROR_DATOS_ACT4_OBTENER_TRAMA_VIGENTE_DEL_CPE, () -> {
            if (epdRequestId == null) {
                throw notFound(menTran, ConstanApi.ACT4_OBTENER_TRAMA_VIGENTE_DEL_CPE, REQUEST_NOT_FOUND);
            }
            return requests.findById(epdRequestId)
                    .orElseThrow(() -> notFound(menTran, ConstanApi.ACT4_OBTENER_TRAMA_VIGENTE_DEL_CPE, REQUEST_NOT_FOUND));
        });
    }

    private EpdRequestHistEntity registrarSnapshot(String menTran, EpdRequestEntity current, String user, LocalDateTime now) {
        EpdRequestHistEntity snapshot = mapper.snapshot(current, user, now);
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT5_REGISTRAR_SNAPSHOT_HISTORICO, ConstanApi.LOG_ERROR_DATOS_ACT5_REGISTRAR_SNAPSHOT_HISTORICO, () -> history.save(snapshot));
    }

    private String actualizar(String menTran, ResolveCustomerBillCaseRequest request, EpdRequestEntity current, String user, LocalDateTime now) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT6_ACTUALIZAR_SOLICITUD_CPE, ConstanApi.LOG_ERROR_DATOS_ACT6_ACTUALIZAR_SOLICITUD_CPE, () -> {
            EpdQueryStatusEntity registered = statuses.findFirstByValue(REGISTERED_STATUS).orElseThrow(() -> {
                log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT6_ACTUALIZAR_SOLICITUD_CPE, HttpStatus.INTERNAL_SERVER_ERROR.value(), STATUS_NOT_FOUND);
                return new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, STATUS_NOT_FOUND);
            });
            final String previous = current.getEpdQueryStatusId() == null ? null : statuses.findById(current.getEpdQueryStatusId().longValue()).map(EpdQueryStatusEntity::getValue).orElse(null);
            current.setPlotSovos(mapper.correctedPlot(current.getPlotSovos(), request.getDataCorrected()));
            current.setEpdQueryStatusId(registered.getId().intValue());
            current.setLastModifiedUser(user);
            current.setLastModifiedDate(now);
            requests.save(current);
            return previous;
        });
    }

    private ServiceOperationException notFound(String menTran, String actividad, String detail) {
        log.error(ERROR_BUSINESS_PATTERN, menTran, actividad, HttpStatus.NOT_FOUND.value(), detail);
        return new ServiceOperationException(HttpStatus.NOT_FOUND, detail);
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

HANDLER = '''@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String TRANSACTION_HEADER = "x-correlation-id";
    private static final Set<HttpStatus> DECLARED = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.INTERNAL_SERVER_ERROR,
            HttpStatus.SERVICE_UNAVAILABLE, HttpStatus.GATEWAY_TIMEOUT);

    private final PersistenceExceptionTranslator translator;

    public GlobalExceptionHandler(PersistenceExceptionTranslator translator) {
        this.translator = translator;
    }

    @ExceptionHandler(ServiceOperationException.class)
    public ResponseEntity<ErrorResponse> operationFailure(ServiceOperationException failure, WebRequest request) {
        HttpStatus status = declared(failure.getStatus());
        logValidationFailure(request, status, failure.getMessage());
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(error(status));
    }

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ErrorResponse> constraintFailure(ConstraintViolationException failure, WebRequest request) {
        logValidationFailure(request, HttpStatus.BAD_REQUEST, failure.getMessage());
        return ResponseEntity.badRequest().contentType(MediaType.APPLICATION_JSON).body(error(HttpStatus.BAD_REQUEST));
    }

    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<ErrorResponse> unexpectedFailure(RuntimeException failure, WebRequest request) {
        return operationFailure(translator.translate(failure), request);
    }

    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception ex, @Nullable Object body,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        HttpStatus resolved = declared(HttpStatus.valueOf(status.value()));
        logValidationFailure(request, resolved, ex.getClass().getSimpleName());
        HttpHeaders json = new HttpHeaders();
        json.putAll(headers);
        json.setContentType(MediaType.APPLICATION_JSON);
        return new ResponseEntity<>(error(resolved), json, resolved);
    }

    /** A status that the operation does not declare is never emitted: it becomes an internal error. */
    private HttpStatus declared(HttpStatus status) {
        return DECLARED.contains(status) ? status : HttpStatus.INTERNAL_SERVER_ERROR;
    }

    private void logValidationFailure(WebRequest request, HttpStatus status, String reason) {
        if (status != HttpStatus.BAD_REQUEST) {
            return;
        }
        String tx = request.getHeader(TRANSACTION_HEADER);
        String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
        ActivityLogger.inicioActividad(log, menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA);
        log.error("{} ERROR [{}] code={} detail={}", menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, status.value(), reason);
        ActivityLogger.finActividad(log, menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA);
    }

    private ErrorResponse error(HttpStatus status) {
        ErrorResponse error = new ErrorResponse();
        error.setCode(status.value());
        switch (status) {
            case BAD_REQUEST -> describe(error, "Bad request", "INVALID_REQUEST", "Los datos de la solicitud no son v\\u00e1lidos.");
            case SERVICE_UNAVAILABLE -> describe(error, "Service unavailable", "SERVICE_UNAVAILABLE", "El servicio no se encuentra disponible temporalmente.");
            case GATEWAY_TIMEOUT -> describe(error, "Gateway timeout", "GATEWAY_TIMEOUT", "Se agot\\u00f3 el tiempo de espera de la solicitud.");
            default -> describe(error, "Internal server error", "INTERNAL_ERROR", "Se produjo un error interno al procesar la solicitud.");
        }
        return error;
    }

    private void describe(ErrorResponse error, String message, String code, String detail) {
        ErrorItem item = new ErrorItem();
        item.setCode(code);
        item.setMessage(detail);
        error.setMessage(message);
        error.setErrors(List.of(item));
    }
}'''


def api():
    out = ['/** Define el contrato del endpoint REST de subsanacion de casos de error no transitorio (contrato OpenAPI). */', 'public interface CustomerBillCasesApi {', '    /**',
           '     * Subsana un caso de error no transitorio.', '     *', '     * @param id Identificador del caso en NONTRANSIENTERROR.', '     * @param request Datos para subsanar el caso.']
    out += [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    out += ['     * @return respuesta HTTP con el modelo ResolveCustomerBillCaseResponse definido en el contrato', '     */',
            '    @PostMapping(path = "/api/v1/orq-customerBillCases/cases/{id}/resolution", consumes = {"application/json"}, produces = {"application/json"})',
            '    @Operation(summary = "Subsanar un caso de error no transitorio.")', '    @ApiResponses({']
    rows = ['      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ResolveCustomerBillCaseResponse.class)))']
    rows += [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS[c]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for c in ('400', '500', '503', '504')]
    out += [',\n'.join(rows), '    })', '    ResponseEntity<ResolveCustomerBillCaseResponse> resolveCustomerBillCase(']
    args = ['            @PathVariable("id") Long id', '            @RequestBody ResolveCustomerBillCaseRequest request'] + [f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS]
    out += [',\n'.join(args) + ');', '}']
    return '\n'.join(out)


def controller():
    args = ['            Long id', '            ResolveCustomerBillCaseRequest request'] + [f'            String {c}' for _, c, _ in dj.HEADERS]
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class CustomerBillCasesController implements CustomerBillCasesApi {', '    private final CustomerBillCasesService service;', '',
                      '    @Override', '    public ResponseEntity<ResolveCustomerBillCaseResponse> resolveCustomerBillCase(', ',\n'.join(args) + ') {',
                      '        log.info("resolveCustomerBillCase - transactionId: {}", xCorrelationId);', '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);',
                      '        return ResponseEntity.ok(service.resolveCustomerBillCase(headers, id, request));', '    }', '}'])


TRANSACTION_CONFIG = '''/** Programmatic transaction boundary of the whole resolution (activities 3 to 6). */
@Configuration
public class TransactionConfig {
    @Bean
    public TransactionTemplate transactionTemplate(PlatformTransactionManager manager) {
        return new TransactionTemplate(manager);
    }
}'''


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    for cls, (table, fields) in ENTITIES.items():
        body = dj.entity(cls, table, fields)
        if cls == 'EpdRequestHistEntity':
            body = body.replace('    @GeneratedValue(strategy = GenerationType.IDENTITY)',
                                '    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "epdRequestHistSeq")\n    @SequenceGenerator(name = "epdRequestHistSeq", sequenceName = "FACEL.SEQ_EPDREQUESTHIST", allocationSize = 1)')
        elif cls != 'ErrorCaseEvidenceEntity':
            body = body.replace('    @GeneratedValue(strategy = GenerationType.IDENTITY)\n', '')
        put('model', cls, body)
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    for cls, fields in REQUEST_DTOS.items():
        put('dto.request', cls, dj.dto(cls, fields))
    for cls, fields in DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields, non_null=cls != 'ErrorItem'))
    put('dto.response', 'ResolveCustomerBillCaseResponse', dj.envelope('ResolveCustomerBillCaseResponse', 'ResolveCustomerBillCaseData'))
    put('dto.response', 'ErrorResponse', '@Data\npublic class ErrorResponse {\n    private Integer code;\n    private String message;\n    private List<ErrorItem> errors;\n}')
    put('dto.mapper', 'CustomerBillCasesMapper', MAPPER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', HANDLER)
    for cls, body in REPOS.items():
        put('repository', cls, body)
    put('service', 'CustomerBillCasesService', SERVICE_IF)
    put('service.impl', 'CustomerBillCasesServiceImpl', SERVICE_IMPL)
    put('validation', 'CustomerBillCasesValidator', VALIDATOR)
    put('controller', 'CustomerBillCasesApi', api())
    put('controller.impl', 'CustomerBillCasesController', controller())
    put('configuration', 'ClockConfig', dj.CLOCK_CONFIG)
    put('configuration', 'TransactionConfig', TRANSACTION_CONFIG)
    return files


ORIGINAL_CONSTANTS = dj.activity_constants


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False),
                     ('ACT2_VALIDAR_CASO_Y_OBTENER_SOLICITUD', 'VALIDAR_CASO_Y_OBTENER_SOLICITUD', True),
                     ('ACT3_GUARDAR_CASO_DE_SUBSANACION', 'GUARDAR_CASO_DE_SUBSANACION', True),
                     ('ACT4_OBTENER_TRAMA_VIGENTE_DEL_CPE', 'OBTENER_TRAMA_VIGENTE_DEL_CPE', True),
                     ('ACT5_REGISTRAR_SNAPSHOT_HISTORICO', 'REGISTRAR_SNAPSHOT_HISTORICO', True),
                     ('ACT6_ACTUALIZAR_SOLICITUD_CPE', 'ACTUALIZAR_SOLICITUD_CPE', True)]
    try:
        return ORIGINAL_CONSTANTS()
    finally:
        dj.ACTIVITIES = saved


TESTS = {}
TESTS['CustomerBillCasesValidatorTest'] = ('validation', '''class CustomerBillCasesValidatorTest {
    private static final Long ID = 15L;
    private static final int TOO_LONG = 256;

    private final CustomerBillCasesValidator validator = new CustomerBillCasesValidator();

    private ResolveCustomerBillCaseRequest request(String user, Map<String, Object> data, String note) {
        ResolveCustomerBillCaseRequest request = new ResolveCustomerBillCaseRequest();
        request.setAssignedUserId(user);
        request.setDataCorrected(data);
        request.setNote(note);
        return request;
    }

    private HttpStatus failure(Long id, ResolveCustomerBillCaseRequest request) {
        return assertThrows(ServiceOperationException.class, () -> validator.resolution(id, request)).getStatus();
    }

    @Test
    void acceptsAValidRequest() {
        validator.resolution(ID, request("USER", Map.of("nombre", "ACME", "direccion", "AV 1"), "nota"));
        validator.resolution(ID, request("USER", Map.of(), null));
    }

    @Test
    void rejectsMissingIdentifierBodyUserOrData() {
        assertEquals(HttpStatus.BAD_REQUEST, failure(null, request("USER", Map.of(), null)));
        assertEquals(HttpStatus.BAD_REQUEST, failure(0L, request("USER", Map.of(), null)));
        assertEquals(HttpStatus.BAD_REQUEST, failure(ID, null));
        assertEquals(HttpStatus.BAD_REQUEST, failure(ID, request(null, Map.of(), null)));
        assertEquals(HttpStatus.BAD_REQUEST, failure(ID, request(" ", Map.of(), null)));
        assertEquals(HttpStatus.BAD_REQUEST, failure(ID, request("USER", null, null)));
    }

    @Test
    void rejectsALongNoteAndInvalidCorrections() {
        assertEquals(HttpStatus.BAD_REQUEST, failure(ID, request("USER", Map.of(), "x".repeat(TOO_LONG))));
        assertEquals(HttpStatus.BAD_REQUEST, failure(ID, request("USER", Map.of("nombre", " "), null)));
        assertEquals(HttpStatus.BAD_REQUEST, failure(ID, request("USER", Map.of("direccion", true), null)));
    }
}''')
TESTS['CustomerBillCasesMapperTest'] = ('dto.mapper', '''class CustomerBillCasesMapperTest {
    private static final Long ID = 10L;
    private static final Long CASE_ID = 7L;
    private static final Integer STATUS = 3;

    private final CustomerBillCasesMapper mapper = new CustomerBillCasesMapper();

    @Test
    void correctedPlotReplacesOnlyTheInformedFields() {
        String plot = "{\\"EN\\":{\\"EN19_RazonSocialAdquiriente\\":\\"OLD\\",\\"EN20_DireccionAdquiriente\\":\\"OLD ADDR\\",\\"EN21\\":\\"keep\\"},\\"other\\":1}";
        String result = mapper.correctedPlot(plot, Map.of("nombre", "NEW"));
        assertTrue(result.contains("\\"EN19_RazonSocialAdquiriente\\":\\"NEW\\""));
        assertTrue(result.contains("\\"EN20_DireccionAdquiriente\\":\\"OLD ADDR\\""));
        assertTrue(result.contains("\\"EN21\\":\\"keep\\""));
        assertTrue(result.contains("\\"other\\":1"));
    }

    @Test
    void correctedPlotCreatesTheBuyerSectionWhenMissing() {
        String result = mapper.correctedPlot(null, Map.of("direccion", "AV 1"));
        assertEquals("{\\"EN\\":{\\"EN20_DireccionAdquiriente\\":\\"AV 1\\"}}", result);
    }

    @Test
    void correctedPlotRejectsInvalidStoredJson() {
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> mapper.correctedPlot("not-json", Map.of())).getStatus());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> mapper.correctedPlot("[1]", Map.of())).getStatus());
    }

    @Test
    void evidenceKeepsTheReceivedValuesAndAudit() {
        ResolveCustomerBillCaseRequest request = new ResolveCustomerBillCaseRequest();
        request.setNote("nota");
        request.setAssignedUserId("USER");
        request.setDataCorrected(Map.of("nombre", "ACME"));
        LocalDateTime now = LocalDateTime.parse("2026-10-12T10:15:30");
        ErrorCaseEvidenceEntity evidence = mapper.evidence(request, CASE_ID, "creator", now);
        assertEquals("nota", evidence.getComentReference());
        assertEquals("USER", evidence.getAssignedUserId());
        assertEquals(CASE_ID, evidence.getNonTransientErrorId());
        assertEquals("{\\"nombre\\":\\"ACME\\"}", evidence.getDataCorrected());
        assertEquals("creator", evidence.getCreationUser());
        assertEquals(now, evidence.getCreationDate());
    }

    @Test
    void snapshotCopiesTheCurrentValuesAndAudit() {
        EpdRequestEntity current = new EpdRequestEntity();
        current.setId(ID);
        current.setEpdQueryStatusId(STATUS);
        current.setInputPayload("{}");
        LocalDateTime now = LocalDateTime.parse("2026-10-12T10:15:30");
        EpdRequestHistEntity snapshot = mapper.snapshot(current, "user", now);
        assertEquals(ID, snapshot.getEpdRequestId());
        assertNull(snapshot.getId());
        assertEquals(STATUS, snapshot.getEpdQueryStatusId());
        assertEquals("user", snapshot.getCreationUser());
        assertEquals(now, snapshot.getCreationDate());
    }

    @Test
    void responseExposesTheContractFields() {
        ResolveCustomerBillCaseResponse response = mapper.response(ID, CASE_ID, "PROCESADO", "REGISTRADO");
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertTrue(response.getData().getSuccess());
        assertEquals(ID, response.getData().getEpdRequestId());
        assertEquals(CASE_ID, response.getData().getEpdRequestHistId());
        assertEquals("PROCESADO", response.getData().getPreviousStatus());
        assertEquals("REGISTRADO", response.getData().getStatus());
    }
}''')
TESTS['GlobalExceptionHandlerTest'] = ('exception', '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request() {
        return new ServletWebRequest(new MockHttpServletRequest("POST", "/api/v1/orq-customerBillCases/cases/1/resolution"));
    }

    @Test
    void badRequestUsesTheContractShape() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request());
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("Bad request", response.getBody().getMessage());
        assertEquals("INVALID_REQUEST", response.getBody().getErrors().get(0).getCode());
    }

    @Test
    void undeclaredStatusesBecomeInternalError() {
        ResponseEntity<ErrorResponse> notFound = handler.operationFailure(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"), request());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), notFound.getStatusCode().value());
        assertEquals("INTERNAL_ERROR", notFound.getBody().getErrors().get(0).getCode());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), handler.operationFailure(new ServiceOperationException(HttpStatus.CONFLICT, "dup"), request()).getStatusCode().value());
    }

    @Test
    void unexpectedFailuresBecomeInternalError() {
        ResponseEntity<ErrorResponse> response = handler.unexpectedFailure(new IllegalStateException("boom"), request());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), response.getStatusCode().value());
    }

    @Test
    void timeoutAndUnavailabilityAreDeclared() {
        ResponseEntity<ErrorResponse> timeout = handler.operationFailure(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"), request());
        assertEquals(HttpStatus.GATEWAY_TIMEOUT.value(), timeout.getStatusCode().value());
        assertEquals("GATEWAY_TIMEOUT", timeout.getBody().getErrors().get(0).getCode());
        ResponseEntity<ErrorResponse> unavailable = handler.operationFailure(new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, "down"), request());
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE.value(), unavailable.getStatusCode().value());
        assertEquals("SERVICE_UNAVAILABLE", unavailable.getBody().getErrors().get(0).getCode());
    }
}''')
TESTS['CustomerBillCasesServiceImplTest'] = ('service.impl', '''class CustomerBillCasesServiceImplTest {
    private static final Long ID = 15L;
    private static final Long REQUEST_ID = 564L;
    private static final Long HIST_ID = 13321L;
    private static final Long PREVIOUS = 4L;
    private static final Long REGISTERED = 1L;

    private final NonTransientErrorRepository cases = Mockito.mock(NonTransientErrorRepository.class);
    private final ErrorCaseEvidenceRepository evidences = Mockito.mock(ErrorCaseEvidenceRepository.class);
    private final EpdRequestRepository requests = Mockito.mock(EpdRequestRepository.class);
    private final EpdRequestHistRepository history = Mockito.mock(EpdRequestHistRepository.class);
    private final EpdQueryStatusRepository statuses = Mockito.mock(EpdQueryStatusRepository.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-12T10:15:30Z"), ZoneOffset.UTC);
    private final CustomerBillCasesServiceImpl service = new CustomerBillCasesServiceImpl(cases, evidences, requests, history, statuses, new CustomerBillCasesMapper(),
            new CustomerBillCasesValidator(), new PersistenceExceptionTranslator(), new TransactionTemplate(Mockito.mock(PlatformTransactionManager.class)), clock);
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");

    private ResolveCustomerBillCaseRequest request() {
        ResolveCustomerBillCaseRequest request = new ResolveCustomerBillCaseRequest();
        request.setAssignedUserId("USER");
        request.setNote("nota");
        request.setDataCorrected(Map.of("nombre", "NEW"));
        return request;
    }

    private EpdRequestEntity stubCase() {
        NonTransientErrorEntity found = new NonTransientErrorEntity();
        found.setId(ID);
        found.setEpdRequestId(REQUEST_ID);
        EpdRequestEntity current = new EpdRequestEntity();
        current.setId(REQUEST_ID);
        current.setEpdQueryStatusId(PREVIOUS.intValue());
        current.setPlotSovos("{\\"EN\\":{\\"EN19_RazonSocialAdquiriente\\":\\"OLD\\"}}");
        EpdQueryStatusEntity registered = new EpdQueryStatusEntity();
        registered.setId(REGISTERED);
        registered.setValue("REGISTRADO");
        EpdQueryStatusEntity previous = new EpdQueryStatusEntity();
        previous.setId(PREVIOUS);
        previous.setValue("PROCESADO");
        Mockito.when(cases.findById(ID)).thenReturn(Optional.of(found));
        Mockito.when(requests.findById(REQUEST_ID)).thenReturn(Optional.of(current));
        Mockito.when(statuses.findFirstByValue("REGISTRADO")).thenReturn(Optional.of(registered));
        Mockito.when(statuses.findById(PREVIOUS)).thenReturn(Optional.of(previous));
        Mockito.when(history.save(ArgumentMatchers.any(EpdRequestHistEntity.class))).thenAnswer(call -> {
            EpdRequestHistEntity saved = call.getArgument(0);
            saved.setId(HIST_ID);
            return saved;
        });
        return current;
    }

    @Test
    void resolvesTheCaseInOrderAndReturnsTheContractData() {
        final EpdRequestEntity current = stubCase();
        ResolveCustomerBillCaseResponse response = service.resolveCustomerBillCase(headers, ID, request());
        assertEquals(REQUEST_ID, response.getData().getEpdRequestId());
        assertEquals(HIST_ID, response.getData().getEpdRequestHistId());
        assertEquals("PROCESADO", response.getData().getPreviousStatus());
        assertEquals("REGISTRADO", response.getData().getStatus());
        assertEquals(REGISTERED.intValue(), current.getEpdQueryStatusId());
        assertEquals("user", current.getLastModifiedUser());
        assertEquals(LocalDateTime.parse("2026-10-12T10:15:30"), current.getLastModifiedDate());
        assertTrue(current.getPlotSovos().contains("\\"EN19_RazonSocialAdquiriente\\":\\"NEW\\""));
        InOrder order = Mockito.inOrder(evidences, history, requests);
        order.verify(evidences).save(ArgumentMatchers.any(ErrorCaseEvidenceEntity.class));
        order.verify(history).save(ArgumentMatchers.any(EpdRequestHistEntity.class));
        order.verify(requests).save(current);
    }

    @Test
    void theSnapshotKeepsTheStatusBeforeTheUpdate() {
        stubCase();
        service.resolveCustomerBillCase(headers, ID, request());
        ArgumentCaptor<EpdRequestHistEntity> captor = ArgumentCaptor.forClass(EpdRequestHistEntity.class);
        Mockito.verify(history).save(captor.capture());
        assertEquals(PREVIOUS.intValue(), captor.getValue().getEpdQueryStatusId());
        assertEquals(REQUEST_ID, captor.getValue().getEpdRequestId());
    }

    @Test
    void anUnknownCaseIsNotFoundAndNothingIsWritten() {
        Mockito.when(cases.findById(ID)).thenReturn(Optional.empty());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.resolveCustomerBillCase(headers, ID, request())).getStatus());
        Mockito.verifyNoInteractions(evidences, history, requests);
    }

    @Test
    void aMissingRequestFailsAfterTheEvidenceSoTheTransactionRollsBack() {
        stubCase();
        Mockito.when(requests.findById(REQUEST_ID)).thenReturn(Optional.empty());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.resolveCustomerBillCase(headers, ID, request())).getStatus());
        Mockito.verify(evidences).save(ArgumentMatchers.any(ErrorCaseEvidenceEntity.class));
        Mockito.verifyNoInteractions(history);
    }

    @Test
    void invalidBodyFailsBeforeTouchingTheDatabase() {
        ResolveCustomerBillCaseRequest invalid = new ResolveCustomerBillCaseRequest();
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.resolveCustomerBillCase(headers, ID, invalid)).getStatus());
        Mockito.verifyNoInteractions(cases);
    }

    @Test
    void aMissingRegisteredStatusIsAnInternalError() {
        stubCase();
        Mockito.when(statuses.findFirstByValue("REGISTRADO")).thenReturn(Optional.empty());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, assertThrows(ServiceOperationException.class, () -> service.resolveCustomerBillCase(headers, ID, request())).getStatus());
    }

    @Test
    void timeoutsBecomeGatewayTimeout() {
        stubCase();
        Mockito.when(evidences.save(ArgumentMatchers.any(ErrorCaseEvidenceEntity.class))).thenThrow(new QueryTimeoutException("slow"));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> service.resolveCustomerBillCase(headers, ID, request())).getStatus());
        Mockito.verifyNoInteractions(history);
    }
}''')
TESTS['CustomerBillCasesApiContractTest'] = ('controller', '''class CustomerBillCasesApiContractTest {
    private static final Long ID = 564L;

    private final CustomerBillCasesService service = Mockito.mock(CustomerBillCasesService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new CustomerBillCasesController(service))
            .setControllerAdvice(new GlobalExceptionHandler(new PersistenceExceptionTranslator()))
            .build();

    private MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder) {
        return builder.header("traceparent", "t")
                .header("x-app-id", "app")
                .header("x-channel", "web")
                .header("x-client-version-id", "1")
                .header("x-correlation-id", "tx")
                .header("x-request-id", "req")
                .header("x-user-id", "user");
    }

    private MockHttpServletRequestBuilder post(String path, String body) {
        return withHeaders(MockMvcRequestBuilders.post(path)).contentType(MediaType.APPLICATION_JSON).content(body);
    }

    @Test
    void postReturnsTheEnvelope() throws Exception {
        ResolveCustomerBillCaseData data = new ResolveCustomerBillCaseData();
        data.setSuccess(true);
        data.setEpdRequestId(ID);
        ResolveCustomerBillCaseResponse response = new ResolveCustomerBillCaseResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("ok");
        response.setData(data);
        Mockito.when(service.resolveCustomerBillCase(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(1L), ArgumentMatchers.any(ResolveCustomerBillCaseRequest.class))).thenReturn(response);
        mvc.perform(post("/api/v1/orq-customerBillCases/cases/1/resolution", "{\\"assignedUserId\\": \\"U\\", \\"dataCorrected\\": {\\"nombre\\": \\"A\\"}}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.message").value("ok")).andExpect(jsonPath("$.data.epdRequestId").value(ID)).andExpect(jsonPath("$.data.success").value(true));
    }

    @Test
    void aMissingHeaderIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(MockMvcRequestBuilders.post("/api/v1/orq-customerBillCases/cases/1/resolution").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("Bad request"))
                .andExpect(jsonPath("$.errors[0].code").value("INVALID_REQUEST"));
    }

    @Test
    void aNonNumericIdentifierIsABadRequest() throws Exception {
        mvc.perform(post("/api/v1/orq-customerBillCases/cases/abc/resolution", "{}")).andExpect(status().isBadRequest());
    }

    @Test
    void aMalformedBodyIsABadRequest() throws Exception {
        mvc.perform(post("/api/v1/orq-customerBillCases/cases/1/resolution", "not-json")).andExpect(status().isBadRequest());
    }

    @Test
    void serviceFailuresKeepTheirDeclaredStatus() throws Exception {
        Mockito.when(service.resolveCustomerBillCase(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(1L), ArgumentMatchers.any(ResolveCustomerBillCaseRequest.class)))
                .thenThrow(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"));
        mvc.perform(post("/api/v1/orq-customerBillCases/cases/1/resolution", "{}")).andExpect(status().isGatewayTimeout()).andExpect(jsonPath("$.errors[0].code").value("GATEWAY_TIMEOUT"));
    }
}''')


def build_tests(pkg):
    import dom_cpe_request_tests as dt
    files = {}
    for name, (suffix, body) in TESTS.items():
        statics = list(dt.MVC_STATICS) if name == 'CustomerBillCasesApiContractTest' else dt.ASSERT
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.orq.customerbillcases and application class OrqCustomerBillCasesApplication are technical choices; no source defines them.'),
    ('A-02', 'Swagger governs (approved delegated decision): only 200/400/500/503/504 are emitted with the Swagger ErrorResponse shape (code, message, errors[]). The Sparx 401/403 and the 404 for a missing case or CPE request are not declared, so they surface as 500.'),
    ('A-03', 'NONTRANSIENTERROR has no table definition in Sparx; only ID and EPDREQUESTID (cited by the activities) are mapped, read-only. EPDQUERYSTATUS is mapped with ID and VALUE and the REGISTRADO status is looked up by VALUE = REGISTRADO.'),
    ('A-04', 'note is persisted in ERRORCASEEVIDENCE.COMENTREFERENCE (the column in the table definition) although Sparx names it NOTE. DATACORRECTED stores the corrected-data JSON as received.'),
    ('A-05', 'ERRORCASEEVIDENCE.ID has no documented sequence: it is mapped as an identity column. EPDREQUESTHIST.ID uses sequence FACEL.SEQ_EPDREQUESTHIST (as in emission-cpehist).'),
    ('A-06', 'EPDREQUESTHIST has no PLOTSOVOS or SNAPSHOTDATE column in its table definition: the original SOVOS plot and the snapshot date are not persisted in the history row; CREATIONDATE carries the snapshot instant (injectable Clock, never SYSDATE). STATUSFROMID, STATUSTOID, STATUSCHANGEDATE and STATUSCHANGEORIGIN are not written (no Sparx mapping).'),
    ('A-07', 'The correction mapping nombre -> EN.EN19_RazonSocialAdquiriente and direccion -> EN.EN20_DireccionAdquiriente is applied to the PLOTSOVOS JSON; Sparx marks it as pending confirmation. A missing plot starts as an empty object; a stored plot that is not a JSON object is an internal error.'),
    ('A-08', 'The creation/modification user is the x-user-id header (Sparx: identity from the service context). previousStatus is the VALUE of the previous EPDQUERYSTATUS row, or its identifier when the row cannot be found.'),
    ('A-09', 'Activities 3 to 6 run in one local transaction (TransactionTemplate); any failure rolls back evidence, history and update. No external service is called and the SOVOS resend remains the batch_invoiceResend process.'),
]


def main(argv=None):
    sys.modules['dom_invoice_java'] = types.SimpleNamespace()
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, 'OrqCustomerBillCasesApplication', ASSUMPTIONS, 'orq-customer-bill-cases-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': 'OrqCustomerBillCasesApplication'}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'orq_customer_bill_cases_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main(argv) if argv is not None else dm.main()


if __name__ == '__main__':
    sys.exit(main())

