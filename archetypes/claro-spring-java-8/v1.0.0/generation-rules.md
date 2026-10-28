# Reglas de extracción y futura generación

Estado: **extraction-complete-decisions-approved**, baseline de esta referencia,
no congelado. J8-D-001…006, H-REV-2026-10-20, resuelven J8-Q-001…005 sin
autorizar generación, compilación o migración. No modificar otros arquetipos,
agentes, output o insumos. Backend/runtime no verificados son gates separados.

## Clasificación primaria y decisiones

| Candidato | Clasificación | Tratamiento / evidencia |
|---|---|---|
| POM técnico | parameterized | Baseline obligatorio completo de SU referencia, no podar/modernizar/corregir scopes; E-POM, J8-D-002/005/006 |
| Bootstrap e initializer WAR | parameterized | Paquete/clase/ruta externa variables, concatenación fiel; E-BOOTSTRAP/E-INITIALIZER, J8-D-002/006 |
| Logback | parameterized | Directorio/nombre variables; patrón real conservado; E-LOGBACK, J8-D-003 |
| Logging en código | reusable/static (convención, no clase) | SLF4J por clase, patrón de marcadores/JSON/tiempos documentado; E-SERVICE/E-CONTROLLER/E-UTIL-LOGGING, J8-D-003 |
| WebLogic descriptor | parameterized | context-root variable y preferencias literales; E-WEBLOGIC, J8-D-006 |
| Descriptor Spring vacío / .gitignore | reusable/static | Solo estructura técnica; E-DISPATCHER/E-GITIGNORE |
| Métodos/DTO/headers/validaciones HTTP | generated-from-specification | Solo OpenAPI determina contrato/schemas; no copiar operaciones |
| Servicios/procesos/clientes/persistencia | generated-from-specification | Sparx, JDBC/JNDI observado, no JPA por declaración de API; J8-D-002 |
| Mappings/traducciones de errores/tests | generated-from-specification | OpenAPI + Sparx; organización JUnit4 observada, sin fixtures |
| Utilidad mixta, constantes/beans/excepciones concretas | project-specific/excluded | Logging solo se documenta separado de validación/negocio; no copiar clases |
| DAO/JdbcConfig/repositorio concretos | project-specific/excluded | Identidades JNDI, procedimientos, cursores, SQL y mappings propios |
| YAML JNDI / properties.config.j2 | project-specific/excluded | Valores de dominio/entorno, solo evidencia estructural |
| Jenkinsfile ejecutable | project-specific/excluded | Se conserva evidencia/estructura de llamada y ocho keys; biblioteca ausente/publicación local; J8-D-006 |
| Exclusiones Sonar de dominio | project-specific/excluded | Vaciar ambas properties, no generalizar por capa; J8-D-005 |
| application*.properties | project-specific/excluded | Nunca leer/analizar/reportar/comparar/copiar/hashear; tampoco comparar metadata |
| HELP, fixtures, SQL, credenciales, host privado | project-specific/excluded | Ninguna copia al template |
| Checkstyle | project-specific/excluded (ausente) | No añadir configuración/plugin/gate; not-applicable, J8-D-004 |

Las dependencias declaradas se conservan incluso si su uso directo no se observa.
`build.dependencyUsage` distingue uso real, proveedor API/transitivo no resuelto,
driver/contenedor declarado y mera declaración. No forzar uso de SOAP/JPA/Gson/
PowerMock ni eliminar bibliotecas. SLF4J/Jackson observados no se convierten en
dependencias directas nuevas por inferencia; la resolución transitiva no se ejecutó.

## Parámetros y sustitución

Fuente, regex, scope y affectedFiles exactos están en `archetype.yml`.
Sintaxis `@@NAME@@` también en rutas; no reemplazar `${...}` ni `%d{...}`.

- GROUP_ID / ARTIFACT_ID / PROJECT_VERSION: identidad técnica Maven del destino.
- BASE_PACKAGE: paquete destino; BASE_PACKAGE_PATH se deriva solo reemplazando
  puntos por `/`, nunca elección independiente.
- APPLICATION_CLASS: nombre bootstrap sin `.java`.
- CONFIG_ROOT_PROPERTY: propiedad JVM con raíz externa; por concatenación original
  el valor del entorno necesita separador final. No usar `new File(parent, child)`.
- CONFIG_SUBDIRECTORY: ruta relativa externa acotada, sin traversal.
- LOG_DIRECTORY: directorio absoluto Unix del entorno; no copiar ruta privada.
- CONTEXT_ROOT: contexto WAR sin `/` inicial.
- CORPORATE_REPOSITORY_URL: URL HTTP/HTTPS sin userinfo, query o secretos. No se
  fuerza cambio a HTTPS que la referencia no usa; no default de host privado.
  Cualquier endurecimiento posterior necesita instrucción, no corrección silenciosa.

