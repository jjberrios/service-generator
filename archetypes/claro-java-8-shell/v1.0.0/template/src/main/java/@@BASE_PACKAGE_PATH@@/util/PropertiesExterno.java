package @@BASE_PACKAGE@@.util;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Propiedades externas del batch (shell). Contiene unicamente las propiedades tecnicas
 * observadas en toda la referencia; las propiedades propias de un servicio (endpoints SFTP,
 * rutas, servicios web, fechas de ejecucion) las agrega el generador a partir de la
 * especificacion funcional, con el mismo estilo: campo publico + @Value("${clave.en.minusculas}").
 */
@Component
public class PropertiesExterno {

  @Value("${log4j.file.dir}")
  public String log4jDir;

  // CODIGOS DE RESPUESTA
  @Value("${idf0.codigo}")
  public String idf0Codigo;

  @Value("${idf0.mensaje}")
  public String idf0Mensaje;

  @Value("${idf1.codigo}")
  public String idf1Codigo;

  @Value("${idf1.mensaje}")
  public String idf1Mensaje;

  // CODIGOS DE ERROR TECNICO
  @Value("${idt1.codigo}")
  public String idt1Codigo;

  @Value("${idt1.mensaje}")
  public String idt1Mensaje;

  @Value("${idt2.codigo}")
  public String idt2Codigo;

  @Value("${idt2.mensaje}")
  public String idt2Mensaje;

  @Value("${idt3.codigo}")
  public String idt3Codigo;

  @Value("${idt3.mensaje}")
  public String idt3Mensaje;
}
