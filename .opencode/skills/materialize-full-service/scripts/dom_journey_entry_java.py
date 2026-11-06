"""Java templates of the dom-journeyEntry service (entities, DTOs, repositories, validators, clients and mapper)."""
import dom_cpe_request_java as dj

PACKAGE = 'com.claro.dom.journeyentry'
for _name, _fqcn in {
        'SequenceGenerator': 'jakarta.persistence.SequenceGenerator', 'Modifying': 'org.springframework.data.jpa.repository.Modifying',
        'JpaSpecificationExecutor': 'org.springframework.data.jpa.repository.JpaSpecificationExecutor',
        'Specification': 'org.springframework.data.jpa.domain.Specification', 'Predicate': 'jakarta.persistence.criteria.Predicate',
        'LocalDate': 'java.time.LocalDate', 'OffsetDateTime': 'java.time.OffsetDateTime', 'DateTimeFormat': 'org.springframework.format.annotation.DateTimeFormat',
        'JsonNode': 'com.fasterxml.jackson.databind.JsonNode', 'ArgumentCaptor': 'org.mockito.ArgumentCaptor', 'InOrder': 'org.mockito.InOrder',
        'MockHttpServletRequestBuilder': 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder',
        'RestClient': 'org.springframework.web.client.RestClient', 'SimpleClientHttpRequestFactory': 'org.springframework.http.client.SimpleClientHttpRequestFactory',
        'ResourceAccessException': 'org.springframework.web.client.ResourceAccessException', 'RestClientResponseException': 'org.springframework.web.client.RestClientResponseException',
        'SocketTimeoutException': 'java.net.SocketTimeoutException', 'IOException': 'java.io.IOException', 'HttpMethod': 'org.springframework.http.HttpMethod',
        'MockRestServiceServer': 'org.springframework.test.web.client.MockRestServiceServer', 'AtomicReference': 'java.util.concurrent.atomic.AtomicReference',
        'HashMap': 'java.util.HashMap', 'Objects': 'java.util.Objects', 'HttpHeaders': 'org.springframework.http.HttpHeaders',
        'SQLException': 'java.sql.SQLException', 'Executable': 'org.junit.jupiter.api.function.Executable', 'DataIntegrityViolationException': 'org.springframework.dao.DataIntegrityViolationException',
        'LinkedHashMap': 'java.util.LinkedHashMap', 'ArrayList': 'java.util.ArrayList', 'Arrays': 'java.util.Arrays', 'ZoneOffset': 'java.time.ZoneOffset'}.items():
    dj.EXTERNAL.setdefault(_name, _fqcn)
dj.REASONS.setdefault('422', 'Unprocessable Entity')

NRO = 'NROREFERENCE'
ENTRY_FIELDS = [
    ('Long', 'id', 'ID', 'id'), ('String', 'requestReference', 'REQUESTREFERENCE', ''), ('String', 'nroReference', 'NROREFERENCE', ''),
    ('String', 'entryPayload', 'ENTRYPAYLOAD', 'lob'), ('String', 'firstRequest', 'FIRSTREQUEST', 'lob'), ('String', 'firstResponse', 'FIRSTRESPONSE', 'lob'),
    ('String', 'secondRequest', 'SECONDREQUEST', 'lob'), ('String', 'secondResponse', 'SECONDRESPONSE', 'lob'), ('String', 'orderNumber', 'ORDERNUMBER', ''),
    ('Integer', 'attemptNumber', 'ATTEMPTNUMBER', ''), ('Long', 'journalEntryStatusId', 'JOURNALENTRYSTATUSID', ''),
    ('LocalDateTime', 'firstSapAttemptDate', 'FIRSTSAPATTEMPTDATE', ''), ('LocalDateTime', 'lastSapAttemptDate', 'LASTSAPATTEMPTDATE', ''),
    ('String', 'sapOrderNumber', 'SAPORDERNUMBER', ''), ('String', 'sapDeliveryNumber', 'SAPDELIVERYNUMBER', ''), ('String', 'sapInvoiceNumber', 'SAPINVOICENUMBER', ''),
    ('String', 'sapAccountingDocumentNumber', 'SAPACCOUNTINGDOCUMENTNUMBER', ''),
    ('String', 'creationUser', 'CREATIONUSER', ''), ('LocalDateTime', 'creationDate', 'CREATIONDATE', ''),
    ('String', 'lastModifiedUser', 'LASTMODIFIEDUSER', ''), ('LocalDateTime', 'lastModifiedDate', 'LASTMODIFIEDDATE', '')]
HIST_FIELDS = ENTRY_FIELDS[:1] + [('Long', 'journalEntryId', 'JOURNALENTRYID', '')] + ENTRY_FIELDS[1:] + [('LocalDateTime', 'snapshotDate', 'SNAPSHOTDATE', '')]
ENTITIES = {
    'JournalEntryEntity': ('JOURNALENTRY', ENTRY_FIELDS),
    'JournalEntryHistEntity': ('JOURNALENTRYHIST', HIST_FIELDS),
    'JournalEntryStatusEntity': ('JOURNALENTRYSTATUS', [('Long', 'id', 'ID', 'id'), ('String', 'value', 'VALUE', ''), ('String', 'description', 'DESCRIPTION', ''), ('Integer', 'status', 'STATUS', '')]),
    'EpdRequestEntity': ('EPDREQUEST', [('Long', 'id', 'ID', 'id'), ('Long', 'epdTypeId', 'EPDTYPEID', ''), ('String', 'series', 'SERIES', ''),
                                        ('Long', 'correlative', 'CORRELATIVE', ''), ('Long', 'epdQueryStatusId', 'EPDQUERYSTATUSID', '')]),
    'ElectronicDocumentTypeEntity': ('ELECTRONICDOCUMENTTYPE', [('Long', 'id', 'ID', 'id'), ('String', 'sunatDocumentTypeCode', 'SUNATDOCUMENTTYPECODE', '')]),
    'EpdQueryStatusEntity': ('EPDQUERYSTATUS', [('Long', 'id', 'ID', 'id'), ('String', 'value', 'VALUE', '')]),
}
SEQUENCES = {'JournalEntryEntity': ('journalEntrySeq', 'FACEL.SEQ_JOURNALENTRY'), 'JournalEntryHistEntity': ('journalEntryHistSeq', 'FACEL.SEQ_JOURNALENTRYHIST')}

