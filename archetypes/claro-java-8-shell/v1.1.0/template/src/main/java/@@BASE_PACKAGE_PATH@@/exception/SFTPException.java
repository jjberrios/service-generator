package @@BASE_PACKAGE@@.exception;

public class SFTPException extends BaseExceptionSFTP {

  private static final long serialVersionUID = 1L;

  public SFTPException(String servidorFTP, String rutaServidor, String nombreArchivo, Exception objException) {
    super(servidorFTP, rutaServidor, nombreArchivo, objException);
  }

  public SFTPException(String code, String message, String detalle) {
    super(code, message, detalle);
  }
}