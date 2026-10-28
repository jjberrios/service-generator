# Decisiones — claro-spring-java-8 / 1.0.0

Estado: **extracción completa; baseline basado en referencia aprobado por las
decisiones actuales, no congelado**. No implica compilación, compatibilidad runtime,
soporte del backend generador ni autorización de generar un servicio.
Ninguna observación por sí sola constituye aprobación o estándar corporativo.
Los identificadores J8-D-* son locales a esta versión; no reutilizan D-001…D-014
de otro arquetipo.

## J8-D-001 — Extracción inicial y alcance

- Decisión: extraer estructura y convenciones técnicas de
  `input/reference/rest-sb-claro-post-atencion/` hacia el destino NUEVO
  `archetypes/claro-spring-java-8/v1.0.0/`, sin sobrescribir versiones existentes,
  copiar negocio, modificar la referencia ni analizar OpenAPI/Sparx.
- Estado: **instrucción explícita del usuario**, aprobada únicamente en ese alcance.
- Alcance: esta extracción inicial y esta versión; no autoriza generación de servicios.
- Razón: disponer de un arquetipo independiente para la referencia solicitada.
- Áreas afectadas: procedencia, inventario, documentación y todas las plantillas.
- Evidencia: solicitud actual; AGENTS.md, seguridad y gobernanza.
- Temporalidad: permanente para la procedencia; no implica aprobación del baseline.
- Revisión futura: cualquier cambio del baseline necesita aprobación explícita.

## Autorización de revisión actual — 2026-10-20

Evidencia humana H-REV-2026-10-20: instrucción explícita actual de revisar
exclusivamente esta versión y basar íntegramente cada arquetipo en SU referencia;
preservar POM, persistencia, logging, herramientas de calidad, runtime y entrega
observados, sin extrapolar decisiones de otras versiones. Autoriza resolver
J8-Q-001…005 en esos alcances y distinguir extracción aprobada de ejecución no
verificada. No autoriza congelación, Maven, DB, despliegue, cambios en otros
arquetipos o acceso al contenido de `application*.properties`.

Todas las decisiones siguientes son **baseline aprobado de esta versión**, no
estándar corporativo ni baseline temporal. Se espera preservarlas; cambios de stack
o modernización requieren nueva instrucción/versionado. No se supersede J8-D-001:
su alcance histórico de extracción inicial se amplía solo mediante esta revisión.

## J8-D-002 — Referencia propia, plataforma y persistencia

- Decisión: mantener Java 8/Boot 2.0.5.RELEASE/WAR y persistencia JDBC/JNDI/Oracle
  mediante DAO, CallableStatement/ResultSet y helper de cursor observado. No imponer
  Spring Data, entidades JPA, HikariCP ni POM de otro arquetipo. Las APIs JPA e
  Hibernate declaradas se conservan, pero no prueban implementación JPA.
- Estado: aprobado; resuelve J8-Q-001. Alcance: `claro-spring-java-8/1.0.0`.
- Razón: fidelidad a la implementación, no adecuación a un generador distinto.
- Áreas: platform/build/structure, bootstrap, inventario POM y reglas de persistencia.
- Evidencia: H-REV-2026-10-20; E-POM:6–31, E-JDBC:3–23,
  E-REPOSITORY:25–110. D-011/D-012 ajenos no se heredan.
- Revisión futura: baseline esperado estable; backend/runtime necesitan comprobación
  separada, no aprobación de migración. SQL, JNDI concreto y mappings siguen excluidos.

## J8-D-003 — Logging real SLF4J/Logback Java 8

- Decisión: extraer el patrón SLF4J/LoggerFactory por clase, Logback externo,
  inicio/fin de método/actividad, prefijo local de transacción, JSON Jackson y
  tiempos observados; no importar ActivityLogger/ConstanApi/RequestHeaders record.
  La utilidad original mezcla validaciones y traducciones de negocio: NO copiarla
  ni inventar una clase adaptadora. El patrón reusable queda documentado y en
  metadatos; Logback técnico es la plantilla. No copiar actividades concretas.
- Estado: aprobado; resuelve J8-Q-002 en el alcance técnico, sin aprobar seguridad
  de payloads. Alcance: esta versión.
- Razón: conservar logging real sin convertir negocio en infraestructura.
- Áreas: runtime.logging, Logback, conventions y generation-rules.
- Evidencia: H-REV-2026-10-20; E-CONTROLLER:35,53–90;
  E-SERVICE:51,61–85,159–163,423–433; E-UTIL-LOGGING:55–85;
  E-LOG-CONSTANTS y E-LOGBACK. D-013 ajena no aplica.
