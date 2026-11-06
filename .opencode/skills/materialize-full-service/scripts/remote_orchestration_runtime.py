"""Static Java sources of the remote-orchestration pattern (runtime support shared by every orchestrated service).

Every entry is a pure text template without package/imports (added by `remote_orchestration_java.finalize`). `__P__` is the base package.
Nothing here depends on a particular service: statuses, codes and flows are generated from the plan.
"""

JSON = '''/** Null-safe reading helpers over Jackson trees: absent values are NullNode, never null. */
public final class Json {
    private static final Map<String, List<String>> ALIASES = Map.of(
            "quoteExpirationDate", List.of("quoteExperationDate"),
            "createdAt", List.of("createDate", "createAt"),
            "requestTypeId", List.of("requestType"));

    private Json() {
    }

    /** The data object of an answer; when data is an array the first element is used. */
    public static JsonNode data(JsonNode body) {
        JsonNode data = body == null ? MissingNode.getInstance() : body.path("data");
        if (data.isArray()) {
            return data.isEmpty() ? MissingNode.getInstance() : data.get(0);
        }
        return data;
    }

    public static JsonNode at(JsonNode node, String name) {
        if (node == null || node.isMissingNode() || node.isNull()) {
            return NullNode.getInstance();
        }
        JsonNode found = node.get(name);
        for (String other : ALIASES.getOrDefault(name, List.of())) {
            if (found == null || found.isNull()) {
                found = node.get(other);
            }
        }
        return found == null ? NullNode.getInstance() : found;
    }

    /** The elements of the array at a dotted path of the answer (empty when absent). */
    public static List<JsonNode> list(JsonNode body, String dotted) {
        JsonNode current = body == null ? MissingNode.getInstance() : body;
        for (String step : dotted.split("\\\\.")) {
            current = current.path(step);
        }
        List<JsonNode> elements = new ArrayList<>();
        if (current.isArray()) {
            current.forEach(elements::add);
        } else if (current.isObject()) {
            elements.add(current);
        }
        return elements;
    }

    public static boolean isEmpty(Object value) {
        Object plain = plain(value);
        return plain == null || plain instanceof String text && text.isBlank();
    }

    /** JsonNode scalars become Java values; containers are returned as they are. */
    public static Object plain(Object value) {
        if (value instanceof JsonNode node) {
            if (node.isNull() || node.isMissingNode()) {
                return null;
            }
            if (node.isNumber()) {
                return node.decimalValue();
            }
            if (node.isBoolean()) {
                return node.booleanValue();
            }
            if (node.isTextual()) {
                return node.textValue();
            }
        }
        return value;
    }

    public static Long toLong(Object value) {
        Object plain = plain(value);
        if (plain == null) {
            return null;
        }
        if (plain instanceof BigDecimal number) {
            return number.longValueExact();
        }
        if (plain instanceof Number number) {
            return number.longValue();
        }
        String text = plain.toString().trim();
        return text.isEmpty() ? null : new BigDecimal(text).longValueExact();
    }

    public static BigDecimal toDecimal(Object value) {
        Object plain = plain(value);
        if (plain == null) {
            return null;
        }
        if (plain instanceof BigDecimal number) {
            return number;
        }
        if (plain instanceof Number number) {
            return new BigDecimal(number.toString());
        }
        String text = plain.toString().trim();
        return text.isEmpty() ? null : new BigDecimal(text);
    }

    public static String toText(Object value) {
        Object plain = plain(value);
        return plain == null ? null : plain.toString();
    }

    /** First ten characters of an ISO-8601 date or date-time. */
    public static LocalDate toDate(Object value) {
        String text = toText(value);
        if (text == null || text.length() < ISO_DATE_LENGTH) {
            return null;
        }
        return LocalDate.parse(text.substring(0, ISO_DATE_LENGTH));
    }

    private static final int ISO_DATE_LENGTH = 10;
}'''

