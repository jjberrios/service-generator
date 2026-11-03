# Reglas de extracción y futura generación — claro-java-8-shell / 1.0.0 (version nueva, SH-D-018..021)

Estado: nueva versión derivada de 1.0.0 (intacta y congelada). Aprobada por instrucción del
usuario (SH-D-011); **no congelada, `generationEnabled: true` (SH-D-017)** (SH-D-016). Preserva
SH-D-001…010 y SH-Q-001…012 de 1.0.0 y añade SH-D-011…016. El backend batch actual
(IR v1: connect, disconnect, list, for-each, download, upload) **no soporta** el descifrado
SOAP ni correo ni los archivos nuevos del template: debe extenderse antes de habilitar esta
versión. Ante comportamiento no soportado: **detenerse, no reescribir el arquetipo para
encajar en otro backend** ni degradar en silencio a 1.0.0.

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
| `util/SFTPConnectionManager` | parameterized | Utilitario técnico SFTP (jsch); sin la ventana de medianoche de negocio; SH-D-006. `UtilSFTP` excluido (SH-D-019) |
| `exception/*` (3 clases: BaseExceptionSFTP, SFTPException, WSException) | parameterized (solo paquete) | Jerarquía técnica usada; BaseException/PropertiesException excluidas (SH-D-019) |
| `applicationContext.xml` | parameterized | `component-scan` paquete + `import` de `applicationProxyWS.xml` (restaurado); SH-D-009/012 |
| `config/<Nombre>.properties.j2` | project-specific/excluded | Sin plantilla de configuración (SH-D-018); las claves requeridas se listan en el README generado y en `required-properties.yml` |
| `service/<Nombre>ServiceImpl` | generated-from-specification | Sparx; seguir patrón técnico de conventions.md §2/§6/§7 |
| `proxy/EbsConsultaClavesWSService`, `proxy/EbsConsultaClavesWSServiceImpl` | parameterized (solo paquete) | Proxy SOAP de descifrado de credenciales idéntico a la referencia; SH-D-012 |
| `applicationProxyWS.xml` | reusable/static | Verbatim; endpoint y timeouts son `${ws.ebsConsultaClavesWS.*}` externos; SH-D-012/013 |
| Otros `proxy/*` / contextos XML de integración | generated-from-specification | Sparx; mismo patrón `JaxWsPortProxyFactoryBean` + `util:map` de timeouts + clasificación idt1/idt2/idt3 |
| Métodos técnicos de `ServiceImpl` (`generation.servicePatterns`) | generated-from-specification (patrón técnico del arquetipo) | `desencriptarCredenciales`, `crearConexionSFTP`, catch/finally, delegaciones, marco de log; SH-D-014 |
| Mapa de tipos de archivo, filtros, margen de medianoche, de-duplicación, contadores, regla idf0/idf1, textos MTC | project-specific/excluded (Sparx) | Negocio; SH-D-014 |
| Correo / notificación | not-present-in-reference-source | Solo un jar sin uso en `Lib/`; nada se plantilla ni declara; SH-D-015 |
| Valores de propiedades, endpoints, rutas, tipos de archivo | generated-from-specification (valores: entorno) | Sparx define claves; el operador define valores |
| Pruebas del servicio | generated-from-specification | Sparx; convenciones de pruebas de conventions.md §9 |
| `sh.properties`, `<Nombre>.properties` | project-specific/excluded | Configuración protegida (secretos/hosts); SH-D-004 |
| `Lib/**` (jars), clases `pe/**`, WSDL del descifrador | project-specific/excluded | Binarios propietarios / artefactos generados / WSDL con dirección de entorno; el cliente de `Lib/` es prerrequisito externo documentado; SH-D-013 |
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
   `ebsConsultaClavesService-Client` que requiere `Lib/`; SH-Q-004 / SH-D-013).
4. Parametrizar por paquete las exclusiones Sonar/cobertura y eliminar patrones de clase
   concreta redundantes (SH-D-007).
5. Quitar de `SFTPConnectionManager` el overload de negocio con ventana de medianoche; de
   `Constantes` solo `MTC_`, `REPLACE_FECHA_*` y `ERROR_CONEXION_MTC`; de `PropertiesExterno` las
   propiedades `ftp.*`, `sftp.mtc.*`, `ruta.temp.*` (específicas). Se conservan las constantes y
   propiedades del proxy de descifrado (SH-D-012).
