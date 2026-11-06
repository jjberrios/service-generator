# Decisiones - claro-spring-bff / 1.0.0

Estado: **extracci?n completa; aprobado y habilitado para generaci?n (BFF-D-012); no congelado**. Las decisiones BFF-D-005..010 siguen siendo delegadas, sujetas a revisi?n humana.
Los identificadores BFF-D-* son locales a esta versión; no reutilizan D-001..D-014 ni J8-D-* de otros arquetipos.

## BFF-D-001 - Extracción inicial, alcance y nombre

- Decisión: extraer estructura y convenciones técnicas de
  `input/reference/bff-customerbillconfiguration-Feature-300864@ccdb2c4c953/` hacia el destino NUEVO
  `archetypes/claro-spring-bff/v1.0.0/`, sin modificar la referencia, sin copiar negocio y sin analizar OpenAPI/Sparx.
- Nombre: `claro-spring-bff` (Spring Boot 3 / Java 21, BFF reactivo sobre WebClient). El usuario delegó la elección del nombre.
- Estado: **instrucción explícita del usuario** (creación del arquetipo y delegación del nombre).
- Alcance: esta extracción y esta versión; no autoriza generación de servicios ni congelación.
- Evidencia: solicitud actual; AGENTS.md.
- Temporalidad: permanente para procedencia y nombre; el baseline sigue pendiente de aprobación.
- Revisión futura: renombrar exige nueva versión o revisión explícita.

## BFF-D-002 - Baseline técnico tomado íntegramente de la referencia

- Decisión: aplicar la política "Reference-Based Extraction" de AGENTS.md: POM completo (parent 3.4.1, propiedades, 21 dependencias,
  5 plugins, 3 repositorios, perfil `local`), Java 21, JAR, WebMVC + WebClient, Spring Security + JWT, springdoc, Checkstyle (validate,
  main y test), JaCoCo 80 % por paquete, logback JSON + CommonAppender, Dockerfile, Jenkinsfile, Kubernetes, wrapper y settings.xml.
  No se poda, moderniza ni corrige scopes. No hay persistencia en la referencia: no se introduce JPA/JDBC.
- Estado: **política del repositorio aplicada**; no es una elección nueva del agente.
- Alcance: plantillas y metadatos de esta versión.
- Evidencia: E-POM, E-CHECKSTYLE, E-LOGBACK, E-DOCKER, E-CI, E-DEPLOYMENT, E-SECURITY, E-UTILS, E-WRAPPER, E-SETTINGS.
- Revisión futura: cualquier desvío necesita decisión explícita.

## BFF-D-003 - Transformaciones documentadas

- Parametrización de identidad: groupId, artifactId, versión, paquete base, clase de aplicación, vault, etiquetas owner/part-of.
- `client/WebClientConfig`: se eliminan los beans `manualSeriesWebClient` y `auditWebClient` (específicos de integración) y los imports
  que quedaban sin uso (Checkstyle UnusedImports); se conserva `createWebClient`. Cada integración Sparx añade su `@Bean` con el mismo estilo.
- `utils/ConstanApi`: se eliminan las constantes `ACT*` (negocio Sparx) y `NOMBRE_APLICACION` pasa a `@@ARTIFACT_ID@@`.
- `config/configmap.yml.j2`: se eliminan las secciones `soap.audit.*` y `manual.series.*`; `security.jwt.secret-key` pasa de
  `${JWT_SECRET_KEY:<valor por defecto>}` a `${JWT_SECRET_KEY}` para no versionar una clave por defecto (exclusión de secretos).
- `Dockerfile`: la clase principal de ENTRYPOINT (que apuntaba a otro paquete inexistente en el fuente) usa `@@BASE_PACKAGE@@.@@APPLICATION_CLASS@@` (BFF-A-003).
- `pom.xml`: las exclusiones de cobertura por capa se conservan; las referencias al paquete/clase concretos se parametrizan.
- Estado: **aplicadas por política (exclusión de negocio y secretos)**; sujetas a revisión del usuario.
- Evidencia: E-WEBCLIENT, E-UTILS, E-CONFIGMAP, E-DOCKER, E-POM.

