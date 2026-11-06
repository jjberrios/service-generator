"""Flow tests of the remote-orchestration pattern and the assembly of the whole test set (`build_tests`)."""
import re

import remote_orchestration_java as rj
import remote_orchestration_tests as t

LOOKUP = {'AgreementRequestClient': 'agreementRequestClient', 'FinancingAgreementClient': 'financingAgreementClient', 'FinancingInstallmentClient': 'financingInstallmentClient',
          'RangeQuoteClient': 'rangeQuoteClient', 'CollectionIntegrationClient': 'collectionIntegrationClient', 'InstallmentSynchronizationClient': 'installmentSynchronizationClient',
          'ParametersClient': 'parametersClient'}

FIN = "'financingStateCodeId': 2, 'clientCode': 'C1', 'documentCodeId': 1, 'documentNumber': '123', 'saleOrder': 'OV1', 'productCode': 'PR', 'line': '999'"
ANY = 'any(), any(), any(), any()'

FLOWS = {}
FLOWS['1'] = ('PreFinancingFlow', '''    private AgreementRequest request(String save, String credit) {
        AgreementRequest request = Fixtures.request(1L);
        request.setSaveRequest(save);
        request.setDebtAmount(new BigDecimal("1500"));
        request.setAmountInitialQuote(new BigDecimal("100"));
        request.setQuotesNumber(12L);
        request.setFixedAmount(new BigDecimal("69.9"));
        request.setCreditLimit(new BigDecimal(credit));
        return request;
    }

    @Test
    void calculatesTheQuoteAndRegistersTheRequest() {
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'requestCodeId': 1001}}"));
        AgreementResponseData data = flow.execute(Fixtures.context(request("S", "300"), Map.of()));
        assertEquals(1001L, data.getRequestCodeId());
        assertEquals(new BigDecimal("1400"), data.getAmountFinanced());
        assertEquals(new BigDecimal("116.67"), data.getQuoteAmount());
    }

    @Test
    void doesNotRegisterTheRequestWhenItIsNotSaved() {
        AgreementResponseData data = flow.execute(Fixtures.context(request("N", "300"), Map.of()));
        assertNull(data.getRequestCodeId());
        verify(agreementRequestClient, never()).create(__ANY__);
    }

    @Test
    void insufficientPaymentCapacityIsRejected() {
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> flow.execute(Fixtures.context(request("S", "100"), Map.of())));
        assertEquals("IDF401", failure.getSubType());
        verify(agreementRequestClient, never()).create(__ANY__);
    }''')
FLOWS['2'] = ('FinancingFlow', '''    private static final String REQUEST = "{'data': [{'requestCodeId': 1001, 'requestType': 1, 'financingStateCodeId': 1, 'saleOrder': 'OV1', 'saleChannel': 'CAC', 'clientCode': 'C1',"
            + " 'amountInitialQuote': 0, 'debtAmount': 1500, 'createdAt': '2026-11-06T10:00:00Z'}]}";

    private AgreementRequest request() {
        AgreementRequest request = Fixtures.request(2L);
        request.setRequestCodeId(1001L);
        request.setClientCode("C1");
        return request;
    }

    private void happyDependencies() {
        when(agreementRequestClient.get(__ANY__)).thenReturn(Fixtures.ok(REQUEST));
        when(financingAgreementClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'agreementCodeId': 5001}}"));
        when(agreementRequestClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
    }

    @Test
    void registersTheFinancingAssociatesTheRequestAndGeneratesTheInstallments() {
        happyDependencies();
        when(financingInstallmentClient.generate(__ANY__)).thenReturn(Fixtures.created("{'data': {'installments': [{'quoteNumber': 1, 'quoteFormat': 'N1', 'quoteAmount': 10}]}}"));
        AgreementResponseData data = flow.execute(Fixtures.context(request(), Map.of("vigenciaRegistroSolicitudEnHoras", "24")));
        assertEquals(5001L, data.getAgreementCodeId());
        assertEquals(1, data.getInstallments().size());
        assertEquals("N1", data.getInstallments().get(0).getQuoteFormat());
    }

    @Test
    void aFailedGenerationRevertsTheRequestAndDeletesTheFinancing() {
        happyDependencies();
        when(financingInstallmentClient.generate(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"));
        when(financingAgreementClient.delete(__ANY__)).thenReturn(Fixtures.ok("{}"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> flow.execute(Fixtures.context(request(), Map.of("vigenciaRegistroSolicitudEnHoras", "24"))));
        assertEquals("IDF412", failure.getSubType());
        verify(agreementRequestClient, times(2)).update(__ANY__);
        verify(financingAgreementClient).delete(__ANY__);
    }

    @Test
    void anExpiredPreFinancingRequestIsRejectedBeforeCreatingAnything() {
        happyDependencies();
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> flow.execute(Fixtures.context(request(), Map.of("vigenciaRegistroSolicitudEnHoras", "1"))));
        assertEquals("IDF407", failure.getSubType());
        verify(financingAgreementClient, never()).create(__ANY__);
    }

    @Test
    void aDeliveredProductConfirmsTheFinancing() {
        AgreementRequest request = Fixtures.request(2L);
        request.setIsDelivered(1L);
        request.setAgreementCodeId(5001L);
        when(financingAgreementClient.get(__ANY__)).thenReturn(Fixtures.ok("{'data': {'financingStateCodeId': 1}}"));
        when(financingAgreementClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        assertEquals(5001L, flow.execute(Fixtures.context(request, Map.of())).getAgreementCodeId());
    }

    @Test
    void aFinancingThatIsNotRequestedCannotBeConfirmed() {
        AgreementRequest request = Fixtures.request(2L);
        request.setIsDelivered(1L);
        request.setAgreementCodeId(5001L);
        when(financingAgreementClient.get(__ANY__)).thenReturn(Fixtures.ok("{'data': {'financingStateCodeId': 2}}"));
        assertEquals("IDF390", assertThrows(ServiceOperationException.class, () -> flow.execute(Fixtures.context(request, Map.of()))).getSubType());
    }''')
