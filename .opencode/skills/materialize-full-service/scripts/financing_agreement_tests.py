"""JUnit 5 / Mockito tests of the financingAgreement service (checkstyle D-014 applies to tests: no magic numbers outside constants)."""
import dom_cpe_request_java as dj
import financing_agreement_java as fj  # noqa: F401  (registers the service classes)

dj.EXTERNAL.update({'Executable': 'org.junit.jupiter.api.function.Executable', 'MockHttpServletRequestBuilder': 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder',
                    'ArgumentCaptor': 'org.mockito.ArgumentCaptor', 'InOrder': 'org.mockito.InOrder', 'Sort': 'org.springframework.data.domain.Sort',
                    'Specification': 'org.springframework.data.jpa.domain.Specification', 'BeforeEach': 'org.junit.jupiter.api.BeforeEach'})

ASSERT = ['org.junit.jupiter.api.Assertions.' + n for n in ('assertEquals', 'assertNull', 'assertSame', 'assertThrows', 'assertTrue', 'assertNotNull', 'assertFalse')]
MVC_STATICS = ['org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get', 'org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch',
               'org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post', 'org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete',
               'org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath', 'org.springframework.test.web.servlet.result.MockMvcResultMatchers.status']

VALIDATOR_TEST = '''class FinancingValidatorTest {
    private static final Instant NOW = Instant.parse("2026-11-06T15:00:00Z");
    private static final LocalDateTime SAP_LOCAL = LocalDateTime.of(2026, 9, 19, 15, 30);
    private static final LocalDate CYCLE = LocalDate.of(2026, 9, 19);
    private static final LocalDate BEGIN = LocalDate.of(2026, 10, 1);
    private static final LocalDate WITHIN_MONTH = LocalDate.of(2026, 11, 1);
    private static final LocalDate BEYOND_MONTH = LocalDate.of(2026, 11, 2);
    private static final Long CLIENT = 99201L;
    private static final int PERIOD = 12;
    private static final String TYPES = "2,4,6";
    private static final List<Integer> TYPE_LIST = List.of(2, 4, 6);

    private final FinancingValidator validator = new FinancingValidator(Clock.fixed(NOW, ZoneOffset.UTC));

    private CreateFinancingRequest minimal() {
        CreateFinancingRequest request = new CreateFinancingRequest();
        request.setRequestCodeId(1);
        request.setRequestTypeId(2);
        return request;
    }

    private void assertFailure(String subType, Executable executable) {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, executable);
        assertEquals(subType, failure.getSubType());
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
    }

    @Test
    void acceptsMinimalCreateRequest() {
        FinancingDates dates = validator.createFinancing(minimal());
        assertNull(dates.quoteCycle());
        assertNull(dates.sapSentDate());
    }

    @Test
    void requiresRequestCodeAndRequestType() {
        assertFailure("IDF101", () -> validator.createFinancing(null));
        CreateFinancingRequest noCode = minimal();
        noCode.setRequestCodeId(null);
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> validator.createFinancing(noCode));
        assertTrue(failure.getDetail().contains("requestCodeId"));
        CreateFinancingRequest noType = minimal();
        noType.setRequestTypeId(null);
        assertFailure("IDF101", () -> validator.createFinancing(noType));
    }

    @Test
    void restrictsIsClientToYesOrNo() {
        CreateFinancingRequest request = minimal();
        request.setIsClient("S");
        validator.createFinancing(request);
        request.setIsClient("N");
        validator.createFinancing(request);
        request.setIsClient("X");
        assertFailure("IDF106", () -> validator.createFinancing(request));
    }

    @Test
    void validatesTheQuoteCycleFormat() {
        CreateFinancingRequest request = minimal();
        request.setQuoteCycle("2026-09-19");
        assertEquals(CYCLE, validator.createFinancing(request).quoteCycle());
        request.setQuoteCycle("19/09/2026");
        assertFailure("IDF113", () -> validator.createFinancing(request));
        UpdateFinancingRequest update = new UpdateFinancingRequest();
        update.setAgreementCodeId(1L);
        update.setQuoteCycle("2026-13-01");
        assertFailure("IDF113", () -> validator.updateFinancing(update));
    }

    @Test
    void convertsTheSapSentDateToTheLocalZone() {
        CreateFinancingRequest request = minimal();
        request.setSapSentDate("2026-09-19T10:30:00-0500");
        assertEquals(SAP_LOCAL, validator.createFinancing(request).sapSentDate());
        request.setSapSentDate("2026-09-19T10:30:00-05:00");
        assertEquals(SAP_LOCAL, validator.createFinancing(request).sapSentDate());
        request.setSapSentDate("not a date");
        assertFailure("IDF101", () -> validator.createFinancing(request));
    }

    @Test
    void requiresTheAgreementCodeToUpdate() {
        assertFailure("IDF101", () -> validator.updateFinancing(new UpdateFinancingRequest()));
        assertFailure("IDF101", () -> validator.agreementCodeId(null));
        assertEquals(CLIENT, validator.agreementCodeId(CLIENT));
    }

    @Test
    void validatesTheSearchDateRange() {
        assertFailure("IDF101", () -> validator.search(null, "2026-11-01", null, null, null, null, null, null, null));
        assertFailure("IDF101", () -> validator.search("bad", "2026-11-01", null, null, null, null, null, null, null));
        assertFailure("IDF126", () -> validator.search("2026-11-02", "2026-11-01", null, null, null, null, null, null, null));
        SearchCriteria criteria = validator.search("2026-10-01", "2026-11-01", 1, " ", null, "CAC", null, 2, 1);
        assertEquals(BEGIN, criteria.dateBegin());
        assertEquals(WITHIN_MONTH, criteria.dateEnd());
        assertNull(criteria.documentNumber());
        assertEquals("CAC", criteria.saleChannel());
    }

    @Test
    void limitsTheSearchRangeToOneMonthUnlessDocumentOrOrderIsInformed() {
        assertFailure("IDF127", () -> validator.search("2026-10-01", "2026-11-02", null, null, null, null, null, null, null));
        assertEquals(BEYOND_MONTH, validator.search("2026-10-01", "2026-11-02", null, "42678935", null, null, null, null, null).dateEnd());
        assertEquals(BEYOND_MONTH, validator.search("2026-10-01", "2026-11-02", null, null, "ORD-1", null, null, null, null).dateEnd());
    }

    @Test
    void validatesTheRefinancingParameters() {
        assertFailure("IDF101", () -> validator.refinancings(null, "12", "2026-11-01"));
        assertFailure("IDF101", () -> validator.refinancings(CLIENT, " ", "2026-11-01"));
        assertFailure("IDF130", () -> validator.refinancings(CLIENT, "12", "01-11-2026"));
        assertFailure("IDF101", () -> validator.refinancings(CLIENT, "twelve", "2026-11-01"));
        RefinancingQuery query = validator.refinancings(CLIENT, "12", "2026-11-01");
        assertEquals("99201", query.clientCode());
        assertEquals(PERIOD, query.periodMonths());
        assertEquals(WITHIN_MONTH, query.processDate());
    }

    @Test
    void validatesTheNotificationWindow() {
        assertFailure("IDF101", () -> validator.notificationCandidates(null, "2026-09-23T09:47:29-0500", "2026-09-23T10:47:29-0500"));
        assertFailure("IDF101", () -> validator.notificationCandidates("a,b", "2026-09-23T09:47:29-0500", "2026-09-23T10:47:29-0500"));
        assertFailure("IDF131", () -> validator.notificationCandidates(TYPES, "yesterday", "2026-09-23T10:47:29-0500"));
        assertFailure("IDF126", () -> validator.notificationCandidates(TYPES, "2026-09-23T11:47:29-0500", "2026-09-23T10:47:29-0500"));
        NotificationQuery query = validator.notificationCandidates(TYPES, "2026-09-23T09:47:29-0500", "2026-09-23T10:47:29-0500");
        assertEquals(TYPE_LIST, query.requestTypeIds());
        assertTrue(query.dateBegin().isBefore(query.dateEnd()));
    }
}'''

