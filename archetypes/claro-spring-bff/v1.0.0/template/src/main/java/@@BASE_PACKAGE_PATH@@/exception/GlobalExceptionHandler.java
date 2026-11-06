package @@BASE_PACKAGE@@.exception;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintDeclarationException;
import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import @@BASE_PACKAGE@@.configuration.WsResponseProperties;
import @@BASE_PACKAGE@@.dto.response.ErrorResponse;
import @@BASE_PACKAGE@@.utils.ConstanApi;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

@Slf4j
@ControllerAdvice
public class GlobalExceptionHandler {
    public static final String ERROR = "ERROR";

    private WsResponseProperties wsResponseCatalog;

    @Autowired
    void setWsResponseProperties(WsResponseProperties wsResponseCatalog) {
        if (wsResponseCatalog != null) {
            this.wsResponseCatalog = wsResponseCatalog;
        }
    }


    private String resolveTransactionId(HttpServletRequest req) {
        String transactionId = req.getHeader("transactionId");
        if (transactionId == null || transactionId.isBlank()) {
            return "NO_TRANSACTION_ID";
        }
        return transactionId;
    }


    private ResponseEntity<ErrorResponse> buildStandardError(
            HttpServletRequest req,
            HttpStatus http,
            String code,
            WsResponseProperties.AuditValue auditValue,
            String status,
            String type) {
        return ResponseEntity.status(http).body(ErrorResponse.builder()
                .transactionId(resolveTransactionId(req))
                .code(code)
                .detail(auditValue.detail())
                .message(auditValue.message())
                .status(status)
                .type(type)
                .subType(auditValue.subType())
                .build());
    }

    private ResponseEntity<ErrorResponse> invalidRequest(HttpServletRequest req) {
        return buildStandardError(req, HttpStatus.BAD_REQUEST, ConstanApi.CODE_400,
                wsResponseCatalog.idf1(), ConstanApi.STATUS_FAIL, ConstanApi.TYPE_INVALID_REQUEST);
    }

    private ResponseEntity<ErrorResponse> invalidRequest(HttpServletRequest req, String detail) {
        WsResponseProperties.AuditValue invalidRequest = wsResponseCatalog.idf1();
        return buildStandardError(req, HttpStatus.BAD_REQUEST, ConstanApi.CODE_400,
                new WsResponseProperties.AuditValue(
                        invalidRequest.subType(), invalidRequest.message(), detail),
                ConstanApi.STATUS_FAIL, ConstanApi.TYPE_INVALID_REQUEST);
    }

    private ResponseEntity<ErrorResponse> missingHeader(HttpServletRequest req, String headerName) {
        WsResponseProperties.AuditValue invalidRequest = wsResponseCatalog.idf1();
        return buildStandardError(req, HttpStatus.BAD_REQUEST, ConstanApi.CODE_400,
                new WsResponseProperties.AuditValue(
                        invalidRequest.subType(),
                        invalidRequest.message(),
                        "Headers requeridos inválidos: " + invalidHeadersDetail(req, headerName)),
                ConstanApi.STATUS_FAIL, ConstanApi.TYPE_INVALID_REQUEST);
    }

    private ResponseEntity<ErrorResponse> resourceNotFound(HttpServletRequest req) {
        return buildStandardError(req, HttpStatus.NOT_FOUND, ConstanApi.CODE_404,
                wsResponseCatalog.idt1(), ConstanApi.STATUS_FAIL, ConstanApi.TYPE_RESOURCE_NOT_FOUND);
    }

    private ResponseEntity<ErrorResponse> serviceUnavailable(HttpServletRequest req) {
        return buildStandardError(req, HttpStatus.SERVICE_UNAVAILABLE, ConstanApi.CODE_503,
                wsResponseCatalog.idt2(), ConstanApi.STATUS_ERROR, ConstanApi.TYPE_SERVICE_UNAVAILABLE);
    }

