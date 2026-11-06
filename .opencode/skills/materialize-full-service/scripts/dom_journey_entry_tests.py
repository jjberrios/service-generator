"""JUnit 5 test templates of the dom-journeyEntry service."""
MOCK_REST = ['org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo', 'org.springframework.test.web.client.match.MockRestRequestMatchers.method',
             'org.springframework.test.web.client.match.MockRestRequestMatchers.header', 'org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess',
             'org.springframework.test.web.client.response.MockRestResponseCreators.withStatus', 'org.springframework.test.web.client.response.MockRestResponseCreators.withException']

TESTS = {}

TESTS['JourneyEntryValidatorTest'] = ('validation', '''class JourneyEntryValidatorTest {
    private final JourneyEntryValidator validator = new JourneyEntryValidator();

    private HttpStatus statusOf(Executable call) {
        return assertThrows(ServiceOperationException.class, call).getStatus();
    }

    @Test
    void identifiersMustBePositiveIntegers() {
        assertEquals(Long.valueOf(1L), validator.id(" 1 "));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.id("abc")));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.id("0")));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.id(null)));
    }

    @Test
    void listFiltersAreValidated() {
        validator.list(LocalDate.parse("2026-10-01"), LocalDate.parse("2026-10-02"), "01", "F001", "123");
        validator.list(null, null, null, null, null);
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.list(LocalDate.parse("2026-10-03"), LocalDate.parse("2026-10-02"), null, null, null)));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.list(null, null, null, "F001", null)));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.list(null, null, "0%", null, null)));
    }

    @Test
    void createRequiresBothFields() {
        CreateJourneyEntryRequest request = new CreateJourneyEntryRequest();
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.create(request)));
        request.setIdTranssacion("T");
        request.setPayloadSAP(" ");
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.create(request)));
        request.setPayloadSAP("{}");
        validator.create(request);
    }

    @Test
    void updateRequiresTheDeclaredFields() {
        UpdateJourneyEntryResultRequest request = new UpdateJourneyEntryResultRequest();
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.update(request)));
        request.setStage("RFC_1");
        request.setExpectedStatus("OK");
        request.setJournalEntryStatusId(1L);
        request.setAttemptNumber(-1);
        request.setAttemptStartedAt(OffsetDateTime.parse("2026-10-12T10:00:00Z"));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(() -> validator.update(request)));
        request.setAttemptNumber(0);
        validator.update(request);
    }
}''')

TESTS['JourneyEntryPayloadValidatorTest'] = ('validation', '''class JourneyEntryPayloadValidatorTest {
    private static final long CORRELATIVE = 1234L;
    private static final String CONFIG = "{'scenarioContext':{'CANAL_VENTA':'WEB|M|VARCHAR'},'rfcRequests':{'Z02OTCMF_GEN_FLUJO_COM':{'TI_DOCUMENTO':{'minItems':1,'maxItems':1,"
            + "'items':{'NRO_REFERENCIA':'M|VARCHAR','IMPORTE':'O|DOUBLE'}}},'Z02OTCMF_VENTAS_CONVER':{'TI_ITEMS':{'minItems':1,'maxItems':null,'items':{'POSICION':'M|INTEGER'}}}}}";
    private static final String PAYLOAD = "{'scenarioContext':{'CANAL_VENTA':'WEB'},'rfcRequests':{'Z02OTCMF_GEN_FLUJO_COM':{'TI_DOCUMENTO':[{'NRO_REFERENCIA':'01-F001-00001234'}]},"
            + "'Z02OTCMF_VENTAS_CONVER':{'TI_ITEMS':[{'POSICION':1}]}}}";

    private final JourneyEntryPayloadValidator validator = new JourneyEntryPayloadValidator();

    private static String json(String text) {
        return text.replace("'", "\\"");
    }

    private List<ConfigurationData> configs(String value) {
        ConfigurationData data = new ConfigurationData();
        data.setConfigValue(json(value));
        return List.of(data);
    }

    private HttpStatus statusOf(String payload, String config) {
        return assertThrows(ServiceOperationException.class, () -> validator.validate(json(payload), configs(config))).getStatus();
    }

    @Test
    void aValidPayloadYieldsTheCpeReference() {
        JsonNode payload = validator.validate(json(PAYLOAD), configs(CONFIG));
        JourneyEntryPayloadValidator.CpeReference reference = validator.reference(payload);
        assertEquals("01", reference.documentType());
        assertEquals("F001", reference.series());
        assertEquals(Long.valueOf(CORRELATIVE), reference.correlative());
        assertEquals("01-F001-00001234", reference.nroReferencia());
    }

    @Test
    void invalidPayloadsAreBadRequests() {
        assertEquals(HttpStatus.BAD_REQUEST, statusOf("not json", CONFIG));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf("{'rfcRequests':{}}", CONFIG));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(PAYLOAD.replace("'NRO_REFERENCIA':'01-F001-00001234'", ""), CONFIG));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(PAYLOAD.replace("'POSICION':1", "'POSICION':'x'"), CONFIG));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(PAYLOAD.replace("'POSICION':1", "'POSICION':1,'EXTRA':1"), CONFIG));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(PAYLOAD.replace("'TI_ITEMS':[{'POSICION':1}]", "'TI_ITEMS':[]"), CONFIG));
        assertEquals(HttpStatus.BAD_REQUEST, statusOf(PAYLOAD.replace("'CANAL_VENTA':'WEB'", "'CANAL_VENTA':''"), CONFIG));
    }

    @Test
    void aMissingConfigurationIsUnprocessable() {
        assertEquals(HttpStatus.UNPROCESSABLE_ENTITY, statusOf(PAYLOAD.replace("'CANAL_VENTA':'WEB'", "'CANAL_VENTA':'TIENDA'"), CONFIG));
    }

    @Test
    void anInvalidConfigurationIsAnInternalError() {
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, statusOf(PAYLOAD, CONFIG.replace("M|INTEGER", "X|Y")));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, statusOf(PAYLOAD, "{'scenarioContext':{}}"));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, statusOf(PAYLOAD, "no json"));
    }

    @Test
    void twoEquallySpecificConfigurationsAreAnInternalError() {
        ConfigurationData first = new ConfigurationData();
        first.setConfigValue(json(CONFIG));
        List<ConfigurationData> twice = List.of(first, first);
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> validator.validate(json(PAYLOAD), twice));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, failure.getStatus());
    }

    @Test
    void theReferenceMustBeWellFormed() {
        JsonNode payload = validator.validate(json(PAYLOAD), configs(CONFIG));
        assertEquals("F001", validator.reference(payload).series());
        JsonNode broken = validator.validate(json(PAYLOAD.replace("01-F001-00001234", "01-F001-abc")), configs(CONFIG));
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> validator.reference(broken)).getStatus());
    }
}''')

