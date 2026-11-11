# Service Generator

Generador de microservicios Java/Spring a partir de tres fuentes:

- **Arquetipo:** estructura del proyecto y convenciones técnicas.
- **OpenAPI/Swagger:** endpoints, solicitudes y respuestas.
- **Sparx Enterprise Architect:** flujos de negocio e integraciones.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `.opencode/` | Agentes, skills y herramientas de automatización. |
| `archetypes/` | Arquetipos versionados. |
| `input/contracts/` | Contratos OpenAPI/Swagger. |
| `input/sparx/` | Exportaciones HTML de Sparx. |
| `input/reference/` | Proyectos de referencia para extraer arquetipos. |
| `.factory/` | Estado y artefactos intermedios por servicio. |
| `output/` | Microservicios generados. |
| `reports/` | Reportes de inconsistencias. |

## Generar un microservicio

1. Abre el proyecto en OpenCode.
2. Coloca el contrato y la exportación Sparx en sus carpetas de entrada.
3. Invoca el agente con el servicio que quieres generar:

```text
@service-generator

Target service: dom-example-service
Archetype: archetypes/<nombre>/<version>
OpenAPI: input/contracts/dom-example-service.yml
Sparx: input/sparx/PROYECT/

Generate the complete functional service.
```

El arquetipo se elige siempre de forma explícita (o se reanuda desde el checkpoint
del servicio); no existe un arquetipo por defecto. Cada arquetipo declara su
perfil de generación y solo se genera con perfiles que tengan backend soportado
(`archetype_contract.py`); un perfil sin backend produce un error técnico, no una
pregunta de negocio.

Servicios sin API HTTP (por ejemplo, tipo shell/batch) no tienen OpenAPI: se
indica solo `Target service`, `Archetype` y `Sparx`, y la autoridad Sparx se
resuelve con `--non-http`. Ver
`.opencode/skills/materialize-full-service/docs/batch-shell-contract.md`.

El agente comprueba la consistencia entre las fuentes y se detiene si necesita
una decisión. No inventa reglas de negocio. `workspace_cli.py lifecycle <servicio>`
muestra por separado los estados del arquetipo y del servicio (aprobado,
congelado, habilitado, generado, completo, verificado). La ejecución de Maven, el
acceso a bases de datos y los despliegues requieren autorización explícita
(las pruebas oficiales con Maven solo corren con
`SERVICE_GENERATOR_AUTHORIZED_MAVEN_TESTS=1`).

## Crear un arquetipo

Coloca el proyecto de referencia en `input/reference/` y solicita una extracción
con un nombre y una versión nuevos:

```text
@archetype-extractor

Extrae un nuevo arquetipo desde input/reference/mi-proyecto.
Destino: archetypes/mi-arquetipo/v1.0.0

Conserva las convenciones técnicas y excluye la lógica de negocio y los secretos.
```

El agente no modifica el proyecto de referencia ni sobrescribe versiones
existentes. Las ambigüedades requieren tu decisión y quedan registradas en
`decisions.md`. Revisa y aprueba el arquetipo antes de usarlo; su extracción no
garantiza compatibilidad con el generador.

## Comparar inconsistencias entre Sparx y Swagger

Ejecuta la auditoría de forma independiente, sin generar un microservicio:

```text
@sparx-swagger-validator

Target service: dom-example-service
OpenAPI: input/contracts/dom-example-service.yml
Sparx: input/sparx/PROYECT/
```

El agente compara ambas fuentes sin modificarlas ni corregir diferencias.
Entrega:

- **Reporte Word:** `reports/inconsistencias/dom-example-service_sparx_swagger.docx`.
- **Registro de hallazgos:** `reports/inconsistencias/registros/dom-example-service/findings.yml`.

Distingue contradicciones verificadas, diferencias documentales y aspectos no
verificados. El reporte no autoriza por sí solo la generación del servicio.

Consulta [AGENTS.md](AGENTS.md) para las reglas completas del proyecto.

## Operación portable con OpenCode V2

`opencode.jsonc` contiene la política local del repositorio; no requiere editar la
configuración global ni rutas de usuario. Las lecturas ordinarias y búsquedas
acotadas no piden confirmación; secretos, certificados, claves y
`application*.properties` permanecen excluidos. La referencia solo se consulta
por el extractor para el proyecto seleccionado, nunca durante generación normal.

Antes de comenzar, revisa **sin modificar archivos** `AGENTS.md`, los agentes y
skills de la fase, la ruta del contrato/exportación y el checkpoint
`.factory/services/<servicio>/service-generation-state.yml` si existe. Comprueba
que Python y las dependencias documentadas estén disponibles; no instales nada
automáticamente. Antes de compartir el repositorio, `python -B tools/doctor.py`
comprueba Python, PyYAML, aceleración opcional, configuración del proyecto y
fronteras de agentes en modo solo lectura. No instala, no accede a red ni lee
configuración global; no garantiza los permisos efectivos fusionados del runtime
ni sustituye los gates del servicio.

Ejecuta los scripts desde la raíz con rutas relativas y `/`: la forma canónica es
`python -B .opencode/skills/<skill>/scripts/<script>.py ...`, o `py -3 -B` en
Windows. Solo los comandos ya autorizados tienen esas variantes; shell sigue
requiriendo aprobación para otros comandos. Los ejemplos históricos con `python`
no implican permiso para Python arbitrario.

La solicitud de servicio completo incluye el análisis e interpretación necesarios
del servicio, sin confirmaciones entre fases. No sustituye revisiones, autorización
de reanudación ni protección de cambios manuales. Solo una delegación explícita
permite registrar decisiones mediante `delegated_review.py`; sobrescrituras y
reatestaciones históricas siguen siendo manuales. Maven, BD y despliegue requieren
autorización separada; no se ejecuta regresión global durante generación normal.

Los permisos de agente se añaden al final de los del proyecto (última coincidencia).
`glob` autoriza patrones y `grep` expresiones, no directorios: delimita las búsquedas
y excluye archivos sensibles. Un bloqueo de lectura no protege contra shell; no
debe eludirse con comandos. El paralelismo exige salidas disjuntas, un único escritor
canónico; serializa llamadas del mismo servicio que escriban artefactos compartidos,
checkpoint, manifiestos o revisiones. Invocaciones aisladas no autorizan dos escritores.

Para `claro-spring-ms/1.0.1`, D-015 permite únicamente que el materializador cree
`application.properties` ausente con placeholders `${ENV}`; nunca leer, comparar
ni sobrescribir configuración existente. No autoriza edición directa del agente.

Referencias V2: [permisos](https://opencode.ai/docs/permissions),
[configuración](https://opencode.ai/docs/config).
