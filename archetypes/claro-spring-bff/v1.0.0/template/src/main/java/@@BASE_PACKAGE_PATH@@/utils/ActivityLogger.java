package @@BASE_PACKAGE@@.utils;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;

public class ActivityLogger {

    private ActivityLogger() {
    }

    public static void inicioActividad(Logger logger,
                                       String mensajeTransaccion,
                                       String actividad) {

        logger.info("{}{}", mensajeTransaccion, ConstanApi.SEPARADOR);
        logger.info("{}{}{}{}", mensajeTransaccion, ConstanApi.INICIO_ACTIVIDAD, actividad, ConstanApi.SEPARADOR_ACTIVIDAD);
        logger.info("{}{}", mensajeTransaccion, ConstanApi.SEPARADOR);
    }

    public static void finActividad(Logger logger,
                                    String mensajeTransaccion,
                                    String actividad) {

        logger.info("{}{}", mensajeTransaccion, ConstanApi.SEPARADOR);
        logger.info("{}{}{}{}", mensajeTransaccion, ConstanApi.FIN_ACTIVIDAD, actividad, ConstanApi.SEPARADOR_ACTIVIDAD);
        logger.info("{}{}", mensajeTransaccion, ConstanApi.SEPARADOR);
    }

    public static <T> void logContenido(Logger log, String mensaje,
                                        Object contenido, Class<T> tipo) {

        ObjectMapper mapper = new ObjectMapper();
        try {
            T objeto = mapper.convertValue(contenido, tipo);
            String bodyJson = mapper.writerWithDefaultPrettyPrinter().writeValueAsString(objeto);
            log.info(mensaje, bodyJson);
        } catch (Exception e) {
            log.error("Error serializando body: {}", e.getMessage());
        }

    }

}
