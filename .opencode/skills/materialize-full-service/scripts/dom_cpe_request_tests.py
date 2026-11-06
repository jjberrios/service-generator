"""JUnit 5 / Mockito tests of the dom-cpeRequest service (checkstyle D-014 applies to tests: no magic numbers outside constants)."""
import dom_cpe_request_java as dj

dj.EXTERNAL.update({'Executable': 'org.junit.jupiter.api.function.Executable', 'MockHttpServletRequestBuilder': 'org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder',
                    'ServletWebRequest': 'org.springframework.web.context.request.ServletWebRequest'})

ASSERT = ['org.junit.jupiter.api.Assertions.' + n for n in ('assertEquals', 'assertNull', 'assertSame', 'assertThrows', 'assertTrue', 'assertNotNull')]

VALIDATOR_TEST = '''class CpeRequestValidatorTest {
    private static final int DEFAULT_SIZE = 50;
    private static final int MAX_SIZE = 100;
    private static final int OVER_MAX_SIZE = 101;
    private static final int OVER_LENGTH = 256;
    private static final Long ID = 10L;
    private static final Integer OUT_OF_RANGE = 9;
    private static final Integer APPROVED = 3;
    private static final Integer REJECTED = 7;
    private static final String URL = "http://host/doc";

    private final CpeRequestValidator validator = new CpeRequestValidator(DEFAULT_SIZE, MAX_SIZE);

    private CreateCpeRequest completeCreate() {
        CreateCpeRequest request = new CreateCpeRequest();
        request.setSeries("F001");
        request.setCorrelative(ID);
        request.setReferenceCode("REF");
        request.setEpdTypeId(1);
        request.setEpdQueryStatusId(1);
        request.setGenerationType(1);
        request.setActionType(1);
        request.setInputPayload("{}");
        request.setAttemptNumber(0);
        request.setDisagreementFlag(0);
        return request;
    }

    private RegisterCpeQueryResultRequest register(Integer status, String url) {
        RegisterCpeQueryResultRequest request = new RegisterCpeQueryResultRequest();
        request.setEpdQueryStatusId(status);
        request.setPdfUrl(url);
        request.setXmlUrl(url);
        request.setCdrUrl(url);
        return request;
    }

    private void assertBadRequest(Executable executable) {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, executable);
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
    }

    @Test
    void acceptsCompleteCreateRequest() {
        CreateCpeRequest request = completeCreate();
        assertSame(request, validator.createCpeRequest(request));
    }

    @Test
    void rejectsNullBody() {
        assertBadRequest(() -> validator.createCpeRequest(null));
    }

    @Test
    void rejectsMissingRequiredField() {
        CreateCpeRequest request = completeCreate();
        request.setSeries(" ");
        assertBadRequest(() -> validator.createCpeRequest(request));
    }

    @Test
    void rejectsValuesOutsideTheDeclaredEnumerations() {
        CreateCpeRequest type = completeCreate();
        type.setEpdTypeId(OUT_OF_RANGE);
        assertBadRequest(() -> validator.createCpeRequest(type));
        CreateCpeRequest flag = completeCreate();
        flag.setDisagreementFlag(2);
        assertBadRequest(() -> validator.createCpeRequest(flag));
        CreateCpeRequest attempts = completeCreate();
        attempts.setAttemptNumber(-1);
        assertBadRequest(() -> validator.createCpeRequest(attempts));
    }

    @Test
    void rejectsNonPositiveIdentifiers() {
        assertBadRequest(() -> validator.id(0L));
        assertBadRequest(() -> validator.id(null));
        assertEquals(ID, validator.id(ID));
    }

    @Test
    void appliesPagingDefaults() {
        StatePage page = validator.statePage(1, null, null);
        assertEquals(0L, page.afterId());
        assertEquals(DEFAULT_SIZE, page.size());
    }

    @Test
    void rejectsInvalidPaging() {
        assertBadRequest(() -> validator.statePage(0, null, null));
        assertBadRequest(() -> validator.statePage(1, -1L, null));
        assertBadRequest(() -> validator.statePage(1, null, 0));
        assertBadRequest(() -> validator.statePage(1, null, OVER_MAX_SIZE));
    }

    @Test
    void requiresAllUrlsUnlessTheStatusIsRejected() {
        assertBadRequest(() -> validator.registerCpeQueryResult(ID, register(APPROVED, null)));
        assertNull(validator.registerCpeQueryResult(ID, register(REJECTED, null)));
        assertNull(validator.registerCpeQueryResult(ID, register(APPROVED, URL)));
    }

    @Test
    void rejectsUrlsLongerThanTheContractLimit() {
        assertBadRequest(() -> validator.registerCpeQueryResult(ID, register(REJECTED, "u".repeat(OVER_LENGTH))));
    }

    @Test
    void serializesTheQueryResponsePayloadAsJson() {
        RegisterCpeQueryResultRequest request = register(APPROVED, URL);
        request.setQueryResponsePayload(Map.of("ok", Boolean.TRUE));
        assertEquals("{\\"ok\\":true}", validator.registerCpeQueryResult(ID, request));
    }
}'''

