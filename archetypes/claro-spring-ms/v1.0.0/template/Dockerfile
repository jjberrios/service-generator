# syntax=docker/dockerfile:1.6

ARG BUILDER_IMAGE=__BUILDER_IMAGE__
ARG RUNTIME_IMAGE=__RUNTIME_IMAGE__

FROM ${BUILDER_IMAGE} AS builder
WORKDIR /workspace/app

COPY ./pom.xml ./
COPY ./src ./src
COPY ./settings.xml ./settings.xml

RUN ${MAVEN_HOME}/bin/mvn -s /workspace/app/settings.xml \
    clean compile dependency:copy-dependencies \
    -DoutputDirectory=target/dependency \
    -DskipTests

FROM ${RUNTIME_IMAGE}
WORKDIR /opt/app

COPY --from=builder /workspace/app/target/classes ./classes
COPY --from=builder /workspace/app/target/dependency ./dependency

EXPOSE __CONTAINER_PORT__

ENTRYPOINT ["java", "-Dspring.config.location=__SPRING_CONFIG_LOCATION__", "-Duser.timezone=__TIME_ZONE__", "-cp", "classes:dependency/*", "__BASE_PACKAGE__.__APPLICATION_CLASS__"]
