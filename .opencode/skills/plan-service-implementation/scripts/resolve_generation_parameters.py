#!/usr/bin/env python3
"""Resolve generation parameters for scaffold or full functional planning."""

from __future__ import annotations

import argparse
import hashlib
import copy
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from build_implementation_plan import PlanError


ROOT = Path.cwd().resolve()
PLAN_PATH = Path(".factory/implementation-plan.yml")
PARAMETERS_PATH = Path(".factory/generation-parameters.yml")
from generation_context import resolve_archetype
TOKEN_RE = re.compile(r"__[A-Z0-9_]+__")
JAVA_SCOPES = ("src/main/java/", "src/test/java/")
BUILD_PATHS = {"pom.xml", "settings.xml"}
DEPLOYMENT_PATHS = {"Dockerfile", "config/deployment.yml.j2", "config/ExternalSecret.yml.j2",
                    "config/configmap.yml.j2"}
ENVIRONMENT_PARAMETERS = {
    "environment", "k8s_namespace", "log_time_zone", "secret_name",
    "vault_secret_path", "vault_secret_store_kind", "vault_secret_store_name",
}
SPECIFIC_ARTIFACT_PARAMETERS = {
    "application_log_level", "corporate_logger_level", "http_log_level", "jwt_roles_claim", "root_log_level",
}
MAVEN_BUILD_PARAMETERS = {
    "group_id", "project_version", "corporate_release_repository_id", "corporate_release_repository_url",
    "corporate_snapshot_repository_id", "corporate_snapshot_repository_url", "corporate_maven_mirror_id",
    "corporate_maven_mirror_of", "corporate_maven_mirror_url", "corporate_maven_profile_id",
    "corporate_plugin_repository_id", "corporate_plugin_repository_url",
}


class ResolutionError(Exception):
    pass


def yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ResolutionError("PyYAML must already be installed; dependencies are not installed dynamically.") from exc
    return yaml