FLOWS['3'] = ('PreRefinancingFlow', '''    private static final Map<String, String> SETTINGS = Map.of("MaximoPeriodoRefinanciamiento", "12", "PorcentajeMinimoCuotaInicialClienteServActivo", "10",
            "PorcentajeMinimoCuotaInicialClienteServSuspendido", "20", "PorcentajeMinimoCuotaInicialClienteServDesactivo", "30");

    private FlowContext context(String saveRequest) {
        AgreementRequest request = Fixtures.request(3L);
        request.setSaveRequest(saveRequest);
        request.setStateLine("1");
        request.setDebtAmount(new BigDecimal("2000"));
        request.setAmountFinanced(new BigDecimal("700"));
        request.setCreditLimit(new BigDecimal("300"));
        request.setFixedAmount(new BigDecimal("69.9"));
        FlowContext ctx = Fixtures.context(request, SETTINGS);
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__}}"));
        return ctx;
    }

    private void dependencies(String installments, String active) {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': " + installments + "}"));
        when(financingAgreementClient.numberOfRefinancings(__ANY__)).thenReturn(Fixtures.ok("{'data': {'activeRefinancingCount': " + active + ", 'completedRefinancingCountInPeriod': 0}}"));
        when(rangeQuoteClient.quotes(__ANY__)).thenReturn(Fixtures.ok("{'data': {'quotesNumber': 12}}"));
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'requestCodeId': 2001}}"));
    }

    private static final String ENOUGH = "[{'quoteStateCodeId': 3}, {'quoteStateCodeId': 3}, {'quoteStateCodeId': 2}]";

    @Test
    void calculatesTheRefinancingAndRegistersTheRequest() {
        dependencies(ENOUGH, "0");
        AgreementResponseData data = flow.execute(context("S"));
        assertEquals(2001L, data.getRequestCodeId());
        assertEquals(new BigDecimal("1300"), data.getAmountInitialQuote().setScale(0));
        assertEquals(new BigDecimal("58.33"), data.getQuoteAmount());
        assertEquals(12L, data.getQuotesNumber());
        assertEquals(new BigDecimal("65.00"), data.getPercentage());
    }

    @Test
    void needsAtLeastTwoPaidInstallments() {
        dependencies("[{'quoteStateCodeId': 3}, {'quoteStateCodeId': 2}]", "0");
        assertEquals("IDF424", assertThrows(ServiceOperationException.class, () -> flow.execute(context("S"))).getSubType());
    }

    @Test
    void anActiveRefinancingBlocksTheRequest() {
        dependencies(ENOUGH, "1");
        assertEquals("IDF426", assertThrows(ServiceOperationException.class, () -> flow.execute(context("S"))).getSubType());
    }

    @Test
    void theRequestIsNotSavedWhenTheIndicatorSaysNo() {
        dependencies(ENOUGH, "0");
        assertNull(flow.execute(context("N")).getRequestCodeId());
        verify(agreementRequestClient, never()).create(__ANY__);
    }''')