## BFF-D-004 - Sobre y manejo de errores incluidos como baseline técnico (TEMPORAL)

- Decisión: `ApiResponseData`, `ResponseAudit`, `ErrorResponse`, `WsResponseProperties`, `BusinessException` y `GlobalExceptionHandler` se
  conservan literalmente como baseline técnico, porque el manejador depende del catálogo `ws.*` y compila solo con ellos.
- Estado: **temporal**; depende de la resolución de BFF-A-001 (propiedad OpenAPI del sobre y lista de headers).
- Regla de generación: si OpenAPI contradice el sobre o los headers, se detiene la generación y se pide aclaración.
- Evidencia: E-ENVELOPE, E-EXCEPTION, E-WSPROPS.
- Revisión futura: obligatoria al resolver BFF-A-001.

## Delegación del usuario

El usuario indicó textualmente: "Necesito que tomes las mejores desiciones por mi." Con base en esa delegación explícita, las
ambigüedades BFF-A-001..006 se resolvieron con la opción más conservadora (preservar la referencia, no inventar comportamiento).
Las decisiones BFF-D-005..010 son decisiones delegadas del agente, sujetas a revisión humana antes de aprobar/congelar.

## BFF-D-005 - Resolución de BFF-A-001: sobre de respuesta y headers (delegada)

- Decisión: el sobre (`ApiResponseData`, `ResponseAudit`, `ErrorResponse`), `WsResponseProperties`, `BusinessException` y
  `GlobalExceptionHandler` son baseline técnico de esta versión, conservados literalmente. `RequestHeaders`/`RequestHeadersMapper`
  siguen excluidos (los headers de entrada son propiedad de OpenAPI). La lista `invalidHeadersDetail` se mantiene literal y se
  registra como riesgo de revisión; no se corrige en silencio.
- Regla: si OpenAPI contradice el sobre, los códigos `ws.*` o los headers, se detiene la generación y se pide aclaración.
- Estado: delegada; sustituye el carácter temporal de BFF-D-004 (que pasa a quedar resuelto por esta decisión).
- Revisión futura: nueva versión si se desea mover el sobre a OpenAPI.

## BFF-D-006 - Resolución de BFF-A-002: seguridad JWT (delegada)

- Decisión: preservar el comportamiento de la referencia (`permitAll` + filtro JWT que autentica sin exigir). No se inventa
  una política de autorización; se registra como riesgo de revisión. Exigir autenticación solo si OpenAPI declara un esquema de
  seguridad aplicable o el usuario lo instruye.
- Estado: delegada.

## BFF-D-007 - Resolución de BFF-A-003: clase principal del Dockerfile (delegada)

- Decisión: se confirma `@@BASE_PACKAGE@@.@@APPLICATION_CLASS@@` como clase principal de ENTRYPOINT (el valor de la referencia apuntaba a un
  paquete inexistente en el fuente).
- Estado: delegada.

## BFF-D-008 - Resolución de BFF-A-004: `libs/*.jar` (delegada)

- Decisión: se conserva `COPY ./libs` del Dockerfile. Los JAR corporativos no se plantillan (binarios); son prerrequisito externo
  que el repositorio del servicio debe proveer. No se inventan versiones ni orígenes.
- Estado: delegada.

## BFF-D-009 - Resolución de BFF-A-005: plugins antiguos (delegada)

- Decisión: se conservan maven-compiler-plugin 3.8.1 y maven-surefire-plugin 2.22.2 sin modernizar (política de POM). La ejecución
  de JUnit 5 con esos plugins queda `unverified` hasta una ejecución Maven autorizada.
- Estado: delegada.

## BFF-D-010 - Resolución de BFF-A-006: prefijo de transacción vacío (delegada)

- Decisión: se conserva el patrón observado (`menTran = ""`); no se altera el logging de la referencia. Se registra como riesgo de
  revisión (logs de actividad sin id de transacción).
- Estado: delegada.

## BFF-D-011 - Alcance del backend del perfil BFF (delegada)

