"""Java sources of the dom-cpeRequest service (typed, evidence-cited model of the cleared Sparx/OpenAPI behaviour).

Every file is a pure text template; `finalize()` adds the imports that the body really uses and writes accents as unicode escapes so the bytes are
ASCII-only and deterministic. Nothing here reads the file system.
"""
import re

PKG_TOKEN = '__P__'

EXTERNAL = {
    'Column': 'jakarta.persistence.Column', 'Entity': 'jakarta.persistence.Entity', 'GeneratedValue': 'jakarta.persistence.GeneratedValue',
    'GenerationType': 'jakarta.persistence.GenerationType', 'Id': 'jakarta.persistence.Id', 'Lob': 'jakarta.persistence.Lob', 'Table': 'jakarta.persistence.Table',
    'LockModeType': 'jakarta.persistence.LockModeType', 'LocalDateTime': 'java.time.LocalDateTime', 'Clock': 'java.time.Clock', 'Instant': 'java.time.Instant',
    'ZoneOffset': 'java.time.ZoneOffset', 'List': 'java.util.List', 'Set': 'java.util.Set', 'Map': 'java.util.Map', 'Optional': 'java.util.Optional',
    'Supplier': 'java.util.function.Supplier', 'SQLException': 'java.sql.SQLException', 'AllArgsConstructor': 'lombok.AllArgsConstructor', 'Data': 'lombok.Data',
    'NoArgsConstructor': 'lombok.NoArgsConstructor', 'RequiredArgsConstructor': 'lombok.RequiredArgsConstructor', 'Slf4j': 'lombok.extern.slf4j.Slf4j',
    'DynamicInsert': 'org.hibernate.annotations.DynamicInsert', 'DynamicUpdate': 'org.hibernate.annotations.DynamicUpdate',
    'JsonInclude': 'com.fasterxml.jackson.annotation.JsonInclude', 'ObjectMapper': 'com.fasterxml.jackson.databind.ObjectMapper',
    'JsonProcessingException': 'com.fasterxml.jackson.core.JsonProcessingException',
    'JpaRepository': 'org.springframework.data.jpa.repository.JpaRepository', 'Lock': 'org.springframework.data.jpa.repository.Lock',
    'Query': 'org.springframework.data.jpa.repository.Query', 'Param': 'org.springframework.data.repository.query.Param', 'Pageable': 'org.springframework.data.domain.Pageable',
    'PageRequest': 'org.springframework.data.domain.PageRequest', 'Repository': 'org.springframework.stereotype.Repository', 'Component': 'org.springframework.stereotype.Component',
    'Service': 'org.springframework.stereotype.Service', 'Value': 'org.springframework.beans.factory.annotation.Value', 'HttpStatus': 'org.springframework.http.HttpStatus',
    'ResponseEntity': 'org.springframework.http.ResponseEntity', 'DataAccessException': 'org.springframework.dao.DataAccessException',
    'QueryTimeoutException': 'org.springframework.dao.QueryTimeoutException', 'DataIntegrityViolationException': 'org.springframework.dao.DataIntegrityViolationException',
    'TransactionTemplate': 'org.springframework.transaction.support.TransactionTemplate', 'PlatformTransactionManager': 'org.springframework.transaction.PlatformTransactionManager',
    'Configuration': 'org.springframework.context.annotation.Configuration', 'Bean': 'org.springframework.context.annotation.Bean',
    'GetMapping': 'org.springframework.web.bind.annotation.GetMapping', 'PostMapping': 'org.springframework.web.bind.annotation.PostMapping',
    'PatchMapping': 'org.springframework.web.bind.annotation.PatchMapping', 'RequestHeader': 'org.springframework.web.bind.annotation.RequestHeader',
    'RequestParam': 'org.springframework.web.bind.annotation.RequestParam', 'PathVariable': 'org.springframework.web.bind.annotation.PathVariable',
    'RequestBody': 'org.springframework.web.bind.annotation.RequestBody', 'RestController': 'org.springframework.web.bind.annotation.RestController',
    'RestControllerAdvice': 'org.springframework.web.bind.annotation.RestControllerAdvice', 'ExceptionHandler': 'org.springframework.web.bind.annotation.ExceptionHandler',
    'Operation': 'io.swagger.v3.oas.annotations.Operation', 'Content': 'io.swagger.v3.oas.annotations.media.Content', 'Schema': 'io.swagger.v3.oas.annotations.media.Schema',
    'ApiResponse': 'io.swagger.v3.oas.annotations.responses.ApiResponse', 'ApiResponses': 'io.swagger.v3.oas.annotations.responses.ApiResponses',
    'ConstraintViolationException': 'jakarta.validation.ConstraintViolationException', 'NotNull': 'jakarta.validation.constraints.NotNull',
    'HttpHeaders': 'org.springframework.http.HttpHeaders', 'HttpStatusCode': 'org.springframework.http.HttpStatusCode', 'Nullable': 'org.springframework.lang.Nullable',
    'ServletWebRequest': 'org.springframework.web.context.request.ServletWebRequest', 'WebRequest': 'org.springframework.web.context.request.WebRequest',
    'ResponseEntityExceptionHandler': 'org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler',
    'Logger': 'org.slf4j.Logger',
    'Test': 'org.junit.jupiter.api.Test', 'Mockito': 'org.mockito.Mockito', 'ArgumentMatchers': 'org.mockito.ArgumentMatchers', 'Assertions': 'org.junit.jupiter.api.Assertions',
    'MockMvc': 'org.springframework.test.web.servlet.MockMvc', 'MockMvcBuilders': 'org.springframework.test.web.servlet.setup.MockMvcBuilders',
    'MockHttpServletRequest': 'org.springframework.mock.web.MockHttpServletRequest', 'MediaType': 'org.springframework.http.MediaType',
    'MockMvcRequestBuilders': 'org.springframework.test.web.servlet.request.MockMvcRequestBuilders',
    'MockMvcResultMatchers': 'org.springframework.test.web.servlet.result.MockMvcResultMatchers', 'ArrayList': 'java.util.ArrayList',
    'LinkedHashMap': 'java.util.LinkedHashMap', 'HttpMessageNotReadableException': 'org.springframework.http.converter.HttpMessageNotReadableException',
    'MockHttpInputMessage': 'org.springframework.mock.http.MockHttpInputMessage', 'Arrays': 'java.util.Arrays',
}
# Generated classes: simple name -> package suffix under the base package.
INTERNAL = {}


def register(suffix, *names):
    for name in names:
        INTERNAL[name] = suffix


STATIC_CALLS = {}