    private ResponseEntity<ErrorResponse> timeout(HttpServletRequest req) {
        return buildStandardError(req, HttpStatus.GATEWAY_TIMEOUT, ConstanApi.CODE_504,
                wsResponseCatalog.idt3(), ConstanApi.STATUS_ERROR, ConstanApi.TYPE_TIMEOUT_ERROR);
    }

    private ResponseEntity<ErrorResponse> internalError(HttpServletRequest req) {
        return buildStandardError(req, HttpStatus.INTERNAL_SERVER_ERROR, ConstanApi.CODE_500,
                wsResponseCatalog.idt4(), ConstanApi.STATUS_ERROR, ConstanApi.TYPE_INTERNAL_ERROR);
    }

    private ResponseEntity<ErrorResponse> conflict(HttpServletRequest req) {
        return buildStandardError(req, HttpStatus.CONFLICT, ConstanApi.CODE_409,
                wsResponseCatalog.idt5(), ConstanApi.STATUS_FAIL, ConstanApi.TYPE_CONFLICT);
    }

    @ExceptionHandler({
            ConstraintViolationException.class,
            ConstraintDeclarationException.class,
            MethodArgumentTypeMismatchException.class,
            BindException.class,
            HttpMessageNotReadableException.class,
            IllegalArgumentException.class
    })
    public ResponseEntity<ErrorResponse> handleBadRequest(Exception ex, HttpServletRequest req) {
        log.error("Validation error", ex);
        return invalidRequest(req);
    }


    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidationErrors(MethodArgumentNotValidException ex, HttpServletRequest req) {

        List<Map<String, String>> errors = new ArrayList<>();

        log.info("Missing request parameter");

        ex.getBindingResult().getFieldErrors().forEach(error -> {
            Map<String, String> err = new HashMap<>();
            err.put("field", error.getField());
            err.put("message", error.getDefaultMessage());
            errors.add(err);
        });

        String detail = errors.stream()
                .map(error -> error.get("message"))
                .filter(Objects::nonNull)
                .filter(message -> !message.isBlank())
                .distinct()
                .collect(Collectors.joining("; "));
        return invalidRequest(req, detail.isBlank() ? wsResponseCatalog.idf1().detail() : detail);
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<ErrorResponse> handleMissingParam(MissingServletRequestParameterException ex,
                                                            HttpServletRequest req) {
        log.error("Missing request parameter", ex);

        return invalidRequest(req, "Faltan parametros obligatorios: " + ex.getParameterName());
    }

    @ExceptionHandler(MissingRequestHeaderException.class)
    public ResponseEntity<ErrorResponse> handleMissingHeader(MissingRequestHeaderException ex,
                                                             HttpServletRequest req) {
        log.error("Missing request header", ex);
        return missingHeader(req, ex.getHeaderName());
    }

    private String invalidHeadersDetail(HttpServletRequest req, String headerName) {
        List<String> details = List.of("transactionId", "msgid", "timestamp", "userId", "accept").stream()
                .filter(header -> req.getHeader(header) == null || req.getHeader(header).isBlank())
                .map(header -> header + (req.getHeader(header) == null ? " no fue enviado" : " está vacío"))
                .toList();
        return details.isEmpty() ? headerName + " no fue enviado" : String.join("; ", details);
    }

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ErrorResponse> handleBusinessException(BusinessException ex, HttpServletRequest req) {
        log.error("Business exception", ex);

        String message = ex.getMessage() != null ? ex.getMessage() : "Error de negocio";

        if (message.contains("NOT_FOUND")) {
            return resourceNotFound(req);
        }
        if (message.contains("TIMEOUT") || message.contains("Timeout")) {
            return timeout(req);
        }
        if (message.contains("NO DISPONIBLE") || message.contains("DISPONIBILIDAD")) {
            return serviceUnavailable(req);
        }
        if (message.contains(ConstanApi.CONFLICT)) {
            return conflict(req);
        }
        return internalError(req);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ErrorResponse> handleNoResource(NoResourceFoundException ex, HttpServletRequest req) {
        return resourceNotFound(req);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleGeneric(Exception ex, HttpServletRequest req) {
        log.error("Unexpected error", ex);
        return internalError(req);
    }

}
