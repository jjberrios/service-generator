"""Deterministic materializer of the dom-journeyEntry service (JPA profile of claro-spring-ms): six operations over the FACEL journal entry tables.

Reuses the machinery of dom_cpe_request_materializer (gate recomputed first, archetype assembly, file protection, per-service lock, manifest last).

Usage: python dom_journey_entry_materializer.py <service> [--dry-run]
"""
from pathlib import Path
import re
import sys
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dom_cpe_request_java as dj  # noqa: E402
import dom_cpe_request_materializer as dm  # noqa: E402
import dom_journey_entry_java as jj  # noqa: E402

PACKAGE = jj.PACKAGE

SERVICE_IMPL = '''/** Servicio con registro de actividades; el log es solo instrumentacion y nunca cambia estados ni resultados. */
@Service
@RequiredArgsConstructor
@Slf4j
public class JourneyEntryServiceImpl implements JourneyEntryService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String INVALID_FILTER = "Par\u00e1metros, headers o campos requeridos inv\u00e1lidos.";
    private static final String ENTRY_NOT_FOUND = "No se encontr\u00f3 el recurso solicitado.";
    private static final String CPE_NOT_ACCEPTED = "El CPE no cumple las condiciones requeridas o no existe configuraci\u00f3n coincidente.";
    private static final String CONFLICT_DETAIL = "Referencia duplicada o conflicto concurrente.";
    private static final String STATUS_MISSING = "No existe el estado contable requerido en el cat\u00e1logo.";
    private static final List<String> ACCEPTED_CPE = List.of("ACEPTADO", "ACEPTADO_CON_OBSERVACIONES");
    private static final Integer ACTIVE = 1;
    private static final String WILDCARD = "%";
    private static final String SEPARATOR = "-";

    private final JournalEntryRepository entries;
    private final JournalEntryHistRepository history;
    private final JournalEntryStatusRepository statuses;
    private final EpdRequestRepository requests;
    private final ElectronicDocumentTypeRepository documentTypes;
    private final EpdQueryStatusRepository queryStatuses;
    private final JourneyEntryMapper mapper;
    private final JourneyEntryValidator validator;
    private final JourneyEntryPayloadValidator payloadValidator;
    private final AccountingConfigClient configClient;
    private final PersistenceExceptionTranslator translator;
    private final TransactionTemplate transaction;
    private final Clock clock;

    @Override
    public GetJourneyEntryResponse getJourneyEntries(RequestHeaders headers, LocalDate dateFrom, LocalDate dateTo, String sapStatus, String documentType,
            String series, String correlative) {
        final String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> {
            validator.list(dateFrom, dateTo, documentType, series, correlative);
            return Boolean.TRUE;
        });
        return ejecutarActividad(menTran, ConstanApi.ACT8_CONSULTAR_ASIENTOS, () -> accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT8_CONSULTAR_ASIENTOS,
                ConstanApi.LOG_ERROR_DATOS_ACT8_CONSULTAR_ASIENTOS, () -> {
                    final Map<Long, JournalEntryStatusEntity> catalog = catalog();
                    Long statusId = null;
                    if (sapStatus != null && !sapStatus.isBlank()) {
                        statusId = statusIdOf(catalog, sapStatus);
                    }
                    if (documentType != null && documentTypes.findFirstBySunatDocumentTypeCode(documentType).isEmpty()) {
                        throw ServiceOperationException.badRequest(INVALID_FILTER);
                    }
                    final LocalDateTime from = dateFrom == null ? null : dateFrom.atStartOfDay();
                    final LocalDateTime until = dateTo == null ? null : dateTo.plusDays(1).atStartOfDay();
                    final List<JournalEntryEntity> found = entries.findAll(JournalEntrySpecifications.filter(from, until, statusId,
                            referencePattern(documentType, series, correlative)));
                    if (found.isEmpty()) {
                        throw notFound(menTran, ConstanApi.ACT8_CONSULTAR_ASIENTOS, ENTRY_NOT_FOUND);
                    }
                    return mapper.list(found, catalog);
                }));
    }

    @Override
    public CreateJourneyEntryResponse createJourneyEntry(RequestHeaders headers, ForwardedHeaders forwarded, CreateJourneyEntryRequest request) {
        final String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> {
            validator.create(request);
            return Boolean.TRUE;
        });
        final List<ConfigurationData> configs = ejecutarActividad(menTran, ConstanApi.ACT2_OBTENER_CONFIGURACION_CONTABLE, () -> configClient.findConfigurations(forwarded));
        final JsonNode payload = ejecutarActividad(menTran, ConstanApi.ACT3_VALIDAR_PAYLOAD_SAP, () -> payloadValidator.validate(request.getPayloadSAP(), configs));
        final Optional<CreateJourneyEntryResponse> duplicate = ejecutarActividad(menTran, ConstanApi.ACT4_VALIDAR_IDEMPOTENCIA, () -> accederDatos(menTran,
                ConstanApi.LOG_TIMEOUT_ACT4_VALIDAR_IDEMPOTENCIA, ConstanApi.LOG_ERROR_DATOS_ACT4_VALIDAR_IDEMPOTENCIA,
                () -> entries.findByRequestReference(request.getIdTranssacion()).map(entry -> mapper.duplicate(entry, statusValue(entry)))));
        if (duplicate.isPresent()) {
            return duplicate.get();
        }
        final JourneyEntryPayloadValidator.CpeReference reference = ejecutarActividad(menTran, ConstanApi.ACT5_EXTRAER_REFERENCIA_DEL_CPE, () -> payloadValidator.reference(payload));
        final Long receivedId = ejecutarActividad(menTran, ConstanApi.ACT6_CONSULTAR_CPE, () -> accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT6_CONSULTAR_CPE,
                ConstanApi.LOG_ERROR_DATOS_ACT6_CONSULTAR_CPE, () -> receivedStatusForAcceptedCpe(menTran, reference)));
        return ejecutarActividad(menTran, ConstanApi.ACT7_REGISTRAR_ASIENTO_Y_SNAPSHOT, () -> accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT7_REGISTRAR_ASIENTO_Y_SNAPSHOT,
                ConstanApi.LOG_ERROR_DATOS_ACT7_REGISTRAR_ASIENTO_Y_SNAPSHOT, () -> transaction.execute(tx -> {
                    final LocalDateTime now = LocalDateTime.now(clock);
                    final JournalEntryEntity saved = entries.save(mapper.newEntry(request, reference.nroReferencia(), payload, receivedId, headers.userId(), now));
                    history.save(mapper.snapshot(saved, now, headers.userId()));
                    return mapper.accepted(saved, JourneyEntryMapper.RECEIVED);
                })));
    }

    @Override
    public GetJourneyEntryTraceabilityResponse getTraceability(RequestHeaders headers, String journalEntryId) {
        final String menTran = prefix(headers);
        final Long id = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validator.id(journalEntryId));
        return ejecutarActividad(menTran, ConstanApi.ACT10_CONSULTAR_TRAZABILIDAD, () -> accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT10_CONSULTAR_TRAZABILIDAD,
                ConstanApi.LOG_ERROR_DATOS_ACT10_CONSULTAR_TRAZABILIDAD, () -> {
                    final JournalEntryEntity entry = entries.findById(id).orElseThrow(() -> notFound(menTran, ConstanApi.ACT10_CONSULTAR_TRAZABILIDAD, ENTRY_NOT_FOUND));
                    return mapper.traceability(entry, history.findByJournalEntryIdOrderBySnapshotDateAscIdAsc(id), catalog());
                }));
    }

    @Override
    public JourneyEntryBasicResponse resend(RequestHeaders headers, String journalEntryId) {
        final String menTran = prefix(headers);
        final Long id = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validator.id(journalEntryId));
        ejecutarActividad(menTran, ConstanApi.ACT11_REENVIAR_ASIENTO, () -> accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT11_REENVIAR_ASIENTO,
                ConstanApi.LOG_ERROR_DATOS_ACT11_REENVIAR_ASIENTO, () -> transaction.execute(tx -> {
                    final JournalEntryStatusEntity notRetryable = statusNamed(menTran, JourneyEntryMapper.NOT_RETRYABLE);
                    final JournalEntryStatusEntity received = statusNamed(menTran, JourneyEntryMapper.RECEIVED);
                    final JournalEntryEntity entry = entries.findById(id).orElseThrow(() -> notFound(menTran, ConstanApi.ACT11_REENVIAR_ASIENTO, ENTRY_NOT_FOUND));
                    if (!notRetryable.getId().equals(entry.getJournalEntryStatusId())) {
                        throw conflict(menTran);
                    }
                    final LocalDateTime now = LocalDateTime.now(clock);
                    if (entries.moveStatus(id, notRetryable.getId(), received.getId(), headers.userId(), now) != 1) {
                        throw conflict(menTran);
                    }
                    final JournalEntryHistEntity snapshot = mapper.snapshot(entry, now, headers.userId());
                    snapshot.setJournalEntryStatusId(received.getId());
                    snapshot.setLastModifiedUser(headers.userId());
                    snapshot.setLastModifiedDate(now);
                    history.save(snapshot);
                    return Boolean.TRUE;
                })));
        return mapper.basic();
    }

    @Override
    public JourneyEntryBasicResponse updateResult(RequestHeaders headers, String id, UpdateJourneyEntryResultRequest request) {
        final String menTran = prefix(headers);
        final Long entryId = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> {
            final Long parsed = validator.id(id);
            validator.update(request);
            return parsed;
        });
        ejecutarActividad(menTran, ConstanApi.ACT12_ACTUALIZAR_RESULTADO, () -> accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT12_ACTUALIZAR_RESULTADO,
                ConstanApi.LOG_ERROR_DATOS_ACT12_ACTUALIZAR_RESULTADO, () -> transaction.execute(tx -> {
                    final JournalEntryEntity entry = entries.findById(entryId).orElseThrow(() -> notFound(menTran, ConstanApi.ACT12_ACTUALIZAR_RESULTADO, ENTRY_NOT_FOUND));
                    if (!statuses.existsById(request.getJournalEntryStatusId())) {
                        throw ServiceOperationException.badRequest(INVALID_FILTER);
                    }
                    final LocalDateTime now = LocalDateTime.now(clock);
                    final LocalDateTime attemptStart = request.getAttemptStartedAt().atZoneSameInstant(clock.getZone()).toLocalDateTime();
                    mapper.applyResult(entry, request, attemptStart, headers.userId(), now);
                    final JournalEntryEntity saved = entries.save(entry);
                    history.save(mapper.snapshot(saved, now, headers.userId()));
                    return Boolean.TRUE;
                })));
        return mapper.basic();
    }

    @Override
    public GetJourneyEntryByIdResponse getById(RequestHeaders headers, String id) {
        final String menTran = prefix(headers);
        final Long entryId = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validator.id(id));
        return ejecutarActividad(menTran, ConstanApi.ACT9_CONSULTAR_ASIENTO_POR_ID, () -> accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT9_CONSULTAR_ASIENTO_POR_ID,
                ConstanApi.LOG_ERROR_DATOS_ACT9_CONSULTAR_ASIENTO_POR_ID, () -> {
                    final JournalEntryEntity entry = entries.findById(entryId).orElseThrow(() -> notFound(menTran, ConstanApi.ACT9_CONSULTAR_ASIENTO_POR_ID, ENTRY_NOT_FOUND));
                    return mapper.byId(entry, statusOf(entry.getJournalEntryStatusId()).orElse(null));
                }));
    }

    private Long receivedStatusForAcceptedCpe(String menTran, JourneyEntryPayloadValidator.CpeReference reference) {
        final ElectronicDocumentTypeEntity type = documentTypes.findFirstBySunatDocumentTypeCode(reference.documentType())
                .orElseThrow(() -> notFound(menTran, ConstanApi.ACT6_CONSULTAR_CPE, ENTRY_NOT_FOUND));
        final List<EpdRequestEntity> found = requests.findBySeriesAndCorrelativeAndEpdTypeId(reference.series(), reference.correlative(), type.getId());
        if (found.isEmpty()) {
            throw notFound(menTran, ConstanApi.ACT6_CONSULTAR_CPE, ENTRY_NOT_FOUND);
        }
        if (found.size() > 1) {
            throw conflict(menTran);
        }
        final Long statusId = found.get(0).getEpdQueryStatusId();
        final String cpeStatus = statusId == null ? "" : queryStatuses.findById(statusId).map(EpdQueryStatusEntity::getValue).orElse("");
        if (!ACCEPTED_CPE.contains(cpeStatus)) {
            throw new ServiceOperationException(HttpStatus.UNPROCESSABLE_ENTITY, CPE_NOT_ACCEPTED);
        }
        return statuses.findFirstByValueAndStatus(JourneyEntryMapper.RECEIVED, ACTIVE)
                .orElseThrow(() -> new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, STATUS_MISSING)).getId();
    }

    private String referencePattern(String documentType, String series, String correlative) {
        if (documentType == null && series == null && correlative == null) {
            return null;
        }
        return (documentType == null ? WILDCARD : documentType) + SEPARATOR + (series == null ? WILDCARD : series) + SEPARATOR
                + (correlative == null ? WILDCARD : correlative);
    }

    private Long statusIdOf(Map<Long, JournalEntryStatusEntity> catalog, String value) {
        for (JournalEntryStatusEntity status : catalog.values()) {
            if (value.equals(status.getValue())) {
                return status.getId();
            }
        }
        throw ServiceOperationException.badRequest(INVALID_FILTER);
    }

    private Map<Long, JournalEntryStatusEntity> catalog() {
        final Map<Long, JournalEntryStatusEntity> result = new HashMap<>();
        for (JournalEntryStatusEntity status : statuses.findAll()) {
            result.put(status.getId(), status);
        }
        return result;
    }

    private Optional<JournalEntryStatusEntity> statusOf(Long id) {
        return id == null ? Optional.empty() : statuses.findById(id);
    }

    private String statusValue(JournalEntryEntity entry) {
        return statusOf(entry.getJournalEntryStatusId()).map(JournalEntryStatusEntity::getValue).orElse(JourneyEntryMapper.RECEIVED);
    }

    private JournalEntryStatusEntity statusNamed(String menTran, String value) {
        return statuses.findFirstByValue(value).orElseThrow(() -> notFound(menTran, ConstanApi.ACT11_REENVIAR_ASIENTO, ENTRY_NOT_FOUND));
    }

    private ServiceOperationException conflict(String menTran) {
        log.error(ERROR_BUSINESS_PATTERN, menTran, "CONFLICTO", HttpStatus.CONFLICT.value(), CONFLICT_DETAIL);
        return new ServiceOperationException(HttpStatus.CONFLICT, CONFLICT_DETAIL);
    }

    private ServiceOperationException notFound(String menTran, String actividad, String detail) {
        log.error(ERROR_BUSINESS_PATTERN, menTran, actividad, HttpStatus.NOT_FOUND.value(), detail);
        return new ServiceOperationException(HttpStatus.NOT_FOUND, detail);
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

    private String prefix(RequestHeaders headers) {
        String tx = headers != null ? headers.transactionId() : null;
        return tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
    }
}'''