def strip(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return re.sub(r'//[^\n]*', '', text)


def ascii_escape(text):
    return ''.join(c if ord(c) < 128 else '\\u%04x' % ord(c) for c in text)


def finalize(pkg, suffix, body, statics=()):
    """body: Java text WITHOUT package/imports. Returns the full compilation unit."""
    base = pkg
    own = base + ('.' + suffix if suffix else '')
    code = strip(body)
    words = set(re.findall(r'\b[A-Z][A-Za-z0-9_]*\b', code))
    imports = set()
    for word in words:
        if word in INTERNAL:
            package = base + '.' + INTERNAL[word]
            if package != own:
                imports.add(f'{package}.{word}')
        elif word in EXTERNAL:
            imports.add(EXTERNAL[word])
    lines = [f'package {own};', '']
    statics = [s for s in statics if re.search(r'\b' + s.rsplit('.', 1)[1] + r'\b', code)]
    if statics:
        lines += [f'import static {s};' for s in sorted(statics)] + ['']
    if imports:
        lines += [f'import {i};' for i in sorted(imports)] + ['']
    text = '\n'.join(lines) + '\n' + body.strip('\n') + '\n'
    return ascii_escape(text.replace(PKG_TOKEN, base))


def _fix(imports):
    return imports


# ---------------------------------------------------------------- field based generators
def entity(cls, table, fields):
    out = ['@Data', '@NoArgsConstructor', '@AllArgsConstructor', '@Entity', '@DynamicInsert', '@DynamicUpdate', f'@Table(name = "{table}", schema = "FACEL")', f'public class {cls} {{']
    for java_type, name, column, flag in fields:
        out.append('')
        if flag == 'id':
            out += ['    @Id', '    @GeneratedValue(strategy = GenerationType.IDENTITY)']
        if flag == 'lob':
            out.append('    @Lob')
        out += [f'    @Column(name = "{column}")', f'    private {java_type} {name};']
    out.append('}')
    return '\n'.join(out)


def dto(cls, fields, non_null=False, doc=None):
    out = []
    if doc:
        out += ['/** ' + doc + ' */']
    if non_null:
        out.append('@JsonInclude(JsonInclude.Include.NON_NULL)')
    out += ['@Data', f'public class {cls} {{']
    for java_type, name in fields:
        out.append(f'    private {java_type} {name};')
    out.append('}')
    return '\n'.join(out)


ENTITIES = {
    'CpeRequestEntity': ('EPDREQUEST', [
        ('Long', 'id', 'ID', 'id'), ('String', 'series', 'SERIES', ''), ('Long', 'correlative', 'CORRELATIVE', ''), ('String', 'uniqueReferenceCod', 'UNIQUEREFERENCECOD', ''),
        ('Integer', 'epdTypeId', 'EPDTYPEID', ''), ('String', 'pointOfSale', 'POINTOFSALE', ''), ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''),
        ('Integer', 'generationType', 'GENERATIONTYPE', ''), ('Integer', 'actionType', 'ACTIONTYPE', ''), ('String', 'inputPayload', 'INPUTPAYLOAD', 'lob'),
        ('String', 'plotSovos', 'PLOTSOVOS', 'lob'), ('String', 'installmentSchedulePayload', 'INSTALLMENTSCHEDULEPAYLOAD', 'lob'), ('Integer', 'attemptNumber', 'ATTEMPTNUMBER', ''),
        ('Integer', 'disagreementFlag', 'DISAGREEMENTFLAG', ''), ('String', 'application', 'APPLICATION', ''), ('String', 'operationId', 'OPERATIONID', ''),
        ('String', 'operation', 'OPERATION', ''), ('String', 'channel', 'CHANNEL', ''), ('String', 'documentType', 'DOCUMENTTYPE', ''), ('String', 'documentNumber', 'DOCUMENTNUMBER', ''),
        ('String', 'creationUser', 'CREATIONUSER', ''), ('LocalDateTime', 'creationDate', 'CREATIONDATE', ''), ('String', 'lastModifiedUser', 'LASTMODIFIEDUSER', ''),
        ('LocalDateTime', 'lastModifiedDate', 'LASTMODIFIEDDATE', '')]),
    'CpeRequestHistEntity': ('EPDREQUESTHIST', [
        ('Long', 'id', 'ID', 'id'), ('Long', 'epdRequestId', 'EPDREQUESTID', ''), ('Integer', 'generationType', 'GENERATIONTYPE', ''), ('Integer', 'actionType', 'ACTIONTYPE', ''),
        ('String', 'inputPayload', 'INPUTPAYLOAD', 'lob'), ('String', 'installmentSchedulePayload', 'INSTALLMENTSCHEDULEPAYLOAD', 'lob'), ('Integer', 'attemptNumber', 'ATTEMPTNUMBER', ''),
        ('Integer', 'disagreementFlag', 'DISAGREEMENTFLAG', ''), ('Integer', 'epdQueryStatusId', 'EPDQUERYSTATUSID', ''), ('Integer', 'epdTypeId', 'EPDTYPEID', ''),
        ('String', 'application', 'APPLICATION', ''), ('String', 'operationId', 'OPERATIONID', ''), ('String', 'channel', 'CHANNEL', ''), ('String', 'operation', 'OPERATION', ''),
        ('String', 'creationUser', 'CREATIONUSER', ''), ('LocalDateTime', 'creationDate', 'CREATIONDATE', '')]),
    'CpeQueryEntity': ('EPDQUERY', [
        ('Long', 'id', 'ID', 'id'), ('String', 'queryUserId', 'QUERYUSERID', ''), ('String', 'queryResponsePayload', 'QUERYRESPONSEPAYLOAD', 'lob'), ('String', 'pdfUrl', 'PDFURL', ''),
        ('String', 'xmlUrl', 'XMLURL', ''), ('String', 'cdrUrl', 'CDRURL', ''), ('Long', 'epdRequestId', 'EPDREQUESTID', ''), ('String', 'creationUser', 'CREATIONUSER', ''),
        ('LocalDateTime', 'creationDate', 'CREATIONDATE', ''), ('String', 'lastModifiedUser', 'LASTMODIFIEDUSER', ''), ('LocalDateTime', 'lastModifiedDate', 'LASTMODIFIEDDATE', '')]),
    'CpeQueryStatusEntity': ('EPDQUERYSTATUS', [
        ('Long', 'id', 'ID', 'id'), ('String', 'value', 'VALUE', ''), ('String', 'description', 'DESCRIPTION', ''), ('Integer', 'status', 'STATUS', ''),
        ('String', 'creationUser', 'CREATIONUSER', ''), ('LocalDateTime', 'creationDate', 'CREATIONDATE', ''), ('String', 'lastModifiedUser', 'LASTMODIFIEDUSER', ''),
        ('LocalDateTime', 'lastModifiedDate', 'LASTMODIFIEDDATE', '')]),
}

REQUEST_DTOS = {
    'CreateCpeRequest': [('String', 'series'), ('Long', 'correlative'), ('String', 'referenceCode'), ('Integer', 'epdTypeId'), ('String', 'pointOfSale'), ('Integer', 'epdQueryStatusId'),
                         ('Integer', 'generationType'), ('Integer', 'actionType'), ('String', 'inputPayload'), ('String', 'plotSovos'), ('String', 'installmentSchedulePayload'),
                         ('Integer', 'attemptNumber'), ('Integer', 'disagreementFlag'), ('String', 'application'), ('String', 'operationId'), ('String', 'operation'),
                         ('String', 'channel'), ('String', 'documentType'), ('String', 'documentNumber')],
    'RegisterCpeQueryResultRequest': [('Integer', 'epdQueryStatusId'), ('Map<String, Object>', 'queryResponsePayload'), ('String', 'pdfUrl'), ('String', 'xmlUrl'), ('String', 'cdrUrl')],
    'UpdateCpeEmissionStatusRequest': [('Integer', 'epdQueryStatusId')],
}

RESPONSE_DTOS = {
    'CreateCpeRequestData': [('Long', 'epdRequestId')],
    'CpeRequestReferenceData': [('Long', 'epdRequestId'), ('String', 'series'), ('Long', 'correlative'), ('String', 'uniqueReferenceCode')],
    'CpeEmissionData': [('Long', 'id'), ('String', 'referenceCode'), ('Integer', 'epdTypeId'), ('Integer', 'epdQueryStatusId'), ('String', 'inputPayload'), ('Integer', 'attemptNumber'),
                        ('String', 'disagreementFlag'), ('LocalDateTime', 'creationDate'), ('LocalDateTime', 'lastModifiedDate')],
    'RegisterCpeQueryResultData': [('Boolean', 'success'), ('Integer', 'updatedRows'), ('Long', 'epdQueryId')],
    'CpeEmissionStateItem': [('Long', 'id'), ('Integer', 'status'), ('Integer', 'epdTypeId'), ('String', 'inputPayload'), ('Long', 'nextAfterId')],
    'UpdateCpeEmissionStatusData': [('Boolean', 'success'), ('Integer', 'updatedRows')],
}
ENVELOPES = {
    'CreateCpeRequestResponse': 'CreateCpeRequestData', 'GetCpeRequestByReferenceResponse': 'CpeRequestReferenceData', 'GetCpeEmissionResponse': 'CpeEmissionData',
    'RegisterCpeQueryResultResponse': 'RegisterCpeQueryResultData', 'GetCpeEmissionsByStateResponse': 'List<CpeEmissionStateItem>',
    'UpdateCpeEmissionStatusResponse': 'UpdateCpeEmissionStatusData',
}