BODY = '''/** Fluent builder of JSON bodies, query strings and headers of the dependency calls. Null values become JSON null in bodies and are omitted elsewhere. */
public final class Body {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private final ObjectNode node = MAPPER.createObjectNode();

    private Body() {
    }

    public static Body of() {
        return new Body();
    }

    public Body put(String name, Object value) {
        Object plain = value instanceof JsonNode json ? Json.plain(json) : value;
        if (plain == null) {
            node.putNull(name);
        } else if (value instanceof JsonNode json && !json.isValueNode()) {
            node.set(name, json);
        } else if (plain instanceof BigDecimal number) {
            node.put(name, number);
        } else if (plain instanceof Number number) {
            node.put(name, new BigDecimal(number.toString()));
        } else if (plain instanceof Boolean flag) {
            node.put(name, flag);
        } else {
            node.put(name, plain.toString());
        }
        return this;
    }

    public Body list(String name, List<JsonNode> source, Function<JsonNode, Body> element) {
        ArrayNode array = node.putArray(name);
        for (JsonNode item : source) {
            array.add(element.apply(item).build());
        }
        return this;
    }

    public ObjectNode build() {
        return node;
    }

    /** Map of the present (non null) values, for query strings and path variables. */
    public Map<String, Object> toMap() {
        Map<String, Object> values = new LinkedHashMap<>();
        node.fields().forEachRemaining(entry -> {
            if (!entry.getValue().isNull()) {
                values.put(entry.getKey(), Json.plain(entry.getValue()));
            }
        });
        return values;
    }

    public Map<String, String> toStrings() {
        Map<String, String> values = new LinkedHashMap<>();
        toMap().forEach((key, value) -> values.put(key, value.toString()));
        return values;
    }
}'''

REMOTE_RESPONSE = '''/** Answer of a dependency: HTTP status and JSON body (NullNode when the answer has no readable body). */
public record RemoteResponse(int status, JsonNode body) {
    public static final int FIRST_SERVER_ERROR = 500;

    public boolean serverError() {
        return status >= FIRST_SERVER_ERROR;
    }

    /** The message a dependency answered, used as the output detail of the business error. */
    public String message() {
        String text = Json.toText(body == null ? null : body.path("message"));
        return text == null ? "" : text;
    }
}'''

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

    /** Value of a received header by its HTTP name (null when unknown). */
    public String value(String name) {
        return switch (name) {
            case "traceparent" -> traceparent;
            case "x-app-id" -> xAppId;
            case "x-channel" -> xChannel;
            case "x-client-version-id" -> xClientVersionId;
            case "x-correlation-id" -> xCorrelationId;
            case "x-request-id" -> xRequestId;
            case "x-user-id" -> xUserId;
            default -> null;
        };
    }

    private static void put(HttpHeaders target, String name, String value) {
        if (value != null) {
            target.set(name, value);
        }
    }
}'''

GATEWAY = '''/** HTTP access to one dependency. HTTP error statuses are answers; connection failures and timeouts are technical (IDT) failures. */
@Slf4j
public class RemoteGateway {
    private final RestClient restClient;
    private final ObjectMapper mapper;
    private final String service;

    public RemoteGateway(RestClient restClient, ObjectMapper mapper, String service) {
        this.restClient = restClient;
        this.mapper = mapper;
        this.service = service;
    }

    public String service() {
        return service;
    }

    public RemoteResponse send(HttpMethod method, String path, Consumer<HttpHeaders> headers, Map<String, Object> pathVariables, Map<String, Object> query, JsonNode body) {
        try {
            RestClient.RequestBodySpec request = restClient.method(method)
                    .uri(builder -> {
                        builder.path(path);
                        query.forEach(builder::queryParam);
                        return builder.build(pathVariables);
                    })
                    .headers(headers);
            if (body != null) {
                request.contentType(MediaType.APPLICATION_JSON).body(body);
            }
            return request.exchange((call, response) -> new RemoteResponse(response.getStatusCode().value(), read(response.getBody())));
        } catch (ResourceAccessException failure) {
            log.error("{} {} {} failed: {}", service, method, path, failure.getMessage());
            throw ErrorCatalog.build(timedOut(failure) ? ErrorCatalog.TIMEOUT : ErrorCatalog.UNAVAILABLE, service, failure.getMessage(), null);
        } catch (RestClientException failure) {
            log.error("{} {} {} failed: {}", service, method, path, failure.getMessage());
            throw ErrorCatalog.build(ErrorCatalog.INTERNAL, service, failure.getMessage(), null);
        }
    }