BASE = '/api/v1/dom-journeyEntry'
CODES_GET = ('400', '404', '500', '503', '504')
CODES_PATCH = ('400', '404', '409', '500', '503', '504')


def responses(success, resp, codes):
    rows = [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS.get(c, "OK")}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = {resp}.class)))'
            for c in success]
    rows += [f'      @ApiResponse(responseCode = "{c}", description = "{dj.REASONS[c]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
             for c in codes]
    return ',\n'.join(rows)


def api_op(name, summary, mapping, resp, params, codes, success=('200',)):
    out = ['    /**', f'     * {summary}', '     *']
    out += [f'     * @param {n} parametro {n}' for n, _ in params]
    out += [f'     * @param {c} {d}' for _, c, d in dj.HEADERS]
    out += [f'     * @return respuesta HTTP con el modelo {resp} definido en el contrato', '     */', f'    {mapping}', f'    @Operation(summary = "{summary}")', '    @ApiResponses({',
            responses(success, resp, codes), '    })', f'    ResponseEntity<{resp}> {name}(']
    args = [f'            {d}' for _, d in params] + [f'            @RequestHeader(name = "{h}", required = true) String {c}' for h, c, _ in dj.HEADERS]
    return '\n'.join(out + [',\n'.join(args) + ');'])


