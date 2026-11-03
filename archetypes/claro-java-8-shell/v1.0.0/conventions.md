# Convenciones — claro-java-8-shell / 1.0.0 (version nueva, SH-D-018..021)

Estado: versión nueva derivada de 1.0.0 (intacta y congelada); aprobada por instrucción del
usuario (SH-D-011); **no congelada y sin generación habilitada** (SH-D-016). No implica
compilación ni ejecución verificadas.
Todo lo aquí descrito es **observado en la referencia**
`input/reference/SH_ObtenerTrasladarArchivosMTC`. Decisiones aprobadas siguiendo
íntegramente esa referencia (ver `decisions.md`); limitaciones externas no verificadas.
No son estándares corporativos universales ni se heredan
de `claro-spring-ms` ni de `claro-spring-java-8`.

## 1. Tipo de proyecto: batch / shell (no HTTP)

- Aplicación Java 8 empaquetada como **jar ejecutable**, lanzada como proceso
  (`java -jar`). **No hay endpoints HTTP** (ni GET ni POST), ni controladores, ni DTOs de
  contrato, ni servidor de aplicaciones.
- Se prueba mediante una **ejecución (running)** del jar con un archivo externo de
  propiedades; la referencia solo trae una prueba unitaria JUnit4/Mockito del servicio.
- Contrato de entrada: argumento de línea de comandos 0 = `idTransaccion` (obligatorio, sin
  validar) + propiedad JVM `properties` (ruta del archivo de propiedades externo).

## 2. Punto de entrada y flujo técnico (E-MAIN, E-CONTEXT)

1. `public static void main(String[] args)` en una clase `@Component` `<Nombre>Main`.
2. `idTransaction = args[0]`; `msjTrx = "[idTx=" + idTransaction + "]"`.
3. `new ClassPathXmlApplicationContext("applicationContext.xml")` (constante
   `Constantes.CONFIG_PATH`): `annotation-config`, `component-scan` del paquete base y
   `property-placeholder location="file:${properties}"`.
4. `getBean(<Nombre>Main.class)` → `loadLog4J()` (`PropertyConfigurator.configure(log4jDir)`,
   clave `log4j.file.dir`) → `start(msjTrx, idTransaction)`.
5. `start` delega en `<Nombre>Service.run(msjTrx, idTransaccion)`; cualquier `Exception`
   se registra con `logger.error` y **no se propaga**.
6. `finally`: registra tiempo total y cierra el contexto Spring (`close()`), con su propio
   `try/catch`.
7. No existe `System.exit`: el proceso termina con estado 0 aunque falle el flujo, salvo
   que falte `args[0]` (excepción antes del `try`). Los códigos idf0/idf1/idt* **solo se
   registran en log** (diferencia con el README conservada por SH-Q-001).

Flujo típico del servicio observado (patrón técnico; contenido funcional = Sparx):
leer propiedades → (opcional) obtener credenciales → abrir conexiones → iterar elementos con
contadores éxito/error y resumen → decidir código idf0/idf1 → capturar por tipo
(`WSException`, `SFTPException`, `Exception` con mensaje idt3) → `finally` cerrar conexiones →
registrar fin y tiempo.

## 3. Ejecución y empaquetado (E-POM, E-README)

- `packaging=jar`, Java `1.8` (`maven.compiler.source/target`), UTF-8.
- `maven-jar-plugin 2.4`: manifest con `mainClass`, `addClasspath=true`,
  `classpathPrefix=LIB/`.
- `maven-shade-plugin 3.5.0` (fase `package`, `createDependencyReducedPom=false`,
  `ManifestResourceTransformer` con la misma `mainClass`) → jar ejecutable único.
- `maven-dependency-plugin 2.5.1` `copy-dependencies` → `target/LIB/` (redundante con
  shade; conservado tal cual).
- `maven-resources-plugin 3.1.0` `copy-resources` (fase `package`, `filtering=true`) copia
  `templates/*`, `log4j.properties` y `<Nombre>.properties` desde `src/main/resources` a
  `target/`; **ninguno de esos recursos existe** en la referencia (SH-Q-003). Con
  `filtering=true`, los `${...}` de esos archivos serían filtrados por Maven (riesgo a
  considerar si se añaden).
- Comando de ejecución (derivado; **no verificado**, no hay script lanzador):
  `java -Dproperties=<ruta>/<Nombre>.properties -jar <artifact>-<version>.jar <idTransaccion>`.
- Sin Maven wrapper, sin `settings.xml`, sin perfiles, sin `dependencyManagement`/
  `pluginManagement`, sin `parent`. Repositorio local `repo` = `file://${project.basedir}/Lib`
  (prerequisito externo para artefactos no públicos). `distributionManagement` local.

## 4. Build, dependencias y plugins (E-POM)

