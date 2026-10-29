# Reglas de extracción y futura generación — claro-java-8-shell / 1.0.0

Estado: extracción completa, **congelada**, `generationEnabled: true` por SH-D-010. Existen
decisiones aprobadas SH-D-001 a 010 y resoluciones SH-Q-001 a 012 fieles a la
referencia en `decisions.md`. Existe un backend acotado para secuencias SFTP del perfil
batch-shell (Java 8, Spring XML, log4j, jsch). Su contrato está en
`.opencode/skills/materialize-full-service/docs/batch-shell-contract.md`.
Ante comportamiento no soportado: **detenerse, no reescribir el arquetipo para encajar
en otro backend**. La habilitación y congelación fueron autorizadas por el usuario
en SH-D-010, no inferidas de la implementación del backend.

## Modelo de generación de un servicio batch

Un servicio batch se genera desde **Arquetipo + especificación funcional Sparx**. El
contrato **no es HTTP**: OpenAPI **no aplica** (no hay métodos, rutas, esquemas de
request/response ni validación HTTP). La invocación técnica conserva `args[0]` y
`-Dproperties`, sin validación adicional ni contrato OpenAPI (SH-Q-002).
Sparx define: flujo del proceso, qué archivos/datos se procesan, orígenes y
destinos, filtros y fechas, integraciones (SFTP/FTP/fileshare, servicios web), persistencia
(si la hay), códigos y condiciones de error, secuencia. El arquetipo aporta: estructura,
build, entrada `main`, logging, configuración externa, utilidades técnicas y pruebas.

Prueba esperada: ejecución (running) del jar con archivo de propiedades externo; las
pruebas unitarias JUnit4/Mockito cubren el servicio con mocks de SFTP/WS. No hay pruebas
de endpoints.

## Clasificación primaria

| Candidato | Clasificación | Tratamiento / evidencia |
|---|---|---|
| `pom.xml` | parameterized | Baseline completo de la referencia (14 deps, 7 plugins); tokens GROUP_ID/ARTIFACT_ID/PROJECT_VERSION/BASE_PACKAGE/MAIN_CLASS/PROPERTIES_FILE_BASENAME; E-POM, SH-D-003 |
| `.gitignore`, `.editorConfig` | reusable/static | Copia literal; E-GITIGNORE, E-EDITORCONFIG |
| `README.MD` | parameterized | Esqueleto de secciones observadas sin negocio ni IP; SH-D-008 |
| `<Nombre>Main` | parameterized | Flujo técnico de entrada idéntico a la referencia; E-MAIN |
| `service/<Nombre>Service` (interfaz) | parameterized | Contrato único `run(String, String)`; E-SERVICE-IFACE |
| `util/Constantes`, `util/PropertiesExterno` | parameterized | Solo constantes/propiedades técnicas; el generador agrega las específicas; SH-D-006 |
| `util/SFTPConnectionManager`, `util/UtilSFTP` | parameterized | Utilitarios técnicos SFTP (jsch); sin la ventana de medianoche de negocio; SH-D-006 |
| `exception/*` (5 clases) | parameterized (solo paquete) | Jerarquía técnica tal cual; SH-D-006 |
| `applicationContext.xml` | parameterized | `component-scan` paquete; sin import de proxy; SH-D-009 |
| `config/<Nombre>.properties.j2` | parameterized | Claves genéricas sin valores; SH-D-004/009 |
| `service/<Nombre>ServiceImpl` | generated-from-specification | Sparx; seguir patrón técnico de conventions.md §2/§6/§7 |
| `proxy/*`, `applicationProxyWS.xml` | generated-from-specification | Sparx (integración SOAP); patrón: `JaxWsPortProxyFactoryBean` + `util:map` de `com.sun.xml.ws.request.timeout`/`connect.timeout` con claves `ws.<servicio>.max.*`; clasificación de excepciones de red → idt1 (timeout)/idt2 (disponibilidad)/idt3 (general) |
| Valores de propiedades, endpoints, rutas, tipos de archivo | generated-from-specification (valores: entorno) | Sparx define claves; el operador define valores |
| Pruebas del servicio | generated-from-specification | Sparx; convenciones de pruebas de conventions.md §9 |
| `sh.properties`, `<Nombre>.properties` | project-specific/excluded | Configuración protegida (secretos/hosts); SH-D-004 |
| `Lib/**`, clases `pe/**`, WSDL | project-specific/excluded | Binarios/artefactos generados; SH-Q-004 |
| `applicationDatasource.xml` | project-specific/excluded | Muerto y con identidad de BD concreta; SH-Q-009 |
| `.idea`, `.settings`, `.classpath`, `.project`, `.iml` | project-specific/excluded | Estado de IDE |
| Checkstyle | not-applicable | Ausente en build; SH-D-005 |

