"""JUnit 5 / Mockito tests of the remote-orchestration pattern (no Spring context, no network, no database).

Tests are text templates finalized with the same import resolver as the main sources. They exercise the declared rules of the plan: validations per request
type, calculations, every flow (happy path and a compensation path), the error shape, the gateway status mapping and the settings cache.
"""
import remote_orchestration_java as rj

ASSERT = ['org.junit.jupiter.api.Assertions.' + n for n in ('assertEquals', 'assertNull', 'assertSame', 'assertThrows', 'assertTrue', 'assertFalse', 'assertNotNull')]
MOCKITO = ['org.mockito.Mockito.mock', 'org.mockito.Mockito.reset', 'org.mockito.Mockito.doThrow', 'org.mockito.Mockito.when', 'org.mockito.Mockito.verify', 'org.mockito.Mockito.never', 'org.mockito.Mockito.times', 'org.mockito.Mockito.inOrder',
           'org.mockito.ArgumentMatchers.any', 'org.mockito.ArgumentMatchers.eq']
MVC = ['org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post', 'org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath',
       'org.springframework.test.web.servlet.result.MockMvcResultMatchers.status']
MOCK_REST = ['org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo', 'org.springframework.test.web.client.match.MockRestRequestMatchers.method',
             'org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess', 'org.springframework.test.web.client.response.MockRestResponseCreators.withStatus',
             'org.springframework.test.web.client.response.MockRestResponseCreators.withException']
EXTRA = {'Test': 'org.junit.jupiter.api.Test', 'Mockito': 'org.mockito.Mockito', 'ArgumentCaptor': 'org.mockito.ArgumentCaptor', 'InOrder': 'org.mockito.InOrder',
         'JsonProcessingException': 'com.fasterxml.jackson.core.JsonProcessingException', 'ZoneOffset': 'java.time.ZoneOffset', 'MockMvc': 'org.springframework.test.web.servlet.MockMvc',
         'MockMvcBuilders': 'org.springframework.test.web.servlet.setup.MockMvcBuilders', 'MockRestServiceServer': 'org.springframework.test.web.client.MockRestServiceServer',
         'MockMvcRequestBuilders': 'org.springframework.test.web.servlet.request.MockMvcRequestBuilders', 'IOException': 'java.io.IOException',
         'SocketTimeoutException': 'java.net.SocketTimeoutException', 'Arrays': 'java.util.Arrays', 'MockHttpServletRequestBuilder': 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder',
         'MissingRequestHeaderException': 'org.springframework.web.bind.MissingRequestHeaderException', 'MethodParameter': 'org.springframework.core.MethodParameter'}

for _name in ('Fixtures', 'AgreementRequestValidatorTest', 'CalculationsTest', 'RulesTest', 'ErrorCatalogTest', 'SystemSettingsTest', 'RemoteGatewayTest', 'InstallmentSynchronizationTest',
              'AgreementServiceImplTest', 'GlobalExceptionHandlerTest', 'AgreementApiContractTest', 'FlowContextTest', 'PreFinancingFlowTest', 'FinancingFlowTest', 'PreRefinancingFlowTest',
              'RefinancingFlowTest', 'InstallmentCancellationFlowTest', 'InstallmentTransferFlowTest', 'ServiceCancellationFlowTest', 'BillingCycleChangeFlowTest'):
    pass

FIXTURES = '''/** Shared fixtures of the flow tests: fixed clock, forwarded headers and JSON answers written with single quotes. */
public final class Fixtures {
    public static final Clock CLOCK = Clock.fixed(Instant.parse("2026-11-06T12:00:00Z"), ZoneOffset.UTC);
    public static final ForwardedHeaders HEADERS = new ForwardedHeaders("tp", "app", "web", "1.0", "tx", "req", "user");
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private Fixtures() {
    }

    public static JsonNode json(String text) {
        try {
            return MAPPER.readTree(text.replace("'", "\\""));
        } catch (JsonProcessingException failure) {
            throw new IllegalStateException(failure);
        }
    }

    public static RemoteResponse answer(int status, String body) {
        return new RemoteResponse(status, json(body));
    }

    public static RemoteResponse ok(String body) {
        return answer(HttpStatus.OK.value(), body);
    }

    public static RemoteResponse created(String body) {
        return answer(HttpStatus.CREATED.value(), body);
    }

    public static AgreementRequest request(long type) {
        AgreementRequest request = new AgreementRequest();
        request.setRequestTypeId(type);
        return request;
    }

    public static FlowContext context(AgreementRequest request, Map<String, String> settings) {
        return new FlowContext(new RequestHeaders("tx", "user", "app"), HEADERS, request, CLOCK, "[tx] ", settings);
    }
}'''