MAPPER_TEST = '''class CpeRequestMapperTest {
    private static final Long ID = 10L;
    private static final Long NEXT_ID = 11L;
    private static final LocalDateTime NOW = LocalDateTime.of(2026, 1, 1, 10, 0);

    private final CpeRequestMapper mapper = new CpeRequestMapper();

    private CpeRequestEntity row(Long id) {
        CpeRequestEntity row = new CpeRequestEntity();
        row.setId(id);
        row.setSeries("F001");
        row.setCorrelative(ID);
        row.setUniqueReferenceCod("REF");
        row.setEpdTypeId(1);
        row.setEpdQueryStatusId(2);
        row.setDisagreementFlag(1);
        return row;
    }

    @Test
    void mapsTheCreateRequestToTheEntityWithAuditData() {
        CreateCpeRequest request = new CreateCpeRequest();
        request.setReferenceCode("REF");
        request.setSeries("F001");
        CpeRequestEntity entity = mapper.toEntity(request, "user", NOW);
        assertEquals("REF", entity.getUniqueReferenceCod());
        assertEquals("user", entity.getCreationUser());
        assertEquals(NOW, entity.getCreationDate());
    }

    @Test
    void copiesTheHistoryColumnsFromTheSavedRequest() {
        CpeRequestHistEntity history = mapper.toHistory(row(ID));
        assertEquals(ID, history.getEpdRequestId());
        assertEquals(2, history.getEpdQueryStatusId());
    }

    @Test
    void createResponseCarriesTheCreatedStatusAndTheId() {
        CreateCpeRequestResponse response = mapper.createResponse(ID);
        assertEquals(HttpStatus.CREATED.value(), response.getCode());
        assertEquals(ID, response.getData().getEpdRequestId());
    }

    @Test
    void emissionResponseExposesTheDisagreementFlagAsText() {
        GetCpeEmissionResponse response = mapper.emissionResponse(row(ID));
        assertEquals("1", response.getData().getDisagreementFlag());
        assertEquals("REF", response.getData().getReferenceCode());
    }

    @Test
    void stateResponseCarriesTheLastIdAsNextAfterId() {
        GetCpeEmissionsByStateResponse response = mapper.stateResponse(List.of(row(ID), row(NEXT_ID)));
        assertEquals(2, response.getData().size());
        assertEquals(NEXT_ID, response.getData().get(0).getNextAfterId());
        assertEquals(2, response.getData().get(0).getStatus());
    }

    @Test
    void emptyStateResponseHasNoItems() {
        assertTrue(mapper.stateResponse(List.of()).getData().isEmpty());
    }

    @Test
    void writeResponsesCarrySuccessAndRows() {
        RegisterCpeQueryResultResponse register = mapper.registerResponse(1, ID);
        assertTrue(register.getData().getSuccess());
        assertEquals(ID, register.getData().getEpdQueryId());
        assertEquals(0, mapper.statusResponse(0).getData().getUpdatedRows());
    }
}'''