PATH_ID = ('id', '@PathVariable("id") String id')
PATH_JOURNAL = ('journalEntryId', '@PathVariable("journalEntryId") String journalEntryId')
QUERY = [('dateFrom', '@RequestParam(name = "dateFrom", required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate dateFrom'),
         ('dateTo', '@RequestParam(name = "dateTo", required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate dateTo'),
         ('sapStatus', '@RequestParam(name = "sapStatus", required = false) String sapStatus'),
         ('documentType', '@RequestParam(name = "documentType", required = false) String documentType'),
         ('series', '@RequestParam(name = "series", required = false) String series'),
         ('correlative', '@RequestParam(name = "correlative", required = false) String correlative')]


def api():
    ops = [
        api_op('getJourneyEntry', 'Consulta los asientos contables.', f'@GetMapping(path = "{BASE}", produces = {{"application/json"}})', 'GetJourneyEntryResponse', QUERY, CODES_GET),
        api_op('createJourneyEntry', 'Registra un asiento contable de forma asincrona.', f'@PostMapping(path = "{BASE}", consumes = {{"application/json"}}, produces = {{"application/json"}})',
               'CreateJourneyEntryResponse', [('request', '@RequestBody CreateJourneyEntryRequest request')], ('400', '404', '409', '422', '500', '503', '504'), ('202', '200')),
        api_op('getJourneyEntryTraceability', 'Consulta la trazabilidad de un asiento contable.', f'@GetMapping(path = "{BASE}/{{journalEntryId}}/traceability", produces = {{"application/json"}})',
               'GetJourneyEntryTraceabilityResponse', [PATH_JOURNAL], CODES_GET),
        api_op('resendJourneyEntry', 'Habilita el reenvio de un asiento contable no reintentable.', f'@PatchMapping(path = "{BASE}/{{journalEntryId}}/resend", produces = {{"application/json"}})',
               'JourneyEntryBasicResponse', [PATH_JOURNAL], CODES_PATCH),
        api_op('updateJourneyEntryResult', 'Actualiza el resultado del envio de un asiento contable.', f'@PatchMapping(path = "{BASE}/{{id}}", consumes = {{"application/json"}}, produces = {{"application/json"}})',
               'JourneyEntryBasicResponse', [PATH_ID, ('request', '@RequestBody UpdateJourneyEntryResultRequest request')], CODES_PATCH),
        api_op('getJourneyEntryId', 'Consulta un asiento contable por identificador.', f'@GetMapping(path = "{BASE}/{{id}}", produces = {{"application/json"}})',
               'GetJourneyEntryByIdResponse', [PATH_ID], CODES_GET),
    ]
    return '/** Define el contrato de los endpoints REST del asiento contable (contrato OpenAPI). */\npublic interface JourneyEntryApi {\n' + '\n\n'.join(ops) + '\n}'


