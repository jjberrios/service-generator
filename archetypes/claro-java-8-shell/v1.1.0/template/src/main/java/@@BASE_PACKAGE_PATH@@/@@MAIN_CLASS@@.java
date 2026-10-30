package @@BASE_PACKAGE@@;

import java.text.MessageFormat;

import org.apache.log4j.Logger;
import org.apache.log4j.PropertyConfigurator;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.support.ClassPathXmlApplicationContext;
import org.springframework.stereotype.Component;

import @@BASE_PACKAGE@@.service.@@SERVICE_INTERFACE@@;
import @@BASE_PACKAGE@@.util.Constantes;
import @@BASE_PACKAGE@@.util.PropertiesExterno;

@Component
public class @@MAIN_CLASS@@ {

  private static Logger logger = Logger.getLogger(@@MAIN_CLASS@@.class);

  private static ApplicationContext objContextoSpring;

  @Autowired
  private PropertiesExterno externalProperties;

  @Autowired
  private @@SERVICE_INTERFACE@@ @@SERVICE_FIELD@@;

  public static void main(String[] args) {
    String nomMetodoActual = Thread.currentThread().getStackTrace()[1].getMethodName();
    long tiempoInicio = System.currentTimeMillis();
    String idTransaction = args[0];
    String msjTrx = "[idTx=" + idTransaction + "]";
    try {

      objContextoSpring = new ClassPathXmlApplicationContext(Constantes.CONFIG_PATH);
      @@MAIN_CLASS@@ mainClass = objContextoSpring.getBean(@@MAIN_CLASS@@.class);
      mainClass.loadLog4J();
      logger.info(MessageFormat.format(Constantes.INICIO_METODO, msjTrx, nomMetodoActual));
      mainClass.start(msjTrx, idTransaction);
      logger.info(
          MessageFormat.format(Constantes.TIPO_TOTAL_PROCESO, msjTrx, (System.currentTimeMillis() - tiempoInicio)));
      logger.info(MessageFormat.format(Constantes.FIN_METODO, msjTrx, nomMetodoActual));

    } catch (Exception e) {
      e.printStackTrace();
      logger.error(msjTrx + "Error al inicializar el contexto spring:", e);
    } finally {
      try {
        logger.info(msjTrx + "[FIN de metodo: " + nomMetodoActual + "] Tiempo total de proceso(ms): "
            + (System.currentTimeMillis() - tiempoInicio) + Constantes.ESPACIO + Constantes.MILISEGUNDOS);
        ((ConfigurableApplicationContext) objContextoSpring).close();
      } catch (Exception e) {
        logger.error(msjTrx + "Error al cerrar el contexto spring: ", e);
      }
    }
  }

  private void loadLog4J() {
    PropertyConfigurator.configure(externalProperties.log4jDir);
  }

  public void start(String messageTransaction, String idTransaction) {
    String nomMetodoActual = Thread.currentThread().getStackTrace()[1].getMethodName();
    long tiempoInicio = System.currentTimeMillis();
    String msjTrx = messageTransaction + "[" + nomMetodoActual + "] ";
    logger.info(MessageFormat.format(Constantes.INICIO_METODO, msjTrx, nomMetodoActual));

    try {
      @@SERVICE_FIELD@@.run(msjTrx, idTransaction);
    } catch (Exception e) {
      logger.error(MessageFormat.format(Constantes.ERROR, msjTrx), e);
    } finally {
      logger.info(
          MessageFormat.format(Constantes.TIPO_TOTAL_PROCESO, msjTrx, (System.currentTimeMillis() - tiempoInicio)));
      logger.info(MessageFormat.format(Constantes.FIN_METODO, msjTrx, nomMetodoActual));
    }

  }

}
