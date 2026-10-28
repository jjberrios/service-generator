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
OpenAPI: input/contracts/dom-example-service.yml
Sparx: input/sparx/PROYECT/

Generate the complete functional service.
```

El agente reutiliza el arquetipo aprobado, comprueba la consistencia entre las
fuentes y se detiene si necesita una decisión. No inventa reglas de negocio.
La ejecución de Maven, el acceso a bases de datos y los despliegues requieren
autorización explícita.

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
