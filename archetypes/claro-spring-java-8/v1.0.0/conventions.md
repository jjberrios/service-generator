# Convenciones — claro-spring-java-8 1.0.0

**Extracción completa, baseline de referencia aprobado por decisiones actuales;
no congelado ni compilado.** J8-D-001 preserva el alcance inicial y J8-D-002…006
aplican la autorización explícita de revisión H-REV-2026-10-20. No se heredan
decisiones de `claro-spring-ms`. Son baselines de ESTA versión, no estándares
corporativos. J8-Q-001…005 están resueltas, no pendientes de aprobación de stack.

## Plataforma y build — J8-D-002 / J8-D-005 / J8-D-006

- E-POM: Maven monomódulo, parent Boot `2.0.5.RELEASE`, Java `1.8`, UTF-8 y WAR.
  No modules, profiles, dependencyManagement o pluginManagement propios.
  Maven, distribución JDK y versión de WebLogic desconocidos; no inventarlos.
- Las 24 dependencias activas directas y cuatro plugins son baseline íntegro.
  Mantener versiones/scopes/optional/configuraciones/ejecuciones declarados;
  añadir solo dependencias futuras justificadas, nunca podar las existentes ni
  obligar a usarlas. Inventario completo en `build.dependencies`; uso observado
  separado en `build.dependencyUsage`, con evidencia para cada declaración.
- MVC/Jackson, JDBC/JNDI y JUnit4/Mockito tienen uso observable. Hibernate aporta
  un helper de cursor Oracle (proveedor transitivo no resuelto), no demuestra uso
  de EntityManager/JPA. SOAP/Gson/Commons/AssertJ/PowerMock/Javassist y APIs JPA
  están declarados sin uso directo observado; eso no prueba inutilidad runtime.
  Las APIs Java EE usadas pueden solaparse con JDK/contenedor; no adjudicar su
  proveedor sin resolver el build. Configuration processor no está verificado.
- Tomcat `provided`; `spring-boot-maven-plugin` y `maven-war-plugin` conservados
  con `failOnMissingWebXml=false`. Sin effective-pom, transitivas ni versiones
  heredadas resueltas. Propiedades Gson/Hibernate no prueban un pin efectivo.
- Driver `com.oracle:ojdbc14:9.0.2.0.0` conservado; alternativa comentada excluida.
  JUnit 4.11, Mockito 2.0.5-beta, PowerMock 1.6.2 y AssertJ 2.6.0 conservan scope
  implícito compile, no corregido a test. No se moderniza por antigüedad.
- Repositorio `maven-releases`: URL HTTP/HTTPS parametrizada, sin host privado,
  userinfo o secretos; HTTP es observado, no una garantía de seguridad. Autenticación
  externa, sin settings inventado. Plugin repositories Spring milestones/snapshots
  y sus restricciones se conservan. No wrapper ni settings.xml observados.
- E-HELP cita Boot 3.2.1-SNAPSHOT; E-POM declara 2.0.5.RELEASE. Se conserva la
  discrepancia documental; el POM manda para el baseline, no se migra.

## Paquetes y arquitectura — J8-D-002

- E-BOOTSTRAP: bootstrap/initializer en `<basePackage>.servlet.config`, escaneo
  explícito del paquete base. Solo esas clases técnicas se materializan.
- Extensiones observadas: `controller`, `service`, `repository`, `canonical.request`,
  `canonical.response`, `canonical.type`, `common.bean`, `common.exception`,
  `common.property`, `common.util`. No crear clases vacías para aparentar negocio.
- E-CONTROLLER/E-SERVICE: `@RestController`, MVC, field injection `@Autowired`,
  servicio concreto `@Component`; no imponer interfaz de servicio.
- E-JDBC/E-REPOSITORY: interfaz DAO y clase `@Repository`, DataSource por
  JndiDataSourceLookup y lookup JNDI en utilidad de conexión, CallableStatement,
  ResultSet y OracleTypesHelper para cursor. No añadir Spring Data/JPA/HikariCP.
  Se excluyen nombres de beans/JNDI concretos, SQL, procedimientos y mappings;
  Sparx determina su semántica futura, no el arquetipo.