REQUEST_DTOS = {
    'CreateJourneyEntryRequest': [('String', 'idTranssacion'), ('String', 'payloadSAP')],
    'UpdateJourneyEntryResultRequest': [('String', 'stage'), ('String', 'expectedStatus'), ('Long', 'journalEntryStatusId'), ('Integer', 'attemptNumber'),
                                        ('OffsetDateTime', 'attemptStartedAt'), ('String', 'firstResponse'), ('String', 'sapOrderNumber'), ('String', 'sapDeliveryNumber'),
                                        ('String', 'sapInvoiceNumber'), ('String', 'secondResponse'), ('String', 'sapAccountingDocumentNumber')],
}
DTOS = {
    'AccountingEntryItem': [('Long', 'id'), ('String', 'journalEntryNumber'), ('String', 'orderNumber'), ('String', 'sapAccountingDocumentNumber'), ('LocalDateTime', 'sentToSapAt'),
                            ('String', 'documentType'), ('String', 'series'), ('String', 'correlative'), ('String', 'sapStatus'), ('Integer', 'canResend')],
    'GetJourneyEntryData': [('List<AccountingEntryItem>', 'accountingEntry')],
    'CreateJourneyEntryAcceptedData': [('Long', 'journalEntryId'), ('String', 'requestReference'), ('String', 'status')],
    'JourneyEntryHistoryItem': [('Long', 'id'), ('String', 'journalEntryNumber'), ('String', 'status'), ('String', 'statusDescription'), ('LocalDateTime', 'occurredAt'), ('String', 'user')],
    'GetJourneyEntryTraceabilityData': [('Long', 'journalEntryId'), ('String', 'journalEntryNumber'), ('String', 'currentStatus'), ('String', 'currentStatusDescription'),
                                        ('LocalDateTime', 'registeredAt'), ('List<JourneyEntryHistoryItem>', 'history')],
    'GetJourneyEntryByIdData': [('Long', 'journalEntryId'), ('String', 'requestreference'), ('String', 'nroReference'), ('String', 'orderNumber'), ('String', 'entryPayload'),
                                ('String', 'firstRequest'), ('String', 'firstResponse'), ('String', 'secondRequest'), ('String', 'secondResponse'), ('Integer', 'attemptNumber'),
                                ('LocalDateTime', 'firstSapAttemptDate'), ('LocalDateTime', 'lastSapAttemptDate'), ('String', 'sapAccountingDocumentNumber'),
                                ('String', 'sapOrderNumber'), ('String', 'sapDeliveryNumber'), ('String', 'sapInvoiceNumber'), ('String', 'journalEntryStatus'),
                                ('String', 'description'), ('Long', 'journalStatusId')],
}
RESPONSES = {'GetJourneyEntryResponse': 'GetJourneyEntryData', 'CreateJourneyEntryResponse': 'CreateJourneyEntryAcceptedData',
             'GetJourneyEntryTraceabilityResponse': 'GetJourneyEntryTraceabilityData', 'GetJourneyEntryByIdResponse': 'GetJourneyEntryByIdData'}
BASIC_RESPONSE = '@Data\npublic class JourneyEntryBasicResponse {\n    private Integer code;\n    private String message;\n}'
CLIENT_DTOS = {'ConfigurationData': [('Long', 'configId'), ('String', 'configKey'), ('String', 'configGroup'), ('String', 'description'), ('String', 'configValue')]}

REGISTRATIONS = [
    ('model', list(ENTITIES)), ('dto.request', list(REQUEST_DTOS)),
    ('dto.response', list(DTOS) + list(RESPONSES) + ['JourneyEntryBasicResponse', 'ErrorResponse']),
    ('dto.mapper', ['JourneyEntryMapper']),
    ('repository', ['JournalEntryRepository', 'JournalEntryHistRepository', 'JournalEntryStatusRepository', 'EpdRequestRepository',
                    'ElectronicDocumentTypeRepository', 'EpdQueryStatusRepository', 'JournalEntrySpecifications']),
    ('service', ['JourneyEntryService']), ('service.impl', ['JourneyEntryServiceImpl']),
    ('validation', ['JourneyEntryValidator', 'JourneyEntryPayloadValidator']),
    ('controller', ['JourneyEntryApi']), ('controller.impl', ['JourneyEntryController']),
    ('client', ['AccountingConfigClient', 'AccountingConfigClientImpl']), ('client.dto', ['ForwardedHeaders', 'ConfigurationData', 'ConfigurationResponse']),
    ('configuration', ['AccountingConfigClientConfig', 'TransactionConfig'])]
for _suffix, _names in REGISTRATIONS:
    dj.register(_suffix, *_names)