FLOWS['4'] = ('RefinancingFlow', '''    private static final String REQUEST = "{'data': [{'requestCodeId': 2001, 'financingStateCodeId': 1, 'createdAt': '2026-11-06T10:00:00Z', 'saleOrder': 'OV1'}]}";

    private FlowContext context() {
        AgreementRequest request = Fixtures.request(4L);
        request.setAgreementCodeId(5001L);
        request.setRequestCodeId(2001L);
        FlowContext ctx = Fixtures.context(request, Map.of("vigenciaRegistroSolicitudEnHoras", "24"));
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__}}"));
        return ctx;
    }

    private void dependencies() {
        when(agreementRequestClient.get(__ANY__)).thenReturn(Fixtures.ok(REQUEST));
        when(financingAgreementClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'agreementCodeId': 6001}}"));
        when(agreementRequestClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(financingAgreementClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 1, 'quoteNumber': 1}]}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(installmentSynchronizationClient.synchronize(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(financingAgreementClient.delete(__ANY__)).thenReturn(Fixtures.ok("{}"));
    }

    @Test
    void createsTheNewFinancingAndCancelsTheOriginalOne() {
        dependencies();
        when(financingInstallmentClient.generate(__ANY__)).thenReturn(Fixtures.created("{'data': {'installments': [{'quoteNumber': 1}]}}"));
        AgreementResponseData data = flow.execute(context());
        assertEquals(6001L, data.getAgreementCodeId());
        assertEquals(1, data.getInstallments().size());
        verify(installmentSynchronizationClient).synchronize(__ANY__);
    }

    @Test
    void aFailedGenerationRevertsTheRequestAndDeletesTheNewFinancing() {
        dependencies();
        when(financingInstallmentClient.generate(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"));
        assertEquals("IDF437", assertThrows(ServiceOperationException.class, () -> flow.execute(context())).getSubType());
        verify(financingAgreementClient).delete(__ANY__);
        verify(financingInstallmentClient, never()).update(__ANY__);
    }

    @Test
    void anAssignedPreRefinancingRequestIsRejected() {
        dependencies();
        when(agreementRequestClient.get(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'financingStateCodeId': 1, 'agreementCodeId': 9, 'createdAt': '2026-11-06T10:00:00Z'}]}"));
        assertEquals("IDF433", assertThrows(ServiceOperationException.class, () -> flow.execute(context())).getSubType());
        verify(financingAgreementClient, never()).create(__ANY__);
    }''')
FLOWS['5'] = ('InstallmentCancellationFlow', '''    private FlowContext context() {
        AgreementRequest request = Fixtures.request(5L);
        request.setAgreementCodeId(5001L);
        request.setClientCode("C1");
        request.setReasonChange("return");
        FlowContext ctx = Fixtures.context(request, Map.of());
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__}}"));
        return ctx;
    }

    @Test
    void cancelsTheFinancingAndItsInstallments() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 20, 'quoteNumber': 0, 'quoteStateCodeId': 3}, {'quoteCodeId': 21, 'quoteNumber': 1, 'quoteStateCodeId': 2}]}"));
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'requestCodeId': 3001}}"));
        when(financingAgreementClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        AgreementResponseData data = flow.execute(context());
        assertEquals(3001L, data.getRequestCodeId());
        assertEquals(5001L, data.getAgreementCodeId());
        ArgumentCaptor<JsonNode> body = ArgumentCaptor.forClass(JsonNode.class);
        verify(financingInstallmentClient).update(any(), any(), any(), body.capture());
        assertEquals("6", body.getValue().path("installments").get(0).path("quoteStateCodeId").asText());
        assertEquals("4", body.getValue().path("installments").get(1).path("quoteStateCodeId").asText());
        verify(installmentSynchronizationClient).synchronize(__ANY__);
    }

    @Test
    void paidInstallmentsBlockTheCancellation() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 21, 'quoteNumber': 1, 'quoteStateCodeId': 3}]}"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> flow.execute(context()));
        assertEquals("IDF343", failure.getSubType());
        assertEquals(HttpStatus.CONFLICT, failure.getStatus());
        verify(agreementRequestClient, never()).create(__ANY__);
    }

    @Test
    void aFailedInstallmentUpdateRestoresTheFinancingAndDeletesTheRequest() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 21, 'quoteNumber': 1, 'quoteStateCodeId': 2}]}"));
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'requestCodeId': 3001}}"));
        when(financingAgreementClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"));
        assertEquals("IDF347", assertThrows(ServiceOperationException.class, () -> flow.execute(context())).getSubType());
        verify(financingAgreementClient, times(2)).update(__ANY__);
        verify(agreementRequestClient).delete(__ANY__);
    }''')