TESTS['JourneyEntryMapperTest'] = ('dto.mapper', '''class JourneyEntryMapperTest {
    private final JourneyEntryMapper mapper = new JourneyEntryMapper();

    private JournalEntryStatusEntity status(Long id, String value) {
        JournalEntryStatusEntity status = new JournalEntryStatusEntity();
        status.setId(id);
        status.setValue(value);
        status.setDescription(value + " descripcion");
        return status;
    }

    private JournalEntryEntity entry() {
        JournalEntryEntity entry = new JournalEntryEntity();
        entry.setId(1L);
        entry.setRequestReference("T1");
        entry.setNroReference("01-F001-00001234");
        entry.setSapOrderNumber("O");
        entry.setSapDeliveryNumber("D");
        entry.setSapInvoiceNumber("I");
        entry.setJournalEntryStatusId(2L);
        entry.setLastSapAttemptDate(LocalDateTime.parse("2026-10-12T10:15:30"));
        return entry;
    }

    @Test
    void theJournalEntryNumberNeedsTheThreeSapNumbers() {
        assertEquals("O-D-I", mapper.journalEntryNumber("O", "D", "I"));
        assertNull(mapper.journalEntryNumber("O", null, "I"));
        assertNull(mapper.journalEntryNumber("O", "D", " "));
    }

    @Test
    void theListingItemParsesTheReferenceAndTheResendFlag() {
        Map<Long, JournalEntryStatusEntity> catalog = Map.of(2L, status(2L, JourneyEntryMapper.NOT_RETRYABLE));
        AccountingEntryItem item = mapper.list(List.of(entry()), catalog).getData().getAccountingEntry().get(0);
        assertEquals("01", item.getDocumentType());
        assertEquals("F001", item.getSeries());
        assertEquals("00001234", item.getCorrelative());
        assertEquals("O-D-I", item.getJournalEntryNumber());
        assertEquals(Integer.valueOf(1), item.getCanResend());
        assertEquals(JourneyEntryMapper.NOT_RETRYABLE, item.getSapStatus());
        AccountingEntryItem other = mapper.list(List.of(entry()), Map.of(2L, status(2L, "ENVIADO"))).getData().getAccountingEntry().get(0);
        assertEquals(Integer.valueOf(0), other.getCanResend());
    }

    @Test
    void acceptedAndDuplicateResponsesKeepTheirCodes() {
        assertEquals(HttpStatus.ACCEPTED.value(), mapper.accepted(entry(), "RECIBIDO").getCode());
        assertEquals(HttpStatus.OK.value(), mapper.duplicate(entry(), "RECIBIDO").getCode());
        assertEquals("T1", mapper.accepted(entry(), "RECIBIDO").getData().getRequestReference());
    }

    @Test
    void theSnapshotCopiesTheEntry() {
        LocalDateTime now = LocalDateTime.parse("2026-10-12T11:00:00");
        JournalEntryHistEntity hist = mapper.snapshot(entry(), now, "user");
        assertEquals(Long.valueOf(1L), hist.getJournalEntryId());
        assertEquals("T1", hist.getRequestReference());
        assertEquals(now, hist.getSnapshotDate());
        assertEquals("user", hist.getCreationUser());
    }

    @Test
    void theResultIsAppliedAndTheFirstAttemptIsKept() {
        UpdateJourneyEntryResultRequest request = new UpdateJourneyEntryResultRequest();
        request.setJournalEntryStatusId(1L);
        request.setAttemptNumber(1);
        request.setSapOrderNumber("O2");
        JournalEntryEntity entry = entry();
        LocalDateTime first = LocalDateTime.parse("2026-10-01T08:00:00");
        entry.setFirstSapAttemptDate(first);
        LocalDateTime attempt = LocalDateTime.parse("2026-10-12T10:00:00");
        mapper.applyResult(entry, request, attempt, "user", attempt);
        assertEquals(first, entry.getFirstSapAttemptDate());
        assertEquals(attempt, entry.getLastSapAttemptDate());
        assertEquals("O2", entry.getSapOrderNumber());
        assertEquals("D", entry.getSapDeliveryNumber());
        assertEquals("user", entry.getLastModifiedUser());
    }

    @Test
    void traceabilityAndDetailExposeTheStatusCatalog() {
        Map<Long, JournalEntryStatusEntity> catalog = Map.of(2L, status(2L, "ENVIADO"));
        JournalEntryHistEntity hist = new JournalEntryHistEntity();
        hist.setId(1L);
        hist.setJournalEntryStatusId(2L);
        hist.setCreationUser("user");
        GetJourneyEntryTraceabilityData data = mapper.traceability(entry(), List.of(hist), catalog).getData();
        assertEquals("ENVIADO", data.getCurrentStatus());
        assertEquals("ENVIADO", data.getHistory().get(0).getStatus());
        assertEquals("user", data.getHistory().get(0).getUser());
        assertEquals(0, mapper.traceability(entry(), List.of(), catalog).getData().getHistory().size());
        GetJourneyEntryByIdData detail = mapper.byId(entry(), status(2L, "ENVIADO")).getData();
        assertEquals("ENVIADO", detail.getJournalEntryStatus());
        assertEquals("T1", detail.getRequestreference());
        assertNull(mapper.byId(entry(), null).getData().getJournalEntryStatus());
    }

    @Test
    void theNewEntryStartsWithoutAttempts() throws Exception {
        CreateJourneyEntryRequest request = new CreateJourneyEntryRequest();
        request.setIdTranssacion("T1");
        request.setPayloadSAP("{}");
        JsonNode payload = new ObjectMapper().readTree("{\\"rfcRequests\\":{\\"Z02OTCMF_GEN_FLUJO_COM\\":{\\"A\\":1},\\"Z02OTCMF_VENTAS_CONVER\\":{\\"B\\":2}}}");
        JournalEntryEntity created = mapper.newEntry(request, "01-F001-1", payload, 1L, "user", LocalDateTime.parse("2026-10-12T10:15:30"));
        assertEquals(Integer.valueOf(0), created.getAttemptNumber());
        assertEquals("{\\"A\\":1}", created.getFirstRequest());
        assertEquals("{\\"B\\":2}", created.getSecondRequest());
        assertEquals("user", created.getCreationUser());
    }
}''')