VALIDATOR_TEST = '''class AgreementRequestValidatorTest {
    private static final long TYPE_PRE_FINANCING = 1L;
    private static final long TYPE_FINANCING = 2L;
    private static final long TYPE_REFINANCING = 4L;
    private static final long TYPE_CYCLE = 8L;
    private static final long OUT_OF_RANGE = 9L;
    private static final long CANCELLATION_OUT_OF_RANGE = 5L;
    private static final long TYPE_SERVICE_CANCELLATION = 7L;
    private static final String CYCLE_DAYS_AHEAD = "2026-11-07";
    private static final String CYCLE_TOO_FAR = "2026-12-07";

    private final AgreementRequestValidator validator = new AgreementRequestValidator(Fixtures.CLOCK);

    private AgreementRequest preFinancing() {
        AgreementRequest request = Fixtures.request(TYPE_PRE_FINANCING);
        request.setSaveRequest("S");
        request.setSaleOrder("OV1");
        request.setSaleChannel("CAC");
        request.setSalePoint("P1");
        request.setDocumentCodeId(1L);
        request.setDocumentNumber("123");
        request.setClientCode("C1");
        request.setIsClient("S");
        request.setProductCode("PR");
        request.setLine("999");
        request.setDebtAmount(new BigDecimal("1500"));
        request.setCreditLimit(new BigDecimal("300"));
        request.setFixedAmount(new BigDecimal("69.9"));
        request.setQuotesNumber(12L);
        request.setAmountInitialQuote(new BigDecimal("100"));
        return request;
    }

    private String subType(AgreementRequest request) {
        return assertThrows(ServiceOperationException.class, () -> validator.validate(request)).getSubType();
    }

    @Test
    void acceptsAValidPreFinancing() {
        validator.validate(preFinancing());
    }

    @Test
    void aMissingRequestTypeIsAMissingParameter() {
        assertEquals("IDF101", subType(new AgreementRequest()));
        assertThrows(ServiceOperationException.class, () -> validator.validate(null));
    }

    @Test
    void aRequestTypeOutOfRangeIsRejected() {
        assertEquals("IDF102", subType(Fixtures.request(OUT_OF_RANGE)));
    }

    @Test
    void aMissingMandatoryFieldIsReportedWithItsName() {
        AgreementRequest request = preFinancing();
        request.setSalePoint(" ");
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> validator.validate(request));
        assertEquals("IDF101", failure.getSubType());
        assertTrue(failure.getMessage().contains("salePoint"));
    }

    @Test
    void preFinancingValueRulesKeepTheirCodes() {
        AgreementRequest debt = preFinancing();
        debt.setDebtAmount(BigDecimal.ZERO);
        assertEquals("IDF103", subType(debt));
        AgreementRequest quotes = preFinancing();
        quotes.setQuotesNumber(0L);
        assertEquals("IDF104", subType(quotes));
        AgreementRequest credit = preFinancing();
        credit.setCreditLimit(BigDecimal.ZERO);
        assertEquals("IDF105", subType(credit));
        AgreementRequest client = preFinancing();
        client.setIsClient("X");
        assertEquals("IDF106", subType(client));
        AgreementRequest save = preFinancing();
        save.setSaveRequest("X");
        assertEquals("IDF107", subType(save));
    }

    @Test
    void theInitialQuoteRuleDependsOnTheChannel() {
        AgreementRequest negative = preFinancing();
        negative.setAmountInitialQuote(new BigDecimal("-1"));
        assertEquals("IDF108", subType(negative));
        AgreementRequest cad = preFinancing();
        cad.setSaleChannel("CAD");
        cad.setAmountInitialQuote(BigDecimal.ZERO);
        assertEquals("IDF109", subType(cad));
        cad.setAmountInitialQuote(BigDecimal.ONE);
        validator.validate(cad);
    }

    @Test
    void financingRequiresDifferentFieldsWhenTheProductIsDelivered() {
        AgreementRequest delivered = Fixtures.request(TYPE_FINANCING);
        delivered.setIsDelivered(1L);
        assertEquals("IDF101", subType(delivered));
        delivered.setAgreementCodeId(1L);
        delivered.setLine("999");
        delivered.setProductSerie("S1");
        delivered.setProofPaymentType("F");
        delivered.setProofPaymentNumber("1");
        validator.validate(delivered);
    }

    @Test
    void financingNotDeliveredNeedsTheRequestAndAValidCycleFormat() {
        AgreementRequest request = Fixtures.request(TYPE_FINANCING);
        request.setSaleOrder("OV1");
        request.setRequestCodeId(1L);
        request.setDocumentCodeId(1L);
        request.setDocumentNumber("123");
        request.setQuoteCycle("2026-13-45");
        request.setProductDescription("phone");
        request.setClientFullName("Ana");
        assertEquals("IDF113", subType(request));
        request.setQuoteCycle(CYCLE_DAYS_AHEAD);
        validator.validate(request);
    }

    @Test
    void refinancingChecksTheCycleAndTheInitialQuoteIndicator() {
        AgreementRequest request = Fixtures.request(TYPE_REFINANCING);
        request.setAgreementCodeId(1L);
        request.setRequestCodeId(1L);
        request.setQuoteCycle("2026-11-05");
        request.setIsInitialQuotePaid("S");
        assertEquals("IDF119", subType(request));
        request.setQuoteCycle("2026-11-06");
        validator.validate(request);
        request.setIsInitialQuotePaid("N");
        assertEquals("IDF135", subType(request));
    }

    @Test
    void serviceCancellationChecksTheCancellationType() {
        AgreementRequest request = Fixtures.request(TYPE_SERVICE_CANCELLATION);
        request.setAgreementCodeId(1L);
        request.setClientCode("C1");
        request.setCancellationTypeId(CANCELLATION_OUT_OF_RANGE);
        assertEquals("IDF114", subType(request));
        request.setCancellationTypeId(1L);
        validator.validate(request);
    }

    @Test
    void billingCycleChecksTheRangeOfTheCycle() {
        AgreementRequest request = Fixtures.request(TYPE_CYCLE);
        request.setAgreementCodeId(1L);
        request.setClientCode("C1");
        request.setQuoteCycle("2026-11-06");
        assertEquals("IDF120", subType(request));
        request.setQuoteCycle(CYCLE_TOO_FAR);
        assertEquals("IDF115", subType(request));
        request.setQuoteCycle(CYCLE_DAYS_AHEAD);
        validator.validate(request);
    }
}'''