register('model', *ENTITIES, 'StatePage')
register('dto.request', 'RequestHeaders', *REQUEST_DTOS)
register('dto.response', 'ErrorResponse', *RESPONSE_DTOS, *ENVELOPES)
register('dto.mapper', 'CpeRequestMapper')
register('exception', 'GlobalExceptionHandler', 'PersistenceExceptionTranslator', 'ServiceOperationException')
register('repository', 'CpeRequestRepository', 'CpeRequestHistRepository', 'CpeQueryRepository', 'CpeQueryStatusRepository')
register('service', 'CpeRequestService')
register('service.impl', 'CpeRequestServiceImpl')
register('validation', 'CpeRequestValidator')
register('utils', 'ActivityLogger', 'ConstanApi')
register('controller', 'CpeRequestApi')
register('controller.impl', 'CpeRequestController')
register('configuration', 'ClockConfig')

HEADERS = [('traceparent', 'traceparent', 'Header OpenTelemetry.'), ('x-app-id', 'xAppId', 'ClientID de la aplicaci\u00f3n en Keycloak.'), ('x-channel', 'xChannel', 'Tipo de canal.'),
           ('x-client-version-id', 'xClientVersionId', 'Versi\u00f3n de la aplicaci\u00f3n.'), ('x-correlation-id', 'xCorrelationId', 'Header generado por el API Gateway. Es \u00fanico.'),
           ('x-request-id', 'xRequestId', 'Identificador \u00fanico del request.'), ('x-user-id', 'xUserId', 'Usuario que inicia la invocaci\u00f3n.')]

# operationId -> (HTTP method, path, summary, response class, success status, declared error statuses, java params [(annotation, type, name, doc)])
OPERATIONS = [
    ('createCpeRequest', 'Post', '/api/v1/cpe-requests', 'Registra una solicitud de comprobante electr\u00f3nico.', 'CreateCpeRequestResponse', '201', ('400', '409', '500', '503', '504'),
     [('@RequestBody', 'CreateCpeRequest', 'request', 'Datos de la solicitud de comprobante electr\u00f3nico.')]),
    ('getCpeRequestByReferenceCode', 'Get', '/api/v1/cpe-requests', 'Consulta una solicitud por c\u00f3digo de referencia.', 'GetCpeRequestByReferenceResponse', '200', ('400', '404', '500', '503', '504'),
     [('@RequestParam(name = "referenceCode", required = true)', 'Long', 'referenceCode', 'C\u00f3digo de referencia \u00fanico de la solicitud.')]),
    ('getCpeEmissionById', 'Get', '/api/v1/emisiones/{id}', 'Consulta el detalle de una emisi\u00f3n por identificador.', 'GetCpeEmissionResponse', '200', ('400', '404', '500', '503', '504'),
     [('@PathVariable("id")', 'Long', 'id', 'Identificador de la solicitud.')]),
    ('registerCpeQueryResult', 'Patch', '/api/v1/emisiones/{id}', 'Registra el resultado de la consulta del comprobante.', 'RegisterCpeQueryResultResponse', '200', ('400', '404', '409', '500', '503', '504'),
     [('@PathVariable("id")', 'Long', 'id', 'Identificador de la solicitud.'), ('@RequestBody', 'RegisterCpeQueryResultRequest', 'request', 'Resultado de la consulta y URLs recibidas.')]),
    ('getCpeEmissionsByState', 'Get', '/api/v1/emisiones/estado/{state}', 'Consulta un lote de emisiones por estado.', 'GetCpeEmissionsByStateResponse', '200', ('400', '404', '500', '503', '504'),
     [('@PathVariable("state")', 'Integer', 'state', 'Identificador del estado.'), ('@RequestParam(name = "afterId", required = false)', 'Long', 'afterId', 'Cursor: solo registros con id mayor.'),
      ('@RequestParam(name = "size", required = false)', 'Integer', 'size', 'Tama\u00f1o m\u00e1ximo del lote.')]),
    ('updateCpeEmissionStatus', 'Patch', '/api/v1/emisiones/{id}/estado', 'Actualiza el estado de una emisi\u00f3n.', 'UpdateCpeEmissionStatusResponse', '200', ('400', '404', '409', '500', '503', '504'),
     [('@PathVariable("id")', 'Long', 'id', 'Identificador de la solicitud.'), ('@RequestBody', 'UpdateCpeEmissionStatusRequest', 'request', 'Nuevo estado de la emisi\u00f3n.')]),
]
REASONS = {'400': 'Bad request', '404': 'Not Found', '409': 'Conflict', '500': 'Internal server error', '503': 'Service unavailable', '504': 'Gateway Timeout'}
SUCCESS_REASON = {'200': 'OK', '201': 'Created'}
ERROR_MESSAGES = {'createCpeRequest': 'PROCESPOST_CPE_REQUEST_SERVICE_ERROR', 'getCpeRequestByReferenceCode': 'PROCESGET_CPE_REQUEST_SERVICE_ERROR',
                  'getCpeEmissionById': 'PROCESGETID_CPE_REQUEST_SERVICE_ERROR', 'registerCpeQueryResult': 'PROCESPATCH_CPE_REQUEST_SERVICE_ERROR',
                  'getCpeEmissionsByState': 'PROCESGETSTATE_CPE_REQUEST_SERVICE_ERROR', 'updateCpeEmissionStatus': 'PROCESPATCHID_CPE_REQUEST_SERVICE_ERROR'}


def api():
    out = ['/**', ' * Define el contrato de los endpoints REST expuestos por el microservicio dom-cpeRequest (contrato OpenAPI).', ' */', 'public interface CpeRequestApi {']
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
        rows = [f'      @ApiResponse(responseCode = "{ok}", description = "{SUCCESS_REASON[ok]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = {response}.class)))']
        rows += [f'      @ApiResponse(responseCode = "{code}", description = "{REASONS[code]}", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ErrorResponse.class)))' for code in errors]
        out += [',\n'.join(rows), '    })', f'    ResponseEntity<{response}> {op}(']
        args = [f'            {annotation} {jtype} {name}' for annotation, jtype, name, _ in params]
        args += [f'            @RequestHeader(name = "{header}", required = true) String {camel}' for header, camel, _ in HEADERS]
        out.append(',\n'.join(args) + ');')
    out.append('}')
    return '\n'.join(out)


def controller():
    out = ['@RestController', '@Slf4j', '@RequiredArgsConstructor', 'public class CpeRequestController implements CpeRequestApi {', '    private final CpeRequestService service;']
    for op, verb, path, summary, response, ok, errors, params in OPERATIONS:
        out += ['', '    @Override', f'    public ResponseEntity<{response}> {op}(']
        args = [f'            {jtype} {name}' for _, jtype, name, _ in params] + [f'            String {camel}' for _, camel, _ in HEADERS]
        out += [',\n'.join(args) + ') {', f'        log.info("{op} - transactionId: {{}}", xCorrelationId);', '        RequestHeaders headers = new RequestHeaders(xCorrelationId, xUserId, xAppId);']
        call = f'service.{op}(headers, ' + ', '.join(name for _, _, name, _ in params) + ')'
        if ok == '201':
            out.append(f'        return ResponseEntity.status(HttpStatus.CREATED).body({call});')
        else:
            out.append(f'        return ResponseEntity.ok({call});')
        out.append('    }')
    out.append('}')
    return '\n'.join(out)


