#!/usr/bin/env python3
"""Build a deterministic scaffold or full implementation plan from approved inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


SERVICE_SPEC = Path(".factory/service-spec.yml")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'service-workspace' / 'scripts'))
from generation_context import resolve_archetype
PLAN_PATH = Path(".factory/implementation-plan.yml")
SCAFFOLD_ARTIFACTS = {
    "template/.gitattributes", "template/.gitignore", "template/.mvn/wrapper/maven-wrapper.properties",
    "template/Dockerfile", "template/config/ExternalSecret.yml.j2", "template/config/configmap.yml.j2",
    "template/config/deployment.yml.j2", "template/mvnw", "template/mvnw.cmd", "template/pom.xml",
    "template/settings.xml", "template/src/main/java/__BASE_PACKAGE_PATH__/__APPLICATION_CLASS__.java",
    "template/src/main/java/__BASE_PACKAGE_PATH__/configuration/swagger/SwaggerConfig.java",
    "template/src/main/java/__BASE_PACKAGE_PATH__/configuration/security/SecurityConfig.java",
    "template/src/main/java/__BASE_PACKAGE_PATH__/security/filter/JwtRequestFilter.java",
    "template/src/main/java/__BASE_PACKAGE_PATH__/security/service/JwtValidatorService.java",
    "template/src/main/java/__BASE_PACKAGE_PATH__/security/service/impl/JwtValidatorServiceImpl.java",
    "template/src/main/resources/application.properties", "template/src/main/resources/checkstyle.xml",
    "template/src/main/resources/logback.xml",
}
BLOCKED_COMPONENTS = [
    ("src/main/java/{packagePath}/controller/impl/*Controller.java", "Behavior-bearing controller implementations require operation behavior."),
    ("src/main/java/{packagePath}/service/**", "Service behavior, sequencing, and outcomes are unresolved."),
    ("src/main/java/{packagePath}/client/**", "Integration endpoints and client behavior are not established."),
    ("src/main/java/{packagePath}/repository/**", "Persistence operations and repository semantics are unresolved."),
    ("src/main/java/{packagePath}/entity/**", "JPA/entity behavior and field mappings are not established."),
    ("src/main/java/{packagePath}/model/**", "Domain/entity fields and persistence mappings are not established."),
    ("src/main/java/{packagePath}/port/**", "Port existence and semantics are not established by evidence."),
    ("src/main/java/{packagePath}/dto/mapper/**", "Request-to-domain and persistence mappings are unsupported."),
    ("src/main/resources/db/**", "SQL and schema behavior are not established."),
    ("src/test/java/{packagePath}/service/**", "Business-level test behavior and outcomes are unresolved."),
]
JAVA_KEYWORDS = {"abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const",
                 "continue", "default", "do", "double", "else", "enum", "extends", "final", "finally", "float",
                 "for", "goto", "if", "implements", "import", "instanceof", "int", "interface", "long", "native",
                 "new", "package", "private", "protected", "public", "return", "short", "static", "strictfp",
                 "super", "switch", "synchronized", "this", "throw", "throws", "transient", "try", "void",
                 "volatile", "while", "true", "false", "null"}


class PlanError(Exception):
    """Raised when an authoritative input is missing, unsafe, or inconsistent."""


def yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise PlanError("PyYAML must already be installed; dependencies are not installed dynamically.") from exc
    return yaml


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_yaml(path: Path, root: Path, yaml: Any) -> tuple[Any, bytes]:
    resolved = path.resolve()
    roots = [root.resolve()] + [child.resolve() for child in root.iterdir() if child.is_dir() and (child.is_symlink() or os.path.isjunction(child))]
    if path.is_symlink() or not path.is_file() or not any(resolved.is_relative_to(base) for base in roots):
        raise PlanError(f"Missing or unsafe input: {path.as_posix()}")
    payload = path.read_bytes()
    try:
        value = yaml.load(payload, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise PlanError(f"Invalid YAML input: {path.as_posix()}") from exc
    return value or {}, payload


def dump_yaml(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def pascal(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    result = "".join(part[:1].upper() + part[1:] for part in parts)
    if not result or result[0].isdigit():
        result = "Service" + result
    return result


def valid_kebab(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value))


def technical_identifier(value: str) -> str:
    """Lowercase kebab-case technical identifier of a service name (dom-cpeRequest -> dom-cpe-request); lowercase names are unchanged."""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", value)
    return re.sub(r"-{2,}", "-", text).lower()


def archetype_fingerprint(path: Path) -> str:
    from artifact_integrity import archetype_hashes, IntegrityError
    try:
        hashes = archetype_hashes(path)
    except (IntegrityError, ValueError, OSError) as error:
        raise PlanError(f"Invalid archetype fingerprint: {error}") from error
    return sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode())


def field_java_type(schema: dict[str, Any]) -> str:
    resolved = schema.get("resolved") if isinstance(schema.get("resolved"), dict) else schema
    source = schema.get("source") if isinstance(schema.get("source"), dict) else {}
    ref = source.get("$ref")
    if ref:
        return pascal(str(ref).rsplit("/", 1)[-1])
    kind = resolved.get("type")
    if kind == "array":
        item = resolved.get("items") or {}
        return f"List<{field_java_type(item)}>"
    if kind == "integer":
        return "Long" if resolved.get("format") == "int64" else "Integer"
    return {"string": "String", "number": "BigDecimal", "boolean": "Boolean",
            "object": "Object"}.get(kind, "Object")


def constraint_annotations(schema: dict[str, Any], required: bool) -> list[str]:
    value = schema.get("resolved") if isinstance(schema.get("resolved"), dict) else schema
    annotations = []
    if required:
        annotations.append("@NotNull")
    fmt = value.get("format")
    if fmt == "email":
        annotations.append("@Email")
    if "minLength" in value or "maxLength" in value:
        args = []
        if "minLength" in value:
            args.append(f"min = {value['minLength']}")
        if "maxLength" in value:
            args.append(f"max = {value['maxLength']}")
        annotations.append("@Size(" + ", ".join(args) + ")")
    if "minimum" in value:
        annotations.append(f"@DecimalMin(\"{value['minimum']}\")")
    if "maximum" in value:
        annotations.append(f"@DecimalMax(\"{value['maximum']}\")")
    if value.get("exclusiveMinimum") is True and "minimum" in value:
        annotations.append(f"@DecimalMin(value = \"{value['minimum']}\", inclusive = false)")
    elif isinstance(value.get("exclusiveMinimum"), (int, float)) and not isinstance(value.get("exclusiveMinimum"), bool):
        annotations.append(f"@DecimalMin(value = \"{value['exclusiveMinimum']}\", inclusive = false)")
    if value.get("exclusiveMaximum") is True and "maximum" in value:
        annotations.append(f"@DecimalMax(value = \"{value['maximum']}\", inclusive = false)")
    elif isinstance(value.get("exclusiveMaximum"), (int, float)) and not isinstance(value.get("exclusiveMaximum"), bool):
        annotations.append(f"@DecimalMax(value = \"{value['exclusiveMaximum']}\", inclusive = false)")
    if "pattern" in value:
        annotations.append(f"@Pattern(regexp = {json.dumps(str(value['pattern']), ensure_ascii=False)})")
    if "minItems" in value or "maxItems" in value:
        args = []
        if "minItems" in value:
            args.append(f"min = {value['minItems']}")
        if "maxItems" in value:
            args.append(f"max = {value['maxItems']}")
        annotations.append("@Size(" + ", ".join(args) + ")")
    return annotations


def collect_models(service: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    models: dict[str, dict[str, Any]] = {}
    operation_refs: dict[str, set[str]] = {}

    def visit(node: Any, operation: dict[str, Any], pointer: str, required_by_parent: bool = False) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, operation, f"{pointer}/{index}")
            return
        if not isinstance(node, dict):
            return
        source = node.get("source") if isinstance(node.get("source"), dict) else {}
        ref = source.get("$ref")
        resolved = node.get("resolved") if isinstance(node.get("resolved"), dict) else None
        if ref and resolved is not None:
            name = pascal(str(ref).rsplit("/", 1)[-1])
            operation_refs.setdefault(operation["operationId"], set()).add(name)
            usage = "request" if "/requestBody" in pointer else "response" if "/responses/" in pointer else "contract"
            required = set(resolved.get("required") or [])
            properties = resolved.get("properties") or {}
            fields = []
            for field_name, field_schema in properties.items():
                field_resolved = (field_schema.get("resolved")
                                  if isinstance(field_schema.get("resolved"), dict) else field_schema)
                fields.append({
                    "name": field_name,
                    "javaType": field_java_type(field_schema),
                    "required": field_name in required,
                    "validationAnnotations": constraint_annotations(field_schema, field_name in required),
                    "declaredConstraints": {key: field_resolved[key] for key in (
                        "type", "format", "enum", "minLength", "maxLength", "minimum", "maximum",
                        "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "pattern", "minItems",
                        "maxItems", "uniqueItems", "minProperties", "maxProperties", "const")
                        if key in field_resolved},
                    "serializationMetadata": {key: field_resolved[key]
                                              for key in ("format", "enum") if key in field_resolved},
                    "traceability": f"{pointer}/resolved/properties/{str(field_name).replace('~', '~0').replace('/', '~1')}",
                })
            is_enum = resolved.get("type") == "string" and isinstance(resolved.get("enum"), list)
            models.setdefault(name, {
                "name": name,
                "kind": "enum" if is_enum else "contract-model",
                "javaTargetType": name,
                "sourceSchema": str(ref),
                "sourceOperations": [],
                "requestResponseScope": [],
                "fields": [] if is_enum else fields,
                "enumValues": resolved.get("enum", []) if is_enum else [],
                "requiredFields": sorted(required),
                "traceability": f"{pointer}/resolved",
            })
            model = models[name]
            if model.get("sourceSchema") != ref:
                raise PlanError(f"Distinct contract schema references resolve to the same Java type name: {ref}")
            if operation["operationId"] not in model["sourceOperations"]:
                model["sourceOperations"].append(operation["operationId"])
            if usage not in model["requestResponseScope"]:
                model["requestResponseScope"].append(usage)
        for key, child in node.items():
            if key != "source":
                token = str(key).replace("~", "~0").replace("/", "~1")
                visit(child, operation, f"{pointer}/{token}")

    for index, operation in enumerate(service.get("operations") or []):
        visit(operation.get("contract") or {}, operation, f"/operations/{index}/contract")
    return [models[key] for key in sorted(models)], operation_refs


def input_pointer_map(operations: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    return {(str(operation.get("operationId")), str(operation.get("method"))): f"/operations/{index}"
            for index, operation in enumerate(operations)}


def operation_api_entry(operation: dict[str, Any], index: int, refs: set[str]) -> dict[str, Any]:
    contract = operation.get("contract") or {}
    parameters = contract.get("parameters") or {}
    body = contract.get("requestBody")
    responses = contract.get("responses") or {}
    return {
        "operationId": operation.get("operationId"),
        "method": operation.get("method"),
        "path": operation.get("path"),
        "javaMethod": str(operation.get("operationId") or "operation"),
        "summary": contract.get("summary"),
        "description": contract.get("description"),
        "deprecated": contract.get("deprecated"),
        "requestBodyPresent": body is not None,
        "requestParameters": parameters,
        "responseStatuses": sorted(map(str, responses), key=lambda value: (len(value), value)),
        "modelTypes": sorted(refs),
        "source": ".factory/service-spec.yml",
        "traceability": f"/operations/{index}/contract",
    }


def parameter_value(parameter: dict[str, Any], service: dict[str, Any], archetype: dict[str, Any]) -> tuple[Any, str | None, str | None]:
    name = parameter.get("name")
    svc = service.get("service") or {}
    if name == "service_name" and svc.get("name"):
        return technical_identifier(svc["name"]), ".factory/service-spec.yml#/service/name (lowercase-kebab technical identifier)", None
    if name == "artifact_id" and valid_kebab(technical_identifier(str(svc.get("name") or ""))):
        return technical_identifier(svc["name"]), ".factory/service-spec.yml#/service/name (valid lowercase-kebab artifact identifier)", None
    if name == "application_class" and svc.get("name"):
        return pascal(str(svc["name"])) + "Application", ".factory/service-spec.yml#/service/name (deterministic UpperCamelCase + Application)", None
    quality = archetype.get("quality") or {}
    if name == "jacoco_exclusions":
        defaults = (quality.get("jacoco") or {}).get("default_exclusions", [])
        if any("__BASE_PACKAGE_PATH__" in str(value) for value in defaults):
            return None, None, "JaCoCo default exclusions include the unresolved base package path."
        return [str(value).replace("__APPLICATION_CLASS__", pascal(str(svc.get("name") or "")) + "Application")
                for value in defaults], "archetype.yml#/quality/jacoco/default_exclusions", None
    if name == "sonar_coverage_exclusions":
        defaults = (quality.get("sonar") or {}).get("default_exclusions", [])
        return [str(value).replace("__APPLICATION_CLASS__", pascal(str(svc.get("name") or "")) + "Application")
                for value in defaults], "archetype.yml#/quality/sonar/default_exclusions", None
    if name in {"external_secret_additional_data", "specification_owned_application_properties"}:
        return [], ".factory/service-spec.yml#/operations (no service-owned extra configuration is present)", None
    return None, None, f"Required archetype parameter '{name}' has no safe value in the approved service spec or archetype defaults."


def plan(root: Path, yaml: Any) -> dict[str, Any]:
    ARCHETYPE_ROOT = resolve_archetype(root)
    from archetype_contract import normalize, require_backend
    require_backend(normalize(read_yaml(root / ARCHETYPE_ROOT / 'archetype.yml', root, yaml)[0]), mode='scaffold')
    service, service_bytes = read_yaml(root / SERVICE_SPEC, root, yaml)
    archetype_root = root / ARCHETYPE_ROOT
    archetype, _ = read_yaml(archetype_root / "archetype.yml", root, yaml)
    readiness = service.get("readiness") or {}
    if readiness.get("strictImplementationReady") != readiness.get("implementationReady"):
        raise PlanError("implementationReady must remain an alias of strictImplementationReady.")
    if readiness.get("scaffoldImplementationReady") is not True:
        raise PlanError("Scaffold planning requires scaffoldImplementationReady: true.")
    active = service.get("operations") or []
    inactive = ((service.get("inactive") or {}).get("operations") or [])
    if not active:
        raise PlanError("No active operations are present in service-spec.yml.")
    keys = {(str(item.get("method")), str(item.get("path"))) for item in active}
    inactive_keys = {(str(item.get("method")), str(item.get("path"))) for item in inactive}
    if keys & inactive_keys:
        raise PlanError("An inactive operation collides with an active operation.")

    models, refs_by_operation = collect_models(service)
    package = None
    service_name = str((service.get("service") or {}).get("name") or "")
    application_class = pascal(service_name) + "Application"
    package_path = "__BASE_PACKAGE_PATH__"
    api_name = pascal(service_name) + "Api"
    api_target = f"src/main/java/{package_path}/controller/{api_name}.java"
    generated = [{
        "path": api_target,
        "type": "contract-api-interface",
        "generationStatus": "generate",
        "source": ".factory/service-spec.yml",
        "reason": "Structural API interface signatures are derived only from active OpenAPI contract entries; no implementations are planned.",
        "dependencies": ["base_package", "base_package_path"],
        "traceability": [f"/operations/{i}/contract" for i in range(len(active))],
    }]
    for model in models:
        scopes = set(model.get("requestResponseScope") or [])
        model_pkg = ("dto/enum" if model["kind"] == "enum" else
                     "dto/request" if scopes == {"request"} else
                     "dto/response" if scopes == {"response"} else "dto/contract")
        generated.append({
            "path": f"src/main/java/{package_path}/{model_pkg}/{model['name']}.java",
            "type": model["kind"], "generationStatus": "generate",
            "source": ".factory/service-spec.yml",
            "reason": "Contract schema model; fields and constraints are copied only from the resolved service-spec schema.",
            "dependencies": ["base_package", "base_package_path"],
            "traceability": [model["traceability"]],
        })
    tests = [{
        "path": f"src/test/java/{package_path}/controller/{api_name}ContractTest.java",
        "type": "empty-contract-test-skeleton", "generationStatus": "generate",
        "source": ".factory/service-spec.yml",
        "reason": "Structural contract test skeleton only; no expected business outcomes are asserted.",
        "dependencies": ["base_package", "base_package_path"],
        "traceability": [f"/operations/{i}/contract" for i in range(len(active))],
    }]

    manifest = archetype.get("template_inventory") or []
    parameters = archetype.get("parameters") or []
    parameter_by_path: dict[str, list[str]] = {}
    for parameter in parameters:
        for affected in parameter.get("affected_paths") or []:
            parameter_by_path.setdefault(str(affected), []).append(str(parameter.get("name")))
    copies, parameterized = [], []
    needed_parameter_names: set[str] = set()
    for record in manifest:
        source_path = str(record.get("path") or "")
        if source_path not in SCAFFOLD_ARTIFACTS:
            continue
        target_path = source_path.removeprefix("template/")
        is_parameterized = record.get("classification") == "parameterized"
        file_params = sorted(set(parameter_by_path.get(source_path, []))) if is_parameterized else []
        needed_parameter_names.update(file_params)
        entry = {
            "path": target_path,
            "type": "archetype-template-file",
            "generationStatus": "archetype-parameterize" if is_parameterized else "archetype-copy",
            "source": f"{ARCHETYPE_ROOT.as_posix()}/{source_path}",
            "reason": "Included technical baseline file from the selected archetype; only declared tokens are parameterized." if is_parameterized
                      else "Static archetype-owned technical baseline file.",
            "dependencies": file_params,
            "traceability": [f"archetype.yml#/template_inventory/{manifest.index(record)}"],
        }
        (parameterized if is_parameterized else copies).append(entry)

    parameter_results = []
    planning_blockers = []
    for parameter in parameters:
        name = str(parameter.get("name"))
        if name not in needed_parameter_names:
            continue
        value, source, blocker = parameter_value(parameter, service, archetype)
        entry = {"name": name, "token": parameter.get("token"), "value": value,
                 "required": True, "validForm": parameter.get("valid_form"),
                 "source": source or parameter.get("source"),
                 "affectedPaths": parameter.get("affected_paths") or [],
                 "traceability": f"archetype.yml#/parameters/{parameters.index(parameter)}"}
        if blocker:
            entry["status"] = "unresolved"
            entry["value"] = None
            entry["planningBlocker"] = blocker
            planning_blockers.append(blocker)
        else:
            entry["status"] = "resolved"
        parameter_results.append(entry)

    omitted = []
    for path_pattern, reason in BLOCKED_COMPONENTS:
        omitted.append({
            "path": path_pattern.format(packagePath=package_path),
            "type": "unresolved-functional-component",
            "generationStatus": "omit-scaffold-scope" if readiness.get("behaviorComplete") else "omit-unresolved",
            "source": ".factory/service-spec.yml#/readiness/scaffoldReadiness/unresolvedBehavior",
            "reason": "Functional component omitted by selected scaffold scope; full readiness is preserved from the specification." if readiness.get("behaviorComplete") else reason,
            "dependencies": [],
            "traceability": ["/readiness/blockers", "/readiness/scaffoldReadiness/unresolvedBehavior"],
        })
    api_ops = [operation_api_entry(item, i, refs_by_operation.get(str(item.get("operationId")), set()))
               for i, item in enumerate(active)]
    unresolved_operations = []
    for operation in active:
        behavior = operation.get("behavior") or {}
        unresolved_behavior = behavior.get("unresolved") or {}
        missing = list(unresolved_behavior.get("missingEvidence") or []) + list(unresolved_behavior.get("ambiguities") or [])
        if missing:
            unresolved_operations.append({
                "operationId": operation.get("operationId"),
                "missing": missing,
                "blockedArtifacts": [entry["path"] for entry in omitted
                                     if any(label in entry["path"] for label in ("controller/impl", "service/", "client/"))],
            })
    service_unresolved = service.get("unresolved") or {}
    readiness_scope = readiness.get("scaffoldReadiness") or {}
    persistence_items = [item for item in (service_unresolved.get("missingEvidence") or [])
                         if "persist" in str(item).lower() or "mapping" in str(item).lower()]
    integration_items = [item for item in (service_unresolved.get("missingEvidence") or [])
                         if "integration" in str(item).lower() or "client" in str(item).lower()]
    if not persistence_items:
        persistence_items = [item for item in (readiness.get("blockers") or [])
                             if "persistence" in str(item).lower() or "mapping" in str(item).lower()]
    if not integration_items:
        integration_items = [item for item in (readiness_scope.get("unresolvedBehavior") or [])
                             if "integration" in str(item).lower() or "invocation" in str(item).lower()]

    api_index = input_pointer_map(active)
    validation_checks = [
        "scaffold mode and readiness match service-spec.yml",
        "every active operation is present once and inactive operations are excluded",
        "contract models are traceable to service-spec.yml schema nodes",
        "no repository, entity, SQL, integration client, Retry, or business behavior is generated",
        "all required archetype parameter values are either traceably resolved or reported as planning blockers",
        "unresolved functional scope is explicitly listed as omit-unresolved",
    ]
    all_planned = generated + tests
    forbidden = ("/repository/", "/entity/", "/model/", "/client/", "/service/", "/sql/")
    if any(any(part in entry["path"].lower() for part in forbidden) for entry in all_planned):
        raise PlanError("A behavior/persistence-owned artifact entered the generated file inventory.")
    if len({str(item.get("operationId")) for item in active}) != len(active):
        raise PlanError("Active operation IDs are not unique.")
    if any(not model.get("traceability", "").startswith("/operations/") for model in models):
        raise PlanError("A planned contract model lacks service-spec schema traceability.")

    return {
        "plan": {"version": 1, "mode": "scaffold", "strictModeAuthorized": False,
                 "strictImplementationReady": readiness.get("strictImplementationReady"),
                 "scaffoldImplementationReady": readiness.get("scaffoldImplementationReady"),
                 "generatorMustOmitUnresolvedBehavior": True},
        "service": {"name": service_name, "package": package, "packagePath": package_path,
                    "artifactId": service_name if valid_kebab(service_name) else None,
                    "projectVersion": None,
                    "applicationClass": application_class,
                    "description": (service.get("service") or {}).get("description")},
        "inputs": {
            "serviceSpec": {"path": SERVICE_SPEC.as_posix(), "fingerprint": sha256(service_bytes),
                            "artifactSha256": sha256(service_bytes)},
            "archetype": {"path": ARCHETYPE_ROOT.as_posix(),
                          "id": (archetype.get("archetype") or {}).get("id"),
                          "version": (archetype.get("archetype") or {}).get("version"),
                          "fingerprint": archetype_fingerprint(archetype_root),
                          "manifest": f"{ARCHETYPE_ROOT.as_posix()}/archetype.yml",
                          "conventions": f"{ARCHETYPE_ROOT.as_posix()}/conventions.md",
                          "generationRules": f"{ARCHETYPE_ROOT.as_posix()}/generation-rules.md"},
        },
        "readiness": {
            "contractComplete": readiness.get("contractComplete"),
            "behaviorComplete": readiness.get("behaviorComplete"),
            "implementationReady": readiness.get("implementationReady"),
            "strictImplementationReady": readiness.get("strictImplementationReady"),
            "scaffoldImplementationReady": readiness.get("scaffoldImplementationReady"),
        },
        "parameters": {"resolved": [item for item in parameter_results if item["status"] == "resolved"],
                       "unresolved": [item for item in parameter_results if item["status"] == "unresolved"]},
        "files": {"generate": generated + tests, "archetypeCopy": copies,
                  "archetypeParameterize": parameterized, "omitUnresolved": omitted},
        "statistics": {"activeOperations": len(active), "models": len(models),
                       "filesToGenerate": len(generated) + len(tests), "archetypeFilesCopied": len(copies),
                       "archetypeFilesParameterized": len(parameterized),
                       "totalPlannedFiles": len(generated) + len(tests) + len(copies) + len(parameterized),
                       "filesOmittedUnresolved": len(omitted)},
        "api": {"style": "contract-facing interface only; no concrete behavior-bearing implementation",
                "interfaceFile": api_target, "operations": api_ops,
                "inactiveOperationsExcluded": [
                    {"method": item.get("method"), "path": item.get("path"),
                     "state": (item.get("lifecycle") or {}).get("state"),
                     "source": ".factory/service-spec.yml#/inactive/operations"}
                    for item in inactive]},
        "models": models,
        "tests": {"structural": tests, "businessTests": "omit-unresolved"},
        "unresolvedImplementation": {
            "operations": unresolved_operations,
            "persistence": {"status": "unresolved", "evidenceGaps": persistence_items,
                            "blockedArtifacts": ["repository", "entity", "SQL", "persistence mapper", "MAILINGINFORMATION CRUD", "GEDODBDD mapping"]},
            "integrations": {"status": "unresolved", "evidenceGaps": integration_items,
                             "blockedArtifacts": ["integration clients/calls", "Retry behavior"]},
            "otherBlockedArtifacts": ["business rules", "operation sequencing", "inferred success/error outcomes", "unsupported domain mappings"],
        },
        "quality": {"jacoco": (archetype.get("quality") or {}).get("jacoco"),
                    "sonar": (archetype.get("quality") or {}).get("sonar"),
                    "source": f"{ARCHETYPE_ROOT.as_posix()}/archetype.yml"},
        "planningBlockers": planning_blockers,
        "generation": {"scaffoldCodeGenerationCanBegin": not planning_blockers,
                       "reason": "All required technical parameters are resolved." if not planning_blockers
                                 else "Resolve required archetype technical parameters before scaffold materialization."},
        "validation": {"warnings": ["Strict/full implementation is not authorized.",
                                     "Scaffold readiness does not imply functional completeness."],
                       "checks": [{"check": check, "status": "passed"} for check in validation_checks],
                       "errors": []},
    }


def _enforce_consistency_gate():
    """Mandatory Sparx/Swagger consistency gate: no consolidation, planning or generation unless it is cleared (service workspace)."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "service-workspace" / "scripts"))
    import gate_guard
    return gate_guard.enforce()