MAPPER_TEST = '''class FinancingMapperTest {
    private static final Instant NOW = Instant.parse("2026-11-06T15:00:00Z");
    private static final LocalDateTime STAMP = LocalDateTime.of(2026, 9, 19, 10, 30);
    private static final LocalDate CYCLE = LocalDate.of(2026, 9, 19);
    private static final Long ID = 5001L;
    private static final Double AMOUNT = 1250.5;
    private static final long COUNT = 3L;
    private static final Integer UPDATED_STATE = 3;

    private final FinancingMapper mapper = new FinancingMapper(Clock.fixed(NOW, ZoneOffset.UTC));

    private FinancingEntity row() {
        FinancingEntity row = new FinancingEntity();
        row.setAgreementCodeId(ID);
        row.setSystem("CRM_POS");
        row.setSaleOrder("ORD-1");
        row.setDebtAmount(BigDecimal.valueOf(AMOUNT));
        row.setQuoteCycle(CYCLE);
        row.setCreatedBy("user");
        row.setCreatedAt(STAMP);
        row.setFinancingStateCodeId(2);
        row.setRequestTypeId(1);
        return row;
    }

    @Test
    void mapsTheCreateRequestToTheEntity() {
        CreateFinancingRequest request = new CreateFinancingRequest();
        request.setSaleOrder("ORD-1");
        request.setDebtAmount(AMOUNT);
        request.setRequestTypeId(2);
        FinancingEntity entity = mapper.toEntity(request, new FinancingDates(CYCLE, STAMP), "CRM_POS", "user", STAMP);
        assertEquals("CRM_POS", entity.getSystem());
        assertEquals("ORD-1", entity.getSaleOrder());
        assertEquals(BigDecimal.valueOf(AMOUNT), entity.getDebtAmount());
        assertEquals(CYCLE, entity.getQuoteCycle());
        assertEquals(STAMP, entity.getSapSentDate());
        assertEquals(2, entity.getRequestTypeId());
        assertEquals("user", entity.getCreatedBy());
        assertEquals(STAMP, entity.getCreatedAt());
        assertNull(entity.getUpdatedBy());
    }

    @Test
    void updatesOnlyTheInformedFields() {
        FinancingEntity entity = row();
        entity.setImei("IMEI-1");
        UpdateFinancingRequest request = new UpdateFinancingRequest();
        request.setAgreementCodeId(ID);
        request.setFinancingStateCodeId(UPDATED_STATE);
        request.setReasonChange("");
        mapper.applyUpdate(entity, request, new FinancingDates(null, null), "admin", STAMP);
        assertEquals(UPDATED_STATE, entity.getFinancingStateCodeId());
        assertEquals("", entity.getReasonChange());
        assertEquals("IMEI-1", entity.getImei());
        assertEquals(CYCLE, entity.getQuoteCycle());
        assertEquals("admin", entity.getUpdatedBy());
        assertEquals(STAMP, entity.getUpdatedAt());
        assertEquals("user", entity.getCreatedBy());
    }

    @Test
    void copiesTheFinancingToTheHistory() {
        FinancingHistoryEntity history = mapper.toHistory(row());
        assertEquals(ID, history.getAgreementCodeId());
        assertNull(history.getHistoryId());
        assertEquals("CRM_POS", history.getSystem());
        assertEquals("ORD-1", history.getSaleOrder());
        assertEquals(BigDecimal.valueOf(AMOUNT), history.getDebtAmount());
        assertEquals(STAMP, history.getCreatedAt());
    }

    @Test
    void buildsTheEnvelopesOfTheWriteOperations() {
        CreateFinancingResponse created = mapper.createResponse(ID);
        assertEquals(HttpStatus.CREATED.value(), created.getCode());
        assertEquals(ID, created.getData().getAgreementCodeId());
        UpdateFinancingResponse updated = mapper.updateResponse();
        assertEquals(HttpStatus.OK.value(), updated.getCode());
        assertNull(updated.getData());
        assertNull(mapper.deleteResponse().getData());
    }

    @Test
    void formatsTheDetailResponse() {
        GetFinancingResponse response = mapper.getResponse(row());
        assertEquals(ID, response.getData().getAgreementCodeId());
        assertEquals(AMOUNT, response.getData().getDebtAmount());
        assertEquals("2026-09-19", response.getData().getQuoteCycle());
        assertEquals("2026-09-19T10:30:00+0000", response.getData().getCreatedAt());
        assertNull(response.getData().getUpdatedAt());
    }

    @Test
    void addsTheCatalogDescriptionsToTheSearchRows() {
        SearchFinancingResponse response = mapper.searchResponse(List.of(row()), Map.of(2, "CONFIRMADA"), Map.of());
        assertEquals(1, response.getData().size());
        assertEquals("CONFIRMADA", response.getData().get(0).getFinancingStateDescription());
        assertNull(response.getData().get(0).getRequestTypeDescription());
        assertEquals(AMOUNT, response.getData().get(0).getDebtAmount());
    }

    @Test
    void mapsTheStateCatalog() {
        FinancingStateEntity state = new FinancingStateEntity();
        state.setFinancingStateCodeId(1);
        state.setFinancingStateDescription("SOLICITADA");
        state.setState(1);
        state.setCreatedAt(STAMP);
        StateFinancingResponse response = mapper.stateResponse(List.of(state));
        assertEquals("SOLICITADA", response.getData().get(0).getFinancingStateDescription());
        assertEquals(1, response.getData().get(0).getState());
        assertEquals("2026-09-19T10:30:00+0000", response.getData().get(0).getCreatedAt());
    }

    @Test
    void mapsTheRefinancingCounts() {
        RefinancingsAgreementResponse response = mapper.refinancingsResponse(1L, COUNT);
        assertEquals(1L, response.getData().getActiveRefinancingCount());
        assertEquals(COUNT, response.getData().getCompletedRefinancingCountInPeriod());
    }

    @Test
    void marksTheErrorCandidatesAsRetries() {
        NotificationFinancingResponse response = mapper.notificationResponse(List.of(row()), List.of(row()));
        assertEquals(2, response.getData().size());
        assertEquals(0, response.getData().get(0).getIsRetry());
        assertEquals(1, response.getData().get(1).getIsRetry());
        assertEquals(ID, response.getData().get(1).getAgreementCodeId());
    }
}'''