FLOWS['6'] = ('InstallmentTransferFlow', '''    private FlowContext context() {
        AgreementRequest request = Fixtures.request(6L);
        request.setAgreementCodeId(5001L);
        request.setCurrentDocumentCodeId(1L);
        request.setCurrentDocumentNumber("123");
        request.setDebtAmount(new BigDecimal("300"));
        request.setQuotesNumber(12L);
        request.setFixedAmount(new BigDecimal("69.9"));
        request.setCreditLimit(new BigDecimal("300"));
        FlowContext ctx = Fixtures.context(request, Map.of());
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__}}"));
        return ctx;
    }

    private static final String NOTIFIED = "{'data': [{'quoteCodeId': 31, 'quoteNumber': 1, 'quoteAmount': 100}, {'quoteCodeId': 32, 'quoteNumber': 2, 'quoteAmount': 200}]}";

    private void dependencies() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok(NOTIFIED));
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'requestCodeId': 7001}}"));
        when(financingAgreementClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'agreementCodeId': 8001}}"));
        when(financingInstallmentClient.generate(__ANY__)).thenReturn(Fixtures.created("{'data': {'installments': [{'quoteNumber': 1}]}}"));
        when(financingAgreementClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(installmentSynchronizationClient.synchronize(__ANY__)).thenReturn(Fixtures.ok("{}"));
    }

    @Test
    void movesTheDebtToTheNewFinancing() {
        dependencies();
        AgreementResponseData data = flow.execute(context());
        assertEquals(8001L, data.getAgreementCodeId());
        assertEquals(1, data.getInstallments().size());
    }

    @Test
    void theDebtMustEqualThePendingInstallments() {
        dependencies();
        AgreementRequest request = context().request();
        request.setDebtAmount(new BigDecimal("299"));
        FlowContext ctx = Fixtures.context(request, Map.of());
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__}}"));
        assertEquals("IDF444", assertThrows(ServiceOperationException.class, () -> flow.execute(ctx)).getSubType());
        verify(agreementRequestClient, never()).create(__ANY__);
    }

    @Test
    void theCurrentHolderMustOwnTheOriginFinancing() {
        dependencies();
        AgreementRequest request = context().request();
        request.setCurrentDocumentNumber("999");
        FlowContext ctx = Fixtures.context(request, Map.of());
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__}}"));
        assertEquals("IDF441", assertThrows(ServiceOperationException.class, () -> flow.execute(ctx)).getSubType());
    }

    @Test
    void aFailedInstallmentUpdateRunsTheWholeCompensationChain() {
        dependencies();
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"));
        when(financingAgreementClient.delete(__ANY__)).thenReturn(Fixtures.ok("{}"));
        assertEquals("IDF450", assertThrows(ServiceOperationException.class, () -> flow.execute(context())).getSubType());
        verify(financingAgreementClient, times(2)).update(__ANY__);
        verify(financingAgreementClient).delete(__ANY__);
        verify(agreementRequestClient).delete(__ANY__);
    }''')