- Revisión futura: riesgo abierto de cuerpos/headers/parámetros sin masking;
  también fechas con zona local y literal Z. No añadir masking, corregir formatos,
  introducir fallback de transacción ni alterar respuestas silenciosamente.

## J8-D-004 — Checkstyle ausente: no aplicable

- Decisión: no incluir Checkstyle, plugin, ruleset ni gate main/test porque no
  están en la referencia. Estados: `not-present-in-reference` / `not-applicable`,
  nunca `passed` ni gate obligatorio `unverified`. Mantener JaCoCo/Sonar observados.
- Estado: aprobado; resuelve J8-Q-003. Alcance: esta versión.
- Razón: no extrapolar D-014 ni inventar tooling.
- Áreas: quality/validation, POM y validador; documentos de estado.
- Evidencia: H-REV-2026-10-20; E-POM:177–248 e inventario de archivos permitido.
- Revisión futura: no temporal; añadir herramienta necesita decisión explícita.
  JaCoCo/Sonar/tests no ejecutados no se declaran aprobados por esta decisión.

## J8-D-005 — POM completo, versiones/scopes y exclusiones de dominio

- Decisión: conservar parent, las 24 dependencias activas directas, propiedades,
  cuatro plugins, ejecuciones, scopes/optional y repositorios del POM de SU
  referencia; no podar, modernizar ni forzar uso. Separar inventario declarado de
  evidencia de uso Java; sin atribuir una transitive a una declaración directa
  mediante suposición. Versiones heredadas/effective-pom permanecen no resueltas.
  Solo parametrizar identidad/entorno, omitir comentario de driver alternativo y
  vaciar las dos exclusiones Sonar concretas de dominio, sin exclusiones nuevas.
- Estado: aprobado; resuelve J8-Q-004. Alcance: esta versión.
- Razón: conservar baseline íntegro sin copiar negocio ni corregir scopes legados.
- Áreas: build/dependencyUsage, template/pom.xml, reglas y validación comparativa.
- Evidencia: H-REV-2026-10-20; E-POM:18–175,177–248; E-JAVA-USAGE,
  E-TESTS, E-REPOSITORY y E-HELP:5–13.
- Revisión futura: no temporal. Bibliotecas solo declaradas no obligan a generar
  SOAP/JPA/Gson/PowerMock. HELP cita Boot 3.2.1-SNAPSHOT pero el POM declara 2.0.5:
  prevalece el POM para el baseline, sin inventar aprobación de migración.
  Propiedades Gson/Hibernate no prueban pins efectivos; scopes de tests en compile
  se conservan. Disponibilidad/compatibilidad y seguridad no verificadas.

## J8-D-006 — Runtime, repositorio y entrega de referencia

- Decisión: mantener WAR/descriptor WebLogic y carga externa servlet observados.
  Versiones no documentadas de servidor, Maven y distribución JDK quedan unknown,
  sin bloquear extracción ni requerir aprobar otro stack. URL de repositorio es
  parámetro HTTP/HTTPS sin host privado/credenciales; no forzar HTTPS distinto de
  la referencia. Autenticación externa, sin inventar settings.xml.
  Preservar evidencia/estructura de llamada Jenkins, no implementación de librería.
- Estado: aprobado; resuelve J8-Q-005 en baseline, no verifica runtime/entrega.
  Alcance: esta versión.
- Razón: no convertir prerequisitos de ejecución desconocidos en migraciones.
- Áreas: platform/deployment, repositorios, initializer, descriptors, parámetros,
  evidencia Jenkins y reglas de entrega.
- Evidencia: H-REV-2026-10-20; E-INITIALIZER:18–22, E-WEBLOGIC,
  E-POM:224–248 y E-CI:1–10.
- Tratamiento Jenkins: se conserva en archetype.yml el nombre observado de llamada
  y las ocho keys; se excluye template ejecutable. Toda implementación está en una
  biblioteca ausente y la llamada solicita publicación de configuración local.
  No se inventan stages ni un sustituto, no se copian valores de infraestructura
  ni se automatiza publicación del archivo protegido. Esta exclusión no es un
  bloqueo de extracción; CI real requiere biblioteca y política externa verificadas.