SERVICE_TEST = '''class FinancingServiceImplTest {
    private static final Instant NOW = Instant.parse("2026-11-06T15:00:00Z");
    private static final Long ID = 5001L;
    private static final Long CLIENT = 99201L;
    private static final Integer CONFIRMED = 2;
    private static final Integer PENDING = 1;
    private static final Integer OAC_ERROR = 7;
    private static final Integer REFINANCING = 3;
    private static final Integer COMPLETED = 5;
    private static final String TYPES = "2,4";
    private static final String BEGIN = "2026-09-23T09:47:29-0500";
    private static final String END = "2026-09-23T10:47:29-0500";
    private static final LocalDate FROM_DATE = LocalDate.of(2025, 11, 1);
    private static final LocalDate TO_DATE = LocalDate.of(2026, 11, 2);

    private final FinancingRepository repository = Mockito.mock(FinancingRepository.class);
    private final FinancingHistoryRepository historyRepository = Mockito.mock(FinancingHistoryRepository.class);
    private final FinancingStateRepository stateRepository = Mockito.mock(FinancingStateRepository.class);
    private final RequestTypeRepository requestTypeRepository = Mockito.mock(RequestTypeRepository.class);
    private final InstallmentRepository installmentRepository = Mockito.mock(InstallmentRepository.class);
    private final InstallmentHistoryRepository installmentHistoryRepository = Mockito.mock(InstallmentHistoryRepository.class);
    private final Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
    private final TransactionTemplate transactions = new TransactionTemplate(Mockito.mock(PlatformTransactionManager.class));
    private final FinancingServiceImpl service = new FinancingServiceImpl(repository, historyRepository, stateRepository, requestTypeRepository, installmentRepository,
            installmentHistoryRepository, new FinancingMapper(clock), new FinancingValidator(clock),
            new FinancingProperties(CONFIRMED, PENDING, OAC_ERROR, REFINANCING, CONFIRMED, COMPLETED), new PersistenceExceptionTranslator(), transactions, clock);
    private final RequestHeaders headers = new RequestHeaders("tx-1", "user", "CRM_POS");

    private FinancingEntity stored() {
        FinancingEntity row = new FinancingEntity();
        row.setAgreementCodeId(ID);
        row.setFinancingStateCodeId(1);
        row.setImei("IMEI-1");
        row.setRequestTypeId(1);
        return row;
    }

    private CreateFinancingRequest createRequest() {
        CreateFinancingRequest request = new CreateFinancingRequest();
        request.setRequestCodeId(1);
        request.setRequestTypeId(2);
        request.setSaleOrder("ORD-1");
        return request;
    }

    private void assertFailure(HttpStatus status, String subType, Executable executable) {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, executable);
        assertEquals(status, failure.getStatus());
        assertEquals(subType, failure.getSubType());
    }

    @Test
    void createsTheFinancingAndItsHistory() {
        Mockito.when(repository.saveAndFlush(ArgumentMatchers.any(FinancingEntity.class))).thenAnswer(invocation -> {
            FinancingEntity entity = invocation.getArgument(0);
            entity.setAgreementCodeId(ID);
            return entity;
        });
        CreateFinancingResponse response = service.createFinancing(headers, createRequest());
        assertEquals(HttpStatus.CREATED.value(), response.getCode());
        assertEquals(ID, response.getData().getAgreementCodeId());
        ArgumentCaptor<FinancingEntity> saved = ArgumentCaptor.forClass(FinancingEntity.class);
        Mockito.verify(repository).saveAndFlush(saved.capture());
        assertEquals("CRM_POS", saved.getValue().getSystem());
        assertEquals("user", saved.getValue().getCreatedBy());
        assertEquals(LocalDateTime.ofInstant(NOW, ZoneOffset.UTC), saved.getValue().getCreatedAt());
        ArgumentCaptor<FinancingHistoryEntity> history = ArgumentCaptor.forClass(FinancingHistoryEntity.class);
        Mockito.verify(historyRepository).saveAndFlush(history.capture());
        assertEquals(ID, history.getValue().getAgreementCodeId());
        assertEquals("ORD-1", history.getValue().getSaleOrder());
    }

    @Test
    void rejectsAnInvalidCreateRequestBeforeAnyWrite() {
        CreateFinancingRequest invalid = createRequest();
        invalid.setIsClient("X");
        assertFailure(HttpStatus.BAD_REQUEST, "IDF106", () -> service.createFinancing(headers, invalid));
        Mockito.verifyNoInteractions(repository, historyRepository);
    }

    @Test
    void translatesDataAccessFailuresOfTheInsert() {
        Mockito.when(repository.saveAndFlush(ArgumentMatchers.any(FinancingEntity.class))).thenThrow(new QueryTimeoutException("timeout"));
        assertFailure(HttpStatus.GATEWAY_TIMEOUT, "IDT1", () -> service.createFinancing(headers, createRequest()));
        Mockito.verifyNoInteractions(historyRepository);
        Mockito.when(repository.saveAndFlush(ArgumentMatchers.any(FinancingEntity.class))).thenThrow(new DataIntegrityViolationException("constraint"));
        assertFailure(HttpStatus.INTERNAL_SERVER_ERROR, "IDT3", () -> service.createFinancing(headers, createRequest()));
    }

    @Test
    void updatesTheInformedFieldsAndRecordsTheHistory() {
        FinancingEntity current = stored();
        Mockito.when(repository.findById(ID)).thenReturn(Optional.of(current));
        Mockito.when(repository.saveAndFlush(current)).thenReturn(current);
        UpdateFinancingRequest request = new UpdateFinancingRequest();
        request.setAgreementCodeId(ID);
        request.setFinancingStateCodeId(CONFIRMED);
        UpdateFinancingResponse response = service.updateFinancing(headers, request);
        assertEquals(HttpStatus.OK.value(), response.getCode());
        assertEquals(CONFIRMED, current.getFinancingStateCodeId());
        assertEquals("IMEI-1", current.getImei());
        assertEquals("user", current.getUpdatedBy());
        ArgumentCaptor<FinancingHistoryEntity> history = ArgumentCaptor.forClass(FinancingHistoryEntity.class);
        Mockito.verify(historyRepository).saveAndFlush(history.capture());
        assertEquals(CONFIRMED, history.getValue().getFinancingStateCodeId());
        assertEquals("user", history.getValue().getUpdatedBy());
    }

    @Test
    void rejectsTheUpdateOfAnUnknownFinancing() {
        Mockito.when(repository.findById(ID)).thenReturn(Optional.empty());
        UpdateFinancingRequest request = new UpdateFinancingRequest();
        request.setAgreementCodeId(ID);
        assertFailure(HttpStatus.BAD_REQUEST, "IDF101", () -> service.updateFinancing(headers, request));
        Mockito.verifyNoInteractions(historyRepository);
    }

    @Test
    void deletesTheChildrenBeforeTheFinancing() {
        DeleteFinancingResponse response = service.deleteFinancing(headers, ID);
        assertEquals(HttpStatus.OK.value(), response.getCode());
        InOrder order = Mockito.inOrder(installmentHistoryRepository, installmentRepository, historyRepository, repository);
        order.verify(installmentHistoryRepository).deleteByAgreementCode(ID);
        order.verify(installmentRepository).deleteByAgreementCode(ID);
        order.verify(historyRepository).deleteByAgreementCode(ID);
        order.verify(repository).deleteByAgreementCode(ID);
        assertFailure(HttpStatus.BAD_REQUEST, "IDF101", () -> service.deleteFinancing(headers, null));
    }

    @Test
    void returnsTheFinancingOrNotFound() {
        Mockito.when(repository.findById(ID)).thenReturn(Optional.of(stored()));
        assertEquals(ID, service.getFinancing(headers, ID).getData().getAgreementCodeId());
        Mockito.when(repository.findById(ID)).thenReturn(Optional.empty());
        assertFailure(HttpStatus.NOT_FOUND, "IDF302", () -> service.getFinancing(headers, ID));
    }

    @Test
    void searchesWithTheCatalogDescriptions() {
        FinancingEntity row = stored();
        Mockito.when(repository.findAll(ArgumentMatchers.<Specification<FinancingEntity>>any(), ArgumentMatchers.any(Sort.class))).thenReturn(List.of(row));
        FinancingStateEntity state = new FinancingStateEntity();
        state.setFinancingStateCodeId(1);
        state.setFinancingStateDescription("SOLICITADA");
        Mockito.when(stateRepository.findAllById(List.of(1))).thenReturn(List.of(state));
        SearchFinancingResponse response = service.searchFinancing(headers, "2026-10-01", "2026-10-15", null, null, null, null, null, null, 1);
        assertEquals(1, response.getData().size());
        assertEquals("SOLICITADA", response.getData().get(0).getFinancingStateDescription());
    }

    @Test
    void reportsNotFoundWhenTheSearchHasNoRows() {
        Mockito.when(repository.findAll(ArgumentMatchers.<Specification<FinancingEntity>>any(), ArgumentMatchers.any(Sort.class))).thenReturn(List.of());
        assertFailure(HttpStatus.NOT_FOUND, "IDF302", () -> service.searchFinancing(headers, "2026-10-01", "2026-10-15", null, null, null, null, null, null, null));
        assertFailure(HttpStatus.BAD_REQUEST, "IDF127", () -> service.searchFinancing(headers, "2026-09-01", "2026-10-15", null, null, null, null, null, null, null));
    }

    @Test
    void listsTheStateCatalogOrNotFound() {
        FinancingStateEntity state = new FinancingStateEntity();
        state.setFinancingStateCodeId(1);
        Mockito.when(stateRepository.findAll(ArgumentMatchers.any(Sort.class))).thenReturn(List.of(state));
        assertEquals(1, service.stateFinancing(headers).getData().size());
        Mockito.when(stateRepository.findAll(ArgumentMatchers.any(Sort.class))).thenReturn(List.of());
        assertFailure(HttpStatus.NOT_FOUND, "IDF302", () -> service.stateFinancing(headers));
    }

    @Test
    void countsTheRefinancingsWithTheConfiguredCodes() {
        Mockito.when(repository.countByClientCodeAndRequestTypeIdAndFinancingStateCodeId("99201", REFINANCING, CONFIRMED)).thenReturn(1L);
        Mockito.when(repository.countInWindow(ArgumentMatchers.eq("99201"), ArgumentMatchers.eq(REFINANCING), ArgumentMatchers.eq(COMPLETED),
                ArgumentMatchers.any(LocalDateTime.class), ArgumentMatchers.any(LocalDateTime.class))).thenReturn(2L);
        RefinancingsAgreementResponse response = service.refinancingsAgreement(headers, CLIENT, "12", "2026-11-01");
        assertEquals(1L, response.getData().getActiveRefinancingCount());
        assertEquals(2L, response.getData().getCompletedRefinancingCountInPeriod());
        ArgumentCaptor<LocalDateTime> from = ArgumentCaptor.forClass(LocalDateTime.class);
        ArgumentCaptor<LocalDateTime> to = ArgumentCaptor.forClass(LocalDateTime.class);
        Mockito.verify(repository).countInWindow(ArgumentMatchers.eq("99201"), ArgumentMatchers.eq(REFINANCING), ArgumentMatchers.eq(COMPLETED), from.capture(), to.capture());
        assertEquals(FROM_DATE.atStartOfDay(), from.getValue());
        assertEquals(TO_DATE.atStartOfDay(), to.getValue());
    }

    @Test
    void consolidatesTheNotificationCandidates() {
        FinancingEntity pending = stored();
        FinancingEntity failed = stored();
        failed.setAgreementCodeId(ID + 1);
        Mockito.when(repository.findWithInstallmentStateBetween(ArgumentMatchers.eq(CONFIRMED), ArgumentMatchers.eq(List.of(2, 4)), ArgumentMatchers.eq(PENDING),
                ArgumentMatchers.any(LocalDateTime.class), ArgumentMatchers.any(LocalDateTime.class))).thenReturn(List.of(pending));
        Mockito.when(repository.findWithInstallmentState(CONFIRMED, List.of(2, 4), OAC_ERROR)).thenReturn(List.of(failed));
        NotificationFinancingResponse response = service.notificationFinancing(headers, TYPES, BEGIN, END);
        assertEquals(2, response.getData().size());
        assertEquals(0, response.getData().get(0).getIsRetry());
        assertEquals(1, response.getData().get(1).getIsRetry());
        assertEquals(ID + 1, response.getData().get(1).getAgreementCodeId());
    }

    @Test
    void reportsNotFoundWhenAnyNotificationQueryReturnsNothing() {
        Mockito.when(repository.findWithInstallmentStateBetween(ArgumentMatchers.eq(CONFIRMED), ArgumentMatchers.any(), ArgumentMatchers.eq(PENDING),
                ArgumentMatchers.any(LocalDateTime.class), ArgumentMatchers.any(LocalDateTime.class))).thenReturn(List.of());
        assertFailure(HttpStatus.NOT_FOUND, "IDF302", () -> service.notificationFinancing(headers, TYPES, BEGIN, END));
        Mockito.verify(repository, Mockito.never()).findWithInstallmentState(ArgumentMatchers.any(), ArgumentMatchers.any(), ArgumentMatchers.any());
    }
}'''

