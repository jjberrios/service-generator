"""Java sources of the financingAgreement service (typed, evidence-cited model of the cleared Sparx/OpenAPI behaviour).

Every file is a pure text template rendered through `dom_cpe_request_java.finalize` (imports added by use, accents written as unicode escapes, ASCII-only bytes).
Nothing here reads the file system. The model below is verified against the workspace evidence (OpenAPI + authoritative Sparx) by `financing_agreement_materializer`.
"""
import re
import unicodedata

import dom_cpe_request_java as dj

PACKAGE = 'com.claro.financingagreement'
APPLICATION_CLASS = 'FinancingAgreementApplication'
SERVICE_MESSAGE = 'FINANCINGAGREEMENT_SERVICE_ERROR'
SERVICE_LANE = 'FINANDB'

dj.EXTERNAL.update({
    'BigDecimal': 'java.math.BigDecimal', 'LocalDate': 'java.time.LocalDate', 'DateTimeFormatter': 'java.time.format.DateTimeFormatter',
    'DateTimeParseException': 'java.time.format.DateTimeParseException', 'OffsetDateTime': 'java.time.OffsetDateTime', 'Collection': 'java.util.Collection',
    'HashMap': 'java.util.HashMap', 'Objects': 'java.util.Objects', 'Collections': 'java.util.Collections', 'ArrayDeque': 'java.util.ArrayDeque',
    'IdentityHashMap': 'java.util.IdentityHashMap', 'Getter': 'lombok.Getter', 'Modifying': 'org.springframework.data.jpa.repository.Modifying',
    'JpaSpecificationExecutor': 'org.springframework.data.jpa.repository.JpaSpecificationExecutor', 'Specification': 'org.springframework.data.jpa.domain.Specification',
    'Sort': 'org.springframework.data.domain.Sort', 'Predicate': 'jakarta.persistence.criteria.Predicate', 'Path': 'jakarta.persistence.criteria.Path',
    'CriteriaBuilder': 'jakarta.persistence.criteria.CriteriaBuilder', 'SQLTimeoutException': 'java.sql.SQLTimeoutException',
    'SQLNonTransientConnectionException': 'java.sql.SQLNonTransientConnectionException', 'SQLRecoverableException': 'java.sql.SQLRecoverableException',
    'SQLTransientConnectionException': 'java.sql.SQLTransientConnectionException', 'JDBCConnectionException': 'org.hibernate.exception.JDBCConnectionException',
    'DataAccessResourceFailureException': 'org.springframework.dao.DataAccessResourceFailureException',
    'TransientDataAccessResourceException': 'org.springframework.dao.TransientDataAccessResourceException',
    'CannotCreateTransactionException': 'org.springframework.transaction.CannotCreateTransactionException',
    'MissingServletRequestParameterException': 'org.springframework.web.bind.MissingServletRequestParameterException',
    'MissingRequestHeaderException': 'org.springframework.web.bind.MissingRequestHeaderException',
    'MethodArgumentTypeMismatchException': 'org.springframework.web.method.annotation.MethodArgumentTypeMismatchException',
    'DeleteMapping': 'org.springframework.web.bind.annotation.DeleteMapping', 'PropertySource': 'org.springframework.context.annotation.PropertySource',
})

# (api name, api type, column, kind): the fields shared by the contract (CreateFinancingRequest / FinancingDto) and CUST_FINANCIAMIENTO / CUST_FINANCIAMIENTO_HIST.
# kind: plain = same Java type, decimal = Double in the API and BigDecimal in the entity, date = String in the API and LocalDate in the entity,
# datetime = String in the API and LocalDateTime in the entity, integer/long keep their boxed type.
FIELDS = [
    ('saleOrder', 'String', 'FNNC_ORDEN', 'plain'), ('saleChannel', 'String', 'FNNC_CANAL', 'plain'), ('salePoint', 'String', 'FNNC_PUNTO', 'plain'),
    ('isClient', 'String', 'FNNC_ESCLIENTE', 'plain'), ('platform', 'String', 'FNNC_PLATAFORMA', 'plain'), ('documentCodeId', 'Integer', 'FNNC_TIPODOCUMENTO', 'plain'),
    ('documentNumber', 'String', 'FNNC_NUMERODOCUMENTO', 'plain'), ('clientCode', 'String', 'FNNC_CLIENTECODIGO', 'plain'), ('creditLimit', 'Double', 'FNNC_LIMITECREDITO', 'decimal'),
    ('productCode', 'String', 'FNNC_PRODUCTOCODIGO', 'plain'), ('debtAmount', 'Double', 'FNNC_MONTODEUDA', 'decimal'), ('quotesNumber', 'Integer', 'FNNC_NUMERODECUOTAS', 'plain'),
    ('amountInitialQuote', 'Double', 'FNNC_MONTOCUOTAINICIAL', 'decimal'), ('amountFinanced', 'Double', 'FNNC_MONTOFINANCIADO', 'decimal'),
    ('quoteAmount', 'Double', 'FNNC_MONTODELACUOTA', 'decimal'), ('line', 'String', 'FNNC_LINEA', 'plain'), ('stateLine', 'String', 'FNNC_LINEAESTADO', 'plain'),
    ('fixedAmount', 'Double', 'FNNC_LINEACARGO', 'decimal'), ('quoteCycle', 'String', 'FNNC_CICLOCUOTA', 'date'), ('imei', 'String', 'FNNC_IMEI', 'plain'),
    ('productSerie', 'String', 'FNNC_PRODUCTOSERIEID', 'plain'), ('contractNumber', 'String', 'FNNC_NUMEROCONTRATO', 'plain'),
    ('proofPaymentType', 'String', 'FNNC_TIPOCOMPROBANTEPAGO', 'plain'), ('proofPaymentNumber', 'String', 'FNNC_NUMEROCOMPROBANTEPAGO', 'plain'),
    ('reasonChange', 'String', 'FNNC_MOTIVOCAMBIO', 'plain'), ('clientFullName', 'String', 'FNNC_CLIENTENOMBRE', 'plain'), ('contactName', 'String', 'FNNC_CONTACTONOMBRE', 'plain'),
    ('productDescription', 'String', 'FNNC_PRODUCTODESCRIPCION', 'plain'), ('isSapSent', 'String', 'FNNC_FLGENVIOSAP', 'plain'),
    ('sapSentDate', 'String', 'FNNC_FECHAENVIOSAP', 'datetime'), ('sapDocumentId', 'String', 'FNNC_DOCUMENTOSAPID', 'plain'),
    ('financingStateCodeId', 'Integer', 'STFN_CODIGO', 'plain'), ('requestCodeId', 'Integer', 'SLCT_CODIGO', 'plain'), ('requestTypeId', 'Integer', 'TPSL_CODIGO', 'plain'),
    ('cancellationTypeId', 'Integer', 'TPCN_CODIGO', 'plain'), ('agreementCodeIdParent', 'Long', 'FNNC_CODIGOORIGINAL', 'plain'),
]
UPDATE_FIELDS = ['financingStateCodeId', 'quoteCycle', 'line', 'imei', 'productSerie', 'proofPaymentType', 'proofPaymentNumber', 'reasonChange']
AUDIT = [('String', 'createdBy', 'FNNC_USUARIOCREACION'), ('LocalDateTime', 'createdAt', 'FNNC_FECHACREACION'), ('String', 'updatedBy', 'FNNC_USUARIOULTIMAACT'),
         ('LocalDateTime', 'updatedAt', 'FNNC_FECHAULTIMAACT')]
STATE_COLUMNS = [('Integer', 'financingStateCodeId', 'STFN_CODIGO', 'id'), ('String', 'financingStateDescription', 'STFN_VALOR', ''), ('Integer', 'state', 'STFN_ESTADO', ''),
                 ('String', 'description', 'STFN_DESCRIPCION', ''), ('String', 'createdBy', 'STFN_USUARIOCREACION', ''), ('LocalDateTime', 'createdAt', 'STFN_FECHACREACION', ''),
                 ('String', 'updatedBy', 'STFN_USUARIOULTIMAACT', ''), ('LocalDateTime', 'updatedAt', 'STFN_FECHAULTIMAACT', '')]
REQUEST_TYPE_COLUMNS = [('Integer', 'requestTypeId', 'TPSL_CODIGO', 'id'), ('String', 'requestTypeDescription', 'TPSL_VALOR', '')]
INSTALLMENT_COLUMNS = [('Long', 'installmentId', 'COTA_CODIGO', 'id'), ('Long', 'agreementCodeId', 'FNNC_CODIGO', ''), ('Integer', 'installmentStateCodeId', 'STCT_CODIGO', '')]
INSTALLMENT_HISTORY_COLUMNS = [('Long', 'installmentHistoryId', 'COTA_CODIGOHIST', 'id'), ('Long', 'agreementCodeId', 'FNNC_CODIGO', '')]

# Entity name -> (table, columns); the columns are the ones the specified operations read or write.
ENTITY_TABLES = {'FinancingEntity': 'CUST_FINANCIAMIENTO', 'FinancingHistoryEntity': 'CUST_FINANCIAMIENTO_HIST', 'FinancingStateEntity': 'CUST_ESTADOFINANCIAMIENTO',
                 'RequestTypeEntity': 'CUST_TIPOSOLICITUD', 'InstallmentEntity': 'CUST_CUOTA', 'InstallmentHistoryEntity': 'CUST_CUOTA_HIST'}