HANDLER_TEST = '''class GlobalExceptionHandlerTest {
    private final GlobalExceptionHandler handler = new GlobalExceptionHandler(new PersistenceExceptionTranslator());

    private ServletWebRequest request(String method, String uri) {
        return new ServletWebRequest(new MockHttpServletRequest(method, uri));
    }

    @Test
    void badRequestUsesTheContractShape() {
        ResponseEntity<ErrorResponse> response = handler.operationFailure(ServiceOperationException.badRequest("x"), request("POST", "/api/v1/cpe-requests"));
        assertEquals(HttpStatus.BAD_REQUEST.value(), response.getStatusCode().value());
        assertEquals("IDF1", response.getBody().getSubType());
        assertEquals("MissingParameters", response.getBody().getType());
        assertEquals("PROCESPOST_CPE_REQUEST_SERVICE_ERROR", response.getBody().getMessage());
    }

    @Test
    void messageDependsOnTheOperation() {
        assertEquals("PROCESGET_CPE_REQUEST_SERVICE_ERROR", message("GET", "/api/v1/cpe-requests"));
        assertEquals("PROCESGETID_CPE_REQUEST_SERVICE_ERROR", message("GET", "/api/v1/emisiones/1"));
        assertEquals("PROCESPATCH_CPE_REQUEST_SERVICE_ERROR", message("PATCH", "/api/v1/emisiones/1"));
        assertEquals("PROCESGETSTATE_CPE_REQUEST_SERVICE_ERROR", message("GET", "/api/v1/emisiones/estado/1"));
        assertEquals("PROCESPATCHID_CPE_REQUEST_SERVICE_ERROR", message("PATCH", "/api/v1/emisiones/1/estado"));
    }

    private String message(String method, String uri) {
        return handler.operationFailure(ServiceOperationException.badRequest("x"), request(method, uri)).getBody().getMessage();
    }

    @Test
    void notFoundIsDeclaredForReadsAndPatchButNotForPost() {
        ServiceOperationException notFound = new ServiceOperationException(HttpStatus.NOT_FOUND, "none");
        assertEquals(HttpStatus.NOT_FOUND.value(), handler.operationFailure(notFound, request("GET", "/api/v1/cpe-requests")).getStatusCode().value());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), handler.operationFailure(notFound, request("POST", "/api/v1/cpe-requests")).getStatusCode().value());
    }

    @Test
    void conflictIsDeclaredForPostAndPatchButNotForGet() {
        ServiceOperationException conflict = new ServiceOperationException(HttpStatus.CONFLICT, "dup");
        assertEquals(HttpStatus.CONFLICT.value(), handler.operationFailure(conflict, request("POST", "/api/v1/cpe-requests")).getStatusCode().value());
        assertEquals(HttpStatus.CONFLICT.value(), handler.operationFailure(conflict, request("PATCH", "/api/v1/emisiones/1/estado")).getStatusCode().value());
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), handler.operationFailure(conflict, request("GET", "/api/v1/emisiones/1")).getStatusCode().value());
    }

    @Test
    void uniqueViolationBecomesConflictAndOtherFailuresInternalError() {
        DataIntegrityViolationException unique = new DataIntegrityViolationException("dup", new SQLException("dup", "23000", 1));
        assertEquals(HttpStatus.CONFLICT.value(), handler.unexpectedFailure(unique, request("POST", "/api/v1/cpe-requests")).getStatusCode().value());
        ResponseEntity<ErrorResponse> other = handler.unexpectedFailure(new IllegalStateException("boom"), request("GET", "/api/v1/cpe-requests"));
        assertEquals(HttpStatus.INTERNAL_SERVER_ERROR.value(), other.getStatusCode().value());
        assertEquals("IDT3", other.getBody().getSubType());
    }

    @Test
    void timeoutBecomesGatewayTimeout() {
        ServiceOperationException timeout = new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "slow");
        ResponseEntity<ErrorResponse> response = handler.operationFailure(timeout, request("GET", "/api/v1/cpe-requests"));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT.value(), response.getStatusCode().value());
        assertEquals("IDT1", response.getBody().getSubType());
    }
}'''