def main() -> int:
    _gate_exit = _enforce_consistency_gate()
    if _gate_exit is not None:
        return _gate_exit
    root = Path.cwd().resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scaffold", "full"), default="scaffold")
    parser.add_argument("--planning-input", type=Path, default=Path(".factory/full-planning-input.yml"))
    args = parser.parse_args()
    # Keep one PlanError class when this file is run as a script and imported by
    # the full backend for shared helpers.
    sys.modules.setdefault("build_implementation_plan", sys.modules[__name__])
    try:
        yaml = yaml_module()
        if args.mode == "full":
            import profiles
            cfg, _ = read_yaml(root / args.planning_input, root, yaml)
            resolve_archetype(root, workspace=(root / args.planning_input).parent,
                              explicit=cfg['target']['archetype'])
            arch, _ = read_yaml(root / cfg["target"]["archetype"] / "archetype.yml", root, yaml)
            profile = profiles.resolve(arch)
            if profile == profiles.BATCH_SHELL:
                from batch_shell_plan import write_plan
                return write_plan(root, yaml, args.planning_input)
            if profile == profiles.JDBC_WAR:
                from jdbc_war_plan import write_plan
                return write_plan(root, yaml, args.planning_input)
            if profile == profiles.BFF:
                from bff_plan import write_plan
                return write_plan(root, yaml, args.planning_input)
            import rest_client_plan
            if rest_client_plan.applies(root, yaml, args.planning_input):
                return rest_client_plan.write_plan(root, yaml, args.planning_input)
            from full_implementation_plan import write_full_plan
            return write_full_plan(root, yaml, args.planning_input)
        result = plan(root, yaml)
        payload = dump_yaml(result, yaml)
        output = root / PLAN_PATH
        if output.is_symlink() or output.parent.resolve() != (root / ".factory").resolve():
            raise PlanError("Plan output must be a regular file directly under .factory/.")
        from artifact_integrity import write_atomic
        write_atomic(output, payload)
        print({"mode": result["plan"]["mode"], "operations": len(result["api"]["operations"]),
               "models": len(result["models"]), "plannedFiles": len(result["files"]["generate"]),
               "planningBlockers": len(result["planningBlockers"]), "bytes": len(payload),
               "sha256": sha256(payload)})
        return 0
    except (PlanError, OSError, TypeError, ValueError) as exc:
        print(f"build_implementation_plan.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
