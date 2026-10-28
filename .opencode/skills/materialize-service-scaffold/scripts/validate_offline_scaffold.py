#!/usr/bin/env python3
"""Validate generated scaffold files offline without changing project output."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any


SERVICE_SPEC = Path(".factory/service-spec.yml")
PLAN = Path(".factory/implementation-plan.yml")
PARAMETERS = Path(".factory/generation-parameters.yml")
MANIFEST_REL = Path("output/dom-document-mailing-info/.generation-manifest.yml")
OUTPUT_REL = Path("output/dom-document-mailing-info")
BUILD_REPORT = Path(".factory/build-report.yml")
REPORT = Path(".factory/offline-validation-report.yml")
JAVA_PACKAGE = "com.claro.document.mailing.info.support"
JAVA_PACKAGE_PATH = "com/claro/document/mailing/info/support"
TOKEN_RE = re.compile(r"__[A-Z0-9_]+__")
JAVA_FIELD = re.compile(r"(?m)^[ \t]*private[ \t]+([A-Za-z0-9_<>, ?]+)[ \t]+([A-Za-z_$][A-Za-z0-9_$]*)[ \t]*;")
JAVA_TYPE = re.compile(r"(?m)^[ \t]*(?:public[ \t]+)?(?:abstract[ \t]+)?(class|interface|enum|record)[ \t]+([A-Za-z_$][A-Za-z0-9_$]*)\b")
JAVA_PACKAGE_DECL = re.compile(r"(?m)^package[ \t]+([A-Za-z0-9_.]+);[ \t]*$")
API_METHOD = re.compile(r"ResponseEntity<([A-Za-z_$][A-Za-z0-9_$]*)>[ \t]+([A-Za-z_$][A-Za-z0-9_$]*)\((.*?)\);", re.S)
API_ROUTE = re.compile(r"@(Get|Post|Patch)Mapping\(path = \"([^\"]+)\"")
PARAM_BINDING = re.compile(r"@(RequestParam|PathVariable|RequestHeader)\(name = \"([^\"]+)\", required = (true|false)\)")
BODY_BINDING = re.compile(r"@RequestBody\(required = (true|false)\)[ \t]+([A-Za-z_$][A-Za-z0-9_$]*)[ \t]+request")
ANNOTATION = re.compile(r"@[A-Za-z_$][A-Za-z0-9_$]*(?:\([^\n]*\))?")


def yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML must already be installed.") from exc
    return yaml


def read_yaml(path: Path, root: Path, yaml: Any) -> tuple[Any, bytes]:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise RuntimeError(f"Missing or unsafe offline-validation input: {path.as_posix()}")
    data = path.read_bytes()
    return yaml.safe_load(data) or {}, data


def dump_yaml(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def java_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def resolve_pointer(value: Any, pointer: str) -> Any:
    current = value
    parts = pointer.strip("/").split("/") if pointer else []
    index = 0
    while index < len(parts):
        raw = parts[index]
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        else:
            if part not in current and index + 1 < len(parts):
                combined = part + "/" + parts[index + 1].replace("~1", "/").replace("~0", "~")
                if combined in current:
                    current = current[combined]
                    index += 1
                else:
                    current = current[part]
            else:
                current = current[part]
        index += 1
    return current


def resolved_schema(schema: dict[str, Any]) -> dict[str, Any]:
    resolved = schema.get("resolved")
    return resolved if isinstance(resolved, dict) else schema


def schema_ref(schema: dict[str, Any] | None) -> str | None:
    if not isinstance(schema, dict):
        return None
    source = schema.get("source") if isinstance(schema.get("source"), dict) else {}
    ref = source.get("$ref")
    return str(ref).rsplit("/", 1)[-1] if ref else None


def schema_from_content(content: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(content, dict):
        return None, None
    for media_type in sorted(content):
        schema = (content.get(media_type) or {}).get("schema")
        if isinstance(schema, dict):
            return schema, schema_ref(schema)
    return None, None


def schema_java_type(schema: dict[str, Any]) -> str:
    ref = schema_ref(schema)
    if ref:
        return ref
    resolved = resolved_schema(schema)
    kind = resolved.get("type")
    if kind == "array":
        return f"List<{schema_java_type(resolved.get('items') or {})}>"
    if kind == "integer":
        return "Long" if resolved.get("format") == "int64" else "Integer"
    return {"string": "String", "number": "Double", "boolean": "Boolean", "object": "Object"}.get(kind, "Object")


def method_annotation_name(method: str) -> str:
    return {"GET": "Get", "POST": "Post", "PATCH": "Patch"}.get(method.upper(), method.title())


def source_package_path(relative: str) -> tuple[str | None, str | None]:
    path = PurePosixPath(relative)
    parts = path.parts
    if len(parts) < 5 or parts[0] != "src" or parts[1] not in {"main", "test"} or parts[2] != "java":
        return None, None
    try:
        base = parts.index("com")
    except ValueError:
        return None, None
    package_parts = parts[base:-1]
    return ".".join(package_parts), "/".join(parts[:base + 1] + parts[base + 1:-1])


def java_structure_check(output: Path, files: dict[str, Path], plan: dict[str, Any],
                         errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> dict[str, Any]:
    java_files = {name: path for name, path in files.items() if name.endswith(".java")}
    packages = {}
    package_paths_ok = True
    type_names_ok = True
    lexical_ok = True
    test_mirror_ok = True
    production_packages = set()
    tests = []
    imports = []
    for relative, path in sorted(java_files.items()):
        text = path.read_text(encoding="utf-8")
        package_matches = JAVA_PACKAGE_DECL.findall(text)
        if len(package_matches) != 1:
            package_paths_ok = False
            errors.append({"check": "java-package", "message": f"Expected one package declaration in {relative}; found {len(package_matches)}."})
            continue
        declared = package_matches[0]
        expected_path = ".".join(PurePosixPath(relative).parts[3:-1])
        packages[relative] = declared
        if declared != expected_path:
            package_paths_ok = False
            errors.append({"check": "java-package-path", "message": f"{relative} declares {declared}, expected {expected_path}."})
        if not (declared == JAVA_PACKAGE or declared.startswith(JAVA_PACKAGE + ".")):
            package_paths_ok = False
            errors.append({"check": "base-package", "message": f"{relative} is outside {JAVA_PACKAGE}."})
        if relative.startswith("src/main/java/"):
            production_packages.add(declared)
        else:
            tests.append((relative, declared))
        type_matches = JAVA_TYPE.findall(text)
        expected_class = PurePosixPath(relative).stem
        if len(type_matches) != 1 or type_matches[0][1] != expected_class:
            type_names_ok = False
            errors.append({"check": "java-type-name", "message": f"{relative} must declare one top-level type named {expected_class}."})
        scrubbed = strip_java_noncode(text)
        stack = []
        pairs = {"}": "{", ")": "(", "]": "["}
        for char in scrubbed:
            if char in "{([":
                stack.append(char)
            elif char in pairs:
                if not stack or stack.pop() != pairs[char]:
                    lexical_ok = False
                    break
        if stack:
            lexical_ok = False
        if not lexical_ok:
            errors.append({"check": "java-delimiters", "message": f"Unbalanced Java delimiters in {relative}."})
        for imported in re.findall(r"(?m)^import[ \t]+(?:static[ \t]+)?([A-Za-z0-9_.*]+);", text):
            imports.append((relative, imported))
    for relative, declared in tests:
        if declared not in production_packages:
            test_mirror_ok = False
            errors.append({"check": "test-package-mirror", "message": f"Test package {declared} in {relative} has no matching production package."})

    imports_without_reference = all(not (item.startswith("com.claro.biometria.individual")
                                         or "biometria" in item.lower()
                                         or "ms-individual" in item.lower()) for _, item in imports)
    if not imports_without_reference:
        errors.append({"check": "reference-imports", "message": "A generated import references the reference project namespace."})
    suspicious = []
    for relative, path in sorted(files.items()):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in ("TODO", "FIXME", "UnsupportedOperationException"):
            if marker in text:
                suspicious.append({"path": relative, "marker": marker})
    api_texts = [java_files[name].read_text(encoding="utf-8") for name in java_files if name.endswith("Api.java")]
    if any(re.search(r"ResponseEntity\.(?:ok|status)\s*\(|return\s+new\s+\w*Response\s*\(", text)
           for text in api_texts):
        suspicious.append({"path": "src/main/java/.../controller", "marker": "behavior-bearing/hardcoded API response"})
    filter_path = "src/main/java/" + JAVA_PACKAGE_PATH + "/security/filter/JwtRequestFilter.java"
    if filter_path in files and re.search(r"\breturn\s+null\s*;", files[filter_path].read_text(encoding="utf-8")):
        warnings.append({"check": "technical-filter-null-return", "message": "The approved archetype JWT filter returns null when no bearer token is present; this is filter logic, not an API response placeholder."})
    return {
        "status": "passed" if package_paths_ok and type_names_ok and lexical_ok and test_mirror_ok and imports_without_reference else "failed",
        "javaFileCount": len(java_files),
        "packageDeclarationCount": len(packages),
        "packages": sorted(set(packages.values())),
        "packagePathMatches": package_paths_ok,
        "typeNamesMatchFileNames": type_names_ok,
        "balancedJavaDelimiters": lexical_ok,
        "testPackagesMirrorProduction": test_mirror_ok,
        "importsAreReferenceFree": imports_without_reference,
        "suspiciousMarkers": suspicious,
    }


def strip_java_noncode(text: str) -> str:
    out = []
    i = 0
    state = "code"
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if char == "/" and nxt == "/":
                state = "line"
                out.extend("  ")
                i += 2
                continue
            if char == "/" and nxt == "*":
                state = "block"
                out.extend("  ")
                i += 2
                continue
            if char == '"':
                state = "string"
                out.append(" ")
            elif char == "'":
                state = "char"
                out.append(" ")
            else:
                out.append(char)
        elif state == "line":
            if char == "\n":
                state = "code"
                out.append("\n")
            else:
                out.append(" ")
        elif state == "block":
            if char == "*" and nxt == "/":
                state = "code"
                out.extend("  ")
                i += 2
                continue
            out.append("\n" if char == "\n" else " ")
        else:
            if char == "\\":
                out.extend("  ")
                i += 2
                continue
            if (state == "string" and char == '"') or (state == "char" and char == "'"):
                state = "code"
            out.append(" ")
        i += 1
    return "".join(out)


def validate_pointer_contract(spec: dict[str, Any], plan: dict[str, Any], output_files: dict[str, Path],
                              errors: list[dict[str, str]]) -> dict[str, Any]:
    spec_ops = {str(op.get("operationId")): op for op in spec.get("operations") or []}
    plan_ops = (plan.get("api") or {}).get("operations") or []
    expected_paths = {(str(op.get("method")), str(op.get("path"))) for op in spec.get("operations") or []}
    plan_paths = {(str(op.get("method")), str(op.get("path"))) for op in plan_ops}
    api_paths = [path for path in output_files if path.endswith("Api.java")]
    api_text = output_files[api_paths[0]].read_text(encoding="utf-8") if len(api_paths) == 1 else ""
    route_pairs = {(method.upper(), path) for method, path in API_ROUTE.findall(api_text)}
    operations_ok = expected_paths == plan_paths == route_pairs and len(expected_paths) == 3 and len(api_paths) == 1
    if not operations_ok:
        errors.append({"check": "api-active-operations", "message": f"Active operation set mismatch: spec={sorted(expected_paths)}, plan={sorted(plan_paths)}, generated={sorted(route_pairs)}."})
    inactive_ops = (spec.get("inactive") or {}).get("operations") or []
    inactive_get_id = any(str(item.get("method")).upper() == "GET"
                          and str(item.get("path")) == "/api/v1/mailing/info/{id}" for item in inactive_ops)
    if inactive_get_id and ("GET", "/api/v1/mailing/info/{id}") in route_pairs:
        errors.append({"check": "inactive-operation", "message": "Inactive GET-by-id was found in generated API."})

    model_plans = {str(item["name"]): item for item in plan.get("models") or []}
    model_status = []
    for model_name, model in sorted(model_plans.items()):
        file_path = str(model.get("filePath") or "")
        model_file = output_files.get(file_path)
        if model_file is None:
            errors.append({"check": "contract-model-exists", "message": f"Planned model file is missing: {file_path}"})
            model_status.append({"name": model_name, "status": "missing"})
            continue
        pointer = str(model.get("traceability") or "")
        source_schema_pointer = pointer[:-len("/resolved")] if pointer.endswith("/resolved") else pointer
        try:
            schema_node = resolve_pointer(spec, pointer)
            source_schema = resolve_pointer(spec, source_schema_pointer)
        except (KeyError, IndexError, ValueError, TypeError):
            errors.append({"check": "contract-model-traceability", "message": f"Schema traceability does not resolve: {pointer}"})
            model_status.append({"name": model_name, "status": "invalid-traceability"})
            continue
        source = source_schema.get("source") if isinstance(source_schema, dict) and isinstance(source_schema.get("source"), dict) else {}
        reference = source.get("$ref")
        if not reference or str(reference).rsplit("/", 1)[-1] != model_name:
            errors.append({"check": "contract-model-source", "message": f"Model {model_name} does not trace to its declared schema reference at {source_schema_pointer}."})
        if not isinstance(schema_node, dict):
            errors.append({"check": "contract-model-schema", "message": f"Resolved model schema is not an object: {pointer}"})
            model_status.append({"name": model_name, "status": "invalid-schema"})
            continue
        props = schema_node.get("properties") or {}
        expected_fields = set(props)
        fields = {str(field["name"]): field for field in model.get("fields") or []}
        if set(fields) != expected_fields:
            errors.append({"check": "contract-model-fields", "message": f"Field mismatch for {model_name}: expected {sorted(expected_fields)}, planned {sorted(fields)}."})
        contract_required = set(schema_node.get("required") or [])
        src_text = model_file.read_text(encoding="utf-8")
        actual_field_matches = {name: typ.strip() for typ, name in JAVA_FIELD.findall(src_text)}
        if set(actual_field_matches) != expected_fields:
            errors.append({"check": "generated-model-fields", "message": f"Generated field mismatch for {model_name}: {sorted(actual_field_matches)}."})
        for name, field_schema in props.items():
            planned_field = fields.get(name)
            if not planned_field:
                continue
            is_required = name in contract_required
            java_type = schema_java_type(field_schema)
            if planned_field.get("required") != is_required or actual_field_matches.get(name) != java_type:
                errors.append({"check": "contract-model-field-shape", "message": f"{model_name}.{name} type/required state differs from service-spec.yml."})
            if planned_field.get("javaType") != java_type:
                errors.append({"check": "implementation-plan-model-shape", "message": f"Plan type for {model_name}.{name} differs from service-spec.yml."})
            field_match = re.search(rf"(?P<annotations>(?:[ \t]*@[A-Za-z_$][A-Za-z0-9_$]*(?:\([^\n]*\))?[ \t]*\n)*)[ \t]*private[ \t]+[^\n;]+[ \t]+{re.escape(name)}[ \t]*;", src_text)
            field_annotations = field_match.group("annotations") if field_match else ""
            for annotation in planned_field.get("validationAnnotations") or []:
                if annotation not in field_annotations:
                    errors.append({"check": "dto-validation", "message": f"Missing declared annotation {annotation} on {model_name}.{name}."})
            if ("@NotNull" in field_annotations) != is_required:
                errors.append({"check": "dto-requiredness", "message": f"Required/optional annotation mismatch on {model_name}.{name}."})
            enum_values = (field_schema.get("resolved") if isinstance(field_schema.get("resolved"), dict) else field_schema).get("enum")
            if enum_values and not all(java_string(value) in field_annotations for value in enum_values):
                # @Schema annotations are part of the field declaration and may include the full list rather than separate lines.
                marker = "@Schema(allowableValues = {" + ", ".join(java_string(value) for value in enum_values) + "})"
                if marker not in field_annotations:
                    errors.append({"check": "dto-enum", "message": f"Enum values are not preserved on {model_name}.{name}."})
        model_status.append({"name": model_name, "status": "passed", "fieldCount": len(expected_fields)})

    method_matches = {name: (return_type, params) for return_type, name, params in API_METHOD.findall(api_text)}
    api_validation_errors = []
    for operation in plan_ops:
        operation_id = str(operation.get("operationId"))
        spec_op = spec_ops.get(operation_id)
        if not spec_op:
            api_validation_errors.append(f"Unknown operationId {operation_id}.")
            continue
        method = method_matches.get(operation_id)
        if not method:
            api_validation_errors.append(f"API signature missing for {operation_id}.")
            continue
        return_type, method_params = method
        contract = spec_op.get("contract") or {}
        responses = contract.get("responses") or {}
        success_status = next((key for key in sorted(responses, key=str) if str(key).startswith("2")), None)
        if success_status is None:
            api_validation_errors.append(f"No success response is defined for {operation_id}.")
        else:
            success_schema, success_model = schema_from_content((responses[success_status].get("content") or {}))
            del success_schema
            if return_type != success_model or success_model not in model_plans:
                api_validation_errors.append(f"Response model mismatch for {operation_id}: {return_type} vs {success_model}.")
        param_entries = contract.get("parameters") or {}
        expected_bindings = []
        binding_kinds = {"path": "PathVariable", "query": "RequestParam", "header": "RequestHeader"}
        for loc in ("path", "query", "header"):
            for parameter in param_entries.get(loc) or []:
                expected_bindings.append((binding_kinds[loc], str(parameter.get("name")), bool(parameter.get("required"))))
        actual_bindings = [(kind, name, required == "true")
                           for kind, name, required in PARAM_BINDING.findall(method_params)]
        if sorted(expected_bindings) != sorted(actual_bindings):
            api_validation_errors.append(f"Parameter binding mismatch for {operation_id}.")
        request_body = contract.get("requestBody")
        body_match = BODY_BINDING.search(method_params)
        request_schema, request_model = schema_from_content((request_body or {}).get("content") or {}) if request_body else (None, None)
        del request_schema
        if (request_model is None) != (body_match is None):
            api_validation_errors.append(f"Request DTO presence mismatch for {operation_id}.")
        elif request_model and (body_match.group(2) != request_model or request_model not in model_plans):
            api_validation_errors.append(f"Request DTO reference mismatch for {operation_id}.")
        method_start = api_text.rfind("@ApiResponses", 0, api_text.find(f"{operation_id}(", 0))
        annotation_text = api_text[method_start:api_text.find(f"{operation_id}(", 0)] if method_start >= 0 else ""
        expected_statuses = {str(code) for code in responses}
        actual_statuses = set(re.findall(r"responseCode = \"([^\"]+)\"", annotation_text))
        if expected_statuses != actual_statuses:
            api_validation_errors.append(f"Response status mismatch for {operation_id}: {sorted(actual_statuses)} vs {sorted(expected_statuses)}.")
    if api_validation_errors:
        errors.extend({"check": "api-contract", "message": value} for value in api_validation_errors)

    return {
        "status": "passed" if operations_ok and not api_validation_errors else "failed",
        "activeOperations": [{"operationId": op.get("operationId"), "method": op.get("method"), "path": op.get("path")}
                             for op in plan_ops],
        "operationSetMatchesServiceSpec": operations_ok,
        "inactiveGetByIdExcluded": ("GET", "/api/v1/mailing/info/{id}") not in route_pairs,
        "apiDtoAndStatusChecks": "passed" if not api_validation_errors else "failed",
        "modelCount": len(model_plans),
        "models": model_status,
    }


def validate(root: Path, yaml: Any) -> dict[str, Any]:
    try:
        spec, _ = read_yaml(root / SERVICE_SPEC, root, yaml)
        plan, _ = read_yaml(root / PLAN, root, yaml)
        parameters, _ = read_yaml(root / PARAMETERS, root, yaml)
        manifest, _ = read_yaml(root / MANIFEST_REL, root, yaml)
        build_report, _ = read_yaml(root / BUILD_REPORT, root, yaml)
        output = root / OUTPUT_REL
        if output.is_symlink() or not output.is_dir() or not output.resolve().is_relative_to(root):
            raise RuntimeError("Generated output directory is missing or unsafe.")
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        actual_files = {item.relative_to(output).as_posix(): item for item in output.rglob("*") if item.is_file()}
        actual_paths = set(actual_files)
        generated_manifest_paths = {str(item.get("path")) for item in manifest.get("generatedFiles") or []}
        authorized_groups = (plan.get("files") or {})
        plan_generated_paths = {str(item.get("path")) for key in ("generate", "archetypeCopy", "archetypeParameterize")
                                for item in (authorized_groups.get(key) or [])}
        planned_omit_entries = authorized_groups.get("omitUnresolved") or []
        planned_omitted_paths = {str(item.get("path")) for item in planned_omit_entries}
        manifest_omitted_paths = {str(item.get("path")) for item in manifest.get("omittedFiles") or []}
        unexpected = sorted(actual_paths - generated_manifest_paths - {MANIFEST_REL.name})
        unmaterialized_planned = sorted(plan_generated_paths - generated_manifest_paths)
        unauthorized_manifest = sorted(generated_manifest_paths - plan_generated_paths)
        if unexpected or unmaterialized_planned or unauthorized_manifest:
            errors.append({"check": "generated-inventory", "message": f"Unexpected={unexpected}; missing={unmaterialized_planned}; unauthorized={unauthorized_manifest}."})
        if manifest_omitted_paths != planned_omitted_paths:
            errors.append({"check": "omitted-inventory", "message": "Manifest omittedFiles do not match implementation-plan omitUnresolved."})
        omitted_present = []
        for raw in planned_omitted_paths:
            candidate_pattern = str(output / raw.replace("\\", "/"))
            if any(Path(match).exists() for match in __import__("glob").glob(candidate_pattern, recursive=True)):
                omitted_present.append(raw)
        if omitted_present:
            errors.append({"check": "omit-unresolved", "message": f"Plan-omitted output paths exist: {sorted(omitted_present)}."})
        generated_inventory = {
            "status": "passed" if not any(item["check"] in {"generated-inventory", "omitted-inventory", "omit-unresolved"} for item in errors) else "failed",
            "actualFileCount": len(actual_paths),
            "manifestGeneratedFileCount": len(generated_manifest_paths),
            "planAuthorizedFileCount": len(plan_generated_paths),
            "omittedPlanEntryCount": len(planned_omitted_paths),
            "unexpectedFiles": unexpected,
            "filesInOmitUnresolvedPresent": omitted_present,
        }

        java_result = java_structure_check(output, actual_files, plan, errors, warnings)
        api_result = validate_pointer_contract(spec, plan, actual_files, errors)

        # Reference leakage scan: only the generated output is searched; generic com.claro is permitted.
        leakage = []
        for relative, file in sorted(actual_files.items()):
            text = file.read_text(encoding="utf-8", errors="ignore")
            lowered = text.lower()
            for marker in ("com.claro.biometria.individual", "biometria", "ms-individual"):
                if marker in lowered:
                    leakage.append({"path": relative, "marker": marker})
        if leakage:
            errors.append({"check": "reference-leakage", "message": str(leakage)})

        suspicious_markers = []
        for relative, file in sorted(actual_files.items()):
            text = file.read_text(encoding="utf-8", errors="ignore")
            for marker in ("TODO", "FIXME", "UnsupportedOperationException"):
                if marker in text:
                    suspicious_markers.append({"path": relative, "marker": marker})
        api_files = [file for name, file in actual_files.items() if name.endswith("Api.java")]
        hardcoded_api_success = any(re.search(r"ResponseEntity\.(?:ok|status)\s*\(|return\s+new\s+\w*Response\s*\(",
                                              file.read_text(encoding="utf-8")) for file in api_files)
        if hardcoded_api_success:
            suspicious_markers.append({"path": "API interface", "marker": "hardcoded endpoint response"})
        if suspicious_markers:
            errors.extend({"check": "suspicious-placeholder", "message": f"{item['path']}: {item['marker']}"}
                          for item in suspicious_markers)

        forbidden_patterns = (r"@Entity\b", r"JpaRepository", r"CrudRepository", r"JdbcTemplate",
                              r"RetryTemplate", r"@Retryable", r"\bSELECT\s+.+\s+FROM\b",
                              r"\bINSERT\s+INTO\b", r"\bUPDATE\s+\w+\s+SET\b")
        forbidden_findings = []
        for relative, file in sorted(actual_files.items()):
            if any(segment in relative.lower() for segment in ("/repository/", "/entity/", "/client/", "/model/", "/mapper/", "/db/")):
                forbidden_findings.append({"path": relative, "finding": "forbidden component path"})
            if file.suffix == ".java":
                text = file.read_text(encoding="utf-8")
                for pattern in forbidden_patterns:
                    if re.search(pattern, text, re.I):
                        forbidden_findings.append({"path": relative, "finding": pattern})
        if forbidden_findings:
            errors.extend({"check": "forbidden-functional-implementation", "message": str(item)}
                          for item in forbidden_findings)

        unresolved_tokens = []
        parameter_tokens = set()
        # The generator's parameter token grammar is deliberately checked against output text; wrapper internals are exempt.
        reserved = {"__MVNW_ARG0_NAME__", "__MVNW_CMD__", "__MVNW_ERROR__"}
        for relative, file in sorted(actual_files.items()):
            text = file.read_text(encoding="utf-8", errors="ignore")
            for token in TOKEN_RE.findall(text):
                if token not in reserved:
                    parameter_tokens.add(token)
                    unresolved_tokens.append({"path": relative, "token": token})
        if unresolved_tokens:
            errors.append({"check": "unresolved-placeholders", "message": str(unresolved_tokens)})

        output_paths = set(actual_paths)
        pom_coordinates = {}
        settings_root = None
        wrapper_properties = {}
        config_errors = []
        try:
            pom_root = ET.parse(output / "pom.xml").getroot()
            maven_ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            for name in ("groupId", "artifactId", "version"):
                element = pom_root.find(f"m:{name}", maven_ns)
                pom_coordinates[name] = (element.text or "").strip() if element is not None else None
            ET.parse(output / "settings.xml")
            settings_root = ET.parse(output / "settings.xml").getroot()
            wrapper_lines = (output / ".mvn/wrapper/maven-wrapper.properties").read_text(encoding="utf-8").splitlines()
            wrapper_properties = dict(line.split("=", 1) for line in wrapper_lines if "=" in line)
        except (ET.ParseError, OSError, ValueError) as exc:
            config_errors.append(str(exc))
        resolved_parameters = {str(item.get("name")): item.get("value") for item in parameters.get("resolved") or []}
        approved_coordinates_match = (pom_coordinates.get("groupId") == resolved_parameters.get("group_id")
                                      and pom_coordinates.get("version") == resolved_parameters.get("project_version"))
        config = {
            "status": "passed",
            "pomXml": "valid XML" if "pom.xml" in output_paths else "missing",
            "settingsXml": "valid XML" if "settings.xml" in output_paths else "missing",
            "coordinates": {"groupId": pom_coordinates.get("groupId"), "version": pom_coordinates.get("version"),
                            "matchApprovedParameters": approved_coordinates_match},
            "credentialsEmbedded": bool(settings_root.findall("{http://maven.apache.org/SETTINGS/1.0.0}servers/server")) if settings_root is not None else None,
            "wrapperFilesPresent": all(name in output_paths for name in ("mvnw", "mvnw.cmd", ".mvn/wrapper/maven-wrapper.properties")),
            "wrapperConfiguration": {"wrapperVersion": wrapper_properties.get("wrapperVersion"),
                                      "distributionType": wrapper_properties.get("distributionType"),
                                      "distributionUrl": wrapper_properties.get("distributionUrl")},
            "checkstylePresent": "src/main/resources/checkstyle.xml" in output_paths,
            "applicationProperties": {"present": "src/main/resources/application.properties" in output_paths,
                                      "expectedOmittedParameters": ["jwt_roles_claim"]},
            "logback": {"present": "src/main/resources/logback.xml" in output_paths,
                        "expectedOmittedParameters": ["application_log_level", "corporate_logger_level", "http_log_level", "log_time_zone", "root_log_level"]},
            "deploymentFilesAbsent": all(name not in output_paths for name in (
                "Dockerfile", "config/deployment.yml.j2", "config/ExternalSecret.yml.j2", "config/configmap.yml.j2")),
        }
        if config_errors or config["pomXml"] != "valid XML" or config["settingsXml"] != "valid XML":
            config["status"] = "failed"
            errors.append({"check": "build-xml", "message": "; ".join(config_errors) or "POM or settings XML file is missing."})
        if config["credentialsEmbedded"]:
            config["status"] = "failed"
            errors.append({"check": "credentials", "message": "settings.xml contains Maven server credential entries."})
        if not approved_coordinates_match:
            config["status"] = "failed"
            errors.append({"check": "maven-coordinates", "message": "POM groupId/version differ from approved generation parameters."})
        if (wrapper_properties.get("wrapperVersion") != "3.3.4"
                or wrapper_properties.get("distributionType") != "only-script"
                or "apache-maven/3.9.12/" not in str(wrapper_properties.get("distributionUrl"))):
            config["status"] = "failed"
            errors.append({"check": "maven-wrapper", "message": "Wrapper files or wrapper.properties do not match the approved archetype baseline."})
        if not all(config[key] for key in ("wrapperFilesPresent", "checkstylePresent", "deploymentFilesAbsent")):
            config["status"] = "failed"
            errors.append({"check": "configuration-files", "message": "Expected wrapper/checkstyle files or omission of deployment artifacts is inconsistent."})
        for omission_key in ("applicationProperties", "logback"):
            expected = set(config[omission_key]["expectedOmittedParameters"])
            manifest_omission = next((item for item in manifest.get("omittedFiles") or []
                                      if item.get("path") == ("src/main/resources/application.properties" if omission_key == "applicationProperties" else "src/main/resources/logback.xml")), None)
            if config[omission_key]["present"] or not manifest_omission or not expected.issubset(set(manifest_omission.get("missingParameters") or [])):
                config["status"] = "failed"
                errors.append({"check": "omitted-runtime-configuration", "message": f"{omission_key} omission or its parameter reasons are inconsistent."})

        build = build_report.get("build") or {}
        build_readiness = build_report.get("readiness") or {}
        if (build.get("verificationStatus") != "deferred-external-prerequisite"
                or build_readiness.get("buildVerified") is not False
                or not build_readiness.get("externalPrerequisiteRequired")):
            errors.append({"check": "build-deferred-status", "message": "Maven build report does not preserve deferred external-prerequisite status."})
        warnings.append({"check": "maven-verification", "message": "Maven verification is deferred until corporate VPN/network access to the approved mirror is available."})
        if suspicious_markers:
            warnings.extend({"check": "suspicious-marker", "message": f"{item['path']}: {item['marker']}"}
                            for item in suspicious_markers)

        report = {
            "validation": {
                "result": "failed" if errors else "passed",
                "generatedInventory": generated_inventory,
                "javaStructure": java_result,
                "apiContract": api_result,
                "models": {"status": "passed" if not any(item["check"].startswith("contract-model") or item["check"].startswith("generated-model") or item["check"].startswith("dto-") for item in errors) else "failed",
                           "count": len(plan.get("models") or []),
                           "names": sorted(item["name"] for item in plan.get("models") or [])},
                "forbiddenImplementation": {"status": "passed" if not forbidden_findings else "failed",
                                            "findings": forbidden_findings},
                "referenceLeakage": {"status": "passed" if not leakage else "failed", "findings": leakage},
                "unresolvedPlaceholders": {"status": "passed" if not unresolved_tokens else "failed",
                                           "findings": unresolved_tokens,
                                           "wrapperInternalIdentifiersExempted": sorted(reserved)},
                "configuration": config,
            },
            "build": {"configured": True, "verified": False,
                      "verificationStatus": "deferred-external-prerequisite",
                      "externalPrerequisite": "corporate VPN/network access to the approved Maven mirror"},
            "issues": {"errors": sorted(errors, key=lambda item: (item.get("check", ""), item.get("message", ""))),
                       "warnings": sorted(warnings, key=lambda item: (item.get("check", ""), item.get("message", "")))},
            "readiness": {
                "scaffoldStructurallyValidated": not errors,
                "buildVerified": False,
                "strictImplementationReady": (plan.get("readiness") or {}).get("strictImplementationReady"),
                "deploymentGenerationReady": (plan.get("readiness") or {}).get("deploymentGenerationReady"),
                "sourceGenerationReady": (plan.get("readiness") or {}).get("sourceGenerationReady"),
                "sourceCorrectionRequired": bool(errors),
            },
        }
        return report
    except (OSError, KeyError, IndexError, TypeError, ValueError, RuntimeError):
        raise


def main() -> int:
    root = Path.cwd().resolve()
    try:
        import yaml
        report = validate(root, yaml)
        payload = dump_yaml(report, yaml)
        target = root / REPORT
        if target.is_symlink() or target.parent.resolve() != (root / ".factory").resolve():
            raise RuntimeError("Offline report must be a regular file directly under .factory/.")
        temp = None
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".offline-validation-", delete=False) as stream:
                temp = Path(stream.name)
                stream.write(payload)
            os.replace(temp, target)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        print({"result": report["validation"]["result"],
               "generatedFiles": report["validation"]["generatedInventory"]["actualFileCount"],
               "errors": len(report["issues"]["errors"]), "warnings": len(report["issues"]["warnings"]),
               "sha256": sha256(payload)})
        return 0 if not report["issues"]["errors"] else 1
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f"validate_offline_scaffold.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