def controller():
    hdr = [f'            String {c}' for _, c, _ in dj.HEADERS]
    fwd = 'new ForwardedHeaders(traceparent, xAppId, xChannel, xClientVersionId, xCorrelationId, xRequestId, xUserId)'

    def method(name, resp, params, call, ret='ResponseEntity.ok(%s)'):
        args = [f'            {p}' for p in params] + hdr
        return '\n'.join(['    @Override', f'    public ResponseEntity<{resp}> {name}(', ',\n'.join(args) + ') {', f'        log.info("{name} - transactionId: {{}}", xCorrelationId);',
                          '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);', f'        return {ret % call};', '    }'])
    body = [
        method('getJourneyEntry', 'GetJourneyEntryResponse', ['LocalDate dateFrom', 'LocalDate dateTo', 'String sapStatus', 'String documentType', 'String series', 'String correlative'],
               'service.getJourneyEntries(headers, dateFrom, dateTo, sapStatus, documentType, series, correlative)'),
        '\n'.join(['    @Override', '    public ResponseEntity<CreateJourneyEntryResponse> createJourneyEntry(', ',\n'.join(['            CreateJourneyEntryRequest request'] + hdr) + ') {',
                   '        log.info("createJourneyEntry - transactionId: {}", xCorrelationId);', '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);',
                   f'        CreateJourneyEntryResponse response = service.createJourneyEntry(headers, {fwd}, request);', '        return ResponseEntity.status(response.getCode()).body(response);', '    }']),
        method('getJourneyEntryTraceability', 'GetJourneyEntryTraceabilityResponse', ['String journalEntryId'], 'service.getTraceability(headers, journalEntryId)'),
        method('resendJourneyEntry', 'JourneyEntryBasicResponse', ['String journalEntryId'], 'service.resend(headers, journalEntryId)'),
        method('updateJourneyEntryResult', 'JourneyEntryBasicResponse', ['String id', 'UpdateJourneyEntryResultRequest request'], 'service.updateResult(headers, id, request)'),
        method('getJourneyEntryId', 'GetJourneyEntryByIdResponse', ['String id'], 'service.getById(headers, id)'),
    ]
    return '\n'.join(['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class JourneyEntryController implements JourneyEntryApi {',
                      '    private final JourneyEntryService service;', '', '\n\n'.join(body), '}'])


