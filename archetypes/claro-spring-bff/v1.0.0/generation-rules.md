# Reglas de extracción y futura generación - claro-spring-bff / 1.0.0

Estado: **extracción completa, pendiente de aprobación; generación no habilitada**. El perfil `jar-springboot3-webmvc-webclient-bff`
no tiene backend en el planner/materializer: debe fallar explícitamente, nunca reescribirse para encajar en otro backend.

## Reusable / Static

| Candidato | Evidencia | Decisión |
|---|---|---|
| `.gitattributes`, `.gitignore`, wrapper (`mvnw`, `mvnw.cmd`, `.mvn/**`), `settings.xml`, `README.md` | E-GITATTR, E-GITIGNORE, E-WRAPPER, E-SETTINGS, E-README | BFF-D-002 |
| `checkstyle.xml`, `logback.xml` | E-CHECKSTYLE, E-LOGBACK | BFF-D-002 |
| `config/ExternalSecret.yml.j2` (vacío en la referencia) | E-EXTSECRET | BFF-D-002 |

## Parameterized

| Candidato | Parámetros | Evidencia |
|---|---|---|
| `pom.xml` | GROUP_ID, ARTIFACT_ID, PROJECT_VERSION, APPLICATION_CLASS, BASE_PACKAGE_PATH | E-POM |
| `Dockerfile` | BASE_PACKAGE, APPLICATION_CLASS | E-DOCKER |
| `Jenkinsfile` | ARTIFACT_ID, VAULT_NAME | E-CI |
| `config/configmap.yml.j2` | ARTIFACT_ID, BASE_PACKAGE | E-CONFIGMAP |
| `config/deployment.yml.j2` | OWNER_LABEL, PART_OF_LABEL | E-DEPLOYMENT |
| Bootstrap, `client/WebClientConfig`, `configuration/**`, `dto/response/{ApiResponseData,ErrorResponse,ResponseAudit}`, `exception/**`, `security/**`, `utils/{ActivityLogger,ConstanApi}` | BASE_PACKAGE (+ARTIFACT_ID en Swagger/ConstanApi) | E-BOOTSTRAP, E-WEBCLIENT, E-WSPROPS, E-SECURITY, E-SWAGGER, E-ENVELOPE, E-EXCEPTION, E-UTILS |

Los servicios generados deben usar `ActivityLogger` y `ConstanApi` en lugar de duplicar utilidades.

## Generated From Specification

| Área | Propietario | Semilla técnica |
|---|---|---|
| Controladores, rutas, headers, parámetros, schemas, validaciones, códigos HTTP | OpenAPI | interfaz anotada + `controller.impl` con `@RestController @Validated` |
| Flujo de negocio, actividades, decisiones, validaciones de servicio | Sparx | `service` + `service.impl`, ejecutor de actividades con `ActivityLogger` |
| Integraciones y clientes externos | Sparx | `client.<integración>` + `@Bean <integración>WebClient` en `WebClientConfig` + claves `<prefijo>.*` del ConfigMap |
| Persistencia | Sparx | no presente en la referencia; sin plantilla |
| Mappings que mezclan contrato y comportamiento | OpenAPI + Sparx | manual |
| Constantes `ACT<n>_*` | Sparx | se agregan a `ConstanApi` |
| Headers de entrada (`RequestHeaders`, mapper) | OpenAPI | resuelto por BFF-D-005 |
| Tests de negocio | OpenAPI + Sparx | convenciones en `conventions.md` |

Regla: si OpenAPI contradice el sobre de respuesta o el catálogo de headers de la plantilla (BFF-D-005), detener y pedir aclaración.

## Project-Specific / Excluded

Controlador, servicio, cliente `manualseries`, DTO de negocio y de auditoría SOAP, `RequestHeaders*`, tests y fixtures, claves
`soap.audit.*` y `manual.series.*`, constantes `ACT*`, beans `manualSeriesWebClient`/`auditWebClient`, `libs/*.jar`,
`application*.properties` (protegido) y valor por defecto del secreto JWT. Detalle en `archetype.yml` -> `exclusions`.
