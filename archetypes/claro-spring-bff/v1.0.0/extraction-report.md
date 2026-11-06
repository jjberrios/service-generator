# Informe de extracción - claro-spring-bff / 1.0.0

- Operación: extract (destino nuevo, no existía). Fecha: 2026-11-05.
- Referencia (solo lectura, sin cambios): `input/reference/bff-customerbillconfiguration-Feature-300864@ccdb2c4c953`
  (50 archivos hasheados, excluido `application*.properties`; ver `reference-content-baseline.yml`).
- No se inspeccionaron contratos OpenAPI ni exports Sparx. No se leyó configuración protegida.

## Resultado

- 30 archivos de plantilla, 9 parámetros, 10 decisiones (BFF-D-001..010; 005..010 delegadas por el usuario), 0 ambigüedades abiertas (BFF-A-001..006 resueltas).
- `pom.xml` idéntico a la referencia tras renderizar los parámetros; 21 dependencias y 5 plugins inventariados con uso observado por separado.
- Clases verbatim (verificadas por `validate-extraction.py`): seguridad JWT, SecurityConfig, sobre de respuesta, excepciones, ActivityLogger, WsResponseProperties.
- Modificadas por decisión documentada (BFF-D-003): WebClientConfig, ConstanApi, configmap, Dockerfile.
- 20 archivos de la referencia no plantillados (negocio, contrato, tests, jars); listados en `archetype.yml` -> `exclusions`.

## Validación (estática)

- `python .opencode/skills/extract-archetype/scripts/validate_inventory.py archetypes/claro-spring-bff/v1.0.0` -> passed.
- `python archetypes/claro-spring-bff/v1.0.0/validate-extraction.py` -> passed (referencia sin cambios, POM fiel, sin fuga de dominio ni secretos).
- No ejecutado: Maven, Checkstyle (requerido por la referencia: `unverified`), JaCoCo, tests, Docker, CI.

## Pendiente

Revisión humana de las decisiones delegadas BFF-D-005..010, aprobación y, para generar servicios, soporte de backend para el perfil
`jar-springboot3-webmvc-webclient-bff` (hoy inexistente).
