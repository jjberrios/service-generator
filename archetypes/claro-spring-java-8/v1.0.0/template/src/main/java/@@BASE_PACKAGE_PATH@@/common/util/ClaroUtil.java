package @@BASE_PACKAGE@@.common.util;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.text.DateFormat;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.TimeZone;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import @@BASE_PACKAGE@@.common.property.Constantes;

public class ClaroUtil {

	private static final Logger log = LoggerFactory.getLogger(ClaroUtil.class);

	private ClaroUtil() {
	}

	public static DateFormat getLocalFormat() {
		DateFormat dateFormat = new SimpleDateFormat(Constantes.FORMATOFECHACABECERA);
		dateFormat.setTimeZone(TimeZone.getDefault());
		return dateFormat;
	}

	public static void printRequest(Object header, Object request) {
		log.info(Constantes.LOG_REQUEST_HEADER, printJSONString(header));
		log.info(Constantes.LOG_REQUEST_BODY, printJSONString(request));
	}

	public static String printPrettyJSONString(Object o) throws JsonProcessingException {
		return new ObjectMapper().setDateFormat(ClaroUtil.getLocalFormat())
				.configure(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS, false).writerWithDefaultPrettyPrinter()
				.writeValueAsString(o);
	}

	public static String printJSONString(Object o) {
		try {
			return new ObjectMapper().setDateFormat(ClaroUtil.getLocalFormat())
					.configure(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS, false).writeValueAsString(o);
		} catch (JsonProcessingException e) {
			log.error(e.getMessage());
			return Constantes.CADENA_VACIA;
		}
	}

	public static String formatoFecha(Date fecha, String formato) {
		return new SimpleDateFormat(formato).format(fecha);
	}

	public static Date obtenerFecha(String fechaString) {
		try {
			return new SimpleDateFormat(Constantes.FORMATOFECHACABECERA).parse(fechaString);
		} catch (ParseException e) {
			log.error(e.getMessage());
			return null;
		}
	}

	public static String obtenerMensajeException(Exception e) {
		if (e.getCause() != null) {
			return e.getCause().toString();
		} else {
			if (e.getMessage() != null) {
				return e.getMessage();
			} else {
				return e.toString();
			}
		}
	}

	public static boolean validParamNullOrEmpty(String parametro) {
		return null == parametro || parametro.isEmpty();
	}

	public static String mapearValor(String properties, String valor) {
		String[] pares = properties.split(Constantes.SEPARADOR_REGISTROS_REGEX);
		for (String par : pares) {
			String[] partes = par.split(Constantes.SEPARADOR_PAR);
			if (partes.length == Constantes.DOS_INT && partes[Constantes.CERO_INT].equals(valor)) {
				return partes[Constantes.UNO_INT];
			}
		}
		return valor;
	}

	public static String obtIpServidor(String msjTx) {
		String ipservidor = Constantes.CADENA_VACIA;
		try {
			String localIpAddress = InetAddress.getLocalHost().getHostAddress();
			InetAddress.getAllByName(localIpAddress);
			ipservidor = localIpAddress;
		} catch (UnknownHostException e) {
			log.info(msjTx, e);
		}
		return ipservidor;
	}

}