CALCULATIONS_TEST = '''class CalculationsTest {
    private static final String STATE = "quoteStateCodeId";
    private static final String NUMBER = "quoteNumber";
    private static final String ISSUE_DATE = "quoteIssueDate";

    private List<JsonNode> quotes(String text) {
        return Json.list(Fixtures.json("{'data': " + text + "}"), "data");
    }

    @Test
    void quoteAmountIsRoundedHalfUpToTwoDecimals() {
        assertEquals(new BigDecimal("33.34"), Calculations.divideMoney(new BigDecimal("100.02"), 3L));
        assertEquals(new BigDecimal("33.33"), Calculations.divideMoney(new BigDecimal("99.99"), 3L));
        assertEquals(new BigDecimal("116.67"), Calculations.divideMoney(new BigDecimal("1400"), 12L));
    }

    @Test
    void percentageAndMinimumPercentageFollowTheLineState() {
        assertEquals(0, new BigDecimal("65").compareTo(Calculations.percentage(new BigDecimal("1300"), new BigDecimal("2000"))));
        assertEquals(new BigDecimal("10"), Calculations.minimumPercentage("1", "10", "20", "30"));
        assertEquals(new BigDecimal("30"), Calculations.minimumPercentage("3", "10", "20", "30"));
        assertThrows(IllegalArgumentException.class, () -> Calculations.minimumPercentage("9", "10", "20", "30"));
    }

    @Test
    void installmentsAreClassifiedByState() {
        List<JsonNode> all = quotes("[{'quoteStateCodeId': 2}, {'quoteStateCodeId': 3}, {'quoteStateCodeId': 1}]");
        assertEquals(1, Calculations.byState(all, 2).size());
        assertEquals(1, Calculations.byState(all, 3).size());
    }

    @Test
    void ineligibleInstallmentsIgnoreTheInitialQuote() {
        List<JsonNode> eligible = quotes("[{'quoteNumber': 0, 'quoteStateCodeId': 3}, {'quoteNumber': 1, 'quoteStateCodeId': 2}]");
        assertEquals(0, Calculations.hasIneligible(eligible, 1, 2, 0));
        List<JsonNode> paid = quotes("[{'quoteNumber': 1, 'quoteStateCodeId': 3}]");
        assertEquals(1, Calculations.hasIneligible(paid, 1, 2, 0));
    }

    @Test
    void cancellationTransformExportsTheInitialQuoteAndCancelsTheRest() {
        List<JsonNode> result = Calculations.cancellationTransform(quotes("[{'quoteCodeId': 1, 'quoteNumber': 0}, {'quoteCodeId': 2, 'quoteNumber': 1}]"), 6, 4);
        assertEquals("6", result.get(0).get(STATE).asText());
        assertEquals("4", result.get(1).get(STATE).asText());
        assertEquals(2, result.size());
    }

    @Test
    void serviceCancellationKeepsPendingOrNotifiedQuotesIssuedFromToday() {
        List<JsonNode> all = quotes("[{'quoteStateCodeId': 2, 'quoteIssueDate': '2026-11-05'}, {'quoteStateCodeId': 2, 'quoteIssueDate': '2026-11-06T00:00:00Z'},"
                + " {'quoteStateCodeId': 1, 'quoteIssueDate': '2026-12-06'}, {'quoteStateCodeId': 3, 'quoteIssueDate': '2026-12-06'}]");
        assertEquals(2, Calculations.filterForServiceCancellation(all, 1, 2, LocalDate.of(2026, 11, 6)).size());
    }

    @Test
    void synchronizationSelectsThePaidQuotesByNumberAndSkipsTheInitialQuote() {
        List<JsonNode> installments = quotes("[{'quoteCodeId': 10, 'quoteNumber': 0}, {'quoteCodeId': 11, 'quoteNumber': 1}, {'quoteCodeId': 12, 'quoteNumber': 2}]");
        List<JsonNode> collections = quotes("[{'quoteNumber': 0, 'quoteStateCodeId': 3}, {'quoteNumber': 1, 'quoteStateCodeId': 3, 'paymentDate': '2026-10-01', 'quoteAmount': 100},"
                + " {'quoteNumber': 2, 'quoteStateCodeId': 2}]");
        List<JsonNode> result = Calculations.filterPaidForSync(installments, collections, 3);
        assertEquals(1, result.size());
        assertEquals("11", result.get(0).get("quoteCodeId").asText());
        assertEquals("100", result.get(0).get("paymentAmount").asText());
        assertEquals("3", result.get(0).get(STATE).asText());
    }

    @Test
    void billingCycleDatesStartAtTheRequestedCycleAndAddOneMonthEach() {
        List<JsonNode> installments = quotes("[{'quoteCodeId': 2, 'quoteNumber': 2, 'quoteStateCodeId': 2}, {'quoteCodeId': 1, 'quoteNumber': 1, 'quoteStateCodeId': 2}]");
        List<JsonNode> result = Calculations.billingCycleDates(installments, "2026-12-31", "30");
        assertEquals("1", result.get(0).get("quoteCodeId").asText());
        assertEquals("2026-12-31", result.get(0).get(ISSUE_DATE).asText());
        assertEquals("2027-01-30", result.get(0).get("quoteExpirationDate").asText());
        assertEquals("2027-01-31", result.get(1).get(ISSUE_DATE).asText());
        assertEquals("1", result.get(0).get(NUMBER).asText());
    }

    @Test
    void sumsAndWithoutHelpers() {
        List<JsonNode> list = quotes("[{'quoteNumber': 0, 'quoteAmount': 10.5}, {'quoteNumber': 1, 'quoteAmount': 20}]");
        assertEquals(0, new BigDecimal("30.5").compareTo(Calculations.sumQuotes(list)));
        assertEquals(1, Calculations.without(list, NUMBER, 0).size());
    }
}'''

