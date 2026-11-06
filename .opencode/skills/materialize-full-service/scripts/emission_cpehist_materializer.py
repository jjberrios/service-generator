"""Deterministic materializer of the emission-cpehist service (JPA profile of claro-spring-ms): one POST that copies an EPDREQUEST row into EPDREQUESTHIST.

Reuses the machinery of dom_cpe_request_materializer (gate recomputed first, archetype assembly, file protection, per-service lock, manifest last).

Usage: python emission_cpehist_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import re
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402

PACKAGE = 'com.claro.emission.cpehist'
dj.EXTERNAL['SequenceGenerator'] = 'jakarta.persistence.SequenceGenerator'
ENTITIES = {
    'EpdRequestEntity': ('EPDREQUEST', [
        ('Long', 'id', 'ID', 'id'), ('String', 'uniqueReferenceCod', 'UNIQUEREFERENCECOD', ''), ('Integer', 'epdTypeId', 'EPDTYPEID', ''),
        ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''), ('Integer', 'generationType', 'GENERATIONTYPE', ''), ('Integer', 'actionType', 'ACTIONTYPE', ''),
        ('String', 'inputPayload', 'INPUTPAYLOAD', 'lob'), ('String', 'installmentSchedulePayload', 'INSTALLMENTSCHEDULEPAYLOAD', 'lob'),
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
REQUEST_DTOS = {'CreateEmissionCpeHistRequest': [('Long', 'epdRequestId')]}
DTOS = {'CreateEmissionCpeHistData': [('Long', 'id'), ('Long', 'epdRequestId'), ('LocalDateTime', 'snapshotDate')]}
dj.register('model', *ENTITIES)
dj.register('dto.request', *REQUEST_DTOS)
dj.register('dto.response', *DTOS, 'CreateEmissionCpeHistResponse')
dj.register('dto.mapper', 'EmissionCpeHistMapper')
dj.register('repository', 'EpdRequestRepository', 'EpdRequestHistRepository')
dj.register('service', 'EmissionCpeHistService')
dj.register('service.impl', 'EmissionCpeHistServiceImpl')
dj.register('validation', 'EmissionCpeHistValidator')
dj.register('controller', 'EmissionCpeHistApi')
dj.register('controller.impl', 'EmissionCpeHistController')

REPOS = {
    'EpdRequestRepository': '''@Repository
public interface EpdRequestRepository extends JpaRepository<EpdRequestEntity, Long> {
}''',
    'EpdRequestHistRepository': '''@Repository
public interface EpdRequestHistRepository extends JpaRepository<EpdRequestHistEntity, Long> {
}''',
}

SERVICE_IF = '''/** Registro de snapshots historicos de solicitudes CPE. */
public interface EmissionCpeHistService {
    CreateEmissionCpeHistResponse createEmissionCpeHist(RequestHeaders headers, CreateEmissionCpeHistRequest request);
}'''

VALIDATOR = '''/** Declared contract rules: the body is required and epdRequestId must be a positive identifier. */
@Component
public class EmissionCpeHistValidator {
    private static final String INVALID_REQUEST_ID = "El campo epdRequestId es obligatorio o presenta un valor no v\u00e1lido.";

    public Long epdRequestId(CreateEmissionCpeHistRequest request) {
        Long id = request == null ? null : request.getEpdRequestId();
        if (id == null || id <= 0) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST_ID);
        }
        return id;
    }
}'''

MAPPER = '''/** Explicit mapping between the current request row, the history row and the API contract. */
@Component
public class EmissionCpeHistMapper {
    private static final String SUCCESS_MESSAGE = "Operaci\u00f3n exitosa";

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

    public CreateEmissionCpeHistResponse response(EpdRequestHistEntity saved) {
        CreateEmissionCpeHistData data = new CreateEmissionCpeHistData();
        data.setId(saved.getId());
        data.setEpdRequestId(saved.getEpdRequestId());
        data.setSnapshotDate(saved.getCreationDate());
        CreateEmissionCpeHistResponse response = new CreateEmissionCpeHistResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }
}'''

SERVICE_IMPL = '''/** Activity-logged service; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class EmissionCpeHistServiceImpl implements EmissionCpeHistService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String NOT_FOUND_DETAIL = "No se encontr\u00f3 la solicitud CPE asociada al epdRequestId indicado.";

    private final EpdRequestRepository requests;
    private final EpdRequestHistRepository history;
    private final EmissionCpeHistMapper mapper;
    private final EmissionCpeHistValidator validator;
    private final PersistenceExceptionTranslator translator;
    private final Clock clock;

    @Override
    public CreateEmissionCpeHistResponse createEmissionCpeHist(RequestHeaders headers, CreateEmissionCpeHistRequest request) {
        String menTran = prefix(headers);
        Long id = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validar(headers, request));
        ejecutarActividad(menTran, ConstanApi.ACT2_VALIDAR_EXISTENCIA_EPDREQUEST, () -> validarExistencia(menTran, id));
        EpdRequestEntity current = ejecutarActividad(menTran, ConstanApi.ACT3_OBTENER_DATOS_VIGENTES, () -> obtenerVigente(menTran, id));
        EpdRequestHistEntity saved = ejecutarActividad(menTran, ConstanApi.ACT4_CREAR_SNAPSHOT_HISTORICO, () -> crearSnapshot(menTran, headers, current));
        return mapper.response(saved);
    }

    private Long validar(RequestHeaders headers, CreateEmissionCpeHistRequest request) {
        log.info(
                "createEmissionCpeHist applicationName={}, transactionId={}, userId={}, epdRequestId={}",
                headers != null ? headers.applicationName() : null,
                headers != null ? headers.transactionId() : null,
                headers != null ? headers.userId() : null,
                request != null ? request.getEpdRequestId() : null
        );
        return validator.epdRequestId(request);
    }

    private Boolean validarExistencia(String menTran, Long id) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_VALIDAR_EXISTENCIA_EPDREQUEST, ConstanApi.LOG_ERROR_DATOS_ACT2_VALIDAR_EXISTENCIA_EPDREQUEST, () -> {
            if (!requests.existsById(id)) {
                log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT2_VALIDAR_EXISTENCIA_EPDREQUEST, HttpStatus.NOT_FOUND.value(), NOT_FOUND_DETAIL);
                throw new ServiceOperationException(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);
            }
            return Boolean.TRUE;
        });
    }

    private EpdRequestEntity obtenerVigente(String menTran, Long id) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT3_OBTENER_DATOS_VIGENTES, ConstanApi.LOG_ERROR_DATOS_ACT3_OBTENER_DATOS_VIGENTES, () -> requests.findById(id).orElseThrow(() -> {
            log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT3_OBTENER_DATOS_VIGENTES, HttpStatus.NOT_FOUND.value(), NOT_FOUND_DETAIL);
            return new ServiceOperationException(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);
        }));
    }

    private EpdRequestHistEntity crearSnapshot(String menTran, RequestHeaders headers, EpdRequestEntity current) {
        String user = headers != null ? headers.userId() : null;
        EpdRequestHistEntity snapshot = mapper.snapshot(current, user, LocalDateTime.now(clock));
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT4_CREAR_SNAPSHOT_HISTORICO, ConstanApi.LOG_ERROR_DATOS_ACT4_CREAR_SNAPSHOT_HISTORICO, () -> history.save(snapshot));
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


def api():
    out = ['/** Define el contrato del endpoint REST de registro de snapshots historicos de solicitudes CPE (contrato OpenAPI). */', 'public interface EmissionCpeHistApi {', '    /**',
           '     * Registra un snapshot historico de una solicitud CPE.', '     *', '     * @param request Datos de la solicitud CPE a capturar.']
    out += [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    out += ['     * @return respuesta HTTP con el modelo CreateEmissionCpeHistResponse definido en el contrato', '     */',
            '    @PostMapping(path = "/api/v1/emisioneshist", consumes = {"application/json"}, produces = {"application/json"})',
            '    @Operation(summary = "Registra un snapshot hist\u00f3rico de una solicitud CPE.")', '    @ApiResponses({']
    rows = ['      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = CreateEmissionCpeHistResponse.class)))']
    rows += [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS[c]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for c in ('400', '404', '500', '503', '504')]
    out += [',\n'.join(rows), '    })', '    ResponseEntity<CreateEmissionCpeHistResponse> createEmissionCpeHist(']
    args = ['            @RequestBody CreateEmissionCpeHistRequest request'] + [f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS]
    out += [',\n'.join(args) + ');', '}']
    return '\n'.join(out)


def controller():
    args = ['            CreateEmissionCpeHistRequest request'] + [f'            String {c}' for _, c, _ in dj.HEADERS]
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class EmissionCpeHistController implements EmissionCpeHistApi {', '    private final EmissionCpeHistService service;', '',
                      '    @Override', '    public ResponseEntity<CreateEmissionCpeHistResponse> createEmissionCpeHist(', ',\n'.join(args) + ') {',
                      '        log.info("createEmissionCpeHist - transactionId: {}", xCorrelationId);', '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);',
                      '        return ResponseEntity.ok(service.createEmissionCpeHist(headers, request));', '    }', '}'])


def handler():
    text = dj.HANDLER
    text = re.sub(r'    private String operationMessage\(.*?\n    }\n\n    private String method', '    private String operationMessage(String method, String uri, HttpStatus status) {\n        return "PROCESCREATIONEMISSIONCPEHIST_SERVICE_ERROR";\n    }\n\n    private String method', text, flags=re.S)
    text = text.replace('Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.CONFLICT,', 'Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.NOT_FOUND,')
    text = re.sub(r'(case BAD_REQUEST -> describe\(error, "MissingParameters", "IDF1", )"[^"]*"', r'\1"El campo epdRequestId es obligatorio o presenta un valor no v\\\\u00e1lido."', text)
    text = re.sub(r'(case NOT_FOUND -> describe\(error, "ParameterValueNotFound", "IDF2", )"[^"]*"', r'\1"No se encontr\\\\u00f3 la solicitud CPE asociada al epdRequestId indicado."', text)
    text = re.sub(r'(case INTERNAL_SERVER_ERROR -> describe\(error, "InternalError", "IDT3", )"[^"]*"', r'\1"Error interno al registrar el snapshot hist\\\\u00f3rico: [ERROR_DETAIL]"', text)
    text = re.sub(r'(case GATEWAY_TIMEOUT -> describe\(error, "TimeoutException", "IDT1", )"[^"]*"', r'\1"Timeout al registrar el snapshot hist\\\\u00f3rico en [SERVICE_NAME] - Detalle: [ERROR_DETAIL]"', text)
    return text


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    for cls, (table, fields) in ENTITIES.items():
        body = dj.entity(cls, table, fields)
        if cls == 'EpdRequestHistEntity':
            body = body.replace('    @GeneratedValue(strategy = GenerationType.IDENTITY)',
                                '    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "epdRequestHistSeq")\n    @SequenceGenerator(name = "epdRequestHistSeq", sequenceName = "FACEL.SEQ_EPDREQUESTHIST", allocationSize = 1)')
        else:
            body = body.replace('    @GeneratedValue(strategy = GenerationType.IDENTITY)\n', '')
        put('model', cls, body)
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    for cls, fields in REQUEST_DTOS.items():
        put('dto.request', cls, dj.dto(cls, fields))
    for cls, fields in DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields, non_null=True))
    put('dto.response', 'CreateEmissionCpeHistResponse', dj.envelope('CreateEmissionCpeHistResponse', 'CreateEmissionCpeHistData'))
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    put('dto.mapper', 'EmissionCpeHistMapper', MAPPER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', handler())
    for cls, body in REPOS.items():
        put('repository', cls, body)
    put('service', 'EmissionCpeHistService', SERVICE_IF)
    put('service.impl', 'EmissionCpeHistServiceImpl', SERVICE_IMPL)
    put('validation', 'EmissionCpeHistValidator', VALIDATOR)
    put('controller', 'EmissionCpeHistApi', api())
    put('controller.impl', 'EmissionCpeHistController', controller())
    put('configuration', 'ClockConfig', dj.CLOCK_CONFIG)
    return files


ORIGINAL_CONSTANTS = dj.activity_constants


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False), ('ACT2_VALIDAR_EXISTENCIA_EPDREQUEST', 'VALIDAR_EXISTENCIA_EPDREQUEST', True),
                     ('ACT3_OBTENER_DATOS_VIGENTES', 'OBTENER_DATOS_VIGENTES', True), ('ACT4_CREAR_SNAPSHOT_HISTORICO', 'CREAR_SNAPSHOT_HISTORICO', True)]
    try:
        return ORIGINAL_CONSTANTS()
    finally:
        dj.ACTIVITIES = saved


TESTS = {}
TESTS['EmissionCpeHistValidatorTest'] = ('validation', '''class EmissionCpeHistValidatorTest {
    private static final Long ID = 12345L;

    private final EmissionCpeHistValidator validator = new EmissionCpeHistValidator();

    private CreateEmissionCpeHistRequest request(Long id) {
        CreateEmissionCpeHistRequest request = new CreateEmissionCpeHistRequest();
        request.setEpdRequestId(id);
        return request;
    }

    @Test
    void acceptsAPositiveIdentifier() {
        assertEquals(ID, validator.epdRequestId(request(ID)));
    }

    @Test
    void rejectsMissingBodyMissingOrNonPositiveIdentifier() {
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> validator.epdRequestId(null)).getStatus());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> validator.epdRequestId(request(null))).getStatus());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> validator.epdRequestId(request(0L))).getStatus());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> validator.epdRequestId(request(-1L))).getStatus());
    }
}''')
TESTS['EmissionCpeHistMapperTest'] = ('dto.mapper', '''class EmissionCpeHistMapperTest {
    private static final Long ID = 10L;
    private static final Long HIST_ID = 5001L;
    private static final Integer STATUS = 3;

    private final EmissionCpeHistMapper mapper = new EmissionCpeHistMapper();

    @Test
    void snapshotCopiesTheCurrentValuesAndAudit() {
        EpdRequestEntity current = new EpdRequestEntity();
        current.setId(ID);
        current.setEpdQueryStatusId(STATUS);
        current.setInputPayload("{}");
        current.setApplication("app");
        LocalDateTime now = LocalDateTime.parse("2026-10-12T10:15:30");
        EpdRequestHistEntity snapshot = mapper.snapshot(current, "user", now);
        assertEquals(ID, snapshot.getEpdRequestId());
        assertNull(snapshot.getId());
        assertEquals(STATUS, snapshot.getEpdQueryStatusId());
        assertEquals("{}", snapshot.getInputPayload());
        assertEquals("user", snapshot.getCreationUser());
        assertEquals(now, snapshot.getCreationDate());
    }

    @Test
    void responseExposesTheHistoryIdentifierAndSnapshotDate() {
        EpdRequestHistEntity saved = new EpdRequestHistEntity();
        saved.setId(HIST_ID);
        saved.setEpdRequestId(ID);
        saved.setCreationDate(LocalDateTime.parse("2026-10-12T10:15:30"));
        CreateEmissionCpeHistResponse response = mapper.response(saved);
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertEquals(HIST_ID, response.getData().getId());
        assertEquals(ID, response.getData().getEpdRequestId());
        assertNotNull(response.getData().getSnapshotDate());
    }
}''')
TESTS['GlobalExceptionHandlerTest'] = ('exception', '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request() {
        return new ServletWebRequest(new MockHttpServletRequest("POST", "/api/v1/emisioneshist"));
    }

    @Test
    void badRequestUsesTheContractShape() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request());
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF1", response.getBody().getSubType());
        assertEquals("PROCESCREATIONEMISSIONCPEHIST_SERVICE_ERROR", response.getBody().getMessage());
    }

    @Test
    void notFoundIsDeclaredAndConflictIsNot() {
        assertEquals(HttpStatus.NOT_FOUND.value(), handler.operationFailure(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"), request()).getStatusCode().value());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), handler.operationFailure(new ServiceOperationException(HttpStatus.CONFLICT, "dup"), request()).getStatusCode().value());
    }

    @Test
    void unexpectedFailuresBecomeInternalError() {
        ResponseEntity<ErrorResponse> response = handler.unexpectedFailure(new IllegalStateException("boom"), request());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), response.getStatusCode().value());
        assertEquals("IDT3", response.getBody().getSubType());
    }

    @Test
    void timeoutBecomesGatewayTimeout() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow"), request());
        assertEquals(HttpStatus.GATEWAY_TIMEOUT.value(), response.getStatusCode().value());
        assertEquals("IDT1", response.getBody().getSubType());
    }
}''')
TESTS['EmissionCpeHistServiceImplTest'] = ('service.impl', '''class EmissionCpeHistServiceImplTest {
    private static final Long ID = 12345L;
    private static final Long HIST_ID = 5001L;
    private static final Integer STATUS = 3;

    private final EpdRequestRepository requests = Mockito.mock(EpdRequestRepository.class);
    private final EpdRequestHistRepository history = Mockito.mock(EpdRequestHistRepository.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-12T10:15:30Z"), ZoneOffset.UTC);
    private final EmissionCpeHistServiceImpl service = new EmissionCpeHistServiceImpl(requests, history, new EmissionCpeHistMapper(), new EmissionCpeHistValidator(),
            new PersistenceExceptionTranslator(), clock);
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");

    private CreateEmissionCpeHistRequest request() {
        CreateEmissionCpeHistRequest request = new CreateEmissionCpeHistRequest();
        request.setEpdRequestId(ID);
        return request;
    }

    private void stubExisting() {
        EpdRequestEntity current = new EpdRequestEntity();
        current.setId(ID);
        current.setEpdQueryStatusId(STATUS);
        Mockito.when(requests.existsById(ID)).thenReturn(true);
        Mockito.when(requests.findById(ID)).thenReturn(Optional.of(current));
    }

    @Test
    void createsTheSnapshotFromTheCurrentRow() {
        stubExisting();
        Mockito.when(history.save(ArgumentMatchers.any(EpdRequestHistEntity.class))).thenAnswer(call -> {
            EpdRequestHistEntity saved = call.getArgument(0);
            saved.setId(HIST_ID);
            return saved;
        });
        CreateEmissionCpeHistResponse response = service.createEmissionCpeHist(headers, request());
        assertEquals(HIST_ID, response.getData().getId());
        assertEquals(ID, response.getData().getEpdRequestId());
        assertEquals(LocalDateTime.parse("2026-10-12T10:15:30"), response.getData().getSnapshotDate());
        ArgumentCaptor<EpdRequestHistEntity> captor = ArgumentCaptor.forClass(EpdRequestHistEntity.class);
        Mockito.verify(history).save(captor.capture());
        assertEquals(STATUS, captor.getValue().getEpdQueryStatusId());
        assertEquals("user", captor.getValue().getCreationUser());
    }

    @Test
    void aMissingRequestIsNotFoundAndNothingIsWritten() {
        Mockito.when(requests.existsById(ID)).thenReturn(false);
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.createEmissionCpeHist(headers, request()));
        assertEquals(HttpStatus.NOT_FOUND, failure.getStatus());
        Mockito.verifyNoInteractions(history);
    }

    @Test
    void invalidBodyFailsBeforeTouchingTheDatabase() {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.createEmissionCpeHist(headers, new CreateEmissionCpeHistRequest()));
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
        Mockito.verifyNoInteractions(requests);
    }

    @Test
    void readTimeoutsBecomeGatewayTimeout() {
        Mockito.when(requests.existsById(ID)).thenThrow(new QueryTimeoutException("slow"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.createEmissionCpeHist(headers, request()));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, failure.getStatus());
    }

    @Test
    void writeFailuresBecomeServerErrors() {
        stubExisting();
        Mockito.when(history.save(ArgumentMatchers.any(EpdRequestHistEntity.class))).thenThrow(new QueryTimeoutException("slow"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.createEmissionCpeHist(headers, request()));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, failure.getStatus());
    }
}''')
TESTS['EmissionCpeHistApiContractTest'] = ('controller', '''class EmissionCpeHistApiContractTest {
    private static final Long ID = 12345L;

    private final EmissionCpeHistService service = Mockito.mock(EmissionCpeHistService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new EmissionCpeHistController(service))
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

    private MockHttpServletRequestBuilder post(String body) {
        return withHeaders(MockMvcRequestBuilders.post("/api/v1/emisioneshist")).contentType(MediaType.APPLICATION_JSON).content(body);
    }

    @Test
    void postReturnsTheEnvelope() throws Exception {
        CreateEmissionCpeHistData data = new CreateEmissionCpeHistData();
        data.setEpdRequestId(ID);
        CreateEmissionCpeHistResponse response = new CreateEmissionCpeHistResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("ok");
        response.setData(data);
        Mockito.when(service.createEmissionCpeHist(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(CreateEmissionCpeHistRequest.class))).thenReturn(response);
        mvc.perform(post("{\\"epdRequestId\\": 12345}")).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("ok")).andExpect(jsonPath("$.data.epdRequestId").value(ID));
    }

    @Test
    void aMissingHeaderIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(MockMvcRequestBuilders.post("/api/v1/emisioneshist").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.subType").value("IDF1"));
    }

    @Test
    void aMalformedBodyIsABadRequest() throws Exception {
        mvc.perform(post("not-json")).andExpect(status().isBadRequest()).andExpect(jsonPath("$.message").value("PROCESCREATIONEMISSIONCPEHIST_SERVICE_ERROR"));
    }

    @Test
    void notFoundIsReportedWithTheOperationMessage() throws Exception {
        Mockito.when(service.createEmissionCpeHist(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(CreateEmissionCpeHistRequest.class)))
                .thenThrow(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"));
        mvc.perform(post("{\\"epdRequestId\\": 12345}")).andExpect(status().isNotFound()).andExpect(jsonPath("$.subType").value("IDF2"));
    }
}''')


def build_tests(pkg):
    import dom_cpe_request_tests as dt
    files = {}
    for name, (suffix, body) in TESTS.items():
        statics = list(dt.MVC_STATICS) if name == 'EmissionCpeHistApiContractTest' else dt.ASSERT
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


dj.EXTERNAL['ArgumentCaptor'] = 'org.mockito.ArgumentCaptor'
dj.EXTERNAL['MockHttpServletRequestBuilder'] = 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder'

ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.emission.cpehist and application class EmissionCpeHistApplication are technical choices; no source defines them.'),
    ('A-02', 'Tables are mapped in schema FACEL. EPDREQUEST is read with the columns that exist in its Sparx table definition (REFERENCECODE of the Sparx output is not a column; UNIQUEREFERENCECOD is the table column and is not copied).'),
    ('A-03', 'Sparx lists history columns REFERENCECODE, COMREQUESTPAYLOAD, SIGNATUREHASH, SUNATTICKET, CDRPAYLOAD and SNAPSHOTDATE that are absent from the EPDREQUESTHIST table definition; only columns present in the definition are persisted.'),
    ('A-04', 'SNAPSHOTDATE does not exist in the table definition: data.snapshotDate is the CREATIONDATE written by the service (injectable Clock, never SYSDATE).'),
    ('A-05', 'The history id comes from sequence FACEL.SEQ_EPDREQUESTHIST (Sparx) through a JPA sequence generator with allocationSize 1.'),
    ('A-06', 'CREATIONUSER of the snapshot is the x-user-id header (Sparx: internal parameter creationUser without a defined source).'),
    ('A-07', 'epdRequestId must be a positive integer (Sparx only says informed and with valid format). Status/audit columns STATUSFROMID, STATUSTOID, STATUSCHANGEDATE and STATUSCHANGEORIGIN are not written (no Sparx mapping).'),
    ('A-08', 'Only the statuses declared by the OpenAPI (200/400/404/500/503/504) are emitted; the error messages come from the Swagger examples. No 401/403 handling.'),
]


def main(argv=None):
    sys.modules['dom_invoice_java'] = types.SimpleNamespace()
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, 'EmissionCpeHistApplication', ASSUMPTIONS, 'emission-cpehist-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': 'EmissionCpeHistApplication'}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'emission_cpehist_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main(argv) if argv is not None else dm.main()


if __name__ == '__main__':
    sys.exit(main())
