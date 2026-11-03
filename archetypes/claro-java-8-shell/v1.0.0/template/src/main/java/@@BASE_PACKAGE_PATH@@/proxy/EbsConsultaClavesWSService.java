package @@BASE_PACKAGE@@.proxy;

import pe.com.claro.eai.ebs.operaciones.consultaclaves.DesencriptarRequest;
import pe.com.claro.eai.ebs.operaciones.consultaclaves.DesencriptarResponse;
import @@BASE_PACKAGE@@.exception.WSException;

public interface EbsConsultaClavesWSService {

  DesencriptarResponse desencriptar(String mensajeTransaccion, DesencriptarRequest request)
      throws WSException;
}