def service_interface():
    out = ['/** Casos de uso de las solicitudes de comprobantes electr\u00f3nicos. */', 'public interface CpeRequestService {']
    for op, verb, path, summary, response, ok, errors, params in OPERATIONS:
        out.append(f'    {response} {op}(RequestHeaders headers, ' + ', '.join(f'{jtype} {name}' for _, jtype, name, _ in params) + ');')
    out.append('}')
    return '\n'.join(out)


def envelope(cls, data_type):
    return '\n'.join(['@Data', f'public class {cls} {{', '    private Integer code;', '    private String message;', f'    private {data_type} data;', '}'])


REPOSITORIES = {
    'CpeRequestRepository': '''@Repository
public interface CpeRequestRepository extends JpaRepository<CpeRequestEntity, Long> {
    Optional<CpeRequestEntity> findFirstByUniqueReferenceCodOrderByIdAsc(String uniqueReferenceCod);

    List<CpeRequestEntity> findByEpdQueryStatusIdAndIdGreaterThanOrderByIdAsc(Integer epdQueryStatusId, Long id, Pageable pageable);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select r from CpeRequestEntity r where r.id = :id")
    Optional<CpeRequestEntity> findForUpdateById(@Param("id") Long id);
}''',
    'CpeRequestHistRepository': '''@Repository
public interface CpeRequestHistRepository extends JpaRepository<CpeRequestHistEntity, Long> {
}''',
    'CpeQueryRepository': '''@Repository
public interface CpeQueryRepository extends JpaRepository<CpeQueryEntity, Long> {
}''',
    'CpeQueryStatusRepository': '''@Repository
public interface CpeQueryStatusRepository extends JpaRepository<CpeQueryStatusEntity, Long> {
}''',
}

STATE_PAGE = '''/** Validated paging command of the emissions-by-state query. */
public record StatePage(Integer state, Long afterId, Integer size) {
}'''

CLOCK_CONFIG = '''/** Single time source of the service: audit dates are derived from this injectable clock. */
@Configuration
public class ClockConfig {
    @Bean
    public Clock clock() {
        return Clock.systemDefaultZone();
    }
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

ERROR_RESPONSE = '''public class ErrorResponse {
    @NotNull
    private Integer code;

    @NotNull
    private String detail;

    @NotNull
    private String message;

    @NotNull
    private String status;

    @NotNull
    private String subType;

    @NotNull
    private String type;

''' + '\n\n'.join(
    f'    public {t} get{n[0].upper() + n[1:]}() {{\n        return {n};\n    }}\n\n    public void set{n[0].upper() + n[1:]}({t} {n}) {{\n        this.{n} = {n};\n    }}'
    for t, n in (('Integer', 'code'), ('String', 'detail'), ('String', 'message'), ('String', 'status'), ('String', 'subType'), ('String', 'type'))) + '\n}'

SERVICE_OPERATION_EXCEPTION = '''/** Application failure that carries the HTTP status decided by the approved behavior. */
public class ServiceOperationException extends RuntimeException {
    private final HttpStatus status;

    public ServiceOperationException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public ServiceOperationException(HttpStatus status, String message, Throwable cause) {
        super(message, cause);
        this.status = status;
    }

    public static ServiceOperationException badRequest(String message) {
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, message);
    }

    public HttpStatus getStatus() {
        return status;
    }
}'''

TRANSLATOR = '''/** Classifies data-access failures (cause chains included) into HTTP statuses: timeout, unique violation, unavailability, otherwise internal error. */
@Component
public class PersistenceExceptionTranslator {
    private static final int ORACLE_UNIQUE_VIOLATION = 1;

    public ServiceOperationException translate(RuntimeException failure) {
        boolean unique = false;
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
            if (cause instanceof SQLException sql) {
                unique |= sql.getErrorCode() == ORACLE_UNIQUE_VIOLATION;
                if (sql.getNextException() != null) {
                    queue.add(sql.getNextException());
                }
            }
            if (cause.getCause() != null) {
                queue.add(cause.getCause());
            }
        }
        HttpStatus status = timeout ? HttpStatus.GATEWAY_TIMEOUT
                : unique ? HttpStatus.CONFLICT
                : unavailable ? HttpStatus.SERVICE_UNAVAILABLE : HttpStatus.INTERNAL_SERVER_ERROR;
        return new ServiceOperationException(status, "Persistence operation failed.", failure);
    }
}'''
TRANSLATOR_IMPORTS = '''import java.sql.SQLNonTransientConnectionException;
import java.sql.SQLRecoverableException;
import java.sql.SQLTimeoutException;
import java.sql.SQLTransientConnectionException;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.IdentityHashMap;
import org.hibernate.exception.JDBCConnectionException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.TransientDataAccessResourceException;
import org.springframework.transaction.CannotCreateTransactionException;
'''

HANDLER = '''@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String TRANSACTION_HEADER = "x-correlation-id";
    private static final Set<HttpStatus> GET_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.NOT_FOUND, HttpStatus.INTERNAL_SERVER_ERROR,
            HttpStatus.SERVICE_UNAVAILABLE, HttpStatus.GATEWAY_TIMEOUT);
    private static final Set<HttpStatus> POST_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.CONFLICT, HttpStatus.INTERNAL_SERVER_ERROR,
            HttpStatus.SERVICE_UNAVAILABLE, HttpStatus.GATEWAY_TIMEOUT);
    private static final Set<HttpStatus> PATCH_STATUSES = Set.of(HttpStatus.BAD_REQUEST, HttpStatus.NOT_FOUND, HttpStatus.CONFLICT,
            HttpStatus.INTERNAL_SERVER_ERROR, HttpStatus.SERVICE_UNAVAILABLE, HttpStatus.GATEWAY_TIMEOUT);

    private final PersistenceExceptionTranslator translator;

    public GlobalExceptionHandler(PersistenceExceptionTranslator translator) {
        this.translator = translator;
    }

    @ExceptionHandler(ServiceOperationException.class)
    public ResponseEntity<ErrorResponse> operationFailure(ServiceOperationException failure, WebRequest request) {
        HttpStatus status = declared(failure.getStatus(), method(request));
        logValidationFailure(request, status, failure.getMessage());
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(error(status, request));
    }

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ErrorResponse> constraintFailure(ConstraintViolationException failure, WebRequest request) {
        logValidationFailure(request, HttpStatus.BAD_REQUEST, failure.getMessage());
        return ResponseEntity.badRequest().contentType(MediaType.APPLICATION_JSON).body(error(HttpStatus.BAD_REQUEST, request));
    }

    @ExceptionHandler(RuntimeException.class)
    public ResponseEntity<ErrorResponse> unexpectedFailure(RuntimeException failure, WebRequest request) {
        return operationFailure(translator.translate(failure), request);
    }

    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception ex, @Nullable Object body,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        HttpStatus resolved = declared(HttpStatus.valueOf(status.value()), method(request));
        logValidationFailure(request, resolved, ex.getClass().getSimpleName());
        HttpHeaders json = new HttpHeaders();
        json.putAll(headers);
        json.setContentType(MediaType.APPLICATION_JSON);
        return new ResponseEntity<>(error(resolved, request), json, status);
    }

    /** A status that the operation does not declare is never emitted: it becomes an internal error. */
    private HttpStatus declared(HttpStatus status, String method) {
        Set<HttpStatus> allowed = switch (method) {
            case "GET" -> GET_STATUSES;
            case "POST" -> POST_STATUSES;
            default -> PATCH_STATUSES;
        };
        return allowed.contains(status) ? status : HttpStatus.INTERNAL_SERVER_ERROR;
    }

    private void logValidationFailure(WebRequest request, HttpStatus status, String reason) {
        if (status != HttpStatus.BAD_REQUEST) {
            return;
        }
        String tx = request.getHeader(TRANSACTION_HEADER);
        String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
        ActivityLogger.inicioActividad(log, menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA);
        log.error("{} ERROR [{}] code={} detail={}", menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, status.value(), reason);
        ActivityLogger.finActividad(log, menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA);
    }

    private ErrorResponse error(HttpStatus status, WebRequest request) {
        ErrorResponse error = new ErrorResponse();
        error.setCode(status.value());
        error.setStatus(status.name());
        error.setMessage(operationMessage(method(request), uri(request), status));
        switch (status) {
            case BAD_REQUEST -> describe(error, "MissingParameters", "IDF1", "Par\\u00e1metros obligatorios incompletos o con valores no v\\u00e1lidos.");
            case NOT_FOUND -> describe(error, "ParameterValueNotFound", "IDF2", "No se encontraron resultados con los datos ingresados.");
            case CONFLICT -> describe(error, "Conflict", "IDF3", "La solicitud ya existe o presenta un conflicto.");
            case INTERNAL_SERVER_ERROR -> describe(error, "InternalError", "IDT3", "Error interno al procesar la transacci\\u00f3n: [ERROR_DETAIL]");
            case SERVICE_UNAVAILABLE -> describe(error, "ServiceUnavailable", "IDT2", "Error de disponibilidad en [SERVICE_NAME] - Detalle: [ERROR_DETAIL]");
            case GATEWAY_TIMEOUT -> describe(error, "TimeoutException", "IDT1", "Error de timeout en [SERVICE_NAME] - Detalle: [ERROR_DETAIL]");
            default -> error.setDetail(status.getReasonPhrase());
        }
        return error;
    }

    private void describe(ErrorResponse error, String type, String subType, String detail) {
        error.setType(type);
        error.setSubType(subType);
        error.setDetail(detail);
    }

    private String operationMessage(String method, String uri, HttpStatus status) {
        if (uri.contains("/emisiones/estado/")) {
            return "PROCESGETSTATE_CPE_REQUEST_SERVICE_ERROR";
        }
        if (uri.contains("/emisiones/")) {
            boolean read = "GET".equals(method);
            boolean statusChange = uri.endsWith("/estado");
            return read ? "PROCESGETID_CPE_REQUEST_SERVICE_ERROR"
                    : statusChange ? "PROCESPATCHID_CPE_REQUEST_SERVICE_ERROR" : "PROCESPATCH_CPE_REQUEST_SERVICE_ERROR";
        }
        if (uri.endsWith("/cpe-requests")) {
            return "POST".equals(method) ? "PROCESPOST_CPE_REQUEST_SERVICE_ERROR" : "PROCESGET_CPE_REQUEST_SERVICE_ERROR";
        }
        return status.getReasonPhrase();
    }

    private String method(WebRequest request) {
        return request instanceof ServletWebRequest servlet ? servlet.getRequest().getMethod() : "";
    }

    private String uri(WebRequest request) {
        return request instanceof ServletWebRequest servlet ? servlet.getRequest().getRequestURI() : "";
    }
}'''

MAPPER = '''/** Explicit mappings between the API contract and the JPA entities; nothing relies on name coincidence. */
@Component
public class CpeRequestMapper {
    private static final String SUCCESS_MESSAGE = "Operaci\u00f3n exitosa";
    private static final String SUCCESS_MESSAGE_WITH_DOT = "Operaci\u00f3n exitosa.";