- DTOs POJO mutables con getters/setters; no records, Lombok o MapStruct observados.
  Mappings manuales futuros son OpenAPI + Sparx, no copia de setters de referencia.
- E-EXCEPTIONS: jerarquía checked con metadata observada, sin template de clases
  porque mezcla error shapes/códigos/servicios. No imponer HTTP 200 ni handler global.

## Configuración y logging — J8-D-003 / J8-D-006

- E-INITIALIZER: `spring.config.location` externo solo en arranque servlet.
  La plantilla conserva concatenación original de propiedad raíz + subdirectorio
  + File.separator + nombre técnico de archivo. La raíz debe traer separador
  final; no se normaliza mediante `new File(parent, child)`. No afirmar mecanismo
  idéntico en `main` ni corregir el comportamiento cuando falta propiedad.
- **Nunca leer, analizar, reportar, comparar, copiar ni hashear contenido de
  `application*.properties`**; tampoco comparar metadata de esos archivos.
  Su nombre en initializer no es acceso al contenido. Configuración efectiva,
  perfiles, seguridad y datasource permanecen fuera del alcance.
- E-CONFIG: plantilla externa distinta contiene claves técnicas mezcladas con
  mensajes/procedimientos de negocio; queda excluida, no reproducida.
- E-LOGBACK: RollingFileAppender, INFO, rotación diaria, 30 días y 3GB; patrón
  literal conservado, directorio/nombre parametrizados. Activación del XML externo
  es prerequisito del entorno, no descubrimiento automático garantizado.

### Patrón reusable real (sin copiar la utilidad mixta)

E-CONTROLLER:35,53–90, E-SERVICE:51,61–85,159–163,423–433,
E-UTIL-LOGGING:55–85 y E-LOG-CONSTANTS:

1. Logger SLF4J estático final por clase: `LoggerFactory.getLogger(CurrentClass.class)`.
   El controller emite separadores e inicio/fin de método a INFO, header/body JSON
   pretty, response y tiempo con `System.currentTimeMillis()`. El formato observado
   de tiempo no contiene placeholder; NO se promete que imprima un valor numérico.
2. El servicio registra request por utilidad y usa `inicioActividad`/`finActividad`.
   El prefijo se construye localmente con método e `idTx`; el espaciado varía.
   No se inventa fallback universal ni header/record técnico de otro proyecto.
3. Esquema exacto reusable de marcadores, con argumentos futuros del flujo:

   ```text
   INFO menTran + SEPARADOR
   INFO menTran + INICIO_ACTIVIDAD/FIN_ACTIVIDAD + actividad + SEPARADOR_ACTIVIDAD
   INFO menTran + SEPARADOR
   ```

   Literales técnicos observados: inicio `====[INICIO ACTIVIDAD]: ` y fin
   ` ======== [ FIN ACTIVIDAD : `; no corregirlos ni copiar nombres de actividades.
   Son operaciones locales del servicio, no un ActivityLogger nuevo.
4. JSON usa Jackson ObjectMapper con DateFormat en zona local, patrón
   `yyyy-MM-dd'T'HH:mm:ss'Z'`, `WRITE_DATES_AS_TIMESTAMPS=false`; pretty en
   controller, compacto en utilidad. La forma compacta captura JsonProcessingException,
   registra su mensaje y devuelve cadena vacía; pretty propaga esa excepción.
   La Z es literal pese a usar zona local: riesgo observado, no corregido.
5. Errores: controller registra prefijo ERROR + mensaje y excepción; servicio
   detalle y excepción; repositorio registra parámetros/timing/errores JDBC.
   No extraer la traducción de errores de negocio junto con esos logs.