def entity_type(api_type, kind):
    return {'decimal': 'BigDecimal', 'date': 'LocalDate', 'datetime': 'LocalDateTime'}.get(kind, api_type)


def financing_columns(history):
    rows = [('Long', 'historyId', 'FNNC_CODIGOHIST', 'id'), ('Long', 'agreementCodeId', 'FNNC_CODIGO', '')] if history else [('Long', 'agreementCodeId', 'FNNC_CODIGO', 'id')]
    rows.append(('String', 'system', 'FNNC_SISTEMA', ''))
    rows += [(entity_type(t, k), n, c, '') for n, t, c, k in FIELDS]
    rows += [(t, n, c, '') for t, n, c in AUDIT]
    return rows


def entity_columns(cls):
    return {'FinancingEntity': financing_columns(False), 'FinancingHistoryEntity': financing_columns(True), 'FinancingStateEntity': STATE_COLUMNS,
            'RequestTypeEntity': REQUEST_TYPE_COLUMNS, 'InstallmentEntity': INSTALLMENT_COLUMNS, 'InstallmentHistoryEntity': INSTALLMENT_HISTORY_COLUMNS}[cls]


# Sparx activities (authoritative branch): (constant, title as named in Sparx, data access?)
def constant_name(number, title):
    text = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('ascii').upper()
    return f'ACT{number}_' + re.sub(r'[^A-Z0-9]+', '_', text).strip('_')


ACTIVITY_TITLES = [
    (1, 'Valida campos', False), (1, 'Validar parametros', False), (1, 'Validar Par\u00e1metros', False), (2, 'Guardar Financiamiento', True), (3, 'Guardar Financiamiento hist\u00f3rico', True),
    (3, 'Actualizar Financiamiento', True), (2, 'Registrar hist\u00f3rico', True), (2, 'Eliminar financiamiento y cuotas asociadas', True), (2, 'Consultar Financiamientos', True),
    (2, 'Buscar Financiamiento', True), (2, 'Consultar estados de financiamiento', True), (2, 'obtener financiamientos confirmados con cuotas pendientes', True),
    (3, 'Obtener financiamientos confirmados con cuotas en error envio', True), (4, 'Consolidar Candidatos de Notificaci\u00f3n', False),
]
ACTIVITIES = list(dict.fromkeys((constant_name(n, t), constant_name(n, t).split('_', 1)[1], d) for n, t, d in ACTIVITY_TITLES))
ACT = {t: constant_name(n, t) for n, t, d in ACTIVITY_TITLES}


def activity_constants():
    lines = [f'    public static final String {const} = "{value}";' for const, value, _ in ACTIVITIES]
    lines += ['', '    // Mensajes log (actividades con acceso a datos)']
    for const, value, data in ACTIVITIES:
        if data:
            lines += [f'    public static final String LOG_TIMEOUT_{const} =', f'            "Timeout en la actividad {value}: ";', '',
                      f'    public static final String LOG_ERROR_DATOS_{const} =', f'            "Error de acceso a datos en la actividad {value}: ";', '']
    return '\n'.join(lines).rstrip('\n')


def log(title, wrap=False):
    const = ACT[title]
    separator = ',\n                        ' if wrap else ', '
    return f'ConstanApi.LOG_TIMEOUT_{const}{separator}ConstanApi.LOG_ERROR_DATOS_{const}'


def cap(name):
    return name[0].upper() + name[1:]


dj.register('model', 'FinancingEntity', 'FinancingHistoryEntity', 'FinancingStateEntity', 'RequestTypeEntity', 'InstallmentEntity', 'InstallmentHistoryEntity',
            'FinancingDates', 'SearchCriteria', 'RefinancingQuery', 'NotificationQuery')
REQUEST_CLASSES = ['CreateFinancingRequest', 'UpdateFinancingRequest']
RESPONSE_DATA = ['CreateFinancingResponseData', 'FinancingDto', 'FinancingSearchDto', 'FinancingStateDto', 'RefinancingsAgreementDataDto', 'NotificationFinancingDto']
ENVELOPES = {'CreateFinancingResponse': 'CreateFinancingResponseData', 'UpdateFinancingResponse': 'Object', 'GetFinancingResponse': 'FinancingDto', 'DeleteFinancingResponse': 'Object',
             'SearchFinancingResponse': 'List<FinancingSearchDto>', 'StateFinancingResponse': 'List<FinancingStateDto>',
             'RefinancingsAgreementResponse': 'RefinancingsAgreementDataDto', 'NotificationFinancingResponse': 'List<NotificationFinancingDto>'}
dj.register('dto.request', 'RequestHeaders', *REQUEST_CLASSES)
dj.register('dto.response', 'ErrorResponse', *RESPONSE_DATA, *ENVELOPES)
dj.register('dto.mapper', 'FinancingMapper')
dj.register('exception', 'GlobalExceptionHandler', 'PersistenceExceptionTranslator', 'ServiceOperationException')
dj.register('repository', 'FinancingRepository', 'FinancingHistoryRepository', 'FinancingStateRepository', 'RequestTypeRepository', 'InstallmentRepository',
            'InstallmentHistoryRepository', 'FinancingSpecifications')
dj.register('service', 'FinancingService')
dj.register('service.impl', 'FinancingServiceImpl')
dj.register('validation', 'FinancingValidator')
dj.register('controller', 'FinancingApi')
dj.register('controller.impl', 'FinancingController')
dj.register('configuration', 'ClockConfig', 'FinancingProperties')

# operationId -> (HTTP method, path, summary, response class, success status, declared error statuses, java params [(annotation, type, name, doc)])
OPERATIONS = [
    ('createFinancing', 'Post', '/api/v1/financingAgreement', 'Registrar financiamiento', 'CreateFinancingResponse', '201', ('400', '500', '503', '504'),
     [('@RequestBody', 'CreateFinancingRequest', 'request', 'Datos del financiamiento.')]),
    ('updateFinancing', 'Patch', '/api/v1/financingAgreement', 'Actualizar financiamiento', 'UpdateFinancingResponse', '200', ('400', '500', '503', '504'),
     [('@RequestBody', 'UpdateFinancingRequest', 'request', 'Datos a actualizar del financiamiento.')]),
    ('getFinancing', 'Get', '/api/v1/financingAgreement/{agreementCodeId}', 'Obtener financiamiento', 'GetFinancingResponse', '200', ('400', '404', '500', '503', '504'),
     [('@PathVariable("agreementCodeId")', 'Long', 'agreementCodeId', 'Identificador del financiamiento.')]),
    ('deleteFinancing', 'Delete', '/api/v1/financingAgreement/{agreementCodeId}', 'Eliminar financiamiento', 'DeleteFinancingResponse', '200', ('400', '500', '503', '504'),
     [('@PathVariable("agreementCodeId")', 'Long', 'agreementCodeId', 'Identificador del financiamiento.')]),
    ('searchFinancing', 'Get', '/api/v1/financingAgreement/search', 'Consultar financiamientos.', 'SearchFinancingResponse', '200', ('400', '404', '500', '503', '504'),
     [('@RequestParam(name = "dateBegin", required = true)', 'String', 'dateBegin', 'Fecha de inicio de consulta. Formato yyyy-MM-dd.'),
      ('@RequestParam(name = "dateEnd", required = true)', 'String', 'dateEnd', 'Fecha fin de consulta. Formato yyyy-MM-dd.'),
      ('@RequestParam(name = "documentCodeId", required = false)', 'Integer', 'documentCodeId', 'Identificador de tipo documento del cliente.'),
      ('@RequestParam(name = "documentNumber", required = false)', 'String', 'documentNumber', 'N\u00famero documento del cliente.'),
      ('@RequestParam(name = "saleOrder", required = false)', 'String', 'saleOrder', 'Orden de venta.'),
      ('@RequestParam(name = "saleChannel", required = false)', 'String', 'saleChannel', 'Canal donde se origina la venta.'),
      ('@RequestParam(name = "productCode", required = false)', 'String', 'productCode', 'C\u00f3digo o serie del producto.'),
      ('@RequestParam(name = "financingStateCodeId", required = false)', 'Integer', 'financingStateCodeId', 'Identificador de estado de financiamiento.'),
      ('@RequestParam(name = "hasOverduePayments", required = false)', 'Integer', 'hasOverduePayments', 'Flag para filtro de financiamientos con cuotas vencidas.')]),
    ('stateFinancing', 'Get', '/api/v1/financingAgreement/state', 'Obtener estados de financiamiento.', 'StateFinancingResponse', '200', ('400', '404', '500', '503', '504'), []),
    ('refinancingsAgreement', 'Get', '/api/v1/financingAgreement/numberOfRefinancings', 'Obtener indicadores de refinanciamiento.', 'RefinancingsAgreementResponse', '200',
     ('400', '404', '500', '503', '504'),
     [('@RequestParam(name = "clientCode", required = true)', 'Long', 'clientCode', 'C\u00f3digo de cliente.'),
      ('@RequestParam(name = "periodMonths", required = true)', 'String', 'periodMonths', 'Cantidad de meses del per\u00edodo de restricci\u00f3n.'),
      ('@RequestParam(name = "processDate", required = true)', 'String', 'processDate', 'Fecha de proceso. Formato yyyy-MM-dd.')]),
    ('notificationFinancing', 'Get', '/api/v1/financingAgreement/notification-candidates', 'Obtener financiamientos candidatos a notificaci\u00f3n.', 'NotificationFinancingResponse', '200',
     ('400', '404', '500', '503', '504'),
     [('@RequestParam(name = "requestTypeIds", required = true)', 'String', 'requestTypeIds', 'Lista de tipos de solicitud separados por coma.'),
      ('@RequestParam(name = "dateBegin", required = true)', 'String', 'dateBegin', 'Fecha y hora inicial de la ventana de b\u00fasqueda.'),
      ('@RequestParam(name = "dateEnd", required = true)', 'String', 'dateEnd', 'Fecha y hora final de la ventana de b\u00fasqueda.')]),
]
HEADERS = dj.HEADERS