    public CpeRequestEntity toEntity(CreateCpeRequest request, String user, LocalDateTime now) {
        CpeRequestEntity entity = new CpeRequestEntity();
        entity.setSeries(request.getSeries());
        entity.setCorrelative(request.getCorrelative());
        entity.setUniqueReferenceCod(request.getReferenceCode());
        entity.setEpdTypeId(request.getEpdTypeId());
        entity.setPointOfSale(request.getPointOfSale());
        entity.setEpdQueryStatusId(request.getEpdQueryStatusId());
        entity.setGenerationType(request.getGenerationType());
        entity.setActionType(request.getActionType());
        entity.setInputPayload(request.getInputPayload());
        entity.setPlotSovos(request.getPlotSovos());
        entity.setInstallmentSchedulePayload(request.getInstallmentSchedulePayload());
        entity.setAttemptNumber(request.getAttemptNumber());
        entity.setDisagreementFlag(request.getDisagreementFlag());
        entity.setApplication(request.getApplication());
        entity.setOperationId(request.getOperationId());
        entity.setOperation(request.getOperation());
        entity.setChannel(request.getChannel());
        entity.setDocumentType(request.getDocumentType());
        entity.setDocumentNumber(request.getDocumentNumber());
        entity.setCreationUser(user);
        entity.setCreationDate(now);
        return entity;
    }

    public CpeRequestHistEntity toHistory(CpeRequestEntity request) {
        CpeRequestHistEntity history = new CpeRequestHistEntity();
        history.setEpdRequestId(request.getId());
        history.setGenerationType(request.getGenerationType());
        history.setActionType(request.getActionType());
        history.setInputPayload(request.getInputPayload());
        history.setInstallmentSchedulePayload(request.getInstallmentSchedulePayload());
        history.setAttemptNumber(request.getAttemptNumber());
        history.setDisagreementFlag(request.getDisagreementFlag());
        history.setEpdQueryStatusId(request.getEpdQueryStatusId());
        history.setEpdTypeId(request.getEpdTypeId());
        history.setApplication(request.getApplication());
        history.setOperationId(request.getOperationId());
        history.setChannel(request.getChannel());
        history.setOperation(request.getOperation());
        history.setCreationUser(request.getCreationUser());
        history.setCreationDate(request.getCreationDate());
        return history;
    }

    public CpeQueryEntity toQuery(Long requestId, String payload, RegisterCpeQueryResultRequest request, String user, LocalDateTime now) {
        CpeQueryEntity query = new CpeQueryEntity();
        query.setEpdRequestId(requestId);
        query.setQueryUserId(user);
        query.setQueryResponsePayload(payload);
        query.setPdfUrl(request.getPdfUrl());
        query.setXmlUrl(request.getXmlUrl());
        query.setCdrUrl(request.getCdrUrl());
        query.setCreationUser(user);
        query.setCreationDate(now);
        return query;
    }

