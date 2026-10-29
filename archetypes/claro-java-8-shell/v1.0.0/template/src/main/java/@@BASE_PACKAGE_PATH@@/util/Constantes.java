package @@BASE_PACKAGE@@.util;

/**
 * Constantes tecnicas del batch (shell). Las constantes propias de un servicio
 * (nombres de archivo, mensajes de negocio, campos de integraciones concretas)
 * las agrega el generador a partir de la especificacion funcional.
 */
public class Constantes {

  // Caracteres y separadores
  public final static char SLASH = '/';
  public final static String ESPACIO = " ";
  public final static String MILISEGUNDOS = "milisegundos";
  public final static String PALOTE_BACKSLASH = "\\|";

  // Constantes SFTP
  public static final String SFTP = "sftp";
  public static final String SUCCESS = "SUCCESS";

  // Configuración Spring
  public final static String CONFIG_PATH = "applicationContext.xml";

  // Mensajes de log
  public static final String INICIO_METODO = "{0} [INICIO] - METODO: [{1}]";
  public static final String FIN_METODO = "{0} [FIN] - METODO: [{1}]";
  public static final String ERROR = "{0} Error: ";
  public static final String TIPO_TOTAL_PROCESO = "{0} Tiempo TOTAL Proceso: [{1} milisegundos]";

  // Trazas de proxies de servicios web (patron tecnico; el proxy concreto lo define la especificacion)
  public static final String TRAZA = "[%s][%s] ";
  public static final String INICIO_METODO_PROXY = "{} [INICIO] - PROXY: [{}]";
  public static final String FIN_METODO_PROXY = "{} [FIN] - PROXY: [{}]";
  public static final String INVOCANDO_WS = "{} Invocando WS: [{}]";
  public static final String DATOS_ENVIADOS = "{} Datos enviados:";
  public static final String DATOS_OBTENIDOS = "{} Datos obtenidos:";
  public static final String DATO = "{} {}: [{}]";
  public static final String TIEMPO_TOTAL = "{} Tiempo total: [{} ms]";
  public static final String NESTED_EXCEPTION = "NestedRuntimeException: %s";
  public static final String EXCEPCION = "Exception: %s";
  public static final String CODIGO_RESULTADO = "codigoResultado";
  public static final String MENSAJE_RESULTADO = "mensajeResultado";
  public static final String WS_EXITO = "0";
  public static final String WS_ERROR_GENERAL = "-1";

  // Placeholders para mensajes de error técnico (idt1, idt2, idt3)
  public static final String PLACEHOLDER_RECURSO = "[RECURSO]";
  public static final String PLACEHOLDER_DETALLE  = "[DETALLE]";
}
