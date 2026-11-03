# @@ARTIFACT_ID@@

## Descripción

{{DESCRIPTION}}

## Tipo de componente

Batch / shell Java 8. No expone endpoints HTTP (ni GET ni POST): se ejecuta como un proceso
(`java -jar`) y se prueba mediante una ejecución (running).

## Pre-requisitos

- Java JDK 8
- Maven 3.x
- Accesos de red a los servidores SFTP/FTP indicados en la configuración
- Archivo externo de configuración `@@PROPERTIES_FILE_BASENAME@@.properties` (valores del entorno, fuera del jar)
{{PREREQUISITES}}

## Configuración

El archivo `config/@@PROPERTIES_FILE_BASENAME@@.properties` se entrega con todas las claves y valores vacíos;
el operador completa la configuración del entorno (credenciales, hosts, rutas, códigos de respuesta).
No se versiona con valores reales. Claves que debe definir:

{{PROPERTIES}}

## Construcción

```bash
mvn clean package
```

Genera `target/@@ARTIFACT_ID@@-@@PROJECT_VERSION@@.jar` (jar sombreado con `maven-shade-plugin`)
y copia las dependencias en `target/LIB/`.

## Ejecución

```bash
java -Dproperties=<ruta>/@@PROPERTIES_FILE_BASENAME@@.properties -jar @@ARTIFACT_ID@@-@@PROJECT_VERSION@@.jar <idTransaccion>
```

Clase principal: `@@BASE_PACKAGE@@.@@MAIN_CLASS@@`.

## Parámetros

- **idTransaccion** (argumento 0, obligatorio): identificador de la transacción para trazabilidad.
- **properties** (propiedad de la JVM): ruta del archivo externo de configuración.

## Códigos de respuesta

Los códigos y mensajes (`idf0`, `idf1`, `idt1`, `idt2`, `idt3`) se leen de la configuración externa y se registran en el log.