REPOS = {
    'JournalEntryRepository': '''@Repository
public interface JournalEntryRepository extends JpaRepository<JournalEntryEntity, Long>, JpaSpecificationExecutor<JournalEntryEntity> {
    Optional<JournalEntryEntity> findByRequestReference(String requestReference);

    @Modifying
    @Query("update JournalEntryEntity e set e.journalEntryStatusId = :to, e.lastModifiedUser = :user, e.lastModifiedDate = :now "
            + "where e.id = :id and e.journalEntryStatusId = :from")
    int moveStatus(@Param("id") Long id, @Param("from") Long from, @Param("to") Long to, @Param("user") String user, @Param("now") LocalDateTime now);
}''',
    'JournalEntryHistRepository': '''@Repository
public interface JournalEntryHistRepository extends JpaRepository<JournalEntryHistEntity, Long> {
    List<JournalEntryHistEntity> findByJournalEntryIdOrderBySnapshotDateAscIdAsc(Long journalEntryId);
}''',
    'JournalEntryStatusRepository': '''@Repository
public interface JournalEntryStatusRepository extends JpaRepository<JournalEntryStatusEntity, Long> {
    Optional<JournalEntryStatusEntity> findFirstByValue(String value);

    Optional<JournalEntryStatusEntity> findFirstByValueAndStatus(String value, Integer status);
}''',
    'EpdRequestRepository': '''@Repository
public interface EpdRequestRepository extends JpaRepository<EpdRequestEntity, Long> {
    List<EpdRequestEntity> findBySeriesAndCorrelativeAndEpdTypeId(String series, Long correlative, Long epdTypeId);
}''',
    'ElectronicDocumentTypeRepository': '''@Repository
public interface ElectronicDocumentTypeRepository extends JpaRepository<ElectronicDocumentTypeEntity, Long> {
    Optional<ElectronicDocumentTypeEntity> findFirstBySunatDocumentTypeCode(String sunatDocumentTypeCode);
}''',
    'EpdQueryStatusRepository': '''@Repository
public interface EpdQueryStatusRepository extends JpaRepository<EpdQueryStatusEntity, Long> {
}''',
    'JournalEntrySpecifications': '''/** Dynamic filters of the accounting entry listing. */
public final class JournalEntrySpecifications {
    private JournalEntrySpecifications() {
    }

    public static Specification<JournalEntryEntity> filter(LocalDateTime from, LocalDateTime toExclusive, Long statusId, String referencePattern) {
        return (root, query, builder) -> {
            List<Predicate> predicates = new ArrayList<>();
            if (from != null) {
                predicates.add(builder.greaterThanOrEqualTo(root.get("creationDate"), from));
            }
            if (toExclusive != null) {
                predicates.add(builder.lessThan(root.get("creationDate"), toExclusive));
            }
            if (statusId != null) {
                predicates.add(builder.equal(root.get("journalEntryStatusId"), statusId));
            }
            if (referencePattern != null) {
                predicates.add(builder.like(root.get("nroReference"), referencePattern));
            }
            query.orderBy(builder.desc(root.get("creationDate")), builder.desc(root.get("id")));
            return builder.and(predicates.toArray(new Predicate[0]));
        };
    }
}''',
}

SERVICE_IF = '''/** Casos de uso del asiento contable. */
public interface JourneyEntryService {
    GetJourneyEntryResponse getJourneyEntries(RequestHeaders headers, LocalDate dateFrom, LocalDate dateTo, String sapStatus, String documentType,
            String series, String correlative);

    CreateJourneyEntryResponse createJourneyEntry(RequestHeaders headers, ForwardedHeaders forwarded, CreateJourneyEntryRequest request);

    GetJourneyEntryTraceabilityResponse getTraceability(RequestHeaders headers, String journalEntryId);

    JourneyEntryBasicResponse resend(RequestHeaders headers, String journalEntryId);

    JourneyEntryBasicResponse updateResult(RequestHeaders headers, String id, UpdateJourneyEntryResultRequest request);

    GetJourneyEntryByIdResponse getById(RequestHeaders headers, String id);
}'''

VALIDATOR = '''/** Reglas declaradas en el contrato: identificadores, filtros y campos obligatorios. */
@Component
public class JourneyEntryValidator {
    private static final String INVALID_REQUEST = "Par\u00e1metros, headers o campos requeridos inv\u00e1lidos.";
    private static final String FILTER_PATTERN = "[A-Za-z0-9]+";

    public Long id(String raw) {
        try {
            long value = Long.parseLong(raw == null ? "" : raw.trim());
            if (value <= 0) {
                throw ServiceOperationException.badRequest(INVALID_REQUEST);
            }
            return value;
        } catch (NumberFormatException e) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
    }

    public void list(LocalDate dateFrom, LocalDate dateTo, String documentType, String series, String correlative) {
        if (dateFrom != null && dateTo != null && dateFrom.isAfter(dateTo)) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
        if ((series == null) != (correlative == null)) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
        for (String value : new String[] {documentType, series, correlative}) {
            if (value != null && !value.matches(FILTER_PATTERN)) {
                throw ServiceOperationException.badRequest(INVALID_REQUEST);
            }
        }
    }

    public void create(CreateJourneyEntryRequest request) {
        if (request == null || blank(request.getIdTranssacion()) || blank(request.getPayloadSAP())) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
    }

    public void update(UpdateJourneyEntryResultRequest request) {
        if (request == null || blank(request.getStage()) || blank(request.getExpectedStatus()) || request.getJournalEntryStatusId() == null
                || request.getAttemptNumber() == null || request.getAttemptNumber() < 0 || request.getAttemptStartedAt() == null) {
            throw ServiceOperationException.badRequest(INVALID_REQUEST);
        }
    }

    private boolean blank(String value) {
        return value == null || value.isBlank();
    }
}'''