14 dependencias directas (11 compile, 3 test) y 7 plugins, inventariados en `archetype.yml`
(`build.dependencies`, `build.dependencyUsage`, `build.plugins`). Declarar no implica usar:
`commons-logging`, `commons-lang`, `slf4j-api`, `slf4j-log4j12` no tienen import directo observado (`spring-web` se usa desde el
XML plantillado `applicationProxyWS.xml`); la propiedad `com.fasterxml.jackson.core`
y `endorsed.dir` no se referencian. Todo se preserva sin podar ni modernizar.

## 5. Estructura de código (E-MAIN, E-SERVICE-IFACE, E-EXCEPTIONS)

```text
src/main/java/<paquete>/
  <Nombre>Main.java                 # @Component con main
  service/<Nombre>Service.java      # interface: run(String messageTransaction, String idTransaccion)
  service/<Nombre>ServiceImpl.java  # (Sparx) @Service, @Autowired PropertiesExterno
  proxy/EbsConsultaClavesWSService.java  EbsConsultaClavesWSServiceImpl.java   # (template, SH-D-012) proxy SOAP de descifrado; otros proxies: Sparx
  util/Constantes.java  PropertiesExterno.java  SFTPConnectionManager.java
  exception/BaseExceptionSFTP SFTPException WSException
src/main/resources/applicationContext.xml   (importa applicationProxyWS.xml; + otros contextos generados)
src/main/resources/applicationProxyWS.xml   (JaxWsPortProxyFactoryBean del descifrador)
src/test/java/<paquete>/service/<Nombre>ServiceImplTest.java
```

Inyección por campo (`@Autowired`), sin constructores; sin DTOs ni mappers (no hay evidencia).

## 6. Estilo de código y externalización (generation.style; E-CONSTANTS, E-PROPERTIES-CLASS)

- Constantes: clase `util.Constantes` con `public static final` (separadores, `SFTP`,
  `SUCCESS`, `CONFIG_PATH`, patrones de log `INICIO_METODO`/`FIN_METODO`/`ERROR`/
  `TIPO_TOTAL_PROCESO` con `MessageFormat` `{0}{1}`, patrones de proxy con `{}` de
  logger, placeholders `[RECURSO]`/`[DETALLE]`).
- Propiedades externas: clase `util.PropertiesExterno` (`@Component`) con **campos públicos
  mutables** `@Value("${clave.dotted}")`, sin getters (los tests los asignan directamente);
  nombres de campo mezclados (UPPER_SNAKE y lowerCamel); claves en minúsculas con puntos
  (`ftp.externo.host`, `idf0.codigo`, `ws.<servicio>.url`).
- Códigos/mensajes de respuesta externalizados: `idf0/idf1` (funcional), `idt1/idt2/idt3`
  (técnico: timeout, disponibilidad, general) con placeholders de mensaje.
- **Literales en duro: observado MIXTO** (`hardcodedLiterals: allowed`): hay constantes para
  patrones de log/SFTP, pero el servicio y las utilidades usan además literales inline
  (textos de log, `"ERROR: "`, `"ALERTA: "`, claves de mapa). La referencia no prohíbe
  literales; se mantiene este estilo por SH-Q-007. Los valores de entorno nunca van en código.
- Excepciones: `BaseExceptionSFTP`/`WSException` heredan de `Exception` (comprobadas);
  `SFTPException extends BaseExceptionSFTP`. `BaseException`, `PropertiesException` y
  `UtilSFTP` no se incluyen: el servicio generado no los usa (SH-D-019).
- Nombres: `<Nombre>Main`, `<Nombre>Service`/`ServiceImpl`, `<Ws>WSService`/`WSServiceImpl`,
  `*Test`. Indentación Java de 2 espacios (utilidades SFTP usan 4/2: se conserva), XML 3
  espacios (`.editorConfig`).
- Testabilidad: métodos `protected` de fábrica/delegación (`crearConexionSFTP`) para espiar con Mockito sin PowerMock.

## 7. Logging (E-MAIN, E-SFTP-MANAGER)

- log4j 1.2 directo: `Logger.getLogger(X.class)` (`private static`, `private final` o
  `private static final` según clase). Sin SLF4J en código, sin ActivityLogger, sin
  Logback.
- Configuración externa: archivo log4j cuya ruta está en `log4j.file.dir`; se configura con
  `PropertyConfigurator` **después** de crear el contexto Spring. El archivo no existe en la
  referencia (SH-Q-003).
- Prefijo de transacción `"[idTx=<id>]"` y `"[<método>] "`; marcadores de método con
  `MessageFormat`; banners de `=` y `-`; progreso `[i/n]`; resumen por tipo y general;
  tiempos con `System.currentTimeMillis`; errores con `logger.error(msg, e)` y a veces
  `e.printStackTrace()`.
