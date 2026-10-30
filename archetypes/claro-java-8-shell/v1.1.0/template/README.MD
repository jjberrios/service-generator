# @@ARTIFACT_ID@@

## Descripción

<Descripción funcional del batch: se obtiene de la especificación funcional (Sparx).>

## Tipo de componente

Batch / shell Java 8. No expone endpoints HTTP (ni GET ni POST): se ejecuta como un proceso
(`java -jar`) y se prueba mediante una ejecución (running).

## Pre-requisitos

- Java JDK 8
- Maven 3.x
- Accesos de red a los recursos externos que declare la especificación funcional
- Archivo externo de configuración `@@PROPERTIES_FILE_BASENAME@@.properties` (valores del entorno, fuera del jar)
- Repositorio local `Lib/` con los artefactos no públicos declarados en el POM (por ejemplo `eai:ebsConsultaClavesService-Client:1.0.0`, cliente del servicio de descifrado de credenciales; su jar NO forma parte del arquetipo)
- Endpoint del servicio SOAP de descifrado de credenciales (`ws.ebsConsultaClavesWS.url`), sus timeouts y su código de aplicación, suministrados por el operador en el archivo externo

## Configuración

El archivo externo `@@PROPERTIES_FILE_BASENAME@@.properties` contiene la configuración del entorno
(credenciales cifradas, hosts, rutas, códigos de respuesta). No se versiona con valores reales.
La plantilla de claves está en `config/@@PROPERTIES_FILE_BASENAME@@.properties.j2`.

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