def entity(cls):
    out = ['@Data', '@NoArgsConstructor', '@AllArgsConstructor', '@Entity', '@DynamicInsert', '@DynamicUpdate', f'@Table(name = "{ENTITY_TABLES[cls]}")', f'public class {cls} {{']
    for java_type, name, column, flag in entity_columns(cls):
        out.append('')
        if flag == 'id':
            out += ['    @Id', '    @GeneratedValue(strategy = GenerationType.IDENTITY)']
        out += [f'    @Column(name = "{column}")', f'    private {java_type} {name};']
    out.append('}')
    return '\n'.join(out)


def request_dto(cls):
    names = [('Long', 'agreementCodeId')] if cls == 'UpdateFinancingRequest' else []
    wanted = [f for f in FIELDS if cls == 'CreateFinancingRequest' or f[0] in UPDATE_FIELDS]
    if cls == 'UpdateFinancingRequest':
        wanted = [f for f in FIELDS if f[0] in UPDATE_FIELDS]
    names += [(t, n) for n, t, c, k in wanted]
    return dj.dto(cls, names)


def financing_dto():
    names = [('Long', 'agreementCodeId'), ('String', 'system')] + [(t, n) for n, t, c, k in FIELDS] + [('String', 'createdBy'), ('String', 'createdAt'), ('String', 'updatedBy'), ('String', 'updatedAt')]
    return dj.dto('FinancingDto', names, non_null=True)


DATA_DTOS = {
    'CreateFinancingResponseData': [('Long', 'agreementCodeId')],
    'FinancingSearchDto': [('String', 'saleOrder'), ('Integer', 'documentCodeId'), ('String', 'documentNumber'), ('String', 'createdAt'), ('String', 'productCode'),
                           ('Long', 'agreementCodeId'), ('Double', 'debtAmount'), ('Integer', 'quotesNumber'), ('Double', 'amountInitialQuote'), ('Double', 'amountFinanced'),
                           ('Double', 'quoteAmount'), ('String', 'saleChannel'), ('String', 'salePoint'), ('Integer', 'requestTypeId'), ('String', 'requestTypeDescription'),
                           ('Integer', 'financingStateCodeId'), ('String', 'financingStateDescription'), ('String', 'isSapSent'), ('String', 'sapSentDate'), ('String', 'sapDocumentId')],
    'FinancingStateDto': [('Integer', 'financingStateCodeId'), ('String', 'financingStateDescription'), ('String', 'description'), ('Integer', 'state'), ('String', 'createdBy'),
                          ('String', 'createdAt'), ('String', 'updatedBy'), ('String', 'updatedAt')],
    'RefinancingsAgreementDataDto': [('Long', 'activeRefinancingCount'), ('Long', 'completedRefinancingCountInPeriod')],
    'NotificationFinancingDto': [('Long', 'agreementCodeId'), ('Integer', 'documentCodeId'), ('String', 'documentNumber'), ('String', 'clientCode'), ('String', 'line'),
                                 ('String', 'contractNumber'), ('String', 'productDescription'), ('Integer', 'requestTypeId'), ('Integer', 'financingStateCodeId'),
                                 ('String', 'proofPaymentType'), ('String', 'proofPaymentNumber'), ('String', 'createdAt'), ('Integer', 'isRetry')],
}

RECORDS = {
    'FinancingDates': '''/** Date values of a request already validated and converted: the billing cycle date and the SAP sent date. */
public record FinancingDates(LocalDate quoteCycle, LocalDateTime sapSentDate) {
}''',
    'SearchCriteria': '''/** Validated search command of the financing query; hasOverduePayments is accepted from the contract but no source defines its filter. */
public record SearchCriteria(
        LocalDate dateBegin,
        LocalDate dateEnd,
        Integer documentCodeId,
        String documentNumber,
        String saleOrder,
        String saleChannel,
        String productCode,
        Integer financingStateCodeId,
        Integer hasOverduePayments
) {
}''',
    'RefinancingQuery': '''/** Validated command of the refinancing indicators query. */
public record RefinancingQuery(String clientCode, int periodMonths, LocalDate processDate) {
}''',
    'NotificationQuery': '''/** Validated command of the notification candidates query. */
public record NotificationQuery(List<Integer> requestTypeIds, LocalDateTime dateBegin, LocalDateTime dateEnd) {
}''',
}

REQUEST_HEADERS = dj.REQUEST_HEADERS

CLOCK_CONFIG = dj.CLOCK_CONFIG

PROPERTIES = '''/**
 * Business constants that Sparx names as properties (propEstado..., propTipo...). The defaults are the values Sparx states; they can be overridden by configuration.
 */
@Getter
@Component
public class FinancingProperties {
    private final Integer confirmedState;
    private final Integer pendingInstallmentState;
    private final Integer oacErrorInstallmentState;
    private final Integer refinancingRequestType;
    private final Integer refinancingConfirmedState;
    private final Integer refinancingCompletedState;

    public FinancingProperties(
            @Value("${propEstadoFinanConfirmada:2}") Integer confirmedState,
            @Value("${propEstadoCuotaPendiente:1}") Integer pendingInstallmentState,
            @Value("${propEstadoCuotaErrorOac:7}") Integer oacErrorInstallmentState,
            @Value("${propTipoReFinanciamiento:3}") Integer refinancingRequestType,
            @Value("${propEstadoConfirmado:2}") Integer refinancingConfirmedState,
            @Value("${propEstadoTerminado:5}") Integer refinancingCompletedState) {
        this.confirmedState = confirmedState;
        this.pendingInstallmentState = pendingInstallmentState;
        this.oacErrorInstallmentState = oacErrorInstallmentState;
        this.refinancingRequestType = refinancingRequestType;
        this.refinancingConfirmedState = refinancingConfirmedState;
        this.refinancingCompletedState = refinancingCompletedState;
    }
}'''

REPOSITORIES = {
    'FinancingRepository': '''@Repository
public interface FinancingRepository extends JpaRepository<FinancingEntity, Long>, JpaSpecificationExecutor<FinancingEntity> {
    long countByClientCodeAndRequestTypeIdAndFinancingStateCodeId(String clientCode, Integer requestTypeId, Integer financingStateCodeId);

    @Query("select count(f) from FinancingEntity f where f.clientCode = :clientCode and f.requestTypeId = :requestTypeId"
            + " and f.financingStateCodeId = :stateId and f.createdAt >= :dateFrom and f.createdAt < :dateTo")
    long countInWindow(@Param("clientCode") String clientCode, @Param("requestTypeId") Integer requestTypeId, @Param("stateId") Integer stateId,
            @Param("dateFrom") LocalDateTime dateFrom, @Param("dateTo") LocalDateTime dateTo);

    @Query("select f from FinancingEntity f where f.financingStateCodeId = :stateId and f.requestTypeId in :requestTypeIds"
            + " and f.createdAt >= :dateFrom and f.createdAt <= :dateTo"
            + " and exists (select 1 from InstallmentEntity i where i.agreementCodeId = f.agreementCodeId and i.installmentStateCodeId = :installmentStateId)"
            + " order by f.agreementCodeId")
    List<FinancingEntity> findWithInstallmentStateBetween(@Param("stateId") Integer stateId, @Param("requestTypeIds") Collection<Integer> requestTypeIds,
            @Param("installmentStateId") Integer installmentStateId, @Param("dateFrom") LocalDateTime dateFrom, @Param("dateTo") LocalDateTime dateTo);

    @Query("select f from FinancingEntity f where f.financingStateCodeId = :stateId and f.requestTypeId in :requestTypeIds"
            + " and exists (select 1 from InstallmentEntity i where i.agreementCodeId = f.agreementCodeId and i.installmentStateCodeId = :installmentStateId)"
            + " order by f.agreementCodeId")
    List<FinancingEntity> findWithInstallmentState(@Param("stateId") Integer stateId, @Param("requestTypeIds") Collection<Integer> requestTypeIds,
            @Param("installmentStateId") Integer installmentStateId);

    @Modifying
    @Query("delete from FinancingEntity f where f.agreementCodeId = :agreementCodeId")
    int deleteByAgreementCode(@Param("agreementCodeId") Long agreementCodeId);
}''',
    'FinancingHistoryRepository': '''@Repository
public interface FinancingHistoryRepository extends JpaRepository<FinancingHistoryEntity, Long> {
    @Modifying
    @Query("delete from FinancingHistoryEntity h where h.agreementCodeId = :agreementCodeId")
    int deleteByAgreementCode(@Param("agreementCodeId") Long agreementCodeId);
}''',
    'FinancingStateRepository': '''@Repository
public interface FinancingStateRepository extends JpaRepository<FinancingStateEntity, Integer> {
}''',
    'RequestTypeRepository': '''@Repository
public interface RequestTypeRepository extends JpaRepository<RequestTypeEntity, Integer> {
}''',
    'InstallmentRepository': '''@Repository
public interface InstallmentRepository extends JpaRepository<InstallmentEntity, Long> {
    @Modifying
    @Query("delete from InstallmentEntity i where i.agreementCodeId = :agreementCodeId")
    int deleteByAgreementCode(@Param("agreementCodeId") Long agreementCodeId);
}''',
    'InstallmentHistoryRepository': '''@Repository
public interface InstallmentHistoryRepository extends JpaRepository<InstallmentHistoryEntity, Long> {
    @Modifying
    @Query("delete from InstallmentHistoryEntity h where h.agreementCodeId = :agreementCodeId")
    int deleteByAgreementCode(@Param("agreementCodeId") Long agreementCodeId);
}''',
}

