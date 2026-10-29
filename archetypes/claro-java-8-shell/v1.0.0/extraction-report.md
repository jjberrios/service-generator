# Informe de extracción — claro-java-8-shell / 1.0.0

Fecha: 2026-10-29. Operación: extracción inicial (destino nuevo). Referencia (solo lectura):
`input/reference/SH_ObtenerTrasladarArchivosMTC`. Estado: extracción completa; **congelado**;
`generationEnabled: true`; 10 decisiones aprobadas y preguntas SH-Q-001 a 012 resueltas
por la instrucción humana de seguir enteramente la referencia (ver `decisions.md`).
Los artefactos externos ausentes y la compatibilidad siguen sin verificarse.

## Resumen del proyecto de referencia

- Batch/shell Java 8 (jar ejecutable, `main`), Spring 3.1.0 (XML + component-scan), log4j 1.2,
  jsch (SFTP), JUnit4/Mockito 2/AssertJ, JaCoCo 0.8.2, Sonar, plugins jar/shade/dependency/resources.
- Sin endpoints HTTP; se ejecuta con `java -Dproperties=<archivo> -jar <jar> <idTransaccion>`
  (comando derivado, sin script lanzador) y se prueba con un running.
- Sin persistencia implementada, sin Checkstyle de build, sin Docker/K8s/Jenkinsfile.

## Resultado

| Elemento | Cantidad |
|---|---|
| Archivos de la referencia (todos con disposición) | 51 |
| Archivos del template | 17 |
| Utilitarios/excepciones declarados en `generation.utilities` | 9 |
| Plantillas de configuración en `generation.configuration` | 2 |
| Parámetros (todos usados) | 9 |
| Dependencias / plugins inventariados | 14 / 7 |
| Decisiones aprobadas / propuestas / preguntas pendientes | 10 / 0 / 0 |

## Validación estática (`validate-extraction.py`)

Pasa: YAML con claves únicas; template == inventario; parámetros usados exactamente en
`affectedFiles`; XML bien formado (original y renderizado); estructura Java renderizada;
11 plantillas idénticas a la referencia tras el render de tokens; archivos mixtos
(Constantes, PropertiesExterno, SFTPConnectionManager) solo con eliminaciones; POM idéntico
salvo la parametrización autorizada y la eliminación de patrones Sonar concretos;
dependencias/plugins == POM; uso de dependencias vs imports; cobertura de la referencia;
trazabilidad decisiones; sin fuga de dominio/integración ni secretos/IP; referencia sin
cambios (hash de 49 archivos permitidos + inventario de rutas).

## No verificado (honestamente)

Maven (compilación, `package`, resolución de `Lib/`), pruebas, JaCoCo, Sonar, compatibilidad
Spring 3.1.0 con bytecode Java 8 (SH-Q-010), ejecución real del jar y compilación Java
del nuevo backend. Checkstyle no aplica. El backend batch implementa un IR SFTP acotado;
sus pruebas Python sintéticas pasan, sin afirmar pruebas Maven/runtime.

## Cierre y alcance habilitado (SH-D-010)

La instrucción «Porque?, termina el arquetipo.» autoriza finalizar, congelar y habilitar
esta versión. El planificador/materializador conserva el baseline de referencia y
soporta únicamente el IR SFTP cerrado documentado; SOAP/descifrado, persistencia y
pasos no soportados bloquean la generación. No hay interpretación automática de
prosa Sparx. Cada destino requiere revisión semántica y autorización propias.

Evidencia del backend: suite completa de materialización, 258 pruebas ejecutadas,
resultado OK con 1 omitida por falta de JSch local; prueba focalizada del perfil,
16 pruebas, 15 satisfactorias y 1 omitida. El parseo de sintaxis Java 8 pasa;
no equivale a compilar, ejecutar JUnit ni probar el jar. No se ejecutó Maven.

Revisión de estilo: el servicio generado usa `@Service`, interfaz `run(String,String)`,
inyección de `PropertiesExterno`, log4j por clase, prefijo de transacción,
`MessageFormat` con constantes de inicio/fin/tiempo y cierre SFTP en `finally`,
como el servicio de referencia. Conserva utilitarios, excepciones, contexto XML y
plantilla de configuración. La integración de descifrado concreta no se trasplanta.