PAYLOAD_VALIDATOR = '''/** Valida payloadSAP contra la configuracion contable seleccionada y extrae la referencia del CPE. */
@Component
@Slf4j
public class JourneyEntryPayloadValidator {
    public record CpeReference(String nroReferencia, String documentType, String series, Long correlative) {
    }

    private static final String SCENARIO = "scenarioContext";
    private static final String REQUESTS = "rfcRequests";
    private static final String RFC_GENERAL = "Z02OTCMF_GEN_FLUJO_COM";
    private static final String RFC_SALES = "Z02OTCMF_VENTAS_CONVER";
    private static final String DOCUMENT_TABLE = "TI_DOCUMENTO";
    private static final String REFERENCE_FIELD = "NRO_REFERENCIA";
    private static final String MANDATORY = "M";
    private static final String OPTIONAL = "O";
    private static final String SEPARATOR = "-";
    private static final String RULE_SEPARATOR = "[|]";
    private static final int SCENARIO_PARTS = 3;
    private static final int FIELD_PARTS = 2;
    private static final int REFERENCE_PARTS = 3;
    private static final List<String> TYPES = List.of("VARCHAR", "INTEGER", "DOUBLE");
    private static final List<String> CRITERIA = List.of("CANAL_VENTA", "TIPO_VENTA", "TIPO_DOCUMENTO", "TIPO_OPERACI\u00d3N", "SECTOR", "MOTIVO_PEDIDO", "CLASE_PEDIDO");
    private static final String INVALID_PAYLOAD = "payloadSAP no cumple la configuraci\u00f3n contable.";
    private static final String INVALID_CONFIG = "La configuraci\u00f3n contable no tiene una estructura v\u00e1lida.";
    private static final String NO_CONFIG = "No existe configuraci\u00f3n contable coincidente.";
    private static final String AMBIGUOUS = "Existe m\u00e1s de una configuraci\u00f3n contable coincidente.";
    private static final String REQUIRED_FIELD = "REQUIRED_FIELD";
    private static final String INVALID_TYPE = "INVALID_TYPE";
    private static final String INVALID_STRUCTURE = "INVALID_STRUCTURE";
    private static final String UNEXPECTED_FIELD = "UNEXPECTED_FIELD";
    private static final String INVALID_CARDINALITY = "INVALID_CARDINALITY";

    private final ObjectMapper mapper = new ObjectMapper();

    public JsonNode validate(String payloadSap, List<ConfigurationData> configs) {
        JsonNode payload = parse(payloadSap, true);
        Map<String, String> criteria = criteria(payload);
        JsonNode selected = select(criteria, configs);
        List<String> errors = new ArrayList<>();
        scenario(selected.path(SCENARIO), payload.path(SCENARIO), errors);
        requests(selected.path(REQUESTS), payload.path(REQUESTS), errors);
        if (!errors.isEmpty()) {
            log.warn("payloadSAP rechazado: {}", String.join("; ", errors));
            throw ServiceOperationException.badRequest(INVALID_PAYLOAD);
        }
        return payload;
    }

    public CpeReference reference(JsonNode payload) {
        JsonNode table = payload.path(REQUESTS).path(RFC_GENERAL).path(DOCUMENT_TABLE);
        JsonNode first = table.isArray() && table.size() > 0 ? table.get(0) : table;
        String reference = first.path(REFERENCE_FIELD).asText("").trim();
        String[] parts = reference.split(SEPARATOR);
        if (reference.isEmpty() || parts.length < REFERENCE_PARTS) {
            throw ServiceOperationException.badRequest(INVALID_PAYLOAD);
        }
        try {
            return new CpeReference(reference, parts[0], parts[1], Long.parseLong(parts[parts.length - 1]));
        } catch (NumberFormatException e) {
            throw ServiceOperationException.badRequest(INVALID_PAYLOAD);
        }
    }

    private JsonNode parse(String text, boolean fromRequest) {
        try {
            JsonNode node = mapper.readTree(text);
            if (node == null || !node.isObject()) {
                throw fromRequest ? ServiceOperationException.badRequest(INVALID_PAYLOAD) : invalidConfig();
            }
            return node;
        } catch (JsonProcessingException e) {
            throw fromRequest ? ServiceOperationException.badRequest(INVALID_PAYLOAD) : invalidConfig();
        }
    }

    private Map<String, String> criteria(JsonNode payload) {
        Map<String, String> result = new LinkedHashMap<>();
        for (String key : CRITERIA) {
            JsonNode value = payload.path(SCENARIO).get(key);
            if (value != null && !value.isNull()) {
                if (!value.isTextual() || value.asText().isBlank()) {
                    throw ServiceOperationException.badRequest(INVALID_PAYLOAD);
                }
                result.put(key, value.asText());
            }
        }
        if (result.isEmpty()) {
            throw ServiceOperationException.badRequest(INVALID_PAYLOAD);
        }
        return result;
    }

    private JsonNode select(Map<String, String> criteria, List<ConfigurationData> configs) {
        JsonNode best = null;
        int bestScore = -1;
        boolean tie = false;
        for (ConfigurationData config : configs) {
            JsonNode model = parse(config.getConfigValue() == null ? "" : config.getConfigValue(), false);
            int score = score(model.path(SCENARIO), criteria);
            if (score < 0) {
                continue;
            }
            if (score > bestScore) {
                best = model;
                bestScore = score;
                tie = false;
            } else if (score == bestScore) {
                tie = true;
            }
        }
        if (best == null) {
            throw new ServiceOperationException(HttpStatus.UNPROCESSABLE_ENTITY, NO_CONFIG);
        }
        if (tie) {
            throw new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, AMBIGUOUS);
        }
        model(best);
        return best;
    }

    private int score(JsonNode declared, Map<String, String> criteria) {
        int score = 0;
        for (Map.Entry<String, String> criterion : criteria.entrySet()) {
            JsonNode rule = declared.get(criterion.getKey());
            if (rule == null) {
                continue;
            }
            String[] parts = rule.asText().split(RULE_SEPARATOR, -1);
            if (!parts[0].equals(criterion.getValue())) {
                return -1;
            }
            score++;
        }
        return score;
    }

    private void model(JsonNode model) {
        JsonNode requests = model.path(REQUESTS);
        for (String rfc : List.of(RFC_GENERAL, RFC_SALES)) {
            JsonNode groups = requests.get(rfc);
            if (groups == null || !groups.isObject()) {
                throw invalidConfig();
            }
            for (String group : names(groups)) {
                JsonNode rule = groups.get(group);
                JsonNode min = rule.get("minItems");
                JsonNode max = rule.get("maxItems");
                JsonNode items = rule.get("items");
                if (min == null || !min.isIntegralNumber() || min.asInt() < 0 || items == null || !items.isObject() || items.isEmpty()) {
                    throw invalidConfig();
                }
                if (max != null && !max.isNull() && (!max.isIntegralNumber() || max.asInt() < min.asInt())) {
                    throw invalidConfig();
                }
                for (String field : names(items)) {
                    String[] parts = items.get(field).asText().split(RULE_SEPARATOR, -1);
                    if (parts.length != FIELD_PARTS || !(MANDATORY.equals(parts[0]) || OPTIONAL.equals(parts[0])) || !TYPES.contains(parts[1])) {
                        throw invalidConfig();
                    }
                }
            }
        }
        for (String key : names(model.path(SCENARIO))) {
            String[] parts = model.path(SCENARIO).get(key).asText().split(RULE_SEPARATOR, -1);
            if (parts.length != SCENARIO_PARTS || !(MANDATORY.equals(parts[1]) || OPTIONAL.equals(parts[1])) || !TYPES.contains(parts[2])) {
                throw invalidConfig();
            }
        }
    }

    private void scenario(JsonNode declared, JsonNode actual, List<String> errors) {
        for (String key : names(declared)) {
            String[] parts = declared.get(key).asText().split(RULE_SEPARATOR, -1);
            JsonNode value = actual.get(key);
            if (value == null || value.isNull()) {
                if (MANDATORY.equals(parts[1])) {
                    errors.add(SCENARIO + "." + key + " " + REQUIRED_FIELD);
                }
            } else if (!value.isTextual()) {
                errors.add(SCENARIO + "." + key + " " + INVALID_TYPE);
            } else if (!parts[0].equals(value.asText())) {
                errors.add(SCENARIO + "." + key + " " + INVALID_STRUCTURE);
            }
        }
    }

    private void requests(JsonNode declared, JsonNode actual, List<String> errors) {
        if (!actual.isObject()) {
            errors.add(REQUESTS + " " + REQUIRED_FIELD);
            return;
        }
        for (String rfc : names(actual)) {
            if (!declared.has(rfc)) {
                errors.add(REQUESTS + "." + rfc + " " + UNEXPECTED_FIELD);
            }
        }
        for (String rfc : names(declared)) {
            JsonNode groups = actual.get(rfc);
            if (groups == null || !groups.isObject()) {
                errors.add(REQUESTS + "." + rfc + " " + REQUIRED_FIELD);
            } else {
                groups(REQUESTS + "." + rfc, declared.get(rfc), groups, errors);
            }
        }
    }

    private void groups(String path, JsonNode declared, JsonNode actual, List<String> errors) {
        for (String group : names(actual)) {
            if (!declared.has(group)) {
                errors.add(path + "." + group + " " + UNEXPECTED_FIELD);
            }
        }
        for (String group : names(declared)) {
            JsonNode rule = declared.get(group);
            JsonNode rows = actual.get(group);
            String groupPath = path + "." + group;
            if (rows == null || !rows.isArray()) {
                errors.add(groupPath + " " + INVALID_STRUCTURE);
                continue;
            }
            JsonNode max = rule.get("maxItems");
            if (rows.size() < rule.get("minItems").asInt() || (max != null && !max.isNull() && rows.size() > max.asInt())) {
                errors.add(groupPath + " " + INVALID_CARDINALITY);
            }
            for (int index = 0; index < rows.size(); index++) {
                if (rows.get(index).isObject()) {
                    fields(groupPath + "[" + index + "]", rule.get("items"), rows.get(index), errors);
                } else {
                    errors.add(groupPath + "[" + index + "] " + INVALID_STRUCTURE);
                }
            }
        }
    }

    private void fields(String path, JsonNode declared, JsonNode row, List<String> errors) {
        for (String field : names(row)) {
            if (!declared.has(field)) {
                errors.add(path + "." + field + " " + UNEXPECTED_FIELD);
            }
        }
        for (String field : names(declared)) {
            String[] parts = declared.get(field).asText().split(RULE_SEPARATOR, -1);
            JsonNode value = row.get(field);
            if (value == null || value.isNull()) {
                if (MANDATORY.equals(parts[0])) {
                    errors.add(path + "." + field + " " + REQUIRED_FIELD);
                }
            } else if (!matches(parts[1], value)) {
                errors.add(path + "." + field + " " + INVALID_TYPE);
            }
        }
    }

    private boolean matches(String type, JsonNode value) {
        if ("VARCHAR".equals(type)) {
            return value.isTextual();
        }
        if ("INTEGER".equals(type)) {
            return value.isIntegralNumber();
        }
        return value.isNumber();
    }

    private List<String> names(JsonNode node) {
        List<String> result = new ArrayList<>();
        node.fieldNames().forEachRemaining(result::add);
        return result;
    }

    private ServiceOperationException invalidConfig() {
        return new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, INVALID_CONFIG);
    }
}'''

