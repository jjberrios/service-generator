package @@BASE_PACKAGE@@.proxy;

import org.apache.log4j.Logger;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.NestedRuntimeException;
import org.springframework.stereotype.Service;

import pe.com.claro.eai.ebs.operaciones.consultaclaves.DesencriptarRequest;
import pe.com.claro.eai.ebs.operaciones.consultaclaves.DesencriptarResponse;
import pe.com.claro.eai.ebs.operaciones.consultaclaves.EbsConsultaClavesPortType;
import @@BASE_PACKAGE@@.exception.WSException;
import @@BASE_PACKAGE@@.util.Constantes;
import @@BASE_PACKAGE@@.util.PropertiesExterno;

@Service
public class EbsConsultaClavesWSServiceImpl implements EbsConsultaClavesWSService {

  private final Logger logger = Logger.getLogger(EbsConsultaClavesWSServiceImpl.class);

  @Autowired
  private PropertiesExterno prop;

  @Autowired
  private EbsConsultaClavesPortType consultaClavesWS;

  @Override
  public DesencriptarResponse desencriptar(String mensajeTransaccion, DesencriptarRequest request)
      throws WSException {
    long tiempoInicio = System.currentTimeMillis();
    String cadenaTrazabilidad = mensajeTransaccion
        .concat(String.format(Constantes.TRAZA, this.getClass().getSimpleName(), Constantes.DESENCRIPTAR));
    logger.info(cadenaTrazabilidad + " [INICIO] - PROXY: [" + Constantes.DESENCRIPTAR + "]");

    DesencriptarResponse response = null;
    try {
      logger.info(cadenaTrazabilidad + " Invocando WS: [" + prop.wsEbsConsultaClavesWSUrl + "]");

      response = this.consultaClavesWS.desencriptar(request);

      logger.info(cadenaTrazabilidad + " Datos obtenidos:");
      logger.info(cadenaTrazabilidad + " " + Constantes.CODIGO_RESULTADO + ": [" + response.getCodigoResultado() + "]");
      logger.info(cadenaTrazabilidad + " " + Constantes.MENSAJE_RESULTADO + ": [" + response.getMensajeResultado() + "]");

      if (!Constantes.WS_EXITO.equals(response.getCodigoResultado())) {
        throw new WSException(response.getCodigoResultado(), response.getMensajeResultado());
      }

    } catch (WSException e) {
      throw e;
    } catch (NestedRuntimeException e) {
      throw buildWSException(cadenaTrazabilidad, e);
    } catch (Exception e) {
      throw buildWSException(cadenaTrazabilidad, e);
    } finally {
      logger.info(cadenaTrazabilidad + " Tiempo total: [" + (System.currentTimeMillis() - tiempoInicio) + " ms]");
      logger.info(cadenaTrazabilidad + " [FIN] - PROXY: [" + Constantes.DESENCRIPTAR + "]");
    }
    return response;
  }

  /**
   * Inspecciona la cadena de causas y lanza el WSException con el código idt correcto:
   *   idt1 – Timeout        : SocketTimeoutException en la causa
   *   idt2 – Disponibilidad : ConnectException / UnknownHostException / NoRouteToHostException
   *   idt3 – Error general  : cualquier otra excepción
   */
  private WSException buildWSException(String trazabilidad, Throwable e) {
    String tipo = clasificarExcepcionRed(e);
    String codigo;
    String mensaje;

    if ("TIMEOUT".equals(tipo)) {
      codigo  = prop.idt1Codigo;
      mensaje = prop.idt1Mensaje.replace(Constantes.PLACEHOLDER_RECURSO, prop.wsEbsConsultaClavesWSUrl);
    } else if ("DISPONIBILIDAD".equals(tipo)) {
      codigo  = prop.idt2Codigo;
      mensaje = prop.idt2Mensaje.replace(Constantes.PLACEHOLDER_RECURSO, prop.wsEbsConsultaClavesWSUrl);
    } else {
      codigo  = prop.idt3Codigo;
      String detalle = e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
      mensaje = prop.idt3Mensaje.replace(Constantes.PLACEHOLDER_DETALLE, detalle);
    }

    logger.error(trazabilidad + " [" + codigo + "] " + mensaje, e);
    return new WSException(codigo, mensaje);
  }

  /**
   * Recorre la cadena de causas para determinar la naturaleza del error de red.
   * Retorna: "TIMEOUT" | "DISPONIBILIDAD" | "GENERAL"
   */
  private String clasificarExcepcionRed(Throwable e) {
    Throwable causa = e;
    while (causa != null) {
      if (causa instanceof java.net.SocketTimeoutException) {
        return "TIMEOUT";
      }
      if (causa instanceof java.net.ConnectException
          || causa instanceof java.net.UnknownHostException
          || causa instanceof java.net.NoRouteToHostException) {
        return "DISPONIBILIDAD";
      }
      causa = causa.getCause();
    }
    return "GENERAL";
  }
}
