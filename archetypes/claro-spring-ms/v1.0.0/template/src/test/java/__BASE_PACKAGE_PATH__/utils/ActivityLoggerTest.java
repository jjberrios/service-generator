package __BASE_PACKAGE__.utils;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.Logger;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class ActivityLoggerTest {

    @Test
    @DisplayName("logContenido: debe manejar excepciones de serializaciÃ³n en el catch")
    void logContenidoSerializationError() {
        Logger mockLogger = mock(Logger.class);

        // Pasamos un contenido incompatible con el tipo declarado
        Object contenido = new Object();

        assertDoesNotThrow(() ->
                ActivityLogger.logContenido(
                        mockLogger,
                        "Mensaje con body: {}",
                        contenido,
                        // Tipo forzado que no coincide con el contenido para provocar error en convertValue
                        String.class
                )
        );
    }

    @Test
    @DisplayName("logContenido: rama exitosa serializa y llama a log.info")
    void logContenidoSuccessBranch() {
        Logger mockLogger = mock(Logger.class);

        // Usamos un tipo simple que Jackson puede serializar sin problemas
        String contenido = "texto-prueba";

        ActivityLogger.logContenido(
                mockLogger,
                "Mensaje con body: {}",
                contenido,
                String.class
        );

        ArgumentCaptor<String> mensajeCaptor = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> bodyCaptor = ArgumentCaptor.forClass(String.class);

        verify(mockLogger).info(mensajeCaptor.capture(), bodyCaptor.capture());

        assertEquals("Mensaje con body: {}", mensajeCaptor.getValue());
        String bodyJson = bodyCaptor.getValue();
        String trimmed = bodyJson.replace("\n", "").replace(" ", "");
        assertEquals("\"texto-prueba\"", trimmed);
    }
}
