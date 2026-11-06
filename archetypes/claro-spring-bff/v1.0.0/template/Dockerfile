# syntax=docker/dockerfile:1.6

ARG BUILDER_IMAGE=172.19.90.65:6000/docker-private/maven-builder:1.0
ARG RUNTIME_IMAGE=172.19.90.65:6000/docker-private/openjdk-21-runtime:1.18

FROM ${BUILDER_IMAGE} AS builder

WORKDIR /workspace/app

COPY ./pom.xml ./
COPY ./src ./src
COPY ./libs ./libs
COPY ./settings.xml ./settings.xml

RUN ${MAVEN_HOME}/bin/mvn -s /workspace/app/settings.xml \
    clean compile dependency:copy-dependencies \
    -DoutputDirectory=target/dependency \
    -DskipTests

# --runtime--
FROM ${RUNTIME_IMAGE}
WORKDIR /opt/app

# --copiar el jar--
COPY --from=builder /workspace/app/target/classes ./classes
COPY --from=builder /workspace/app/target/dependency ./dependency

EXPOSE 8080

ENTRYPOINT ["java", "-Dspring.config.location=/config/application.properties", "-Doracle.jdbc.timezoneAsRegion=false", "-Duser.timezone=America/Lima", "-cp", "classes:dependency/*", "@@BASE_PACKAGE@@.@@APPLICATION_CLASS@@"]