6. No se añade ninguna herramienta, clase, endpoint, DAO, SQL, script ni plantilla log4j
   sin evidencia.

## Reglas para el generador (cuando se autorice)

1. No emitir código que contradiga `generation.style`: constantes en `util.Constantes`,
   propiedades en `util.PropertiesExterno` (campo público + `@Value("${clave}")`), clases
   nombradas como la referencia, logging log4j 1.2 por clase con prefijo
   `[idTx=<id>][<método>] `, marcadores `INICIO_METODO/FIN_METODO/TIPO_TOTAL_PROCESO`.
2. Usar `SFTPConnectionManager` en vez de duplicar código SFTP; no emitir clases ni utilidades sin uso (SH-D-019); registrar en
   `Constantes` las `requiredConstants` declaradas.
3. Cada propiedad nueva requiere un campo en `PropertiesExterno` y su listado en el README
   generado; sin duplicar las genéricas. No se declaran `sonar.exclusions` ni
   `sonar.coverage.exclusions` (SH-D-020).
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
SH-D-010 (habilitación y congelación) pertenece solo a 1.0.0; esta versión sigue sin congelar ni
habilitar (SH-D-016). No autoriza generar un destino concreto sin sus controles ni ejecutar
Maven, redes o el jar. Cambios posteriores del baseline deben evaluarse como una versión nueva
tras congelar.

## Módulo de descifrado (SH-D-021) y reglas históricas

### Módulo `credential-decrypt-soap` (SH-D-012/013/021, solo si una conexión usa `credentialMode: decrypted-soap`)

- **Estático/parametrizado**: las 3 plantillas (`proxy/*` ×2, `applicationProxyWS.xml`), el `import`
  en `applicationContext.xml`, las constantes de `Constantes` y los 4 campos `ws.ebsConsultaClavesWS.*`
  de `PropertiesExterno`. Solo `BASE_PACKAGE`/`BASE_PACKAGE_PATH` se sustituyen.
- **Variables externas (no parámetros de render `@@`)**: `ws_ebsconsultaclavesws_url`,
  `ws_ebsconsultaclavesws_max_request_timeout`, `ws_ebsconsultaclavesws_max_connection_timeout`,
  `ws_ebsconsultaclavesws_codigo_aplicacion` (claves `ws.ebsConsultaClavesWS.*`, listadas en el README); los valores los aporta el
  operador y nunca se versionan.
- **Prerrequisitos externos**: jar `eai:ebsConsultaClavesService-Client:1.0.0` en `Lib/`
  (declarado en el POM preservado; no forma parte del arquetipo) y endpoint alcanzable.
- **Propiedad de Sparx**: si se descifra, qué credenciales y en qué orden; qué hace el flujo
  ante `WSException`; el nombre `codigoAplicacion` concreto (valor externo).
- **Condicional**: el planificador poda proxy, WSException, `applicationProxyWS.xml`, su `import` y los 4 campos cuando ninguna conexión descifra.

### Patrones técnicos del servicio (SH-D-014)

El generador puede emitir, solo si la especificación requiere el paso, los patrones
`SP-DECRYPT-HELPER`, `SP-DECRYPT-CALL`, `SP-CONN-FACTORY`, `SP-ERROR-HANDLING`,
`SP-TESTABILITY-DELEGATIONS`, `SP-DATE-FORMAT` y `SP-LOG-FRAME` de
`archetype.yml generation.servicePatterns`. `SP-FILE-TYPE-MAP` y `SP-RESPONSE-RULE` son negocio
(Sparx) y **no** se emiten desde el arquetipo. El texto de respaldo `ERROR_CONEXION_MTC` se
sustituye por el recurso que defina la especificación.

### Correo / notificación (SH-D-015)

Sin implementación en la referencia: no se genera nada y no se añade dependencia. Un paso de
envío de correo en Sparx bloquea la generación (comportamiento no soportado) hasta que exista una
decisión con evidencia.

### Brecha del backend (SH-D-016)

El IR v1 del backend no contiene pasos de descifrado SOAP ni de correo. Mientras no se amplíe,
esta versión no puede usarse para materializar y los planificadores deben detenerse.