CONTROLLER_TEST = '''class FinancingApiContractTest {
    private static final Long ID = 5001L;
    private static final String PATH = "/api/v1/financingAgreement";

    private final FinancingService service = Mockito.mock(FinancingService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new FinancingController(service))
            .setControllerAdvice(new GlobalExceptionHandler(new PersistenceExceptionTranslator())).build();

    private MockHttpServletRequestBuilder withHeaders(MockHttpServletRequestBuilder builder) {
        return builder.header("x-correlation-id", "tx-1").header("x-client-version-id", "1.0.0").header("x-app-id", "CRM_POS").header("x-channel", "WEB")
                .header("x-request-id", "req-1").header("x-user-id", "user").header("traceparent", "00-4d186321c1a7f0f354b297e8914ab240-4b2a9f18c30eb2f1-01");
    }

    @Test
    void postReturnsCreatedWithTheGeneratedIdentifier() throws Exception {
        CreateFinancingData data = new CreateFinancingData();
        data.setAgreementCodeId(ID);
        CreateFinancingResponse response = new CreateFinancingResponse();
        response.setCode(HttpStatus.CREATED.value());
        response.setData(data);
        Mockito.when(service.createFinancing(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(CreateFinancingRequest.class))).thenReturn(response);
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("{\\"requestCodeId\\":1,\\"requestTypeId\\":2}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.data.agreementCodeId").value(ID.intValue()));
    }

    @Test
    void patchAndDeleteReturnOkWithoutData() throws Exception {
        UpdateFinancingResponse updated = new UpdateFinancingResponse();
        updated.setCode(HttpStatus.OK.value());
        Mockito.when(service.updateFinancing(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(UpdateFinancingRequest.class))).thenReturn(updated);
        mvc.perform(withHeaders(patch(PATH)).contentType(MediaType.APPLICATION_JSON).content("{\\"agreementCodeId\\":5001}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isEmpty());
        DeleteFinancingResponse deleted = new DeleteFinancingResponse();
        deleted.setCode(HttpStatus.OK.value());
        Mockito.when(service.deleteFinancing(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(ID))).thenReturn(deleted);
        mvc.perform(withHeaders(delete(PATH + "/" + ID))).andExpect(status().isOk());
    }

    @Test
    void routesTheLiteralPathsBeforeTheIdentifierTemplate() throws Exception {
        StateFinancingResponse states = new StateFinancingResponse();
        states.setCode(HttpStatus.OK.value());
        Mockito.when(service.stateFinancing(ArgumentMatchers.any(RequestHeaders.class))).thenReturn(states);
        mvc.perform(withHeaders(get(PATH + "/state"))).andExpect(status().isOk());
        Mockito.verify(service, Mockito.never()).getFinancing(ArgumentMatchers.any(), ArgumentMatchers.any());
    }

    @Test
    void notFoundIsReportedWithTheContractError() throws Exception {
        Mockito.when(service.getFinancing(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(ID))).thenThrow(ServiceOperationException.notFound());
        mvc.perform(withHeaders(get(PATH + "/" + ID)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.status").value("NOT_FOUND"))
                .andExpect(jsonPath("$.code").value(HttpStatus.NOT_FOUND.value()))
                .andExpect(jsonPath("$.subType").value("IDF302"))
                .andExpect(jsonPath("$.type").value("ResourceNotFoundException"))
                .andExpect(jsonPath("$.message").value("FINANCINGAGREEMENT_SERVICE_ERROR"));
    }

    @Test
    void aMissingHeaderOrParameterIsABadRequestNamingTheField() throws Exception {
        mvc.perform(get(PATH + "/state"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.subType").value("IDF101"));
        mvc.perform(withHeaders(get(PATH + "/search")).param("dateBegin", "2026-10-01"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.detail").value(org.hamcrest.Matchers.containsString("dateEnd")));
        mvc.perform(withHeaders(get(PATH + "/abc"))).andExpect(status().isBadRequest());
    }

    @Test
    void anUnreadableBodyIsABadRequest() throws Exception {
        mvc.perform(withHeaders(post(PATH)).contentType(MediaType.APPLICATION_JSON).content("{\\"requestCodeId\\":\\"x\\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.subType").value("IDF101"));
    }

    @Test
    void persistenceFailuresUseTheDeclaredServerStatuses() throws Exception {
        Mockito.when(service.getFinancing(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(ID))).thenThrow(new QueryTimeoutException("timeout"));
        mvc.perform(withHeaders(get(PATH + "/" + ID)))
                .andExpect(status().isGatewayTimeout())
                .andExpect(jsonPath("$.subType").value("IDT1"));
        Mockito.when(service.stateFinancing(ArgumentMatchers.any(RequestHeaders.class))).thenThrow(new IllegalStateException("boom"));
        mvc.perform(withHeaders(get(PATH + "/state")))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.subType").value("IDT3"));
    }
}'''
CONTROLLER_TEST = CONTROLLER_TEST.replace('CreateFinancingData', 'CreateFinancingResponseData')