La parte tecnica reutilizable de `ClaroUtil` SI se incluye en el template (J8-D-009): impresion JSON,
formato de fecha local, mensaje de excepcion, validacion nulo/vacio, mapeo de valores e IP del servidor.
El codigo generado debe usarla. Los validadores por request y los constructores de respuesta de error
(parte de negocio de la utilidad de referencia) se generan por servicio con operaciones/actividades
autorizadas, sin importar payloads, headers, validadores, codigos ni constantes de negocio.
Tambien se incluyen `config/properties.config.j2` y `jndi/<servicio>.yml` (sin secretos). Logging no
autoriza cambiar statuses/retornos ni inventar actividades.

**Riesgos no resueltos por aprobación técnica:** cuerpos/headers/parámetros sin
evidencia de masking, excepciones y formato de fechas. No añadir masking ni afirmar
seguridad por inferencia. Revisión de seguridad separada, no bloqueo de extracción.
No starter-security/configuración de seguridad ni tooling OpenAPI observados;
no crear permitAll/CORS/TLS/autenticación ni Swagger por defecto. Eso no demuestra
ausencia de controles externos del contenedor.

## Tests y calidad — J8-D-004 / J8-D-005

- E-TESTS: JUnit4 `@Before`/`@Test`, Mockito `@Mock`/`@InjectMocks`,
  `MockitoAnnotations.initMocks(this)`, naming `*Test`, tests de servicio con
  colaboradores mockeados y getters/setters. No copiar escenarios/fixtures.
- JaCoCo `0.7.7.201606060606`: prepare-agent en initialize, report en test;
  sin check goal ni umbral declarado. Sonar plugin `3.9.1.2184` conservado.
  Solo se vacían dos properties de exclusiones de dominio; no crear exclusiones
  equivalentes generales ni presentar cobertura de negocio como aprobada.
- Checkstyle **not-present-in-reference / not-applicable**: no plugin, ruleset ni
  scope main/test obligatorio. Ausencia nunca se informa como passed. PMD/SpotBugs
  tampoco observados. No se extrapola D-014 de otra versión.
- Maven, compilación, tests, JaCoCo y Sonar no ejecutados. Checks estáticos no
  sustituyen esos resultados; no se exige ejecutar una herramienta ausente.

## Runtime y entrega — J8-D-006

- WAR/WebLogic: preferencias Spring/SLF4J/Jackson/Guava/Logback, literal
  `com.apache.commons.logging.*` y recurso StaticLoggerBinder conservados sin
  corrección silenciosa; context-root variable. Descriptor Spring beans vacío.
- E-CI: Jenkins usa biblioteca compartida ausente y llamada `springBootPipelineV3`.
  `deployment.ci` conserva ocho keys y evidencia, no valores privados ni etapas
  imaginarias. No hay template ejecutable: la librería contiene todo el pipeline
  y la llamada solicita publicación de configuración local protegida. No inventar
  implementación, modificar biblioteca o automatizar esa publicación.
- E-JNDI: YAML externo con lista `bd_name`/`jndi_name`, valores/cardinalidad
  específicos excluidos. No Docker/Kubernetes/Helm observados; no agregarlos.
- Versiones desconocidas y prerequisitos de repositorio/JNDI/configuración/CI
  permanecen explícitos; no bloquean extracción ni autorizan migrar runtime.

## Estado y trazabilidad

`archetype.yml` contiene inventarios, parámetros, evidencia E-* y cierre individual
de J8-Q-001, J8-Q-002, J8-Q-003, J8-Q-004 y J8-Q-005 por J8-D-002…006.
`decisions.md` conserva J8-D-001 y autorización actual. No hay contradicción de
decisión pendiente. La extracción es completa, pero congelación no autorizada;
backend para Java8/Boot2/WAR/JDBC-JNDI/JUnit4 no probado, runtime y resolución no
verificados. La generación futura exige su propio gate y autorización; nunca
adaptar el baseline a otro backend ni afirmar que este arquetipo ya se compiló.