MAPPER = '''/** Mapeo explicito entre las filas del asiento contable y el contrato de la API. */
@Component
public class JourneyEntryMapper {
    public static final String RECEIVED = "RECIBIDO";
    public static final String NOT_RETRYABLE = "NO_REINTENTABLE";
    private static final String SUCCESS_MESSAGE = "Operaci\u00f3n exitosa";
    private static final String ACCEPTED_MESSAGE = "Solicitud recibida correctamente";
    private static final String DUPLICATE_MESSAGE = "La transacci\u00f3n ya se encuentra registrada";
    private static final String NUMBER_SEPARATOR = "-";
    private static final String REQUEST_FIELD = "idTranssacion";
    private static final String PAYLOAD_FIELD = "payloadSAP";
    private static final int REFERENCE_PARTS = 3;
    private static final int CAN_RESEND = 1;
    private static final int CANNOT_RESEND = 0;
    private final ObjectMapper json = new ObjectMapper();

    public String journalEntryNumber(String order, String delivery, String invoice) {
        if (blank(order) || blank(delivery) || blank(invoice)) {
            return null;
        }
        return order + NUMBER_SEPARATOR + delivery + NUMBER_SEPARATOR + invoice;
    }

    public JourneyEntryBasicResponse basic() {
        JourneyEntryBasicResponse response = new JourneyEntryBasicResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        return response;
    }

    public GetJourneyEntryResponse list(List<JournalEntryEntity> entries, Map<Long, JournalEntryStatusEntity> catalog) {
        List<AccountingEntryItem> items = new ArrayList<>();
        for (JournalEntryEntity entry : entries) {
            items.add(item(entry, catalog.get(entry.getJournalEntryStatusId())));
        }
        GetJourneyEntryData data = new GetJourneyEntryData();
        data.setAccountingEntry(items);
        GetJourneyEntryResponse response = new GetJourneyEntryResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private AccountingEntryItem item(JournalEntryEntity entry, JournalEntryStatusEntity status) {
        AccountingEntryItem item = new AccountingEntryItem();
        item.setId(entry.getId());
        item.setJournalEntryNumber(journalEntryNumber(entry.getSapOrderNumber(), entry.getSapDeliveryNumber(), entry.getSapInvoiceNumber()));
        item.setOrderNumber(entry.getOrderNumber());
        item.setSapAccountingDocumentNumber(entry.getSapAccountingDocumentNumber());
        item.setSentToSapAt(entry.getLastSapAttemptDate());
        String[] parts = entry.getNroReference() == null ? new String[0] : entry.getNroReference().split(NUMBER_SEPARATOR);
        if (parts.length == REFERENCE_PARTS) {
            item.setDocumentType(parts[0]);
            item.setSeries(parts[1]);
            item.setCorrelative(parts[2]);
        }
        String value = status == null ? null : status.getValue();
        item.setSapStatus(value);
        item.setCanResend(NOT_RETRYABLE.equals(value) ? CAN_RESEND : CANNOT_RESEND);
        return item;
    }

    public CreateJourneyEntryResponse accepted(JournalEntryEntity entry, String status) {
        return created(entry, status, HttpStatus.ACCEPTED.value(), ACCEPTED_MESSAGE);
    }

    public CreateJourneyEntryResponse duplicate(JournalEntryEntity entry, String status) {
        return created(entry, status, HttpStatus.OK.value(), DUPLICATE_MESSAGE);
    }

    private CreateJourneyEntryResponse created(JournalEntryEntity entry, String status, int code, String message) {
        CreateJourneyEntryAcceptedData data = new CreateJourneyEntryAcceptedData();
        data.setJournalEntryId(entry.getId());
        data.setRequestReference(entry.getRequestReference());
        data.setStatus(status);
        CreateJourneyEntryResponse response = new CreateJourneyEntryResponse();
        response.setCode(code);
        response.setMessage(message);
        response.setData(data);
        return response;
    }

    public JournalEntryEntity newEntry(CreateJourneyEntryRequest request, String nroReference, JsonNode payload, Long statusId, String user, LocalDateTime now) {
        JournalEntryEntity entry = new JournalEntryEntity();
        entry.setRequestReference(request.getIdTranssacion());
        entry.setNroReference(nroReference);
        entry.setEntryPayload(json.createObjectNode().put(REQUEST_FIELD, request.getIdTranssacion()).put(PAYLOAD_FIELD, request.getPayloadSAP()).toString());
        entry.setFirstRequest(payload.path("rfcRequests").path("Z02OTCMF_GEN_FLUJO_COM").toString());
        entry.setSecondRequest(payload.path("rfcRequests").path("Z02OTCMF_VENTAS_CONVER").toString());
        entry.setAttemptNumber(0);
        entry.setJournalEntryStatusId(statusId);
        entry.setCreationUser(user);
        entry.setCreationDate(now);
        return entry;
    }

    public JournalEntryHistEntity snapshot(JournalEntryEntity entry, LocalDateTime now, String user) {
        JournalEntryHistEntity hist = new JournalEntryHistEntity();
        hist.setJournalEntryId(entry.getId());
        hist.setRequestReference(entry.getRequestReference());
        hist.setNroReference(entry.getNroReference());
        hist.setEntryPayload(entry.getEntryPayload());
        hist.setFirstRequest(entry.getFirstRequest());
        hist.setFirstResponse(entry.getFirstResponse());
        hist.setSecondRequest(entry.getSecondRequest());
        hist.setSecondResponse(entry.getSecondResponse());
        hist.setOrderNumber(entry.getOrderNumber());
        hist.setAttemptNumber(entry.getAttemptNumber());
        hist.setJournalEntryStatusId(entry.getJournalEntryStatusId());
        hist.setFirstSapAttemptDate(entry.getFirstSapAttemptDate());
        hist.setLastSapAttemptDate(entry.getLastSapAttemptDate());
        hist.setSapOrderNumber(entry.getSapOrderNumber());
        hist.setSapDeliveryNumber(entry.getSapDeliveryNumber());
        hist.setSapInvoiceNumber(entry.getSapInvoiceNumber());
        hist.setSapAccountingDocumentNumber(entry.getSapAccountingDocumentNumber());
        hist.setSnapshotDate(now);
        hist.setCreationUser(user);
        hist.setCreationDate(now);
        return hist;
    }

    public void applyResult(JournalEntryEntity entry, UpdateJourneyEntryResultRequest request, LocalDateTime attemptStart, String user, LocalDateTime now) {
        entry.setJournalEntryStatusId(request.getJournalEntryStatusId());
        entry.setAttemptNumber(request.getAttemptNumber());
        entry.setLastSapAttemptDate(attemptStart);
        if (entry.getFirstSapAttemptDate() == null) {
            entry.setFirstSapAttemptDate(attemptStart);
        }
        if (request.getFirstResponse() != null) {
            entry.setFirstResponse(request.getFirstResponse());
        }
        if (request.getSecondResponse() != null) {
            entry.setSecondResponse(request.getSecondResponse());
        }
        if (request.getSapOrderNumber() != null) {
            entry.setSapOrderNumber(request.getSapOrderNumber());
        }
        if (request.getSapDeliveryNumber() != null) {
            entry.setSapDeliveryNumber(request.getSapDeliveryNumber());
        }
        if (request.getSapInvoiceNumber() != null) {
            entry.setSapInvoiceNumber(request.getSapInvoiceNumber());
        }
        if (request.getSapAccountingDocumentNumber() != null) {
            entry.setSapAccountingDocumentNumber(request.getSapAccountingDocumentNumber());
        }
        entry.setLastModifiedUser(user);
        entry.setLastModifiedDate(now);
    }

    public GetJourneyEntryTraceabilityResponse traceability(JournalEntryEntity entry, List<JournalEntryHistEntity> history, Map<Long, JournalEntryStatusEntity> catalog) {
        List<JourneyEntryHistoryItem> items = new ArrayList<>();
        for (JournalEntryHistEntity hist : history) {
            JournalEntryStatusEntity status = catalog.get(hist.getJournalEntryStatusId());
            JourneyEntryHistoryItem item = new JourneyEntryHistoryItem();
            item.setId(hist.getId());
            item.setJournalEntryNumber(journalEntryNumber(hist.getSapOrderNumber(), hist.getSapDeliveryNumber(), hist.getSapInvoiceNumber()));
            item.setStatus(status == null ? null : status.getValue());
            item.setStatusDescription(status == null ? null : status.getDescription());
            item.setOccurredAt(hist.getSnapshotDate());
            item.setUser(hist.getCreationUser());
            items.add(item);
        }
        JournalEntryStatusEntity current = catalog.get(entry.getJournalEntryStatusId());
        GetJourneyEntryTraceabilityData data = new GetJourneyEntryTraceabilityData();
        data.setJournalEntryId(entry.getId());
        data.setJournalEntryNumber(journalEntryNumber(entry.getSapOrderNumber(), entry.getSapDeliveryNumber(), entry.getSapInvoiceNumber()));
        data.setCurrentStatus(current == null ? null : current.getValue());
        data.setCurrentStatusDescription(current == null ? null : current.getDescription());
        data.setRegisteredAt(entry.getCreationDate());
        data.setHistory(items);
        GetJourneyEntryTraceabilityResponse response = new GetJourneyEntryTraceabilityResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    public GetJourneyEntryByIdResponse byId(JournalEntryEntity entry, JournalEntryStatusEntity status) {
        GetJourneyEntryByIdData data = new GetJourneyEntryByIdData();
        data.setJournalEntryId(entry.getId());
        data.setRequestreference(entry.getRequestReference());
        data.setNroReference(entry.getNroReference());
        data.setOrderNumber(entry.getOrderNumber());
        data.setEntryPayload(entry.getEntryPayload());
        data.setFirstRequest(entry.getFirstRequest());
        data.setFirstResponse(entry.getFirstResponse());
        data.setSecondRequest(entry.getSecondRequest());
        data.setSecondResponse(entry.getSecondResponse());
        data.setAttemptNumber(entry.getAttemptNumber());
        data.setFirstSapAttemptDate(entry.getFirstSapAttemptDate());
        data.setLastSapAttemptDate(entry.getLastSapAttemptDate());
        data.setSapAccountingDocumentNumber(entry.getSapAccountingDocumentNumber());
        data.setSapOrderNumber(entry.getSapOrderNumber());
        data.setSapDeliveryNumber(entry.getSapDeliveryNumber());
        data.setSapInvoiceNumber(entry.getSapInvoiceNumber());
        data.setJournalStatusId(entry.getJournalEntryStatusId());
        if (status != null) {
            data.setJournalEntryStatus(status.getValue());
            data.setDescription(status.getDescription());
        }
        GetJourneyEntryByIdResponse response = new GetJourneyEntryByIdResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private boolean blank(String value) {
        return value == null || value.isBlank();
    }
}'''

