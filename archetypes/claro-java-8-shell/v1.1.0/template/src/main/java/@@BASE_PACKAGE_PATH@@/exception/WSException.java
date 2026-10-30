package @@BASE_PACKAGE@@.exception;

public class WSException extends Exception {

  private static final long serialVersionUID = 1L;

  private String codigo;
  private String mensaje;

  public WSException() {
    super();
  }

  public WSException(String codigo, String mensaje) {
    super(mensaje);
    this.codigo = codigo;
    this.mensaje = mensaje;
  }

  public String getCodigo() {
    return codigo;
  }

  public void setCodigo(String codigo) {
    this.codigo = codigo;
  }

  public String getMensaje() {
    return mensaje;
  }

  public void setMensaje(String mensaje) {
    this.mensaje = mensaje;
  }

  @Override
  public String toString() {
    return "WSException [codigo=" + codigo + ", mensaje=" + mensaje + "]";
  }
}

