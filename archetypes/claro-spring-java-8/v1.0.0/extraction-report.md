# Informe de extracción y revisión autorizada

Fecha: 2026-10-20. `claro-spring-java-8/1.0.0`.
Referencia read-only: `input/reference/rest-sb-claro-post-atencion/`.

## Resultado y alcance

La extracción inicial creó esta versión nueva; esta revisión explícitamente
autorizada conserva su identificador y J8-D-001. Se aplican las nuevas instrucciones
humanas H-REV-2026-10-20 mediante J8-D-002…006, solo aquí. La extracción queda
**completa, con baseline basado en SU referencia aprobado por decisiones actuales**;
no congelada, no compilada ni autorizada para generación de un servicio.

Se actualizaron `archetype.yml`, `conventions.md`, `generation-rules.md`,
`decisions.md`, `validate-extraction.py`, este informe y la plantilla initializer.
No se editaron otros arquetipos, AGENTS.md, agentes, ZIP, Word, output o insumos.
No Maven, bases de datos, red ni despliegues; no contratos OpenAPI/Sparx.

## Decisiones y cierre de preguntas

| Pregunta histórica | Decisión actual | Resultado |
|---|---|---|
| J8-Q-001 | J8-D-002 | Java8/Boot2/WAR/JDBC-JNDI/Oracle propios; no imponer JPA/Spring Data/HikariCP |
| J8-Q-002 | J8-D-003 | SLF4J/Logback y patrón local observado; no ActivityLogger/record de otra referencia |
| J8-Q-003 | J8-D-004 | Checkstyle ausente: not-present-in-reference/not-applicable, nunca passed |
| J8-Q-004 | J8-D-005 | POM íntegro con versiones/scopes legados; distinguir declaración/uso, sin podar ni forzar uso |
| J8-Q-005 | J8-D-006 | WAR/WebLogic/carga externa/repositorio/CI de referencia; unknown no obliga a migrar |

No quedan decisiones contradictorias que requieran consulta en estos alcances.
Las preguntas previas y gates importados de otra versión quedaron supersedidos
por autorización humana, no por inferencia. Ninguna decisión ajena fue modificada.
La aprobación técnica no aprueba seguridad, compatibilidad ni congelación.

## Baseline extraído

- Java `1.8`, Boot `2.0.5.RELEASE`, WAR monomódulo y Tomcat provided;
  bootstrap servlet, descriptor WebLogic y configuración externa observada.
- JDBC/JNDI/CallableStatement/ResultSet con helper Oracle de Hibernate; no entidades
  ni repositorios Spring Data. La declaración de APIs JPA no implica su uso.
- SLF4J/Logback INFO, rotación diaria, 30 días, 3GB; JSON Jackson, logger por clase,
  marcadores inicio/fin locales, prefijo método/idTx y logging de errores/tiempos.
  Patrón completo en conventions y runtime.logging, sin copiar utilidad de negocio
  ni crear adaptador. Riesgos de payloads sin masking y fechas con Z literal
  documentados, no corregidos silenciosamente ni aprobados como seguridad.
- JUnit4/Mockito, JaCoCo y Sonar declarados; sin Checkstyle, PMD/SpotBugs,
  wrapper/settings.xml, Docker/Kubernetes observados.
- Referencia: 61 archivos / 51 Java; inventario sin abrir configuración protegida.

### POM: declaración completa frente a uso observado

Conserva 24 dependencias activas, cuatro plugins, 13 properties, parent,
repositorios y ejecuciones. Versiones/scopes/optional no cambian. Las bibliotecas
de pruebas mantienen compile implícito. Gson/Hibernate no tienen necesariamente
versión efectiva igual a propiedades homónimas; effective-pom no resuelto.

`build.dependencyUsage` contiene 24 entradas con evidencia/estado: MVC/Jackson,
JDBC/JNDI y JUnit/Mockito usados; Oracle driver y Tomcat conservados como proveedores
runtime/contenedor declarados; Hibernate cursor helper transitivo observado sin
atribuirlo falsamente a EntityManager. APIs Java EE pueden solaparse con JDK y
contenedor. SOAP/Gson/Commons/APIs JPA/AssertJ/PowerMock/Javassist no tienen uso
directo observado en Java; eso no demuestra inutilidad runtime ni autoriza retirarlos.
Processor declarado sin ejecución comprobada. No se exige usar cada dependencia.

Únicas transformaciones POM: identidad técnica y URL parametrizadas, eliminación
de comentarios de negocio/driver alternativo no activo y valores de dos exclusiones
Sonar de dominio vaciados, sin sustitutas generales. Se valida equivalencia del POM
completo tras normalizar exclusivamente las transformaciones autorizadas.
HELP enlaza Boot 3.2.1-SNAPSHOT pero el POM declara 2.0.5: discrepancia conservada,
POM determina baseline, no implica aprobar una migración.

## Siete plantillas y fidelidad

1. `pom.xml`: baseline íntegro de SU referencia, identidad/repositorio variables.
2. Bootstrap parametrizado bajo `servlet/config`.
3. `ServletInitializer.java`: carga externa, concatenación original restaurada;
   no `new File(parent, child)` que normalice comportamiento. La raíz de entorno
   requiere separador final; no se corrigió caso de propiedad ausente.
4. `WEB-INF/weblogic.xml`: context-root variable, preferencias literales conservadas.
5. `WEB-INF/dispatcherServlet-servlet.xml`: descriptor beans vacío.
6. `config/logback.xml`: patrón observado, directorio/nombre parametrizados.
7. `.gitignore`: exclusiones técnicas observadas.

