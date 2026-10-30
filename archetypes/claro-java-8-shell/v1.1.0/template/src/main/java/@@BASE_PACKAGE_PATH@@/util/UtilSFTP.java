package @@BASE_PACKAGE@@.util;

import com.jcraft.jsch.Channel;
import com.jcraft.jsch.ChannelSftp;
import com.jcraft.jsch.JSch;
import com.jcraft.jsch.Session;
import org.apache.log4j.Logger;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;

public class UtilSFTP {

    private static final Logger logger = Logger.getLogger(UtilSFTP.class);
    
    public static String obtenerArchivo(String trazabilidad, String username, String host,
                                       int puerto, String password, String rutaExterno,
                                       String rutaInterno) {
        Session session = null;
        Channel channel = null;
        ChannelSftp channelSftp = null;

        try {
            logger.info(trazabilidad + " [UtilSFTP.obtenerArchivo] Conectando a SFTP...");
            logger.info(trazabilidad + " Host: " + host + ", Puerto: " + puerto + ", Usuario: " + username);
            logger.info(trazabilidad + " Ruta remota: " + rutaExterno);
            logger.info(trazabilidad + " Ruta local: " + rutaInterno);

            JSch jsch = new JSch();
            session = jsch.getSession(username, host, puerto);
            session.setPassword(password);

            java.util.Properties config = new java.util.Properties();
            config.put("StrictHostKeyChecking", "no");
            session.setConfig(config);
            session.connect();

            logger.info(trazabilidad + " Sesión SFTP establecida");

            channel = session.openChannel(Constantes.SFTP);
            channel.connect();
            channelSftp = (ChannelSftp) channel;

            logger.info(trazabilidad + " Canal SFTP abierto");

            // Extraer nombre del archivo de la ruta
            String nombreArchivo = rutaExterno.substring(rutaExterno.lastIndexOf('/') + 1);
            String rutaLocalCompleta = rutaInterno + nombreArchivo;

            logger.info(trazabilidad + " Descargando archivo: " + nombreArchivo);

            // Crear directorio si no existe
            File dirLocal = new File(rutaInterno);
            if (!dirLocal.exists()) {
                dirLocal.mkdirs();
                logger.info(trazabilidad + " Directorio local creado: " + rutaInterno);
            }

            // Descargar archivo
            FileOutputStream fos = new FileOutputStream(rutaLocalCompleta);
            channelSftp.get(rutaExterno, fos);
            fos.close();

            // Verificar que el archivo no esté vacío
            File archivoDescargado = new File(rutaLocalCompleta);
            if (archivoDescargado.length() == 0) {
                logger.warn(trazabilidad + " ADVERTENCIA: El archivo descargado está vacío");
                return "ERROR: Archivo vacío";
            }

            logger.info(trazabilidad + " Archivo descargado exitosamente. Tamaño: " + archivoDescargado.length() + " bytes");
            return Constantes.SUCCESS;

        } catch (Exception e) {
            logger.error(trazabilidad + " ERROR al obtener archivo desde SFTP: " + e.getMessage(), e);
            return "ERROR: " + e.getMessage();
        } finally {
            if (channelSftp != null && channelSftp.isConnected()) {
                channelSftp.disconnect();
                logger.info(trazabilidad + " Canal SFTP desconectado");
            }
            if (channel != null && channel.isConnected()) {
                channel.disconnect();
            }
            if (session != null && session.isConnected()) {
                session.disconnect();
                logger.info(trazabilidad + " Sesión SFTP cerrada");
            }
        }
    }

