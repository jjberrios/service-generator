package @@BASE_PACKAGE@@.utils;

public final class ConstanApi {

    // ===============================
    // HTTP STATUS CODES
    // ===============================
    public static final String CODE_200 = "200";
    public static final String CODE_201 = "201";
    public static final String CODE_400 = "400";
    public static final String CODE_404 = "404";
    public static final String CODE_409 = "409";
    public static final String CODE_500 = "500";
    public static final String CODE_503 = "503";
    public static final String CODE_504 = "504";

    // ===============================
    // ERROR TYPES
    // ===============================
    public static final String NOT_FOUND = "NOT_FOUND";
    public static final String TIMEOUT = "TIMEOUT";
    public static final String UNAVAILABLE = "UNAVAILABLE";
    public static final String INTERNAL_ERROR = "INTERNAL_ERROR";
    public static final String CONFLICT = "CONFLICT";

    // ===============================
    // RESPONSE STATUS
    // ===============================
    public static final String STATUS_SUCCESS = "SUCCESS";
    public static final String STATUS_FAIL = "FAIL";
    public static final String STATUS_ERROR = "ERROR";

    // ===============================
    // RESPONSE TYPES
    // ===============================
    public static final String TYPE_DATA_RETRIEVED = "DATA_RETRIEVED";
    public static final String TYPE_INVALID_REQUEST = "invalidRequest";
    public static final String TYPE_RESOURCE_NOT_FOUND = "resourceNotFound";
    public static final String TYPE_SERVICE_UNAVAILABLE = "serviceUnavailable";
    public static final String TYPE_TIMEOUT_ERROR = "timeoutError";
    public static final String TYPE_INTERNAL_ERROR = "internalError";
    public static final String TYPE_CONFLICT = "conflict";

    // ===============================
    // LOGGING
    // ===============================
    public static final String SEPARADOR = "=========================================================================================";

    public static final String SEPARADOR_ACTIVIDAD = " ========================";

    public static final String INICIO_ACTIVIDAD = "====[INICIO ACTIVIDAD]: ";

    public static final String FIN_ACTIVIDAD = " ======== [ FIN ACTIVIDAD] : ";

    // ===============================
    // APPLICATION
    // ===============================
    public static final String NOMBRE_APLICACION = "@@ARTIFACT_ID@@";

    public static final String MSG_PETICION_PROCESADA_EXITOSAMENTE = "API ejecutada correctamente: ";

    private ConstanApi() {
        // Prevent instantiation
    }
}