package @@BASE_PACKAGE@@.exception;

public class BaseExceptionSFTP extends Exception {

  private static final long serialVersionUID = 1L;

  private Exception exception;
  private String code;
  private String message;
  private String servidorFTP;

  private String rutaServidor;
  private String nombreArchivo;
  private String detalle;

  public BaseExceptionSFTP(String code, String message, Exception exception) {
    super(message);
    this.exception = exception;
    this.code = code;
    this.message = message;
  }

  public BaseExceptionSFTP(String code, String message) {
    super(message);
    this.code = code;
    this.message = message;
  }

  public BaseExceptionSFTP(String code, String message, String detalle) {
    super(message);
    this.code = code;
    this.message = message;
    this.detalle = detalle;
  }

  public BaseExceptionSFTP(String message, Exception exception) {
    super(message);
    this.exception = exception;
    this.message = message;
  }

  public BaseExceptionSFTP(Exception exception) {
    this.exception = exception;
  }

  public BaseExceptionSFTP(String message) {
    super(message);
    this.message = message;
  }

  public BaseExceptionSFTP(String servidorFTP, String rutaServidor, String nombreArchivo, Exception objException) {
    super(objException);
    this.servidorFTP = servidorFTP;
    this.rutaServidor = rutaServidor;
    this.nombreArchivo = nombreArchivo;

  }

  public String getMessage() {
    return message;
  }

  public Exception getException() {
    return exception;
  }

  public void setException(Exception exception) {
    this.exception = exception;
  }

  public String getCode() {
    return code;
  }

  public String getServidorFTP() {
    return servidorFTP;
  }

  public void setServidorFTP(String servidorFTP) {
    this.servidorFTP = servidorFTP;
  }

  public String getRutaServidor() {
    return rutaServidor;
  }

  public void setRutaServidor(String rutaServidor) {
    this.rutaServidor = rutaServidor;
  }

  public String getNombreArchivo() {
    return nombreArchivo;
  }

  public void setNombreArchivo(String nombreArchivo) {
    this.nombreArchivo = nombreArchivo;
  }

  public String getDetalle() {
    return detalle;
  }

  public void setDetalle(String detalle) {
    this.detalle = detalle;
  }

}