RULES_TEST = '''class RulesTest {
    @Test
    void numbersCompareByValueAndTextByEquality() {
        assertTrue(Rules.eq(new BigDecimal("2.0"), 2));
        assertTrue(Rules.eq(Fixtures.json("{'v': '2'}").get("v"), 2));
        assertTrue(Rules.eq("S", "S"));
        assertFalse(Rules.eq("S", "N"));
        assertFalse(Rules.eq(null, 1));
    }

    @Test
    void orderedComparisonsNeverMatchAbsentValues() {
        assertTrue(Rules.gt(BigDecimal.TEN, 1));
        assertTrue(Rules.ge(BigDecimal.TEN, BigDecimal.TEN));
        assertTrue(Rules.le(BigDecimal.ONE, BigDecimal.TEN));
        assertFalse(Rules.gt(null, 1));
        assertThrows(IllegalArgumentException.class, () -> Rules.ge(1, null));
    }

    @Test
    void emptyDetectsNullBlankAndJsonNull() {
        assertTrue(Rules.empty(null));
        assertTrue(Rules.empty(" "));
        assertTrue(Rules.empty(Fixtures.json("{'v': null}").get("v")));
        assertFalse(Rules.empty("x"));
        assertEquals(2, Rules.size(List.of(1, 2)));
        assertEquals(0, Rules.size(null));
    }

    @Test
    void addAndRoundWorkWithDecimals() {
        assertEquals(new BigDecimal("3.30"), Rules.add(new BigDecimal("1.1"), new BigDecimal("2.2")).setScale(2));
        assertEquals(new BigDecimal("65.43"), Rules.round2(new BigDecimal("65.4321")));
    }
}'''