SPECIFICATIONS = '''/** Search filter of the financing query: creation date range (both days included) and the optional equality filters informed by the caller. */
public final class FinancingSpecifications {
    private FinancingSpecifications() {
    }

    public static Specification<FinancingEntity> search(SearchCriteria criteria) {
        return (root, query, builder) -> {
            List<Predicate> predicates = new ArrayList<>();
            predicates.add(builder.greaterThanOrEqualTo(root.<LocalDateTime>get("createdAt"), criteria.dateBegin().atStartOfDay()));
            predicates.add(builder.lessThan(root.<LocalDateTime>get("createdAt"), criteria.dateEnd().plusDays(1).atStartOfDay()));
            equal(predicates, builder, root.get("documentCodeId"), criteria.documentCodeId());
            equal(predicates, builder, root.get("documentNumber"), criteria.documentNumber());
            equal(predicates, builder, root.get("saleOrder"), criteria.saleOrder());
            equal(predicates, builder, root.get("saleChannel"), criteria.saleChannel());
            equal(predicates, builder, root.get("productCode"), criteria.productCode());
            equal(predicates, builder, root.get("financingStateCodeId"), criteria.financingStateCodeId());
            return builder.and(predicates.toArray(new Predicate[0]));
        };
    }

    private static void equal(List<Predicate> predicates, CriteriaBuilder builder, Path<?> path, Object value) {
        if (value != null) {
            predicates.add(builder.equal(path, value));
        }
    }
}'''
dj.EXTERNAL.setdefault('ArrayList', 'java.util.ArrayList')

SERVICE_OPERATION_EXCEPTION = '''/** Application failure that carries the HTTP status and the error identity (subType IDFxxx / IDTx, type, detail) decided by the approved behavior. */
public class ServiceOperationException extends RuntimeException {
    private static final String SERVICE_NAME = "__LANE__";
    private static final String MISSING_DETAIL = "Par\\u00e1metros obligatorios incompletos. ";
    private static final String MISSING_DETAIL_TAIL = " presenta valor no v\\u00e1lido.";
    private final HttpStatus status;
    private final String subType;
    private final String type;
    private final String detail;

    public ServiceOperationException(HttpStatus status, String subType, String type, String detail) {
        this(status, subType, type, detail, null);
    }

    public ServiceOperationException(HttpStatus status, String subType, String type, String detail, Throwable cause) {
        super(detail, cause);
        this.status = status;
        this.subType = subType;
        this.type = type;
        this.detail = detail;
    }

    public static ServiceOperationException missingParameters(String field) {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, "IDF101", "MissingParameters", MISSING_DETAIL + field + MISSING_DETAIL_TAIL);
    }

    public static ServiceOperationException invalidIsClient() {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, "IDF106", "InvalidIsClientValueException", "La variable \\"isClient\\" solo permite valores N o S.");
    }

    public static ServiceOperationException invalidQuoteCycleFormat() {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, "IDF113", "InvalidQuoteCycleFormatException", "La variable \\"quoteCycle\\" presenta formato no valido.");
    }

    public static ServiceOperationException invalidDateRange() {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, "IDF126", "InvalidDateRangeException", "La variable 'dateBegin' no debe ser mayor a 'dateEnd'.");
    }

    public static ServiceOperationException dateDifferenceExceeded() {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, "IDF127", "DateDifferenceExceededException", "La diferencia de fechas no debe superar un (1) mes.");
    }

    public static ServiceOperationException invalidProcessDateFormat() {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, "IDF130", "InvalidProcessDateFormatException",
                "La variable 'processDate' no tiene el formato correcto. Deber\\u00eda de ser yyyy-MM-dd");
    }

    public static ServiceOperationException invalidDateFormat() {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, "IDF131", "InvalidDateFormatException", "La variable 'dateBegin' y/o 'dateEnd' no tiene el formato correcto.");
    }

    public static ServiceOperationException notFound() {
        return new ServiceOperationException(HttpStatus.NOT_FOUND, "IDF302", "ResourceNotFoundException", "Registro o recurso no encontrado (El ID consultado no existe).");
    }

    public static ServiceOperationException timeout(Throwable cause) {
        return new ServiceOperationException(HttpStatus.GATEWAY_TIMEOUT, "IDT1", "TimeoutException",
                "Error de timeout en " + SERVICE_NAME + " - Detalle: Tiempo de espera agotado al acceder a los datos.", cause);
    }

    public static ServiceOperationException unavailable(Throwable cause) {
        return new ServiceOperationException(HttpStatus.SERVICE_UNAVAILABLE, "IDT2", "ServiceUnavailable",
                "Error de disponibilidad en " + SERVICE_NAME + " - Detalle: Base de datos no disponible.", cause);
    }

    public static ServiceOperationException internal(Throwable cause) {
        return new ServiceOperationException(HttpStatus.INTERNAL_SERVER_ERROR, "IDT3", "InternalError",
                "Error interno al procesar la transacci\\u00f3n: Error no controlado.", cause);
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

    public String getDetail() {
        return detail;
    }
}'''.replace('__LANE__', SERVICE_LANE)

TRANSLATOR = '''/** Classifies data-access failures (cause chains included) into the declared statuses: timeout, unavailability, otherwise internal error. */
@Component
public class PersistenceExceptionTranslator {
    public ServiceOperationException translate(RuntimeException failure) {
        boolean unavailable = false;
        boolean timeout = false;
        Set<Throwable> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        ArrayDeque<Throwable> queue = new ArrayDeque<>();
        queue.add(failure);
        while (!queue.isEmpty()) {
            Throwable cause = queue.removeFirst();
            if (!seen.add(cause)) {
                continue;
            }
            timeout |= cause instanceof SQLTimeoutException
                    || cause instanceof QueryTimeoutException
                    || cause instanceof jakarta.persistence.QueryTimeoutException;
            unavailable |= cause instanceof DataAccessResourceFailureException
                    || cause instanceof TransientDataAccessResourceException
                    || cause instanceof CannotCreateTransactionException
                    || cause instanceof JDBCConnectionException
                    || cause instanceof SQLNonTransientConnectionException
                    || cause instanceof SQLTransientConnectionException
                    || cause instanceof SQLRecoverableException;
            if (cause instanceof SQLException sql && sql.getNextException() != null) {
                queue.add(sql.getNextException());
            }
            if (cause.getCause() != null) {
                queue.add(cause.getCause());
            }
        }
        if (timeout) {
            return ServiceOperationException.timeout(failure);
        }
        return unavailable ? ServiceOperationException.unavailable(failure) : ServiceOperationException.internal(failure);
    }
}'''

HANDLER = '''@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String TRANSACTION_HEADER = "x-correlation-id";
    private static final String SERVICE_MESSAGE = "__MESSAGE__";
    private static final String BODY_FIELD = "body";
    private static final Set<HttpStatus> DECLARED_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.NOT_FOUND, HttpStatus.INTERNAL_SERVER_ERROR,
            HttpStatus.SERVICE_UNAVAILABLE, HttpStatus.GATEWAY_TIMEOUT);

    private final PersistenceExceptionTranslator translator;

    public GlobalExceptionHandler(PersistenceExceptionTranslator translator) {
        this.translator = translator;
    }

    @ExceptionHandler(ServiceOperationException.class)
    public ResponseEntity<ErrorResponse> operationFailure(ServiceOperationException failure, WebRequest request) {
        logValidationFailure(request, failure.getStatus(), failure.getDetail());
        return ResponseEntity.status(failure.getStatus()).contentType(MediaType.APPLICATION_JSON).body(error(failure));
    }

    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<ErrorResponse> unexpectedFailure(RuntimeException failure, WebRequest request) {
        return operationFailure(translator.translate(failure), request);
    }

    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception ex, @Nullable Object body,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        ServiceOperationException failure = status.value() == HttpStatus.BAD_REQUEST.value()
                ? ServiceOperationException.missingParameters(field(ex)) : ServiceOperationException.internal(ex);
        logValidationFailure(request, failure.getStatus(), ex.getClass().getSimpleName());
        HttpHeaders json = new HttpHeaders();
        json.putAll(headers);
        json.setContentType(MediaType.APPLICATION_JSON);
        return new ResponseEntity<>(error(failure), json, failure.getStatus());
    }

    private String field(Exception failure) {
        if (failure instanceof MissingServletRequestParameterException parameter) {
            return parameter.getParameterName();
        }
        if (failure instanceof MissingRequestHeaderException header) {
            return header.getHeaderName();
        }
        if (failure instanceof MethodArgumentTypeMismatchException mismatch) {
            return mismatch.getName();
        }
        return BODY_FIELD;
    }

    private void logValidationFailure(WebRequest request, HttpStatus status, String reason) {
        if (status != HttpStatus.BAD_REQUEST) {
            return;
        }
        String tx = request.getHeader(TRANSACTION_HEADER);
        String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
        ActivityLogger.inicioActividad(log, menTran, ConstanApi.__VALIDATE__);
        log.error("{} ERROR [{}] code={} detail={}", menTran, ConstanApi.__VALIDATE__, status.value(), reason);
        ActivityLogger.finActividad(log, menTran, ConstanApi.__VALIDATE__);
    }

    private ErrorResponse error(ServiceOperationException failure) {
        HttpStatus status = DECLARED_STATUSES.contains(failure.getStatus()) ? failure.getStatus() : HttpStatus.INTERNAL_SERVER_ERROR;
        ErrorResponse error = new ErrorResponse();
        error.setCode(status.value());
        error.setStatus(status.name());
        error.setMessage(SERVICE_MESSAGE);
        error.setType(failure.getType());
        error.setSubType(failure.getSubType());
        error.setDetail(failure.getDetail());
        return error;
    }
}'''.replace('__MESSAGE__', SERVICE_MESSAGE).replace('__VALIDATE__', ACT['Validar parametros'])