FLOWS['7'] = ('ServiceCancellationFlow', '''    private FlowContext context() {
        AgreementRequest request = Fixtures.request(7L);
        request.setAgreementCodeId(5001L);
        request.setClientCode("C1");
        request.setCancellationTypeId(1L);
        FlowContext ctx = Fixtures.context(request, Map.of());
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__}}"));
        return ctx;
    }

    @Test
    void cancelsThePendingInstallmentsIssuedFromToday() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 41, 'quoteNumber': 1, 'quoteStateCodeId': 2, 'quoteIssueDate': '2026-11-06'},"
                + " {'quoteCodeId': 43, 'quoteNumber': 3, 'quoteStateCodeId': 3, 'quoteIssueDate': '2026-12-06'}]}"));
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.ok("{'data': {'requestCodeId': 4001}}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        AgreementResponseData data = flow.execute(context());
        assertEquals(4001L, data.getRequestCodeId());
        ArgumentCaptor<JsonNode> body = ArgumentCaptor.forClass(JsonNode.class);
        verify(financingInstallmentClient).update(any(), any(), any(), body.capture());
        assertEquals(1, body.getValue().path("installments").size());
        assertEquals("2026-11-06", body.getValue().path("installments").get(0).path("quoteExpirationDate").asText());
    }

    @Test
    void withoutEligibleInstallmentsNothingIsRegistered() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 43, 'quoteNumber': 3, 'quoteStateCodeId': 3, 'quoteIssueDate': '2026-12-06'}]}"));
        assertEquals("IDF353", assertThrows(ServiceOperationException.class, () -> flow.execute(context())).getSubType());
        verify(agreementRequestClient, never()).create(__ANY__);
    }

    @Test
    void aFailedUpdateDeletesTheRequest() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 41, 'quoteNumber': 1, 'quoteStateCodeId': 2, 'quoteIssueDate': '2026-11-06'}]}"));
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.ok("{'data': {'requestCodeId': 4001}}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"));
        assertEquals("IDF355", assertThrows(ServiceOperationException.class, () -> flow.execute(context())).getSubType());
        verify(agreementRequestClient).delete(__ANY__);
    }''')
FLOWS['8'] = ('BillingCycleChangeFlow', '''    private FlowContext context() {
        AgreementRequest request = Fixtures.request(8L);
        request.setAgreementCodeId(5001L);
        request.setClientCode("C1");
        request.setQuoteCycle("2026-12-05");
        FlowContext ctx = Fixtures.context(request, Map.of("DiasVencimientoCuota", "30"));
        ctx.remember("4.1", Fixtures.json("{'data': {__FIN__, 'quoteCycle': '2026-11-05'}}"));
        return ctx;
    }

    private void dependencies() {
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 11, 'quoteNumber': 2}, {'quoteCodeId': 10, 'quoteNumber': 1}]}"));
        when(agreementRequestClient.create(__ANY__)).thenReturn(Fixtures.created("{'data': {'requestCodeId': 4001}}"));
        when(financingAgreementClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
        when(installmentSynchronizationClient.synchronize(__ANY__)).thenReturn(Fixtures.ok("{}"));
    }

    @Test
    void movesTheInstallmentsToTheNewCycle() {
        dependencies();
        AgreementResponseData data = flow.execute(context());
        assertEquals(4001L, data.getRequestCodeId());
        assertEquals(5001L, data.getAgreementCodeId());
        ArgumentCaptor<JsonNode> body = ArgumentCaptor.forClass(JsonNode.class);
        verify(financingInstallmentClient).update(any(), any(), any(), body.capture());
        assertEquals("10", body.getValue().path("installments").get(0).path("quoteCodeId").asText());
        assertEquals("2026-12-05", body.getValue().path("installments").get(0).path("quoteIssueDate").asText());
        assertEquals("2027-01-04", body.getValue().path("installments").get(0).path("quoteExpirationDate").asText());
        assertEquals("2027-01-05", body.getValue().path("installments").get(1).path("quoteIssueDate").asText());
        verify(installmentSynchronizationClient).synchronize(__ANY__);
    }

    @Test
    void aNotificationFailureDoesNotChangeTheOutcome() {
        dependencies();
        when(installmentSynchronizationClient.synchronize(__ANY__)).thenThrow(ErrorCatalog.build(ErrorCatalog.UNAVAILABLE, "tros", "down", null));
        assertEquals(4001L, flow.execute(context()).getRequestCodeId());
    }

    @Test
    void aFailedInstallmentUpdateRestoresTheCycleAndDeletesTheRequest() {
        dependencies();
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"));
        when(agreementRequestClient.delete(__ANY__)).thenReturn(Fixtures.ok("{}"));
        assertEquals("IDF466", assertThrows(ServiceOperationException.class, () -> flow.execute(context())).getSubType());
        verify(financingAgreementClient, times(2)).update(__ANY__);
        verify(agreementRequestClient).delete(__ANY__);
    }

    @Test
    void withoutNotifiedInstallmentsNothingIsRegistered() {
        dependencies();
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': []}"));
        ServiceOperationException failure = assertThrows(ServiceOperationException.class, () -> flow.execute(context()));
        assertEquals("IDF461", failure.getSubType());
        verify(agreementRequestClient, never()).create(__ANY__);
    }

    @Test
    void theFinancingMustBeConfirmed() {
        dependencies();
        FlowContext ctx = Fixtures.context(Fixtures.request(8L), Map.of());
        ctx.remember("4.1", Fixtures.json("{'data': {'financingStateCodeId': 1}}"));
        assertEquals("IDF301", assertThrows(ServiceOperationException.class, () -> flow.execute(ctx)).getSubType());
    }''')

