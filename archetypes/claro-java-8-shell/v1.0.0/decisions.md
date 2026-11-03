# Decisiones - claro-java-8-shell / 1.0.0 (version nueva)

Estado: **version nueva 1.0.0 creada por instruccion explicita del usuario (SH-D-018)**;
las versiones anteriores 1.0.0 y 1.1.0 de este arquetipo fueron eliminadas y esta las
reemplaza. SH-D-001..017 se conservan abajo como historico de las versiones eliminadas;
SH-D-018..021 prevalecen donde difieren (sin plantilla de configuracion, sin UtilSFTP /
BaseException / PropertiesException, sin exclusiones Sonar, modulo de descifrado solo si
se usa). `generationEnabled: true`, `frozen: false`, `readyToFreeze: false`.
Los textos historicos que dicen "version 1.1.0" o "v1.0.0 congelada" describen las versiones
eliminadas y no son un estado de esta version.

---

## Historico (versiones eliminadas)

Estado: **nueva versión 1.1.0 derivada de 1.0.0 (que permanece congelada e intacta);
aprobada por instrucción explícita del usuario (SH-D-011); NO congelada;
`generationEnabled: true` desde SH-D-017 (SH-D-016 queda superada solo en ese punto)**. Preserva SH-D-001…SH-D-010 y SH-Q-001…012 de 1.0.0
sin reabrirlas; SH-D-011…016 son nuevas de esta versión. Donde SH-D-004, SH-D-006 y
SH-D-009 de 1.0.0 excluían la integración de descifrado de credenciales, SH-D-011…013
reemplazan **únicamente esa exclusión**. SH-D-010 (congelación/habilitación) es propia de
1.0.0 y **no se hereda**: aquí el texto de SH-D-010 describe su alcance histórico. No
implica compilación, compatibilidad runtime ni autorización de generar un servicio.

Los identificadores SH-D-* (decisiones) y SH-Q-* (preguntas) son locales a esta versión;
no reutilizan D-001…D-014 (claro-spring-ms) ni J8-D-* (claro-spring-java-8), y esas
decisiones/tecnologías NO se aplican aquí.

Leyenda de estado: **aprobada** = respaldada por instrucción explícita del usuario;
**propuesta** = aplicada en esta extracción por regla del skill/AGENTS.md, pendiente de
revisión humana; **pendiente** = pregunta abierta, sin resolver (no se eligió en silencio).

Instrucción literal del usuario (evidencia H-EXT-2026-10-29): "Conserva las convenciones
tecnicas y excluye la logica de negocio y los secretos. Revisa detalladamente el proyecto,
porque en si los proyectos shell son como tipo batcheros, no tienen post o get, se prueban
a traves de un running. Analiza bien el proyecto para poder generar el arquetipo
correctamente."

## Decisiones aprobadas (instrucción del usuario)

### SH-D-001 — Extracción inicial y alcance

- Decisión: extraer estructura y convenciones técnicas de
  `input/reference/SH_ObtenerTrasladarArchivosMTC/` hacia el destino NUEVO
  `archetypes/claro-java-8-shell/v1.0.0/`, sin sobrescribir arquetipos existentes, sin
  modificar la referencia y sin analizar OpenAPI/Sparx.
- Estado: **aprobada** (instrucción explícita). Alcance: esta extracción y versión.
- Razón: disponer de un arquetipo independiente para proyectos shell/batch Java 8.
- Áreas: procedencia, inventario, documentación y plantillas.
- Evidencia: solicitud actual; AGENTS.md.
- Temporalidad: permanente para la procedencia; no implica aprobación del baseline ni
  habilita generación (`generationEnabled: false`, `frozen: false`).
- Revisión futura: aprobación humana explícita para congelar.

### SH-D-002 — Perfil batch/shell: sin HTTP, entrada = especificación funcional

- Decisión: el arquetipo describe un **batch ejecutable** (`main` + `java -jar`), no un
  servicio HTTP. No hay endpoints GET/POST; el servicio se prueba mediante una ejecución
  (running) del jar. Por tanto: el contrato **no es HTTP**; OpenAPI **no aplica**
  (apiContract/schemas/validación HTTP = not-applicable); el comportamiento funcional
  (flujo, archivos, integraciones, códigos) lo define Sparx. La forma técnica de la
  invocación (argumento 0 = `idTransaccion`, propiedad JVM `properties`) pertenece al
  arquetipo.
- Estado: **aprobada**; SH-Q-002 confirma la invocación observada sin OpenAPI.
- Razón: la referencia no contiene controladores, rutas ni DTOs HTTP (E-MAIN).
- Áreas: identity.profile, execution, generationOwnership, generation-rules.md.
- Evidencia: E-MAIN, E-README, E-CONTEXT.
- Temporalidad: permanente para este perfil.

### SH-D-003 — Baseline técnico fiel a la referencia (POM preservado)

- Decisión: conservar la tecnología y convenciones observadas: Java 1.8, jar (sin Spring
  Boot), Spring 3.1.0.RELEASE con contexto XML + component-scan, log4j 1.2, jsch,
  JUnit 4.12/Mockito 2.23.4/AssertJ 2.6.0, JaCoCo 0.8.2, Sonar 3.7.0.1746,
  jar+shade+dependency+resources plugins, repositorio local `Lib/`. El POM se preserva sin
  podar, modernizar ni corregir scopes; solo se parametriza identidad
  (groupId/artifactId/version), paquete/clase principal y nombre del archivo de
  propiedades. No se importa JPA, ActivityLogger, Logback, Spring Boot ni nada de otros
  arquetipos.
