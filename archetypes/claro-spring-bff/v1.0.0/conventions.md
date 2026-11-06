# Convenciones - claro-spring-bff / 1.0.0

Estado: extracción completa, pendiente de revisión (ver `decisions.md`). Todo lo siguiente proviene de la referencia
`input/reference/bff-customerbillconfiguration-Feature-300864@ccdb2c4c953` y no es un estándar corporativo por sí mismo.

## Plataforma (BFF-D-002)

- Java 21, Spring Boot 3.4.1 (`spring-boot-starter-parent`), empaquetado JAR, namespace `jakarta`, Tomcat embebido.
- Stack: WebMVC (controladores) + WebFlux (`WebClient` para integraciones), Bean Validation, Actuator, springdoc 2.7.0, Spring Security,
  jjwt 0.11.5, Lombok, logstash-logback-encoder, micrometer-tracing-bridge-brave.
- POM completo preservado (21 dependencias, 5 plugins, repositorios `${repository-url}`, perfil `local` activo por defecto).
  Varias dependencias están declaradas sin uso observado (`archetype.yml` -> `build.dependencyUsage`); no se podan.
- Persistencia: **no presente en la referencia**. No se asume JPA, JDBC ni repositorios.

## Estructura de paquetes

Raíz = paquete de la clase de aplicación (en la referencia termina en `.support`):
`client`, `configuration` (+ `security`, `swagger`), `controller` (+ `impl`), `dto.request`, `dto.response`, `exception`,
`security.filter`, `security.service(.impl)`, `service` (+ `impl`), `utils`.
Plantillas: client (fábrica WebClient), configuration, dto.response (sobre), exception, security, utils. El resto lo generan OpenAPI/Sparx.

## Estilo de código observado (`generation.style`)

- Constantes: `utils.ConstanApi` (clase final, constructor privado, `public static final String`, secciones comentadas con `// ====`).
  Códigos HTTP como String (`CODE_404`), tokens de error (`NOT_FOUND`, `TIMEOUT`, `UNAVAILABLE`, `INTERNAL_ERROR`, `CONFLICT`),
  estados (`STATUS_*`), tipos (`TYPE_*`), marcadores de log y nombres de actividad `ACT<n>_<NOMBRE>`.
  Literales: parcialmente externalizados; mensajes de log y algunos textos de error van inline (no se impone otro estilo).
- Propiedades externas: `@Value("${key}")` por constructor; catálogo `ws.codigoId*/mensajeId*/detailId*` en `WsResponseProperties`;
  por integración `<prefijo>.baseurl`, `<prefijo>.url`, `<prefijo>.rest-client.connect-timeout|read-timeout` (segundos);
  `security.jwt.secret-key`. Los valores viven en el ConfigMap (`/config/application.properties`), nunca en código.
- WebClient: un bean `<integración>WebClient` por integración, inyectado con `@Qualifier`; `onStatus` traduce 404/409/504/5xx a
  `BusinessException(ConstanApi.<TOKEN>)`; cabeceras salientes aplicadas con un mapper.
- Excepciones: `BusinessException extends RuntimeException`; `GlobalExceptionHandler` (`@ControllerAdvice`) mapea por contenido del mensaje
  a `ErrorResponse` usando el catálogo `ws.*`.
- Clases: interfaz + `Impl` para controlador y servicio; DTO de respuesta con Lombok (`@Data @Builder @NoArgsConstructor @AllArgsConstructor`),
  records para datos de cabecera; retorno reactivo `Mono<ResponseEntity<ApiResponseData<T>>>`.
- Logging: SLF4J por clase; `ActivityLogger.inicioActividad/finActividad` alrededor de cada actividad; `logContenido` serializa cuerpos
  (sin enmascaramiento: riesgo de revisión, no se altera). Prefijo de transacción vacío en la referencia (BFF-D-010, riesgo de revisión).
- Checkstyle (calidad requerida): `src/main/resources/checkstyle.xml`, plugin 3.3.1 en `validate`, incluye tests; `MagicNumber` con lista blanca,
  `UnusedImports`, `NeedBraces`, `Indentation` 4, línea máx. 250.
- Tests observados: JUnit 5 + Mockito (`mock()` en `@BeforeEach`), stubs de `ExchangeFunction` para WebClient, `Mono.block()`,
  datos de prueba en constantes, clases `<Clase>Test`. JaCoCo 80 % INSTRUCTION por paquete con exclusión por capas.

## Runtime y entrega

- Dockerfile multi-etapa (imagen builder y runtime corporativas), lanzamiento `java -cp classes:dependency/*`, puerto 8080,
  `-Dspring.config.location=/config/application.properties`, `-Duser.timezone=America/Lima`.
- Kubernetes: Deployment con RollingUpdate, `securityContext` restringido, ConfigMap montado en `/config`, etiquetas ArgoCD.
  `ExternalSecret.yml.j2` está vacío en la referencia.
- CI: `MicroserviciosPipeline(nombreDeCompilado, nombreVault)` de la biblioteca compartida (no disponible, comportamiento no verificado).
- `application*.properties` es configuración local protegida: no se lee, copia ni genera.

## Baselines temporales / no verificados

BFF-D-004 era temporal y quedó resuelto por BFF-D-005; BFF-D-005..010 son decisiones delegadas por el usuario. Maven, Checkstyle, JaCoCo, tests, Docker y CI no se ejecutaron. Ambigüedades BFF-A-001..006 resueltas por BFF-D-005..010.