    private JsonNode read(InputStream stream) {
        try {
            JsonNode node = mapper.readTree(stream);
            return node == null ? NullNode.getInstance() : node;
        } catch (IOException failure) {
            return NullNode.getInstance();
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

STEP_OUTCOME = '''/** How the answer of a dependency call is interpreted: accepted statuses, business code per status and compensation. */
public final class StepOutcome {
    private final String service;
    private final Set<Integer> accepted = new HashSet<>();
    private final Map<Integer, String> byStatus = new HashMap<>();
    private String otherwise;
    private String emptyList;
    private Runnable compensation;

    private StepOutcome(String service) {
        this.service = service;
    }

    public static StepOutcome of(String service) {
        return new StepOutcome(service);
    }

    public StepOutcome ok(int... statuses) {
        for (int status : statuses) {
            accepted.add(status);
        }
        return this;
    }

    public StepOutcome on(int status, String code) {
        byStatus.put(status, code);
        return this;
    }

    public StepOutcome otherwise(String code) {
        this.otherwise = code;
        return this;
    }

    public StepOutcome emptyList(String code) {
        this.emptyList = code;
        return this;
    }

    public StepOutcome compensate(Runnable action) {
        this.compensation = action;
        return this;
    }

    public String service() {
        return service;
    }

    public boolean accepts(int status) {
        return accepted.contains(status);
    }

    public String codeFor(int status) {
        return byStatus.getOrDefault(status, otherwise);
    }

    public String emptyListCode() {
        return emptyList;
    }

    public void compensation() {
        if (compensation != null) {
            compensation.run();
        }
    }
}'''

RULES = '''/** Comparisons used by the decisions of the flows: numbers compare by value, texts by equality, absent values never match. */
public final class Rules {
    private Rules() {
    }

    private static int compare(Object left, Object right) {
        BigDecimal a = Json.toDecimal(left);
        BigDecimal b = Json.toDecimal(right);
        if (a == null || b == null) {
            throw new IllegalArgumentException("A value required by a decision is absent");
        }
        return a.compareTo(b);
    }

    public static boolean eq(Object left, Object right) {
        Object a = Json.plain(left);
        Object b = Json.plain(right);
        if (a == null || b == null) {
            return false;
        }
        if (a instanceof String && b instanceof String) {
            return a.equals(b);
        }
        try {
            return compare(a, b) == 0;
        } catch (NumberFormatException failure) {
            return a.toString().equals(b.toString());
        }
    }

    public static boolean gt(Object left, Object right) {
        return left != null && Json.plain(left) != null && compare(left, right) > 0;
    }

    public static boolean ge(Object left, Object right) {
        return left != null && Json.plain(left) != null && compare(left, right) >= 0;
    }

    public static boolean le(Object left, Object right) {
        return left != null && Json.plain(left) != null && compare(left, right) <= 0;
    }

    public static boolean empty(Object value) {
        return Json.isEmpty(value);
    }

    public static int size(Object value) {
        return value instanceof Collection<?> collection ? collection.size() : 0;
    }

    public static BigDecimal add(Object left, Object right) {
        return Json.toDecimal(left).add(Json.toDecimal(right));
    }

    public static BigDecimal round2(Object value) {
        return Json.toDecimal(value).setScale(Calculations.MONEY_SCALE, RoundingMode.HALF_UP);
    }
}'''

CALCULATIONS = '''/** Calculations of the flows (money with BigDecimal; quote amounts rounded HALF_UP to two decimals). */
public final class Calculations {
    public static final int MONEY_SCALE = 2;
    private static final int PERCENT_SCALE = 10;
    private static final BigDecimal HUNDRED = BigDecimal.valueOf(100);
    private static final String STATE = "quoteStateCodeId";
    private static final String NUMBER = "quoteNumber";
    private static final String CODE = "quoteCodeId";

    private Calculations() {
    }

    public static BigDecimal subtract(Object left, Object right) {
        return Json.toDecimal(left).subtract(Json.toDecimal(right));
    }

    public static BigDecimal divideMoney(Object amount, Object divisor) {
        return Json.toDecimal(amount).divide(Json.toDecimal(divisor), MONEY_SCALE, RoundingMode.HALF_UP);
    }

    public static BigDecimal percentage(Object part, Object whole) {
        return Json.toDecimal(part).multiply(HUNDRED).divide(Json.toDecimal(whole), PERCENT_SCALE, RoundingMode.HALF_UP);
    }

    /** 5.4.3: configured minimum percentage by the state of the line (1 active, 2 suspended, 3 disabled). */
    public static BigDecimal minimumPercentage(Object stateLine, Object active, Object suspended, Object disabled) {
        String state = Json.toText(stateLine);
        if ("1".equals(state)) {
            return Json.toDecimal(active);
        }
        if ("2".equals(state)) {
            return Json.toDecimal(suspended);
        }
        if ("3".equals(state)) {
            return Json.toDecimal(disabled);
        }
        throw new IllegalArgumentException("Unknown line state");
    }

    public static List<JsonNode> byState(List<JsonNode> installments, Object state) {
        List<JsonNode> selected = new ArrayList<>();
        for (JsonNode installment : installments) {
            if (Rules.eq(Json.at(installment, STATE), state)) {
                selected.add(installment);
            }
        }
        return selected;
    }

    public static BigDecimal sumQuotes(List<JsonNode> installments) {
        BigDecimal total = BigDecimal.ZERO;
        for (JsonNode installment : installments) {
            total = total.add(Json.toDecimal(Json.at(installment, "quoteAmount")));
        }
        return total;
    }

    /** 7.3: 1 when a quote other than the initial one is neither pending nor notified. */
    public static int hasIneligible(List<JsonNode> installments, Object pending, Object notified, Object initial) {
        for (JsonNode installment : installments) {
            boolean eligible = Rules.eq(Json.at(installment, STATE), pending) || Rules.eq(Json.at(installment, STATE), notified);
            if (!eligible && !Rules.eq(Json.at(installment, NUMBER), initial)) {
                return 1;
            }
        }
        return 0;
    }

    /** 7.6: reduced list with the new state (exported for the initial quote, cancelled for the others). */
    public static List<JsonNode> cancellationTransform(List<JsonNode> installments, Object exported, Object cancelled) {
        List<JsonNode> result = new ArrayList<>();
        for (JsonNode installment : installments) {
            Object state = Rules.eq(Json.at(installment, NUMBER), 0) ? exported : cancelled;
            result.add(Body.of().put(CODE, Json.at(installment, CODE)).put(NUMBER, Json.at(installment, NUMBER)).put(STATE, state).build());
        }
        return result;
    }

    /** The installments whose field does not have the given value (used to leave out the initial quote). */
    public static List<JsonNode> without(List<JsonNode> installments, String field, Object value) {
        List<JsonNode> result = new ArrayList<>();
        for (JsonNode installment : installments) {
            if (!Rules.eq(Json.at(installment, field), value)) {
                result.add(installment);
            }
        }
        return result;
    }

    /** 9.3: pending or notified quotes whose issue date is today or later. */
    public static List<JsonNode> filterForServiceCancellation(List<JsonNode> installments, Object pending, Object notified, LocalDate today) {
        List<JsonNode> result = new ArrayList<>();
        for (JsonNode installment : installments) {
            boolean state = Rules.eq(Json.at(installment, STATE), pending) || Rules.eq(Json.at(installment, STATE), notified);
            LocalDate issued = Json.toDate(Json.at(installment, "quoteIssueDate"));
            if (state && issued != null && !issued.isBefore(today)) {
                result.add(installment);
            }
        }
        return result;
    }

    /** 4.4: quotes of the financing paid in collections (matched by quoteNumber; quote 0 is the initial quote and is skipped). */
    public static List<JsonNode> filterPaidForSync(List<JsonNode> installments, List<JsonNode> collections, Object paid) {
        List<JsonNode> result = new ArrayList<>();
        for (JsonNode installment : installments) {
            if (Rules.eq(Json.at(installment, NUMBER), 0)) {
                continue;
            }
            for (JsonNode match : collections) {
                if (Rules.eq(Json.at(match, NUMBER), Json.at(installment, NUMBER)) && Rules.eq(Json.at(match, STATE), paid)) {
                    result.add(Body.of().put(CODE, Json.at(installment, CODE)).put(NUMBER, Json.at(installment, NUMBER))
                            .put("paymentDate", Json.at(match, "paymentDate")).put("paymentAmount", Json.at(match, "quoteAmount")).put(STATE, paid).build());
                    break;
                }
            }
        }
        return result;
    }

    /** 10.5: new issue and expiration dates; the first quote takes the requested cycle, each next one adds one calendar month. */
    public static List<JsonNode> billingCycleDates(List<JsonNode> installments, Object quoteCycle, Object expirationDays) {
        List<JsonNode> ordered = new ArrayList<>(installments);
        ordered.sort(Comparator.comparing(installment -> Json.toLong(Json.at(installment, NUMBER))));
        LocalDate issue = LocalDate.parse(Json.toText(quoteCycle));
        long days = Json.toLong(expirationDays);
        List<JsonNode> result = new ArrayList<>();
        for (JsonNode installment : ordered) {
            result.add(Body.of().put(CODE, Json.at(installment, CODE)).put("quoteFormat", Json.at(installment, "quoteFormat")).put(NUMBER, Json.at(installment, NUMBER))
                    .put("quoteIssueDate", issue).put("quoteExpirationDate", issue.plusDays(days)).put("agreementCodeId", Json.at(installment, "agreementCodeId"))
                    .put(STATE, Json.at(installment, STATE)).build());
            issue = issue.plusMonths(1);
        }
        return result;
    }
}'''

CLOCK_CONFIG = '''/** Single time source of the service: dates and timestamps are derived from this injectable clock. */
@Configuration
public class ClockConfig {
    @Bean
    public Clock clock() {
        return Clock.systemDefaultZone();
    }
}'''

SERVICE_OPERATION_EXCEPTION = '''/** Application failure that carries the HTTP status and the contract error identity (subType, type, detail). */
public class ServiceOperationException extends RuntimeException {
    private final HttpStatus status;
    private final String subType;
    private final String type;

    public ServiceOperationException(HttpStatus status, String subType, String type, String detail) {
        super(detail);
        this.status = status;
        this.subType = subType;
        this.type = type;
    }

    public HttpStatus getStatus() {
        return status;
    }

    public String getSubType() {
        return subType;
    }

    public String getType() {
        return type;
    }
}'''

ERROR_RESPONSE = '''/** Error body declared by the contract. */
@Data
public class ErrorResponse {
    private String status;
    private Integer code;
    private String subType;
    private String type;
    private String message;
    private String detail;
}'''

REQUEST_HEADERS = '''/**
 * Technical request headers carried to the service layer. Components are the roles that have a declared target header; they are technical identifiers, never business fields.
 */
public record RequestHeaders(
        String transactionId,
        String userId,
        String applicationName
) {

}'''

SYSTEM_SETTINGS = '''/**
 * Configuration of the financing module read from the parameters service (activity 1.1) with a local cache: the cached copy is used until its
 * time to live expires; when a refresh fails the last valid copy keeps being used, and only without any copy the failure is reported.
 */
@Component
@Slf4j
public class SystemSettings {
    private final ParametersClient client;
    private final Clock clock;
    private final long ttlMillis;
    private Map<String, String> cached;
    private Instant loadedAt;

    public SystemSettings(ParametersClient client, Clock clock, @Value("${agreement-orquestation.settings.max-time-refresh-cache:3600000}") long ttlMillis) {
        this.client = client;
        this.clock = clock;
        this.ttlMillis = ttlMillis;
    }

    /** Current configuration (key to value). */
    public synchronized Map<String, String> load(ForwardedHeaders headers) {
        Instant now = Instant.now(clock);
        if (cached != null && loadedAt.plusMillis(ttlMillis).isAfter(now)) {
            return cached;
        }
        try {
            RemoteResponse response = client.list(headers::applyTo, Map.of(), Map.of(), null);
            if (response.status() == HttpStatus.OK.value()) {
                Map<String, String> fresh = new HashMap<>();
                for (JsonNode item : Json.list(response.body(), "data")) {
                    fresh.put(Json.toText(Json.at(item, "clueParameter")), Json.toText(Json.at(item, "data")));
                }
                cached = fresh;
                loadedAt = now;
                return cached;
            }
            return fallback(response.status() >= RemoteResponse.FIRST_SERVER_ERROR ? ErrorCatalog.build(ErrorCatalog.INTERNAL, client.service(), "HTTP " + response.status(), null)
                    : ErrorCatalog.build("__CONFIG_CODE__", client.service(), response.message(), null));
        } catch (ServiceOperationException failure) {
            return fallback(failure);
        }
    }

    private Map<String, String> fallback(ServiceOperationException failure) {
        if (cached == null) {
            throw failure;
        }
        log.warn("The parameters service could not be refreshed ({}); the last valid copy is used", failure.getSubType());
        return cached;
    }
}'''

FLOW_INTERFACE = '''/** A request type flow of the orchestration. */
public interface AgreementFlow {
    int requestTypeId();

    /** Whether the installments of the financing are synchronized with collections before the flow (Sparx activity 4). */
    boolean synchronizesInstallments();

    AgreementResponseData execute(FlowContext ctx);
}'''

FLOW_CONTEXT = '''/** State of one execution: request, headers, settings, answers of the dependencies by activity and calculated values. */
@Slf4j
public final class FlowContext {
    private static final DateTimeFormatter TIMESTAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssZ");
    private static final String ERROR_PATTERN = "{} ERROR [{}] code={} detail={}";
    public static final Runnable NO_COMPENSATION = () -> { };

    private final RequestHeaders headers;
    private final ForwardedHeaders forwarded;
    private final AgreementRequest request;
    private final Clock clock;
    private final String menTran;
    private final Map<String, String> settings;
    private final Map<String, JsonNode> responses = new HashMap<>();
    private final Map<String, Object> values = new HashMap<>();

    public FlowContext(RequestHeaders headers, ForwardedHeaders forwarded, AgreementRequest request, Clock clock, String menTran, Map<String, String> settings) {
        this.headers = headers;
        this.forwarded = forwarded;
        this.request = request;
        this.clock = clock;
        this.menTran = menTran;
        this.settings = settings;
    }

    public RequestHeaders headers() {
        return headers;
    }

    public ForwardedHeaders forwarded() {
        return forwarded;
    }

    public AgreementRequest request() {
        return request;
    }

    public String menTran() {
        return menTran;
    }

    public LocalDate today() {
        return LocalDate.now(clock);
    }

    public String timestamp() {
        return OffsetDateTime.now(clock).format(TIMESTAMP);
    }

    public String header(String name) {
        return forwarded.value(name);
    }

    /** Explicit headers of a dependency call (used when the evidence maps them one by one instead of forwarding all). */
    public Consumer<HttpHeaders> headers(Map<String, String> values) {
        return target -> values.forEach(target::set);
    }

    public String setting(String key) {
        return settings.get(key);
    }

    public JsonNode field(String key, String name) {
        return Json.at(Json.data(responses.get(key)), name);
    }

    public List<JsonNode> list(String key, String dotted) {
        return Json.list(responses.get(key), dotted);
    }

    public Object value(String key, String name) {
        return values.get(key + "/" + name);
    }

    public void put(String key, String name, Object value) {
        values.put(key + "/" + name, value);
    }

    /** Records the answer of a dependency step (used by the synchronization and by tests that start from a known state). */
    public void remember(String key, JsonNode body) {
        responses.put(key, body);
    }

    @SuppressWarnings("unchecked")
    public List<JsonNode> valueList(String key, String name) {
        return (List<JsonNode>) values.get(key + "/" + name);
    }

    /** Installments answered by a generation step, in the contract shape. */
    public List<AgreementInstallmentDto> installments(String key) {
        List<AgreementInstallmentDto> result = new ArrayList<>();
        for (JsonNode item : Json.list(responses.get(key), "data.installments")) {
            AgreementInstallmentDto dto = new AgreementInstallmentDto();
            dto.setQuoteNumber(Json.toLong(Json.at(item, "quoteNumber")));
            dto.setQuoteFormat(Json.toText(Json.at(item, "quoteFormat")));
            dto.setQuoteIssueDate(Json.toText(Json.at(item, "quoteIssueDate")));
            dto.setQuoteExpirationDate(Json.toText(Json.at(item, "quoteExpirationDate")));
            dto.setQuoteAmount(Json.toDecimal(Json.at(item, "quoteAmount")));
            dto.setQuoteStateCodeId(Json.toLong(Json.at(item, "quoteStateCodeId")));
            result.add(dto);
        }
        return result;
    }

    /** True when more than the configured hours passed since the given instant (date-only values count from the start of the day). */
    public boolean hoursExceed(Object createdAt, Object hours) {
        String text = Json.toText(createdAt);
        if (text == null) {
            throw new IllegalArgumentException("The creation instant is absent");
        }
        LocalDateTime created = text.length() > "yyyy-MM-dd".length() ? parseInstant(text) : LocalDate.parse(text).atStartOfDay();
        return Duration.between(created, LocalDateTime.now(clock)).toMinutes() > Json.toDecimal(hours).multiply(BigDecimal.valueOf(MINUTES_PER_HOUR)).longValue();
    }

    private static final long MINUTES_PER_HOUR = 60;

    private LocalDateTime parseInstant(String text) {
        try {
            return OffsetDateTime.parse(text).atZoneSameInstant(clock.getZone()).toLocalDateTime();
        } catch (DateTimeParseException failure) {
            return LocalDateTime.parse(text);
        }
    }

    public ServiceOperationException fail(String code) {
        return ErrorCatalog.build(code, null, null, null);
    }

    /** One call to a dependency: activity logging, interpretation of the answer and compensation when it fails. */
    public RemoteResponse step(String key, String activity, Supplier<RemoteResponse> call, StepOutcome outcome) {
        ActivityLogger.inicioActividad(log, menTran, activity);
        RemoteResponse response;
        try {
            response = call.get();
        } catch (ServiceOperationException failure) {
            log.error(ERROR_PATTERN, menTran, activity, failure.getStatus().value(), failure.getSubType());
            outcome.compensation();
            throw failure;
        }
        if (!outcome.accepts(response.status())) {
            outcome.compensation();
            throw failureOf(activity, response, outcome);
        }
        responses.put(key, response.body());
        if (outcome.emptyListCode() != null && Json.list(response.body(), "data").isEmpty()) {
            outcome.compensation();
            throw ErrorCatalog.build(outcome.emptyListCode(), outcome.service(), response.message(), null);
        }
        ActivityLogger.finActividad(log, menTran, activity);
        return response;
    }

    private ServiceOperationException failureOf(String activity, RemoteResponse response, StepOutcome outcome) {
        log.error(ERROR_PATTERN, menTran, activity, response.status(), outcome.service());
        if (response.status() == HttpStatus.GATEWAY_TIMEOUT.value() || response.status() == HttpStatus.REQUEST_TIMEOUT.value()) {
            return ErrorCatalog.build(ErrorCatalog.TIMEOUT, outcome.service(), "HTTP " + response.status(), null);
        }
        if (response.status() == HttpStatus.SERVICE_UNAVAILABLE.value() || response.status() == HttpStatus.BAD_GATEWAY.value()) {
            return ErrorCatalog.build(ErrorCatalog.UNAVAILABLE, outcome.service(), "HTTP " + response.status(), null);
        }
        if (response.serverError()) {
            return ErrorCatalog.build(ErrorCatalog.INTERNAL, outcome.service(), "HTTP " + response.status(), null);
        }
        return ErrorCatalog.build(outcome.codeFor(response.status()), outcome.service(), response.message(), null);
    }

    /** Compensation and notification calls: their failure is logged and ignored, the flow outcome does not change. */
    public void bestEffort(String activity, Supplier<RemoteResponse> call) {
        try {
            ActivityLogger.inicioActividad(log, menTran, activity);
            RemoteResponse response = call.get();
            log.info("{} {} answered HTTP {}", menTran, activity, response.status());
            ActivityLogger.finActividad(log, menTran, activity);
        } catch (RuntimeException failure) {
            log.error("{} ERROR [{}] ignored: {}", menTran, activity, failure.getMessage());
        }
    }

    /** A calculation step: any failure is the declared code of the activity, or an internal error when none is declared. */
    public void compute(String activity, String code, Runnable compensation, Runnable calculation) {
        ActivityLogger.inicioActividad(log, menTran, activity);
        try {
            calculation.run();
        } catch (ServiceOperationException failure) {
            throw failure;
        } catch (RuntimeException failure) {
            log.error(ERROR_PATTERN, menTran, activity, failure.getClass().getSimpleName(), failure.getMessage());
            compensation.run();
            throw code == null ? ErrorCatalog.build(ErrorCatalog.INTERNAL, null, failure.getMessage(), null) : ErrorCatalog.build(code, null, failure.getMessage(), null);
        }
        ActivityLogger.finActividad(log, menTran, activity);
    }
}'''
