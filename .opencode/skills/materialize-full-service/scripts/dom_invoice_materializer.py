"""Deterministic materializer of the dom-invoice service (read-only multi-table JPA profile of claro-spring-ms).

Reuses the machinery of dom_cpe_request_materializer (gate recomputed first, archetype assembly, file protection, per-service lock, manifest last) with the
typed model of this service: one GET operation, four FACEL tables (EPDREQUEST, ELECTRONICDOCUMENTTYPE, EPDQUERYSTATUS, EPDQUERY).

Usage: python dom_invoice_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import re
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402

PACKAGE = 'com.claro.dom.invoice'
ENTITIES = {
    'InvoiceRequestEntity': ('EPDREQUEST', [('Long', 'id', 'ID', 'id'), ('String', 'series', 'SERIES', ''), ('Long', 'correlative', 'CORRELATIVE', ''), ('Integer', 'epdTypeId', 'EPDTYPEID', ''),
                                            ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''), ('String', 'creationUser', 'CREATIONUSER', '')]),
    'DocumentTypeEntity': ('ELECTRONICDOCUMENTTYPE', [('Long', 'id', 'ID', 'id'), ('String', 'sunatDocumentTypeCode', 'SUNATDOCUMENTTYPECODE', '')]),
    'QueryStatusEntity': ('EPDQUERYSTATUS', [('Long', 'id', 'ID', 'id'), ('String', 'value', 'VALUE', '')]),
    'QueryEntity': ('EPDQUERY', [('Long', 'id', 'ID', 'id'), ('Long', 'epdRequestId', 'EPDREQUESTID', ''), ('String', 'pdfUrl', 'PDFURL', ''), ('String', 'xmlUrl', 'XMLURL', ''), ('String', 'cdrUrl', 'CDRURL', '')]),
}
DTOS = {'InvoiceDocuments': [('String', 'pdfUrl'), ('String', 'xmlUrl'), ('String', 'cdrUrl')],
        'InvoiceRequest': [('Long', 'id'), ('String', 'documentType'), ('String', 'series'), ('String', 'sequential'), ('String', 'status'), ('String', 'creationUser'), ('InvoiceDocuments', 'documents')],
        'GetInvoiceData': [('List<InvoiceRequest>', 'epdRrequest')]}
dj.register('model', *ENTITIES, 'InvoiceQuery')
dj.register('dto.response', *DTOS, 'GetInvoiceResponse')
dj.register('dto.mapper', 'InvoiceMapper')
dj.register('repository', 'InvoiceRequestRepository', 'DocumentTypeRepository', 'QueryStatusRepository', 'QueryRepository')
dj.register('service', 'InvoiceService')
dj.register('service.impl', 'InvoiceServiceImpl')
dj.register('validation', 'InvoiceValidator')
dj.register('controller', 'InvoiceApi')
dj.register('controller.impl', 'InvoiceController')

QUERY = '''/** Validated search command: the SUNAT document type code, the series, the numeric correlative and the creating user. */
public record InvoiceQuery(String documentType, String series, Long sequential, String creationUser) {
}'''

REPOS = {
    'InvoiceRequestRepository': '''@Repository
public interface InvoiceRequestRepository extends JpaRepository<InvoiceRequestEntity, Long> {
    List<InvoiceRequestEntity> findByEpdTypeIdAndSeriesAndCorrelativeAndCreationUserOrderByIdAsc(Integer epdTypeId, String series, Long correlative, String creationUser);
}''',
    'DocumentTypeRepository': '''@Repository
public interface DocumentTypeRepository extends JpaRepository<DocumentTypeEntity, Long> {
    Optional<DocumentTypeEntity> findFirstBySunatDocumentTypeCodeOrderByIdAsc(String sunatDocumentTypeCode);
}''',
    'QueryStatusRepository': '''@Repository
public interface QueryStatusRepository extends JpaRepository<QueryStatusEntity, Long> {
}''',
    'QueryRepository': '''@Repository
public interface QueryRepository extends JpaRepository<QueryEntity, Long> {
    Optional<QueryEntity> findFirstByEpdRequestIdOrderByIdDesc(Long epdRequestId);
}''',
}

SERVICE_IF = '''/** Consulta interna de CPE emitidos. */
public interface InvoiceService {
    GetInvoiceResponse getInvoice(RequestHeaders headers, String documentType, String series, String sequential, String creationUser);
}'''

VALIDATOR = '''/** Declared contract rules: the four query parameters are required and must have the permitted format. */
@Component
public class InvoiceValidator {
    private static final Pattern DOCUMENT_TYPE = Pattern.compile("^[0-9A-Za-z]{2}$");
    private static final Pattern SERIES = Pattern.compile("^[0-9A-Za-z]{1,20}$");
    private static final Pattern SEQUENTIAL = Pattern.compile("^[0-9]{1,18}$");
    private static final Pattern USER = Pattern.compile("^\\\\S{1,20}$");
    private static final String INVALID_PARAMETERS = "Par\u00e1metros obligatorios incompletos o con valores no v\u00e1lidos.";

    public InvoiceQuery getInvoice(String documentType, String series, String sequential, String creationUser) {
        require(matches(DOCUMENT_TYPE, documentType));
        require(matches(SERIES, series));
        require(matches(SEQUENTIAL, sequential));
        require(matches(USER, creationUser));
        return new InvoiceQuery(documentType, series, Long.valueOf(sequential), creationUser);
    }

    private static boolean matches(Pattern pattern, String value) {
        return value != null && pattern.matcher(value).matches();
    }

    private static void require(boolean valid) {
        if (!valid) {
            throw ServiceOperationException.badRequest(INVALID_PARAMETERS);
        }
    }
}'''
dj.EXTERNAL['Pattern'] = 'java.util.regex.Pattern'

MAPPER = '''/** Explicit mapping between the JPA entities and the API contract. */
@Component
public class InvoiceMapper {
    private static final String SUCCESS_MESSAGE = "Operaci\u00f3n exitosa";

    public InvoiceRequest item(String documentType, InvoiceRequestEntity row, String status, QueryEntity documents) {
        InvoiceRequest item = new InvoiceRequest();
        item.setId(row.getId());
        item.setDocumentType(documentType);
        item.setSeries(row.getSeries());
        item.setSequential(row.getCorrelative() == null ? null : String.valueOf(row.getCorrelative()));
        item.setStatus(status);
        item.setCreationUser(row.getCreationUser());
        item.setDocuments(documents == null ? null : documents(documents));
        return item;
    }

    private InvoiceDocuments documents(QueryEntity query) {
        InvoiceDocuments documents = new InvoiceDocuments();
        documents.setPdfUrl(query.getPdfUrl());
        documents.setXmlUrl(query.getXmlUrl());
        documents.setCdrUrl(query.getCdrUrl());
        return documents;
    }

    public GetInvoiceResponse response(List<InvoiceRequest> items) {
        GetInvoiceData data = new GetInvoiceData();
        data.setEpdRrequest(items);
        GetInvoiceResponse response = new GetInvoiceResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }
}'''

SERVICE_IMPL = '''/** Activity-logged read-only service; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class InvoiceServiceImpl implements InvoiceService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String NOT_FOUND_DETAIL = "CPE no encontrado.";
    private static final Set<String> DOWNLOADABLE_STATUSES = Set.of("ACEPTADO", "ACEPTADO_CON_OBSERVACIONES");

    private final InvoiceRequestRepository requests;
    private final DocumentTypeRepository documentTypes;
    private final QueryStatusRepository statuses;
    private final QueryRepository queries;
    private final InvoiceMapper mapper;
    private final InvoiceValidator validator;
    private final PersistenceExceptionTranslator translator;

    @Override
    public GetInvoiceResponse getInvoice(RequestHeaders headers, String documentType, String series, String sequential, String creationUser) {
        String menTran = prefix(headers);
        InvoiceQuery query = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validar(headers, documentType, series, sequential, creationUser));
        List<InvoiceRequest> items = ejecutarActividad(menTran, ConstanApi.ACT2_CONSULTAR_CPE_EMITIDO, () -> consultar(menTran, query));
        return mapper.response(items);
    }

    private InvoiceQuery validar(RequestHeaders headers, String documentType, String series, String sequential, String creationUser) {
        log.info(
                "getInvoice applicationName={}, transactionId={}, userId={}, documentType={}, series={}, sequential={}, creationUser={}",
                headers != null ? headers.applicationName() : null,
                headers != null ? headers.transactionId() : null,
                headers != null ? headers.userId() : null,
                documentType,
                series,
                sequential,
                creationUser
        );
        return validator.getInvoice(documentType, series, sequential, creationUser);
    }

    private List<InvoiceRequest> consultar(String menTran, InvoiceQuery query) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_CONSULTAR_CPE_EMITIDO, ConstanApi.LOG_ERROR_DATOS_ACT2_CONSULTAR_CPE_EMITIDO, () -> leer(menTran, query));
    }

    private List<InvoiceRequest> leer(String menTran, InvoiceQuery query) {
        Optional<DocumentTypeEntity> type = documentTypes.findFirstBySunatDocumentTypeCodeOrderByIdAsc(query.documentType());
        List<InvoiceRequestEntity> rows = type.isEmpty() ? List.of() : requests.findByEpdTypeIdAndSeriesAndCorrelativeAndCreationUserOrderByIdAsc(
                Math.toIntExact(type.get().getId()), query.series(), query.sequential(), query.creationUser());
        if (rows.isEmpty()) {
            log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT2_CONSULTAR_CPE_EMITIDO, HttpStatus.NOT_FOUND.value(), NOT_FOUND_DETAIL);
            throw new ServiceOperationException(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);
        }
        return rows.stream().map(row -> item(query.documentType(), row)).toList();
    }

    private InvoiceRequest item(String documentType, InvoiceRequestEntity row) {
        String status = statusOf(row);
        QueryEntity documents = DOWNLOADABLE_STATUSES.contains(status) ? queries.findFirstByEpdRequestIdOrderByIdDesc(row.getId()).orElse(null) : null;
        return mapper.item(documentType, row, status, documents);
    }

    private String statusOf(InvoiceRequestEntity row) {
        if (row.getEpdQueryStatusId() == null) {
            return null;
        }
        return statuses.findById(Long.valueOf(row.getEpdQueryStatusId())).map(QueryStatusEntity::getValue).orElse(null);
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

PARAMS = [('@RequestParam(name = "documentType", required = true)', 'documentType', 'C\u00f3digo SUNAT del tipo de documento electr\u00f3nico.'),
          ('@RequestParam(name = "series", required = true)', 'series', 'Serie del CPE.'), ('@RequestParam(name = "sequential", required = true)', 'sequential', 'Correlativo del CPE.'),
          ('@RequestParam(name = "creationUser", required = true)', 'creationUser', 'Usuario creador del CPE.')]


def api():
    out = ['/** Define el contrato del endpoint REST de consulta interna de CPE emitidos (contrato OpenAPI). */', 'public interface InvoiceApi {', '    /**', '     * Consulta un CPE emitido.', '     *']
    out += [f'     * @param {n} {d}' for _, n, d in PARAMS] + [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    out += ['     * @return respuesta HTTP con el modelo GetInvoiceResponse definido en el contrato', '     */',
            '    @GetMapping(path = "/api/v1/dom-invoice", produces = {"application/json"})', '    @Operation(summary = "Consulta un CPE emitido.")', '    @ApiResponses({']
    rows = ['      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = GetInvoiceResponse.class)))']
    rows += [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS[c]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for c in ('400', '404', '500', '503', '504')]
    out += [',\n'.join(rows), '    })', '    ResponseEntity<GetInvoiceResponse> getInvoice(']
    args = [f'            {a} String {n}' for a, n, _ in PARAMS] + [f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS]
    out += [',\n'.join(args) + ');', '}']
    return '\n'.join(out)


def controller():
    args = [f'            String {n}' for _, n, _ in PARAMS] + [f'            String {c}' for _, c, _ in dj.HEADERS]
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class InvoiceController implements InvoiceApi {', '    private final InvoiceService service;', '', '    @Override',
                      '    public ResponseEntity<GetInvoiceResponse> getInvoice(', ',\n'.join(args) + ') {', '        log.info("getInvoice - transactionId: {}", xCorrelationId);',
                      '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);', '        return ResponseEntity.ok(service.getInvoice(headers, documentType, series, sequential, creationUser));',
                      '    }', '}'])


def handler():
    text = dj.HANDLER
    text = re.sub(r'    private String operationMessage\(.*?\n    }\n\n    private String method', '    private String operationMessage(String method, String uri, HttpStatus status) {\n        return "PROCESGET_INVOICE_SERVICE_ERROR";\n    }\n\n    private String method', text, flags=re.S)
    return text


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    for cls, (table, fields) in ENTITIES.items():
        put('model', cls, dj.entity(cls, table, fields))
    put('model', 'InvoiceQuery', QUERY)
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    for cls, fields in DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields, non_null=True))
    put('dto.response', 'GetInvoiceResponse', dj.envelope('GetInvoiceResponse', 'GetInvoiceData'))
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    put('dto.mapper', 'InvoiceMapper', MAPPER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', handler())
    for cls, body in REPOS.items():
        put('repository', cls, body)
    put('service', 'InvoiceService', SERVICE_IF)
    put('service.impl', 'InvoiceServiceImpl', SERVICE_IMPL)
    put('validation', 'InvoiceValidator', VALIDATOR)
    put('controller', 'InvoiceApi', api())
    put('controller.impl', 'InvoiceController', controller())
    return files


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False), ('ACT2_CONSULTAR_CPE_EMITIDO', 'CONSULTAR_CPE_EMITIDO', True)]
    try:
        return dj_constants()
    finally:
        dj.ACTIVITIES = saved


def dj_constants():
    return ORIGINAL_CONSTANTS()


ORIGINAL_CONSTANTS = dj.activity_constants

TESTS = {}
TESTS['InvoiceValidatorTest'] = ('validation', '''class InvoiceValidatorTest {
    private static final Long SEQUENTIAL = 123L;

    private final InvoiceValidator validator = new InvoiceValidator();

    private void assertBadRequest(Executable executable) {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, executable);
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
    }

    @Test
    void acceptsAValidSearch() {
        InvoiceQuery query = validator.getInvoice("01", "F001", "123", "user");
        assertEquals(SEQUENTIAL, query.sequential());
        assertEquals("F001", query.series());
    }

    @Test
    void rejectsMissingOrMalformedParameters() {
        assertBadRequest(() -> validator.getInvoice(null, "F001", "123", "user"));
        assertBadRequest(() -> validator.getInvoice("1", "F001", "123", "user"));
        assertBadRequest(() -> validator.getInvoice("01", "", "123", "user"));
        assertBadRequest(() -> validator.getInvoice("01", "F-001", "123", "user"));
        assertBadRequest(() -> validator.getInvoice("01", "F001", "12a", "user"));
        assertBadRequest(() -> validator.getInvoice("01", "F001", "123", " "));
        assertBadRequest(() -> validator.getInvoice("01", "F001", "123", null));
    }
}''')
TESTS['InvoiceMapperTest'] = ('dto.mapper', '''class InvoiceMapperTest {
    private static final Long ID = 10L;
    private static final Long SEQUENTIAL = 123L;

    private final InvoiceMapper mapper = new InvoiceMapper();

    private InvoiceRequestEntity row() {
        InvoiceRequestEntity row = new InvoiceRequestEntity();
        row.setId(ID);
        row.setSeries("F001");
        row.setCorrelative(SEQUENTIAL);
        row.setCreationUser("user");
        return row;
    }

    @Test
    void mapsTheRequestWithoutDocumentsWhenNoneAreAvailable() {
        InvoiceRequest item = mapper.item("01", row(), "PENDIENTE", null);
        assertEquals("123", item.getSequential());
        assertEquals("01", item.getDocumentType());
        assertEquals("PENDIENTE", item.getStatus());
        assertNull(item.getDocuments());
    }

    @Test
    void mapsTheDownloadableUrls() {
        QueryEntity query = new QueryEntity();
        query.setPdfUrl("p");
        query.setXmlUrl("x");
        query.setCdrUrl("c");
        InvoiceRequest item = mapper.item("01", row(), "ACEPTADO", query);
        assertEquals("p", item.getDocuments().getPdfUrl());
        assertEquals("c", item.getDocuments().getCdrUrl());
    }

    @Test
    void responseWrapsTheItemsInTheEnvelope() {
        GetInvoiceResponse response = mapper.response(List.of(mapper.item("01", row(), null, null)));
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertEquals(1, response.getData().getEpdRrequest().size());
    }
}''')
TESTS['GlobalExceptionHandlerTest'] = ('exception', '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request() {
        return new ServletWebRequest(new MockHttpServletRequest("GET", "/api/v1/dom-invoice"));
    }

    @Test
    void badRequestUsesTheContractShape() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request());
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF1", response.getBody().getSubType());
        assertEquals("PROCESGET_INVOICE_SERVICE_ERROR", response.getBody().getMessage());
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
TESTS['InvoiceServiceImplTest'] = ('service.impl', '''class InvoiceServiceImplTest {
    private static final Long ID = 10L;
    private static final Long TYPE_ID = 1L;
    private static final Long SEQUENTIAL = 123L;
    private static final Integer STATUS_ID = 3;

    private final InvoiceRequestRepository requests = Mockito.mock(InvoiceRequestRepository.class);
    private final DocumentTypeRepository documentTypes = Mockito.mock(DocumentTypeRepository.class);
    private final QueryStatusRepository statuses = Mockito.mock(QueryStatusRepository.class);
    private final QueryRepository queries = Mockito.mock(QueryRepository.class);
    private final InvoiceServiceImpl service = new InvoiceServiceImpl(requests, documentTypes, statuses, queries, new InvoiceMapper(), new InvoiceValidator(),
            new PersistenceExceptionTranslator());
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");

    private void stubFound(String statusValue) {
        DocumentTypeEntity type = new DocumentTypeEntity();
        type.setId(TYPE_ID);
        Mockito.when(documentTypes.findFirstBySunatDocumentTypeCodeOrderByIdAsc("01")).thenReturn(Optional.of(type));
        InvoiceRequestEntity row = new InvoiceRequestEntity();
        row.setId(ID);
        row.setSeries("F001");
        row.setCorrelative(SEQUENTIAL);
        row.setEpdQueryStatusId(STATUS_ID);
        Mockito.when(requests.findByEpdTypeIdAndSeriesAndCorrelativeAndCreationUserOrderByIdAsc(1, "F001", SEQUENTIAL, "user")).thenReturn(List.of(row));
        QueryStatusEntity status = new QueryStatusEntity();
        status.setValue(statusValue);
        Mockito.when(statuses.findById(Long.valueOf(STATUS_ID))).thenReturn(Optional.of(status));
    }

    private GetInvoiceResponse call() {
        return service.getInvoice(headers, "01", "F001", "123", "user");
    }

    @Test
    void acceptedInvoicesIncludeTheDownloadableUrls() {
        stubFound("ACEPTADO");
        QueryEntity query = new QueryEntity();
        query.setPdfUrl("p");
        Mockito.when(queries.findFirstByEpdRequestIdOrderByIdDesc(ID)).thenReturn(Optional.of(query));
        InvoiceRequest item = call().getData().getEpdRrequest().get(0);
        assertEquals("ACEPTADO", item.getStatus());
        assertEquals("p", item.getDocuments().getPdfUrl());
    }

    @Test
    void otherStatusesDoNotQueryTheDocuments() {
        stubFound("PENDIENTE");
        assertNull(call().getData().getEpdRrequest().get(0).getDocuments());
        Mockito.verifyNoInteractions(queries);
    }

    @Test
    void anUnknownDocumentTypeOrMissingRowIsNotFound() {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, this::call);
        assertEquals(HttpStatus.NOT_FOUND, failure.getStatus());
    }

    @Test
    void invalidParametersFailBeforeTouchingTheDatabase() {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.getInvoice(headers, "01", "F001", "abc", "user"));
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
        Mockito.verifyNoInteractions(requests);
    }

    @Test
    void dataAccessTimeoutsBecomeGatewayTimeout() {
        Mockito.when(documentTypes.findFirstBySunatDocumentTypeCodeOrderByIdAsc("01")).thenThrow(new QueryTimeoutException("slow"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, this::call);
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, failure.getStatus());
    }
}''')
TESTS['InvoiceApiContractTest'] = ('controller', '''class InvoiceApiContractTest {
    private final InvoiceService service = Mockito.mock(InvoiceService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new InvoiceController(service))
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

    private MockHttpServletRequestBuilder search() {
        return withHeaders(get("/api/v1/dom-invoice")).param("documentType", "01").param("series", "F001").param("sequential", "123").param("creationUser", "user");
    }

    @Test
    void getReturnsTheEnvelope() throws Exception {
        GetInvoiceResponse response = new GetInvoiceResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("ok");
        Mockito.when(service.getInvoice(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq("01"), ArgumentMatchers.eq("F001"), ArgumentMatchers.eq("123"),
                ArgumentMatchers.eq("user"))).thenReturn(response);
        mvc.perform(search()).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("ok"));
    }

    @Test
    void aMissingRequiredParameterIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(withHeaders(get("/api/v1/dom-invoice")).param("documentType", "01"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.subType").value("IDF1"));
    }

    @Test
    void notFoundIsReportedWithTheOperationMessage() throws Exception {
        Mockito.when(service.getInvoice(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.anyString(), ArgumentMatchers.anyString(), ArgumentMatchers.anyString(),
                ArgumentMatchers.anyString())).thenThrow(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"));
        mvc.perform(search()).andExpect(status().isNotFound()).andExpect(jsonPath("$.message").value("PROCESGET_INVOICE_SERVICE_ERROR"));
    }
}''')


def build_tests(pkg):
    import dom_cpe_request_tests as dt
    files = {}
    for name, (suffix, body) in TESTS.items():
        statics = dt.MVC_STATICS if name == 'InvoiceApiContractTest' else dt.ASSERT
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.dom.invoice and application class DomInvoiceApplication are technical choices; no source defines them.'),
    ('A-02', 'All tables are mapped in schema FACEL (EPDREQUEST, ELECTRONICDOCUMENTTYPE, EPDQUERYSTATUS, EPDQUERY); only the columns the query reads are mapped; the service is read-only.'),
    ('A-03', 'Gate decisions delegated by the user (swagger-governs): data.epdRrequest is a list of InvoiceRequest (Sparx returns a flat object), and creationUser is REQUIRED (Sparx says optional).'),
    ('A-04', 'documentType is resolved through ELECTRONICDOCUMENTTYPE.SUNATDOCUMENTTYPECODE; an unknown code or no matching EPDREQUEST row returns 404.'),
    ('A-05', 'Format validation (not defined by the sources): documentType 2 alphanumerics, series 1-20 alphanumerics, sequential 1-18 digits (EPDREQUEST.CORRELATIVE is NUMBER), creationUser 1-20 non-blank characters.'),
    ('A-06', 'data.status is EPDQUERYSTATUS.VALUE (Sparx output says SELECT.STATUS, but STATUS is the 1/0 active flag; the status names ACEPTADO / ACEPTADO_CON_OBSERVACIONES live in VALUE).'),
    ('A-07', 'URLs come from the most recent EPDQUERY row of the request (highest ID) and only when the status is ACEPTADO or ACEPTADO_CON_OBSERVACIONES; otherwise documents is omitted.'),
    ('A-08', 'Query auditing is not implemented: Sparx leaves the audit table/mechanism undefined (no EPDQUERY insert).'),
    ('A-09', 'No 401/403 handling and only the statuses declared by the OpenAPI (200/400/404/500/503/504) are emitted.'),
]


def main():
    sys.modules['dom_invoice_java'] = types.SimpleNamespace()
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, 'DomInvoiceApplication', ASSUMPTIONS, 'dom-invoice-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': 'DomInvoiceApplication'}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'dom_invoice_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main()


if __name__ == '__main__':
    sys.exit(main())