- Fidelidad: se revierte la normalización previa con `new File(parent, child)` a
  concatenación original (propiedad raíz + subdirectorio + File.separator + nombre).
  La raíz requiere separador final en el entorno; no se corrige comportamiento.
- Revisión futura: baseline no temporal; comprobar runtime/backend/entorno por
  separado y solicitar autorización de ejecución solo cuando corresponda.

## Cierre trazable de las cinco preguntas

| Pregunta histórica | Resolución actual | Restricción real restante |
|---|---|---|
| J8-Q-001 | J8-D-002 | Backend del generador no probado para este perfil |
| J8-Q-002 | J8-D-003 | Riesgo de exposición en logging, no aprobación de seguridad |
| J8-Q-003 | J8-D-004 | No aplicable; ausencia nunca equivale a pasó |
| J8-Q-004 | J8-D-005 | Resolución/compatibilidad del POM no ejecutadas; HELP discrepante |
| J8-Q-005 | J8-D-006 | Versiones unknown y prerequisitos de CI/entorno no verificados |

Las preguntas nacieron por extrapolar reglas de otra referencia y por incertidumbre
del POM/runtime. Su formulación anterior queda supersedida por H-REV-2026-10-20,
no por inferencia automática. No quedan contradicciones de decisión que requieran
consulta en esta revisión. Congelación no autorizada; ninguna compilación afirmada.


## J8-D-007 - Habilitacion de generacion (2026-10-22)

- Decision humana explicita del usuario ("Si, autorizo"): generationEnabled: true en rchetype.yml para generar el servicio claro-post-atencion con este arquetipo.
- Alcance: solo esta version; no la congela (rozen: false) ni afirma compilacion o soporte del backend del generador.
- Restriccion vigente: el planificador/materializador FULL actual esta construido para JPA/Hibernate/Oracle; si no soporta Java 8, WAR/WebLogic y JDBC CallableStatement debe detenerse como perfil no soportado.

## J8-D-008 - Constantes y properties externas en codigo generado (2026-10-22)

- Origen: observacion de revision del usuario y estilo observado en la referencia (input/reference/rest-sb-claro-post-atencion): ningun valor de entorno o de respuesta va en duro.
- Regla: los literales de codigo (textos de log, nombres de actividad, nombres de parametros/columnas, indices JDBC, rutas, tags) viven en common.property.Constantes; los valores dependientes de entorno u operacion (nombre JNDI, owner/paquete/nombre del procedimiento, timeouts de ejecucion, codigos y mensajes de respuesta) se leen de common.property.PropertiesExternos (campos @Value). El DataSource se llama dataSourceCRMLITE y se inyecta con @Qualifier.
- Los valores de las properties los define el operador; el generador nunca escribe application*.properties. Emite el registro required-properties.yml con claves y valores sugeridos tomados de OpenAPI/Sparx.
- El materializador falla si detecta literales de cadena fuera de Constantes/PropertiesExternos/JdbcConfig en el codigo principal. Aplica solo a esta version.

## J8-D-009 - Clases utilitarias y archivos de configuracion del arquetipo (2026-10-23)

- Origen: observacion de revision del usuario: el proyecto de referencia usa clases utilitarias (common.util.ClaroUtil) y la plantilla de configuracion config/properties.config.j2 (+ jndi/<servicio>.yml), y el arquetipo los habia excluido, perdiendose en los servicios generados.
- Regla: la parte tecnica reutilizable de ClaroUtil (impresion JSON, formato de fecha local, mensaje de excepcion, validacion nulo/vacio, mapeo de valores, IP del servidor) forma parte del template y el codigo generado debe usarla (sin duplicar helpers privados). Los validadores por request y constructores de respuesta de error de ClaroUtil son de negocio y se generan por servicio. Los helpers JAXB/XML y getJNDIConnection no se incluyen (el servicio usa DataSource por JndiDataSourceLookup y JSON).
- config/properties.config.j2 y jndi/@@ARTIFACT_ID@@.yml se incluyen en el template (sin secretos: logging.config parametrizado por CONFIG_SUBDIRECTORY, datos corporativos del DataSource CRMLITE y codigos/mensajes IDT genericos). El materializador anade al j2 las claves propias del servicio (procedimientos, timeouts, codigos/mensajes por operacion) sin duplicar las del template.
- Sigue excluido: Jenkinsfile (libreria compartida no disponible) y application*.properties (nunca se lee ni escribe). Aplica solo a esta version; no la congela.