    public CreateCpeRequestResponse createResponse(Long requestId) {
        CreateCpeRequestData data = new CreateCpeRequestData();
        data.setEpdRequestId(requestId);
        CreateCpeRequestResponse response = new CreateCpeRequestResponse();
        response.setCode(HttpStatus.CREATED.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    public GetCpeRequestByReferenceResponse referenceResponse(CpeRequestEntity row) {
        CpeRequestReferenceData data = new CpeRequestReferenceData();
        data.setEpdRequestId(row.getId());
        data.setSeries(row.getSeries());
        data.setCorrelative(row.getCorrelative());
        data.setUniqueReferenceCode(row.getUniqueReferenceCod());
        GetCpeRequestByReferenceResponse response = new GetCpeRequestByReferenceResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE_WITH_DOT);
        response.setData(data);
        return response;
    }

    public GetCpeEmissionResponse emissionResponse(CpeRequestEntity row) {
        CpeEmissionData data = new CpeEmissionData();
        data.setId(row.getId());
        data.setReferenceCode(row.getUniqueReferenceCod());
        data.setEpdTypeId(row.getEpdTypeId());
        data.setEpdQueryStatusId(row.getEpdQueryStatusId());
        data.setInputPayload(row.getInputPayload());
        data.setAttemptNumber(row.getAttemptNumber());
        data.setDisagreementFlag(text(row.getDisagreementFlag()));
        data.setCreationDate(row.getCreationDate());
        data.setLastModifiedDate(row.getLastModifiedDate());
        GetCpeEmissionResponse response = new GetCpeEmissionResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    public GetCpeEmissionsByStateResponse stateResponse(List<CpeRequestEntity> rows) {
        Long next = rows.isEmpty() ? null : rows.get(rows.size() - 1).getId();
        List<CpeEmissionStateItem> data = rows.stream().map(row -> stateItem(row, next)).toList();
        GetCpeEmissionsByStateResponse response = new GetCpeEmissionsByStateResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private CpeEmissionStateItem stateItem(CpeRequestEntity row, Long next) {
        CpeEmissionStateItem item = new CpeEmissionStateItem();
        item.setId(row.getId());
        item.setStatus(row.getEpdQueryStatusId());
        item.setEpdTypeId(row.getEpdTypeId());
        item.setInputPayload(row.getInputPayload());
        item.setNextAfterId(next);
        return item;
    }

    public RegisterCpeQueryResultResponse registerResponse(int updatedRows, Long queryId) {
        RegisterCpeQueryResultData data = new RegisterCpeQueryResultData();
        data.setSuccess(Boolean.TRUE);
        data.setUpdatedRows(updatedRows);
        data.setEpdQueryId(queryId);
        RegisterCpeQueryResultResponse response = new RegisterCpeQueryResultResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    public UpdateCpeEmissionStatusResponse statusResponse(int updatedRows) {
        UpdateCpeEmissionStatusData data = new UpdateCpeEmissionStatusData();
        data.setSuccess(Boolean.TRUE);
        data.setUpdatedRows(updatedRows);
        UpdateCpeEmissionStatusResponse response = new UpdateCpeEmissionStatusResponse();
        response.setCode(HttpStatus.OK.value());
        response.setMessage(SUCCESS_MESSAGE);
        response.setData(data);
        return response;
    }

    private static String text(Object value) {
        return value == null ? null : value.toString();
    }
}'''

VALIDATOR = '''/** Declared contract rules (required fields, enumerations, limits) and lossless conversions from contract values to typed commands. */
@Component
public class CpeRequestValidator {
    private static final Set<Integer> EPD_TYPE_IDS = Set.of(1, 2, 3, 4, 5);
    private static final Set<Integer> QUERY_STATUS_IDS = Set.of(1, 2, 3, 4, 5, 6, 7);
    private static final Set<Integer> GENERATION_TYPES = Set.of(1, 2);
    private static final Set<Integer> ACTION_TYPES = Set.of(1, 2);
    private static final Set<Integer> DISAGREEMENT_FLAGS = Set.of(0, 1);
    private static final int URL_MAX_LENGTH = 255;
    private static final Integer REJECTED_STATUS_ID = 7;
    private static final String INVALID_PARAMETERS = "Par\u00e1metros obligatorios incompletos o con valores no v\u00e1lidos.";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final int defaultSize;
    private final int maxSize;

    public CpeRequestValidator(@Value("${api.pagination.defaultSize:50}") int defaultSize, @Value("${api.pagination.maxSize:100}") int maxSize) {
        this.defaultSize = defaultSize;
        this.maxSize = maxSize;
    }

    public CreateCpeRequest createCpeRequest(CreateCpeRequest request) {
        require(request != null);
        require(!blank(request.getSeries()));
        require(request.getCorrelative() != null);
        require(!blank(request.getReferenceCode()));
        require(request.getEpdTypeId() != null && EPD_TYPE_IDS.contains(request.getEpdTypeId()));
        require(request.getEpdQueryStatusId() != null && QUERY_STATUS_IDS.contains(request.getEpdQueryStatusId()));
        require(request.getGenerationType() != null && GENERATION_TYPES.contains(request.getGenerationType()));
        require(request.getActionType() != null && ACTION_TYPES.contains(request.getActionType()));
        require(!blank(request.getInputPayload()));
        require(request.getAttemptNumber() != null && request.getAttemptNumber() >= 0);
        require(request.getDisagreementFlag() != null && DISAGREEMENT_FLAGS.contains(request.getDisagreementFlag()));
        return request;
    }

    public Long referenceCode(Long referenceCode) {
        require(referenceCode != null);
        return referenceCode;
    }

    public Long id(Long id) {
        require(id != null && id > 0);
        return id;
    }

    /** Returns the response payload serialized as JSON text (null when absent). */
    public String registerCpeQueryResult(Long id, RegisterCpeQueryResultRequest request) {
        id(id);
        require(request != null && request.getEpdQueryStatusId() != null);
        require(urlLength(request.getPdfUrl()) && urlLength(request.getXmlUrl()) && urlLength(request.getCdrUrl()));
        if (!REJECTED_STATUS_ID.equals(request.getEpdQueryStatusId())) {
            require(!blank(request.getPdfUrl()) && !blank(request.getXmlUrl()) && !blank(request.getCdrUrl()));
        }
        return payloadText(request.getQueryResponsePayload());
    }

    public UpdateCpeEmissionStatusRequest updateCpeEmissionStatus(Long id, UpdateCpeEmissionStatusRequest request) {
        id(id);
        require(request != null && request.getEpdQueryStatusId() != null);
        return request;
    }

    public StatePage statePage(Integer state, Long afterId, Integer size) {
        require(state != null && state > 0);
        require(afterId == null || afterId >= 0);
        require(size == null || size > 0 && size <= maxSize);
        return new StatePage(state, afterId == null ? Long.valueOf(0L) : afterId, size == null ? Integer.valueOf(defaultSize) : size);
    }

    private String payloadText(Map<String, Object> payload) {
        if (payload == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw ServiceOperationException.badRequest(INVALID_PARAMETERS);
        }
    }

    private static boolean urlLength(String value) {
        return value == null || value.length() <= URL_MAX_LENGTH;
    }

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private static void require(boolean valid) {
        if (!valid) {
            throw ServiceOperationException.badRequest(INVALID_PARAMETERS);
        }
    }
}'''

SERVICE_IMPL = '''/** Activity-logged service implementation; logging is instrumentation only and never changes statuses or return values. */
@Service
@RequiredArgsConstructor
@Slf4j
public class CpeRequestServiceImpl implements CpeRequestService {
    private static final String NO_TRANSACTION_PREFIX = "[SIN-TRANSACTION] ";
    private static final String ERROR_TECHNICAL_PATTERN = "{} {}: {}";
    private static final String ERROR_BUSINESS_PATTERN = "{} ERROR [{}] code={} detail={}";
    private static final String NOT_FOUND_DETAIL = "No matching record.";
    private static final String UNKNOWN_STATUS_DETAIL = "Estado inexistente.";
    private static final String DISABLED_STATUS_DETAIL = "Estado deshabilitado.";
    private static final Integer REJECTED_STATUS_ID = 7;
    private static final int ENABLED_STATUS = 1;
    private static final int UPDATED_ROWS = 1;
    private static final int NOT_UPDATED_ROWS = 0;

    private final CpeRequestRepository repository;
    private final CpeRequestHistRepository historyRepository;
    private final CpeQueryRepository queryRepository;
    private final CpeQueryStatusRepository statusRepository;
    private final CpeRequestMapper mapper;
    private final CpeRequestValidator validator;
    private final PersistenceExceptionTranslator translator;
    private final TransactionTemplate transactions;
    private final Clock clock;

    @Override
    public CreateCpeRequestResponse createCpeRequest(RequestHeaders headers, CreateCpeRequest request) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validarCreacion(headers, request));
        CpeRequestEntity saved = ejecutarActividad(menTran, ConstanApi.ACT2_INSERTAR_COMPROBANTE, () -> insertarComprobante(menTran, request, userOf(headers)));
        ejecutarActividad(menTran, ConstanApi.ACT3_GUARDAR_HISTORICO, () -> guardarHistorico(menTran, saved));
        return mapper.createResponse(saved.getId());
    }

    @Override
    public GetCpeRequestByReferenceResponse getCpeRequestByReferenceCode(RequestHeaders headers, Long referenceCode) {
        String menTran = prefix(headers);
        Long code = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validarReferencia(headers, referenceCode));
        CpeRequestEntity row = ejecutarActividad(menTran, ConstanApi.ACT2_OBTENER_SOLICITUD, () -> obtenerSolicitud(menTran, code));
        return mapper.referenceResponse(row);
    }

    @Override
    public GetCpeEmissionResponse getCpeEmissionById(RequestHeaders headers, Long id) {
        String menTran = prefix(headers);
        Long requestId = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validarIdentificador(headers, "getCpeEmissionById", id));
        CpeRequestEntity row = ejecutarActividad(menTran, ConstanApi.ACT2_CONSULTAR_SOLICITUD_CPE_POR_ID, () -> consultarPorId(menTran, requestId));
        return mapper.emissionResponse(row);
    }