ERROR_CATALOG_TEST = '''class ErrorCatalogTest {
    @Test
    void everyDeclaredCodeBuildsItsFailure() {
__CODES__
    }

    @Test
    void placeholdersAreReplaced() {
        ServiceOperationException timeout = ErrorCatalog.build(ErrorCatalog.TIMEOUT, "svc", "slow", null);
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, timeout.getStatus());
        assertTrue(timeout.getMessage().contains("svc"));
        assertTrue(timeout.getMessage().contains("slow"));
        assertTrue(ErrorCatalog.build("IDF101", null, null, "field").getMessage().contains("field"));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, ErrorCatalog.build(ErrorCatalog.UNAVAILABLE, "svc", "x", null).getStatus());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, ErrorCatalog.build(ErrorCatalog.INTERNAL, "svc", "x", null).getStatus());
    }
}'''

SETTINGS_TEST = '''class SystemSettingsTest {
    private static final long TTL = 3600000L;

    private final ParametersClient client = mock(ParametersClient.class);
    private final SystemSettings settings = new SystemSettings(client, Fixtures.CLOCK, TTL);

    @Test
    void readsTheParametersAndCachesThem() {
        when(client.list(any(), any(), any(), any())).thenReturn(Fixtures.ok("{'data': [{'clueParameter': 'DiasVencimientoCuota', 'data': '30'}]}"));
        assertEquals("30", settings.load(Fixtures.HEADERS).get("DiasVencimientoCuota"));
        settings.load(Fixtures.HEADERS);
        verify(client, times(1)).list(any(), any(), any(), any());
    }

    @Test
    void anUnreadableAnswerWithoutACopyIsTheConfigurationError() {
        when(client.list(any(), any(), any(), any())).thenReturn(Fixtures.answer(HttpStatus.NOT_FOUND.value(), "{}"));
        assertEquals("__CONFIG_CODE__", assertThrows(ServiceOperationException.class, () -> settings.load(Fixtures.HEADERS)).getSubType());
    }

    @Test
    void aServerErrorWithoutACopyIsAnInternalError() {
        when(client.list(any(), any(), any(), any())).thenReturn(Fixtures.answer(HttpStatus.INTERNAL_SERVER_ERROR.value(), "{}"));
        assertEquals(ErrorCatalog.INTERNAL, assertThrows(ServiceOperationException.class, () -> settings.load(Fixtures.HEADERS)).getSubType());
    }

    @Test
    void theLastValidCopyIsUsedWhenARefreshFails() {
        SystemSettings shortLived = new SystemSettings(client, Fixtures.CLOCK, 0L);
        when(client.list(any(), any(), any(), any())).thenReturn(Fixtures.ok("{'data': [{'clueParameter': 'k', 'data': 'v'}]}"))
                .thenThrow(ErrorCatalog.build(ErrorCatalog.UNAVAILABLE, "parameters", "down", null));
        assertEquals("v", shortLived.load(Fixtures.HEADERS).get("k"));
        assertEquals("v", shortLived.load(Fixtures.HEADERS).get("k"));
    }
}'''