MESSAGES = [('/traceability', 'PROCESGETTRACE_JOURNEYENTRY_SERVICE_ERROR'), ('/resend', 'PROCESPATCH_JOURNEYENTRY_SERVICE_ERROR')]


def handler():
    text = dj.HANDLER
    text = re.sub(r'    private String operationMessage\(.*?\n    }\n\n    private String method',
                  '    private String operationMessage(String method, String uri, HttpStatus status) {\n'
                  '        if (uri.endsWith("/traceability")) {\n            return "PROCESGETTRACE_JOURNEYENTRY_SERVICE_ERROR";\n        }\n'
                  '        if (uri.endsWith("/resend")) {\n            return "PROCESPATCH_JOURNEYENTRY_SERVICE_ERROR";\n        }\n'
                  '        boolean collection = uri.endsWith("/dom-journeyEntry");\n'
                  '        if ("POST".equals(method)) {\n            return "PROCESPOST_JOURNEYENTRY_SERVICE_ERROR";\n        }\n'
                  '        if ("PATCH".equals(method)) {\n            return "PROCESPATCHID_JOURNEYENTRY_SERVICE_ERROR";\n        }\n'
                  '        return collection ? "PROCESGET_JOURNEYENTRY_SERVICE_ERROR" : "PROCESGETID_JOURNEYENTRY_SERVICE_ERROR";\n    }\n\n    private String method', text, flags=re.S)
    old = 'Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.CONFLICT, HttpStatus.INTERNAL_SERVER_ERROR,'
    assert old in text
    text = text.replace(old, 'Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.NOT_FOUND, HttpStatus.CONFLICT,\n            HttpStatus.UNPROCESSABLE_ENTITY, HttpStatus.INTERNAL_SERVER_ERROR,')
    texts = {'BAD_REQUEST': ('MissingParameters', 'IDF1', 'Par\u00e1metros, headers o campos requeridos inv\u00e1lidos.'),
             'NOT_FOUND': ('ParameterValueNotFound', 'IDF2', 'No se encontr\u00f3 el recurso solicitado.'),
             'CONFLICT': ('Conflict', 'IDF3', 'Referencia duplicada o conflicto concurrente.'),
             'INTERNAL_SERVER_ERROR': ('InternalError', 'IDT3', 'Error interno al procesar la transacci\u00f3n: [ERROR_DETAIL].'),
             'SERVICE_UNAVAILABLE': ('ServiceUnavailable', 'IDT2', 'Base de datos o publicaci\u00f3n as\u00edncrona no disponible.'),
             'GATEWAY_TIMEOUT': ('TimeoutException', 'IDT1', 'Tiempo de espera agotado al procesar la solicitud.')}
    for status, (kind, code, detail) in texts.items():
        pattern = rf'case {status} -> describe\(error, "[^"]*", "[^"]*", "[^"]*"\);'
        assert re.search(pattern, text), status
        text = re.sub(pattern, lambda m, s=status, k=kind, c=code, d=detail: f'case {s} -> describe(error, "{k}", "{"IDF5" if s == "CONFLICT" else c}", "{d}");', text)
    default = '            default -> error.setDetail(status.getReasonPhrase());'
    assert default in text
    return text.replace(default, '            case UNPROCESSABLE_ENTITY -> describe(error, "UnprocessableEntity", "IDF6", "El CPE no cumple las condiciones requeridas o no existe configuraci\u00f3n coincidente.");\n' + default)