    @Override
    public RegisterCpeQueryResultResponse registerCpeQueryResult(RequestHeaders headers, Long id, RegisterCpeQueryResultRequest request) {
        String menTran = prefix(headers);
        String payload = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validarResultado(headers, id, request));
        Long queryId = ejecutarActividad(menTran, ConstanApi.ACT2_ACTUALIZAR_ESTADO_DEL_CPE, () -> registrarResultado(menTran, id, request, payload, userOf(headers)));
        return mapper.registerResponse(UPDATED_ROWS, queryId);
    }

    @Override
    public GetCpeEmissionsByStateResponse getCpeEmissionsByState(RequestHeaders headers, Integer state, Long afterId, Integer size) {
        String menTran = prefix(headers);
        StatePage page = ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validarEstado(headers, state, afterId, size));
        List<CpeRequestEntity> rows = ejecutarActividad(menTran, ConstanApi.ACT2_CONSULTAR_LOTE_DE_EMISIONES_POR_ESTADO, () -> consultarLote(menTran, page));
        return mapper.stateResponse(rows);
    }

    @Override
    public UpdateCpeEmissionStatusResponse updateCpeEmissionStatus(RequestHeaders headers, Long id, UpdateCpeEmissionStatusRequest request) {
        String menTran = prefix(headers);
        ejecutarActividad(menTran, ConstanApi.ACT1_VALIDAR_PARAMETROS_DE_ENTRADA, () -> validarCambioEstado(headers, id, request));
        Integer rows = ejecutarActividad(menTran, ConstanApi.ACT2_ACTUALIZAR_ESTADO_DE_LA_SOLICITUD_CPE, () -> cambiarEstado(menTran, id, request, userOf(headers)));
        return mapper.statusResponse(rows);
    }

    private Boolean validarCreacion(RequestHeaders headers, CreateCpeRequest request) {
        logRequest("createCpeRequest", headers);
        ActivityLogger.logContenido(log, "createCpeRequest body: {}", request, CreateCpeRequest.class);
        validator.createCpeRequest(request);
        return Boolean.TRUE;
    }

    private Long validarReferencia(RequestHeaders headers, Long referenceCode) {
        logRequest("getCpeRequestByReferenceCode", headers);
        return validator.referenceCode(referenceCode);
    }

    private Long validarIdentificador(RequestHeaders headers, String operation, Long id) {
        logRequest(operation, headers);
        return validator.id(id);
    }

    private String validarResultado(RequestHeaders headers, Long id, RegisterCpeQueryResultRequest request) {
        logRequest("registerCpeQueryResult", headers);
        ActivityLogger.logContenido(log, "registerCpeQueryResult body: {}", request, RegisterCpeQueryResultRequest.class);
        return validator.registerCpeQueryResult(id, request);
    }

    private StatePage validarEstado(RequestHeaders headers, Integer state, Long afterId, Integer size) {
        logRequest("getCpeEmissionsByState", headers);
        return validator.statePage(state, afterId, size);
    }

    private Boolean validarCambioEstado(RequestHeaders headers, Long id, UpdateCpeEmissionStatusRequest request) {
        logRequest("updateCpeEmissionStatus", headers);
        ActivityLogger.logContenido(log, "updateCpeEmissionStatus body: {}", request, UpdateCpeEmissionStatusRequest.class);
        validator.updateCpeEmissionStatus(id, request);
        return Boolean.TRUE;
    }

    private CpeRequestEntity insertarComprobante(String menTran, CreateCpeRequest request, String user) {
        LocalDateTime now = LocalDateTime.now(clock);
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_INSERTAR_COMPROBANTE, ConstanApi.LOG_ERROR_DATOS_ACT2_INSERTAR_COMPROBANTE,
                () -> transactions.execute(status -> repository.saveAndFlush(mapper.toEntity(request, user, now))));
    }

    /** A failure while saving the history never fails the request: the process continues (Sparx: ACT 3). */
    private Boolean guardarHistorico(String menTran, CpeRequestEntity saved) {
        try {
            transactions.executeWithoutResult(status -> historyRepository.saveAndFlush(mapper.toHistory(saved)));
        } catch (RuntimeException e) {
            log.error(ERROR_TECHNICAL_PATTERN, menTran, ConstanApi.LOG_ERROR_DATOS_ACT3_GUARDAR_HISTORICO, e.getMessage());
        }
        return Boolean.TRUE;
    }

    private CpeRequestEntity obtenerSolicitud(String menTran, Long code) {
        Optional<CpeRequestEntity> found = accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_OBTENER_SOLICITUD, ConstanApi.LOG_ERROR_DATOS_ACT2_OBTENER_SOLICITUD,
                () -> repository.findFirstByUniqueReferenceCodOrderByIdAsc(String.valueOf(code)));
        return found.orElseThrow(() -> notFound(menTran, ConstanApi.ACT2_OBTENER_SOLICITUD));
    }

    private CpeRequestEntity consultarPorId(String menTran, Long id) {
        Optional<CpeRequestEntity> found = accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_CONSULTAR_SOLICITUD_CPE_POR_ID,
                ConstanApi.LOG_ERROR_DATOS_ACT2_CONSULTAR_SOLICITUD_CPE_POR_ID, () -> repository.findById(id));
        return found.orElseThrow(() -> notFound(menTran, ConstanApi.ACT2_CONSULTAR_SOLICITUD_CPE_POR_ID));
    }

    private List<CpeRequestEntity> consultarLote(String menTran, StatePage page) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_CONSULTAR_LOTE_DE_EMISIONES_POR_ESTADO,
                ConstanApi.LOG_ERROR_DATOS_ACT2_CONSULTAR_LOTE_DE_EMISIONES_POR_ESTADO, () -> leerLote(menTran, page));
    }

    private List<CpeRequestEntity> leerLote(String menTran, StatePage page) {
        requireStatus(menTran, ConstanApi.ACT2_CONSULTAR_LOTE_DE_EMISIONES_POR_ESTADO, page.state(), false);
        return repository.findByEpdQueryStatusIdAndIdGreaterThanOrderByIdAsc(page.state(), page.afterId(), PageRequest.of(0, page.size()));
    }

    private Long registrarResultado(String menTran, Long id, RegisterCpeQueryResultRequest request, String payload, String user) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_ACTUALIZAR_ESTADO_DEL_CPE, ConstanApi.LOG_ERROR_DATOS_ACT2_ACTUALIZAR_ESTADO_DEL_CPE,
                () -> transactions.execute(status -> aplicarResultado(menTran, id, request, payload, user)));
    }

    private Long aplicarResultado(String menTran, Long id, RegisterCpeQueryResultRequest request, String payload, String user) {
        String activity = ConstanApi.ACT2_ACTUALIZAR_ESTADO_DEL_CPE;
        CpeRequestEntity current = repository.findForUpdateById(id).orElseThrow(() -> notFound(menTran, activity));
        requireStatus(menTran, activity, request.getEpdQueryStatusId(), true);
        LocalDateTime now = LocalDateTime.now(clock);
        current.setEpdQueryStatusId(request.getEpdQueryStatusId());
        current.setLastModifiedUser(user);
        current.setLastModifiedDate(now);
        repository.saveAndFlush(current);
        if (REJECTED_STATUS_ID.equals(request.getEpdQueryStatusId())) {
            return null;
        }
        return queryRepository.saveAndFlush(mapper.toQuery(current.getId(), payload, request, user, now)).getId();
    }

    private Integer cambiarEstado(String menTran, Long id, UpdateCpeEmissionStatusRequest request, String user) {
        return accederDatos(menTran, ConstanApi.LOG_TIMEOUT_ACT2_ACTUALIZAR_ESTADO_DE_LA_SOLICITUD_CPE,
                ConstanApi.LOG_ERROR_DATOS_ACT2_ACTUALIZAR_ESTADO_DE_LA_SOLICITUD_CPE, () -> transactions.execute(status -> aplicarEstado(menTran, id, request, user)));
    }

    private Integer aplicarEstado(String menTran, Long id, UpdateCpeEmissionStatusRequest request, String user) {
        String activity = ConstanApi.ACT2_ACTUALIZAR_ESTADO_DE_LA_SOLICITUD_CPE;
        CpeRequestEntity current = repository.findById(id).orElseThrow(() -> notFound(menTran, activity));
        requireStatus(menTran, activity, request.getEpdQueryStatusId(), false);
        if (request.getEpdQueryStatusId().equals(current.getEpdQueryStatusId())) {
            return NOT_UPDATED_ROWS;
        }
        current.setEpdQueryStatusId(request.getEpdQueryStatusId());
        current.setLastModifiedUser(user);
        current.setLastModifiedDate(LocalDateTime.now(clock));
        repository.saveAndFlush(current);
        return UPDATED_ROWS;
    }

    private void requireStatus(String menTran, String activity, Integer statusId, boolean mustBeEnabled) {
        Optional<CpeQueryStatusEntity> found = statusRepository.findById(Long.valueOf(statusId));
        if (found.isEmpty()) {
            throw badRequest(menTran, activity, UNKNOWN_STATUS_DETAIL);
        }
        Integer enabled = found.get().getStatus();
        if (mustBeEnabled && (enabled == null || enabled != ENABLED_STATUS)) {
            throw badRequest(menTran, activity, DISABLED_STATUS_DETAIL);
        }
    }

    private ServiceOperationException notFound(String menTran, String activity) {
        log.error(ERROR_BUSINESS_PATTERN, menTran, activity, HttpStatus.NOT_FOUND.value(), NOT_FOUND_DETAIL);
        return new ServiceOperationException(HttpStatus.NOT_FOUND, NOT_FOUND_DETAIL);
    }

    private ServiceOperationException badRequest(String menTran, String activity, String detail) {
        log.error(ERROR_BUSINESS_PATTERN, menTran, activity, HttpStatus.BAD_REQUEST.value(), detail);
        return new ServiceOperationException(HttpStatus.BAD_REQUEST, detail);
    }

    private String prefix(RequestHeaders headers) {
        String tx = headers != null ? headers.transactionId() : null;
        return tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;
    }

    private String userOf(RequestHeaders headers) {
        return headers != null ? headers.userId() : null;
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

# (constant suffix, Sparx activity title, data access?)
ACTIVITIES = [
    ('ACT1_VALIDAR_PARAMETROS_DE_ENTRADA', 'VALIDAR_PARAMETROS_DE_ENTRADA', False),
    ('ACT2_INSERTAR_COMPROBANTE', 'INSERTAR_COMPROBANTE', True),
    ('ACT3_GUARDAR_HISTORICO', 'GUARDAR_HISTORICO', True),
    ('ACT2_OBTENER_SOLICITUD', 'OBTENER_SOLICITUD', True),
    ('ACT2_CONSULTAR_SOLICITUD_CPE_POR_ID', 'CONSULTAR_SOLICITUD_CPE_POR_ID', True),
    ('ACT2_ACTUALIZAR_ESTADO_DEL_CPE', 'ACTUALIZAR_ESTADO_DEL_CPE', True),
    ('ACT2_CONSULTAR_LOTE_DE_EMISIONES_POR_ESTADO', 'CONSULTAR_LOTE_DE_EMISIONES_POR_ESTADO', True),
    ('ACT2_ACTUALIZAR_ESTADO_DE_LA_SOLICITUD_CPE', 'ACTUALIZAR_ESTADO_DE_LA_SOLICITUD_CPE', True),
]


def activity_constants():
    lines = []
    for const, value, _ in ACTIVITIES:
        lines.append(f'    public static final String {const} = "{value}";')
    lines += ['', '    // Mensajes log (actividades con acceso a datos)']
    for const, value, data in ACTIVITIES:
        if not data:
            continue
        name = const
        if const != 'ACT3_GUARDAR_HISTORICO':
            lines += [f'    public static final String LOG_TIMEOUT_{name} =', f'            "Timeout en la actividad {value}: ";', '']
        lines += [f'    public static final String LOG_ERROR_DATOS_{name} =', f'            "Error de acceso a datos en la actividad {value}: ";', '']
    return '\n'.join(lines).rstrip('\n')


def build_main(pkg):
    files = {}

    def put(suffix, name, body, statics=()):
        files[f'src/main/java/{pkg.replace(".", "/")}/{suffix.replace(".", "/") + "/" if suffix else ""}{name}.java'] = finalize(pkg, suffix, body, statics)

    for cls, (table, fields) in ENTITIES.items():
        put('model', cls, entity(cls, table, fields))
    put('model', 'StatePage', STATE_PAGE)
    put('dto.request', 'RequestHeaders', REQUEST_HEADERS)
    for cls, fields in REQUEST_DTOS.items():
        put('dto.request', cls, dto(cls, fields))
    for cls, fields in RESPONSE_DTOS.items():
        put('dto.response', cls, dto(cls, fields, non_null=True))
    for cls, data_type in ENVELOPES.items():
        put('dto.response', cls, envelope(cls, data_type))
    put('dto.response', 'ErrorResponse', ERROR_RESPONSE)
    put('dto.mapper', 'CpeRequestMapper', MAPPER)
    put('exception', 'ServiceOperationException', SERVICE_OPERATION_EXCEPTION)
    translator = finalize(pkg, 'exception', TRANSLATOR)
    translator = translator.replace('import org.springframework.http.HttpStatus;', 'import org.springframework.http.HttpStatus;\n' + TRANSLATOR_IMPORTS.strip('\n'))
    files[f'src/main/java/{pkg.replace(".", "/")}/exception/PersistenceExceptionTranslator.java'] = translator
    put('exception', 'GlobalExceptionHandler', HANDLER)
    for cls, body in REPOSITORIES.items():
        put('repository', cls, body)
    put('service', 'CpeRequestService', service_interface())
    put('service.impl', 'CpeRequestServiceImpl', SERVICE_IMPL)
    put('validation', 'CpeRequestValidator', VALIDATOR)
    put('controller', 'CpeRequestApi', api())
    put('controller.impl', 'CpeRequestController', controller())
    put('configuration', 'ClockConfig', CLOCK_CONFIG)
    return files