TESTS['GlobalExceptionHandlerTest'] = ('exception', '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request(String method, String uri) {
        return new ServletWebRequest(new MockHttpServletRequest(method, uri));
    }

    @Test
    void unprocessableEntityIsDeclaredForThePost() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(new ServiceOperationException(HttpStatus.UNPROCESSABLE_ENTITY, "x"), request("POST", "/api/v1/dom-journeyEntry"));
        assertEquals(HttpStatus.UNPROCESSABLE_ENTITY.value(), response.getStatusCode().value());
        assertEquals("IDF6", response.getBody().getSubType());
        assertEquals("PROCESPOST_JOURNEYENTRY_SERVICE_ERROR", response.getBody().getMessage());
    }

    @Test
    void conflictUsesTheContractSubtype() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(new ServiceOperationException(HttpStatus.CONFLICT, "x"), request("PATCH", "/api/v1/dom-journeyEntry/1/resend"));
        assertEquals(HttpStatus.CONFLICT.value(), response.getStatusCode().value());
        assertEquals("IDF5", response.getBody().getSubType());
        assertEquals("PROCESPATCH_JOURNEYENTRY_SERVICE_ERROR", response.getBody().getMessage());
    }

    @Test
    void operationMessagesFollowTheContract() {
        assertEquals("PROCESGET_JOURNEYENTRY_SERVICE_ERROR", handler.operationFailure(ServiceOperationException.badRequest("x"), request("GET", "/api/v1/dom-journeyEntry")).getBody().getMessage());
        assertEquals("PROCESGETID_JOURNEYENTRY_SERVICE_ERROR", handler.operationFailure(ServiceOperationException.badRequest("x"), request("GET", "/api/v1/dom-journeyEntry/1")).getBody().getMessage());
        assertEquals("PROCESGETTRACE_JOURNEYENTRY_SERVICE_ERROR", handler.operationFailure(ServiceOperationException.badRequest("x"), request("GET", "/api/v1/dom-journeyEntry/1/traceability")).getBody().getMessage());
        assertEquals("PROCESPATCHID_JOURNEYENTRY_SERVICE_ERROR", handler.operationFailure(ServiceOperationException.badRequest("x"), request("PATCH", "/api/v1/dom-journeyEntry/1")).getBody().getMessage());
    }

    @Test
    void getRequestsNeverReturnConflict() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(new ServiceOperationException(HttpStatus.CONFLICT, "x"), request("GET", "/api/v1/dom-journeyEntry"));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), response.getStatusCode().value());
    }

    @Test
    void unexpectedFailuresBecomeInternalError() {
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), handler.unexpectedFailure(new IllegalStateException("boom"), request("GET", "/api/v1/dom-journeyEntry")).getStatusCode().value());
    }
}''')

TESTS['JourneyEntryServiceImplTest'] = ('service.impl', '''class JourneyEntryServiceImplTest {
    private static final Long ID = 7L;
    private static final Long RECEIVED_ID = 1L;
    private static final Long SENT_ID = 2L;
    private static final Long NOT_RETRYABLE_ID = 3L;
    private static final Long TYPE_ID = 4L;
    private static final Long CPE_STATUS_ID = 5L;
    private static final Long CORRELATIVE = 1234L;
    private static final LocalDateTime NOW = LocalDateTime.parse("2026-10-12T10:15:30");
    private static final String CONFIG = "{'scenarioContext':{'CANAL_VENTA':'WEB|M|VARCHAR'},'rfcRequests':{'Z02OTCMF_GEN_FLUJO_COM':{'TI_DOCUMENTO':{'minItems':1,'maxItems':1,"
            + "'items':{'NRO_REFERENCIA':'M|VARCHAR'}}},'Z02OTCMF_VENTAS_CONVER':{'TI_ITEMS':{'minItems':1,'maxItems':null,'items':{'POSICION':'M|INTEGER'}}}}}";
    private static final String PAYLOAD = "{'scenarioContext':{'CANAL_VENTA':'WEB'},'rfcRequests':{'Z02OTCMF_GEN_FLUJO_COM':{'TI_DOCUMENTO':[{'NRO_REFERENCIA':'01-F001-00001234'}]},"
            + "'Z02OTCMF_VENTAS_CONVER':{'TI_ITEMS':[{'POSICION':1}]}}}";

    private final JournalEntryRepository entries = Mockito.mock(JournalEntryRepository.class);
    private final JournalEntryHistRepository history = Mockito.mock(JournalEntryHistRepository.class);
    private final JournalEntryStatusRepository statuses = Mockito.mock(JournalEntryStatusRepository.class);
    private final EpdRequestRepository requests = Mockito.mock(EpdRequestRepository.class);
    private final ElectronicDocumentTypeRepository documentTypes = Mockito.mock(ElectronicDocumentTypeRepository.class);
    private final EpdQueryStatusRepository queryStatuses = Mockito.mock(EpdQueryStatusRepository.class);
    private final AccountingConfigClient configClient = Mockito.mock(AccountingConfigClient.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-12T10:15:30Z"), ZoneOffset.UTC);
    private final JourneyEntryServiceImpl service = new JourneyEntryServiceImpl(entries, history, statuses, requests, documentTypes, queryStatuses, new JourneyEntryMapper(),
            new JourneyEntryValidator(), new JourneyEntryPayloadValidator(), configClient, new PersistenceExceptionTranslator(),
            new TransactionTemplate(Mockito.mock(PlatformTransactionManager.class)), clock);
    private final RequestHeaders headers = new RequestHeaders("tx", "user", "app");
    private final ForwardedHeaders forwarded = new ForwardedHeaders("t", "app", "web", "1", "tx", "req", "user");

    private static String json(String text) {
        return text.replace("'", "\\"");
    }

    private JournalEntryStatusEntity status(Long id, String value) {
        JournalEntryStatusEntity status = new JournalEntryStatusEntity();
        status.setId(id);
        status.setValue(value);
        status.setDescription(value);
        status.setStatus(1);
        return status;
    }

    private JournalEntryEntity entry(Long statusId) {
        JournalEntryEntity entry = new JournalEntryEntity();
        entry.setId(ID);
        entry.setRequestReference("T1");
        entry.setNroReference("01-F001-00001234");
        entry.setJournalEntryStatusId(statusId);
        return entry;
    }

    private CreateJourneyEntryRequest createRequest() {
        CreateJourneyEntryRequest request = new CreateJourneyEntryRequest();
        request.setIdTranssacion("T1");
        request.setPayloadSAP(json(PAYLOAD));
        return request;
    }

    private void stubCreation(String cpeStatus) {
        ConfigurationData config = new ConfigurationData();
        config.setConfigValue(json(CONFIG));
        Mockito.when(configClient.findConfigurations(forwarded)).thenReturn(List.of(config));
        ElectronicDocumentTypeEntity type = new ElectronicDocumentTypeEntity();
        type.setId(TYPE_ID);
        Mockito.when(documentTypes.findFirstBySunatDocumentTypeCode("01")).thenReturn(Optional.of(type));
        EpdRequestEntity cpe = new EpdRequestEntity();
        cpe.setEpdQueryStatusId(CPE_STATUS_ID);
        Mockito.when(requests.findBySeriesAndCorrelativeAndEpdTypeId("F001", CORRELATIVE, TYPE_ID)).thenReturn(List.of(cpe));
        EpdQueryStatusEntity queryStatus = new EpdQueryStatusEntity();
        queryStatus.setValue(cpeStatus);
        Mockito.when(queryStatuses.findById(CPE_STATUS_ID)).thenReturn(Optional.of(queryStatus));
        Mockito.when(statuses.findFirstByValueAndStatus("RECIBIDO", 1)).thenReturn(Optional.of(status(RECEIVED_ID, "RECIBIDO")));
        Mockito.when(entries.findByRequestReference("T1")).thenReturn(Optional.empty());
        Mockito.when(entries.save(ArgumentMatchers.any(JournalEntryEntity.class))).thenAnswer(call -> {
            JournalEntryEntity saved = call.getArgument(0);
            saved.setId(ID);
            return saved;
        });
    }

    @Test
    void createRegistersTheEntryAndItsSnapshot() {
        stubCreation("ACEPTADO");
        CreateJourneyEntryResponse response = service.createJourneyEntry(headers, forwarded, createRequest());
        assertEquals(HttpStatus.ACCEPTED.value(), response.getCode());
        assertEquals("RECIBIDO", response.getData().getStatus());
        assertEquals(ID, response.getData().getJournalEntryId());
        ArgumentCaptor<JournalEntryEntity> saved = ArgumentCaptor.forClass(JournalEntryEntity.class);
        ArgumentCaptor<JournalEntryHistEntity> snapshot = ArgumentCaptor.forClass(JournalEntryHistEntity.class);
        InOrder order = Mockito.inOrder(entries, history);
        order.verify(entries).save(saved.capture());
        order.verify(history).save(snapshot.capture());
        assertEquals(Integer.valueOf(0), saved.getValue().getAttemptNumber());
        assertEquals("user", saved.getValue().getCreationUser());
        assertEquals(NOW, saved.getValue().getCreationDate());
        assertEquals("01-F001-00001234", saved.getValue().getNroReference());
        assertEquals(ID, snapshot.getValue().getJournalEntryId());
        assertEquals(NOW, snapshot.getValue().getSnapshotDate());
    }

    @Test
    void anExistingTransactionIsReturnedWithoutRegistering() {
        stubCreation("ACEPTADO");
        Mockito.when(entries.findByRequestReference("T1")).thenReturn(Optional.of(entry(RECEIVED_ID)));
        Mockito.when(statuses.findById(RECEIVED_ID)).thenReturn(Optional.of(status(RECEIVED_ID, "RECIBIDO")));
        CreateJourneyEntryResponse response = service.createJourneyEntry(headers, forwarded, createRequest());
        assertEquals(HttpStatus.OK.value(), response.getCode());
        Mockito.verify(entries, Mockito.never()).save(ArgumentMatchers.any(JournalEntryEntity.class));
    }

    @Test
    void aRejectedCpeIsUnprocessable() {
        stubCreation("RECHAZADO");
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.createJourneyEntry(headers, forwarded, createRequest()));
        assertEquals(HttpStatus.UNPROCESSABLE_ENTITY, failure.getStatus());
    }

    @Test
    void anUnknownCpeIsNotFoundAndDuplicatedCpesConflict() {
        stubCreation("ACEPTADO");
        Mockito.when(requests.findBySeriesAndCorrelativeAndEpdTypeId("F001", CORRELATIVE, TYPE_ID)).thenReturn(List.of());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.createJourneyEntry(headers, forwarded, createRequest())).getStatus());
        Mockito.when(requests.findBySeriesAndCorrelativeAndEpdTypeId("F001", CORRELATIVE, TYPE_ID)).thenReturn(List.of(new EpdRequestEntity(), new EpdRequestEntity()));
        assertEquals(HttpStatus.CONFLICT, assertThrows(ServiceOperationException.class, () -> service.createJourneyEntry(headers, forwarded, createRequest())).getStatus());
    }

    @Test
    void anUnavailableConfigurationServiceStopsTheCreation() {
        Mockito.when(configClient.findConfigurations(forwarded)).thenThrow(new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, "down"));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, assertThrows(ServiceOperationException.class, () -> service.createJourneyEntry(headers, forwarded, createRequest())).getStatus());
    }

    @Test
    void aUniqueViolationBecomesAConflict() {
        stubCreation("ACEPTADO");
        Mockito.when(entries.save(ArgumentMatchers.any(JournalEntryEntity.class))).thenThrow(new DataIntegrityViolationException("unique", new SQLException("ORA-00001", "23000", 1)));
        assertEquals(HttpStatus.CONFLICT, assertThrows(ServiceOperationException.class, () -> service.createJourneyEntry(headers, forwarded, createRequest())).getStatus());
    }

    @Test
    void theListingMapsRowsAndRejectsEmptyResults() {
        Mockito.when(statuses.findAll()).thenReturn(List.of(status(SENT_ID, "ENVIADO")));
        Mockito.when(documentTypes.findFirstBySunatDocumentTypeCode("01")).thenReturn(Optional.of(new ElectronicDocumentTypeEntity()));
        Mockito.when(entries.findAll(ArgumentMatchers.<Specification<JournalEntryEntity>>any())).thenReturn(List.of(entry(SENT_ID)));
        GetJourneyEntryResponse response = service.getJourneyEntries(headers, LocalDate.parse("2026-10-01"), LocalDate.parse("2026-10-31"), "ENVIADO", "01", "F001", "00001234");
        assertEquals("ENVIADO", response.getData().getAccountingEntry().get(0).getSapStatus());
        Mockito.when(entries.findAll(ArgumentMatchers.<Specification<JournalEntryEntity>>any())).thenReturn(List.of());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.getJourneyEntries(headers, null, null, null, null, null, null)).getStatus());
    }

    @Test
    void anUnknownStatusOrDocumentTypeIsABadRequest() {
        Mockito.when(statuses.findAll()).thenReturn(List.of(status(SENT_ID, "ENVIADO")));
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.getJourneyEntries(headers, null, null, "OTRO", null, null, null)).getStatus());
        Mockito.when(documentTypes.findFirstBySunatDocumentTypeCode("99")).thenReturn(Optional.empty());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.getJourneyEntries(headers, null, null, null, "99", null, null)).getStatus());
    }

    private void stubResend(Long currentStatus, int updatedRows) {
        Mockito.when(statuses.findFirstByValue("NO_REINTENTABLE")).thenReturn(Optional.of(status(NOT_RETRYABLE_ID, "NO_REINTENTABLE")));
        Mockito.when(statuses.findFirstByValue("RECIBIDO")).thenReturn(Optional.of(status(RECEIVED_ID, "RECIBIDO")));
        Mockito.when(entries.findById(ID)).thenReturn(Optional.of(entry(currentStatus)));
        Mockito.when(entries.moveStatus(ArgumentMatchers.eq(ID), ArgumentMatchers.eq(NOT_RETRYABLE_ID), ArgumentMatchers.eq(RECEIVED_ID), ArgumentMatchers.eq("user"),
                ArgumentMatchers.any(LocalDateTime.class))).thenReturn(updatedRows);
    }

    @Test
    void resendMovesTheEntryBackToReceivedAndWritesAHistoryRow() {
        stubResend(NOT_RETRYABLE_ID, 1);
        JourneyEntryBasicResponse response = service.resend(headers, "7");
        assertEquals(HttpStatus.OK.value(), response.getCode());
        ArgumentCaptor<JournalEntryHistEntity> snapshot = ArgumentCaptor.forClass(JournalEntryHistEntity.class);
        Mockito.verify(history).save(snapshot.capture());
        assertEquals(RECEIVED_ID, snapshot.getValue().getJournalEntryStatusId());
        assertEquals(NOW, snapshot.getValue().getSnapshotDate());
    }

    @Test
    void resendConflictsWhenTheStatusIsNotRetryableOrTheUpdateLosesTheRace() {
        stubResend(SENT_ID, 1);
        assertEquals(HttpStatus.CONFLICT, assertThrows(ServiceOperationException.class, () -> service.resend(headers, "7")).getStatus());
        stubResend(NOT_RETRYABLE_ID, 0);
        assertEquals(HttpStatus.CONFLICT, assertThrows(ServiceOperationException.class, () -> service.resend(headers, "7")).getStatus());
        Mockito.verify(history, Mockito.never()).save(ArgumentMatchers.any(JournalEntryHistEntity.class));
    }

    @Test
    void resendOfAMissingEntryIsNotFound() {
        stubResend(NOT_RETRYABLE_ID, 1);
        Mockito.when(entries.findById(ID)).thenReturn(Optional.empty());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.resend(headers, "7")).getStatus());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.resend(headers, "x")).getStatus());
    }

    private UpdateJourneyEntryResultRequest updateRequest() {
        UpdateJourneyEntryResultRequest request = new UpdateJourneyEntryResultRequest();
        request.setStage("RFC_1");
        request.setExpectedStatus("OK");
        request.setJournalEntryStatusId(SENT_ID);
        request.setAttemptNumber(1);
        request.setAttemptStartedAt(OffsetDateTime.parse("2026-10-12T10:00:00Z"));
        request.setSapOrderNumber("O");
        return request;
    }

    @Test
    void theResultUpdatesTheEntryAndWritesAHistoryRow() {
        Mockito.when(entries.findById(ID)).thenReturn(Optional.of(entry(RECEIVED_ID)));
        Mockito.when(statuses.existsById(SENT_ID)).thenReturn(true);
        Mockito.when(entries.save(ArgumentMatchers.any(JournalEntryEntity.class))).thenAnswer(call -> call.getArgument(0));
        assertEquals(HttpStatus.OK.value(), service.updateResult(headers, "7", updateRequest()).getCode());
        ArgumentCaptor<JournalEntryEntity> saved = ArgumentCaptor.forClass(JournalEntryEntity.class);
        Mockito.verify(entries).save(saved.capture());
        assertEquals(SENT_ID, saved.getValue().getJournalEntryStatusId());
        assertEquals(LocalDateTime.parse("2026-10-12T10:00:00"), saved.getValue().getFirstSapAttemptDate());
        assertEquals("O", saved.getValue().getSapOrderNumber());
        assertEquals(NOW, saved.getValue().getLastModifiedDate());
        Mockito.verify(history).save(ArgumentMatchers.any(JournalEntryHistEntity.class));
    }

    @Test
    void theResultRejectsMissingEntriesUnknownStatusesAndInvalidBodies() {
        Mockito.when(entries.findById(ID)).thenReturn(Optional.empty());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.updateResult(headers, "7", updateRequest())).getStatus());
        Mockito.when(entries.findById(ID)).thenReturn(Optional.of(entry(RECEIVED_ID)));
        Mockito.when(statuses.existsById(SENT_ID)).thenReturn(false);
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.updateResult(headers, "7", updateRequest())).getStatus());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.updateResult(headers, "7", new UpdateJourneyEntryResultRequest())).getStatus());
    }

    @Test
    void theDetailAndTheTraceabilityReadTheEntry() {
        Mockito.when(entries.findById(ID)).thenReturn(Optional.of(entry(SENT_ID)));
        Mockito.when(statuses.findById(SENT_ID)).thenReturn(Optional.of(status(SENT_ID, "ENVIADO")));
        Mockito.when(statuses.findAll()).thenReturn(List.of(status(SENT_ID, "ENVIADO")));
        assertEquals("ENVIADO", service.getById(headers, "7").getData().getJournalEntryStatus());
        assertEquals(0, service.getTraceability(headers, "7").getData().getHistory().size());
        Mockito.when(entries.findById(ID)).thenReturn(Optional.empty());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.getById(headers, "7")).getStatus());
        assertEquals(HttpStatus.NOT_FOUND, assertThrows(ServiceOperationException.class, () -> service.getTraceability(headers, "7")).getStatus());
        assertEquals(HttpStatus.BAD_REQUEST, assertThrows(ServiceOperationException.class, () -> service.getById(headers, "abc")).getStatus());
    }

    @Test
    void databaseTimeoutsBecomeGatewayTimeouts() {
        Mockito.when(entries.findById(ID)).thenThrow(new QueryTimeoutException("slow"));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, assertThrows(ServiceOperationException.class, () -> service.getById(headers, "7")).getStatus());
    }
}''')

TESTS['AccountingConfigClientImplTest'] = ('client', '''class AccountingConfigClientImplTest {
    private static final String URL = "http://sod/api/v1/sod-configurations?configGroup=GROUP";
    private static final String BODY = "{'code':200,'data':[{'configId':1,'configKey':'K','configGroup':'GROUP','configValue':'v'}]}";

    private final RestClient.Builder builder = RestClient.builder().baseUrl("http://sod");
    private final MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    private final AccountingConfigClientImpl client = new AccountingConfigClientImpl(builder.build(), "GROUP");
    private final ForwardedHeaders forwarded = new ForwardedHeaders("t", "app", "web", "1", "tx", "req", "user");

    private static String json(String text) {
        return text.replace("'", "\\"");
    }

    private void expectSuccess() {
        server.expect(requestTo(URL)).andExpect(method(HttpMethod.GET)).andExpect(header("x-correlation-id", "tx"))
                .andRespond(withSuccess(json(BODY), MediaType.APPLICATION_JSON));
    }

    private HttpStatus failureOf() {
        return assertThrows(ServiceOperationException.class, () -> client.findConfigurations(forwarded)).getStatus();
    }

    @Test
    void itReadsTheConfigurationsAndForwardsTheHeaders() {
        expectSuccess();
        List<ConfigurationData> result = client.findConfigurations(forwarded);
        assertEquals("v", result.get(0).getConfigValue());
        server.verify();
    }

    @Test
    void itFallsBackToTheLastValueWhenTheServiceFails() {
        expectSuccess();
        client.findConfigurations(forwarded);
        server.reset();
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        assertEquals("v", client.findConfigurations(forwarded).get(0).getConfigValue());
    }

    @Test
    void withoutACachedValueFailuresAreMapped() {
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, failureOf());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.GATEWAY_TIMEOUT));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, failureOf());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withException(new SocketTimeoutException("slow")));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, failureOf());
        server.reset();
        server.expect(requestTo(URL)).andRespond(withException(new IOException("down")));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, failureOf());
    }

    @Test
    void aClientErrorIsNotFound() {
        server.expect(requestTo(URL)).andRespond(withStatus(HttpStatus.NOT_FOUND));
        assertEquals(HttpStatus.NOT_FOUND, failureOf());
    }
}''')

TESTS['JourneyEntryApiContractTest'] = ('controller', '''class JourneyEntryApiContractTest {
    private static final String BASE = "/api/v1/dom-journeyEntry";

    private final JourneyEntryService service = Mockito.mock(JourneyEntryService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new JourneyEntryController(service))
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

    private CreateJourneyEntryResponse created(int code) {
        CreateJourneyEntryAcceptedData data = new CreateJourneyEntryAcceptedData();
        data.setJournalEntryId(1L);
        data.setRequestReference("T1");
        data.setStatus("RECIBIDO");
        CreateJourneyEntryResponse response = new CreateJourneyEntryResponse();
        response.setCode(code);
        response.setMessage("ok");
        response.setData(data);
        return response;
    }

    @Test
    void getReturnsTheAccountingEntries() throws Exception {
        AccountingEntryItem item = new AccountingEntryItem();
        item.setId(1L);
        item.setSapStatus("ENVIADO");
        GetJourneyEntryData data = new GetJourneyEntryData();
        data.setAccountingEntry(List.of(item));
        GetJourneyEntryResponse response = new GetJourneyEntryResponse();
        response.setCode(HttpStatus.OK.value());
        response.setData(data);
        Mockito.when(service.getJourneyEntries(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(), ArgumentMatchers.any(), ArgumentMatchers.eq("ENVIADO"),
                ArgumentMatchers.any(), ArgumentMatchers.any(), ArgumentMatchers.any())).thenReturn(response);
        mvc.perform(withHeaders(get(BASE).param("sapStatus", "ENVIADO")))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.accountingEntry[0].sapStatus").value("ENVIADO"));
    }

    @Test
    void postAnswersAcceptedOrOkForDuplicates() throws Exception {
        Mockito.when(service.createJourneyEntry(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class), ArgumentMatchers.any(CreateJourneyEntryRequest.class)))
                .thenReturn(created(HttpStatus.ACCEPTED.value()));
        mvc.perform(withHeaders(post(BASE)).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isAccepted()).andExpect(jsonPath("$.data.status").value("RECIBIDO"));
        Mockito.when(service.createJourneyEntry(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class), ArgumentMatchers.any(CreateJourneyEntryRequest.class)))
                .thenReturn(created(HttpStatus.OK.value()));
        mvc.perform(withHeaders(post(BASE)).contentType(MediaType.APPLICATION_JSON).content("{}")).andExpect(status().isOk());
    }

    @Test
    void patchEndpointsReturnTheBasicEnvelope() throws Exception {
        JourneyEntryBasicResponse basic = new JourneyEntryBasicResponse();
        basic.setCode(HttpStatus.OK.value());
        basic.setMessage("ok");
        Mockito.when(service.resend(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq("1"))).thenReturn(basic);
        Mockito.when(service.updateResult(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq("1"), ArgumentMatchers.any(UpdateJourneyEntryResultRequest.class))).thenReturn(basic);
        mvc.perform(withHeaders(patch(BASE + "/1/resend"))).andExpect(status().isOk()).andExpect(jsonPath("$.message").value("ok"));
        mvc.perform(withHeaders(patch(BASE + "/1")).contentType(MediaType.APPLICATION_JSON).content("{}")).andExpect(status().isOk());
    }

    @Test
    void detailAndTraceabilityAreExposed() throws Exception {
        GetJourneyEntryByIdData detail = new GetJourneyEntryByIdData();
        detail.setJournalEntryId(1L);
        detail.setRequestreference("T1");
        GetJourneyEntryByIdResponse byId = new GetJourneyEntryByIdResponse();
        byId.setData(detail);
        Mockito.when(service.getById(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq("1"))).thenReturn(byId);
        GetJourneyEntryTraceabilityData trace = new GetJourneyEntryTraceabilityData();
        trace.setCurrentStatus("ENVIADO");
        GetJourneyEntryTraceabilityResponse traceResponse = new GetJourneyEntryTraceabilityResponse();
        traceResponse.setData(trace);
        Mockito.when(service.getTraceability(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq("1"))).thenReturn(traceResponse);
        mvc.perform(withHeaders(get(BASE + "/1"))).andExpect(status().isOk()).andExpect(jsonPath("$.data.requestreference").value("T1"));
        mvc.perform(withHeaders(get(BASE + "/1/traceability"))).andExpect(status().isOk()).andExpect(jsonPath("$.data.currentStatus").value("ENVIADO"));
    }

    @Test
    void aMissingHeaderIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(get(BASE)).andExpect(status().isBadRequest()).andExpect(jsonPath("$.subType").value("IDF1"));
    }

    @Test
    void serviceFailuresKeepTheirDeclaredStatus() throws Exception {
        Mockito.when(service.createJourneyEntry(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(ForwardedHeaders.class), ArgumentMatchers.any(CreateJourneyEntryRequest.class)))
                .thenThrow(new ServiceOperationException(HttpStatus.UNPROCESSABLE_ENTITY, "x"));
        mvc.perform(withHeaders(post(BASE)).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.subType").value("IDF6"));
    }

    @Test
    void aMalformedBodyIsABadRequest() throws Exception {
        mvc.perform(withHeaders(post(BASE)).contentType(MediaType.APPLICATION_JSON).content("not-json")).andExpect(status().isBadRequest());
    }
}''')
