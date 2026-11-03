# Informe de extracción — claro-java-8-shell / 1.0.0 (version nueva)

Fecha: 2026-10-30. Operación: extracción de **versión nueva** derivada de 1.0.0 (la 1.0.0
permanece congelada e intacta). Referencia (solo lectura):
`input/reference/SH_ObtenerTrasladarArchivosMTC`. Instrucción del usuario (SH-D-011): recuperar la
infraestructura técnica reutilizable que 1.0.0 excluyó por considerarla negocio.

Estado: aprobada por instrucción del usuario; `frozen: false`, `generationEnabled: true` (SH-D-017),
`readyToFreeze: false` (SH-D-016). Decisiones SH-D-001…010 preservadas; nuevas SH-D-011…016.

## Qué se incluyó de nuevo respecto a 1.0.0

| Elemento | Archivo / lugar | Decisión |
|---|---|---|
| Proxy SOAP de descifrado (interfaz) | `template/src/main/java/@@BASE_PACKAGE_PATH@@/proxy/EbsConsultaClavesWSService.java` | SH-D-012 |
| Proxy SOAP de descifrado (impl, clasificación idt1/idt2/idt3) | `.../proxy/EbsConsultaClavesWSServiceImpl.java` | SH-D-012 |
| Contexto Spring del cliente JAX-WS | `template/src/main/resources/applicationProxyWS.xml` (verbatim) | SH-D-012/013 |
| `import` del contexto de proxy | `applicationContext.xml` (idéntico a la referencia tras tokens) | SH-D-012 |
| Constantes `DESENCRIPTAR`, `ID_TRANSACCION`, `CODIGO_APLICACION`, `USUARIO` | `Constantes.java` | SH-D-012 |
| Propiedades `ws.ebsConsultaClavesWS.{url,max.request.timeout,max.connection.timeout,codigo.aplicacion}` | `PropertiesExterno.java` (solo si se descifra) | SH-D-012/013 |
| Prerrequisito `Lib/` + endpoint del operador | `README.MD`, `externalPrerequisites` | SH-D-013 |
| Patrones técnicos del servicio (método a método) | `generation.servicePatterns` (9 entradas, rangos de línea verificados) | SH-D-014 |
| Contrato técnico del descifrador (operación/campos/namespace/servicio/puerto) | `servicePatterns.credentialDecryptContract` (verificado contra el WSDL) | SH-D-013 |

## Qué se excluyó y por qué

- **Lógica de negocio MTC** (mapa SUSPENSION/NOTIFICACION/IDENTIFICACION/REPORTE, rutas, filtros por
  nombre/mtime, ventana de medianoche, de-duplicación Reporte/Identificación, contadores, regla
  idf0/idf1, textos MTC; `MTC_`, `REPLACE_FECHA_*`, `ERROR_CONEXION_MTC`; claves `ftp.*`,
  `sftp.mtc.*`, `ruta.temp.trasladar.mtc`): Sparx (SH-D-014).
- **WSDL** del descifrador: contiene `soap:address` con IP/puerto de entorno; el cliente ya está
  en el jar de `Lib/`; contrato técnico documentado sin la dirección (SH-D-013).
- **Jars de `Lib/`** y **clases `pe/**`**: binarios propietarios; el cliente de descifrado es
  prerrequisito externo declarado en el POM.
- **Correo/notificación**: la referencia no tiene código, XML, constantes ni POM que lo use; solo
  `EnvioCorreoSB-Client` en `Lib/` sin uso ni declaración. No se inventa nada (SH-D-015).
- `ojdbc6` (sin persistencia), `applicationDatasource.xml`, IDE, `.properties` protegidos
  (no abiertos en esta extracción), tests de negocio: como en 1.0.0.

## Parámetros

Sin parámetros `@@` nuevos (9 usados exactamente; `BASE_PACKAGE`/`BASE_PACKAGE_PATH` alcanzan 2
archivos más). Nuevas **variables externas jinja2** (valor del operador, no secreto):
`ws_ebsconsultaclavesws_url`, `_max_request_timeout`, `_max_connection_timeout`, `_codigo_aplicacion`.

## Resultado

| Elemento | Cantidad |
|---|---|
| Archivos de la referencia (todos con disposición) | 51 |
| Archivos del template | 16 (sin config j2, UtilSFTP, BaseException ni PropertiesException) |
| Utilitarios/proxies en `generation.utilities` | 9 → 11 |
| Dependencias / plugins | 14 / 7 (POM sin cambios) |
| Decisiones aprobadas | 16 (10 heredadas + 6 nuevas) |

## Validación estática

`validate_inventory.py` (común): passed. `validate-extraction.py` (1.0.0): passed — incluye
hash de la referencia sin cambios (49 archivos permitidos + inventario de 51 rutas), plantillas
idénticas a la referencia tras tokens (15), solo eliminaciones exactas en `Constantes`/`PropertiesExterno`,
consistencia de claves `.j2` = `@Value` = marcadores del XML, contrato del descifrador == WSDL,
rangos de `servicePatterns`, ausencia de WSDL/jar/dirección de entorno, sin comportamiento de correo,
sin secretos/IP, 1.0.0 sigue congelada.

## No verificado

Maven, compilación (requiere el jar de `Lib/` fuera del arquetipo), JUnit, JaCoCo, Sonar,
compatibilidad Spring 3.1/Java 8, comportamiento real del proxy JAX-WS. Checkstyle: no aplica.

## Backend

El backend batch actual (IR v1: connect/disconnect/list/for-each/download/upload) **no soporta** el
correo; el descifrado SOAP está soportado de forma acotada (SH-D-021).