FORWARDED_HEADERS = '''/** Headers de trazabilidad que se propagan a los servicios invocados. */
public record ForwardedHeaders(String traceparent, String xAppId, String xChannel, String xClientVersionId, String xCorrelationId, String xRequestId, String xUserId) {
}'''

CLIENT_IF = '''/** Consulta de la configuracion contable de sod-general-configurations. */
public interface AccountingConfigClient {
    List<ConfigurationData> findConfigurations(ForwardedHeaders headers);
}'''

CLIENT_IMPL = '''/** Cliente HTTP de configuraciones; ante indisponibilidad usa el ultimo valor obtenido si existe. */
@Component
@Slf4j
public class AccountingConfigClientImpl implements AccountingConfigClient {
    private static final String PATH = "/api/v1/sod-configurations";
    private static final String CONFIG_NOT_FOUND = "No se encontr\u00f3 la configuraci\u00f3n contable solicitada.";
    private static final String CONFIG_UNAVAILABLE = "Servicio de configuraciones no disponible.";
    private static final int REQUEST_TIMEOUT = 408;
    private static final int GATEWAY_TIMEOUT_CODE = 504;
    private final RestClient restClient;
    private final String configGroup;
    private final AtomicReference<List<ConfigurationData>> cache = new AtomicReference<>();

    public AccountingConfigClientImpl(RestClient accountingConfigRestClient, @Value("${accounting.validation.config-group:ACCOUNTING_VALIDATION}") String configGroup) {
        this.restClient = accountingConfigRestClient;
        this.configGroup = configGroup;
    }

    @Override
    public List<ConfigurationData> findConfigurations(ForwardedHeaders headers) {
        try {
            ConfigurationResponse response = restClient.get()
                    .uri(uri -> uri.path(PATH).queryParam("configGroup", configGroup).build())
                    .headers(target -> {
                        put(target, "traceparent", headers.traceparent());
                        put(target, "x-app-id", headers.xAppId());
                        put(target, "x-channel", headers.xChannel());
                        put(target, "x-client-version-id", headers.xClientVersionId());
                        put(target, "x-correlation-id", headers.xCorrelationId());
                        put(target, "x-request-id", headers.xRequestId());
                        put(target, "x-user-id", headers.xUserId());
                    })
                    .retrieve()
                    .body(ConfigurationResponse.class);
            List<ConfigurationData> data = response == null || response.getData() == null ? List.of() : response.getData();
            cache.set(data);
            return data;
        } catch (ResourceAccessException e) {
            return fallback(e, timedOut(e) ? HttpStatus.GATEWAY_TIMEOUT : HttpStatus.SERVICE_UNAVAILABLE);
        } catch (RestClientResponseException e) {
            int code = e.getStatusCode().value();
            if (code == GATEWAY_TIMEOUT_CODE || code == REQUEST_TIMEOUT) {
                return fallback(e, HttpStatus.GATEWAY_TIMEOUT);
            }
            if (code >= HttpStatus.INTERNAL_SERVER_ERROR.value()) {
                return fallback(e, HttpStatus.SERVICE_UNAVAILABLE);
            }
            throw new ServiceOperationException(HttpStatus.NOT_FOUND, CONFIG_NOT_FOUND, e);
        }
    }

    private List<ConfigurationData> fallback(RuntimeException failure, HttpStatus status) {
        List<ConfigurationData> cached = cache.get();
        if (cached != null) {
            log.warn("Configuracion contable no disponible, se usa el ultimo valor obtenido: {}", failure.getMessage());
            return cached;
        }
        throw new ServiceOperationException(status, CONFIG_UNAVAILABLE, failure);
    }

    private static void put(HttpHeaders target, String name, String value) {
        if (value != null) {
            target.set(name, value);
        }
    }

    private static boolean timedOut(Throwable failure) {
        for (Throwable cause = failure; cause != null; cause = cause.getCause()) {
            if (cause instanceof SocketTimeoutException) {
                return true;
            }
        }
        return false;
    }
}'''

CLIENT_CONFIG = '''/** Cliente HTTP hacia sod-general-configurations con timeouts configurables. */
@Configuration
public class AccountingConfigClientConfig {
    @Bean
    public RestClient accountingConfigRestClient(@Value("${sod-general-configurations.base-url:http://sod-general-configurations}") String baseUrl,
            @Value("${sod-general-configurations.timeout-ms:5000}") int timeoutMs) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeoutMs);
        factory.setReadTimeout(timeoutMs);
        return RestClient.builder().baseUrl(baseUrl).requestFactory(factory).build();
    }
}'''

TRANSACTION_CONFIG = '''/** Limite transaccional local de las operaciones de escritura. */
@Configuration
public class TransactionConfig {
    @Bean
    public TransactionTemplate transactionTemplate(PlatformTransactionManager manager) {
        return new TransactionTemplate(manager);
    }
}'''