    public static boolean enviarArchivo(String trazabilidad, String username, String host,
                                       int puerto, String password, String rutaLocal, String rutaRemota,
                                       String nombreArchivo) {
        Session session = null;
        Channel channel = null;
        ChannelSftp channelSftp = null;

        try {
            logger.info(trazabilidad + " [UtilSFTP.enviarArchivo] Conectando a SFTP...");
            logger.info(trazabilidad + " Host: " + host + ", Puerto: " + puerto + ", Usuario: " + username);
            logger.info(trazabilidad + " Archivo local: " + rutaLocal);
            logger.info(trazabilidad + " Ruta remota: " + rutaRemota);

            JSch jsch = new JSch();
            session = jsch.getSession(username, host, puerto);
            session.setPassword(password);

            java.util.Properties config = new java.util.Properties();
            config.put("StrictHostKeyChecking", "no");
            session.setConfig(config);
            session.connect();

            logger.info(trazabilidad + " Sesión SFTP establecida");

            channel = session.openChannel(Constantes.SFTP);
            channel.connect();
            channelSftp = (ChannelSftp) channel;

            logger.info(trazabilidad + " Canal SFTP abierto");

            // Verificar que el archivo local existe
            File archivoLocal = new File(rutaLocal);
            if (!archivoLocal.exists()) {
                logger.error(trazabilidad + " ERROR: El archivo local no existe: " + rutaLocal);
                return false;
            }

            logger.info(trazabilidad + " Subiendo archivo: " + nombreArchivo + " (Tamaño: " + archivoLocal.length() + " bytes)");

            // Cambiar al directorio remoto (crear si no existe)
            try {
                channelSftp.cd(rutaRemota);
            } catch (Exception e) {
                logger.info(trazabilidad + " Directorio remoto no existe, creando: " + rutaRemota);
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

            // Subir archivo
            FileInputStream fis = new FileInputStream(rutaLocal);
            channelSftp.put(fis, nombreArchivo);
            fis.close();

            logger.info(trazabilidad + " Archivo enviado exitosamente");
            return true;

        } catch (Exception e) {
            logger.error(trazabilidad + " ERROR al enviar archivo a SFTP: " + e.getMessage(), e);
            return false;
        } finally {
            if (channelSftp != null && channelSftp.isConnected()) {
                channelSftp.disconnect();
                logger.info(trazabilidad + " Canal SFTP desconectado");
            }
            if (channel != null && channel.isConnected()) {
                channel.disconnect();
            }
            if (session != null && session.isConnected()) {
                session.disconnect();
                logger.info(trazabilidad + " Sesión SFTP cerrada");
            }
        }
    }

    public static java.util.List<String> listarArchivos(String trazabilidad, String username, String host,
                                                         int puerto, String password, String rutaRemota,
                                                         String fechaEjecucion, String formatoFecha) {
        Session session = null;
        Channel channel = null;
        ChannelSftp channelSftp = null;
        java.util.List<String> listaArchivos = new java.util.ArrayList<>();

        try {
            logger.info(trazabilidad + " [UtilSFTP.listarArchivos] Conectando a SFTP...");
            logger.info(trazabilidad + " Host: " + host + ", Puerto: " + puerto + ", Usuario: " + username);
            logger.info(trazabilidad + " Ruta remota: " + rutaRemota);

            // Determinar la fecha a usar para el filtro
            String fechaFiltro;
            if (fechaEjecucion == null || fechaEjecucion.trim().isEmpty()) {
                // Si está vacío, usar la fecha actual
                java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat(formatoFecha);
                fechaFiltro = sdf.format(new java.util.Date());
                logger.info(trazabilidad + " Fecha de ejecución no especificada. Usando fecha actual: " + fechaFiltro);
            } else {
                fechaFiltro = fechaEjecucion.trim();
                logger.info(trazabilidad + " Fecha de ejecución especificada: " + fechaFiltro);
            }

            JSch jsch = new JSch();
            session = jsch.getSession(username, host, puerto);
            session.setPassword(password);

            java.util.Properties config = new java.util.Properties();
            config.put("StrictHostKeyChecking", "no");
            session.setConfig(config);
            session.connect();

            logger.info(trazabilidad + " Sesión SFTP establecida");

            channel = session.openChannel(Constantes.SFTP);
            channel.connect();
            channelSftp = (ChannelSftp) channel;

            logger.info(trazabilidad + " Canal SFTP abierto");

            // Listar archivos en el directorio
            java.util.Vector<?> listaEntradas = channelSftp.ls(rutaRemota);

            java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat(formatoFecha);

            for (Object entrada : listaEntradas) {
                ChannelSftp.LsEntry lsEntry = (ChannelSftp.LsEntry) entrada;
                String nombreArchivo = lsEntry.getFilename();

                // Filtrar directorios y entradas especiales (. y ..)
                if (!lsEntry.getAttrs().isDir() && !nombreArchivo.equals(".") && !nombreArchivo.equals("..")) {
                    // Obtener fecha de modificación del archivo
                    long mTimeMillis = lsEntry.getAttrs().getMTime() * 1000L; // Convertir segundos a milisegundos
                    java.util.Date fechaModificacion = new java.util.Date(mTimeMillis);
                    String fechaModificacionStr = sdf.format(fechaModificacion);

                    // Filtrar por fecha de modificación
                    if (fechaModificacionStr.equals(fechaFiltro)) {
                        listaArchivos.add(nombreArchivo);
                        logger.info(trazabilidad + " Archivo encontrado: " + nombreArchivo +
                                   " (Tamaño: " + lsEntry.getAttrs().getSize() + " bytes, " +
                                   "Fecha modificación: " + fechaModificacionStr + ")");
                    } else {
                        logger.debug(trazabilidad + " Archivo omitido (fecha no coincide): " + nombreArchivo +
                                    " (Fecha: " + fechaModificacionStr + ", Esperada: " + fechaFiltro + ")");
                        logger.debug(trazabilidad + " Archivo omitido (fecha no coincide): " + nombreArchivo +
                                    " (Fecha: " + fechaModificacionStr + ", Esperada: " + fechaFiltro + ")");
                    }
                }
            }
            return listaArchivos;

        } catch (Exception e) {
            logger.error(trazabilidad + " ERROR al listar archivos desde SFTP: " + e.getMessage(), e);
            return null;
        } finally {
            if (channelSftp != null && channelSftp.isConnected()) {
                channelSftp.disconnect();
                logger.info(trazabilidad + " Canal SFTP desconectado");
            }
            if (channel != null && channel.isConnected()) {
                channel.disconnect();
            }
            if (session != null && session.isConnected()) {
                session.disconnect();
                logger.info(trazabilidad + " Sesión SFTP cerrada");
            }
        }
    }
}