Validar/escapar por contexto XML/string Java y rechazar palabras Java reservadas,
traversal/colisiones. Render solo bajo salida autorizada y sin tokens restantes.
Configuración protegida jamás es destino del render. No defaults de identidad,
infraestructura, repositorio, versión de servidor o toolchain desconocida.

## Transformaciones autorizadas, no modernizaciones

1. Selección manual, no copia recursiva de referencia.
2. Sustituir identidad Maven/paquetes/clase/URL/rutas/context-root por tokens.
3. Conservar 24 dependencias activas, cuatro plugins y sus versiones/scopes/
   optional/ejecuciones, parent/properties/plugin repositories. Excluir alternativa
   de driver comentada (no activa) y comentarios propios de negocio.
4. Vaciar SOLO `sonar.coverage.exclusions` y `sonar.exclusions` por patrones de
   dominio; preservar claves y plugins, sin exclusiones sustitutas. J8-D-005
   autoriza esta transformación junto con prohibición de copiar negocio.
5. Preservar carga externa servlet por concatenación original; la revisión revierte
   la normalización previa por File. No corregir casos de propiedad inexistente,
   formato de tiempo/fecha, versiones o scopes. Formato XML/Java sin cambios semánticos.
6. Mantener Logback y descriptor WebLogic literales salvo valores parametrizados.
7. No incluir pipeline Jenkins sustituto ni publicación de configuración local.
   `deployment.ci.parameterKeys` conserva contrato observable, no implementación.
   Reutilizar pipeline real exige biblioteca/entorno y política externa comprobadas.
8. No añadir herramientas ausentes ni clases vacías/endpoints/SQL de ejemplo.

## Logging reusable sin negocio — J8-D-003

Aplicar el patrón detallado en conventions/runtime.logging: LoggerFactory por clase,
marcadores INFO de inicio/fin, prefijo local método/idTx, header/body/response por
Jackson (pretty controller, compacto utilidad), tiempos y error con excepción.
Mantener peculiaridades observadas; no importar ActivityLogger/records ni crear
adaptador. No copiar la utilidad de validación mixta, actividades, constantes de
negocio o headers de referencia. Actividades/nombres/llamadas vienen del flujo
Sparx y los datos del contrato OpenAPI. Sin operación autorizada no generar logs
de operación. No inventar fallback de transacción, cambiar respuestas o añadir
masking silenciosamente. Exposición de datos/fechas permanece riesgo explícito,
no garantía de seguridad ni regla universal aprobada.

## Ownership futuro (sin analizar fuentes en esta fase)

- Arquetipo: plataforma/paquetes/ingeniería y configuración/entrega reutilizable
  de SU referencia, conforme J8-D-002…006.
- OpenAPI: métodos/paths/headers/parámetros, request/response, HTTP, validaciones
  declaradas y error shapes.
- Sparx: flujo/reglas/procesos/actividades, decisiones, integraciones/clientes,
  persistencia y errores de comportamiento.
- OpenAPI + Sparx: mappings/traducciones y pruebas combinadas.
- Operador: valores locales, secretos, JNDI, configuración externa, autenticación
  de repositorios y despliegue. No incrustar credenciales.

## Preguntas históricas y gates actuales

| Pregunta | Decisión aplicada |
|---|---|
| J8-Q-001 | J8-D-002: plataforma/persistencia propias |
| J8-Q-002 | J8-D-003: logging real, riesgo de datos separado |
| J8-Q-003 | J8-D-004: Checkstyle ausente, no aplicable |
| J8-Q-004 | J8-D-005: POM íntegro, uso no forzado, exclusiones de dominio fuera |
| J8-Q-005 | J8-D-006: runtime/repositorio/entrega observados; unknown no migración |

No hay ambigüedad de decisión pendiente en estos alcances. Congelación NO
autorizada; generación aún deshabilitada, backend Java8/Boot2/WAR/JDBC-JNDI/JUnit4
no probado. Antes de generar verificar soporte del backend, contrato/semántica,
gate de consistencia, autorización y protección de output; no adaptar baseline
a otro perfil. Versiones de servidor/toolchain permanecen unknown sin bloquear
extracción, no promesa de ejecución.

Validación reproducible: YAML/XML, inventario/parámetros/render en memoria,
dependencias/plugins/properties/repositorios contra referencia, evidence/decisiones,
uso declarado/observado, fugas/secretos e integridad permitida. No compila Java ni
ejecuta Maven/tests/JaCoCo/Sonar. Checkstyle **not-applicable**, nunca passed ni
gate obligatorio prestado. Sin Maven, DB, red, despliegues ni contratos/Sparx.