## Fuente de propiedad

| Área | Propietario |
|---|---|
| Runtime/plataforma, estructura, build, logging, config externa, utilitarios, calidad | Arquetipo |
| Contrato HTTP, esquemas, validación HTTP | **No aplica** (batch) |
| Argumentos/parámetros de invocación (más allá de `idTransaccion` técnico) | Sparx (SH-Q-002) |
| Flujo, archivos, filtros, fechas, integraciones, persistencia, errores | Sparx |
| Valores de configuración y secretos | Operador/entorno |

## Parámetros y sustitución

Sintaxis `@@NAME@@` en contenido y rutas; no reemplazar `${...}` (Spring/Maven) ni `{{ ... }}`
(jinja2 de los `.j2`). Detalle exacto en `archetype.yml` (`parameters`).

- GROUP_ID / ARTIFACT_ID / PROJECT_VERSION: identidad Maven (observado `pe.com.claro.shell`,
  `SH_<Nombre>`).
- BASE_PACKAGE (+ BASE_PACKAGE_PATH derivado, solo puntos→`/`): paquete raíz del destino.
- MAIN_CLASS: clase con `main` (observado `<Nombre>Main`).
- SERVICE_INTERFACE (+ SERVICE_FIELD derivado, primera letra en minúscula): interfaz del
  servicio (observado `<Nombre>Service`).
- PROPERTIES_FILE_BASENAME: nombre del `.properties` externo sin extensión.

Rechazar palabras reservadas Java, traversal y colisiones. Render solo bajo salida
autorizada y sin tokens remanentes. Los `application*.properties` y los `.properties`
protegidos jamás son destino de render ni se leen.

## Transformaciones autorizadas

1. Selección manual de archivos (no hay copia recursiva).
2. Sustituir identidad/paquete/clase/archivo de propiedades por tokens.
3. Preservar íntegros dependencias, plugins, versiones, scopes, ejecuciones, propiedades,
   repositorio y `distributionManagement` del POM (incluida la dependencia
   `ebsConsultaClavesService-Client` que requiere `Lib/`; SH-Q-004).
4. Parametrizar por paquete las exclusiones Sonar/cobertura y eliminar patrones de clase
   concreta redundantes (SH-D-007).
5. Quitar de `SFTPConnectionManager` el overload de negocio con ventana de medianoche; de
   `Constantes` las constantes de negocio/integración; de `PropertiesExterno` las
   propiedades específicas.
6. No se añade ninguna herramienta, clase, endpoint, DAO, SQL, script ni plantilla log4j
   sin evidencia.

## Reglas para el generador (cuando se autorice)

1. No emitir código que contradiga `generation.style`: constantes en `util.Constantes`,
   propiedades en `util.PropertiesExterno` (campo público + `@Value("${clave}")`), clases
   nombradas como la referencia, logging log4j 1.2 por clase con prefijo
   `[idTx=<id>][<método>] `, marcadores `INICIO_METODO/FIN_METODO/TIPO_TOTAL_PROCESO`.
2. Usar `SFTPConnectionManager`/`UtilSFTP` en vez de duplicar código SFTP; registrar en
   `Constantes` las `requiredConstants` declaradas.
3. Cada propiedad nueva requiere (a) clave en `config/<Nombre>.properties.j2` y (b) campo
   en `PropertiesExterno`; sin duplicar las genéricas.
4. `run` captura por tipo, registra código/mensaje (idf/idt) y cierra recursos en `finally`;
   no propaga excepciones a `main` (observado). El código de salida del proceso solo se
    cambia por una nueva decisión explícita; SH-Q-001 conserva la ausencia de `System.exit`.
5. Los comportamientos no resueltos por Sparx se omiten y se declaran; nunca se inventan.
6. Revisión obligatoria contra la referencia (estilo) antes de declarar el arquetipo listo
   para generación.

## Limitaciones externas y verificaciones pendientes

Las preguntas SH-Q-001 a 012 están resueltas en `decisions.md` por fidelidad a la
referencia. No se inventan log4j, scripts, scheduler, ubicación de distribución de
`Lib/` ni persistencia. Los recursos externos requeridos los provee el operador.
Compatibilidad Spring/Java, resolución de dependencias y ejecución no verificadas.
SH-D-010 habilita el backend acotado y congela esta versión. No autoriza generar un
destino concreto sin sus controles ni ejecutar Maven, redes o el jar. Revisar esta
versión congelada requiere una instrucción explícita; cambios de baseline deben
evaluarse como una nueva versión.