- Estado: **aprobada** ("Conserva las convenciones técnicas") + política de AGENTS.md.
- Razón: fidelidad a la referencia seleccionada.
- Áreas: archetype.yml (platform/build), pom.xml, conventions.md.
- Evidencia: E-POM.
- Temporalidad: baseline observado, no estándar corporativo universal. Compatibilidad
  runtime (Spring 3.1 + Java 8, SH-Q-010) sin verificar.

### SH-D-004 — Exclusión de negocio y secretos; configuración protegida

- Decisión: excluir lógica de negocio (flujo de archivos, rutas, tipos, ventana de
  medianoche, nombres) y secretos. Los archivos `sh.properties` y
  `ObtenerTrasladarArchivosMTC.properties` de la raíz de la referencia se tratan como
  configuración protegida por analogía con `application*.properties`: **no se copian ni se
  hashean**; solo se inspeccionaron los NOMBRES de clave (sin valores) para documentar el
  contrato de configuración externa (divulgado explícitamente). README: se elimina la IP de
  entorno. Los jars de `Lib/` y las clases compiladas/WSDL de la raíz no se copian.
- Estado: **aprobada** ("excluye la lógica de negocio y los secretos").
- Razón: AGENTS.md y la instrucción del usuario.
- Áreas: exclusions/referenceInventory, template/config/*.properties.j2, PropertiesExterno.
- Evidencia: E-PROPERTIES-CLASS; lista de claves (sin valores) en la sesión de extracción.
- Temporalidad: permanente.

## Aprobación de SH-D-005 a SH-D-009 (2026-10-29)

El usuario respondió "Aprobar decisiones" a la solicitud de continuar con este arquetipo y
pidió fijarse netamente en el proyecto de referencia. Por tanto SH-D-005…SH-D-009 pasan a
**aprobadas**; donde su texto indica "propuesta" se entiende aprobada en este alcance (la
versión sigue sin congelar y sin generación habilitada).

Resoluciones de preguntas (criterio del usuario: seguir la referencia):

- **SH-Q-001 — resuelta:** se mantiene lo observado; sin `System.exit`, los códigos
  idf0/idf1 solo se registran en log. La discrepancia con el README queda documentada.
- **SH-Q-007 — resuelta:** `hardcodedLiterals: allowed` (estilo mixto de la referencia).
- **SH-Q-005, SH-Q-006, SH-Q-008 — resueltas y confirmadas por el criterio del usuario:
  se conserva lo observado** (SFTP sin endurecer, `UtilSFTP`
  en el template, exclusiones por capa de SH-D-007).
- La instrucción posterior "Guiate enteramente del proyecto de referencia." confirma
  este criterio para todas las preguntas; las resoluciones se registran abajo.

## Decisiones aprobadas por revisión (antes propuestas)

### SH-D-005 — Herramientas de calidad solo si la referencia las usa

- Decisión: Checkstyle = `not-present-in-reference`/`not-applicable` (solo existe una
  configuración IDE de IntelliJ CheckStyle-IDEA con reglas Sun/Google empaquetadas: no es
  un gate de build ni hay `checkstyle.xml`/plugin Maven). JaCoCo 0.8.2 (sin umbral ni
  `check`) y Sonar 3.7.0.1746 se conservan como en la referencia.
- Estado: **aprobada** por revisión humana y criterio de fidelidad a la referencia.
- Evidencia: E-POM, E-CHECKSTYLE-IDE.

### SH-D-006 — Inventario y partición de utilitarios (skill 4.2)

- Decisión: inventariar todas las clases de `util/` y `exception/`. Técnico → template:
  `SFTPConnectionManager` (sin el overload de negocio con ventana pre-medianoche),
  `UtilSFTP`, `Constantes` (sin constantes de negocio ni campos de la integración
  concreta), `PropertiesExterno` (solo claves técnicas log4j/idf/idt), y las cinco
  excepciones. Excluidos con motivo: ventana de medianoche de 5 min (negocio MTC),
  `MTC_`, `REPLACE_FECHA_*`, `ERROR_CONEXION_MTC`, `DESENCRIPTAR`, `ID_TRANSACCION`,
  `CODIGO_APLICACION`, `USUARIO`, claves ftp/ruta/ws concretas de PropertiesExterno.
  `StrictHostKeyChecking=no` y el timeout 60000 se conservan tal cual (SH-Q-005).
- Estado: **aprobada**. Evidencia: E-SFTP-MANAGER, E-SFTP-UTIL, E-CONSTANTS,
  E-PROPERTIES-CLASS, E-EXCEPTIONS.
- Revisión futura: SH-Q-004, SH-Q-006.

### SH-D-007 — Exclusiones Sonar/JaCoCo por capa, parametrizadas por paquete

- Decisión: la referencia excluye de cobertura y de análisis Sonar los paquetes
  `proxy`, `exception`, `util` y la clase principal. Se conservan como patrones
  `**/@@BASE_PACKAGE_PATH@@/{proxy,exception,util}/*.java` y la clase principal
  (parametrizados), eliminando los patrones de clase concreta redundantes. No se vacían
  (a diferencia de claro-spring-java-8) porque son por capa técnica, no de negocio.
- Estado: **aprobada** para esta versión. Resolución: SH-Q-008.
- Evidencia: E-POM (líneas 24-39).

### SH-D-008 — README parametrizado

- Decisión: incluir un `README.MD` esqueleto con las secciones observadas (descripción,
  pre-requisitos, configuración, construcción, ejecución, parámetros, códigos). La
  descripción funcional se deja para la especificación. El comando de ejecución incluye
  `-Dproperties=<ruta>` porque `applicationContext.xml` lo exige (`file:${properties}`),
  aunque el README de la referencia lo omite (SH-Q-002).
- Estado: **aprobada**. Evidencia: E-README, E-CONTEXT.

### SH-D-009 — Plantillas de configuración y puntos de extensión

- Decisión: `applicationContext.xml` se plantilla sin el `import` de
  `applicationProxyWS.xml` (integración concreta, la agrega el generador desde Sparx);
  se crea `config/@@PROPERTIES_FILE_BASENAME@@.properties.j2` con las claves genéricas
  (log4j.file.dir, idf0/idf1, idt1/idt2/idt3) y patrones de claves específicas como
  comentarios, sin valores. No se crea `log4j.properties`, script `.sh`, Jenkinsfile ni
  `applicationProxyWS.xml`/`applicationDatasource.xml` porque no hay evidencia utilizable
  (ausentes o específicos/muertos).
- Estado: **aprobada**. Evidencia: E-CONTEXT, E-PROXY-XML, E-PROPERTIES-CLASS.
- Revisión: SH-Q-003, SH-Q-004, SH-Q-009.

## Resoluciones por fidelidad a la referencia

Instrucción humana: "Guiate enteramente del proyecto de referencia." Alcance: esta
versión y sus decisiones técnicas, sin congelación, habilitación de generación,
ejecución Maven ni construcción de backend implícitas. Las preguntas históricas se
conservan debajo como evidencia; ya no son decisiones pendientes.

| Pregunta | Resolución y evidencia | Limitación preservada |
|---|---|---|
| SH-Q-001 | Sin `System.exit`; mantener `main` observado (E-MAIN). | El log no garantiza un código de salida de error. |
| SH-Q-002 | `args[0]=idTransaccion`, sin validación adicional; `-Dproperties` exigido por XML (E-MAIN/E-CONTEXT). Sin OpenAPI. | El comando del README es derivado del código, no ejecución verificada. |
| SH-Q-003 | No inventar log4j, lanzador ni `templates/*` ausentes (E-POM/E-CONTEXT). | Archivo log4j requerido del entorno; contenido no conocido. |
| SH-Q-004 | Conservar dependencia y repositorio `Lib/` del POM; excluir proxy concreto como negocio/integración (E-POM/E-PROXY-IMPL). | Operador debe proveer artefactos; ubicación de distribución desconocida. No imponer descifrado a todo batch. |
| SH-Q-005 | Conservar SFTP/logging sin endurecimiento automático (E-SFTP-MANAGER). | Riesgos reportados no equivalen a seguridad validada. |
| SH-Q-006 | Mantener `UtilSFTP` inventariado (E-SFTP-UTIL). | Su inclusión no obliga a invocarlo sin necesidad funcional. |
| SH-Q-007 | Estilo mixto, literales permitidos (E-CONSTANTS). | Configuración externa y secretos nunca se fijan en código. |
| SH-Q-008 | Mantener exclusiones por capa parametrizadas (E-POM). | No trasladarlas a otros arquetipos. |
| SH-Q-009 | Sin persistencia implementada; no añadir DAO ni tecnología ajena. | Si un servicio necesita BD, falta evidencia específica y soporte; detener esa parte. |
| SH-Q-010 | Conservar Spring 3.1.0 y Java 8 (E-POM), sin modernizar. | Compatibilidad runtime sin verificar; no ejecutar ni ajustar sin autorización. |
| SH-Q-011 | Mantener nomenclatura observada mediante los parámetros ya declarados. | No inferir un estándar corporativo a partir de una referencia. |
| SH-Q-012 | Ejecución manual `java -jar`, sin scheduler inventado (E-README/E-MAIN). | Cron/Control-M/Jenkins desconocidos y fuera del baseline. |

Futuras revisiones requieren evidencia nueva o instrucción explícita. El baseline
queda aprobado; las verificaciones runtime/dependencias siguen pendientes.

### Implementación posterior del backend (2026-10-29)

Por instrucción explícita del usuario «Pues implementalos.» se implementaron
planificador y materializador independientes para el perfil batch. El soporte se limita
al IR SFTP documentado en `.opencode/skills/materialize-full-service/docs/batch-shell-contract.md`.
Conserva templates, utilitarios, configuración, POM y estilo aprobados; no introduce
HTTP, Boot, JPA, ActivityLogger, Checkstyle, scheduler ni `System.exit`. SOAP/descifrado,
persistencia y pasos desconocidos detienen la generación. No implica habilitar
`generationEnabled`, congelar, autorizar un servicio real ni ejecutar Maven/redes.

### SH-D-010 — Cierre, congelación y habilitación del perfil soportado

- Decisión: finalizar y congelar `claro-java-8-shell/1.0.0`, habilitando
  `generationEnabled` para el backend `batch-shell-jar-spring-xml-log4j-sftp-junit4`.
- Estado: **aprobada**, 2026-10-29. Evidencia humana: «Porque?, termina el arquetipo.»,
  tras informar que el backend estaba implementado pero la versión seguía deshabilitada.
- Alcance: esta versión y su IR SFTP cerrado. No habilita SOAP/descifrado, persistencia
  ni pasos desconocidos; estos siguen bloqueando. No importa tecnologías ajenas.
- Razón: las decisiones de baseline están aprobadas, las preguntas resueltas y el
  backend implementado y probado estáticamente. La falta de autorización de cierre
  se resuelve con la instrucción actual, no con una aprobación inferida de las pruebas.
- Áreas: identity/readiness de `archetype.yml`, documentación y validador de extracción.
- Verificación: suite materializador 258 pruebas, OK con 1 omitida; parseo Java 8
  satisfactorio. Maven, compilación del proyecto, JUnit generado y runtime sin verificar.
- Prerrequisitos preservados: configuración externa/log4j, artefactos `Lib/`, datos
  de entorno y especificación funcional de cada destino. No se inventan ni proveen.
- Seguridad: conserva los riesgos SFTP de la referencia aprobados previamente;
  congelar no certifica seguridad ni compatibilidad.
- Autorización separada: no se ha elegido un servicio real. Cada destino necesita
  evidencias, revisión y gate liberado; no autoriza Maven, red, ejecución ni despliegue.
- Revisión futura: modificación explícitamente autorizada o nueva versión cuando
  cambie el baseline; conservar decisiones y trazabilidad de esta versión congelada.

## Decisiones de la versión 1.1.0 (instrucción del usuario, 2026-10-30)

Instrucción literal del usuario (evidencia H-EXT-2026-10-30, precedencia máxima): «la
version v1.0.0 excluyo cosas que el servicio generado necesita (cliente SOAP/proxy de
descifrado de credenciales, y todo lo reutilizable tecnico que quedo fuera). Hay que crear
un NUEVO arquetipo con el mismo nombre claro-java-8-shell, version 1.1.0, que tenga en
cuenta todo lo reutilizable del proyecto de referencia», separando método a método lo
técnico de la regla de negocio (lógica MTC, nombres de archivos de negocio y ventana de
medianoche NO van al arquetipo).

### SH-D-011 — Nueva versión 1.1.0 que recupera infraestructura técnica reutilizable

- Decisión: crear `claro-java-8-shell/1.1.0` partiendo de 1.0.0 (archetype.yml,
  conventions, generation-rules, decisions, template, validador), sin tocar 1.0.0.
  Se reincorpora lo técnico reutilizable que 1.0.0 dejó fuera por considerarlo negocio:
  proxy SOAP de descifrado, su wiring XML, constantes y propiedades asociadas.
- Estado: **aprobada** (instrucción explícita); `approved: true`, `frozen: false`,
  `generationEnabled: false`, `readyToFreeze: false`.
- Alcance: solo esta versión. No reabre SH-D-001…010 ni SH-Q-001…012.
- Razón: el servicio generado necesita lo excluido; un cambio de baseline requiere
  versión nueva (AGENTS.md, Version Safety).
- Áreas: identity, provenance, template, referenceInventory, generation, readiness.
- Evidencia: instrucción del usuario; E-PROXY-IMPL, E-PROXY-IFACE, E-PROXY-XML.
- Temporalidad: vigente hasta congelar o sustituir esta versión.

### SH-D-012 — Proxy SOAP de descifrado de credenciales incluido en el template

- Decisión: incluir en `template/`: `proxy/EbsConsultaClavesWSService.java` y
  `proxy/EbsConsultaClavesWSServiceImpl.java` (solo cambia el paquete; cuerpo, clasificación
  de excepciones de red SocketTimeout→idt1, Connect/UnknownHost/NoRouteToHost→idt2,
  otras→idt3, reemplazo de `[RECURSO]`/`[DETALLE]` y textos de log idénticos a la
  referencia), `src/main/resources/applicationProxyWS.xml` verbatim,
  `applicationContext.xml` con el `import` restaurado, y en `Constantes` las constantes
  `DESENCRIPTAR`, `ID_TRANSACCION`, `CODIGO_APLICACION`, `USUARIO`; en `PropertiesExterno` las
  cuatro propiedades `ws.ebsConsultaClavesWS.{url,max.request.timeout,max.connection.timeout,codigo.aplicacion}`.
  Módulo declarado como `credential-decrypt-soap`, `defaultEnabled: true`
  (incondicional, como en la referencia). Cuáles credenciales se descifran y en qué orden
  sigue siendo de Sparx.
- Estado: **aprobada** (instrucción explícita). Alcance: 1.1.0.
- Razón: son clases/configuración técnicas (cliente SOAP, timeouts, clasificación de
  errores), no regla de negocio MTC. El nombre del servicio corporativo
  (`EbsConsultaClaves…`, namespace, servicio y puerto) es la identidad técnica de un
  servicio corporativo compartido, no del dominio MTC; se conserva literal, igual que
  `Constantes`/`PropertiesExterno` conservan nombres observados.
- Áreas: template, archetype.yml (templateInventory, parameters.affectedFiles,
  generation.utilities/featureModules/configuration), generation-rules.md,
  conventions.md, validate-extraction.py (la regla de fuga de integración se invierte).
- Evidencia: E-PROXY-IMPL (1-107), E-PROXY-IFACE, E-PROXY-XML (1-53), E-CONSTANTS,
  E-PROPERTIES-CLASS (109-120), E-CONTEXT.
- Riesgos conservados (no corregidos): sin reintentos; se registra la URL del servicio;
  la dependencia de compilación proviene de `Lib/` (SH-D-013); los comentarios Javadoc de la
  referencia tienen codificación doble y se conservan byte a byte.
- Revisión futura: hacerlo opcional por servicio requiere flag de materializador y
  plantillas condicionales (no implementado).

### SH-D-013 — Endpoint como propiedad externa; Lib/ prerrequisito; WSDL y jars excluidos

- Decisión: (a) el endpoint, timeouts y código de aplicación del descifrador son
  **propiedades externas** (`ws.ebsConsultaClavesWS.*`) con variables jinja2
  `ws_ebsconsultaclavesws_*` en `config/@@PROPERTIES_FILE_BASENAME@@.properties.j2`, sin
  valores; (b) la dependencia `eai:ebsConsultaClavesService-Client:1.0.0` (ya declarada
  en el POM, preservado) y el repositorio `file://${project.basedir}/Lib` se documentan como
  **prerrequisito externo** (README, externalPrerequisites, readiness); (c) NO se copian
  jars ni clases `pe/**`; (d) el WSDL se evaluó y **se excluye**: el contrato técnico
  (operación `desencriptar`, campos de request/response, namespace, servicio, puerto) se
  documenta en `generation.servicePatterns.credentialDecryptContract`, pero el archivo
  contiene elementos `soap:address` con una IP privada y puerto de entorno; el cliente real
  ya viene en el jar de `Lib/`; (e) el jar de correo y `ojdbc6` no se declaran como
  prerrequisitos (SH-D-015, SH-Q-009).
- Estado: **aprobada** (instrucción: parametrizar el endpoint, declarar y documentar la
  dependencia de `Lib/`, no copiar jars ni WSDL con datos de entorno, decidir con motivo).
- Alcance: 1.1.0.
- Razón: evitar datos de entorno y binarios propietarios con procedencia no verificada,
  manteniendo reproducible el contrato técnico.
- Áreas: template/config, README, referenceInventory, externalPrerequisites.
- Evidencia: E-WSDL, E-LIB-DECRYPT (solo listado de entradas del jar, sin extraer), E-PROXY-XML.
- Revisión futura: si se aprueba publicar el WSDL sin direcciones, podría añadirse como recurso.

### SH-D-014 — Partición técnico/negocio método a método del servicio de la referencia

- Decisión: `ObtenerTrasladarArchivosServiceImpl` sigue excluido como archivo (es de
  Sparx), pero sus partes técnicas se registran en `generation.servicePatterns`:
  `desencriptarCredenciales`, llamada de descifrado previa a conectar, `crearConexionSFTP`
  (fábrica protegida con envoltura `SFTPException`), manejo de errores por tipo con cierre
  en `finally`, delegaciones de prueba hacia `UtilSFTP`, `obtenerFechaProcesoFormato` y el
  marco de log (banners, marcadores, tiempo). Se excluyen como negocio: mapa de tipos
  SUSPENSION/NOTIFICACION/IDENTIFICACION/REPORTE y sus rutas, filtro por nombre o fecha de
  modificación, margen de medianoche, de-duplicación Reporte/Identificación, contadores
  por tipo, regla idf0/idf1 y textos MTC (`MTC_`, `REPLACE_FECHA_*`, `ERROR_CONEXION_MTC`,
  claves `ftp.*`, `sftp.mtc.*`, `ruta.temp.trasladar.mtc`).
- Estado: **aprobada** (instrucción explícita de separar método a método).
- Alcance: 1.1.0. Los patrones son un contrato para el generador/materializador; no son
  archivos del template.
- Áreas: archetype.yml (generation.servicePatterns, excludedBusinessMethods),
  generation-rules.md.
- Evidencia: E-SERVICE-IMPL con rangos de líneas por patrón.
- Revisión futura: promover alguno a clase de `util` solo con decisión explícita.

### SH-D-015 — Correo/notificación: sin implementación en la referencia; no se inventa

- Decisión: la referencia no contiene código, XML, constantes, propiedades ni entrada de
  POM de envío de correo o notificación; solo el binario
  `Lib/pe/com/claro/eai/EnvioCorreoSB-Client/1.0.0/…jar` (cliente SOAP; clases
  `EnvioCorreoSBPortType`, `EnviarCorreoRequest/Response`, `ArchivoAdjunto`, …) que ninguna
  fuente usa y que el POM no declara. No se crea plantilla, propiedad ni dependencia; no se
  copia el jar; el módulo `mail-notification` queda registrado como
  `not-present-in-reference-source`. Los textos "Notificación" de la referencia son un
  tipo de archivo de negocio (excluido), no un envío de correo.
- Estado: **aprobada** (instrucción: incluir lo que la referencia tenga; no inventar).
- Alcance: 1.1.0. Un envío de correo futuro sería propiedad de Sparx y requiere una
  decisión nueva con evidencia (dependencia, coordenadas Maven y contrato).
- Áreas: archetype.yml (featureModules, referenceInventory, externalPrerequisites).
- Evidencia: E-LIB-MAIL (listado de entradas del jar); ausencia verificada por búsqueda
  de referencias en `src/` y POM.
- Revisión futura: decidir si el jar debe declararse en el POM.

### SH-D-016 — Estado de la versión: no congelada, sin generación; backend sin soporte

- Decisión: 1.1.0 queda `approved: true`, `frozen: false`, `generationEnabled: false`,
  `readyToFreeze: false`. El backend batch actual (IR v1: connect, disconnect, list,
  for-each, download, upload) **no soporta** el descifrado SOAP ni correo, ni conoce los
  archivos nuevos del template; debe extenderse (nuevos pasos IR, inventario de plantillas,
  pruebas, gate de consistencia) antes de habilitar esta versión. Los planificadores deben
  detenerse con esta versión; no se rebajan a 1.0.0 en silencio.
- Estado: **aprobada** (instrucción explícita).
- Alcance: 1.1.0. SH-D-010 no se hereda.
- Áreas: identity, readiness.generatorBackend*, limitations.
- Evidencia: instrucción del usuario; contrato del backend
  `batch-shell-contract.md` (solo referencia, no modificado).
- Revisión futura: freeze tras validar, revisar SH-D-011…015 y extender el backend.

## Preguntas originales (histórico, resueltas arriba)

El arquetipo conserva lo observado; las interrogantes siguientes no reabren las resoluciones.

- **SH-Q-001 — Código de salida.** El README documenta 0 (éxito) y 1 (error), pero el
  código nunca llama `System.exit`; idf0/idf1 solo se registran en log y el proceso termina
  con estado 0 salvo falta de `args[0]` (excepción no capturada). ¿Los batch generados
  deben fijar el código de salida (`System.exit`) o mantener lo observado?
- **SH-Q-002 — Rol de OpenAPI y contrato de invocación.** ¿Se descarta OpenAPI para este
  perfil o se acepta un contrato opcional solo para parámetros de entrada? ¿Cómo se
  especifican en Sparx los argumentos (hoy solo `idTransaccion` sin validar)? ¿Se
  corrige/documenta `-Dproperties` en el README?
- **SH-Q-003 — log4j.properties y lanzador.** `log4j.file.dir` apunta a un archivo log4j
  que no existe en la referencia (ni `templates/*`, que el resources plugin copia); log4j
  se configura después de crear el contexto Spring. No hay script `.sh` de arranque ni
  Jenkinsfile (aunque `.editorConfig` tiene sección Jenkinsfile). ¿Se debe crear una
  plantilla log4j y/o un script lanzador (no hay evidencia de su contenido)?
- **SH-Q-004 — Servicio de descifrado de credenciales y jars de Lib/.** El batch obtiene
  credenciales cifradas y las descifra con un WS corporativo (cliente
  `eai:ebsConsultaClavesService-Client` desde `Lib/`). La dependencia se preserva en el
  POM por política, pero el jar no se copia y la integración se excluye. ¿Es parte del
  baseline de todos los batch o específica por servicio (Sparx)? ¿Dónde se aloja el
  repositorio `Lib/` para compilar? (hay además ojdbc6 y EnvioCorreoSB no declarados en el POM).
- **SH-Q-005 — Riesgos SFTP/logging.** `StrictHostKeyChecking=no`, timeout fijo 60000 ms,
  log de host/puerto/usuario, `SimpleDateFormat` con zona por defecto: se conservan; ¿se
  autoriza endurecerlos?
- **SH-Q-006 — UtilSFTP.** Solo lo invocan métodos delegadores protegidos que `run()` no
  usa (código muerto observado); ¿se mantiene en el template?
- **SH-Q-007 — Literales en duro.** Estilo observado mixto (constantes + literales
  inline). ¿Se exige a lo generado usar siempre `Constantes`/`PropertiesExterno`
  (`forbidden`) o se replica lo observado (`allowed`, valor actual)?
- **SH-Q-008 — Exclusiones Sonar por capa** (ver SH-D-007): confirmar o vaciar.
- **SH-Q-009 — Persistencia.** La referencia no implementa base de datos
  (`applicationDatasource.xml` no se importa; no hay DAO). Si Sparx exige BD, ¿qué
  mecanismo? No se importa ninguno de otros arquetipos.
- **SH-Q-010 — Compatibilidad Spring 3.1.0 + Java 8.** Posible incompatibilidad del
  escaneo de clases (ASM de Spring 3.1) con bytecode Java 8; sin verificar, no se ejecutó
  nada. ¿Se mantiene la versión o se autoriza una verificación/ajuste?
- **SH-Q-011 — Nomenclatura.** `pe.com.claro.shell` / `SH_<Nombre>` / `<Nombre>Main` /
  paquete en minúsculas provienen de una sola referencia; ¿son convención o solo valor
  configurable?
- **SH-Q-012 — Planificador/orquestación.** Cron/Control-M/Jenkins desconocidos;
  la ejecución real es manual con `java -jar`.

## Evidencia y trazabilidad

Todas las referencias E-* están en `archetype.yml` (`evidence.entries`) con ruta y líneas
dentro de `input/reference/SH_ObtenerTrasladarArchivosMTC/`.

### SH-D-017 - Habilitacion de generacion de la version 1.1.0 (backend extendido)

- Estado: aprobada por instruccion explicita del usuario; fecha 2026-10-30.
- Evidencia textual del usuario: "Generalo de todas formas" y "Si el arquetipo lo excluyo, seria mejor generar un nuevo arquetipo que tenga en consideracion todo eso. Osea un arquetipo con el mismo nombre claro-java-8-shell".
- Decision: `generationEnabled: true`; `frozen: false` y `readyToFreeze: false` (compilacion con `Lib/`, Spring 3.1/Java 8 y ejecucion sin verificar). Reemplaza solo el estado "sin generacion" de SH-D-016.
- Backend: el planificador/materializador batch soporta el modulo `credential-decrypt-soap` mediante `credentialMode: decrypted-soap` (usuario/clave cifrados desde propiedades externas secretas, descifrado con `EbsConsultaClavesWSService.desencriptar`, `WSException` registrada y mapeada al resultado de falla general). El correo sigue NO soportado (SH-D-015) y detiene la generacion.
- No se infiere autorizacion para Maven, red, ejecucion ni congelacion. v1.0.0 queda intacta.

## Decisiones de la version 1.0.0 nueva (instruccion del usuario, 2026-10-31)

Evidencia textual del usuario (H-NEW-2026-10-31): "Elimina las versiones de arquetipos que tenemos y genera una nueva. Quitar la config del arquetipo. En el caso de UtilSFTP, lo que se requiere es validar codigo no utilizado. Es decir, no deberia tener clases o utilidades que al final no se usan en el servicio. Ya que eso afecta a SonarQube."
Observaciones de revision del documento "REVISION CODIGO GENERADO MTC.docx": (1) quitar config `.properties.j2` (no pasa por integracion continua); (2) evitar exclusiones para inflar la cobertura; (3) README y comentarios describen la plantilla, no una implementacion; (4) UtilSFTP y PropertiesException sin referencias.

### SH-D-018 - Version nueva y retiro de las versiones anteriores

- Estado: aprobada por instruccion explicita del usuario.
- Decision: se eliminan las versiones 1.0.0 y 1.1.0 de `claro-java-8-shell` y se crea una version `1.0.0` nueva. No se tocan `claro-spring-ms` ni `claro-spring-java-8`. El arquetipo ya no incluye la plantilla de configuracion `config/*.properties.j2`; las claves externas requeridas se listan en el README generado y en el registro `required-properties.yml` del workspace.
- Alcance: solo este arquetipo. Reemplaza lo dicho sobre la plantilla `.j2` en SH-D-004, SH-D-009 y SH-D-013.

### SH-D-019 - Sin codigo no utilizado

- Estado: aprobada por instruccion explicita del usuario.
- Decision: el proyecto generado no contiene clases, utilidades ni campos de configuracion que el servicio no use (afecta a SonarQube). `UtilSFTP`, `BaseException` y `PropertiesException` no se incluyen en la plantilla (en la referencia solo `UtilSFTP` tiene llamadores, a traves de metodos delegadores del servicio de negocio excluido; las otras dos no se referencian). El planificador poda los modulos de plantilla no usados y el materializador falla si una clase principal queda sin referencias.
- Limite: la poda es a nivel de clase, recurso y campo del modulo de descifrado; no elimina metodos sin uso dentro de clases conservadas ni dependencias del POM base.
- Reemplaza SH-Q-006 (mantener UtilSFTP) y el patron de servicio `SP-TESTABILITY-DELEGATIONS`.

### SH-D-020 - Sin exclusiones de cobertura ni de analisis

- Estado: aprobada por instruccion explicita del usuario (prevalece sobre la evidencia de la referencia, cuyo POM declara `sonar.coverage.exclusions` y `sonar.exclusions`).
- Decision: el POM de plantilla y el proyecto generado no declaran `sonar.coverage.exclusions` ni `sonar.exclusions`. El materializador falla si aparecen. Reemplaza SH-D-007 y SH-Q-008.
- Consecuencia: SonarQube medira todas las clases; sin pruebas adicionales la cobertura sera baja en `util`, `proxy`, `exception` y la clase principal. No se generan pruebas extra salvo peticion.

### SH-D-021 - Modulo de descifrado condicional y README de implementacion

- Estado: aprobada por instruccion explicita del usuario (observaciones 3 y 4 del documento de revision).
- Decision: el modulo `credential-decrypt-soap` (proxy, `WSException`, `applicationProxyWS.xml`, import del contexto y las cuatro propiedades `ws.ebsConsultaClavesWS.*`) solo se incluye cuando la especificacion usa `credentialMode: decrypted-soap`; si no, se poda. El README de plantilla usa marcadores que el materializador rellena (descripcion desde la IR, prerrequisitos y propiedades requeridas); el proyecto generado no describe una plantilla ni el arquetipo.
- Estado de la version: `generationEnabled: true`, `frozen: false`, `readyToFreeze: false`; no se infiere autorizacion para Maven, red, ejecucion ni congelacion.

### SH-D-022 - Alcance solo estructura y modulo SFTP condicional

- Estado: aprobada por instruccion explicita del usuario. Contexto: el servicio `sh_batch_invoiceUpdateError` requiere persistencia en BD, clientes REST, correo y programacion, que este arquetipo no soporta (ninguno existe en su referencia). El usuario eligio generar solo lo posible: "La opcion 3, por el momento no tengo otro proyecto de referencia."
- Decision: la IR admite `scope: structure-only` con `omittedBehavior` explicito (id, descripcion, evidencia Sparx literal), sin propiedades, conexiones ni pasos, y un unico resultado `generalFailure` (grupo idt1/idt2/idt3). El servicio generado no simula exito: registra el resultado de fallo e identifica el comportamiento omitido. La disponibilidad del modulo `sftp-transfer` (`SFTPConnectionManager`, `SFTPException`, `BaseExceptionSFTP`) depende de que existan conexiones SFTP; en estructura se poda (SH-D-019). No se inventa estilo de BD, REST ni correo.
- Estado de la version: sin cambios (`generationEnabled: true`, `frozen: false`); no se autoriza Maven, red ni ejecucion.

### SH-D-023 - Ambito ports-flow: flujo Sparx orquestado contra puertos

- Estado: aprobada por instruccion explicita del usuario: "Genera el servicio tomando de base el arquetipo, y lo demas queda a tu criterio." (servicio sh_batch_invoiceUpdateError).
- Decision: la IR admite `scope: ports-flow` ademas de `structure-only`. Declara `dtos` (campos String/Integer/Long/Boolean con evidencia Sparx literal), `ports` (kind db/rest/mail; metodos con parametros y retorno), `flow` (pasos `call` con politica de fallo abort/skip-item/log, `for-each` sin anidar e `if` con `<` sobre Integer o `present`) y `omittedBehavior` obligatorio. El materializador genera DTO POJO, interfaz y adaptador por puerto (el adaptador lanza `OperacionNoImplementadaException`; nunca simula una integracion), el servicio con el flujo y pruebas JUnit4/Mockito derivadas de cada ruta del flujo y de cada politica de fallo. Paquetes generados: `dto`, `port`, `exception`.
- Limite: no implementa SQL, clientes HTTP, correo, URLs, propiedades de conexion ni programacion periodica; esos elementos permanecen en `omittedBehavior` y la readiness funcional/estricta sigue en false. No traslada JDBC, Spring Boot ni logging de otros arquetipos.
- Estado de la version: sin cambios (`generationEnabled: true`, `frozen: false`); no se autoriza Maven, red ni ejecucion.

### SH-D-024 - Adaptadores concretos por supuestos (JDBC, REST, correo) en ports-flow

- Estado: aprobada por instruccion explicita del usuario: "Implementar con supuestos", "Si, solo para este caso de shell.", "Continua con todo lo que falta, hasta terminar el servicio." y "Generalo completamente. Librerias externas y maven obvialo por ahora, ya que no tengo VPN, continua hasta terminar de geenrar el proyecto por completo."
- Decision: la IR ports-flow admite dapters opcionales por puerto. Cada metodo declara explicitamente (y siempre ssumed: true con evidencia Sparx literal) el SQL con sus binds y mapeo de columnas (db), el verbo, ruta, query y cuerpo (rest) o los placeholders (mail). El materializador genera util/ConexionBd (JDBC plano, driver externo), util/RestClienteHttp (Apache HttpClient + Jackson) y adaptadores <Port>Impl con pruebas JUnit4/Mockito para db y rest. Las propiedades de entorno (d.*, est.<puerto>.url, est.timeout.ms, mail.*) son campos @Value de PropertiesExterno, sin valores ni secretos, listadas en equired-properties.yml. Dependencias adicionales (jackson-databind, httpclient, javax.mail) se anaden al POM como adicion justificada sin podar el baseline. Un puerto sin adaptador sigue lanzando OperacionNoImplementadaException.
- Limite: SQL, columnas, payloads, URLs, autenticacion, SMTP y tipo de base de datos son supuestos a validar contra los sistemas reales (registrados en ssumptions-register.yml); la programacion periodica es externa. La readiness funcional/estricta no se mejora. No traslada JDBC/Spring Boot de otros arquetipos ni se aplica a otros perfiles.
- Estado de la version: sin cambios (generationEnabled: true, rozen: false); no se autoriza Maven, red ni ejecucion.

### SH-D-025 - Configuracion generada en /config y nombre con underscores

- Estado: aprobada por instruccion explicita del usuario: "Generar properties", "Va en /config. underscores solo en artifactId, jar y archivo de properties. Solo a este arquetipo shell y a este servicio. Continua."
- Decision: el materializador genera config/<PROPERTIES_FILE_BASENAME>.properties con todas las claves requeridas y valores vacios (las secretas marcadas con comentario); no es plantilla del arquetipo. Reemplaza lo dicho en SH-D-018 sobre no incluir configuracion. ARTIFACT_ID y PROPERTIES_FILE_BASENAME admiten underscores (patrones ya vigentes).
- Limite: sin valores reales ni secretos; solo perfil shell.
- Estado de la version: sin cambios (generationEnabled: true, frozen: false); no se autoriza Maven, red ni ejecucion.

### SH-D-026 - Carpeta del proyecto con el nombre de Sparx
- Estado: aprobada por instruccion explicita del usuario: "El nombre del proyecto y el jar debe estar con guiones, igual como aparece en sparx." y "Asi como esta en sparx".
- Decision: para este perfil shell la carpeta de salida puede ser output/<ARTIFACT_ID> (p. ej. output/sh_batch_invoiceUpdateError); el workspace sigue en kebab-case.
- Estado de la version: sin cambios (generationEnabled: true, frozen: false); no se autoriza Maven, red ni ejecucion.

### SH-D-027 - Flujos con bucles anidados, guardas y condiciones compuestas (ports-flow)
- Estado: aprobada por instruccion explicita del usuario: "Genera todo el servicio completo hasta donde se pueda."; antecedentes: "Implementar con supuestos" y "Si, solo para este caso de shell.".
- Decision: el modo ports-flow admite bucles for-each anidados (profundidad 2), pasos guard, condiciones simples o compuestas (all/any con <, present, nonempty, equals, true) y metodos REST con retorno Boolean (okStatus). Todo adaptador sigue marcado assumed y el comportamiento no definido en Sparx permanece en omittedBehavior.
- Limite: solo perfil shell; sin Maven, red ni ejecucion.
- Estado de la version: sin cambios (generationEnabled: true, frozen: false).