- Decisión: el backend del perfil `jar-springboot3-webmvc-webclient-bff` (`bff_plan.py`, `bff_materializer.py`) cubre estructura + contrato:
  ensamblado de la plantilla, DTOs/interfaz/controlador desde OpenAPI y servicio+cliente WebClient solo con `bffBinding` v1 explícito
  respaldado por Sparx (passthrough de identidad). Las operaciones sin binding se omiten de forma explícita
  (`UnsupportedOperationException` + `omittedBehavior`); no se inventa comportamiento. Restricciones de esquema no soportadas, `required`
  en cuerpo y enums se rechazan. Checkstyle/Maven/JaCoCo permanecen `unverified`/`not-run`.
- Estado: delegada (instrucción del usuario: "Si, hay que añadir sopote para ese perfil" y alcance "Estructura + contrato"). No aprueba ni habilita el arquetipo.

## Ambigüedades

BFF-A-001..006 quedaron resueltas por BFF-D-005..010 (delegadas). No quedan ambigüedades abiertas; la aprobación y congelación
del arquetipo siguen pendientes de revisión humana y de soporte de backend para el perfil.

## BFF-D-012 - Aprobaci?n y habilitaci?n para generaci?n (usuario)

- Decisi?n: aprobar y habilitar el arquetipo `claro-spring-bff` v1.0.0 para generaci?n de servicios (`identity.approved: true`,
  `identity.generationEnabled: true`). No se congela (`frozen: false`, `readyToFreeze: false`) y el baseline t?cnico (POM, plantillas, plugins,
  Checkstyle, JaCoCo, runtime) no se modifica; las decisiones BFF-D-001..011 se preservan sin cambios.
- Estado: **instrucci?n expl?cita del usuario**. Cita literal de la respuesta del usuario a la pregunta de aprobar `claro-spring-bff/v1.0.0`:
  "S?, aprobar y habilitar".
- Alcance: esta versi?n; el alcance del backend sigue siendo el de BFF-D-011 (estructura + contrato, WebClient solo con `bffBinding` v1 expl?cito).
  Maven, base de datos y despliegue siguen requiriendo autorizaci?n expl?cita aparte.
- Revisi?n futura: congelar o cambiar el baseline requiere una instrucci?n expl?cita nueva.

## BFF-D-013 - Extensión del backend BFF: cuerpo de request con restricciones declaradas (usuario)

- Decisión: el backend del perfil `jar-springboot3-webmvc-webclient-bff` (`bff_plan.py`, `bff_materializer.py`) amplía el alcance de BFF-D-011 solo para el
  **cuerpo de request** (`requestBody`) con: `required` (Bean Validation `@NotNull`, exactamente la semántica del swagger: presencia, no no-vacío),
  `maxLength` en strings (`@Size(max = N)`), `additionalProperties: true` en objetos (los campos declarados se conservan como propiedades tipadas y el resto
  se retiene con `@JsonAnySetter`/`@JsonAnyGetter` sin pérdida de datos) y objetos anidados validados en cascada (`@Valid`). Los DTO de request con
  restricciones usan `@JsonInclude(NON_NULL)` para no reenviar al backend campos ausentes como `null`. El reenvío del cuerpo (`forwardRequestBody`) y el
  passthrough de la respuesta (`responseMapping: identity`) no cambian. Se genera `RequestContractTest` (JUnit 5, Bean Validation real y Jackson) para estas restricciones.
- Siguen sin soportarse (rechazo explícito): `minimum`, `maximum`, `minLength`, `pattern`, `minItems`, `maxItems`, `oneOf`/`allOf`/`anyOf`,
  `additionalProperties` distinto de `true`, `nullable`, `readOnly`, `writeOnly` y `enum`; `maxLength` fuera de strings; y cualquiera de estas
  restricciones en parámetros o respuestas (en respuestas solo se tolera `required`, como antes).
- Estado: **instrucción explícita del usuario**: "extiende el materializador" (para soportar `resolveCustomerBillCase` de orq-customerBillCases).
  No altera el baseline técnico del arquetipo (POM, plantillas, plugins, Checkstyle, JaCoCo, runtime) ni las decisiones BFF-D-001..012, que se preservan.
  Checkstyle/Maven/JaCoCo siguen `unverified`/`not-run` en el materializador; Maven, base de datos y despliegue requieren autorización aparte.