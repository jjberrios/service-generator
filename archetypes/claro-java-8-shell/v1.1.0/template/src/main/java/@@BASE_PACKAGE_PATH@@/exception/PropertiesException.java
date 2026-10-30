package @@BASE_PACKAGE@@.exception;

public class PropertiesException extends RuntimeException {

  private static final long serialVersionUID = -1324456679431478277L;

  public PropertiesException() {
    super();
  }

  public PropertiesException(Exception e) {
    super(e);
  }

  public PropertiesException(String message) {
    super(message);
  }

  public PropertiesException(String message, Exception e) {
    super(message, e);
  }
}