GATEWAY_TEST = '''class RemoteGatewayTest {
    private static final String BASE = "http://dependency";

    private MockRestServiceServer server;
    private RemoteGateway gateway;

    private void bind() {
        RestClient.Builder builder = RestClient.builder().baseUrl(BASE);
        server = MockRestServiceServer.bindTo(builder).build();
        gateway = new RemoteGateway(builder.build(), new ObjectMapper(), "dependency");
    }

    @Test
    void answersWithTheStatusAndTheJsonBody() {
        bind();
        server.expect(requestTo(BASE + "/items/7?a=1")).andExpect(method(HttpMethod.GET)).andRespond(withSuccess("{\\"data\\": {\\"id\\": 7}}", MediaType.APPLICATION_JSON));
        RemoteResponse response = gateway.send(HttpMethod.GET, "/items/{id}", headers -> { }, Map.of("id", "7"), Map.of("a", "1"), null);
        assertEquals(HttpStatus.OK.value(), response.status());
        assertEquals("7", response.body().path("data").path("id").asText());
        server.verify();
    }

    @Test
    void httpErrorStatusesAreAnswersNotFailures() {
        bind();
        server.expect(requestTo(BASE + "/items")).andRespond(withStatus(HttpStatus.NOT_FOUND).contentType(MediaType.APPLICATION_JSON).body("{\\"message\\": \\"none\\"}"));
        RemoteResponse response = gateway.send(HttpMethod.POST, "/items", headers -> { }, Map.of(), Map.of(), Fixtures.json("{'a': 1}"));
        assertEquals(HttpStatus.NOT_FOUND.value(), response.status());
        assertEquals("none", response.message());
    }

    @Test
    void anUnreadableBodyBecomesANullBody() {
        bind();
        server.expect(requestTo(BASE + "/items")).andRespond(withStatus(HttpStatus.CREATED).body("not json"));
        assertTrue(gateway.send(HttpMethod.POST, "/items", headers -> { }, Map.of(), Map.of(), null).body().isNull());
    }

    @Test
    void connectionFailuresAreUnavailableAndTimeoutsAreTimeouts() {
        bind();
        server.expect(requestTo(BASE + "/items")).andRespond(withException(new IOException("refused")));
        ServiceOperationException unavailable = assertThrows(ServiceOperationException.class, () -> gateway.send(HttpMethod.GET, "/items", headers -> { }, Map.of(), Map.of(), null));
        assertEquals(ErrorCatalog.UNAVAILABLE, unavailable.getSubType());
        server.reset();
        server.expect(requestTo(BASE + "/items")).andRespond(withException(new SocketTimeoutException("slow")));
        ServiceOperationException timeout = assertThrows(ServiceOperationException.class, () -> gateway.send(HttpMethod.GET, "/items", headers -> { }, Map.of(), Map.of(), null));
        assertEquals(ErrorCatalog.TIMEOUT, timeout.getSubType());
    }
}'''