def build_main(pkg):
    files = {}

    def put(suffix, name, body):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body)
    for cls, (table, fields) in jj.ENTITIES.items():
        body = dj.entity(cls, table, fields)
        if cls in jj.SEQUENCES:
            gen, seq = jj.SEQUENCES[cls]
            body = body.replace('    @GeneratedValue(strategy = GenerationType.IDENTITY)',
                                f'    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "{gen}")\n    @SequenceGenerator(name = "{gen}", sequenceName = "{seq}", allocationSize = 1)')
        else:
            body = body.replace('    @GeneratedValue(strategy = GenerationType.IDENTITY)\n', '')
        put('model', cls, body)
    put('dto.request', 'RequestHeaders', dj.REQUEST_HEADERS)
    for cls, fields in jj.REQUEST_DTOS.items():
        put('dto.request', cls, dj.dto(cls, fields))
    for cls, fields in jj.DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields, non_null=False))
    for resp, data in jj.RESPONSES.items():
        put('dto.response', resp, dj.envelope(resp, data))
    put('dto.response', 'JourneyEntryBasicResponse', jj.BASIC_RESPONSE)
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    for cls, fields in jj.CLIENT_DTOS.items():
        put('client.dto', cls, dj.dto(cls, fields))
    put('client.dto', 'ConfigurationResponse', dj.envelope('ConfigurationResponse', 'List<ConfigurationData>'))
    put('client.dto', 'ForwardedHeaders', jj.FORWARDED_HEADERS)
    put('client', 'AccountingConfigClient', jj.CLIENT_IF)
    put('client', 'AccountingConfigClientImpl', jj.CLIENT_IMPL)
    put('configuration', 'AccountingConfigClientConfig', jj.CLIENT_CONFIG)
    put('configuration', 'TransactionConfig', jj.TRANSACTION_CONFIG)
    put('configuration', 'ClockConfig', dj.CLOCK_CONFIG)
    put('dto.mapper', 'JourneyEntryMapper', jj.MAPPER)
    put('exception', 'ServiceOperationException', dj.SERVICE_OPERATION_EXCEPTION)
    translator = dj.finalize(pkg, 'exception', dj.TRANSLATOR).replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + dj.TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', handler())
    for cls, body in jj.REPOS.items():
        put('repository', cls, body)
    put('service', 'JourneyEntryService', jj.SERVICE_IF)
    put('service.impl', 'JourneyEntryServiceImpl', SERVICE_IMPL)
    put('validation', 'JourneyEntryValidator', jj.VALIDATOR)
    put('validation', 'JourneyEntryPayloadValidator', jj.PAYLOAD_VALIDATOR)
    put('controller', 'JourneyEntryApi', api())
    put('controller.impl', 'JourneyEntryController', controller())
    return files


