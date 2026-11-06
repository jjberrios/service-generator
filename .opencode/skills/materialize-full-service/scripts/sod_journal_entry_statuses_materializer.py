"""Deterministic materializer of the sod-journal-entry-statuses service (read-only catalog over FACEL.JOURNALENTRYSTATUS).

Same controls as dom_cpe_request_materializer (gate recomputed first, archetype assembly, file protection, lock, manifest last).
Usage: python sod_journal_entry_statuses_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import re
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402

PACKAGE = 'com.claro.sod.journalentrystatuses'
dj.register('model', 'JournalEntryStatusEntity')
dj.register('dto.response', 'JournalEntryStatus', 'GetJournalEntryStatusesData', 'GetJournalEntryStatusesResponse')
dj.register('dto.mapper', 'JournalEntryStatusMapper')
dj.register('repository', 'JournalEntryStatusRepository')
dj.register('service', 'JournalEntryStatusService')
dj.register('service.impl', 'JournalEntryStatusServiceImpl')
dj.register('controller', 'JournalEntryStatusApi')
dj.register('controller.impl', 'JournalEntryStatusController')

ENTITY = ('JOURNALENTRYSTATUS', [('Long', 'id', 'ID', 'id'), ('String', 'value', 'VALUE', ''), ('String', 'description', 'DESCRIPTION', ''), ('Integer', 'status', 'STATUS', '')])

MAPPER = '''/** Explicit mapping between the JPA entity and the API contract. */
@Component
public class JournalEntryStatusMapper {
    private static final String SUCCESS_MESSAGE = "Operaci\u00f3n exitosa.";

    public GetJournalEntryStatusesResponse response(List<JournalEntryStatusEntity> rows) {
        GetJournalEntryStatusesData data = new GetJournalEntryStatusesData();
        data.setFields(rows.stream().map(this::item).toList());
        data.setTotal(rows.size());
        GetJournalEntryStatusesResponse response = new GetJournalEntryStatusesResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private JournalEntryStatus item(JournalEntryStatusEntity row) {
        JournalEntryStatus item = new JournalEntryStatus();
        item.setId(row.getId());
        item.setValue(row.getValue());
        item.setDescription(row.getDescription());
        item.setStatus(row.getStatus());
        return item;
    }
}'''

REPOSITORY = '''@Repository
public interface JournalEntryStatusRepository extends JpaRepository<JournalEntryStatusEntity, Long> {
    List<JournalEntryStatusEntity> findAllByOrderByIdAsc();
}'''

SERVICE_IF = '''/** Consulta del cat\u00e1logo de estados de asiento contable. */
public interface JournalEntryStatusService {
    GetJournalEntryStatusesResponse getJournalEntryStatuses(RequestHeaders headers);
}'''

SERVICE_IMPL = '''/** Activity-logged read-only service; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class JournalEntryStatusServiceImpl implements JournalEntryStatusService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";

    private final JournalEntryStatusRepository repository;
    private final JournalEntryStatusMapper mapper;
    private final PersistenceExceptionTranslator translator;

    @Override
    public GetJournalEntryStatusesResponse getJournalEntryStatuses(RequestHeaders headers) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validar(headers));
        List<JournalEntryStatusEntity> rows = ejecutarActividad(menTran, ConstanApi.ACT2_CONSULTAR_CATALOGO_DE_ESTADOS, () -> consultar(menTran));
        return mapper.response(rows);
    }

    private Boolean validar(RequestHeaders headers) {
        log.info(
                "getJournalEntryStatuses applicationName={}, transactionId={}, userId={}",
                headers != null ? headers.applicationName() : null,
                headers != null ? headers.transactionId() : null,
                headers != null ? headers.userId() : null
        );
        return Boolean.TRUE;
    }

    private List<JournalEntryStatusEntity> consultar(String menTran) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_CONSULTAR_CATALOGO_DE_ESTADOS, ConstanApi.LOG_ERROR_DATOS_ACT2_CONSULTAR_CATALOGO_DE_ESTADOS,
                repository::findAllByOrderByIdAsc);
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
    out = ['/** Define el contrato del endpoint REST del cat\u00e1logo de estados de asiento contable (contrato OpenAPI). */', 'public interface JournalEntryStatusApi {', '    /**',
           '     * Consulta el cat\u00e1logo de estados de asiento contable.', '     *'] + [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    out += ['     * @return respuesta HTTP con el modelo GetJournalEntryStatusesResponse definido en el contrato', '     */',
            '    @GetMapping(path = "/api/v1/sod-journal-entry-statuses/journalEntryStatuses", produces = {"application/json"})',
            '    @Operation(summary = "Consulta el cat\u00e1logo de estados de asiento contable.")', '    @ApiResponses({']
    rows = ['      @ApiResponse(responseCode = "200", description = "OK", content = @Content(mediaType = "application/json", schema = @Schema(implementation = GetJournalEntryStatusesResponse.class)))']
    rows += [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS[c]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for c in ('400', '404', '500', '503', '504')]
    out += [',\n'.join(rows), '    })', '    ResponseEntity<GetJournalEntryStatusesResponse> getJournalEntryStatuses(']
    out += [',\n'.join(f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS) + ');', '}']
    return '\n'.join(out)


def controller():
    args = [f'            String {c}' for _, c, _ in dj.HEADERS]
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class JournalEntryStatusController implements JournalEntryStatusApi {',
                      '    private final JournalEntryStatusService service;', '', '    @Override', '    public ResponseEntity<GetJournalEntryStatusesResponse> getJournalEntryStatuses(',
                      ',\n'.join(args) + ') {', '        log.info("getJournalEntryStatuses - transactionId: {}", xCorrelationId);',
                      '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);', '        return ResponseEntity.ok(service.getJournalEntryStatuses(headers));', '    }', '}'])


def handler():
    text = re.sub(r'    private String operationMessage\(.*?\n    }\n\n    private String method', '    private String operationMessage(String method, String uri, HttpStatus status) {\n        return "PROCESGETJOURNALENTRYSTATUSES_SERVICE_ERROR";\n    }\n\n    private String method', dj.HANDLER, flags=re.S)
    text = text.replace('"Par\\u00e1metros obligatorios incompletos o con valores no v\\u00e1lidos."', '"Los par\\u00e1metros de la solicitud no presentan un formato v\\u00e1lido."')
    return text.replace('"No se encontraron resultados con los datos ingresados."', '"No se encontraron estados de asiento contable."')


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    put('model', 'JournalEntryStatusEntity', dj.entity('JournalEntryStatusEntity', *ENTITY))
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    put('dto.response', 'JournalEntryStatus', dj.dto('JournalEntryStatus', [('Long', 'id'), ('String', 'value'), ('String', 'description'), ('Integer', 'status')], non_null=False))
    put('dto.response', 'GetJournalEntryStatusesData', dj.dto('GetJournalEntryStatusesData', [('List<JournalEntryStatus>', 'fields'), ('Integer', 'total')]))
    put('dto.response', 'GetJournalEntryStatusesResponse', dj.envelope('GetJournalEntryStatusesResponse', 'GetJournalEntryStatusesData'))
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    put('dto.mapper', 'JournalEntryStatusMapper', MAPPER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', handler())
    put('repository', 'JournalEntryStatusRepository', REPOSITORY)
    put('service', 'JournalEntryStatusService', SERVICE_IF)
    put('service.impl', 'JournalEntryStatusServiceImpl', SERVICE_IMPL)
    put('controller', 'JournalEntryStatusApi', api())
    put('controller.impl', 'JournalEntryStatusController', controller())
    return files


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False), ('ACT2_CONSULTAR_CATALOGO_DE_ESTADOS', 'CONSULTAR_CATALOGO_DE_ESTADOS', True)]
    try:
        return ORIGINAL()
    finally:
        dj.ACTIVITIES = saved


ORIGINAL = dj.activity_constants

TESTS = {
    'JournalEntryStatusMapperTest': ('dto.mapper', '''class JournalEntryStatusMapperTest {
    private final JournalEntryStatusMapper mapper = new JournalEntryStatusMapper();

    private JournalEntryStatusEntity row(Long id) {
        JournalEntryStatusEntity row = new JournalEntryStatusEntity();
        row.setId(id);
        row.setValue("V");
        row.setDescription("D");
        row.setStatus(1);
        return row;
    }

    @Test
    void mapsTheRowsAndTheTotal() {
        GetJournalEntryStatusesResponse response = mapper.response(List.of(row(1L), row(2L)));
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertEquals(2, response.getData().getTotal());
        assertEquals("V", response.getData().getFields().get(0).getValue());
    }

    @Test
    void anEmptyCatalogHasNoFieldsAndTotalZero() {
        GetJournalEntryStatusesResponse response = mapper.response(List.of());
        assertTrue(response.getData().getFields().isEmpty());
        assertEquals(0, response.getData().getTotal());
    }
}'''),
    'GlobalExceptionHandlerTest': ('exception', '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request() {
        return new ServletWebRequest(new MockHttpServletRequest("GET", "/api/v1/sod-journal-entry-statuses/journalEntryStatuses"));
    }

    @Test
    void badRequestUsesTheContractShape() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request());
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF1", response.getBody().getSubType());
        assertEquals("PROCESGETJOURNALENTRYSTATUSES_SERVICE_ERROR", response.getBody().getMessage());
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
}'''),
    'JournalEntryStatusServiceImplTest': ('service.impl', '''class JournalEntryStatusServiceImplTest {
    private final JournalEntryStatusRepository repository = Mockito.mock(JournalEntryStatusRepository.class);
    private final JournalEntryStatusServiceImpl service = new JournalEntryStatusServiceImpl(repository, new JournalEntryStatusMapper(), new PersistenceExceptionTranslator());
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");

    @Test
    void returnsTheCatalogOrderedByTheRepository() {
        JournalEntryStatusEntity row = new JournalEntryStatusEntity();
        row.setId(1L);
        Mockito.when(repository.findAllByOrderByIdAsc()).thenReturn(List.of(row));
        assertEquals(1, service.getJournalEntryStatuses(headers).getData().getTotal());
    }

    @Test
    void anEmptyCatalogIsASuccessfulEmptyList() {
        Mockito.when(repository.findAllByOrderByIdAsc()).thenReturn(List.of());
        assertEquals(0, service.getJournalEntryStatuses(headers).getData().getTotal());
    }

    @Test
    void timeoutsBecomeGatewayTimeout() {
        Mockito.when(repository.findAllByOrderByIdAsc()).thenThrow(new QueryTimeoutException("slow"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.getJournalEntryStatuses(headers));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, failure.getStatus());
    }
}'''),
    'JournalEntryStatusApiContractTest': ('controller', '''class JournalEntryStatusApiContractTest {
    private final JournalEntryStatusService service = Mockito.mock(JournalEntryStatusService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new JournalEntryStatusController(service))
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

    @Test
    void getReturnsTheEnvelope() throws Exception {
        GetJournalEntryStatusesResponse response = new GetJournalEntryStatusesResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("ok");
        Mockito.when(service.getJournalEntryStatuses(ArgumentMatchers.any(RequestHeaders.class))).thenReturn(response);
        mvc.perform(withHeaders(get("/api/v1/sod-journal-entry-statuses/journalEntryStatuses"))).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("ok"));
    }

    @Test
    void aMissingRequiredHeaderIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(get("/api/v1/sod-journal-entry-statuses/journalEntryStatuses"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.subType").value("IDF1"));
    }
}'''),
}


def build_tests(pkg):
    import dom_cpe_request_tests as dt
    files = {}
    for name, (suffix, body) in TESTS.items():
        statics = dt.MVC_STATICS if name.endswith('ContractTest') else dt.ASSERT
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.sod.journalentrystatuses and application class SodJournalEntryStatusesApplication are technical choices; no source defines them.'),
    ('A-02', 'FACEL.JOURNALENTRYSTATUS is mapped read-only with ID, VALUE, DESCRIPTION, STATUS; the query orders by ID ascending; no filters or paging.'),
    ('A-03', 'Gate decisions delegated by the user (swagger-governs): list is data.fields with data.total; no 401/403 handling; only 200/400/404/500/503/504 are emitted.'),
    ('A-04', 'An empty catalog returns 200 with an empty list and total 0 (Sparx rule); the OpenAPI also declares 404 without saying when, so 404 is never produced by this code.'),
    ('A-05', 'Missing required headers are rejected by the framework as 400 (IDF1); header contents are not validated further (the sources define no format).'),
]


def main():
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, 'SodJournalEntryStatusesApplication', ASSUMPTIONS, 'sod-journal-entry-statuses-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': 'SodJournalEntryStatusesApplication'}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'sod_journal_entry_statuses_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main()


if __name__ == '__main__':
    sys.exit(main())