FLOW_CONTEXT_TEST = '''class FlowContextTest {
    private static final String KEY = "1";
    private static final String ACTIVITY = "A";

    private final FlowContext ctx = Fixtures.context(Fixtures.request(1L), Map.of("limit", "24"));

    private StepOutcome outcome(Runnable compensation) {
        return StepOutcome.of("svc").ok(HttpStatus.OK.value()).on(HttpStatus.NOT_FOUND.value(), "IDF386").otherwise("IDF387").compensate(compensation);
    }

    @Test
    void anAcceptedAnswerIsRememberedAndRead() {
        ctx.step(KEY, ACTIVITY, () -> Fixtures.ok("{'data': {'id': 5, 'quoteExperationDate': '2026-12-01'}}"), outcome(() -> { }));
        assertEquals("5", ctx.field(KEY, "id").asText());
        assertEquals("2026-12-01", ctx.field(KEY, "quoteExpirationDate").asText());
        assertTrue(ctx.field(KEY, "absent").isNull());
    }

    @Test
    void statusesMapToTheirCodeAndRunTheCompensationOnce() {
        Runnable compensation = mock(Runnable.class);
        ServiceOperationException notFound = assertThrows(ServiceOperationException.class,
                () -> ctx.step(KEY, ACTIVITY, () -> Fixtures.answer(HttpStatus.NOT_FOUND.value(), "{}"), outcome(compensation)));
        assertEquals("IDF386", notFound.getSubType());
        ServiceOperationException other = assertThrows(ServiceOperationException.class,
                () -> ctx.step(KEY, ACTIVITY, () -> Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"), outcome(compensation)));
        assertEquals("IDF387", other.getSubType());
        verify(compensation, times(2)).run();
    }

    @Test
    void serverSideStatusesAreTechnicalFailures() {
        assertEquals(ErrorCatalog.TIMEOUT, failureOf(HttpStatus.GATEWAY_TIMEOUT));
        assertEquals(ErrorCatalog.TIMEOUT, failureOf(HttpStatus.REQUEST_TIMEOUT));
        assertEquals(ErrorCatalog.UNAVAILABLE, failureOf(HttpStatus.SERVICE_UNAVAILABLE));
        assertEquals(ErrorCatalog.UNAVAILABLE, failureOf(HttpStatus.BAD_GATEWAY));
        assertEquals(ErrorCatalog.INTERNAL, failureOf(HttpStatus.INTERNAL_SERVER_ERROR));
    }

    private String failureOf(HttpStatus status) {
        return assertThrows(ServiceOperationException.class, () -> ctx.step(KEY, ACTIVITY, () -> Fixtures.answer(status.value(), "{}"), outcome(() -> { }))).getSubType();
    }

    @Test
    void aTechnicalFailureOfTheCallRunsTheCompensationAndIsRethrown() {
        Runnable compensation = mock(Runnable.class);
        ServiceOperationException failure = ErrorCatalog.build(ErrorCatalog.UNAVAILABLE, "svc", "down", null);
        ServiceOperationException thrown = assertThrows(ServiceOperationException.class, () -> ctx.step(KEY, ACTIVITY, () -> {
            throw failure;
        }, outcome(compensation)));
        assertSame(failure, thrown);
        verify(compensation).run();
    }

    @Test
    void anEmptyListAnswerIsTheDeclaredBusinessCode() {
        StepOutcome empty = StepOutcome.of("svc").ok(HttpStatus.OK.value()).otherwise("IDF387").emptyList("IDF386");
        assertEquals("IDF386", assertThrows(ServiceOperationException.class, () -> ctx.step(KEY, ACTIVITY, () -> Fixtures.ok("{'data': []}"), empty)).getSubType());
    }

    @Test
    void bestEffortCallsNeverFail() {
        ctx.bestEffort(ACTIVITY, () -> {
            throw new IllegalStateException("boom");
        });
        ctx.bestEffort(ACTIVITY, () -> Fixtures.answer(HttpStatus.INTERNAL_SERVER_ERROR.value(), "{}"));
    }

    @Test
    void calculationFailuresUseTheDeclaredCodeOrAnInternalError() {
        Runnable compensation = mock(Runnable.class);
        assertEquals("IDF465", assertThrows(ServiceOperationException.class, () -> ctx.compute(ACTIVITY, "IDF465", compensation, () -> {
            throw new IllegalArgumentException("x");
        })).getSubType());
        verify(compensation).run();
        assertEquals(ErrorCatalog.INTERNAL, assertThrows(ServiceOperationException.class, () -> ctx.compute(ACTIVITY, null, FlowContext.NO_COMPENSATION, () -> {
            throw new IllegalArgumentException("x");
        })).getSubType());
    }

    @Test
    void requestAgeIsComparedWithTheConfiguredHours() {
        assertTrue(ctx.hoursExceed("2026-11-05T10:00:00Z", "24"));
        assertFalse(ctx.hoursExceed("2026-11-06T10:00:00Z", "24"));
        assertTrue(ctx.hoursExceed("2026-11-04", "24"));
        assertThrows(IllegalArgumentException.class, () -> ctx.hoursExceed(null, "24"));
    }

    @Test
    void valuesAndDatesComeFromTheInjectedClock() {
        ctx.put(KEY, "list", List.of());
        assertEquals(LocalDate.of(2026, 11, 6), ctx.today());
        assertEquals("2026-11-06T12:00:00+0000", ctx.timestamp());
        assertEquals("tx", ctx.header("x-correlation-id"));
        assertEquals("24", ctx.setting("limit"));
        assertTrue(ctx.valueList(KEY, "list").isEmpty());
    }
}'''

SERVICE_TEST = '''class AgreementServiceImplTest {
    private final AgreementRequestValidator validator = mock(AgreementRequestValidator.class);
    private final SystemSettings settings = mock(SystemSettings.class);
    private final InstallmentSynchronization synchronization = mock(InstallmentSynchronization.class);
    private final AgreementFlow flow = mock(AgreementFlow.class);
    private final AgreementServiceImpl service = new AgreementServiceImpl(validator, settings, synchronization, List.of(flow), Fixtures.CLOCK);
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");

    private void flowOfType(long type, boolean synchronizes) {
        when(flow.requestTypeId()).thenReturn((int) type);
        when(flow.synchronizesInstallments()).thenReturn(synchronizes);
        when(settings.load(any())).thenReturn(Map.of());
        AgreementResponseData data = new AgreementResponseData();
        data.setRequestCodeId(1L);
        when(flow.execute(any())).thenReturn(data);
    }

    @Test
    void runsTheFlowOfTheRequestTypeAndAnswersTheContractEnvelope() {
        flowOfType(1L, false);
        AgreementResponse response = service.__METHOD__(headers, Fixtures.HEADERS, Fixtures.request(1L));
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertEquals("__SUCCESS__", response.getMessage());
        assertEquals(1L, response.getData().getRequestCodeId());
        verify(validator).validate(any());
        verify(synchronization, never()).run(any());
    }

    @Test
    void synchronizesTheInstallmentsBeforeTheFlowsThatNeedIt() {
        flowOfType(2L, true);
        service.__METHOD__(headers, Fixtures.HEADERS, Fixtures.request(2L));
        verify(synchronization).run(any());
    }

    @Test
    void aTypeWithoutFlowIsAnInvalidRequestType() {
        when(flow.requestTypeId()).thenReturn(1);
        when(settings.load(any())).thenReturn(Map.of());
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.__METHOD__(headers, Fixtures.HEADERS, Fixtures.request(2L)));
        assertEquals("IDF102", failure.getSubType());
    }

    @Test
    void validationFailuresStopBeforeAnyDependencyCall() {
        doThrow(ErrorCatalog.build("IDF101", null, null, "x")).when(validator).validate(any());
        assertThrows(ServiceOperationException.class, () -> service.__METHOD__(headers, Fixtures.HEADERS, Fixtures.request(1L)));
        verify(settings, never()).load(any());
    }
}'''