SERVICE_TEST = '''class CpeRequestServiceImplTest {
    private static final Long ID = 10L;
    private static final Long NEXT_ID = 11L;
    private static final Long QUERY_ID = 20L;
    private static final Long REFERENCE = 123L;
    private static final Integer STATE = 1;
    private static final Integer APPROVED = 3;
    private static final Integer REJECTED = 7;
    private static final int PAGE_SIZE = 2;
    private static final int DEFAULT_SIZE = 50;
    private static final int MAX_SIZE = 100;
    private static final String USER = "user";
    private static final String URL = "http://host/doc";

    private final CpeRequestRepository repository = Mockito.mock(CpeRequestRepository.class);
    private final CpeRequestHistRepository historyRepository = Mockito.mock(CpeRequestHistRepository.class);
    private final CpeQueryRepository queryRepository = Mockito.mock(CpeQueryRepository.class);
    private final CpeQueryStatusRepository statusRepository = Mockito.mock(CpeQueryStatusRepository.class);
    private final Clock clock = Clock.fixed(Instant.parse("2026-01-01T10:00:00Z"), ZoneOffset.UTC);
    private final TransactionTemplate transactions = new TransactionTemplate(Mockito.mock(PlatformTransactionManager.class));
    private final CpeRequestServiceImpl service = new CpeRequestServiceImpl(repository, historyRepository, queryRepository, statusRepository,
            new CpeRequestMapper(), new CpeRequestValidator(DEFAULT_SIZE, MAX_SIZE), new PersistenceExceptionTranslator(), transactions, clock);
    private final RequestHeaders headers = new RequestHeaders("tx", USER, "app");

    private CreateCpeRequest createRequest() {
        CreateCpeRequest request = new CreateCpeRequest();
        request.setSeries("F001");
        request.setCorrelative(ID);
        request.setReferenceCode("REF");
        request.setEpdTypeId(1);
        request.setEpdQueryStatusId(1);
        request.setGenerationType(1);
        request.setActionType(1);
        request.setInputPayload("{}");
        request.setAttemptNumber(0);
        request.setDisagreementFlag(0);
        return request;
    }

    private CpeRequestEntity row(Long id, Integer status) {
        CpeRequestEntity row = new CpeRequestEntity();
        row.setId(id);
        row.setEpdQueryStatusId(status);
        return row;
    }

    private CpeQueryStatusEntity status(int enabled) {
        CpeQueryStatusEntity entity = new CpeQueryStatusEntity();
        entity.setStatus(enabled);
        return entity;
    }

    private RegisterCpeQueryResultRequest register(Integer status, String url) {
        RegisterCpeQueryResultRequest request = new RegisterCpeQueryResultRequest();
        request.setEpdQueryStatusId(status);
        request.setPdfUrl(url);
        request.setXmlUrl(url);
        request.setCdrUrl(url);
        return request;
    }

    private UpdateCpeEmissionStatusRequest statusRequest(Integer status) {
        UpdateCpeEmissionStatusRequest request = new UpdateCpeEmissionStatusRequest();
        request.setEpdQueryStatusId(status);
        return request;
    }

    private void stubInsert() {
        Mockito.when(repository.saveAndFlush(ArgumentMatchers.any(CpeRequestEntity.class))).thenAnswer(invocation -> {
            CpeRequestEntity entity = invocation.getArgument(0);
            entity.setId(ID);
            return entity;
        });
    }

    @Test
    void createInsertsTheRequestAndItsHistory() {
        stubInsert();
        CreateCpeRequestResponse response = service.createCpeRequest(headers, createRequest());
        assertEquals(HttpStatus.CREATED.value(), response.getCode());
        assertEquals(ID, response.getData().getEpdRequestId());
        Mockito.verify(historyRepository).saveAndFlush(ArgumentMatchers.any(CpeRequestHistEntity.class));
    }

    @Test
    void createContinuesWhenTheHistoryInsertFails() {
        stubInsert();
        Mockito.when(historyRepository.saveAndFlush(ArgumentMatchers.any(CpeRequestHistEntity.class))).thenThrow(new DataIntegrityViolationException("history"));
        assertEquals(ID, service.createCpeRequest(headers, createRequest()).getData().getEpdRequestId());
    }

    @Test
    void createTranslatesAUniqueViolationToConflict() {
        Mockito.when(repository.saveAndFlush(ArgumentMatchers.any(CpeRequestEntity.class)))
                .thenThrow(new DataIntegrityViolationException("dup", new SQLException("dup", "23000", 1)));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.createCpeRequest(headers, createRequest()));
        assertEquals(HttpStatus.CONFLICT, failure.getStatus());
    }

    @Test
    void createRejectsAnInvalidBodyWithoutTouchingTheDatabase() {
        CreateCpeRequest invalid = createRequest();
        invalid.setSeries(null);
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.createCpeRequest(headers, invalid));
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
        Mockito.verifyNoInteractions(repository);
    }

    @Test
    void getByReferenceReturnsTheRequest() {
        CpeRequestEntity row = row(ID, 1);
        row.setUniqueReferenceCod(String.valueOf(REFERENCE));
        Mockito.when(repository.findFirstByUniqueReferenceCodOrderByIdAsc(String.valueOf(REFERENCE))).thenReturn(Optional.of(row));
        GetCpeRequestByReferenceResponse response = service.getCpeRequestByReferenceCode(headers, REFERENCE);
        assertEquals(ID, response.getData().getEpdRequestId());
        assertEquals(String.valueOf(REFERENCE), response.getData().getUniqueReferenceCode());
    }

    @Test
    void getByReferenceFailsWithNotFound() {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.getCpeRequestByReferenceCode(headers, REFERENCE));
        assertEquals(HttpStatus.NOT_FOUND, failure.getStatus());
    }

    @Test
    void getByIdReturnsTheEmissionAndRejectsInvalidIdentifiers() {
        Mockito.when(repository.findById(ID)).thenReturn(Optional.of(row(ID, 1)));
        assertEquals(ID, service.getCpeEmissionById(headers, ID).getData().getId());
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.getCpeEmissionById(headers, 0L));
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
    }

    @Test
    void getByStateReturnsTheBatchWithTheCursor() {
        Mockito.when(statusRepository.findById(Long.valueOf(STATE))).thenReturn(Optional.of(status(1)));
        Mockito.when(repository.findByEpdQueryStatusIdAndIdGreaterThanOrderByIdAsc(ArgumentMatchers.eq(STATE), ArgumentMatchers.eq(0L), ArgumentMatchers.any(Pageable.class)))
                .thenReturn(List.of(row(ID, STATE), row(NEXT_ID, STATE)));
        GetCpeEmissionsByStateResponse response = service.getCpeEmissionsByState(headers, STATE, null, PAGE_SIZE);
        assertEquals(PAGE_SIZE, response.getData().size());
        assertEquals(NEXT_ID, response.getData().get(0).getNextAfterId());
    }

    @Test
    void getByStateRejectsAnUnknownState() {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> service.getCpeEmissionsByState(headers, STATE, null, null));
        assertEquals(HttpStatus.BAD_REQUEST, failure.getStatus());
    }

    @Test
    void registerUpdatesTheStatusAndInsertsTheQuery() {
        CpeRequestEntity row = row(ID, 1);
        Mockito.when(repository.findForUpdateById(ID)).thenReturn(Optional.of(row));
        Mockito.when(statusRepository.findById(Long.valueOf(APPROVED))).thenReturn(Optional.of(status(1)));
        Mockito.when(queryRepository.saveAndFlush(ArgumentMatchers.any(CpeQueryEntity.class))).thenAnswer(invocation -> {
            CpeQueryEntity query = invocation.getArgument(0);
            query.setId(QUERY_ID);
            return query;
        });
        RegisterCpeQueryResultResponse response = service.registerCpeQueryResult(headers, ID, register(APPROVED, URL));
        assertEquals(QUERY_ID, response.getData().getEpdQueryId());
        assertEquals(1, response.getData().getUpdatedRows());
        assertEquals(APPROVED, row.getEpdQueryStatusId());
        assertEquals(USER, row.getLastModifiedUser());
    }

    @Test
    void registerDoesNotInsertTheQueryWhenTheStatusIsRejected() {
        Mockito.when(repository.findForUpdateById(ID)).thenReturn(Optional.of(row(ID, 1)));
        Mockito.when(statusRepository.findById(Long.valueOf(REJECTED))).thenReturn(Optional.of(status(1)));
        RegisterCpeQueryResultResponse response = service.registerCpeQueryResult(headers, ID, register(REJECTED, null));
        assertNull(response.getData().getEpdQueryId());
        Mockito.verifyNoInteractions(queryRepository);
    }

    @Test
    void registerFailsForMissingRequestsAndDisabledStatuses() {
        ServiceOperationException missing = assertThrows(ServiceOperationException.class, () -> service.registerCpeQueryResult(headers, ID, register(APPROVED, URL)));
        assertEquals(HttpStatus.NOT_FOUND, missing.getStatus());
        Mockito.when(repository.findForUpdateById(ID)).thenReturn(Optional.of(row(ID, 1)));
        Mockito.when(statusRepository.findById(Long.valueOf(APPROVED))).thenReturn(Optional.of(status(0)));
        ServiceOperationException disabled = assertThrows(ServiceOperationException.class, () -> service.registerCpeQueryResult(headers, ID, register(APPROVED, URL)));
        assertEquals(HttpStatus.BAD_REQUEST, disabled.getStatus());
    }

    @Test
    void statusChangeUpdatesOneRowAndIsIdempotentForTheSameStatus() {
        CpeRequestEntity row = row(ID, 1);
        Mockito.when(repository.findById(ID)).thenReturn(Optional.of(row));
        Mockito.when(statusRepository.findById(Long.valueOf(APPROVED))).thenReturn(Optional.of(status(1)));
        assertEquals(1, service.updateCpeEmissionStatus(headers, ID, statusRequest(APPROVED)).getData().getUpdatedRows());
        assertEquals(APPROVED, row.getEpdQueryStatusId());
        assertEquals(0, service.updateCpeEmissionStatus(headers, ID, statusRequest(APPROVED)).getData().getUpdatedRows());
        Mockito.verify(repository, Mockito.times(1)).saveAndFlush(ArgumentMatchers.any(CpeRequestEntity.class));
    }

    @Test
    void statusChangeFailsForMissingRequestsAndUnknownStatuses() {
        ServiceOperationException missing = assertThrows(ServiceOperationException.class, () -> service.updateCpeEmissionStatus(headers, ID, statusRequest(APPROVED)));
        assertEquals(HttpStatus.NOT_FOUND, missing.getStatus());
        Mockito.when(repository.findById(ID)).thenReturn(Optional.of(row(ID, 1)));
        ServiceOperationException unknown = assertThrows(ServiceOperationException.class, () -> service.updateCpeEmissionStatus(headers, ID, statusRequest(APPROVED)));
        assertEquals(HttpStatus.BAD_REQUEST, unknown.getStatus());
    }
}'''