SYNC = ('InstallmentSynchronizationTest', '''    private FlowContext context() {
        AgreementRequest request = Fixtures.request(8L);
        request.setAgreementCodeId(5001L);
        request.setClientCode("C1");
        return Fixtures.context(request, Map.of());
    }

    private void dependencies(String collections) {
        when(financingAgreementClient.get(__ANY__)).thenReturn(Fixtures.ok("{'data': {'financingStateCodeId': 2}}"));
        when(collectionIntegrationClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': {'installments': " + collections + "}}"));
        when(financingInstallmentClient.list(__ANY__)).thenReturn(Fixtures.ok("{'data': [{'quoteCodeId': 10, 'quoteNumber': 0}, {'quoteCodeId': 11, 'quoteNumber': 1}]}"));
        when(financingInstallmentClient.update(__ANY__)).thenReturn(Fixtures.ok("{}"));
    }

    @Test
    void updatesTheInstallmentsPaidInCollections() {
        dependencies("[{'quoteNumber': 1, 'quoteStateCodeId': 3, 'paymentDate': '2026-10-01', 'quoteAmount': 100}]");
        FlowContext ctx = context();
        synchronization.run(ctx);
        ArgumentCaptor<JsonNode> body = ArgumentCaptor.forClass(JsonNode.class);
        verify(financingInstallmentClient).update(any(), any(), any(), body.capture());
        assertEquals("11", body.getValue().path("installments").get(0).path("quoteCodeId").asText());
        assertEquals("100", body.getValue().path("installments").get(0).path("paymentAmount").asText());
        assertEquals("2", ctx.field("4.1", "financingStateCodeId").asText());
    }

    @Test
    void doesNotUpdateWhenNothingWasPaid() {
        dependencies("[{'quoteNumber': 1, 'quoteStateCodeId': 2}]");
        synchronization.run(context());
        verify(financingInstallmentClient, never()).update(__ANY__);
    }

    @Test
    void aMissingFinancingIsReported() {
        when(financingAgreementClient.get(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.NOT_FOUND.value(), "{}"));
        assertEquals("IDF386", assertThrows(ServiceOperationException.class, () -> synchronization.run(context())).getSubType());
    }

    @Test
    void aCollectionsFailureIsASynchronizationError() {
        when(financingAgreementClient.get(__ANY__)).thenReturn(Fixtures.ok("{'data': {'financingStateCodeId': 2}}"));
        when(collectionIntegrationClient.list(__ANY__)).thenReturn(Fixtures.answer(HttpStatus.BAD_REQUEST.value(), "{}"));
        assertEquals("IDF388", assertThrows(ServiceOperationException.class, () -> synchronization.run(context())).getSubType());
    }''')


def class_with_mocks(plan, name, suffix, body, flow_class, client_services, statics, kind='flow'):
    clients = plan['orchestration']['clients']
    classes = [clients[s]['className'] for s in sorted(client_services)]
    mocks = [f'    private final {c} {LOOKUP[c]} = mock({c}.class);' for c in classes]
    new = f'new {flow_class}(' + ', '.join(LOOKUP[c] for c in classes) + ')'
    var = 'flow' if kind == 'flow' else 'synchronization'
    cls = flow_class
    field = f'    private final {cls} {var} = {new};'
    text = f'class {name} {{\n' + '\n'.join(mocks) + '\n' + field + '\n\n' + body.replace('__ANY__', ANY).replace('__FIN__', FIN) + '\n}'
    return text


