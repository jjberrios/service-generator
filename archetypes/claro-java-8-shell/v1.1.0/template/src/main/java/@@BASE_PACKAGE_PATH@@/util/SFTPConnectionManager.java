package @@BASE_PACKAGE@@.util;

import com.jcraft.jsch.Channel;
import com.jcraft.jsch.ChannelSftp;
import com.jcraft.jsch.JSch;
import com.jcraft.jsch.Session;
import org.apache.log4j.Logger;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;

/**
 * Gestor de conexiones SFTP que mantiene las conexiones abiertas para reutilización
 */
public class SFTPConnectionManager {

  private static final Logger logger = Logger.getLogger(SFTPConnectionManager.class);

  private Session session;
  private Channel channel;
  private ChannelSftp channelSftp;
  private String trazabilidad;
  private String connectionInfo;

  /**
   * Constructor que establece la conexión SFTP
   */
  public SFTPConnectionManager(String trazabilidad, String username, String host,
                               int puerto, String password) throws Exception {
    this.trazabilidad = trazabilidad;
    this.connectionInfo = host + ":" + puerto + " (" + username + ")";



    JSch jsch = new JSch();
    session = jsch.getSession(username, host, puerto);
    session.setPassword(password);

    java.util.Properties config = new java.util.Properties();
    config.put("StrictHostKeyChecking", "no");
    session.setConfig(config);
    session.setTimeout(60000); // 60 segundos timeout
    session.connect();


    channel = session.openChannel(Constantes.SFTP);
    channel.connect();
    channelSftp = (ChannelSftp) channel;


  }

  /**
   * Lista archivos en un directorio remoto, filtrando por fecha de modificación (mtime).
   * Las reglas de ventana horaria propias de un proceso de negocio no forman parte del
   * arquetipo: las determina la especificacion funcional.
   */
  public java.util.List<String> listarArchivos(String rutaRemota, String fechaEjecucion,
                                               String formatoFecha) {
    java.util.List<String> listaArchivos = new java.util.ArrayList<>();

    try {
      logger.info(trazabilidad + " [Listando archivos] Ruta: " + rutaRemota);

      java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat(formatoFecha);

      // Determinar la fecha a usar para el filtro
      String fechaFiltro;
      if (fechaEjecucion == null || fechaEjecucion.trim().isEmpty()) {
        fechaFiltro = sdf.format(new java.util.Date());
        logger.info(trazabilidad + " Usando fecha actual: " + fechaFiltro);
      } else {
        fechaFiltro = fechaEjecucion.trim();
        logger.info(trazabilidad + " Usando fecha especificada: " + fechaFiltro);
      }

      // Listar archivos en el directorio
      java.util.Vector<?> listaEntradas = channelSftp.ls(rutaRemota);

      for (Object entrada : listaEntradas) {
        ChannelSftp.LsEntry lsEntry = (ChannelSftp.LsEntry) entrada;
        String nombreArchivo = lsEntry.getFilename();

        if (!lsEntry.getAttrs().isDir() && !nombreArchivo.equals(".") && !nombreArchivo.equals("..")) {
          long mTimeMillis = lsEntry.getAttrs().getMTime() * 1000L;
          java.util.Date fechaModificacion = new java.util.Date(mTimeMillis);
          String fechaModificacionStr = sdf.format(fechaModificacion);

          boolean coincideFecha = fechaModificacionStr.equals(fechaFiltro);

          if (coincideFecha) {
            listaArchivos.add(nombreArchivo);
            logger.info(trazabilidad + " Archivo encontrado: " + nombreArchivo +
              " (Tamaño: " + lsEntry.getAttrs().getSize() + " bytes, " +
              "Fecha: " + fechaModificacionStr + ")");
          }
        }
      }

      return listaArchivos;

    } catch (Exception e) {
      logger.error(trazabilidad + " ERROR al listar archivos: " + e.getMessage(), e);
      return null;
    }
  }