HANDLER_TEST = '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    void businessFailuresKeepTheirContractIdentity() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ErrorCatalog.build("IDF301", null, null, null));
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        ErrorResponse body = response.getBody();
        assertEquals("BAD_REQUEST", body.getStatus());
        assertEquals("IDF301", body.getSubType());
        assertEquals("InvalidFinancingStateException", body.getType());
        assertEquals(ErrorCatalog.MESSAGE, body.getMessage());
        assertEquals(HttpStatus.BAD_REQUEST.value(), body.getCode());
    }

    @Test
    void undeclaredStatusesBecomeInternalErrors() {
        ServiceOperationException unknown = new ServiceOperationException(HttpStatus.FORBIDDEN, "X", "Y", "z");
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), handler.operationFailure(unknown).getStatusCode().value());
    }

    @Test
    void unexpectedFailuresAreInternalErrorsWithTheCause() {
        ResponseEntity<ErrorResponse> response = handler.unexpectedFailure(new IllegalStateException("boom"));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), response.getStatusCode().value());
        assertEquals("IDT3", response.getBody().getSubType());
        assertTrue(response.getBody().getDetail().contains("boom"));
    }

    @Test
    void aMissingHeaderIsAMissingParameter() throws NoSuchMethodException {
        MethodParameter parameter = new MethodParameter(GlobalExceptionHandlerTest.class.getDeclaredMethod("aMissingHeaderIsAMissingParameter"), -1);
        ResponseEntity<ErrorResponse> response = handler.missingHeader(new MissingRequestHeaderException("x-user-id", parameter));
        assertEquals("IDF101", response.getBody().getSubType());
        assertTrue(response.getBody().getDetail().contains("x-user-id"));
    }
}'''

CONTRACT_TEST = '''class AgreementApiContractTest {
    private static final String PATH = "__PATH__";

    private final AgreementService service = mock(AgreementService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new AgreementController(service)).setControllerAdvice(new GlobalExceptionHandler()).build();

    private MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder) {
        return builder.header("traceparent", "t").header("x-app-id", "app").header("x-channel", "web").header("x-client-version-id", "1")
                .header("x-correlation-id", "tx").header("x-request-id", "req").header("x-user-id", "user");
    }

    @Test
    void postReturnsTheEnvelopeOfTheContract() throws Exception {
        AgreementResponseData data = new AgreementResponseData();
        data.setRequestCodeId(1001L);
        AgreementResponse response = new AgreementResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage("__SUCCESS__");
        response.setData(data);
        when(service.__METHOD__(any(), any(), any())).thenReturn(response);
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("{\\"requestTypeId\\": 1}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.code").value(HttpStatus.OK.value())).andExpect(jsonPath("$.data.requestCodeId").value(1001));
    }

    @Test
    void aMissingHeaderIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.subType").value("IDF101")).andExpect(jsonPath("$.message").value(ErrorCatalog.MESSAGE));
    }

    @Test
    void aMalformedBodyIsABadRequest() throws Exception {
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("not-json"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.subType").value("IDF101"));
    }

    @Test
    void failuresKeepTheirDeclaredStatusAndShape() throws Exception {
        when(service.__METHOD__(any(), any(), any())).thenThrow(ErrorCatalog.build("IDF386", null, "none", null));
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.subType").value("IDF386")).andExpect(jsonPath("$.status").value("NOT_FOUND"));
        reset(service);
        when(service.__METHOD__(any(), any(), any())).thenThrow(ErrorCatalog.build(ErrorCatalog.TIMEOUT, "svc", "slow", null));
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isGatewayTimeout()).andExpect(jsonPath("$.subType").value("IDT1"));
    }
}'''
