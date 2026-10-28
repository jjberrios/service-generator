#!/usr/bin/env python3
"""Deterministically normalize an OpenAPI 3.x YAML or JSON document."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PARAMETER_LOCATIONS = ("path", "query", "header", "cookie")
SCHEMA_SCALAR_KEYS = (
    "$id",
    "$schema",
    "$anchor",
    "type",
    "format",
    "title",
    "description",
    "default",
    "example",
    "examples",
    "enum",
    "const",
    "nullable",
    "readOnly",
    "writeOnly",
    "deprecated",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "contentEncoding",
    "contentMediaType",
)


class NormalizationFailure(Exception):
    """Raised when the source cannot be parsed enough to normalize."""


class IssueCollector:
    def __init__(self) -> None:
        self.warnings: list[dict[str, str]] = []
        self.errors: list[dict[str, str]] = []
        self._seen: set[tuple[str, str, str, str]] = set()

    def add(self, severity: str, code: str, location: str, message: str) -> None:
        key = (severity, code, location, message)
        if key in self._seen:
            return
        self._seen.add(key)
        issue = {"code": code, "location": location, "message": message}
        (self.errors if severity == "error" else self.warnings).append(issue)

    def error(self, code: str, location: str, message: str) -> None:
        self.add("error", code, location, message)

    def warning(self, code: str, location: str, message: str) -> None:
        self.add("warning", code, location, message)

    def sorted_warnings(self) -> list[dict[str, str]]:
        return sorted(self.warnings, key=lambda item: (item["location"], item["code"], item["message"]))

    def sorted_errors(self) -> list[dict[str, str]]:
        return sorted(self.errors, key=lambda item: (item["location"], item["code"], item["message"]))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and normalize an OpenAPI 3.x YAML or JSON document."
    )
    parser.add_argument("input", type=Path, help="Source OpenAPI YAML or JSON file")
    parser.add_argument("output", type=Path, help="Destination normalized YAML file")
    return parser.parse_args()


def load_yaml_module() -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise NormalizationFailure(
            "PyYAML is required to parse YAML and emit normalized YAML. "
            "Install it in the managed environment before running this script; "
            "the script will not install packages dynamically."
        ) from exc
    return yaml


def find_repository_root() -> Path:
    script_path = Path(__file__).resolve()
    for candidate in script_path.parents:
        if (
            (candidate / "AGENTS.md").is_file()
            and (candidate / "input" / "contracts").is_dir()
            and (candidate / ".opencode").is_dir()
        ):
            return candidate
    raise NormalizationFailure(
        "Cannot locate the repository root containing AGENTS.md and input/contracts/."
    )


def is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def unique_key_yaml_loader(yaml_module: Any) -> Any:
    class UniqueKeySafeLoader(yaml_module.SafeLoader):
        pass

    def construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
        seen: dict[Any, Any] = {}
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = loader.construct_object(key_node, deep=False)
            try:
                duplicate = key in seen
            except TypeError as exc:
                raise yaml_module.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                first_mark = seen[key]
                raise yaml_module.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    (
                        f"found duplicate key {key!r}; first declared at "
                        f"line {first_mark.line + 1}, column {first_mark.column + 1}"
                    ),
                    key_node.start_mark,
                )
            seen[key] = key_node.start_mark
        return loader.construct_mapping(node, deep=deep)

    UniqueKeySafeLoader.add_constructor(
        yaml_module.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping,
    )
    return UniqueKeySafeLoader


def load_document(path: Path, yaml_module: Any) -> tuple[dict[str, Any], str, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NormalizationFailure(f"Cannot read source file '{path}': {exc}") from exc

    source_format = "json" if path.suffix.lower() == ".json" else "yaml"
    try:
        if source_format == "json":
            document = json.loads(raw.decode("utf-8-sig"))
        else:
            document = yaml_module.load(
                raw.decode("utf-8-sig"),
                Loader=unique_key_yaml_loader(yaml_module),
            )
    except (UnicodeDecodeError, json.JSONDecodeError, yaml_module.YAMLError) as exc:
        raise NormalizationFailure(f"Cannot parse source file '{path}': {exc}") from exc

    if not isinstance(document, dict):
        raise NormalizationFailure("The OpenAPI document root must be a mapping/object.")
    return document, source_format, raw


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): canonical(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def pointer_location(parts: list[str]) -> str:
    if not parts:
        return "#"
    encoded = [part.replace("~", "~0").replace("/", "~1") for part in parts]
    return "#/" + "/".join(encoded)


def resolve_json_pointer(document: dict[str, Any], reference: str) -> Any:
    if reference == "#":
        return document
    if not reference.startswith("#/"):
        raise ValueError("Only local '#/...' references are supported")
    current: Any = document
    for token in reference[2:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            raise KeyError(key)
    return current


def reference_target(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
) -> tuple[Any, dict[str, Any] | None]:
    if not isinstance(value, dict) or "$ref" not in value:
        return value, None
    reference = value.get("$ref")
    provenance: dict[str, Any] = {"kind": "local-reference", "$ref": reference, "resolved": False}
    siblings = {key: canonical(item) for key, item in value.items() if key != "$ref"}
    if siblings:
        provenance["siblings"] = siblings
        issues.warning(
            "reference_siblings_preserved",
            location,
            "A $ref has sibling fields; they are preserved without being merged into the target.",
        )
    if not isinstance(reference, str):
        issues.error("invalid_reference", f"{location}/$ref", "$ref must be a string.")
        provenance["kind"] = "invalid-reference"
        return {}, provenance
    if not reference.startswith("#"):
        issues.error(
            "external_reference_unsupported",
            f"{location}/$ref",
            f"External reference '{reference}' was preserved but not resolved; network access is disabled.",
        )
        provenance["kind"] = "external-reference"
        return {}, provenance
    try:
        target = resolve_json_pointer(document, reference)
    except (KeyError, ValueError) as exc:
        issues.error("unresolved_local_reference", f"{location}/$ref", f"Cannot resolve '{reference}': {exc}")
        return {}, provenance
    provenance["resolved"] = True
    return target, provenance


def validate_references(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    parts: list[str] | None = None,
) -> None:
    current_parts = parts or []
    if isinstance(value, dict):
        if "$ref" in value:
            reference = value["$ref"]
            location = pointer_location(current_parts + ["$ref"])
            if not isinstance(reference, str):
                issues.error("invalid_reference", location, "$ref must be a string.")
            elif not reference.startswith("#"):
                issues.error(
                    "external_reference_unsupported",
                    location,
                    f"External reference '{reference}' cannot be resolved because network access is disabled.",
                )
            else:
                try:
                    resolve_json_pointer(document, reference)
                except (KeyError, ValueError) as exc:
                    issues.error("unresolved_local_reference", location, f"Cannot resolve '{reference}': {exc}")
        for key, child in value.items():
            validate_references(child, document, issues, current_parts + [str(key)])
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_references(child, document, issues, current_parts + [str(index)])


def validate_parameters(
    values: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
) -> None:
    if values is None:
        return
    if not isinstance(values, list):
        issues.error("invalid_parameters", location, "parameters must be an array.")
        return
    for index, value in enumerate(values):
        item_location = f"{location}/{index}"
        target, _ = reference_target(value, document, issues, item_location)
        if not isinstance(target, dict):
            issues.error("invalid_parameter", item_location, "Parameter must be a mapping/object.")
            continue
        name = target.get("name")
        parameter_in = target.get("in")
        if not isinstance(name, str) or not name:
            issues.error("invalid_parameter_name", f"{item_location}/name", "Parameter name must be a non-empty string.")
        if parameter_in not in PARAMETER_LOCATIONS:
            issues.error("invalid_parameter_location", f"{item_location}/in", f"Parameter location must be one of {PARAMETER_LOCATIONS}.")
        if parameter_in == "path" and target.get("required") is not True:
            issues.error("path_parameter_not_required", f"{item_location}/required", "Path parameters must declare required: true.")
        if "schema" in target and "content" in target:
            issues.error("parameter_schema_and_content", item_location, "A parameter cannot declare both schema and content.")


def validate_document(document: dict[str, Any], issues: IssueCollector) -> None:
    validate_references(document, document, issues)
    version = document.get("openapi")
    if not isinstance(version, str):
        issues.error("missing_openapi_version", "#/openapi", "openapi must be a string.")
    elif not re.fullmatch(r"3(?:\.\d+){1,2}(?:[-+].*)?", version):
        issues.error("unsupported_openapi_version", "#/openapi", f"Expected OpenAPI 3.x, found '{version}'.")

    info = document.get("info")
    if not isinstance(info, dict):
        issues.error("invalid_info", "#/info", "info must be a mapping/object.")
    else:
        for field in ("title", "version"):
            if not isinstance(info.get(field), str) or not info.get(field):
                issues.error("missing_info_field", f"#/info/{field}", f"info.{field} must be a non-empty string.")

    paths = document.get("paths")
    if not isinstance(paths, dict):
        issues.error("invalid_paths", "#/paths", "paths must be a mapping/object.")
        return

    operation_ids: dict[str, str] = {}
    for path_name in sorted(paths, key=str):
        path_item = paths[path_name]
        path_location = pointer_location(["paths", str(path_name)])
        if not isinstance(path_name, str) or not path_name.startswith("/"):
            issues.warning("unusual_path_key", path_location, "Path keys normally start with '/'.")
        path_item, _ = reference_target(path_item, document, issues, path_location)
        if not isinstance(path_item, dict):
            issues.error("invalid_path_item", path_location, "Path item must be a mapping/object.")
            continue
        validate_parameters(path_item.get("parameters"), document, issues, f"{path_location}/parameters")
        for method in HTTP_METHODS:
            if method not in path_item:
                continue
            operation = path_item[method]
            operation_location = f"{path_location}/{method}"
            if not isinstance(operation, dict):
                issues.error("invalid_operation", operation_location, "Operation must be a mapping/object.")
                continue
            operation_id = operation.get("operationId")
            if operation_id is None:
                issues.warning("missing_operation_id", operation_location, "operationId is not declared.")
            elif not isinstance(operation_id, str) or not operation_id:
                issues.error("invalid_operation_id", f"{operation_location}/operationId", "operationId must be a non-empty string.")
            elif operation_id in operation_ids:
                issues.error(
                    "duplicate_operation_id",
                    f"{operation_location}/operationId",
                    f"operationId '{operation_id}' is also declared at {operation_ids[operation_id]}.",
                )
            else:
                operation_ids[operation_id] = operation_location
            tags = operation.get("tags")
            if tags is not None and (
                not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)
            ):
                issues.error("invalid_operation_tags", f"{operation_location}/tags", "Operation tags must be an array of strings.")
            validate_parameters(operation.get("parameters"), document, issues, f"{operation_location}/parameters")
            if not isinstance(operation.get("responses"), dict):
                issues.error("invalid_responses", f"{operation_location}/responses", "Operation responses must be a mapping/object.")

    if "webhooks" in document:
        issues.warning("webhooks_not_normalized", "#/webhooks", "OpenAPI webhooks are preserved only as an unsupported top-level construct.")


def normalize_schema(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
    ref_stack: tuple[str, ...] = (),
) -> Any:
    if isinstance(value, bool):
        return {"source": {"kind": "explicit"}, "booleanSchema": value}
    target, provenance = reference_target(value, document, issues, location)
    if provenance is not None:
        result: dict[str, Any] = {"source": provenance}
        reference = provenance.get("$ref")
        if provenance.get("resolved") and isinstance(reference, str):
            if reference in ref_stack:
                result["recursive"] = True
                issues.warning("recursive_reference", location, f"Recursive reference '{reference}' was not expanded again.")
            else:
                result["resolved"] = normalize_schema(
                    target, document, issues, reference, ref_stack + (reference,)
                )
        return result
    if not isinstance(target, dict):
        issues.error("invalid_schema", location, "Schema must be a mapping/object or boolean.")
        return {"source": {"kind": "explicit"}, "raw": canonical(target)}

    result = {"source": {"kind": "explicit"}}
    for key in SCHEMA_SCALAR_KEYS:
        if key in target:
            result[key] = canonical(target[key])

    required = target.get("required")
    if required is not None:
        if isinstance(required, list) and all(isinstance(item, str) for item in required):
            result["required"] = sorted(required)
        else:
            issues.error("invalid_schema_required", f"{location}/required", "Schema required must be an array of property names.")
            result["required"] = canonical(required)

    properties = target.get("properties")
    if properties is not None:
        if isinstance(properties, dict):
            result["properties"] = {
                str(name): normalize_schema(schema, document, issues, f"{location}/properties/{name}", ref_stack)
                for name, schema in sorted(properties.items(), key=lambda item: str(item[0]))
            }
        else:
            issues.error("invalid_schema_properties", f"{location}/properties", "Schema properties must be a mapping/object.")
            result["properties"] = canonical(properties)

    for key in ("items", "not", "contains", "propertyNames", "if", "then", "else"):
        if key in target:
            result[key] = normalize_schema(target[key], document, issues, f"{location}/{key}", ref_stack)

    for key in ("allOf", "oneOf", "anyOf", "prefixItems"):
        if key in target:
            schemas = target[key]
            if isinstance(schemas, list):
                result[key] = [
                    normalize_schema(schema, document, issues, f"{location}/{key}/{index}", ref_stack)
                    for index, schema in enumerate(schemas)
                ]
            else:
                issues.error("invalid_schema_composition", f"{location}/{key}", f"{key} must be an array.")
                result[key] = canonical(schemas)

    if "additionalProperties" in target:
        additional = target["additionalProperties"]
        result["additionalProperties"] = (
            additional
            if isinstance(additional, bool)
            else normalize_schema(additional, document, issues, f"{location}/additionalProperties", ref_stack)
        )

    for key in ("dependentSchemas", "$defs"):
        if key in target and isinstance(target[key], dict):
            result[key] = {
                str(name): normalize_schema(schema, document, issues, f"{location}/{key}/{name}", ref_stack)
                for name, schema in sorted(target[key].items(), key=lambda item: str(item[0]))
            }

    if "discriminator" in target:
        result["discriminator"] = canonical(target["discriminator"])
    if "xml" in target:
        result["xml"] = canonical(target["xml"])
    if "externalDocs" in target:
        result["externalDocs"] = canonical(target["externalDocs"])

    handled = set(SCHEMA_SCALAR_KEYS) | {
        "$ref", "required", "properties", "items", "not", "contains", "propertyNames",
        "if", "then", "else", "allOf", "oneOf", "anyOf", "prefixItems",
        "additionalProperties", "dependentSchemas", "$defs", "discriminator", "xml", "externalDocs",
    }
    extensions = {key: canonical(item) for key, item in target.items() if str(key).startswith("x-")}
    if extensions:
        result["extensions"] = dict(sorted(extensions.items()))
    unsupported = {key: canonical(item) for key, item in target.items() if key not in handled and not str(key).startswith("x-")}
    if unsupported:
        result["unsupported"] = dict(sorted(unsupported.items()))
        for key in sorted(unsupported):
            issues.warning("schema_keyword_preserved", f"{location}/{key}", f"Schema keyword '{key}' was preserved without semantic normalization.")
    return result


def normalize_examples(value: Any) -> Any:
    return canonical(value)


def normalize_media_types(
    content: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
) -> dict[str, Any]:
    if content is None:
        return {}
    if not isinstance(content, dict):
        issues.error("invalid_content", location, "content must be a mapping/object.")
        return {}
    result: dict[str, Any] = {}
    for media_type, media in sorted(content.items(), key=lambda item: str(item[0])):
        media_location = f"{location}/{media_type}"
        if not isinstance(media, dict):
            issues.error("invalid_media_type", media_location, "Media type entry must be a mapping/object.")
            result[str(media_type)] = {"raw": canonical(media)}
            continue
        normalized: dict[str, Any] = {}
        if "schema" in media:
            normalized["schema"] = normalize_schema(media["schema"], document, issues, f"{media_location}/schema")
        for key in ("example", "examples", "encoding"):
            if key in media:
                normalized[key] = normalize_examples(media[key])
        extensions = {key: canonical(item) for key, item in media.items() if str(key).startswith("x-")}
        if extensions:
            normalized["extensions"] = dict(sorted(extensions.items()))
        result[str(media_type)] = normalized
    return result


def normalize_parameter(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
    scope: str | None = None,
) -> dict[str, Any]:
    target, provenance = reference_target(value, document, issues, location)
    source = provenance or {"kind": "explicit"}
    result: dict[str, Any] = {"source": source}
    if scope is not None:
        result["scope"] = scope
    if not isinstance(target, dict):
        issues.error("invalid_parameter", location, "Parameter must be a mapping/object.")
        result["raw"] = canonical(target)
        return result
    name = target.get("name")
    parameter_in = target.get("in")
    result.update(
        {
            "name": name if isinstance(name, str) else None,
            "in": parameter_in if isinstance(parameter_in, str) else None,
            "description": target.get("description"),
            "required": bool(target.get("required", False)),
            "requiredDeclared": "required" in target,
            "deprecated": bool(target.get("deprecated", False)),
        }
    )
    if not isinstance(name, str) or not name:
        issues.error("invalid_parameter_name", f"{location}/name", "Parameter name must be a non-empty string.")
    if parameter_in not in PARAMETER_LOCATIONS:
        issues.error("invalid_parameter_location", f"{location}/in", f"Parameter location must be one of {PARAMETER_LOCATIONS}.")
    if parameter_in == "path" and target.get("required") is not True:
        issues.error("path_parameter_not_required", f"{location}/required", "Path parameters must declare required: true.")
    for key in ("style", "explode", "allowEmptyValue", "allowReserved", "example", "examples"):
        if key in target:
            result[key] = canonical(target[key])
    if "schema" in target and "content" in target:
        issues.error("parameter_schema_and_content", location, "A parameter cannot declare both schema and content.")
    if "schema" in target:
        result["schema"] = normalize_schema(target["schema"], document, issues, f"{location}/schema")
    if "content" in target:
        result["content"] = normalize_media_types(target["content"], document, issues, f"{location}/content")
    return result


def normalize_request_body(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
) -> dict[str, Any]:
    target, provenance = reference_target(value, document, issues, location)
    result: dict[str, Any] = {"source": provenance or {"kind": "explicit"}}
    if not isinstance(target, dict):
        issues.error("invalid_request_body", location, "Request body must be a mapping/object.")
        result["raw"] = canonical(target)
        return result
    result["description"] = target.get("description")
    result["required"] = bool(target.get("required", False))
    result["requiredDeclared"] = "required" in target
    result["content"] = normalize_media_types(target.get("content"), document, issues, f"{location}/content")
    return result


def normalize_header(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
) -> dict[str, Any]:
    target, provenance = reference_target(value, document, issues, location)
    result: dict[str, Any] = {"source": provenance or {"kind": "explicit"}}
    if not isinstance(target, dict):
        issues.error("invalid_header", location, "Header must be a mapping/object.")
        result["raw"] = canonical(target)
        return result
    for key in ("description", "required", "deprecated", "style", "explode", "example", "examples"):
        if key in target:
            result[key] = canonical(target[key])
    if "schema" in target:
        result["schema"] = normalize_schema(target["schema"], document, issues, f"{location}/schema")
    if "content" in target:
        result["content"] = normalize_media_types(target["content"], document, issues, f"{location}/content")
    return result


def normalize_response(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
) -> dict[str, Any]:
    target, provenance = reference_target(value, document, issues, location)
    result: dict[str, Any] = {"source": provenance or {"kind": "explicit"}}
    if not isinstance(target, dict):
        issues.error("invalid_response", location, "Response must be a mapping/object.")
        result["raw"] = canonical(target)
        return result
    result["description"] = target.get("description")
    if not isinstance(target.get("description"), str):
        issues.error("missing_response_description", f"{location}/description", "Response description must be a string.")
    headers = target.get("headers", {})
    if isinstance(headers, dict):
        result["headers"] = {
            str(name): normalize_header(header, document, issues, f"{location}/headers/{name}")
            for name, header in sorted(headers.items(), key=lambda item: str(item[0]))
        }
    else:
        issues.error("invalid_response_headers", f"{location}/headers", "Response headers must be a mapping/object.")
        result["headers"] = {}
    result["content"] = normalize_media_types(target.get("content"), document, issues, f"{location}/content")
    if "links" in target:
        result["links"] = canonical(target["links"])
        issues.warning("links_preserved", f"{location}/links", "Response links were preserved without semantic normalization.")
    return result


def normalize_security_requirements(value: Any, issues: IssueCollector, location: str) -> list[dict[str, list[str]]]:
    if value is None:
        return []
    if not isinstance(value, list):
        issues.error("invalid_security", location, "security must be an array.")
        return []
    result: list[dict[str, list[str]]] = []
    for index, requirement in enumerate(value):
        item_location = f"{location}/{index}"
        if not isinstance(requirement, dict):
            issues.error("invalid_security_requirement", item_location, "Security requirement must be a mapping/object.")
            continue
        normalized: dict[str, list[str]] = {}
        for name, scopes in sorted(requirement.items(), key=lambda item: str(item[0])):
            if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
                issues.error("invalid_security_scopes", f"{item_location}/{name}", "Security scopes must be an array of strings.")
                normalized[str(name)] = []
            else:
                normalized[str(name)] = list(scopes)
        result.append(normalized)
    return result


def parameter_identity(parameter: dict[str, Any], fallback: str) -> tuple[str, str]:
    name = parameter.get("name")
    parameter_in = parameter.get("in")
    if isinstance(name, str) and isinstance(parameter_in, str):
        return name, parameter_in
    return fallback, "invalid"


def normalize_parameter_list(
    values: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
    scope: str,
) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, list):
        issues.error("invalid_parameters", location, "parameters must be an array.")
        return []
    return [
        normalize_parameter(value, document, issues, f"{location}/{index}", scope)
        for index, value in enumerate(values)
    ]


def normalize_operation(
    path: str,
    method: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
    document: dict[str, Any],
    issues: IssueCollector,
    root_security: Any,
    root_servers: Any,
    path_item_source: dict[str, Any] | None,
) -> dict[str, Any]:
    location = pointer_location(["paths", path, method])
    path_parameters = normalize_parameter_list(
        path_item.get("parameters"), document, issues,
        pointer_location(["paths", path, "parameters"]), "path-item",
    )
    operation_parameters = normalize_parameter_list(
        operation.get("parameters"), document, issues, f"{location}/parameters", "operation",
    )
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for index, parameter in enumerate(path_parameters):
        merged[parameter_identity(parameter, f"path-item-{index}")] = parameter
    for index, parameter in enumerate(operation_parameters):
        merged[parameter_identity(parameter, f"operation-{index}")] = parameter
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in PARAMETER_LOCATIONS}
    unsupported_parameters: list[dict[str, Any]] = []
    for identity in sorted(merged, key=lambda item: (item[1], item[0])):
        parameter = merged[identity]
        location_name = parameter.get("in")
        if location_name in grouped:
            grouped[location_name].append(parameter)
        else:
            unsupported_parameters.append(parameter)

    if "security" in operation:
        security = {
            "source": "operation",
            "requirements": normalize_security_requirements(operation.get("security"), issues, f"{location}/security"),
        }
    elif root_security is not None:
        security = {
            "source": "inherited-root",
            "requirements": normalize_security_requirements(root_security, issues, "#/security"),
        }
    else:
        security = {"source": "missing", "requirements": []}

    if "servers" in operation:
        servers = {
            "source": "operation",
            "values": normalize_servers(operation["servers"], issues, f"{location}/servers"),
        }
    elif "servers" in path_item:
        servers = {
            "source": "path-item",
            "values": normalize_servers(path_item["servers"], issues, f"{pointer_location(['paths', path])}/servers"),
        }
    elif root_servers is not None:
        servers = {
            "source": "inherited-root",
            "values": normalize_servers(root_servers, issues, "#/servers"),
        }
    else:
        servers = {"source": "missing", "values": []}

    responses: dict[str, Any] = {}
    raw_responses = operation.get("responses")
    if isinstance(raw_responses, dict):
        responses = {
            str(status): normalize_response(response, document, issues, f"{location}/responses/{status}")
            for status, response in sorted(raw_responses.items(), key=lambda item: str(item[0]))
        }

    result: dict[str, Any] = {
        "path": path,
        "method": method.upper(),
        "operationId": operation.get("operationId"),
        "tags": list(operation.get("tags", [])) if isinstance(operation.get("tags", []), list) else [],
        "summary": operation.get("summary"),
        "description": operation.get("description"),
        "deprecated": bool(operation.get("deprecated", False)),
        "pathItem": {
            "source": path_item_source or {"kind": "explicit"},
            "summary": path_item.get("summary"),
            "description": path_item.get("description"),
        },
        "parameters": grouped,
        "requestBody": (
            normalize_request_body(operation["requestBody"], document, issues, f"{location}/requestBody")
            if "requestBody" in operation else None
        ),
        "responses": responses,
        "security": security,
        "servers": servers,
    }
    path_item_extensions = {
        key: canonical(value) for key, value in path_item.items() if str(key).startswith("x-")
    }
    if path_item_extensions:
        result["pathItem"]["extensions"] = dict(sorted(path_item_extensions.items()))
    supported_path_item_keys = set(HTTP_METHODS) | {
        "$ref", "summary", "description", "servers", "parameters",
    }
    unsupported_path_item = {
        key: canonical(value)
        for key, value in path_item.items()
        if key not in supported_path_item_keys and not str(key).startswith("x-")
    }
    if unsupported_path_item:
        result["pathItem"]["unsupported"] = dict(sorted(unsupported_path_item.items()))
        for key in sorted(unsupported_path_item):
            issues.warning(
                "path_item_field_preserved",
                f"{pointer_location(['paths', path])}/{key}",
                f"Path-item field '{key}' was preserved without semantic normalization.",
            )
    if unsupported_parameters:
        result["unsupportedParameters"] = unsupported_parameters
    if "externalDocs" in operation:
        result["externalDocs"] = canonical(operation["externalDocs"])
    if "callbacks" in operation:
        result["callbacks"] = canonical(operation["callbacks"])
        issues.warning("callbacks_preserved", f"{location}/callbacks", "Callbacks were preserved without operation normalization.")
    extensions = {key: canonical(value) for key, value in operation.items() if str(key).startswith("x-")}
    if extensions:
        result["extensions"] = dict(sorted(extensions.items()))
    return result


def normalize_servers(value: Any, issues: IssueCollector, location: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        issues.error("invalid_servers", location, "servers must be an array.")
        return []
    servers: list[dict[str, Any]] = []
    for index, server in enumerate(value):
        server_location = f"{location}/{index}"
        if not isinstance(server, dict):
            issues.error("invalid_server", server_location, "Server must be a mapping/object.")
            continue
        url = server.get("url")
        if not isinstance(url, str):
            issues.error("invalid_server_url", f"{server_location}/url", "Server URL must be a string.")
        servers.append(
            {
                "url": url,
                "description": server.get("description"),
                "variables": canonical(server.get("variables", {})),
            }
        )
    return sorted(servers, key=lambda item: (str(item.get("url")), str(item.get("description"))))


def normalize_tags(value: Any, issues: IssueCollector) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        issues.error("invalid_tags", "#/tags", "tags must be an array.")
        return []
    tags: list[dict[str, Any]] = []
    for index, tag in enumerate(value):
        location = f"#/tags/{index}"
        if not isinstance(tag, dict) or not isinstance(tag.get("name"), str):
            issues.error("invalid_tag", location, "Tag must be an object with a string name.")
            continue
        normalized = {"name": tag["name"], "description": tag.get("description")}
        if "externalDocs" in tag:
            normalized["externalDocs"] = canonical(tag["externalDocs"])
        tags.append(normalized)
    return sorted(tags, key=lambda item: item["name"])


def normalize_component_map(
    values: Any,
    normalizer: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    component_name: str,
) -> dict[str, Any]:
    if values is None:
        return {}
    if not isinstance(values, dict):
        issues.error("invalid_components", f"#/components/{component_name}", f"components.{component_name} must be a mapping/object.")
        return {}
    return {
        str(name): normalizer(value, document, issues, f"#/components/{component_name}/{name}")
        for name, value in sorted(values.items(), key=lambda item: str(item[0]))
    }


def normalize_security_schemes(
    values: Any,
    document: dict[str, Any],
    issues: IssueCollector,
) -> dict[str, Any]:
    if values is None:
        return {}
    if not isinstance(values, dict):
        issues.error("invalid_security_schemes", "#/components/securitySchemes", "securitySchemes must be a mapping/object.")
        return {}
    result: dict[str, Any] = {}
    for name, value in sorted(values.items(), key=lambda item: str(item[0])):
        location = f"#/components/securitySchemes/{name}"
        target, provenance = reference_target(value, document, issues, location)
        result[str(name)] = {
            "source": provenance or {"kind": "explicit"},
            "definition": canonical(target) if isinstance(target, dict) else canonical(value),
        }
    return result


def normalize_generic_component(
    value: Any,
    document: dict[str, Any],
    issues: IssueCollector,
    location: str,
) -> dict[str, Any]:
    target, provenance = reference_target(value, document, issues, location)
    return {"source": provenance or {"kind": "explicit"}, "value": canonical(target)}


def normalize_document(
    document: dict[str, Any],
    source_path: Path,
    source_format: str,
    raw: bytes,
    issues: IssueCollector,
) -> dict[str, Any]:
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    paths = document.get("paths") if isinstance(document.get("paths"), dict) else {}
    root_security = document.get("security") if "security" in document else None
    operations: list[dict[str, Any]] = []
    for path, path_item in sorted(paths.items(), key=lambda item: str(item[0])):
        path_location = pointer_location(["paths", str(path)])
        path_item, path_item_source = reference_target(path_item, document, issues, path_location)
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if isinstance(operation, dict):
                operations.append(
                    normalize_operation(
                        str(path), method, path_item, operation, document, issues,
                        root_security, document.get("servers"), path_item_source,
                    )
                )

    components = document.get("components")
    if components is None:
        components = {}
    elif not isinstance(components, dict):
        issues.error("invalid_components", "#/components", "components must be a mapping/object.")
        components = {}

    normalized_components = {
        "schemas": normalize_component_map(components.get("schemas"), normalize_schema, document, issues, "schemas"),
        "parameters": normalize_component_map(components.get("parameters"), normalize_parameter, document, issues, "parameters"),
        "requestBodies": normalize_component_map(components.get("requestBodies"), normalize_request_body, document, issues, "requestBodies"),
        "responses": normalize_component_map(components.get("responses"), normalize_response, document, issues, "responses"),
        "headers": normalize_component_map(components.get("headers"), normalize_header, document, issues, "headers"),
        "examples": normalize_component_map(components.get("examples"), normalize_generic_component, document, issues, "examples"),
        "links": normalize_component_map(components.get("links"), normalize_generic_component, document, issues, "links"),
        "callbacks": normalize_component_map(components.get("callbacks"), normalize_generic_component, document, issues, "callbacks"),
        "pathItems": normalize_component_map(components.get("pathItems"), normalize_generic_component, document, issues, "pathItems"),
    }
    for component_name in ("links", "callbacks", "pathItems"):
        if normalized_components[component_name]:
            issues.warning(
                "component_kind_preserved",
                f"#/components/{component_name}",
                f"Component kind '{component_name}' was preserved without semantic normalization.",
            )
    known_component_keys = {
        "schemas", "parameters", "requestBodies", "responses", "headers", "examples",
        "securitySchemes", "links", "callbacks", "pathItems",
    }
    unsupported_components = {
        key: canonical(value)
        for key, value in components.items()
        if key not in known_component_keys and not str(key).startswith("x-")
    }
    if unsupported_components:
        normalized_components["unsupported"] = dict(sorted(unsupported_components.items()))
        for key in sorted(unsupported_components):
            issues.warning(
                "component_kind_unsupported",
                f"#/components/{key}",
                f"Unknown component kind '{key}' was preserved without semantic normalization.",
            )
    component_extensions = {
        key: canonical(value) for key, value in components.items() if str(key).startswith("x-")
    }
    if component_extensions:
        normalized_components["extensions"] = dict(sorted(component_extensions.items()))

    unknown_top_level = {
        key: canonical(value)
        for key, value in document.items()
        if key not in {
            "openapi", "info", "jsonSchemaDialect", "servers", "tags", "paths",
            "components", "security", "externalDocs",
        }
        and not str(key).startswith("x-")
    }
    if unknown_top_level:
        for key in sorted(unknown_top_level):
            issues.warning("top_level_construct_preserved", f"#/{key}", f"Top-level construct '{key}' was preserved without semantic normalization.")

    extensions = {key: canonical(value) for key, value in document.items() if str(key).startswith("x-")}
    normalized: dict[str, Any] = {
        "source": {
            "path": source_path.as_posix(),
            "format": source_format,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "openapiVersion": document.get("openapi"),
        },
        "service": {
            "title": info.get("title"),
            "version": info.get("version"),
            "description": info.get("description"),
            "jsonSchemaDialect": document.get("jsonSchemaDialect"),
        },
        "servers": normalize_servers(document.get("servers"), issues, "#/servers"),
        "tags": normalize_tags(document.get("tags"), issues),
        "operations": operations,
        "components": normalized_components,
        "security": {
            "schemes": normalize_security_schemes(components.get("securitySchemes"), document, issues),
            "root": {
                "source": "explicit" if "security" in document else "missing",
                "requirements": normalize_security_requirements(root_security, issues, "#/security"),
            },
        },
    }
    if "externalDocs" in document:
        normalized["service"]["externalDocs"] = canonical(document["externalDocs"])
    if extensions:
        normalized["extensions"] = dict(sorted(extensions.items()))
    if unknown_top_level:
        normalized["unsupported"] = dict(sorted(unknown_top_level.items()))
    normalized["validation"] = {
        "valid": not issues.errors,
        "warnings": issues.sorted_warnings(),
        "errors": issues.sorted_errors(),
    }
    return normalized


def write_yaml(
    path: Path,
    document: dict[str, Any],
    yaml_module: Any,
    output_root: Path,
) -> None:
    if not is_within(path, output_root) or path == output_root:
        raise NormalizationFailure(
            f"Output path must be a file under '{output_root}'."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml_module.safe_dump(
        document,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise NormalizationFailure(f"Cannot write normalized output '{path}': {exc}") from exc


def main() -> int:
    arguments = parse_arguments()
    try:
        repository_root = find_repository_root()
        contracts_root = (repository_root / "input" / "contracts").resolve()
        factory_root = (repository_root / ".factory").resolve()
        source = arguments.input.resolve()
        output = arguments.output.resolve()

        if source == output:
            raise NormalizationFailure("Input and output paths must be different; the source is read-only.")
        if not is_within(source, contracts_root):
            raise NormalizationFailure(
                f"Input path must be a file under '{contracts_root.relative_to(repository_root).as_posix()}/'."
            )
        if not source.is_file():
            raise NormalizationFailure(f"Source file does not exist or is not a regular file: '{source}'.")
        if not is_within(output, factory_root) or output == factory_root:
            raise NormalizationFailure(
                f"Output path must be a file under '{factory_root.relative_to(repository_root).as_posix()}/'."
            )
        yaml_module = load_yaml_module()
        document, source_format, raw = load_document(source, yaml_module)
        issues = IssueCollector()
        validate_document(document, issues)
        source_provenance = source.relative_to(repository_root)
        normalized = normalize_document(document, source_provenance, source_format, raw, issues)
        write_yaml(output, normalized, yaml_module, factory_root)
    except NormalizationFailure as exc:
        print(f"normalize_openapi.py: error: {exc}", file=sys.stderr)
        return 2

    warning_count = len(normalized["validation"]["warnings"])
    error_count = len(normalized["validation"]["errors"])
    print(
        f"Wrote '{output}' with {warning_count} warning(s) and {error_count} error(s).",
        file=sys.stderr,
    )
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