CONTROLLER_TEST = '''class CpeRequestApiContractTest {
    private static final Long ID = 10L;

    private final CpeRequestService service = Mockito.mock(CpeRequestService.class);
    private final MockMvc mvc = MockMvcBuilders.standaloneSetup(new CpeRequestController(service))
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
    void postReturnsCreated() throws Exception {
        CreateCpeRequestData data = new CreateCpeRequestData();
        data.setEpdRequestId(ID);
        CreateCpeRequestResponse response = new CreateCpeRequestResponse();
        response.setCode(HttpStatus.CREATED.value());
        response.setMessage("ok");
        response.setData(data);
        Mockito.when(service.createCpeRequest(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.any(CreateCpeRequest.class))).thenReturn(response);
        mvc.perform(withHeaders(post("/api/v1/cpe-requests")).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.data.epdRequestId").value(ID.intValue()));
    }

    @Test
    void aMissingRequiredHeaderIsABadRequestWithTheContractError() throws Exception {
        mvc.perform(get("/api/v1/cpe-requests").param("referenceCode", "1"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.subType").value("IDF1"));
    }

    @Test
    void notFoundIsReportedWithTheOperationMessage() throws Exception {
        Mockito.when(service.getCpeEmissionById(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(ID)))
                .thenThrow(new ServiceOperationException(HttpStatus.NOT_FOUND, "none"));
        mvc.perform(withHeaders(get("/api/v1/emisiones/" + ID)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.message").value("PROCESGETID_CPE_REQUEST_SERVICE_ERROR"));
    }

    @Test
    void patchRoutesToTheStatusChange() throws Exception {
        UpdateCpeEmissionStatusResponse response = new UpdateCpeEmissionStatusResponse();
        response.setCode(HttpStatus.OK.value());
        Mockito.when(service.updateCpeEmissionStatus(ArgumentMatchers.any(RequestHeaders.class), ArgumentMatchers.eq(ID), ArgumentMatchers.any(UpdateCpeEmissionStatusRequest.class)))
                .thenReturn(response);
        mvc.perform(withHeaders(patch("/api/v1/emisiones/" + ID + "/estado")).contentType(MediaType.APPLICATION_JSON).content("{\\"epdQueryStatusId\\":3}"))
                .andExpect(status().isOk());
    }
}'''

MVC_STATICS = ['org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get', 'org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch',
               'org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post', 'org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath',
               'org.springframework.test.web.servlet.result.MockMvcResultMatchers.status']

dj.register('validation', 'CpeRequestValidatorTest')


def build_tests(pkg):
    files = {}

    def put(suffix, name, body, statics=ASSERT):
        files[f'src/test/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/")}/{name}.java'] = dj.finalize(pkg, suffix, body, statics)
    put('validation', 'CpeRequestValidatorTest', VALIDATOR_TEST)
    put('dto.mapper', 'CpeRequestMapperTest', MAPPER_TEST)
    put('exception', 'GlobalExceptionHandlerTest', HANDLER_TEST)
    put('service.impl', 'CpeRequestServiceImplTest', SERVICE_TEST)
    put('controller', 'CpeRequestApiContractTest', CONTROLLER_TEST, MVC_STATICS)
    return files