def api():
    out = ['/**', ' * Define el contrato de los endpoints REST expuestos por el microservicio financingAgreement (contrato OpenAPI).', ' */', 'public interface FinancingApi {']
    reasons = dj.REASONS
    for index, (op, verb, path, summary, response, ok, errors, params) in enumerate(OPERATIONS):
        if index:
            out.append('')
        out += ['    /**', f'     * {summary}', '     *']
        for annotation, jtype, name, doc in params:
            out.append(f'     * @param {name} {doc}')
        for _, camel, doc in HEADERS:
            out.append(f'     * @param {camel} {doc}')
        out += [f'     * @return respuesta HTTP con el modelo {response} definido en el contrato', '     */']
        consumes = ', consumes = {"application/json"}' if verb in ('Post', 'Patch') else ''
        out += [f'    @{verb}Mapping(path = "{path}"{consumes}, produces = {{"application/json"}})', f'    @Operation(summary = "{summary}")', '    @ApiResponses({']
        rows = [f'      @ApiResponse(responseCode = "{ok}", description = "{dj.SUCCESS_REASON[ok]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = {response}.class)))']
        rows += [f'      @ApiResponse(responseCode = "{code}", description = "{reasons[code]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))'
                 for code in errors]
        out += [',\n'.join(rows), '    })', f'    ResponseEntity<{response}> {op}(']
        args = [f'            {annotation} {jtype} {name}' for annotation, jtype, name, _ in params]
        args += [f'            @RequestHeader(name = "{header}", required = true) String {camel}' for header, camel, _ in HEADERS]
        out.append(',\n'.join(args) + ');')
    out.append('}')
    return '\n'.join(out)


def controller():
    out = ['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class FinancingController implements FinancingApi {', '    private final FinancingService service;']
    for op, verb, path, summary, response, ok, errors, params in OPERATIONS:
        out += ['', '    @Override', f'    public ResponseEntity<{response}> {op}(']
        args = [f'            {jtype} {name}' for _, jtype, name, _ in params] + [f'            String {camel}' for _, camel, _ in HEADERS]
        out += [',\n'.join(args) + ') {', f'        log.info("{op} - transactionId: {{}}", xCorrelationId);', '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);']
        call = f'service.{op}(' + ', '.join(['headers'] + [name for _, _, name, _ in params]) + ')'
        out.append(f'        return ResponseEntity.status(HttpStatus.CREATED).body({call});' if ok == '201' else f'        return ResponseEntity.ok({call});')
        out.append('    }')
    out.append('}')
    return '\n'.join(out)


def service_interface():
    out = ['/** Casos de uso de los acuerdos de financiamiento. */', 'public interface FinancingService {']
    for op, verb, path, summary, response, ok, errors, params in OPERATIONS:
        args = ['RequestHeaders headers'] + [f'{jtype} {name}' for _, jtype, name, _ in params]
        out.append(f'    {response} {op}(' + ',\n            '.join(', '.join(args[i:i + 4]) for i in range(0, len(args), 4)) + ');')
    out.append('}')
    return '\n'.join(out)


def mapper():
    to_entity, apply_update, to_history, to_dto, to_search = [], [], [], [], []
    for name, api_type, column, kind in FIELDS:
        g, s = f'get{cap(name)}', f'set{cap(name)}'
        value = {'plain': f'request.{g}()', 'decimal': f'decimal(request.{g}())', 'date': 'dates.quoteCycle()', 'datetime': 'dates.sapSentDate()'}[kind]
        to_entity.append(f'        entity.{s}({value});')
        if name in UPDATE_FIELDS:
            guard = f'request.{g}() != null'
            apply_update += [f'        if ({guard}) {{', f'            entity.{s}({value});', '        }']
        to_history.append(f'        history.{s}(entity.{g}());')
        dto_value = {'plain': f'entity.{g}()', 'decimal': f'number(entity.{g}())', 'date': f'date(entity.{g}())', 'datetime': f'dateTime(entity.{g}())'}[kind]
        to_dto.append(f'        dto.{s}({dto_value});')
    return MAPPER.replace('__TO_ENTITY__', '\n'.join(to_entity)).replace('__APPLY_UPDATE__', '\n'.join(apply_update)).replace('__TO_HISTORY__', '\n'.join(to_history)).replace('__TO_DTO__', '\n'.join(to_dto))


MAPPER = '''/** Explicit mappings between the API contract and the JPA entities; nothing relies on name coincidence. */
@Component
@RequiredArgsConstructor
public class FinancingMapper {
    private static final DateTimeFormatter DATE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssZ");
    private static final String SUCCESS_MESSAGE = "Operaci\\u00f3n exitosa.";
    private static final Integer NOT_RETRY = 0;
    private static final Integer RETRY = 1;

    private final Clock clock;

    public FinancingEntity toEntity(CreateFinancingRequest request, FinancingDates dates, String system, String user, LocalDateTime now) {
        FinancingEntity entity = new FinancingEntity();
        entity.setSystem(system);
__TO_ENTITY__
        entity.setCreatedBy(user);
        entity.setCreatedAt(now);
        return entity;
    }

    public void applyUpdate(FinancingEntity entity, UpdateFinancingRequest request, FinancingDates dates, String user, LocalDateTime now) {
__APPLY_UPDATE__
        entity.setUpdatedBy(user);
        entity.setUpdatedAt(now);
    }

    public FinancingHistoryEntity toHistory(FinancingEntity entity) {
        FinancingHistoryEntity history = new FinancingHistoryEntity();
        history.setAgreementCodeId(entity.getAgreementCodeId());
        history.setSystem(entity.getSystem());
__TO_HISTORY__
        history.setCreatedBy(entity.getCreatedBy());
        history.setCreatedAt(entity.getCreatedAt());
        history.setUpdatedBy(entity.getUpdatedBy());
        history.setUpdatedAt(entity.getUpdatedAt());
        return history;
    }

    public CreateFinancingResponse createResponse(Long agreementCodeId) {
        CreateFinancingResponseData data = new CreateFinancingResponseData();
        data.setAgreementCodeId(agreementCodeId);
        CreateFinancingResponse response = new CreateFinancingResponse();
        response.setCode(HttpStatus.CREATED.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    public UpdateFinancingResponse updateResponse() {
        UpdateFinancingResponse response = new UpdateFinancingResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        return response;
    }

    public DeleteFinancingResponse deleteResponse() {
        DeleteFinancingResponse response = new DeleteFinancingResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        return response;
    }

    public GetFinancingResponse getResponse(FinancingEntity entity) {
        FinancingDto dto = new FinancingDto();
        dto.setAgreementCodeId(entity.getAgreementCodeId());
        dto.setSystem(entity.getSystem());
__TO_DTO__
        dto.setCreatedBy(entity.getCreatedBy());
        dto.setCreatedAt(dateTime(entity.getCreatedAt()));
        dto.setUpdatedBy(entity.getUpdatedBy());
        dto.setUpdatedAt(dateTime(entity.getUpdatedAt()));
        GetFinancingResponse response = new GetFinancingResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(dto);
        return response;
    }

    public SearchFinancingResponse searchResponse(List<FinancingEntity> rows, Map<Integer, String> states, Map<Integer, String> requestTypes) {
        List<FinancingSearchDto> data = rows.stream().map(row -> searchItem(row, states, requestTypes)).toList();
        SearchFinancingResponse response = new SearchFinancingResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private FinancingSearchDto searchItem(FinancingEntity row, Map<Integer, String> states, Map<Integer, String> requestTypes) {
        FinancingSearchDto item = new FinancingSearchDto();
        item.setSaleOrder(row.getSaleOrder());
        item.setDocumentCodeId(row.getDocumentCodeId());
        item.setDocumentNumber(row.getDocumentNumber());
        item.setCreatedAt(dateTime(row.getCreatedAt()));
        item.setProductCode(row.getProductCode());
        item.setAgreementCodeId(row.getAgreementCodeId());
        item.setDebtAmount(number(row.getDebtAmount()));
        item.setQuotesNumber(row.getQuotesNumber());
        item.setAmountInitialQuote(number(row.getAmountInitialQuote()));
        item.setAmountFinanced(number(row.getAmountFinanced()));
        item.setQuoteAmount(number(row.getQuoteAmount()));
        item.setSaleChannel(row.getSaleChannel());
        item.setSalePoint(row.getSalePoint());
        item.setRequestTypeId(row.getRequestTypeId());
        item.setRequestTypeDescription(requestTypes.get(row.getRequestTypeId()));
        item.setFinancingStateCodeId(row.getFinancingStateCodeId());
        item.setFinancingStateDescription(states.get(row.getFinancingStateCodeId()));
        item.setIsSapSent(row.getIsSapSent());
        item.setSapSentDate(dateTime(row.getSapSentDate()));
        item.setSapDocumentId(row.getSapDocumentId());
        return item;
    }

    public StateFinancingResponse stateResponse(List<FinancingStateEntity> rows) {
        List<FinancingStateDto> data = rows.stream().map(this::stateItem).toList();
        StateFinancingResponse response = new StateFinancingResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private FinancingStateDto stateItem(FinancingStateEntity row) {
        FinancingStateDto item = new FinancingStateDto();
        item.setFinancingStateCodeId(row.getFinancingStateCodeId());
        item.setFinancingStateDescription(row.getFinancingStateDescription());
        item.setDescription(row.getDescription());
        item.setState(row.getState());
        item.setCreatedBy(row.getCreatedBy());
        item.setCreatedAt(dateTime(row.getCreatedAt()));
        item.setUpdatedBy(row.getUpdatedBy());
        item.setUpdatedAt(dateTime(row.getUpdatedAt()));
        return item;
    }

    public RefinancingsAgreementResponse refinancingsResponse(long active, long completedInPeriod) {
        RefinancingsAgreementDataDto data = new RefinancingsAgreementDataDto();
        data.setActiveRefinancingCount(active);
        data.setCompletedRefinancingCountInPeriod(completedInPeriod);
        RefinancingsAgreementResponse response = new RefinancingsAgreementResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    public NotificationFinancingResponse notificationResponse(List<FinancingEntity> pendings, List<FinancingEntity> errors) {
        List<NotificationFinancingDto> data = new ArrayList<>();
        pendings.forEach(row -> data.add(notificationItem(row, NOT_RETRY)));
        errors.forEach(row -> data.add(notificationItem(row, RETRY)));
        NotificationFinancingResponse response = new NotificationFinancingResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private NotificationFinancingDto notificationItem(FinancingEntity row, Integer retry) {
        NotificationFinancingDto item = new NotificationFinancingDto();
        item.setAgreementCodeId(row.getAgreementCodeId());
        item.setDocumentCodeId(row.getDocumentCodeId());
        item.setDocumentNumber(row.getDocumentNumber());
        item.setClientCode(row.getClientCode());
        item.setLine(row.getLine());
        item.setContractNumber(row.getContractNumber());
        item.setProductDescription(row.getProductDescription());
        item.setRequestTypeId(row.getRequestTypeId());
        item.setFinancingStateCodeId(row.getFinancingStateCodeId());
        item.setProofPaymentType(row.getProofPaymentType());
        item.setProofPaymentNumber(row.getProofPaymentNumber());
        item.setCreatedAt(dateTime(row.getCreatedAt()));
        item.setIsRetry(retry);
        return item;
    }

    private BigDecimal decimal(Double value) {
        return value == null ? null : BigDecimal.valueOf(value);
    }

    private Double number(BigDecimal value) {
        return value == null ? null : value.doubleValue();
    }

    private String date(LocalDate value) {
        return value == null ? null : value.toString();
    }

    private String dateTime(LocalDateTime value) {
        return value == null ? null : DATE_TIME.format(value.atZone(clock.getZone()));
    }
}'''