- Riesgos observados, no corregidos: se registran host/puerto/usuario (no contraseñas); log4j
  configurado tarde; fechas con zona por defecto.

## 8. Configuración externa y secretos (E-CONTEXT, E-PROPERTIES-CLASS)

- Un archivo `<Nombre>.properties` fuera del jar, indicado con `-Dproperties`.
- En la referencia existen dos archivos `.properties` de entorno en la raíz (hosts/credenciales cifradas):
  **no se leyeron ni se copian** (SH-D-004); en esta extracción no se abrieron.
- Credenciales: en la referencia se guardan cifradas y se descifran en ejecución con el
  servicio web SOAP corporativo de descifrado a través del proxy plantillado (§11); el valor
  jamás se incluye en el arquetipo.
- Persistencia: **no implementada** en la referencia (SH-Q-009).

## 9. Pruebas y calidad (E-TEST, E-POM)

- JUnit 4.12 + Mockito 2.23.4 (`MockitoJUnitRunner.Silent`, `@Mock`, `@Spy`,
  `@InjectMocks`, `doReturn`) + AssertJ 2.6.0 (uso totalmente cualificado).
- Una sola clase de prueba (el servicio) con escenarios por condición, nombrada
  `<método>_cuando<Condición>_debe<Resultado>` y Javadoc con *Escenario/Verificación*;
  `PropertiesExterno` real con campos asignados (no `@Mock`).
- JaCoCo 0.8.2 (`prepare-agent`, `report` en `prepare-package`; sin `check`/umbral).
- Sonar plugin 3.7.0.1746; exclusiones de cobertura/análisis por capa (SH-D-007).
- Checkstyle: **not-applicable / not-present-in-reference** (solo configuración IDE).
- Nada se ejecutó en esta extracción (Maven, pruebas, JaCoCo, Sonar: `not-run`).

## 10. Entrega

- Sin Dockerfile, Kubernetes ni Jenkinsfile; `.editorConfig` incluye una sección
  Jenkinsfile; esto no demuestra que exista un pipeline. Planificador
  desconocido, no se genera ninguno (SH-Q-012).
- Prerrequisitos externos: JDK 8, Maven 3.x, repositorio `Lib/` (cliente
  `eai:ebsConsultaClavesService-Client:1.0.0`), archivos de propiedades y log4j del entorno,
  endpoint/código de aplicación del servicio de descifrado, conectividad a los recursos remotos.

## 11. Proxy SOAP de descifrado de credenciales (SH-D-012/013/014, E-PROXY-*)

- Interfaz `EbsConsultaClavesWSService.desencriptar(String mensajeTransaccion,
  DesencriptarRequest request) throws WSException`; implementación `@Service` con
  `@Autowired PropertiesExterno prop` y `@Autowired EbsConsultaClavesPortType consultaClavesWS`
  (bean XML `ConsultaClavesWS`). Los tipos `Desencriptar*`/`EbsConsultaClavesPortType`
  (paquete `pe.com.claro.eai.ebs.operaciones.consultaclaves`) vienen del jar externo de `Lib/`.
- `applicationProxyWS.xml`: `util:map` con `com.sun.xml.ws.request.timeout` y
  `com.sun.xml.ws.connect.timeout` tomados de `ws.ebsConsultaClavesWS.max.request.timeout`/
  `max.connection.timeout`; `JaxWsPortProxyFactoryBean` con `wsdlDocumentUrl=${ws.ebsConsultaClavesWS.url}`,
  `lookupServiceOnStartup=false`. El endpoint nunca se fija en código ni en el template.
- Respuesta con `codigoResultado != "0"` → `WSException(codigo, mensaje)`. Errores de red:
  recorrido de la cadena de causas: `SocketTimeoutException` → idt1; `ConnectException`/
  `UnknownHostException`/`NoRouteToHostException` → idt2; otro → idt3, con `[RECURSO]`
  reemplazado por la URL y `[DETALLE]` por el mensaje de la excepción; el proxy registra con `logger.error`.
- Patrón de uso en el servicio (SH-D-014, `generation.servicePatterns`): construir
  `DesencriptarRequest` (idTransaccion, codigoAplicacion de propiedad, usuario/clave cifrados)
  y usar `getUsuarioAplicacion()`/`getClave()` para conectar. Los demás campos del request
  (`ipAplicacion`, `ipTransicion`, `usrAplicacion`, `idAplicacion`) no los fija la referencia.
- Riesgos observados (no corregidos): sin reintentos; la URL se registra; credenciales
  descifradas solo en variables locales (no registradas por la referencia).

## 12. Correo / notificación

La referencia no implementa envío de correo (solo un jar de cliente sin uso en `Lib/`).
Nada se plantilla ni se declara (SH-D-015).