La URL de repositorio admite HTTP/HTTPS, no fuerza upgrade ausente de la referencia;
host privado y credenciales nunca son defaults. Versiones de Maven, distribución
JDK y WebLogic permanecen unknown. No copiar SQL, entidades, DTOs, endpoints,
procedimientos, mappings, escenarios o utilidades de validación del dominio.

### Jenkins evaluado

E-CI conserva evidencia de delegación a shared library ausente. `deployment.ci`
registra llamada observada y las ocho keys de parámetros, no sus valores privados.
No se incluye template ejecutable: toda implementación reside en la biblioteca
no suministrada y la llamada solicita publicación de configuración local protegida.
Una llamada parametrizada no establecería comportamiento seguro/verificado.
No inventar stages/biblioteca ni publicar ese archivo. La exclusión no bloquea
extracción; la disponibilidad de CI real es prerequisito externo de ejecución.

## Validación estática reproducible

```text
python archetypes/claro-spring-java-8/v1.0.0/validate-extraction.py
```

El validador solo lee archivos permitidos, no ejecuta herramientas de build ni
escribe en la referencia. La revisión ejecutó el validador antes de editar y al
final. No se usa una aprobación de Checkstyle ficticia como requisito.
Durante la edición detectó una indentación YAML incorrecta; se corrigió y la
ejecución final pasó sin fallos de los chequeos estáticos declarados.

| Comprobación | Resultado |
|---|---|
| YAML sin claves duplicadas | Pasó |
| Inventario template, incluidos ocultos | 7/7 exactos |
| Parámetros / affectedFiles / uso en rutas | 11/11 exactos |
| Render de muestra/regex en memoria | Sin tokens restantes; HTTP/HTTPS y rechazo userinfo/query comprobados |
| XML original/renderizado | 4/4 bien formados, sin validación XSD remota |
| Fidelidad Logback/descriptors | Estructura completa equivalente salvo parámetros autorizados |
| Java renderizado | 2/2 estructura paquete/clase/delimitadores, NO parseo ni compilación |
| Dependencias directas vs referencia/inventario | 24/24, versiones/scopes/optional exactos |
| Plugins/configuraciones/ejecuciones | 4/4 exactos |
| Properties POM | 13/13, solo dos valores Sonar de dominio vaciados |
| POM completo, parent/repositories/profiles | Equivalente salvo transformaciones autorizadas |
| Uso de dependencias separado de declaración | 24 entradas; scan de 51 Java; atribución transitiva no resuelta explícita |
| Evidencia | 21 localizaciones verificadas; refs de plantillas/inventarios válidas |
| Decisiones/preguntas/ownership | 6 decisiones, 5 preguntas resueltas, 0 ambigüedades de decisión pendientes |
| Initializer y logging | Concatenación original y patrón Java8 de referencia; sin helper inventado |
| CI | Ocho keys frente a fuente; sin template/pipeline inventado |
| Checkstyle | not-applicable / not-present-in-reference; plugin/configuración no añadidos |
| Fuga identidad/dominio en template | 0 coincidencias dirigidas |
| Secretos/userinfo/claves privadas/direcciones privadas | 0 coincidencias heurísticas en artefactos revisados |
| Integridad permitida de input/reference completo | 194 registros contenido/tamaño/mtime sin cambios |
| Inventario de rutas input/reference | 199 rutas sin altas/bajas/cambios |

Patrones de búsqueda del propio validador contienen firmas de dominio, no valores
secretos; no son fugas del template. Búsqueda heurística no certifica ausencia
absoluta de secretos. Identidades en documentación son evidencia, no defaults.

## Integridad y configuración protegida

Se reutiliza la instantánea inicial persistida: contenido permitido SHA-256,
tamaño/mtime e inventario de rutas, confirmados antes y después de revisión.
Digests y alcance en `archetype.yml`. Ninguna operación de escritura bajo
`input/reference/`. `application*.properties` nunca se abrió/leyó/analizó/reportó/
comparó/copió/hasheó; tampoco se comparó su metadata. No se certifica integridad
del contenido protegido mediante hashes; hacerlo violaría la prohibición.
La comprobación de integridad es del alcance permitido, no de ese contenido.

## Restricciones reales restantes y congelación

- Maven/resolución/effective-pom, compilación, JUnit/Mockito, JaCoCo y Sonar:
  **no ejecutados**. Checkstyle **no aplicable**, no pasado ni gate obligatorio.
- Runtime/arranque/compatibilidad no verificados; versiones de servidor/toolchain
  no documentadas permanecen unknown sin bloquear extracción ni requerir otro stack.
- Repositorio/JNDI/configuración externa y biblioteca CI son prerequisitos de
  ejecución por establecer, no implementaciones inventadas.
- Backend generador no probado para Java8/Boot2/WAR/JDBC-JNDI/JUnit4; no adaptar
  este arquetipo al perfil de otro materializador. Ningún servicio fue generado.
- Riesgos del legado/logging documentados, sin aprobación implícita de seguridad.
- **Congelación no autorizada**: extracción completa y decisiones aplicadas no
  equivalen a aprobación de congelación o readiness ejecutable del generador.

Sin contradicción auténtica pendiente de decisión en esta revisión. Contratos/
Sparx futuros no inspeccionados ni comportamiento inventado. Siguiente fase requiere
su propia autorización y gates; este informe no los concede.