VALIDATOR = '''/** Declared contract rules (required fields, formats, date ranges) and lossless conversions from contract values to typed commands. */
@Component
@RequiredArgsConstructor
public class FinancingValidator {
    private static final DateTimeFormatter OFFSET_PATTERN = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssZ");
    private static final String CLIENT_YES = "S";
    private static final String CLIENT_NO = "N";
    private static final String LIST_SEPARATOR = ",";
    private static final String BODY_FIELD = "body";

    private final Clock clock;

    public FinancingDates createFinancing(CreateFinancingRequest request) {
        require(request != null, BODY_FIELD);
        require(request.getRequestCodeId() != null, "requestCodeId");
        require(request.getRequestTypeId() != null, "requestTypeId");
        if (informed(request.getIsClient()) && !CLIENT_YES.equals(request.getIsClient()) && !CLIENT_NO.equals(request.getIsClient())) {
            throw ServiceOperationException.invalidIsClient();
        }
        return new FinancingDates(quoteCycle(request.getQuoteCycle()), sapSentDate(request.getSapSentDate()));
    }

    public FinancingDates updateFinancing(UpdateFinancingRequest request) {
        require(request != null, BODY_FIELD);
        require(request.getAgreementCodeId() != null, "agreementCodeId");
        return new FinancingDates(quoteCycle(request.getQuoteCycle()), null);
    }

    public Long agreementCodeId(Long agreementCodeId) {
        require(agreementCodeId != null, "agreementCodeId");
        return agreementCodeId;
    }

    public SearchCriteria search(String dateBegin, String dateEnd, Integer documentCodeId, String documentNumber, String saleOrder, String saleChannel, String productCode,
            Integer financingStateCodeId, Integer hasOverduePayments) {
        require(informed(dateBegin), "dateBegin");
        require(informed(dateEnd), "dateEnd");
        LocalDate begin = requiredDate(dateBegin, "dateBegin");
        LocalDate end = requiredDate(dateEnd, "dateEnd");
        if (begin.isAfter(end)) {
            throw ServiceOperationException.invalidDateRange();
        }
        boolean unbounded = informed(documentNumber) || informed(saleOrder);
        if (!unbounded && end.isAfter(begin.plusMonths(1))) {
            throw ServiceOperationException.dateDifferenceExceeded();
        }
        return new SearchCriteria(begin, end, documentCodeId, blankToNull(documentNumber), blankToNull(saleOrder), blankToNull(saleChannel), blankToNull(productCode),
                financingStateCodeId, hasOverduePayments);
    }

    public RefinancingQuery refinancings(Long clientCode, String periodMonths, String processDate) {
        require(clientCode != null, "clientCode");
        require(informed(periodMonths), "periodMonths");
        require(informed(processDate), "processDate");
        LocalDate date = parseDate(processDate);
        if (date == null) {
            throw ServiceOperationException.invalidProcessDateFormat();
        }
        return new RefinancingQuery(String.valueOf(clientCode), months(periodMonths), date);
    }

    public NotificationQuery notificationCandidates(String requestTypeIds, String dateBegin, String dateEnd) {
        require(informed(requestTypeIds), "requestTypeIds");
        require(informed(dateBegin), "dateBegin");
        require(informed(dateEnd), "dateEnd");
        LocalDateTime begin = dateTime(dateBegin);
        LocalDateTime end = dateTime(dateEnd);
        List<Integer> types = typeIds(requestTypeIds);
        if (begin == null || end == null) {
            throw ServiceOperationException.invalidDateFormat();
        }
        if (begin.isAfter(end)) {
            throw ServiceOperationException.invalidDateRange();
        }
        return new NotificationQuery(types, begin, end);
    }

    private LocalDate quoteCycle(String value) {
        if (!informed(value)) {
            return null;
        }
        LocalDate date = parseDate(value);
        if (date == null) {
            throw ServiceOperationException.invalidQuoteCycleFormat();
        }
        return date;
    }

    private LocalDateTime sapSentDate(String value) {
        if (!informed(value)) {
            return null;
        }
        LocalDateTime date = dateTime(value);
        require(date != null, "sapSentDate");
        return date;
    }

    private LocalDate requiredDate(String value, String field) {
        LocalDate date = parseDate(value);
        require(date != null, field);
        return date;
    }

    private int months(String value) {
        try {
            int months = Integer.parseInt(value.trim());
            require(months >= 0, "periodMonths");
            return months;
        } catch (NumberFormatException e) {
            throw ServiceOperationException.missingParameters("periodMonths");
        }
    }

    private List<Integer> typeIds(String value) {
        List<Integer> ids = new ArrayList<>();
        try {
            for (String part : value.split(LIST_SEPARATOR)) {
                ids.add(Integer.valueOf(part.trim()));
            }
        } catch (NumberFormatException e) {
            throw ServiceOperationException.missingParameters("requestTypeIds");
        }
        return ids;
    }

    private LocalDate parseDate(String value) {
        try {
            return LocalDate.parse(value.trim());
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    private LocalDateTime dateTime(String value) {
        String text = value.trim();
        LocalDateTime parsed = offsetDateTime(text, OFFSET_PATTERN);
        if (parsed == null) {
            parsed = offsetDateTime(text, DateTimeFormatter.ISO_OFFSET_DATE_TIME);
        }
        if (parsed == null) {
            parsed = localDateTime(text);
        }
        return parsed;
    }

    private LocalDateTime offsetDateTime(String text, DateTimeFormatter formatter) {
        try {
            return OffsetDateTime.parse(text, formatter).atZoneSameInstant(clock.getZone()).toLocalDateTime();
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    private LocalDateTime localDateTime(String text) {
        try {
            return LocalDateTime.parse(text);
        } catch (DateTimeParseException e) {
            return null;
        }
    }

    private static String blankToNull(String value) {
        return informed(value) ? value : null;
    }

    private static boolean informed(String value) {
        return value != null && !value.isBlank();
    }

    private static void require(boolean valid, String field) {
        if (!valid) {
            throw ServiceOperationException.missingParameters(field);
        }
    }
}'''