ORIGINAL_CONSTANTS = dj.activity_constants


def activity_constants():
    saved = dj.ACTIVITIES
    dj.ACTIVITIES = [('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False),
                     ('ACT2_OBTENER_CONFIGURACION_CONTABLE', 'OBTENER_CONFIGURACION_CONTABLE', False),
                     ('ACT3_VALIDAR_PAYLOAD_SAP', 'VALIDAR_PAYLOAD_SAP', False),
                     ('ACT4_VALIDAR_IDEMPOTENCIA', 'VALIDAR_IDEMPOTENCIA', True),
                     ('ACT5_EXTRAER_REFERENCIA_DEL_CPE', 'EXTRAER_REFERENCIA_DEL_CPE', False),
                     ('ACT6_CONSULTAR_CPE', 'CONSULTAR_CPE', True),
                     ('ACT7_REGISTRAR_ASIENTO_Y_SNAPSHOT', 'REGISTRAR_ASIENTO_Y_SNAPSHOT', True),
                     ('ACT8_CONSULTAR_ASIENTOS', 'CONSULTAR_ASIENTOS', True),
                     ('ACT9_CONSULTAR_ASIENTO_POR_ID', 'CONSULTAR_ASIENTO_POR_ID', True),
                     ('ACT10_CONSULTAR_TRAZABILIDAD', 'CONSULTAR_TRAZABILIDAD', True),
                     ('ACT11_REENVIAR_ASIENTO', 'REENVIAR_ASIENTO', True),
                     ('ACT12_ACTUALIZAR_RESULTADO', 'ACTUALIZAR_RESULTADO', True)]
    try:
        return ORIGINAL_CONSTANTS()
    finally:
        dj.ACTIVITIES = saved


def build_tests(pkg):
    import dom_cpe_request_tests as dt
    import dom_journey_entry_tests as jt
    files = {}
    for name, (suffix, body) in jt.TESTS.items():
        if name.endswith('ContractTest'):
            statics = list(dt.MVC_STATICS)
        elif name.endswith('ClientImplTest'):
            statics = list(dt.ASSERT) + jt.MOCK_REST
        else:
            statics = dt.ASSERT
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    return files


ASSUMPTIONS = [
    ('A-01', 'Base package com.claro.dom.journeyentry and application class DomJourneyEntryApplication are technical choices; no source defines them.'),
    ('A-02', 'Swagger governs (approved delegated decision): the listing returns data.accountingEntry[], resend and update return only code/message, and 401/403 are not implemented although Sparx and the POST contract mention them.'),
    ('A-03', 'GET list with no rows returns 404 (Swagger declares it); Sparx says 200 with an empty list. Unresolved Swagger-vs-Sparx point.'),
    ('A-04', 'Sparx filters on EPDREQUEST V_SERIE/V_CORRELATIVO/V_FECHAEMISION, which are not in the EPDREQUEST definition and JOURNALENTRY has no link column to EPDREQUEST. The CPE is therefore linked through NROREFERENCE (documentType-series-correlative); date filters apply to JOURNALENTRY.CREATIONDATE (dateTo inclusive); the 30-day range rule is not applied because Swagger does not declare it.'),
    ('A-05', 'The Sparx asynchronous event publication after registration has no specified mechanism, so it is not implemented. The POST registers JOURNALENTRY and JOURNALENTRYHIST in one local transaction and returns 202 RECIBIDO.'),
    ('A-06', 'Accounting configuration validation follows the Sparx text. For scenarioContext rules the first segment is read as the expected value, the second as M/O and the third as the type. The last configuration read successfully is cached in memory and used when the configuration service is unavailable.'),
    ('A-07', 'PATCH /{id} is thin in Sparx. Assumed semantics: status, attempt number, last attempt date (attemptStartedAt, converted with the injectable Clock zone; first attempt date set once), optional responses and SAP numbers are updated and a history snapshot is written. stage and expectedStatus are required but neither persisted nor compared; no 409 is raised because no concurrency rule is defined.'),
    ('A-08', 'Resend uses a conditional update (status must still be NO_REINTENTABLE) and writes a history snapshot with status RECIBIDO; a lost race or a different status returns 409.'),
    ('A-09', 'Path identifiers are parsed as positive integers in the service; a non numeric identifier returns 400. Audit dates come from an injectable Clock, never SYSDATE.'),
    ('A-10', 'The GET by id reads JOURNALENTRY (Sparx act 2 cites EPDREQUEST tables by copy-paste but maps JOURNALENTRY columns). Table columns absent from the Sparx definitions are not mapped.'),
]


def main(argv=None):
    sys.modules['dom_invoice_java'] = types.SimpleNamespace()
    shim = types.SimpleNamespace(build_main=build_main, build_tests=build_tests, activity_constants=activity_constants)
    dm.PACKAGE, dm.APPLICATION_CLASS, dm.ASSUMPTIONS, dm.VERSION = PACKAGE, 'DomJourneyEntryApplication', ASSUMPTIONS, 'dom-journey-entry-materializer-1'
    dm.PARAMETERS = {**dm.PARAMETERS, 'base_package': PACKAGE, 'base_package_path': PACKAGE.replace('.', '/'), 'group_id': PACKAGE, 'application_class': 'DomJourneyEntryApplication'}
    dm.GENERATOR_FILES = ['dom_cpe_request_java.py', 'dom_cpe_request_tests.py', 'dom_cpe_request_materializer.py', 'dom_journey_entry_java.py',
                          'dom_journey_entry_tests.py', 'dom_journey_entry_materializer.py']
    dm.dj, dm.dt = shim, shim
    return dm.main(argv) if argv is not None else dm.main()


if __name__ == '__main__':
    sys.exit(main())
