"""Deterministic materializer of the dom-customerBills / dom-customerBillQuery services (read-only search over FACEL.EPDREQUEST, JPA profile of claro-spring-ms).

Both services expose the same contract (GET /api/v1/dom-customerBills, getCustomerBills); the service name only selects the package and the application class.
Reuses the machinery of dom_cpe_request_materializer (gate recomputed first, archetype assembly, file protection, per-service lock, manifest last).

Usage: python customer_bills_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import re
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402

PACKAGES = {'dom-customerBills': ('com.claro.dom.customerbills', 'DomCustomerBillsApplication'),
            'dom-customerBillQuery': ('com.claro.dom.customerbillquery', 'DomCustomerBillQueryApplication')}

for name, path in {'LocalDate': 'java.time.LocalDate', 'DateTimeParseException': 'java.time.format.DateTimeParseException', 'HashMap': 'java.util.HashMap', 'Objects': 'java.util.Objects',
                   'Pattern': 'java.util.regex.Pattern', 'Executable': 'org.junit.jupiter.api.function.Executable', 'Specification': 'org.springframework.data.jpa.domain.Specification',
                   'JpaSpecificationExecutor': 'org.springframework.data.jpa.repository.JpaSpecificationExecutor', 'Predicate': 'jakarta.persistence.criteria.Predicate',
                   'Root': 'jakarta.persistence.criteria.Root', 'CriteriaQuery': 'jakarta.persistence.criteria.CriteriaQuery', 'CriteriaBuilder': 'jakarta.persistence.criteria.CriteriaBuilder',
                   'ArgumentCaptor': 'org.mockito.ArgumentCaptor'}.items():
    dj.EXTERNAL[name] = path

ENTITIES = {
    'CustomerBillRequestEntity': ('EPDREQUEST', [('Long', 'id', 'ID', 'id'), ('String', 'series', 'SERIES', ''), ('Long', 'correlative', 'CORRELATIVE', ''), ('Integer', 'epdTypeId', 'EPDTYPEID', ''),
                                                 ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''), ('String', 'inputPayload', 'INPUTPAYLOAD', 'lob'),
                                                 ('String', 'comRequestPayload', 'COMREQUESTPAYLOAD', 'lob'), ('LocalDateTime', 'creationDate', 'CREATIONDATE', '')]),
    'DocumentTypeEntity': ('ELECTRONICDOCUMENTTYPE', [('Long', 'id', 'ID', 'id'), ('String', 'sunatDocumentTypeCode', 'SUNATDOCUMENTTYPECODE', '')]),
}
DTOS = {'CustomerBillRequestCpe': [('Long', 'id'), ('String', 'documentType'), ('String', 'series'), ('Long', 'sequential'), ('Integer', 'status'), ('LocalDate', 'registrationDate'),
                                   ('String', 'inputPayload'), ('String', 'comRequestPayload')],
        'GetCustomerBillsData': [('List<CustomerBillRequestCpe>', 'requestCPE')]}
dj.register('model', *ENTITIES, 'CustomerBillSearch', 'CustomerBillCriteria')
dj.register('dto.response', *DTOS, 'GetCustomerBillsResponse')
dj.register('dto.mapper', 'CustomerBillMapper')
dj.register('repository', 'CustomerBillRequestRepository', 'DocumentTypeRepository', 'CustomerBillSpecifications')
dj.register('service', 'CustomerBillService')
dj.register('service.impl', 'CustomerBillServiceImpl')
dj.register('validation', 'CustomerBillValidator')
dj.register('controller', 'CustomerBillApi')
dj.register('controller.impl', 'CustomerBillController')

SEARCH = '''/** Validated search command: the registration date range (inclusive) and the optional filters. */
public record CustomerBillSearch(LocalDate dateFrom, LocalDate dateTo, String documentType, String series, Long sequential, Integer status) {
}'''

CRITERIA = '''/** Resolved database criteria: the registration instant range [from, toExclusive) and the optional filters. */
public record CustomerBillCriteria(LocalDateTime from, LocalDateTime toExclusive, Integer epdTypeId, String series, Long sequential, Integer status) {
}'''

REPOS = {
    'CustomerBillRequestRepository': '''@Repository
public interface CustomerBillRequestRepository extends JpaRepository<CustomerBillRequestEntity, Long>, JpaSpecificationExecutor<CustomerBillRequestEntity> {
}''',
    'DocumentTypeRepository': '''@Repository
public interface DocumentTypeRepository extends JpaRepository<DocumentTypeEntity, Long> {
    Optional<DocumentTypeEntity> findFirstBySunatDocumentTypeCodeOrderByIdAsc(String sunatDocumentTypeCode);
}''',
    'CustomerBillSpecifications': '''/** Dynamic filters of the search: the optional filters apply only when informed; the order is the registration date descending. */
public final class CustomerBillSpecifications {
    private CustomerBillSpecifications() {
    }

    public static Specification<CustomerBillRequestEntity> matching(CustomerBillCriteria criteria) {
        return (root, query, builder) -> {
            List<Predicate> predicates = new ArrayList<>();
            predicates.add(builder.greaterThanOrEqualTo(root.<LocalDateTime>get("creationDate"), criteria.from()));
            predicates.add(builder.lessThan(root.<LocalDateTime>get("creationDate"), criteria.toExclusive()));
            if (criteria.epdTypeId() != null) {
                predicates.add(builder.equal(root.get("epdTypeId"), criteria.epdTypeId()));
            }
            if (criteria.series() != null) {
                predicates.add(builder.equal(root.get("series"), criteria.series()));
            }
            if (criteria.sequential() != null) {
                predicates.add(builder.equal(root.get("correlative"), criteria.sequential()));
            }
            if (criteria.status() != null) {
                predicates.add(builder.equal(root.get("epdQueryStatusId"), criteria.status()));
            }
            query.orderBy(builder.desc(root.get("creationDate")), builder.desc(root.get("id")));
            return builder.and(predicates.toArray(new Predicate[0]));
        };
    }
}''',
}

SERVICE_IF = '''/** Consulta de solicitudes de comprobantes de pago electr\u00f3nicos. */
public interface CustomerBillService {
    GetCustomerBillsResponse getCustomerBills(RequestHeaders headers, String dateFrom, String dateTo, String documentType, String series, String sequential, String status);
}'''

VALIDATOR = '''/** Declared contract rules: dateFrom and dateTo are required dates (dateTo not before dateFrom); the other filters are optional and must have the permitted format. */
@Component
public class CustomerBillValidator {
    private static final Pattern DOCUMENT_TYPE = Pattern.compile("^[0-9A-Za-z]{1,20}$");
    private static final Pattern SERIES = Pattern.compile("^[0-9A-Za-z-]{1,20}$");
    private static final Pattern SEQUENTIAL = Pattern.compile("^[0-9]{1,18}$");
    private static final Pattern STATUS = Pattern.compile("^[0-9]{1,9}$");
    private static final String INVALID_PARAMETERS = "Los par\u00e1metros obligatorios dateFrom y dateTo son requeridos o contienen valores no v\u00e1lidos.";

    public CustomerBillSearch search(String dateFrom, String dateTo, String documentType, String series, String sequential, String status) {
        LocalDate from = date(dateFrom);
        LocalDate to = date(dateTo);
        require(!to.isBefore(from));
        require(documentType == null || DOCUMENT_TYPE.matcher(documentType).matches());
        require(series == null || SERIES.matcher(series).matches());
        require(sequential == null || SEQUENTIAL.matcher(sequential).matches());
        require(status == null || STATUS.matcher(status).matches());
        return new CustomerBillSearch(from, to, documentType, series, sequential == null ? null : Long.valueOf(sequential), status == null ? null : Integer.valueOf(status));
    }

    private static LocalDate date(String value) {
        if (value == null) {
            throw ServiceOperationException.badRequest(INVALID_PARAMETERS);
        }
        try {
            return LocalDate.parse(value);
        } catch (DateTimeParseException e) {
            throw ServiceOperationException.badRequest(INVALID_PARAMETERS);
        }
    }

    private static void require(boolean valid) {
        if (!valid) {
            throw ServiceOperationException.badRequest(INVALID_PARAMETERS);
        }
    }
}'''

MAPPER = '''/** Explicit mapping between the JPA entities and the API contract. */
@Component
public class CustomerBillMapper {
    private static final String SUCCESS_MESSAGE = "Operaci\u00f3n exitosa";

    public CustomerBillRequestCpe item(CustomerBillRequestEntity row, String documentType) {
        CustomerBillRequestCpe item = new CustomerBillRequestCpe();
        item.setId(row.getId());
        item.setDocumentType(documentType);
        item.setSeries(row.getSeries());
        item.setSequential(row.getCorrelative());
        item.setStatus(row.getEpdQueryStatusId());
        item.setRegistrationDate(row.getCreationDate() == null ? null : row.getCreationDate().toLocalDate());
        item.setInputPayload(row.getInputPayload());
        item.setComRequestPayload(row.getComRequestPayload());
        return item;
    }

    public GetCustomerBillsResponse response(List<CustomerBillRequestCpe> items) {
        GetCustomerBillsData data = new GetCustomerBillsData();
        data.setRequestCPE(items);
        GetCustomerBillsResponse response = new GetCustomerBillsResponse();
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
public class CustomerBillServiceImpl implements CustomerBillService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String NOT_FOUND_DETAIL = "No se encontraron solicitudes CPE con los criterios ingresados.";

    private final CustomerBillRequestRepository requests;
    private final DocumentTypeRepository documentTypes;
    private final CustomerBillMapper mapper;
    private final CustomerBillValidator validator;
    private final PersistenceExceptionTranslator translator;

    @Override
    public GetCustomerBillsResponse getCustomerBills(RequestHeaders headers, String dateFrom, String dateTo, String documentType, String series, String sequential, String status) {
        String menTran = prefix(headers);
        CustomerBillSearch search = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validar(headers, dateFrom, dateTo, documentType, series, sequential, status));
        List<CustomerBillRequestCpe> items = ejecutarActividad(menTran, ConstanApi.ACT2_CONSULTAR_COMPROBANTES_CPE, () -> consultar(menTran, search));
        return mapper.response(items);
    }

    private CustomerBillSearch validar(RequestHeaders headers, String dateFrom, String dateTo, String documentType, String series, String sequential, String status) {
        log.info(
                "getCustomerBills applicationName={}, transactionId={}, userId={}, dateFrom={}, dateTo={}, documentType={}, series={}, sequential={}, status={}",
                headers != null ? headers.applicationName() : null,
                headers != null ? headers.transactionId() : null,
                headers != null ? headers.userId() : null,
                dateFrom,
                dateTo,
                documentType,
                series,
                sequential,
                status
        );
        return validator.search(dateFrom, dateTo, documentType, series, sequential, status);
    }

    private List<CustomerBillRequestCpe> consultar(String menTran, CustomerBillSearch search) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_CONSULTAR_COMPROBANTES_CPE, ConstanApi.LOG_ERROR_DATOS_ACT2_CONSULTAR_COMPROBANTES_CPE, () -> leer(menTran, search));
    }

    private List<CustomerBillRequestCpe> leer(String menTran, CustomerBillSearch search) {
        Integer typeId = null;
        if (search.documentType() != null) {
            Optional<DocumentTypeEntity> type = documentTypes.findFirstBySunatDocumentTypeCodeOrderByIdAsc(search.documentType());
            if (type.isEmpty()) {
                throw notFound(menTran);
            }
            typeId = Math.toIntExact(type.get().getId());
        }
        CustomerBillCriteria criteria = new CustomerBillCriteria(search.dateFrom().atStartOfDay(), search.dateTo().plusDays(1).atStartOfDay(), typeId, search.series(),
                search.sequential(), search.status());
        List<CustomerBillRequestEntity> rows = requests.findAll(CustomerBillSpecifications.matching(criteria));
        if (rows.isEmpty()) {
            throw notFound(menTran);
        }
        Map<Long, String> codes = new HashMap<>();
        List<Long> typeIds = rows.stream().map(CustomerBillRequestEntity::getEpdTypeId).filter(Objects::nonNull).map(Integer::longValue).distinct().toList();
        documentTypes.findAllById(typeIds).forEach(type -> codes.put(type.getId(), type.getSunatDocumentTypeCode()));
        return rows.stream().map(row -> mapper.item(row, row.getEpdTypeId() == null ? null : codes.get(row.getEpdTypeId().longValue()))).toList();
    }

    private ServiceOperationException notFound(String menTran) {
        log.error(ERROR_BUSINESS_PATTERN, menTran, ConstanApi.ACT2_CONSULTAR_COMPROBANTES_CPE, HttpStatus.NOT_FOUND.value(), NOT_FOUND_DETAIL);
        return new ServiceOperationException(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);
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

PARAMS = [('dateFrom', True, 'Fecha inicial del rango de registro utilizado como filtro de consulta de comprobantes electr\u00f3nicos.'),
          ('dateTo', True, 'Fecha final del rango de registro utilizado como filtro de consulta de comprobantes electr\u00f3nicos.'),
          ('documentType', False, 'Tipo de comprobante electr\u00f3nico seg\u00fan c\u00f3digo SUNAT.'), ('series', False, 'Serie del comprobante electr\u00f3nico.'),
          ('sequential', False, 'N\u00famero correlativo del comprobante electr\u00f3nico.'), ('status', False, 'Estado de la solicitud del comprobante electr\u00f3nico.')]


def api():
    out = ['/** Define el contrato del endpoint REST de consulta de solicitudes de comprobantes de pago electr\u00f3nicos (contrato OpenAPI). */', 'public interface CustomerBillApi {', '    /**',
           '     * Consulta solicitudes de comprobantes de pago electr\u00f3nicos.', '     *']
    out += [f'     * @param {n} {d}' for n, _, d in PARAMS] + [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    out += ['     * @return respuesta HTTP con el modelo GetCustomerBillsResponse definido en el contrato', '     */',
            '    @GetMapping(path = "/api/v1/dom-customerBills", produces = {"application/json"})', '    @Operation(summary = "Consulta solicitudes de comprobantes de pago electr\u00f3nicos.")',
            '    @ApiResponses({']
    rows = ['      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = GetCustomerBillsResponse.class)))']
    rows += [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS[c]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for c in ('400', '404', '500', '503', '504')]
    out += [',\n'.join(rows), '    })', '    ResponseEntity<GetCustomerBillsResponse> getCustomerBills(']
    args = [f'            @RequestParam(name = "{n}", required = {str(r).lower()}) String {n}' for n, r, _ in PARAMS] + [f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS]
    out += [',\n'.join(args) + ');', '}']
    return '\n'.join(out)


def controller():
    args = [f'            String {n}' for n, _, _ in PARAMS] + [f'            String {c}' for _, c, _ in dj.HEADERS]
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class CustomerBillController implements CustomerBillApi {', '    private final CustomerBillService service;', '',
                      '    @Override', '    public ResponseEntity<GetCustomerBillsResponse> getCustomerBills(', ',\n'.join(args) + ') {',
                      '        log.info("getCustomerBills - transactionId: {}", xCorrelationId);', '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);',
                      '        return ResponseEntity.ok(service.getCustomerBills(headers, dateFrom, dateTo, documentType, series, sequential, status));', '    }', '}'])


def handler():
    text = re.sub(r'    private String operationMessage\(.*?\n    }\n\n    private String method', '    private String operationMessage(String method, String uri, HttpStatus status) {\n        return "PROCESGETCUSTOMERBILLS_SERVICE_ERROR";\n    }\n\n    private String method',
                  dj.HANDLER, flags=re.S)
    text = text.replace('"Par\\u00e1metros obligatorios incompletos o con valores no v\\u00e1lidos."', '"Los par\\u00e1metros obligatorios dateFrom y dateTo son requeridos o contienen valores no v\\u00e1lidos."')
    return text.replace('"No se encontraron resultados con los datos ingresados."', '"No se encontraron solicitudes CPE con los criterios ingresados."')


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    for cls, (table, fields) in ENTITIES.items():
        put('model', cls, dj.entity(cls, table, fields))
    put('model', 'CustomerBillSearch', SEARCH)
    put('model', 'CustomerBillCriteria', CRITERIA)
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    for cls, fields in DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields))
    put('dto.response', 'GetCustomerBillsResponse', dj.envelope('GetCustomerBillsResponse', 'GetCustomerBillsData'))
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    put('dto.mapper', 'CustomerBillMapper', MAPPER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', handler())
    for cls, body in REPOS.items():
        put('repository', cls, body)
    put('service', 'CustomerBillService', SERVICE_IF)
    put('service.impl', 'CustomerBillServiceImpl', SERVICE_IMPL)
    put('validation', 'CustomerBillValidator', VALIDATOR)
    put('controller', 'CustomerBillApi', api())
    put('controller.impl', 'CustomerBillController', controller())
    return files


ORIGINAL_CONSTANTS = dj.activity_constants


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False), ('ACT2_CONSULTAR_COMPROBANTES_CPE', 'CONSULTAR_COMPROBANTES_CPE', True)]
    try:
        return ORIGINAL_CONSTANTS()
    finally:
        dj.ACTIVITIES = saved


TESTS = {}
TESTS['CustomerBillValidatorTest'] = ('validation', '''class CustomerBillValidatorTest {
    private static final Long SEQUENTIAL = 135L;
    private static final Integer STATUS = 1;

    private final CustomerBillValidator validator = new CustomerBillValidator();

    private void assertBadRequest(Executable executable) {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, executable);
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
    }

    @Test
    void acceptsTheRequiredDatesAlone() {
        CustomerBillSearch search = validator.search("2026-10-10", "2026-10-12", null, null, null, null);
        assertEquals("2026-10-10", search.dateFrom().toString());
        assertNull(search.sequential());
        assertNull(search.status());
    }

    @Test
    void convertsTheOptionalFilters() {
        CustomerBillSearch search = validator.search("2026-10-10", "2026-10-10", "RECIBO", "SB-122", "135", "1");
        assertEquals(SEQUENTIAL, search.sequential());
        assertEquals(STATUS, search.status());
        assertEquals("SB-122", search.series());
    }

    @Test
    void rejectsMissingOrMalformedDates() {
        assertBadRequest(() -> validator.search(null, "2026-10-12", null, null, null, null));
        assertBadRequest(() -> validator.search("2026-10-10", null, null, null, null, null));
        assertBadRequest(() -> validator.search("10/10/2026", "2026-10-12", null, null, null, null));
        assertBadRequest(() -> validator.search("2026-10-13", "2026-10-12", null, null, null, null));
    }

    @Test
    void rejectsMalformedOptionalFilters() {
        assertBadRequest(() -> validator.search("2026-10-10", "2026-10-12", "", null, null, null));
        assertBadRequest(() -> validator.search("2026-10-10", "2026-10-12", null, "SB 1", null, null));
        assertBadRequest(() -> validator.search("2026-10-10", "2026-10-12", null, null, "12a", null));
        assertBadRequest(() -> validator.search("2026-10-10", "2026-10-12", null, null, null, "x"));
    }
}''')
TESTS['CustomerBillMapperTest'] = ('dto.mapper', '''class CustomerBillMapperTest {
    private static final Long ID = 132L;
    private static final Long SEQUENTIAL = 135L;
    private static final Integer STATUS = 1;

    private final CustomerBillMapper mapper = new CustomerBillMapper();

    private CustomerBillRequestEntity row() {
        CustomerBillRequestEntity row = new CustomerBillRequestEntity();
        row.setId(ID);
        row.setSeries("SB-122");
        row.setCorrelative(SEQUENTIAL);
        row.setEpdQueryStatusId(STATUS);
        row.setInputPayload("in");
        row.setComRequestPayload("com");
        row.setCreationDate(LocalDateTime.parse("2026-10-12T10:15:30"));
        return row;
    }

    @Test
    void mapsEveryContractField() {
        CustomerBillRequestCpe item = mapper.item(row(), "RECIBO");
        assertEquals(ID, item.getId());
        assertEquals("RECIBO", item.getDocumentType());
        assertEquals("SB-122", item.getSeries());
        assertEquals(SEQUENTIAL, item.getSequential());
        assertEquals(STATUS, item.getStatus());
        assertEquals("2026-10-12", item.getRegistrationDate().toString());
        assertEquals("in", item.getInputPayload());
        assertEquals("com", item.getComRequestPayload());
    }

    @Test
    void keepsMissingValuesEmpty() {
        CustomerBillRequestCpe item = mapper.item(new CustomerBillRequestEntity(), null);
        assertNull(item.getRegistrationDate());
        assertNull(item.getDocumentType());
    }

    @Test
    void responseWrapsTheItemsInTheEnvelope() {
        GetCustomerBillsResponse response = mapper.response(List.of(mapper.item(row(), "RECIBO")));
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertEquals(1, response.getData().getRequestCPE().size());
    }
}''')
TESTS['CustomerBillSpecificationsTest'] = ('repository', '''class CustomerBillSpecificationsTest {
    private static final int DATE_RANGE_PREDICATES = 2;
    private static final int ALL_PREDICATES = 6;\n    private static final Long SEQUENTIAL = 135L;

    @SuppressWarnings("unchecked")
    private Predicate[] predicatesOf(CustomerBillCriteria criteria) {
        Root<CustomerBillRequestEntity> root = Mockito.mock(Root.class);
        CriteriaQuery<Object> query = Mockito.mock(CriteriaQuery.class);
        CriteriaBuilder builder = Mockito.mock(CriteriaBuilder.class);
        CustomerBillSpecifications.matching(criteria).toPredicate(root, query, builder);
        ArgumentCaptor<Predicate[]> captor = ArgumentCaptor.forClass(Predicate[].class);
        Mockito.verify(builder).and(captor.capture());
        return captor.getValue();
    }

    @Test
    void appliesOnlyTheDateRangeWhenNoOptionalFilterIsInformed() {
        CustomerBillCriteria criteria = new CustomerBillCriteria(LocalDateTime.parse("2026-10-10T00:00:00"), LocalDateTime.parse("2026-10-13T00:00:00"), null, null, null, null);
        assertEquals(DATE_RANGE_PREDICATES, predicatesOf(criteria).length);
    }

    @Test
    void addsEveryInformedFilter() {
        CustomerBillCriteria criteria = new CustomerBillCriteria(LocalDateTime.parse("2026-10-10T00:00:00"), LocalDateTime.parse("2026-10-13T00:00:00"), 1, "SB-122", SEQUENTIAL, 1);
        assertEquals(ALL_PREDICATES, predicatesOf(criteria).length);
    }
}''')
TESTS['GlobalExceptionHandlerTest'] = ('exception', '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request() {
        return new ServletWebRequest(new MockHttpServletRequest("GET", "/api/v1/dom-customerBills"));
    }

    @Test
    void badRequestUsesTheContractShape() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request());
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF1", response.getBody().getSubType());
        assertEquals("PROCESGETCUSTOMERBILLS_SERVICE_ERROR", response.getBody().getMessage());
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
TESTS['CustomerBillServiceImplTest'] = ('service.impl', '''class CustomerBillServiceImplTest {
    private static final Long ID = 132L;
    private static final Long TYPE_ID = 1L;
    private static final Long SEQUENTIAL = 135L;

    private final CustomerBillRequestRepository requests = Mockito.mock(CustomerBillRequestRepository.class);
    private final DocumentTypeRepository documentTypes = Mockito.mock(DocumentTypeRepository.class);
    private final CustomerBillServiceImpl service = new CustomerBillServiceImpl(requests, documentTypes, new CustomerBillMapper(), new CustomerBillValidator(),
            new PersistenceExceptionTranslator());
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");

    private DocumentTypeEntity type() {
        DocumentTypeEntity type = new DocumentTypeEntity();
        type.setId(TYPE_ID);
        type.setSunatDocumentTypeCode("RECIBO");
        return type;
    }

    private void stubRows(List<CustomerBillRequestEntity> rows) {
        Mockito.when(requests.findAll(ArgumentMatchers.<Specification<CustomerBillRequestEntity>>any())).thenReturn(rows);
    }

    private GetCustomerBillsResponse call(String documentType) {
        return service.getCustomerBills(headers, "2026-10-10", "2026-10-12", documentType, null, null, null);
    }

    @Test
    void returnsTheMatchingRequestsWithTheirDocumentTypeCode() {
        CustomerBillRequestEntity row = new CustomerBillRequestEntity();
        row.setId(ID);
        row.setEpdTypeId(1);
        row.setCorrelative(SEQUENTIAL);
        row.setCreationDate(LocalDateTime.parse("2026-10-11T08:00:00"));
        stubRows(List.of(row));
        Mockito.when(documentTypes.findAllById(ArgumentMatchers.<Iterable<Long>>any())).thenReturn(List.of(type()));
        CustomerBillRequestCpe item = call(null).getData().getRequestCPE().get(0);
        assertEquals(ID, item.getId());
        assertEquals("RECIBO", item.getDocumentType());
        assertEquals(SEQUENTIAL, item.getSequential());
    }

    @Test
    void anEmptyResultIsNotFound() {
        stubRows(List.of());
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> call(null));
        assertEquals(HttpStatus.NOT_FOUND, failure.getStatus());
    }

    @Test
    void anUnknownDocumentTypeIsNotFoundWithoutSearching() {
        Mockito.when(documentTypes.findFirstBySunatDocumentTypeCodeOrderByIdAsc("XX")).thenReturn(Optional.empty());
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> call("XX"));
        assertEquals(HttpStatus.NOT_FOUND, failure.getStatus());
        Mockito.verifyNoInteractions(requests);
    }

    @Test
    void invalidParametersFailBeforeTouchingTheDatabase() {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.getCustomerBills(headers, null, null, null, null, null, null));
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
        Mockito.verifyNoInteractions(requests);
    }

    @Test
    void dataAccessTimeoutsBecomeGatewayTimeout() {
        Mockito.when(requests.findAll(ArgumentMatchers.<Specification<CustomerBillRequestEntity>>any())).thenThrow(new QueryTimeoutException("slow"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> call(null));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, failure.getStatus());
    }
}''')
TESTS['CustomerBillApiContractTest'] = ('controller', '''class CustomerBillApiContractTest {
    private final CustomerBillService service = Mockito.mock(CustomerBillService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new CustomerBillController(service))
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
        return withHeaders(get("/api/v1/dom-customerBills")).param("dateFrom", "2026-10-10").param("dateTo", "2026-10-12");
    }

    @Test
    void getReturnsTheEnvelope() throws Exception {
        GetCustomerBillsResponse response = new GetCustomerBillsResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("ok");
        Mockito.when(service.getCustomerBills(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq("2026-10-10"), ArgumentMatchers.eq("2026-10-12"), ArgumentMatchers.isNull(),
                ArgumentMatchers.isNull(), ArgumentMatchers.isNull(), ArgumentMatchers.isNull())).thenReturn(response);
        mvc.perform(search()).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("ok"));
    }

    @Test
    void aMissingRequiredParameterIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(withHeaders(get("/api/v1/dom-customerBills")).param("dateFrom", "2026-10-10"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.subType").value("IDF1"));
    }

    @Test
    void notFoundIsReportedWithTheOperationMessage() throws Exception {
        Mockito.when(service.getCustomerBills(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.anyString(), ArgumentMatchers.anyString(), ArgumentMatchers.any(),
                ArgumentMatchers.any(), ArgumentMatchers.any(), ArgumentMatchers.any())).thenThrow(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"));
        mvc.perform(search()).andExpect(status().isNotFound()).andExpect(jsonPath("$.message").value("PROCESGETCUSTOMERBILLS_SERVICE_ERROR"));
    }
}''')
dj.register('repository', 'CustomerBillSpecificationsTest')


def build_tests(pkg):
    import dom_cpe_request_tests as dt
    files = {}
    for name, (suffix, body) in TESTS.items():
        statics = dt.MVC_STATICS if name == 'CustomerBillApiContractTest' else dt.ASSERT
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


ASSUMPTIONS = [
    ('A-01', 'Base package and application class are technical choices; no source defines them (dom-customerBills -> com.claro.dom.customerbills, dom-customerBillQuery -> com.claro.dom.customerbillquery).'),
    ('A-02', 'Tables are mapped in schema FACEL: EPDREQUEST (ID, SERIES, CORRELATIVE, EPDTYPEID, EPDQUERYSTATUSID, INPUTPAYLOAD, COMREQUESTPAYLOAD, CREATIONDATE) and ELECTRONICDOCUMENTTYPE (ID, SUNATDOCUMENTTYPECODE); the service is read-only.'),
    ('A-03', 'Gate decisions delegated by the user (swagger-governs): dateFrom and dateTo are always required (Sparx makes them optional when sequential is informed); the response uses the Swagger names/types (data.requestCPE[], sequential int64, status int, registrationDate date).'),
    ('A-04', 'Sparx names the filter/output columns V_SERIE and V_CORRELATIVO, which are not in the EPDREQUEST data definition; the definition columns SERIES and CORRELATIVE are used. COMREQUESTPAYLOAD is mapped as a CLOB column of EPDREQUEST because Sparx selects it, although the data definition does not list it.'),
    ('A-05', 'The date range filters CREATIONDATE in [dateFrom 00:00, dateTo + 1 day 00:00); the order is CREATIONDATE descending, then ID descending (tie-break not defined by the sources).'),
    ('A-06', 'documentType is the SUNAT document type code resolved through ELECTRONICDOCUMENTTYPE.SUNATDOCUMENTTYPECODE and returned in data.requestCPE[].documentType (Sparx output says EPDTYPEID; Swagger says string); status filters EPDQUERYSTATUSID directly.'),
    ('A-07', 'An empty result returns 404 (declared by the OpenAPI); Sparx says 200 with an empty list. Swagger governs by the delegated decision; this is reported as unresolved Swagger-vs-Sparx behavior.'),
    ('A-08', 'The MAX_DAYS_RANGE limit (a Sparx property whose value is not defined) is not applied; only dateFrom <= dateTo is validated.'),
    ('A-09', 'Format validation not defined by the sources: documentType 1-20 alphanumerics, series 1-20 alphanumerics or hyphens, sequential 1-18 digits, status 1-9 digits.'),
    ('A-10', 'No 401/403 handling and only the statuses declared by the OpenAPI (200/400/404/500/503/504) are emitted.'),
]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    service = next((a for a in argv if not a.startswith('-')), None)
    if service not in PACKAGES:
        print(f'unsupported service {service!r}; expected one of {sorted(PACKAGES)}', file=sys.stderr)
        return 2
    package, app = PACKAGES[service]
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = package, app, ASSUMPTIONS, 'customer-bills-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': package, 'base_package_path': package.replace('.', '/'), 'group_id': package, 'application_class': app}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'customer_bills_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main(argv)


if __name__ == '__main__':
    sys.exit(main())