def flow_clients(plan, flow):
    found = set()

    def visit(items):
        for s in items:
            if s['t'] == 'remote':
                found.add(s['client'])
            if s['t'] == 'branch':
                visit(s['then'])
                visit(s['else'])
    visit(flow['steps'])
    for name in flow['chains']:
        pass
    used = set()
    writer = rj.FlowWriter(plan)
    writer.used_chains = set()
    writer.statements_with_notify(flow['steps'], flow, 8)
    for name in writer.used_chains:
        for key in flow['chains'][name]:
            found.add(flow['compensations'][key]['client'])
    return found


def build_tests(plan):
    pkg = plan['service']['package']
    base = f'src/test/java/{pkg.replace(".", "/")}/'
    files = {}
    orch = plan['orchestration']
    contract = plan['contract']
    method = contract['operationId'][0].lower() + contract['operationId'][1:]

    def put(suffix, name, body, statics):
        files[f'{base}{suffix.replace(".", "/")}/{name}.java'] = rj.finalize(pkg, suffix, body, statics, t.EXTRA, hoist=True)
    for name in ('Fixtures', 'AgreementRequestValidatorTest', 'CalculationsTest', 'RulesTest', 'ErrorCatalogTest', 'SystemSettingsTest', 'RemoteGatewayTest', 'InstallmentSynchronizationTest',
                 'AgreementServiceImplTest', 'GlobalExceptionHandlerTest', 'AgreementApiContractTest', 'FlowContextTest'):
        pass
    for name, suffix in (('AgreementRequestValidatorTest', 'validation'), ('CalculationsTest', 'orchestration'), ('RulesTest', 'orchestration'), ('FlowContextTest', 'orchestration'),
                         ('Fixtures', 'orchestration')):
        pass
    rj.register('orchestration', 'Fixtures', *[f[0] + 'Test' for f in FLOWS.values()], 'InstallmentSynchronizationTest', 'CalculationsTest', 'RulesTest', 'FlowContextTest', 'SystemSettingsTest')
    put('orchestration', 'Fixtures', t.FIXTURES, t.ASSERT)
    put('validation', 'AgreementRequestValidatorTest', t.VALIDATOR_TEST, t.ASSERT)
    put('orchestration', 'CalculationsTest', t.CALCULATIONS_TEST, t.ASSERT)
    put('orchestration', 'RulesTest', t.RULES_TEST, t.ASSERT)
    codes = '\n'.join(f'        assertEquals(HttpStatus.valueOf({s["status"]}), ErrorCatalog.build("{c}", null, null, null).getStatus());' for c, s in sorted(contract['errors'].items()))
    put('exception', 'ErrorCatalogTest', t.ERROR_CATALOG_TEST.replace('__CODES__', codes), t.ASSERT)
    put('orchestration', 'SystemSettingsTest', t.SETTINGS_TEST.replace('__CONFIG_CODE__', orch['config']['outcome']['otherwise']), t.ASSERT + t.MOCKITO)
    put('client', 'RemoteGatewayTest', t.GATEWAY_TEST, t.ASSERT + t.MOCK_REST)
    put('orchestration', 'FlowContextTest', t.FLOW_CONTEXT_TEST, t.ASSERT + t.MOCKITO)
    put('service.impl', 'AgreementServiceImplTest', t.SERVICE_TEST.replace('__METHOD__', method).replace('__SUCCESS__', contract['successMessage']), t.ASSERT + t.MOCKITO)
    put('exception', 'GlobalExceptionHandlerTest', t.HANDLER_TEST, t.ASSERT)
    put('controller', 'AgreementApiContractTest', t.CONTRACT_TEST.replace('__METHOD__', method).replace('__PATH__', contract['path']).replace('__SUCCESS__', contract['successMessage']),
        t.ASSERT + t.MOCKITO + t.MVC)
    sync_flow = {'steps': orch['sync'], 'chains': {}, 'compensations': {}, 'prerequisite': None}
    sync_text = class_with_mocks(plan, 'InstallmentSynchronizationTest', 'orchestration', SYNC[1], 'InstallmentSynchronization', flow_clients(plan, sync_flow), None, 'sync')
    put('orchestration', 'InstallmentSynchronizationTest', sync_text, t.ASSERT + t.MOCKITO)
    for type_id, (cls, body) in FLOWS.items():
        flow = orch['flows'][type_id]
        text = class_with_mocks(plan, cls + 'Test', 'orchestration', body, cls, flow_clients(plan, flow), None)
        put('orchestration', cls + 'Test', text, t.ASSERT + t.MOCKITO)
    return files