  /**
   * Lista archivos en un directorio remoto, filtrando por la fecha contenida
   * en el NOMBRE del archivo (en lugar de la fecha de modificación/mtime).
   * Usado para tipos de archivo cuyo nombre incluye explícitamente la fecha.
   */
  public java.util.List<String> listarArchivosPorNombreFecha(String rutaRemota, String fechaEjecucion,
                                               String formatoFecha) {
    java.util.List<String> listaArchivos = new java.util.ArrayList<>();

    try {
      logger.info(trazabilidad + " [Listando archivos por nombre] Ruta: " + rutaRemota);

      // Determinar la fecha a usar para el filtro
      String fechaFiltro;
      if (fechaEjecucion == null || fechaEjecucion.trim().isEmpty()) {
        java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat(formatoFecha);
        fechaFiltro = sdf.format(new java.util.Date());
        logger.info(trazabilidad + " Usando fecha actual (nombre archivo): " + fechaFiltro);
      } else {
        fechaFiltro = fechaEjecucion.trim();
        logger.info(trazabilidad + " Usando fecha especificada (nombre archivo): " + fechaFiltro);
      }

      // Listar archivos en el directorio
      java.util.Vector<?> listaEntradas = channelSftp.ls(rutaRemota);

      for (Object entrada : listaEntradas) {
        ChannelSftp.LsEntry lsEntry = (ChannelSftp.LsEntry) entrada;
        String nombreArchivo = lsEntry.getFilename();

        if (!lsEntry.getAttrs().isDir() && !nombreArchivo.equals(".") && !nombreArchivo.equals("..")) {
          if (nombreArchivo.contains(fechaFiltro)) {
            listaArchivos.add(nombreArchivo);
            logger.info(trazabilidad + " Archivo encontrado por nombre: " + nombreArchivo +
              " (Tamaño: " + lsEntry.getAttrs().getSize() + " bytes, " +
              "Fecha en nombre: " + fechaFiltro + ")");
          }
        }
      }

      return listaArchivos;

    } catch (Exception e) {
      logger.error(trazabilidad + " ERROR al listar archivos por nombre: " + e.getMessage(), e);
      return null;
    }
  }

  /**
   * Descarga un archivo desde el servidor SFTP
   */
  public String obtenerArchivo(String rutaRemota, String nombreArchivo, String rutaLocalDestino) {
    try {
      String rutaRemotaCompleta = rutaRemota + nombreArchivo;
      String rutaLocalCompleta = rutaLocalDestino + nombreArchivo;


      // Crear directorio si no existe
      File dirLocal = new File(rutaLocalDestino);
      if (!dirLocal.exists()) {
        dirLocal.mkdirs();
        logger.info(trazabilidad + " Directorio local creado: " + rutaLocalDestino);
      }

      // Descargar archivo
      FileOutputStream fos = new FileOutputStream(rutaLocalCompleta);
      channelSftp.get(rutaRemotaCompleta, fos);
      fos.close();

      // Verificar que el archivo no esté vacío
      File archivoDescargado = new File(rutaLocalCompleta);
      if (archivoDescargado.length() == 0) {
        logger.warn(trazabilidad + " ADVERTENCIA: Archivo vacío");
        return "ALERTA: Archivo vacío";
      }

      logger.info(trazabilidad + " Descarga exitosa. Tamaño: " + archivoDescargado.length() + " bytes");
      return Constantes.SUCCESS;

    } catch (Exception e) {
      logger.error(trazabilidad + " ERROR al descargar archivo: " + e.getMessage(), e);
      return "ERROR: " + e.getMessage();
    }
  }

  /**
   * Envía un archivo al servidor SFTP
   */
  public boolean enviarArchivo(String rutaLocal, String rutaRemota, String nombreArchivo) {
    try {
      logger.info(trazabilidad + " Desde: " + rutaLocal);
      logger.info(trazabilidad + " Hacia: " + rutaRemota);

      // Verificar que el archivo local existe
      File archivoLocal = new File(rutaLocal);
      if (!archivoLocal.exists()) {
        logger.warn(trazabilidad + " Archivo local no existe: " + rutaLocal);
        return false;
      }




      try {
        channelSftp.cd(rutaRemota);
      } catch (Exception e) {
        logger.info(trazabilidad + " Creando directorio remoto: " + rutaRemota);
        String[] carpetas = rutaRemota.split("/");
        String rutaActual = "";
        for (String carpeta : carpetas) {
          if (carpeta.length() > 0) {
            rutaActual += "/" + carpeta;
            try {
              channelSftp.cd(rutaActual);
            } catch (Exception ex) {
              channelSftp.mkdir(rutaActual);
              channelSftp.cd(rutaActual);
            }
          }
        }
      }


      FileInputStream fis = new FileInputStream(rutaLocal);
      channelSftp.put(fis, nombreArchivo);
      fis.close();


      return true;

    } catch (Exception e) {
      logger.error(trazabilidad + " ERROR al enviar archivo: " + e.getMessage(), e);
      return false;
    }
  }

  /**
   * Verifica si la conexión está activa
   */
  public boolean isConnected() {
    return session != null && session.isConnected() &&
      channelSftp != null && channelSftp.isConnected();
  }

  /**
   * Cierra la conexión SFTP
   */
  public void disconnect() {
    try {
      if (channelSftp != null && channelSftp.isConnected()) {
        channelSftp.disconnect();
      }
      if (channel != null && channel.isConnected()) {
        channel.disconnect();
      }
      if (session != null && session.isConnected()) {
        session.disconnect();
      }
    } catch (Exception e) {
      logger.error(trazabilidad + " ERROR al cerrar conexión: " + e.getMessage());
    }
  }

  /**
   * Obtiene información de la conexión para logging
   */
  public String getConnectionInfo() {
    return connectionInfo;
  }
}