SERVICE_IMPL = '''/** Activity-logged service implementation; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class FinancingServiceImpl implements FinancingService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String AGREEMENT_FIELD = "agreementCodeId";
    private static final String SORT_FIELD = "agreementCodeId";

    private final FinancingRepository repository;
    private final FinancingHistoryRepository historyRepository;
    private final FinancingStateRepository stateRepository;
    private final RequestTypeRepository requestTypeRepository;
    private final InstallmentRepository installmentRepository;
    private final InstallmentHistoryRepository installmentHistoryRepository;
    private final FinancingMapper mapper;
    private final FinancingValidator validator;
    private final FinancingProperties properties;
    private final PersistenceExceptionTranslator translator;
    private final TransactionTemplate transactions;
    private final Clock clock;

    @Override
    public CreateFinancingResponse createFinancing(RequestHeaders headers, CreateFinancingRequest request) {
        String menTran = prefix(headers);
        FinancingDates dates = ejecutarActividad(menTran, ConstanApi.__A_CAMPOS__, () -> validarCreacion(headers, request));
        FinancingEntity saved = transactions.execute(status -> guardar(menTran, headers, request, dates));
        return mapper.createResponse(saved.getAgreementCodeId());
    }

    @Override
    public UpdateFinancingResponse updateFinancing(RequestHeaders headers, UpdateFinancingRequest request) {
        String menTran = prefix(headers);
        FinancingDates dates = ejecutarActividad(menTran, ConstanApi.__A_VALIDAR__, () -> validarActualizacion(headers, request));
        transactions.executeWithoutResult(status -> actualizar(menTran, headers, request, dates));
        return mapper.updateResponse();
    }

    @Override
    public GetFinancingResponse getFinancing(RequestHeaders headers, Long agreementCodeId) {
        String menTran = prefix(headers);
        Long id = ejecutarActividad(menTran, ConstanApi.__A_VALIDAR__, () -> validarIdentificador(headers, "getFinancing", agreementCodeId));
        FinancingEntity row = ejecutarActividad(menTran, ConstanApi.__A_CONSULTAR__, () -> consultar(menTran, id));
        return mapper.getResponse(row);
    }

    @Override
    public DeleteFinancingResponse deleteFinancing(RequestHeaders headers, Long agreementCodeId) {
        String menTran = prefix(headers);
        Long id = ejecutarActividad(menTran, ConstanApi.__A_VALIDAR__, () -> validarIdentificador(headers, "deleteFinancing", agreementCodeId));
        transactions.executeWithoutResult(status -> ejecutarActividad(menTran, ConstanApi.__A_ELIMINAR__, () -> eliminar(menTran, id)));
        return mapper.deleteResponse();
    }

    @Override
    public SearchFinancingResponse searchFinancing(RequestHeaders headers, String dateBegin, String dateEnd, Integer documentCodeId, String documentNumber, String saleOrder,
            String saleChannel, String productCode, Integer financingStateCodeId, Integer hasOverduePayments) {
        String menTran = prefix(headers);
        SearchCriteria criteria = ejecutarActividad(menTran, ConstanApi.__A_VALIDAR__, () -> validarBusqueda(headers, dateBegin, dateEnd, documentCodeId, documentNumber, saleOrder,
                saleChannel, productCode, financingStateCodeId, hasOverduePayments));
        return ejecutarActividad(menTran, ConstanApi.__A_BUSCAR__, () -> buscar(menTran, criteria));
    }

    @Override
    public StateFinancingResponse stateFinancing(RequestHeaders headers) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.__A_VALIDAR__, () -> validarSinParametros(headers, "stateFinancing"));
        return ejecutarActividad(menTran, ConstanApi.__A_ESTADOS__, () -> consultarEstados(menTran));
    }

    @Override
    public RefinancingsAgreementResponse refinancingsAgreement(RequestHeaders headers, Long clientCode, String periodMonths, String processDate) {
        String menTran = prefix(headers);
        RefinancingQuery query = ejecutarActividad(menTran, ConstanApi.__A_VALIDAR__, () -> validarRefinanciamientos(headers, clientCode, periodMonths, processDate));
        return ejecutarActividad(menTran, ConstanApi.__A_CONSULTAR__, () -> contarRefinanciamientos(menTran, query));
    }

    @Override
    public NotificationFinancingResponse notificationFinancing(RequestHeaders headers, String requestTypeIds, String dateBegin, String dateEnd) {
        String menTran = prefix(headers);
        NotificationQuery query = ejecutarActividad(menTran, ConstanApi.__A_VALIDAR__, () -> validarNotificacion(headers, requestTypeIds, dateBegin, dateEnd));
        List<FinancingEntity> pendings = ejecutarActividad(menTran, ConstanApi.__A_PENDIENTES__, () -> obtenerPendientes(menTran, query));
        List<FinancingEntity> errors = ejecutarActividad(menTran, ConstanApi.__A_ERRORES__, () -> obtenerErrores(menTran, query));
        return ejecutarActividad(menTran, ConstanApi.__A_CONSOLIDAR__, () -> mapper.notificationResponse(pendings, errors));
    }

    private FinancingDates validarCreacion(RequestHeaders headers, CreateFinancingRequest request) {
        logRequest("createFinancing", headers);
        ActivityLogger.logContenido(log, "createFinancing body: {}", request, CreateFinancingRequest.class);
        return validator.createFinancing(request);
    }

    private FinancingDates validarActualizacion(RequestHeaders headers, UpdateFinancingRequest request) {
        logRequest("updateFinancing", headers);
        ActivityLogger.logContenido(log, "updateFinancing body: {}", request, UpdateFinancingRequest.class);
        return validator.updateFinancing(request);
    }

    private Long validarIdentificador(RequestHeaders headers, String operation, Long agreementCodeId) {
        logRequest(operation, headers);
        return validator.agreementCodeId(agreementCodeId);
    }

    private SearchCriteria validarBusqueda(RequestHeaders headers, String dateBegin, String dateEnd, Integer documentCodeId, String documentNumber, String saleOrder,
            String saleChannel, String productCode, Integer financingStateCodeId, Integer hasOverduePayments) {
        logRequest("searchFinancing", headers);
        return validator.search(dateBegin, dateEnd, documentCodeId, documentNumber, saleOrder, saleChannel, productCode, financingStateCodeId, hasOverduePayments);
    }

    private Boolean validarSinParametros(RequestHeaders headers, String operation) {
        logRequest(operation, headers);
        return Boolean.TRUE;
    }

    private RefinancingQuery validarRefinanciamientos(RequestHeaders headers, Long clientCode, String periodMonths, String processDate) {
        logRequest("refinancingsAgreement", headers);
        return validator.refinancings(clientCode, periodMonths, processDate);
    }

    private NotificationQuery validarNotificacion(RequestHeaders headers, String requestTypeIds, String dateBegin, String dateEnd) {
        logRequest("notificationFinancing", headers);
        return validator.notificationCandidates(requestTypeIds, dateBegin, dateEnd);
    }

    /** Insert of the financing and of its history snapshot in one transaction: any failure rolls both back. */
    private FinancingEntity guardar(String menTran, RequestHeaders headers, CreateFinancingRequest request, FinancingDates dates) {
        FinancingEntity saved = ejecutarActividad(menTran, ConstanApi.__A_GUARDAR__, () -> insertar(menTran, headers, request, dates));
        ejecutarActividad(menTran, ConstanApi.__A_GUARDAR_HIST__, () -> guardarHistorico(menTran, saved, __L_GUARDAR_HIST__));
        return saved;
    }

    private FinancingEntity insertar(String menTran, RequestHeaders headers, CreateFinancingRequest request, FinancingDates dates) {
        return accederDatos(menTran, __L_GUARDAR__,
                () -> repository.saveAndFlush(mapper.toEntity(request, dates, applicationOf(headers), userOf(headers), LocalDateTime.now(clock))));
    }

    /** Update of the informed fields and history snapshot of the updated row, in one transaction. */
    private void actualizar(String menTran, RequestHeaders headers, UpdateFinancingRequest request, FinancingDates dates) {
        FinancingEntity updated = ejecutarActividad(menTran, ConstanApi.__A_ACTUALIZAR__, () -> actualizarFinanciamiento(menTran, headers, request, dates));
        ejecutarActividad(menTran, ConstanApi.__A_REGISTRAR_HIST__, () -> guardarHistorico(menTran, updated, __L_REGISTRAR_HIST__));
    }

    private FinancingEntity actualizarFinanciamiento(String menTran, RequestHeaders headers, UpdateFinancingRequest request, FinancingDates dates) {
        return accederDatos(menTran, __L_ACTUALIZAR__, () -> {
            FinancingEntity current = repository.findById(request.getAgreementCodeId())
                    .orElseThrow(() -> invalidValue(menTran, ConstanApi.__A_ACTUALIZAR__, AGREEMENT_FIELD));
            mapper.applyUpdate(current, request, dates, userOf(headers), LocalDateTime.now(clock));
            return repository.saveAndFlush(current);
        });
    }

    private Boolean guardarHistorico(String menTran, FinancingEntity financing, String logTimeout, String logErrorDatos) {
        accederDatos(menTran, logTimeout, logErrorDatos, () -> historyRepository.saveAndFlush(mapper.toHistory(financing)));
        return Boolean.TRUE;
    }

    private FinancingEntity consultar(String menTran, Long agreementCodeId) {
        Optional<FinancingEntity> found = accederDatos(menTran, __L_CONSULTAR__, () -> repository.findById(agreementCodeId));
        return found.orElseThrow(() -> notFound(menTran, ConstanApi.__A_CONSULTAR__));
    }

    /** Physical delete, children first: installment history, installments, financing history and finally the financing. */
    private Boolean eliminar(String menTran, Long agreementCodeId) {
        return accederDatos(menTran, __L_ELIMINAR__, () -> {
            installmentHistoryRepository.deleteByAgreementCode(agreementCodeId);
            installmentRepository.deleteByAgreementCode(agreementCodeId);
            historyRepository.deleteByAgreementCode(agreementCodeId);
            repository.deleteByAgreementCode(agreementCodeId);
            return Boolean.TRUE;
        });
    }

    private SearchFinancingResponse buscar(String menTran, SearchCriteria criteria) {
        return accederDatos(menTran, __L_BUSCAR__, () -> {
            List<FinancingEntity> rows = repository.findAll(FinancingSpecifications.search(criteria), Sort.by(SORT_FIELD));
            if (rows.isEmpty()) {
                throw notFound(menTran, ConstanApi.__A_BUSCAR__);
            }
            return mapper.searchResponse(rows, stateDescriptions(rows), requestTypeDescriptions(rows));
        });
    }

    private Map<Integer, String> stateDescriptions(List<FinancingEntity> rows) {
        List<Integer> ids = rows.stream().map(FinancingEntity::getFinancingStateCodeId).filter(Objects::nonNull).distinct().toList();
        Map<Integer, String> descriptions = new HashMap<>();
        stateRepository.findAllById(ids).forEach(state -> descriptions.put(state.getFinancingStateCodeId(), state.getFinancingStateDescription()));
        return descriptions;
    }

    private Map<Integer, String> requestTypeDescriptions(List<FinancingEntity> rows) {
        List<Integer> ids = rows.stream().map(FinancingEntity::getRequestTypeId).filter(Objects::nonNull).distinct().toList();
        Map<Integer, String> descriptions = new HashMap<>();
        requestTypeRepository.findAllById(ids).forEach(type -> descriptions.put(type.getRequestTypeId(), type.getRequestTypeDescription()));
        return descriptions;
    }

    private StateFinancingResponse consultarEstados(String menTran) {
        return accederDatos(menTran, __L_ESTADOS__, () -> {
            List<FinancingStateEntity> rows = stateRepository.findAll(Sort.by("financingStateCodeId"));
            if (rows.isEmpty()) {
                throw notFound(menTran, ConstanApi.__A_ESTADOS__);
            }
            return mapper.stateResponse(rows);
        });
    }

    private RefinancingsAgreementResponse contarRefinanciamientos(String menTran, RefinancingQuery query) {
        return accederDatos(menTran, __L_CONSULTAR__, () -> {
            long active = repository.countByClientCodeAndRequestTypeIdAndFinancingStateCodeId(query.clientCode(), properties.getRefinancingRequestType(),
                    properties.getRefinancingConfirmedState());
            long completed = repository.countInWindow(query.clientCode(), properties.getRefinancingRequestType(), properties.getRefinancingCompletedState(),
                    query.processDate().minusMonths(query.periodMonths()).atStartOfDay(), query.processDate().plusDays(1).atStartOfDay());
            return mapper.refinancingsResponse(active, completed);
        });
    }

    private List<FinancingEntity> obtenerPendientes(String menTran, NotificationQuery query) {
        List<FinancingEntity> rows = accederDatos(menTran, __L_PENDIENTES__, () -> repository.findWithInstallmentStateBetween(properties.getConfirmedState(),
                query.requestTypeIds(), properties.getPendingInstallmentState(), query.dateBegin(), query.dateEnd()));
        return noVacio(menTran, ConstanApi.__A_PENDIENTES__, rows);
    }

    private List<FinancingEntity> obtenerErrores(String menTran, NotificationQuery query) {
        List<FinancingEntity> rows = accederDatos(menTran, __L_ERRORES__,
                () -> repository.findWithInstallmentState(properties.getConfirmedState(), query.requestTypeIds(), properties.getOacErrorInstallmentState()));
        return noVacio(menTran, ConstanApi.__A_ERRORES__, rows);
    }

    private List<FinancingEntity> noVacio(String menTran, String activity, List<FinancingEntity> rows) {
        if (rows.isEmpty()) {
            throw notFound(menTran, activity);
        }
        return rows;
    }

    private ServiceOperationException notFound(String menTran, String activity) {
        ServiceOperationException failure = ServiceOperationException.notFound();
        log.error(ERROR_BUSINESS_PATTERN, menTran, activity, failure.getStatus().value(), failure.getDetail());
        return failure;
    }

    private ServiceOperationException invalidValue(String menTran, String activity, String field) {
        ServiceOperationException failure = ServiceOperationException.missingParameters(field);
        log.error(ERROR_BUSINESS_PATTERN, menTran, activity, failure.getStatus().value(), failure.getDetail());
        return failure;
    }

    private String prefix(RequestHeaders headers) {
        String tx = headers != null ? headers.transactionId() : null;
        return tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
    }

    private String userOf(RequestHeaders headers) {
        return headers != null ? headers.userId() : null;
    }

    private String applicationOf(RequestHeaders headers) {
        return headers != null ? headers.applicationName() : null;
    }

    private void logRequest(String operation, RequestHeaders h) {
        log.info(
                "{} applicationName={}, transactionId={}, userId={}",
                operation,
                h != null ? h.applicationName() : null,
                h != null ? h.transactionId() : null,
                h != null ? h.userId() : null
        );
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


def service_impl():
    text = SERVICE_IMPL
    names = {'__A_CAMPOS__': ACT['Valida campos'], '__A_VALIDAR__': ACT['Validar parametros'], '__A_GUARDAR__': ACT['Guardar Financiamiento'],
             '__A_GUARDAR_HIST__': ACT['Guardar Financiamiento hist\u00f3rico'], '__A_ACTUALIZAR__': ACT['Actualizar Financiamiento'],
             '__A_REGISTRAR_HIST__': ACT['Registrar hist\u00f3rico'], '__A_ELIMINAR__': ACT['Eliminar financiamiento y cuotas asociadas'],
             '__A_CONSULTAR__': ACT['Consultar Financiamientos'], '__A_BUSCAR__': ACT['Buscar Financiamiento'], '__A_ESTADOS__': ACT['Consultar estados de financiamiento'],
             '__A_PENDIENTES__': ACT['obtener financiamientos confirmados con cuotas pendientes'],
             '__A_ERRORES__': ACT['Obtener financiamientos confirmados con cuotas en error envio'], '__A_CONSOLIDAR__': ACT['Consolidar Candidatos de Notificaci\u00f3n']}
    logs = {'__L_GUARDAR__': 'Guardar Financiamiento', '__L_GUARDAR_HIST__': 'Guardar Financiamiento hist\u00f3rico', '__L_ACTUALIZAR__': 'Actualizar Financiamiento',
            '__L_REGISTRAR_HIST__': 'Registrar hist\u00f3rico', '__L_ELIMINAR__': 'Eliminar financiamiento y cuotas asociadas', '__L_CONSULTAR__': 'Consultar Financiamientos',
            '__L_BUSCAR__': 'Buscar Financiamiento', '__L_ESTADOS__': 'Consultar estados de financiamiento',
            '__L_PENDIENTES__': 'obtener financiamientos confirmados con cuotas pendientes', '__L_ERRORES__': 'Obtener financiamientos confirmados con cuotas en error envio'}
    for key in sorted(logs, key=len, reverse=True):
        text = text.replace(key, log(logs[key], key in ('__L_GUARDAR_HIST__', '__L_PENDIENTES__')))
    for key in sorted(names, key=len, reverse=True):
        text = text.replace(key, names[key])
    return text


def build_main(pkg):
    files = {}

    def put(suffix, name, body, statics=()):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = dj.finalize(pkg, suffix, body, statics)

    for cls in ENTITY_TABLES:
        put('model', cls, entity(cls))
    for cls, body in RECORDS.items():
        put('model', cls, body)
    put('dto.request', 'RequestHeaders', REQUEST_HEADERS)
    for cls in REQUEST_CLASSES:
        put('dto.request', cls, request_dto(cls))
    put('dto.response', 'FinancingDto', financing_dto())
    for cls, fields in DATA_DTOS.items():
        put('dto.response', cls, dj.dto(cls, fields, non_null=True))
    for cls, data_type in ENVELOPES.items():
        put('dto.response', cls, dj.envelope(cls, data_type))
    put('dto.response', 'ErrorResponse', dj.ERROR_RESPONSE)
    put('dto.mapper', 'FinancingMapper', mapper())
    put('exception', 'ServiceOperationException', SERVICE_OPERATION_EXCEPTION)
    put('exception', 'PersistenceExceptionTranslator', TRANSLATOR)
    put('exception', 'GlobalExceptionHandler', HANDLER)
    for cls, body in REPOSITORIES.items():
        put('repository', cls, body)
    put('repository', 'FinancingSpecifications', SPECIFICATIONS)
    put('service', 'FinancingService', service_interface())
    put('service.impl', 'FinancingServiceImpl', service_impl())
    put('validation', 'FinancingValidator', VALIDATOR)
    put('controller', 'FinancingApi', api())
    put('controller.impl', 'FinancingController', controller())
    put('configuration', 'ClockConfig', CLOCK_CONFIG)
    put('configuration', 'FinancingProperties', PROPERTIES)
    return files