HANDLER_TEST = '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());
    private final WebRequest request = new ServletWebRequest(new MockHttpServletRequest("GET", "/api/v1/financingAgreement/state"));

    @Test
    void mapsOperationFailuresToTheContractErrorBody() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.invalidDateRange(), request);
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF126", response.getBody().getSubType());
        assertEquals("InvalidDateRangeException", response.getBody().getType());
        assertEquals("FINANCINGAGREEMENT_SERVICE_ERROR", response.getBody().getMessage());
        assertEquals("BAD_REQUEST", response.getBody().getStatus());
    }

    @Test
    void neverEmitsAnUndeclaredStatus() {
        ServiceOperationException conflict = new ServiceOperationException(HttpStatus.CONFLICT, "IDF300", "Conflict", "conflict");
        ResponseEntity<ErrorResponse> response = handler.operationFailure(conflict, request);
        assertEquals(HttpStatus.CONFLICT.value(), response.getStatusCode().value());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), response.getBody().getCode());
    }

    @Test
    void translatesUnexpectedFailures() {
        ResponseEntity<ErrorResponse> unavailable = handler.unexpectedFailure(new CannotCreateTransactionException("down"), request);
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE.value(), unavailable.getStatusCode().value());
        assertEquals("IDT2", unavailable.getBody().getSubType());
        ResponseEntity<ErrorResponse> internal = handler.unexpectedFailure(new IllegalStateException("boom"), request);
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), internal.getStatusCode().value());
        assertEquals("IDT3", internal.getBody().getSubType());
        assertFalse(internal.getBody().getDetail().contains("boom"));
    }
}'''


def build_tests(pkg):
    files = {}

    def put(suffix, name, body, statics=ASSERT):
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)

    put('validation', 'FinancingValidatorTest', VALIDATOR_TEST)
    put('dto.mapper', 'FinancingMapperTest', MAPPER_TEST)
    put('exception', 'GlobalExceptionHandlerTest', HANDLER_TEST)
    put('service.impl', 'FinancingServiceImplTest', SERVICE_TEST)
    put('controller', 'FinancingApiContractTest', CONTROLLER_TEST, MVC_STATICS + ASSERT)
    return files