def load_yaml(path: Path, yaml: Any) -> tuple[Any, bytes]:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file() or not resolved.is_relative_to(ROOT):
        raise ResolutionError(f"Missing or unsafe input: {path.as_posix()}")
    data = path.read_bytes()
    try:
        value = yaml.load(data, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise ResolutionError(f"Invalid YAML: {path.as_posix()}") from exc
    return value or {}, data


def dump_yaml(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def directory_fingerprint(path: Path) -> str:
    rows = []
    for file in sorted((entry for entry in path.rglob("*") if entry.is_file()),
                       key=lambda entry: entry.relative_to(path).as_posix()):
        if file.is_symlink():
            raise ResolutionError(f"Archetype contains a symlink: {file}")
        relative = file.relative_to(path).as_posix()
        rows.append(f"{relative}\0{digest(file.read_bytes())}\n")
    return digest("".join(rows).encode("utf-8"))


def classify(name: str) -> str:
    if name == "base_package_path":
        return "derivable"
    if name == "base_package":
        return "required-for-java-generation"
    if name in MAVEN_BUILD_PARAMETERS:
        return "required-for-build"
    if name in SPECIFIC_ARTIFACT_PARAMETERS:
        return "required-for-specific-artifact"
    if name in ENVIRONMENT_PARAMETERS:
        return "environment-only"
    return "deployment-only"


def put_atomic(path: Path, data: bytes) -> None:
    if path.is_symlink() or path.parent.resolve() != (ROOT / ".factory").resolve():
        raise ResolutionError(f"Output must be a regular file directly under .factory/: {path}")
    from artifact_integrity import write_atomic
    write_atomic(path, data)


def parameter_sources(archetype: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    parameters = archetype.get("parameters") or []
    by_name = {str(item["name"]): item for item in parameters}
    token_names = {str(item.get("token")): str(item["name"]) for item in parameters if item.get("token")}
    reserved = set(((archetype.get("parameter_token_policy") or {}).get("non_parameter_wrapper_identifiers")) or [])
    for token in reserved:
        token_names.pop(str(token), None)
    return by_name, token_names


def unresolved_lookup(plan: dict[str, Any], prior_params: dict[str, Any] | None,
                      by_name: dict[str, dict[str, Any]], archetype: dict[str, Any]
                      ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    section = plan.get("parameters") or {}
    existing_unresolved = {str(item["name"]): dict(item) for item in section.get("unresolved", [])}
    prior_inventory = ((prior_params or {}).get("classification") or {}).get("previouslyUnresolved")
    if prior_inventory:
        previously_unresolved = [dict(item) for item in prior_inventory]
    else:
        previously_unresolved = [dict(item) for item in section.get("unresolved", [])]
    original_unresolved = [dict(item) for item in previously_unresolved]

    resolved = [dict(item) for item in section.get("resolved", [])]
    prior_resolved = (prior_params or {}).get("resolved") or []
    resolved_by_name = {str(item["name"]): dict(item) for item in resolved}
    for item in prior_resolved:
        resolved_by_name.setdefault(str(item["name"]), dict(item))

    approved_resolutions = (prior_params or {}).get("approvedResolutions") or []
    service_name = str((plan.get("service") or {}).get("name") or "")
    package_rule = archetype.get("package_naming") or {}
    for approved in approved_resolutions:
        if approved.get("targetServiceIdentity") != service_name:
            raise ResolutionError("Approved package resolution does not match the current service identity.")
    for approved in approved_resolutions:
        name = str(approved.get("name") or "")
        if name not in by_name or approved.get("targetServiceIdentity") != service_name:
            raise ResolutionError(f"Approved resolution has an unknown parameter or mismatched service identity: {name}")
        value = str(approved.get("value") or "")
        if name == "base_package":
            if not value or any(not re.fullmatch(r"[a-z][a-z0-9]*", part) for part in value.split(".")):
                raise ResolutionError("Approved base_package is not a lowercase dot-separated Java package.")
            prefix = str(approved.get("explicitlyRemovedPrefix") or "")
            if prefix and not service_name.startswith(prefix):
                raise ResolutionError("Explicitly removed package prefix is not a leading service-identity prefix.")
            identity = service_name[len(prefix):] if prefix else service_name
            normalization = package_rule.get("service_identity_normalization") or {}
            if normalization.get("lowercase") is not True or normalization.get("hyphen_separator") != "dot-separated-package-segments":
                raise ResolutionError("Archetype package identity normalization metadata is missing or unsupported.")
            expected = ".".join([str(package_rule.get("corporate_namespace"))]
                                + [segment.lower() for segment in identity.split("-")]
                                + [str(package_rule.get("technical_suffix"))])
            if value != expected:
                raise ResolutionError("Approved base_package does not follow the archetype naming rule and target override.")
        resolved_by_name[name] = {
            **by_name[name], "value": value, "status": "resolved-by-explicit-user-instruction",
            "classification": "derivable", "resolution": approved.get("resolution"),
            "source": approved.get("provenance", "explicit current user instruction"),
            "traceability": "generation-parameters.yml#/approvedResolutions",
            "provenance": dict(approved),
        }
        original_unresolved = [item for item in original_unresolved if item.get("name") != name]

    approved_package = resolved_by_name.get("base_package")
    if approved_package and "base_package_path" in by_name:
        derivation_rule = package_rule.get("base_package_path_rule")
        if derivation_rule != "replace-dots-with-slashes":
            raise ResolutionError("Archetype does not declare the supported base_package_path derivation rule.")
        package_path = str(approved_package["value"]).replace(".", "/")
        resolved_by_name["base_package_path"] = {
            **by_name["base_package_path"], "value": package_path,
            "status": "resolved-by-archetype-rule", "classification": "derivable",
            "resolution": "Derived by replacing dots with slashes as declared by archetype package_naming.",
            "source": "generation-parameters.yml#/resolved/base_package",
            "traceability": "archetype.yml#/package_naming/base_package_path_rule",
        }
        original_unresolved = [item for item in original_unresolved if item.get("name") != "base_package_path"]

    parameter_indexes = {str(item.get("name")): index for index, item in enumerate(archetype.get("parameters") or [])}
    for unresolved in list(original_unresolved):
        name = str(unresolved.get("name"))
        parameter = by_name.get(name) or {}
        if name in resolved_by_name and resolved_by_name[name].get("value") is not None:
            original_unresolved = [item for item in original_unresolved if item.get("name") != name]
            continue
        derivation_rule = parameter.get("derivation_rule")
        if derivation_rule:
            upstream = resolved_by_name.get(str(derivation_rule))
            if not upstream or upstream.get("value") is None:
                continue
            value = upstream["value"]
            resolution = f"Derived from {derivation_rule} using the archetype-declared D-010 rule."
            classification = "derivable"
            status = "resolved-by-archetype-rule"
        elif "default_value" in parameter:
            value = copy.deepcopy(parameter["default_value"])
            resolution = "Applied the approved reusable default recorded in archetype.yml."
            classification = "archetype-default"
            status = "resolved-from-archetype-default"
        else:
            continue
        resolved_by_name[name] = {
            **parameter,
            "value": value,
            "status": status,
            "classification": classification,
            "resolution": resolution,
            "source": f"archetype.yml#/parameters/{parameter_indexes[name]}",
            "traceability": f"archetype.yml#/parameters/{parameter_indexes[name]}",
            "provenance": {"source": f"archetype.yml#/parameters/{parameter_indexes[name]}",
                           "approvedDecision": (parameter.get("source") or "archetype-declared default")},
        }
        original_unresolved = [item for item in original_unresolved if item.get("name") != name]

    jacoco = by_name.get("jacoco_exclusions")
    if jacoco and "jacoco_exclusions" in existing_unresolved:
        defaults = (((archetype.get("quality") or {}).get("jacoco") or {}).get("default_exclusions") or [])
        resolved_by_name["jacoco_exclusions"] = {
            **existing_unresolved["jacoco_exclusions"],
            "value": list(defaults),
            "source": "archetype.yml#/quality/jacoco/default_exclusions",
            "status": "resolved-with-unresolved-token-dependency",
            "resolution": "Applied the archetype-declared reusable JaCoCo default; its application-class exclusion retains the declared base-package token until base_package_path is supplied.",
            "unresolvedDependencies": ["base_package_path"],
            "classification": "archetype-default",
        }
        resolved_by_name["jacoco_exclusions"].pop("planningBlocker", None)
        original_unresolved = [item for item in original_unresolved if item.get("name") != "jacoco_exclusions"]
    jacoco_record = resolved_by_name.get("jacoco_exclusions")
    if jacoco_record:
        token_values = {str(parameter.get("token")): resolved_by_name.get(str(parameter.get("name")), {}).get("value")
                        for parameter in by_name.values() if parameter.get("token")}
        rendered_defaults = []
        pending_tokens = set()
        for default in jacoco_record.get("value") or []:
            rendered = str(default)
            for token in TOKEN_RE.findall(rendered):
                replacement = token_values.get(token)
                if isinstance(replacement, str):
                    rendered = rendered.replace(token, replacement)
                else:
                    pending_tokens.add(token)
            rendered_defaults.append(rendered)
        jacoco_record["value"] = rendered_defaults
        if pending_tokens:
            jacoco_record["status"] = "resolved-with-unresolved-token-dependency"
            jacoco_record["unresolvedDependencies"] = sorted(pending_tokens)
        else:
            jacoco_record["status"] = "resolved"
            jacoco_record.pop("unresolvedDependencies", None)
            jacoco_record.pop("planningBlocker", None)
            jacoco_record["resolution"] = "Applied the archetype-declared exclusions and substituted the resolved technical identifiers."

    resolved_names = set(resolved_by_name)
    original_unresolved = [item for item in original_unresolved if item.get("name") not in resolved_names]

    return existing_unresolved, original_unresolved, list(resolved_by_name.values()), previously_unresolved


def render_target_path(value: str, token_names: dict[str, str], resolved_by_name: dict[str, dict[str, Any]]) -> str:
    result = value
    for token in TOKEN_RE.findall(value):
        name = token_names.get(token)
        record = resolved_by_name.get(name or "")
        if record is not None and isinstance(record.get("value"), str):
            result = result.replace(token, record["value"])
    return result


def file_parameters(entry: dict[str, Any], token_names: dict[str, str], root: Path) -> list[str]:
    source = str(entry.get("source") or "")
    prefix = resolve_archetype(root).as_posix() + "/"
    dependencies = set() if source.startswith(prefix) else set(map(str, entry.get("dependencies") or []))
    for candidate in (str(entry.get("path") or ""), str(entry.get("source") or "")):
        for token in TOKEN_RE.findall(candidate):
            if token in token_names:
                dependencies.add(token_names[token])
    if source.startswith(prefix):
        template_path = root / Path(source.replace("/", os.sep))
        if template_path.is_file() and not template_path.is_symlink():
            content = template_path.read_text(encoding="utf-8")
            for token in TOKEN_RE.findall(content):
                if token in token_names:
                    dependencies.add(token_names[token])
    return sorted(dependencies)


def collect_candidates(files: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = []
    functional_omitted = []
    for key in ("generate", "archetypeCopy", "archetypeParameterize"):
        for raw in files.get(key) or []:
            item = dict(raw)
            resolution = item.pop("parameterResolution", {}) or {}
            item["_originalStatus"] = resolution.get("originalGenerationStatus") or raw.get("generationStatus")
            candidates.append(item)
    for raw in files.get("omitUnresolved") or []:
        item = dict(raw)
        resolution = item.get("parameterResolution")
        if resolution and resolution.get("source") == "technical-parameter-resolution":
            item["_originalStatus"] = resolution.get("originalGenerationStatus")
            item.pop("parameterResolution", None)
            candidates.append(item)
        else:
            functional_omitted.append(item)
    return candidates, functional_omitted


def resolve(root: Path, yaml: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    ARCHETYPE_ROOT = resolve_archetype(root)
    plan_path = root / PLAN_PATH
    plan, _ = load_yaml(plan_path, yaml)
    archetype, _ = load_yaml(root / ARCHETYPE_ROOT / "archetype.yml", yaml)
    from archetype_contract import normalize, require_backend
    require_backend(normalize(archetype), mode='scaffold')
    plan.setdefault("inputs", {}).setdefault("archetype", {})["fingerprint"] = directory_fingerprint(root / ARCHETYPE_ROOT)
    prior_parameter_path = root / PARAMETERS_PATH
    prior_params = load_yaml(prior_parameter_path, yaml)[0] if prior_parameter_path.exists() else None
    by_name, token_names = parameter_sources(archetype)
    unresolved_by_name, original_unresolved, resolved_values, previously_unresolved = unresolved_lookup(
        plan, prior_params, by_name, archetype)
    unresolved_names = {str(item["name"]) for item in original_unresolved}

    classification_records = []
    resolved_by_name = {str(item.get("name")): item for item in resolved_values}
    for item in previously_unresolved:
        name = str(item["name"])
        resolved_record = resolved_by_name.get(name)
        category = ("archetype-default" if name == "jacoco_exclusions" and resolved_record
                    else (resolved_record.get("classification") if resolved_record else classify(name)))
        parameter = by_name.get(name) or {}
        classification_record = {
            **item,
            "classification": category,
            "resolutionStatus": (resolved_record.get("status") if resolved_record else "unresolved"),
            "validForm": parameter.get("valid_form", item.get("validForm")),
            "parameterSource": parameter.get("source", item.get("source")),
            "traceability": item.get("traceability") or f"archetype.yml#/parameters/{name}",
            "value": (copy.deepcopy(resolved_record.get("value")) if resolved_record else None),
            "resolution": (resolved_record.get("resolution") if resolved_record else item.get("planningBlocker")),
        }
        if resolved_record:
            classification_record.pop("planningBlocker", None)
            classification_record["status"] = resolved_record.get("status")
            if resolved_record.get("provenance"):
                classification_record["provenance"] = resolved_record["provenance"]
            if resolved_record.get("unresolvedDependencies"):
                classification_record["unresolvedDependencies"] = resolved_record["unresolvedDependencies"]
        classification_records.append(classification_record)
    classification_records.sort(key=lambda item: item["name"])

    plan_params = {**(plan.get("parameters") or {})}
    for item in resolved_values:
        name = str(item.get("name"))
        if "classification" not in item:
            if name in {"artifact_id", "service_name", "application_class"}:
                item["classification"] = "derivable"
                item["resolution"] = "Copied or deterministically derived from the approved service identity already recorded in implementation-plan.yml."
            elif name in {"sonar_coverage_exclusions", "jacoco_exclusions"}:
                item["classification"] = "archetype-default"
                item["resolution"] = "Applied the reusable default declared in archetype metadata."
            elif name in {"external_secret_additional_data", "specification_owned_application_properties"}:
                item["classification"] = "optional"
                item["resolution"] = "The authoritative implementation plan already records an empty value; no extra service-owned configuration is specified."
        item.setdefault("traceability", item.get("source") or item.get("sourcePath"))
        item["resolutionStatus"] = item.get("status", "resolved")
        if item.get("status") == "resolved":
            item.pop("planningBlocker", None)
            item.pop("unresolvedDependencies", None)
    resolved_values.sort(key=lambda item: item.get("name", ""))
    resolved_by_name = {str(item.get("name")): item for item in resolved_values}
    if resolved_by_name.get("base_package"):
        plan.setdefault("service", {})["package"] = resolved_by_name["base_package"]["value"]
    if resolved_by_name.get("base_package_path"):
        plan.setdefault("service", {})["packagePath"] = resolved_by_name["base_package_path"]["value"]
    if resolved_by_name.get("group_id"):
        plan.setdefault("service", {})["groupId"] = resolved_by_name["group_id"]["value"]
    if resolved_by_name.get("project_version"):
        plan.setdefault("service", {})["projectVersion"] = resolved_by_name["project_version"]["value"]
    plan_params["resolved"] = resolved_values
    unresolved_records = []
    for item in original_unresolved:
        name = str(item["name"])
        enriched = dict(item)
        enriched["classification"] = classify(name)
        enriched["status"] = "unresolved"
        enriched["resolutionStatus"] = "unresolved"
        enriched["requiredBy"] = []
        unresolved_records.append(enriched)
    plan_params["unresolved"] = sorted(unresolved_records, key=lambda item: item["name"])
    plan["parameters"] = plan_params

    files = dict(plan.get("files") or {})
    candidates, functional_omitted = collect_candidates(files)
    updated_groups: dict[str, list[dict[str, Any]]] = {
        "generate": [], "archetypeCopy": [], "archetypeParameterize": [],
    }
    technical_omitted = []
    file_dependency_entries = []
    dependencies_by_parameter: dict[str, list[str]] = {name: [] for name in by_name}
    for entry in candidates:
        original_status = str(entry.pop("_originalStatus", entry.get("generationStatus")))
        dependencies = file_parameters(entry, token_names, root)
        entry["dependencies"] = dependencies
        missing = sorted(name for name in dependencies if name in unresolved_names)
        entry["path"] = render_target_path(str(entry.get("path") or ""), token_names, resolved_by_name)
        for name in dependencies:
            dependencies_by_parameter.setdefault(name, []).append(str(entry.get("path")))
        source_path = str(entry.get("path") or "")
        is_java = source_path.endswith(".java") or source_path.startswith(JAVA_SCOPES)
        blocks_java = is_java and any(classify(name) == "required-for-java-generation" or name == "base_package_path"
                                      for name in missing)
        blocks_build = source_path in BUILD_PATHS and bool(missing)
        blocks_deployment = source_path in DEPLOYMENT_PATHS and bool(missing)
        file_dependency_entries.append({
            "path": source_path,
            "previousGenerationStatus": original_status,
            "requiredParameters": [{
                "name": name,
                "classification": "archetype-default" if name == "jacoco_exclusions" and name not in unresolved_names else classify(name),
                "resolved": name not in unresolved_names,
            } for name in dependencies],
            "missingParameters": missing,
            "blocksJavaGeneration": blocks_java,
            "blocksBuildExecution": blocks_build,
            "blocksDeploymentGeneration": blocks_deployment,
        })
        if missing:
            entry["generationStatus"] = "omit-unresolved"
            entry["parameterResolution"] = {
                "source": "technical-parameter-resolution",
                "originalGenerationStatus": original_status,
                "missingParameters": missing,
                "blockingScopes": sorted({"required-for-java-generation" if name == "base_package_path" else classify(name)
                                          for name in missing}),
                "reason": "This file needs unresolved archetype parameters; unrelated files remain independently eligible.",
            }
            technical_omitted.append(entry)
        else:
            entry["generationStatus"] = original_status
            entry.pop("parameterResolution", None)
            effective_status = original_status
            template_prefix = ARCHETYPE_ROOT.as_posix() + "/template/"
            source_path = str(entry.get("source") or "")
            if source_path.startswith(template_prefix):
                template_relative = "template/" + source_path[len(template_prefix):]
                inventory_entry = next((value for value in (archetype.get("template_inventory") or [])
                                        if value.get("path") == template_relative), None)
                if inventory_entry is None:
                    raise ResolutionError(f"Template file is absent from archetype inventory: {template_relative}")
                effective_status = ("archetype-parameterize" if dependencies or inventory_entry.get("classification") == "parameterized"
                                    else "archetype-copy")
            entry["generationStatus"] = effective_status
            group = {"generate": "generate", "archetype-copy": "archetypeCopy",
                     "archetype-parameterize": "archetypeParameterize"}.get(effective_status)
            if group is None:
                raise ResolutionError(f"Unsupported generationStatus for {source_path}: {original_status}")
            updated_groups[group].append(entry)

    for name, item in unresolved_by_name.items():
        for file_name in sorted(set(dependencies_by_parameter.get(name, []))):
            # requiredBy is used in both the parameter summary and per-file inventory.
            match = next((row for row in unresolved_records if row["name"] == name), None)
            if match is not None:
                match["requiredBy"].append(file_name)
    for item in unresolved_records:
        item["requiredBy"] = sorted(set(item["requiredBy"]))

    # Contract Java items mirror the file plan and carry the same parameter gate.
    for item in functional_omitted:
        item["path"] = render_target_path(str(item.get("path") or ""), token_names, resolved_by_name)
    status_by_path = {item["path"]: item for item in updated_groups["generate"] +
                      updated_groups["archetypeParameterize"] + technical_omitted}
    for model in plan.get("models") or []:
        model_file = f"src/main/java/__BASE_PACKAGE_PATH__/dto/{'enum' if model.get('kind') == 'enum' else ('request' if set(model.get('requestResponseScope') or []) == {'request'} else 'response' if set(model.get('requestResponseScope') or []) == {'response'} else 'contract')}/{model['name']}.java"
        model_file = render_target_path(model_file, token_names, resolved_by_name)
        gate = status_by_path.get(model_file)
        if gate:
            model["filePath"] = model_file
            model["generationStatus"] = gate["generationStatus"]
            if gate.get("parameterResolution"):
                model["missingParameters"] = gate["parameterResolution"]["missingParameters"]
    api_file = (plan.get("api") or {}).get("interfaceFile")
    api_file = render_target_path(str(api_file or ""), token_names, resolved_by_name)
    if api_file:
        plan["api"]["interfaceFile"] = api_file
    api_gate = status_by_path.get(api_file)
    if api_gate:
        plan["api"]["interfaceGenerationStatus"] = api_gate["generationStatus"]
        if api_gate.get("parameterResolution"):
            plan["api"]["interfaceMissingParameters"] = api_gate["parameterResolution"]["missingParameters"]
    tests = (plan.get("tests") or {}).get("structural") or []
    for test in tests:
        test["path"] = render_target_path(str(test.get("path") or ""), token_names, resolved_by_name)
        gate = status_by_path.get(test.get("path"))
        if gate:
            test["generationStatus"] = gate["generationStatus"]
            if gate.get("parameterResolution"):
                test["missingParameters"] = gate["parameterResolution"]["missingParameters"]

    for operation in (plan.get("unresolvedImplementation") or {}).get("operations", []):
        operation["blockedArtifacts"] = [render_target_path(str(value), token_names, resolved_by_name)
                                          for value in operation.get("blockedArtifacts") or []]

    files["generate"] = updated_groups["generate"]
    files["archetypeCopy"] = updated_groups["archetypeCopy"]
    files["archetypeParameterize"] = updated_groups["archetypeParameterize"]
    files["omitUnresolved"] = functional_omitted + sorted(technical_omitted, key=lambda item: item["path"])
    plan["files"] = files

    java_blockers = sorted(name for name in unresolved_names
                           if classify(name) == "required-for-java-generation" or name == "base_package_path")
    build_blockers = sorted(name for name in unresolved_names if name in MAVEN_BUILD_PARAMETERS or name == "base_package_path")
    deployment_blockers = sorted(name for name in unresolved_names
                                 if classify(name) in {"deployment-only", "environment-only"})
    source_ready = not java_blockers and not any(row["blocksJavaGeneration"] and row["missingParameters"]
                                                 for row in file_dependency_entries)
    build_ready = not build_blockers and not any(row["blocksBuildExecution"] and row["missingParameters"]
                                                 for row in file_dependency_entries)
    deployment_ready = not deployment_blockers and not any(row["blocksDeploymentGeneration"] and row["missingParameters"]
                                                           for row in file_dependency_entries)
    eligible_paths = {item["path"] for group in updated_groups.values() for item in group}
    build_file_ready = {"pom.xml", "settings.xml"} <= eligible_paths
    plan["generation"] = {
        **(plan.get("generation") or {}),
        "sourceGenerationReady": source_ready,
        "buildFileGenerationReady": build_file_ready,
        "buildExecutionReady": build_ready,
        "deploymentGenerationReady": deployment_ready,
        "scaffoldCodeGenerationCanBegin": source_ready,
        "buildFileGenerationReason": ("pom.xml and settings.xml are present in the parameter-complete file plan."
                                       if build_file_ready else "pom.xml and/or settings.xml still have unresolved required parameters."),
        "buildExecutionReason": (
            "Maven execution is blocked until project coordinates and the declared corporate Maven repository, mirror, profile, and plugin-repository values are supplied. The approved archetype POM includes com.claro.common:claro-common-logger, whose resolution requires approved corporate repository access; no URL or credential is inferred."
            if not build_ready else "Maven project coordinates and approved repository/plugin configuration are resolved. Execution requires network/VPN reachability to the configured private Maven endpoints for corporate dependencies."),
        "deploymentGenerationReason": (
            "Docker and Kubernetes/ExternalSecret templates remain omitted until their image, infrastructure, environment, and Vault parameters are supplied."
            if not deployment_ready else "All required deployment parameters are resolved."),
        "partialMaterializationReady": bool(updated_groups["archetypeCopy"] or updated_groups["archetypeParameterize"] or updated_groups["generate"]),
        "eligibleFiles": [item["path"] for group in updated_groups.values() for item in group],
        "reason": ("Java scaffold source generation is ready; build/deployment inputs are reported separately."
                   if source_ready else "Java source generation is blocked by unresolved package parameters; unrelated safe archetype files may be materialized."),
    }
    plan["generationParameters"] = {
        "path": PARAMETERS_PATH.as_posix(),
        "sourceGenerationReady": source_ready,
        "buildFileGenerationReady": build_file_ready,
        "buildExecutionReady": build_ready,
        "deploymentGenerationReady": deployment_ready,
        "previouslyUnresolvedCount": len(previously_unresolved),
        "stillUnresolvedCount": len(unresolved_records),
        "deterministicallyResolvedCount": len(resolved_values),
    }
    plan["readiness"] = {
        **(plan.get("readiness") or {}),
        "sourceGenerationReady": source_ready,
        "buildFileGenerationReady": build_file_ready,
        "buildExecutionReady": build_ready,
        "deploymentGenerationReady": deployment_ready,
    }
    for quality_section in ("jacoco", "sonar"):
        quality = ((plan.get("quality") or {}).get(quality_section) or {})
        if isinstance(quality.get("default_exclusions"), list):
            quality["default_exclusions"] = [render_target_path(str(value), token_names, resolved_by_name)
                                              for value in quality["default_exclusions"]]
    plan["planningBlockers"] = sorted({
        str(item.get("planningBlocker") or f"Required archetype parameter '{item['name']}' remains unresolved.")
        for item in unresolved_records
    })
    prior_stats = plan.get("statistics") or {}
    total_concrete = len(candidates)
    plan["statistics"] = {
        **prior_stats,
        "filesToGenerate": len(updated_groups["generate"]),
        "archetypeFilesCopied": len(updated_groups["archetypeCopy"]),
        "archetypeFilesParameterized": len(updated_groups["archetypeParameterize"]),
        "totalPlannedFiles": total_concrete,
        "filesOmittedUnresolved": len(technical_omitted),
        "functionalComponentsOmitted": len(functional_omitted),
        "filesEligibleForGeneration": sum(map(len, updated_groups.values())),
    }

    resolved_values.sort(key=lambda item: item.get("name", ""))
    unresolved_by_category: dict[str, list[dict[str, Any]]] = {
        "blocking": [], "build": [], "artifactSpecific": [], "deployment": [], "environment": [], "optional": [],
    }
    group_map = {
        "required-for-java-generation": "blocking", "derivable": "blocking", "required-for-build": "build",
        "required-for-specific-artifact": "artifactSpecific", "deployment-only": "deployment",
        "environment-only": "environment", "optional": "optional", "unresolved-blocking": "blocking",
    }
    for item in unresolved_records:
        unresolved_by_category[group_map[item["classification"]]].append(item)

    generation_parameters = {
        "service": {"name": (plan.get("service") or {}).get("name"),
                    "artifactId": (plan.get("service") or {}).get("artifactId"),
                    "package": (plan.get("service") or {}).get("package"),
                    "groupId": (plan.get("service") or {}).get("groupId"),
                    "projectVersion": (plan.get("service") or {}).get("projectVersion")},
        "approvedResolutions": (prior_params or {}).get("approvedResolutions") or [],
        "inputs": {"serviceSpec": plan["inputs"]["serviceSpec"], "archetype": plan["inputs"]["archetype"]},
        "mavenReferenceAssessment": (prior_params or {}).get("mavenReferenceAssessment") or {},
        "classification": {
            "previouslyUnresolvedCount": len(previously_unresolved),
            "classifiedCount": len(classification_records),
            "previouslyUnresolved": classification_records,
            "archetypeDefaultsApplied": [entry["name"] for entry in resolved_values
                                         if entry.get("classification") == "archetype-default"],
        },
        "resolved": resolved_values,
        "unresolved": unresolved_by_category,
        "fileDependencies": sorted(file_dependency_entries, key=lambda item: item["path"]),
        "readiness": {
            "sourceGenerationReady": source_ready,
            "buildFileGenerationReady": build_file_ready,
            "buildExecutionReady": build_ready,
            "deploymentGenerationReady": deployment_ready,
            "parametersBlockingJavaSourceGeneration": java_blockers,
            "parametersBlockingMavenBuildExecution": build_blockers,
            "buildExecutionReason": plan["generation"]["buildExecutionReason"],
            "deploymentGenerationReason": plan["generation"]["deploymentGenerationReason"],
            "deploymentOnlyUnresolved": [item["name"] for item in unresolved_records if item["classification"] == "deployment-only"],
            "environmentOnlyUnresolved": [item["name"] for item in unresolved_records if item["classification"] == "environment-only"],
            "filesEligibleForGeneration": plan["generation"]["eligibleFiles"],
        },
        "secretsStored": False,
        "validation": {"errors": [], "warnings": [
            "Source generation readiness is independent of Maven build and deployment readiness.",
            "No credential or secret value was requested, inferred, or stored.",
        ]},
    }
    return generation_parameters, plan


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
    parser.add_argument("--mode", choices=("scaffold", "full"))
    parser.add_argument("--planning-input", type=Path, default=Path(".factory/full-planning-input.yml"))
    args = parser.parse_args()
    try:
        yaml = yaml_module()
        # An explicit full run needs no pre-existing plan. Use the workspace-aware
        # loader when inferring mode (the sandbox's .factory is an approved link).
        from build_implementation_plan import read_yaml as workspace_yaml
        current = {}
        if args.mode is None:
            current, _ = workspace_yaml(ROOT / PLAN_PATH, ROOT, yaml)
        mode = args.mode or current.get("plan", {}).get("mode", "scaffold")
        if mode == "full":
            import profiles
            cfg = yaml.safe_load((ROOT / args.planning_input).read_bytes())
            resolve_archetype(ROOT, workspace=(ROOT / args.planning_input).parent,
                              explicit=cfg['target']['archetype'])
            arch = yaml.safe_load((ROOT / cfg['target']['archetype'] / 'archetype.yml').read_bytes())
            profile = profiles.resolve(arch)
            if profile == profiles.BATCH_SHELL:
                from batch_shell_plan import write_plan
                return write_plan(ROOT, yaml, args.planning_input)
            if profile == profiles.JDBC_WAR:
                from jdbc_war_plan import write_plan
                return write_plan(ROOT, yaml, args.planning_input)
            if profile == profiles.BFF:
                from bff_plan import write_plan
                return write_plan(ROOT, yaml, args.planning_input)
            from full_implementation_plan import write_full_plan
            return write_full_plan(ROOT, yaml, args.planning_input)
        generation_parameters, plan = resolve(ROOT, yaml)
        put_atomic(ROOT / PARAMETERS_PATH, dump_yaml(generation_parameters, yaml))
        plan_bytes = dump_yaml(plan, yaml)
        put_atomic(ROOT / PLAN_PATH, plan_bytes)
        print({
            "previouslyUnresolved": generation_parameters["classification"]["previouslyUnresolvedCount"],
            "resolved": len(generation_parameters["resolved"]),
            "stillUnresolved": sum(len(items) for items in generation_parameters["unresolved"].values()),
            "eligibleFiles": len(generation_parameters["readiness"]["filesEligibleForGeneration"]),
            "sourceGenerationReady": generation_parameters["readiness"]["sourceGenerationReady"],
            "buildExecutionReady": generation_parameters["readiness"]["buildExecutionReady"],
            "deploymentGenerationReady": generation_parameters["readiness"]["deploymentGenerationReady"],
            "planSha256": digest(plan_bytes),
            "generationParametersSha256": digest(dump_yaml(generation_parameters, yaml)),
        })
        return 0
    except (ResolutionError, PlanError, OSError, TypeError, ValueError, KeyError) as exc:
        print(f"resolve_generation_parameters.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
