#!/usr/bin/env python3
"""Deterministically materialize only implementation-plan-authorized scaffold files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


SERVICE_SPEC_PATH = Path(".factory/service-spec.yml")
PLAN_PATH = Path(".factory/implementation-plan.yml")
GENERATION_PARAMETERS_PATH = Path(".factory/generation-parameters.yml")
def _resolve_archetype_root() -> Path:
    import os
    chosen = os.environ.get("SERVICE_ARCHETYPE_PATH")
    if not chosen:
        state = Path(".factory/service-generation-state.yml")
        if state.is_file():
            import re
            text = state.read_text(encoding="utf-8")
            match = re.search(r"^archetype:\s*\n(?:[ \t]+.*\n)*?[ \t]+path:\s*['\"]?([^\s'\"]+)", text, re.M)
            chosen = match.group(1) if match else None
    return Path((chosen or "archetypes/claro-spring-ms/v1.0.0").rstrip("/"))


ARCHETYPE_ROOT = _resolve_archetype_root()
DEFAULT_OUTPUT = Path("output/dom-document-mailing-info")
MANIFEST_NAME = ".generation-manifest.yml"
TOKEN_RE = re.compile(r"__[A-Z0-9_]+__")
JAVA_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


class MaterializationError(Exception):
    """Raised when an input is invalid or a planned output is not safe to render."""


def yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise MaterializationError("PyYAML must already be installed; dependencies are not installed dynamically.") from exc
    return yaml


def read_yaml(path: Path, root: Path, yaml: Any) -> tuple[Any, bytes]:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file() or not resolved.is_relative_to(root):
        raise MaterializationError(f"Missing or unsafe approved input: {path.as_posix()}")
    payload = path.read_bytes()
    try:
        value = yaml.load(payload, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise MaterializationError(f"Invalid YAML: {path.as_posix()}") from exc
    return value or {}, payload


def encode_yaml(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def tree_fingerprint(path: Path) -> str:
    rows = []
    for file in sorted((entry for entry in path.rglob("*") if entry.is_file()),
                       key=lambda entry: entry.relative_to(path).as_posix()):
        if file.is_symlink():
            raise MaterializationError(f"Archetype contains a symlink: {file}")
        rows.append(f"{file.relative_to(path).as_posix()}\0{sha256(file.read_bytes())}\n")
    return sha256("".join(rows).encode("utf-8"))


def snapshots(root: Path, archetype_root: Path) -> dict[str, str]:
    return {
        SERVICE_SPEC_PATH.as_posix(): sha256((root / SERVICE_SPEC_PATH).read_bytes()),
        PLAN_PATH.as_posix(): sha256((root / PLAN_PATH).read_bytes()),
        GENERATION_PARAMETERS_PATH.as_posix(): sha256((root / GENERATION_PARAMETERS_PATH).read_bytes()),
        archetype_root.as_posix(): tree_fingerprint(root / archetype_root),
    }


def safe_relative(path: str) -> PurePosixPath:
    value = PurePosixPath(path)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise MaterializationError(f"Unsafe generated path: {path}")
    return value


def manifest_source_path(value: str, token_names: dict[str, str]) -> str:
    """Describe tokenized template source paths without presenting tokens as pending output values."""
    result = value
    for token in TOKEN_RE.findall(value):
        parameter = token_names.get(token)
        if parameter:
            result = result.replace(token, "{" + parameter + "}")
    return result


def package_type(schema: dict[str, Any]) -> str:
    resolved = schema.get("resolved") if isinstance(schema.get("resolved"), dict) else schema
    source = schema.get("source") if isinstance(schema.get("source"), dict) else {}
    ref = source.get("$ref")
    if ref:
        return str(ref).rsplit("/", 1)[-1]
    kind = resolved.get("type")
    if kind == "array":
        return f"List<{package_type(resolved.get('items') or {})}>"
    if kind == "integer":
        return "Long" if resolved.get("format") == "int64" else "Integer"
    return {"string": "String", "number": "Double", "boolean": "Boolean", "object": "Object"}.get(kind, "Object")


def java_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def java_identifier(name: str) -> str:
    segments = re.split(r"[^A-Za-z0-9_$]+", str(name))
    if not segments or not segments[0]:
        raise MaterializationError(f"Contract parameter has no Java identifier mapping: {name}")
    identifier = segments[0][0].lower() + segments[0][1:]
    for segment in segments[1:]:
        if segment:
            identifier += segment[0].upper() + segment[1:]
    if not JAVA_IDENTIFIER_RE.fullmatch(identifier):
        raise MaterializationError(f"Invalid Java identifier derived from contract parameter: {name}")
    return identifier


def schema_from_content(content: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(content, dict):
        return None, None
    for media_type in sorted(content):
        schema = (content.get(media_type) or {}).get("schema")
        if isinstance(schema, dict):
            source = schema.get("source") if isinstance(schema.get("source"), dict) else {}
            ref = source.get("$ref")
            return schema, str(ref).rsplit("/", 1)[-1] if ref else None
    return None, None


def response_model_for(operation: dict[str, Any], models: dict[str, dict[str, Any]]) -> str:
    responses = operation.get("contract", {}).get("responses") or {}
    success = next((responses[status] for status in sorted(responses)
                    if str(status).startswith("2")), None)
    if not success:
        raise MaterializationError(f"No successful response in approved contract for {operation.get('operationId')}")
    _, model = schema_from_content(success.get("content") or {})
    if not model or model not in models:
        raise MaterializationError(f"Successful response schema is not an inventoried contract model: {operation.get('operationId')}")
    return model


def request_model_for(operation: dict[str, Any], models: dict[str, dict[str, Any]]) -> str | None:
    body = operation.get("contract", {}).get("requestBody")
    if not body:
        return None
    _, model = schema_from_content(body.get("content") or {})
    if not model or model not in models:
        raise MaterializationError(f"Request schema is not an inventoried contract model: {operation.get('operationId')}")
    return model


def field_annotations(field: dict[str, Any], known_models: set[str]) -> tuple[list[str], set[str]]:
    annotations = list(field.get("validationAnnotations") or [])
    imports: set[str] = set()
    for annotation in annotations:
        match = re.fullmatch(r"@([A-Za-z][A-Za-z0-9]*)(?:\(.*\))?", annotation)
        if not match:
            raise MaterializationError(f"Unsupported planned validation annotation: {annotation}")
        imports.add(f"jakarta.validation.constraints.{match.group(1)}")
    java_type = str(field.get("javaType") or "Object")
    raw_type = java_type.removeprefix("List<").removesuffix(">")
    if raw_type in known_models:
        annotations.append("@Valid")
        imports.add("jakarta.validation.Valid")
    enum_values = (field.get("serializationMetadata") or {}).get("enum")
    if enum_values:
        values = ", ".join(java_string(value) for value in enum_values)
        annotations.append(f"@Schema(allowableValues = {{{values}}})")
        imports.add("io.swagger.v3.oas.annotations.media.Schema")
    return annotations, imports


def render_model(model: dict[str, Any], package: str, known_models: set[str]) -> bytes:
    name = str(model["javaTargetType"])
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", name):
        raise MaterializationError(f"Unsupported contract model Java type: {name}")
    fields = model.get("fields") or []
    imports: set[str] = set()
    for field in fields:
        annotations, annotation_imports = field_annotations(field, known_models)
        imports.update(annotation_imports)
        java_type = str(field.get("javaType") or "Object")
        if java_type.startswith("List<"):
            imports.add("java.util.List")
        if java_type == "BigDecimal":
            imports.add("java.math.BigDecimal")
    lines = [f"package {package};", ""]
    lines.extend(f"import {name};" for name in sorted(imports))
    if imports:
        lines.append("")
    lines.append(f"public class {name} {{")
    for field in fields:
        annotations, _ = field_annotations(field, known_models)
        for annotation in annotations:
            lines.append(f"    {annotation}")
        lines.append(f"    private {field.get('javaType', 'Object')} {field['name']};")
        lines.append("")
    for index, field in enumerate(fields):
        java_type = str(field.get("javaType") or "Object")
        field_name = str(field["name"])
        accessor = field_name[0].upper() + field_name[1:]
        lines.extend([
            f"    public {java_type} get{accessor}() {{",
            f"        return {field_name};",
            "    }",
            "",
            f"    public void set{accessor}({java_type} {field_name}) {{",
            f"        this.{field_name} = {field_name};",
            "    }",
        ])
        if index != len(fields) - 1:
            lines.append("")
    lines.extend(["}", ""])
    return "\n".join(lines).encode("utf-8")


def parameter_validation(schema: dict[str, Any]) -> tuple[list[str], set[str]]:
    resolved = schema.get("resolved") if isinstance(schema.get("resolved"), dict) else schema
    annotations = []
    imports: set[str] = set()
    kind = resolved.get("type")
    for constraint, annotation in (("minimum", "Min"), ("maximum", "Max")):
        if constraint in resolved and kind == "integer":
            annotations.append(f"@{annotation}({resolved[constraint]})")
            imports.add(f"jakarta.validation.constraints.{annotation}")
    for constraint, annotation in (("minLength", "Size"), ("maxLength", "Size")):
        if constraint in resolved:
            args = []
            if "minLength" in resolved:
                args.append(f"min = {resolved['minLength']}")
            if "maxLength" in resolved:
                args.append(f"max = {resolved['maxLength']}")
            value = "@Size(" + ", ".join(args) + ")"
            if value not in annotations:
                annotations.append(value)
            imports.add("jakarta.validation.constraints.Size")
    if resolved.get("format") == "email":
        annotations.append("@Email")
        imports.add("jakarta.validation.constraints.Email")
    enum_values = resolved.get("enum")
    if enum_values:
        values = ", ".join(java_string(value) for value in enum_values)
        annotations.append(f"@Parameter(schema = @Schema(allowableValues = {{{values}}}))")
        imports.update({"io.swagger.v3.oas.annotations.Parameter", "io.swagger.v3.oas.annotations.media.Schema"})
    return annotations, imports


def operation_schema_map(spec: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    spec_ops = {str(item.get("operationId")): item for item in spec.get("operations") or []}
    plan_ops = {str(item.get("operationId")): item for item in (plan.get("api") or {}).get("operations") or []}
    if set(spec_ops) != set(plan_ops):
        raise MaterializationError("Service spec and implementation plan active operation identities differ.")
    active_pairs = {(item.get("method"), item.get("path")) for item in spec_ops.values()}
    planned_pairs = {(item.get("method"), item.get("path")) for item in plan_ops.values()}
    if active_pairs != planned_pairs:
        raise MaterializationError("Service spec and implementation plan active HTTP operations differ.")
    inactive = (spec.get("inactive") or {}).get("operations") or []
    for item in inactive:
        pair = (item.get("method"), item.get("path"))
        if pair in planned_pairs:
            raise MaterializationError("Inactive operation entered active API generation scope.")
    return spec_ops, plan_ops


def render_api_interface(spec: dict[str, Any], plan: dict[str, Any], package: str) -> bytes:
    operations = (plan.get("api") or {}).get("operations") or []
    models = {str(item["name"]): item for item in plan.get("models") or []}
    known_models = set(models)
    spec_ops, _ = operation_schema_map(spec, plan)
    interface_path = str((plan.get("api") or {}).get("interfaceFile") or "")
    class_name = PurePosixPath(interface_path).stem
    imports = {
        "org.springframework.http.ResponseEntity",
        "org.springframework.web.bind.annotation.RequestBody",
        "org.springframework.web.bind.annotation.RequestHeader",
        "org.springframework.web.bind.annotation.RequestMapping",
        "org.springframework.web.bind.annotation.RequestMethod",
        "org.springframework.web.bind.annotation.RequestParam",
        "org.springframework.web.bind.annotation.PathVariable",
        "io.swagger.v3.oas.annotations.Operation",
        "io.swagger.v3.oas.annotations.responses.ApiResponse",
        "io.swagger.v3.oas.annotations.responses.ApiResponses",
        "io.swagger.v3.oas.annotations.media.Content",
        "io.swagger.v3.oas.annotations.media.Schema",
        "jakarta.validation.Valid",
    }
    imports.update({"org.springframework.web.bind.annotation.GetMapping",
                    "org.springframework.web.bind.annotation.PostMapping",
                    "org.springframework.web.bind.annotation.PatchMapping"})
    tags = sorted({tag for op in spec_ops.values() for tag in ((op.get("contract") or {}).get("tags") or [])})
    for op in operations:
        spec_op = spec_ops[str(op["operationId"])]
        req_model = request_model_for(spec_op, models)
        response_model = response_model_for(spec_op, models)
        if req_model:
            imports.add(f"{package.rsplit('.controller', 1)[0]}.dto.request.{req_model}")
        imports.add(f"{package.rsplit('.controller', 1)[0]}.dto.response.{response_model}")
        contract = spec_op.get("contract") or {}
        for status in (contract.get("responses") or {}).values():
            for media in (status.get("content") or {}).values():
                schema = media.get("schema") or {}
                source = schema.get("source") if isinstance(schema.get("source"), dict) else {}
                if source.get("$ref"):
                    model_name = str(source["$ref"]).rsplit("/", 1)[-1]
                    if model_name in models:
                        imports.add(f"{package.rsplit('.controller', 1)[0]}.dto.response.{model_name}")
        parameters = contract.get("parameters") or {}
        for kind in ("path", "query", "header"):
            for parameter in parameters.get(kind) or []:
                schema = parameter.get("schema") or {}
                type_name = package_type(schema)
                if type_name.startswith("List<"):
                    imports.add("java.util.List")
                if type_name == "BigDecimal":
                    imports.add("java.math.BigDecimal")
                _, validation_imports = parameter_validation(schema)
                imports.update(validation_imports)
    lines = [f"package {package};", ""]
    lines.extend(f"import {value};" for value in sorted(imports))
    lines.extend(["", f"@io.swagger.v3.oas.annotations.tags.Tag(name = {java_string(tags[0] if tags else spec['service']['name'])})",
                  f"public interface {class_name} {{", ""])
    for op in operations:
        operation_id = str(op["operationId"])
        spec_op = spec_ops[operation_id]
        contract = spec_op.get("contract") or {}
        method = str(op["method"]).upper()
        path = str(op["path"])
        response_model = response_model_for(spec_op, models)
        request_model = request_model_for(spec_op, models)
        media_types = sorted({media for response in (contract.get("responses") or {}).values()
                              for media in (response.get("content") or {})})
        request_media = sorted((contract.get("requestBody") or {}).get("content") or {})
        mapping = {"GET": "GetMapping", "POST": "PostMapping", "PATCH": "PatchMapping"}.get(method)
        if not mapping:
            raise MaterializationError(f"Unsupported planned HTTP method: {method}")
        mapping_args = [f"path = {java_string(path)}"]
        if request_media:
            mapping_args.append("consumes = {" + ", ".join(java_string(value) for value in request_media) + "}")
        if media_types:
            mapping_args.append("produces = {" + ", ".join(java_string(value) for value in media_types) + "}")
        lines.append(f"    @{mapping}({', '.join(mapping_args)})")
        summary = (contract.get("summary") or "").strip()
        description = (contract.get("description") or "").strip()
        operation_args = []
        if summary:
            operation_args.append(f"summary = {java_string(summary)}")
        if description:
            operation_args.append(f"description = {java_string(description)}")
        if operation_args:
            lines.append(f"    @Operation({', '.join(operation_args)})")
        responses = contract.get("responses") or {}
        response_annotations = []
        for status_code in sorted(responses, key=lambda item: (int(item) if str(item).isdigit() else 999, str(item))):
            response = responses[status_code]
            args = [f"responseCode = {java_string(status_code)}"]
            if response.get("description"):
                args.append(f"description = {java_string(response['description'])}")
            content_args = []
            for media_type in sorted(response.get("content") or {}):
                media = (response.get("content") or {})[media_type]
                schema = media.get("schema") or {}
                source = schema.get("source") if isinstance(schema.get("source"), dict) else {}
                schema_model = str(source.get("$ref") or "").rsplit("/", 1)[-1]
                if schema_model and schema_model in models:
                    content_args.append(f"@Content(mediaType = {java_string(media_type)}, schema = @Schema(implementation = {schema_model}.class))")
                else:
                    content_args.append(f"@Content(mediaType = {java_string(media_type)})")
            if content_args:
                args.append("content = {" + ", ".join(content_args) + "}")
            response_annotations.append("@ApiResponse(" + ", ".join(args) + ")")
        lines.append("    @ApiResponses({" + ", ".join(response_annotations) + "})")
        method_parameters = []
        all_parameters = contract.get("parameters") or {}
        binding = {"path": "PathVariable", "query": "RequestParam", "header": "RequestHeader"}
        for kind in ("path", "query", "header"):
            for parameter in all_parameters.get(kind) or []:
                name = str(parameter.get("name") or "")
                identifier = java_identifier(name)
                schema = parameter.get("schema") or {}
                type_name = package_type(schema)
                annotations, _ = parameter_validation(schema)
                required = bool(parameter.get("required"))
                annotations.append(f"@{binding[kind]}(name = {java_string(name)}, required = {str(required).lower()})")
                method_parameters.append(" ".join(annotations + [f"{type_name} {identifier}"]))
        body = contract.get("requestBody")
        if body and request_model:
            body_required = bool(body.get("required"))
            method_parameters.append(" ".join([
                "@Valid",
                f"@RequestBody(required = {str(body_required).lower()})",
                f"{request_model} request",
            ]))
        lines.append(f"    ResponseEntity<{response_model}> {operation_id}({', '.join(method_parameters)});")
        lines.append("")
    lines.extend(["}", ""])
    return "\n".join(lines).encode("utf-8")


def render_test_skeleton(package: str, class_name: str) -> bytes:
    return f"package {package};\n\nclass {class_name} {{\n}}\n".encode("utf-8")


def validation_inventory(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = []
    for key in ("generate", "archetypeCopy", "archetypeParameterize"):
        entries.extend(plan["files"].get(key) or [])
    seen = set()
    result = {}
    for entry in entries:
        rel = safe_relative(str(entry.get("path") or ""))
        if rel.as_posix() in seen:
            raise MaterializationError(f"Duplicate authorized generated path: {rel}")
        seen.add(rel.as_posix())
        expected = {"generate": "generate", "archetypeCopy": "archetype-copy",
                    "archetypeParameterize": "archetype-parameterize"}[next(
                        key for key in ("generate", "archetypeCopy", "archetypeParameterize")
                        if entry in (plan["files"].get(key) or []))]
        if entry.get("generationStatus") != expected:
            raise MaterializationError(f"Unexpected generation status for {rel}")
        result[rel.as_posix()] = entry
    for entry in plan["files"].get("omitUnresolved") or []:
        if entry.get("generationStatus") == "omit-unresolved" and str(entry.get("path")) in result:
            raise MaterializationError(f"An omit-unresolved file is also allowlisted: {entry['path']}")
    return result


def check_ready_inputs(spec: dict[str, Any], plan: dict[str, Any], params: dict[str, Any],
                       arch: dict[str, Any], plan_entries: dict[str, dict[str, Any]]) -> None:
    if (plan.get("plan") or {}).get("mode") != "scaffold":
        raise MaterializationError("Only scaffold mode can be materialized in this phase.")
    readiness = plan.get("readiness") or {}
    if (readiness.get("strictImplementationReady") is not False
            or readiness.get("scaffoldImplementationReady") is not True
            or readiness.get("sourceGenerationReady") is not True):
        raise MaterializationError("Implementation plan readiness does not authorize scaffold source materialization.")
    if readiness.get("implementationReady") is not False:
        raise MaterializationError("Strict implementation readiness must remain false.")
    package = (params.get("service") or {}).get("package")
    package_path = package.replace(".", "/") if isinstance(package, str) else None
    plan_package = (plan.get("service") or {}).get("package")
    plan_path = (plan.get("service") or {}).get("packagePath")
    if not package or package != plan_package or package_path != plan_path:
        raise MaterializationError("Resolved Java package does not match generation parameters and plan.")
    resolved = {str(item.get("name")): item for item in (params.get("resolved") or [])}
    for entry in plan_entries.values():
        dependencies = entry.get("dependencies") or []
        missing = [name for name in dependencies if name not in resolved or resolved[name].get("value") is None]
        if missing:
            raise MaterializationError(f"Authorized file {entry['path']} has unresolved parameters: {sorted(missing)}")
    operations = plan.get("api", {}).get("operations") or []
    active_pairs = {(str(op.get("method")), str(op.get("path"))) for op in operations}
    expected = {(str(op.get("method")), str(op.get("path"))) for op in spec.get("operations") or []}
    if active_pairs != expected or len(active_pairs) != len(operations):
        raise MaterializationError("Planned API operations do not exactly match active service-spec operations.")
    inactive = (spec.get("inactive") or {}).get("operations") or []
    if active_pairs.intersection((str(item.get("method")), str(item.get("path"))) for item in inactive):
        raise MaterializationError("An inactive service-spec operation is in the active API generation plan.")
    if (arch.get("archetype") or {}).get("version") != plan.get("inputs", {}).get("archetype", {}).get("version"):
        raise MaterializationError("Plan archetype version does not match the selected archetype manifest.")


def materialize_bytes(root: Path, spec: dict[str, Any], plan: dict[str, Any], params: dict[str, Any],
                      arch: dict[str, Any], entries: dict[str, dict[str, Any]]) -> tuple[dict[str, bytes], dict[str, Any]]:
    package = str((params.get("service") or {})["package"])
    models = {str(model["name"]): model for model in plan.get("models") or []}
    known_models = set(models)
    resolved = {str(item.get("name")): item.get("value") for item in (params.get("resolved") or [])}
    parameter_tokens = {str(item.get("token")): str(item.get("name"))
                        for item in (arch.get("parameters") or []) if item.get("token")}
    internal_tokens = set(((arch.get("parameter_token_policy") or {}).get("non_parameter_wrapper_identifiers")) or [])
    output: dict[str, bytes] = {}
    generated_metadata = []
    specs_by_id = {str(item.get("operationId")): item for item in (spec.get("operations") or [])}

    for relative, entry in sorted(entries.items()):
        status = str(entry["generationStatus"])
        source = str(entry.get("source") or "")
        if status in {"archetype-copy", "archetype-parameterize"}:
            prefix = ARCHETYPE_ROOT.as_posix() + "/"
            if not source.startswith(prefix):
                raise MaterializationError(f"Archetype file has an invalid source path: {source}")
            src = root / Path(source.replace("/", os.sep))
            if src.is_symlink() or not src.is_file() or not src.resolve().is_relative_to(root):
                raise MaterializationError(f"Missing or unsafe archetype template: {source}")
            payload = src.read_bytes()
            if status == "archetype-parameterize":
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise MaterializationError(f"Cannot decode parameterized template as UTF-8: {source}") from exc
                for token in TOKEN_RE.findall(text):
                    name = parameter_tokens.get(token)
                    if not name:
                        if token in internal_tokens:
                            continue
                        raise MaterializationError(f"Unrecognized template token in authorized output {relative}: {token}")
                    value = resolved.get(name)
                    if value is None or not isinstance(value, (str, int, float, bool)):
                        raise MaterializationError(f"No scalar resolved value for {name} in {relative}")
                    text = text.replace(token, str(value))
                payload = text.encode("utf-8")
        elif status == "generate":
            entry_type = str(entry.get("type"))
            if entry_type == "contract-api-interface":
                package_name = package + ".controller"
                payload = render_api_interface(spec, plan, package_name)
            elif entry_type == "contract-model":
                model = next((value for value in plan.get("models") or []
                              if value.get("filePath") == relative), None)
                if model is None:
                    raise MaterializationError(f"No service-spec-derived model maps to {relative}")
                suffix = PurePosixPath(relative).parent.relative_to("src/main/java/" + package.replace(".", "/"))
                model_package = package + ("." + ".".join(suffix.parts) if suffix.parts else "")
                payload = render_model(model, model_package, known_models)
            elif entry_type == "empty-contract-test-skeleton":
                package_name = package + ".controller"
                payload = render_test_skeleton(package_name, PurePosixPath(relative).stem)
            else:
                raise MaterializationError(f"Unsupported generated file type: {entry_type}")
            source = ".factory/service-spec.yml"
        else:
            raise MaterializationError(f"Disallowed file status reached the materializer: {relative}: {status}")
        output[relative] = payload
        generated_metadata.append({
            "path": relative,
            "source": manifest_source_path(source, parameter_tokens),
            "reason": entry.get("reason", "Deterministic scaffold generation from approved inputs."),
            "traceability": entry.get("traceability") or [],
        })

    omitted_metadata = []
    unresolved = plan.get("unresolvedImplementation") or {}
    operation_gaps = [gap.get("reason") for operation in (unresolved.get("operations") or [])
                      for gap in (operation.get("missing") or []) if gap.get("reason")]
    persistence_gaps = [gap.get("reason") for gap in (unresolved.get("persistence") or {}).get("evidenceGaps", [])
                        if gap.get("reason")]
    integration_gaps = [gap.get("reason") for gap in (unresolved.get("integrations") or {}).get("evidenceGaps", [])
                        if gap.get("reason")]
    for entry in plan.get("files", {}).get("omitUnresolved") or []:
        entry_type = str(entry.get("type", ""))
        reason_text = str(entry.get("reason", ""))
        if entry.get("parameterResolution"):
            missing = entry["parameterResolution"].get("missingParameters") or []
            behavior = []
        elif any(key in str(entry.get("path", "")) for key in ("client/", "client/**")):
            missing, behavior = [], integration_gaps
        elif any(key in str(entry.get("path", "")) for key in ("repository/", "entity/", "model/", "db/", "mapper/")):
            missing, behavior = [], persistence_gaps
        elif entry_type == "unresolved-functional-component":
            missing, behavior = [], operation_gaps
        else:
            missing, behavior = [], []
        omitted_metadata.append({
            "path": entry.get("path"),
            "reason": reason_text,
            "missingParameters": sorted(map(str, missing)),
            "unresolvedBehavior": sorted(set(map(str, behavior))),
        })

    input_fingerprints = snapshots(root, ARCHETYPE_ROOT)
    source_input_hash = input_fingerprints[SERVICE_SPEC_PATH.as_posix()]
    manifest = {
        "generation": {"mode": "scaffold"},
        "inputs": {
            "serviceSpec": {"path": SERVICE_SPEC_PATH.as_posix(), "fingerprint": source_input_hash},
            "implementationPlan": {"path": PLAN_PATH.as_posix(),
                                   "fingerprint": input_fingerprints[PLAN_PATH.as_posix()]},
            "generationParameters": {"path": GENERATION_PARAMETERS_PATH.as_posix(),
                                     "fingerprint": input_fingerprints[GENERATION_PARAMETERS_PATH.as_posix()]},
            "archetype": {"path": ARCHETYPE_ROOT.as_posix(),
                          "version": (arch.get("archetype") or {}).get("version"),
                          "fingerprint": input_fingerprints[ARCHETYPE_ROOT.as_posix()]},
        },
        "generatedFiles": sorted(generated_metadata, key=lambda item: item["path"]),
        "omittedFiles": sorted(omitted_metadata, key=lambda item: str(item.get("path"))),
        "readiness": {
            "sourceGenerationReady": (plan.get("readiness") or {}).get("sourceGenerationReady"),
            "buildExecutionReady": (plan.get("readiness") or {}).get("buildExecutionReady"),
            "deploymentGenerationReady": (plan.get("readiness") or {}).get("deploymentGenerationReady"),
            "strictImplementationReady": (plan.get("readiness") or {}).get("strictImplementationReady"),
            "scaffoldImplementationReady": (plan.get("readiness") or {}).get("scaffoldImplementationReady"),
        },
    }
    output[MANIFEST_NAME] = encode_yaml(manifest, yaml_module())
    return output, manifest


def write_output(base: Path, files: dict[str, bytes]) -> None:
    if base.exists() and (not base.is_dir() or any(base.iterdir())):
        raise MaterializationError(f"Output directory already exists and is not empty: {base}")
    base.mkdir(parents=True, exist_ok=True)
    for relative, payload in sorted(files.items()):
        target = base / Path(*safe_relative(relative).parts)
        if target.exists() or target.is_symlink():
            raise MaterializationError(f"Output path already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def inventory(files: dict[str, bytes]) -> list[tuple[str, str]]:
    return [(path, sha256(files[path])) for path in sorted(files)]


def validate_generated(spec: dict[str, Any], plan: dict[str, Any], params: dict[str, Any],
                       files: dict[str, bytes], manifest: dict[str, Any], archetype: dict[str, Any]) -> None:
    entries = validation_inventory(plan)
    planned_paths = set(entries)
    actual_paths = set(files) - {MANIFEST_NAME}
    if actual_paths != planned_paths:
        raise MaterializationError(f"Generated inventory differs from authorized plan. Missing={sorted(planned_paths-actual_paths)}, extra={sorted(actual_paths-planned_paths)}")
    if len(manifest["generatedFiles"]) != len(actual_paths):
        raise MaterializationError("Manifest generated-file inventory is incomplete.")
    package = str(params["service"]["package"])
    inactive = (spec.get("inactive") or {}).get("operations") or []
    api_sources = [files[path].decode("utf-8") for path, entry in entries.items()
                   if entry.get("type") == "contract-api-interface"]
    if len(api_sources) != 1:
        raise MaterializationError("Expected exactly one planned API interface.")
    api_text = api_sources[0]
    if f"package {package}.controller;" not in api_text:
        raise MaterializationError("Generated API interface has an incorrect Java package.")
    active_routes = set()
    for operation in plan.get("api", {}).get("operations") or []:
        method = str(operation["method"]).title()
        path = str(operation["path"])
        if f"@{method}Mapping(path = {java_string(path)}" not in api_text:
            raise MaterializationError(f"Active operation is not represented in API interface: {operation}")
        active_routes.add((method, path))
    rendered_routes = set((method, path) for method, path in
                          re.findall(r"@(Get|Post|Patch)Mapping\(path = \"([^\"]+)\"", api_text))
    if rendered_routes != active_routes:
        raise MaterializationError(f"Generated API route inventory differs from active operations: {rendered_routes}")
    for operation in inactive:
        method = str(operation.get("method", "")).title()
        path = str(operation.get("path", ""))
        if f"@{method}Mapping(path = {java_string(path)}" in api_text:
            raise MaterializationError("Inactive operation was rendered as an active endpoint.")
    forbidden_path_parts = ("/repository/", "/entity/", "/client/", "/model/", "/mapper/", "/db/")
    if any(any(part in "/" + path.lower() for part in forbidden_path_parts) for path in actual_paths):
        raise MaterializationError("A persistence/domain/integration-owned file was generated.")
    exempt = set(((archetype.get("parameter_token_policy") or {}).get("non_parameter_wrapper_identifiers")) or [])
    tokens = {str(item.get("token")) for item in (archetype.get("parameters") or []) if item.get("token")}
    unresolved_tokens = set()
    for path, payload in files.items():
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        unresolved_tokens.update(token for token in TOKEN_RE.findall(text) if token in tokens and token not in exempt)
        if path.endswith(".java"):
            declarations = re.findall(r"^package\s+([A-Za-z0-9_.]+);", text, re.MULTILINE)
            if len(declarations) != 1 or not (declarations[0] == package or declarations[0].startswith(package + ".")):
                raise MaterializationError(f"Generated Java file has an unexpected package declaration: {path}")
            if any(leak in declarations[0].lower() for leak in ("biometria", "individual")):
                raise MaterializationError(f"Reference-service package segment leaked into generated Java: {path}")
    if unresolved_tokens:
        raise MaterializationError(f"Generated files contain unresolved archetype parameters: {sorted(unresolved_tokens)}")
    if manifest["readiness"]["strictImplementationReady"] is not False:
        raise MaterializationError("Strict implementation readiness must remain false.")
    if manifest["readiness"]["scaffoldImplementationReady"] is not True:
        raise MaterializationError("Scaffold readiness must remain true.")


def build_from_approved_inputs(root: Path, yaml: Any) -> tuple[dict[str, bytes], dict[str, Any], dict[str, str]]:
    spec, _ = read_yaml(root / SERVICE_SPEC_PATH, root, yaml)
    plan, _ = read_yaml(root / PLAN_PATH, root, yaml)
    params, _ = read_yaml(root / GENERATION_PARAMETERS_PATH, root, yaml)
    arch, _ = read_yaml(root / ARCHETYPE_ROOT / "archetype.yml", root, yaml)
    entries = validation_inventory(plan)
    check_ready_inputs(spec, plan, params, arch, entries)
    before = snapshots(root, ARCHETYPE_ROOT)
    files, manifest = materialize_bytes(root, spec, plan, params, arch, entries)
    validate_generated(spec, plan, params, files, manifest, arch)
    return files, manifest, before


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-determinism", action="store_true")
    parser.add_argument("--verify-only", action="store_true",
                        help="Verify reproducibility and an existing output without writing the final output directory.")
    parser.add_argument("--refresh-manifest-only", action="store_true",
                        help="Refresh only the manifest if all already-materialized non-manifest files match exactly.")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        yaml = yaml_module()
        files, manifest, before = build_from_approved_inputs(root, yaml)

        output = (root / args.output).absolute()
        if output.parent.resolve() != (root / "output").resolve():
            raise MaterializationError("Final output must be a direct child of output/.")
        if args.verify_only and not args.verify_determinism:
            raise MaterializationError("--verify-only requires --verify-determinism.")
        if args.refresh_manifest_only and args.verify_only:
            raise MaterializationError("Choose either --verify-only or --refresh-manifest-only.")
        if args.verify_determinism:
            with tempfile.TemporaryDirectory(dir=output.parent, prefix=".scaffold-check-a-") as first_dir, \
                 tempfile.TemporaryDirectory(dir=output.parent, prefix=".scaffold-check-b-") as second_dir:
                first = Path(first_dir) / "service"
                second = Path(second_dir) / "service"
                files_a, _, _ = build_from_approved_inputs(root, yaml)
                files_b, _, _ = build_from_approved_inputs(root, yaml)
                write_output(first, files_a)
                write_output(second, files_b)
                inv_a = [(p.relative_to(first).as_posix(), sha256(p.read_bytes()))
                         for p in sorted(first.rglob("*")) if p.is_file()]
                inv_b = [(p.relative_to(second).as_posix(), sha256(p.read_bytes()))
                         for p in sorted(second.rglob("*")) if p.is_file()]
                if inv_a != inv_b:
                    raise MaterializationError("Two clean temporary generations produced different files or hashes.")
                if any(build_from_approved_inputs(root, yaml)[2] != before for _ in range(2)):
                    raise MaterializationError("Approved input fingerprints changed during repeated generation.")
        if args.verify_only:
            if not output.is_dir():
                raise MaterializationError(f"Verification output directory does not exist: {output}")
            actual = {item.relative_to(output).as_posix(): sha256(item.read_bytes())
                      for item in output.rglob("*") if item.is_file()}
            expected = {path: sha256(payload) for path, payload in files.items()}
            if actual != expected:
                raise MaterializationError("Existing final output differs from deterministic materialization.")
        elif args.refresh_manifest_only:
            if not output.is_dir():
                raise MaterializationError(f"Cannot refresh manifest; output directory does not exist: {output}")
            actual_nonmanifest = {item.relative_to(output).as_posix(): sha256(item.read_bytes())
                                  for item in output.rglob("*") if item.is_file()
                                  and item.relative_to(output).as_posix() != MANIFEST_NAME}
            expected_nonmanifest = {path: sha256(payload) for path, payload in files.items() if path != MANIFEST_NAME}
            if actual_nonmanifest != expected_nonmanifest:
                raise MaterializationError("Cannot refresh manifest because generated file contents differ from the current plan.")
            manifest_path = output / MANIFEST_NAME
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise MaterializationError("Cannot refresh a missing or unsafe generation manifest.")
            manifest_path.write_bytes(files[MANIFEST_NAME])
        else:
            write_output(output, files)
        after = snapshots(root, ARCHETYPE_ROOT)
        if before != after:
            raise MaterializationError("An authoritative input changed during materialization.")
        print({"output": output.relative_to(root).as_posix(),
               "files": len(files), "generatedFiles": len(files) - 1,
               "manifestSha256": sha256(files[MANIFEST_NAME]),
               "treeSha256": sha256("".join(f"{p}\0{h}\n" for p, h in inventory(files)).encode("utf-8")),
               "determinismVerified": bool(args.verify_determinism)})
        return 0
    except (MaterializationError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"materialize_scaffold.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
