#!/usr/bin/env python3
"""Materialize only newly authorized pom.xml/settings.xml and update the output manifest."""

from __future__ import annotations

import argparse
import hashlib
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
OUTPUT = Path("output/dom-document-mailing-info")
MANIFEST = ".generation-manifest.yml"
PARAM_RE = re.compile(r"__[A-Z0-9_]+__")


class BuildMaterializationError(Exception):
    pass


def yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise BuildMaterializationError("PyYAML must already be installed; dependencies are not installed dynamically.") from exc
    return yaml


def read_yaml(path: Path, root: Path, yaml: Any) -> tuple[Any, bytes]:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file() or not resolved.is_relative_to(root):
        raise BuildMaterializationError(f"Missing or unsafe approved input: {path.as_posix()}")
    payload = path.read_bytes()
    try:
        value = yaml.load(payload, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise BuildMaterializationError(f"Invalid YAML: {path.as_posix()}") from exc
    return value or {}, payload


def encode_yaml(value: Any, yaml: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True
    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=120).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_fingerprint(path: Path) -> str:
    entries = []
    for item in sorted((x for x in path.rglob("*") if x.is_file()),
                       key=lambda x: x.relative_to(path).as_posix()):
        if item.is_symlink():
            raise BuildMaterializationError(f"Archetype contains a symlink: {item}")
        entries.append(f"{item.relative_to(path).as_posix()}\0{sha256(item.read_bytes())}\n")
    return sha256("".join(entries).encode("utf-8"))


def child_text(element: ET.Element, local_name: str) -> str | None:
    for child in list(element):
        if child.tag.rsplit("}", 1)[-1] == local_name:
            return (child.text or "").strip()
    return None


def validate_build_plan(spec: dict[str, Any], plan: dict[str, Any], params: dict[str, Any], arch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    readiness = plan.get("readiness") or {}
    param_readiness = params.get("readiness") or {}
    if (plan.get("plan") or {}).get("mode") != "scaffold":
        raise BuildMaterializationError("Build files may be materialized only in scaffold mode.")
    for key in ("sourceGenerationReady", "buildFileGenerationReady", "buildExecutionReady"):
        if readiness.get(key) is not True or param_readiness.get(key) is not True:
            raise BuildMaterializationError(f"Required build-file readiness gate is not true: {key}")
    if readiness.get("strictImplementationReady") is not False or readiness.get("implementationReady") is not False:
        raise BuildMaterializationError("Strict implementation readiness must remain false.")
    if readiness.get("scaffoldImplementationReady") is not True:
        raise BuildMaterializationError("Scaffold readiness must remain true.")
    if readiness.get("deploymentGenerationReady") is not False or param_readiness.get("deploymentGenerationReady") is not False:
        raise BuildMaterializationError("Deployment readiness must remain false in this phase.")
    if plan.get("inputs", {}).get("archetype", {}).get("version") != (arch.get("archetype") or {}).get("version"):
        raise BuildMaterializationError("Implementation plan and archetype versions do not match.")
    resolved = {str(item.get("name")): item.get("value") for item in params.get("resolved") or []}
    if resolved.get("group_id") != resolved.get("base_package"):
        raise BuildMaterializationError("group_id is not the approved base_package value.")
    if resolved.get("project_version") != "1.0.0-SNAPSHOT":
        raise BuildMaterializationError("The approved initial project version is not resolved.")

    allowed_statuses = {}
    for group, expected_status in (("archetypeParameterize", "archetype-parameterize"),
                                   ("archetypeCopy", "archetype-copy")):
        for entry in (plan.get("files") or {}).get(group) or []:
            if entry.get("path") in {"pom.xml", "settings.xml"}:
                if entry.get("generationStatus") != expected_status:
                    raise BuildMaterializationError(f"Unexpected plan status for {entry.get('path')}")
                allowed_statuses[str(entry["path"])] = entry
    if set(allowed_statuses) != {"pom.xml", "settings.xml"}:
        raise BuildMaterializationError("Both pom.xml and settings.xml must be plan-authorized for materialization.")
    if any(entry.get("path") in allowed_statuses for entry in (plan.get("files") or {}).get("omitUnresolved") or []):
        raise BuildMaterializationError("A build file is still listed omit-unresolved.")
    for path, entry in allowed_statuses.items():
        if entry.get("parameterResolution", {}).get("missingParameters"):
            raise BuildMaterializationError(f"{path} still declares missing parameters.")
        missing = [name for name in entry.get("dependencies") or []
                   if name not in resolved or resolved[name] is None]
        if missing:
            raise BuildMaterializationError(f"{path} has unresolved dependencies: {sorted(missing)}")
    if (spec.get("service") or {}).get("name") != (plan.get("service") or {}).get("name"):
        raise BuildMaterializationError("service-spec and implementation-plan service names differ.")
    return allowed_statuses, resolved


def materialize_pom(source: bytes, arch: dict[str, Any], resolved: dict[str, Any]) -> bytes:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BuildMaterializationError("POM template must be UTF-8.") from exc

    # D-012: the JaCoCo/Sonar exclusions are part of the reference POM baseline (only package/class tokens are
    # substituted). The legacy marker-based replacement remains for archetype revisions that still carry it.
    if "__JACOCO_EXCLUSIONS__" in text:
        jacoco_values = resolved.get("jacoco_exclusions")
        if not isinstance(jacoco_values, list):
            raise BuildMaterializationError("JaCoCo exclusions are not a resolved list.")
        exclude_match = next((match for match in re.finditer(
            r"(?m)^([ \t]*)<excludes>\s*\n(.*?)^\1</excludes>", text, re.DOTALL)
            if "__JACOCO_EXCLUSIONS__" in match.group(2)), None)
        if not exclude_match:
            raise BuildMaterializationError("Could not locate the JaCoCo excludes block in the approved POM template.")
        inner_indent = exclude_match.group(1) + "    "
        exclude_xml = "\n".join(inner_indent + "<exclude>" + str(value) + "</exclude>" for value in jacoco_values)
        replacement = exclude_match.group(1) + "<excludes>\n" + exclude_xml + "\n" + exclude_match.group(1) + "</excludes>"
        text = text[:exclude_match.start()] + replacement + text[exclude_match.end():]

    by_token = {str(item.get("token")): str(item["name"]) for item in arch.get("parameters") or []
                if item.get("token") and item.get("name") != "jacoco_exclusions"}
    reserved = set(((arch.get("parameter_token_policy") or {}).get("non_parameter_wrapper_identifiers")) or [])
    for token in PARAM_RE.findall(text):
        name = by_token.get(token)
        if token in reserved:
            continue
        if not name:
            raise BuildMaterializationError(f"Unrecognized POM template marker: {token}")
        value = resolved.get(name)
        if value is None:
            raise BuildMaterializationError(f"Missing resolved POM parameter: {name}")
        if isinstance(value, list):
            value = ",".join(map(str, value))
        if not isinstance(value, (str, int, float, bool)):
            raise BuildMaterializationError(f"Unsupported value type for POM parameter {name}")
        text = text.replace(token, str(value))
    if PARAM_RE.search(text):
        raise BuildMaterializationError("POM output still contains a generator placeholder.")

    try:
        parsed = ET.fromstring(text)
    except ET.ParseError as exc:
        raise BuildMaterializationError(f"Materialized POM is not valid XML: {exc}") from exc
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    for key, expected in (("groupId", resolved["group_id"]),
                          ("artifactId", resolved["artifact_id"]),
                          ("version", resolved["project_version"])):
        node = parsed.find(f"m:{key}", ns)
        if node is None or (node.text or "").strip() != str(expected):
            raise BuildMaterializationError(f"Materialized POM {key} does not match approved parameter values.")
    return text.encode("utf-8")


def validate_settings(source: bytes, arch: dict[str, Any]) -> bytes:
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise BuildMaterializationError(f"Archetype settings.xml is not valid XML: {exc}") from exc
    ns = {"s": "http://maven.apache.org/SETTINGS/1.0.0"}
    baseline = (arch.get("maven") or {}).get("approved_corporate_baseline") or {}
    mirror_expectations = {(entry["id"], str(entry["mirror_of"]), str(entry["url"]))
                           for entry in baseline.get("mirrors") or []}
    mirrors = {(child_text(item, "id"), child_text(item, "mirrorOf"), child_text(item, "url"))
               for item in root.findall("s:mirrors/s:mirror", ns)}
    if mirrors != mirror_expectations:
        raise BuildMaterializationError("settings.xml mirrors differ from the approved archetype Maven baseline.")
    profiles = {child_text(item, "id"): item for item in root.findall("s:profiles/s:profile", ns)}
    expected_profiles = {item["id"] for item in baseline.get("settings_profiles") or []}
    if set(profiles) != expected_profiles:
        raise BuildMaterializationError("settings.xml profiles differ from the approved archetype Maven baseline.")
    for profile in baseline.get("settings_profiles") or []:
        element = profiles[profile["id"]]
        actual_repositories = [(child_text(repo, "id"), child_text(repo, "url"))
                               for repo in element.findall("s:repositories/s:repository", ns)]
        expected_repositories = [(item["id"], item["url"]) for item in profile.get("repositories") or []]
        actual_plugins = [(child_text(repo, "id"), child_text(repo, "url"))
                          for repo in element.findall("s:pluginRepositories/s:pluginRepository", ns)]
        expected_plugins = [(item["id"], item["url"]) for item in profile.get("plugin_repositories") or []]
        if actual_repositories != expected_repositories or actual_plugins != expected_plugins:
            raise BuildMaterializationError(f"settings.xml repository contents differ from approved profile {profile['id']}.")
    active = [item.text.strip() for item in root.findall("s:activeProfiles/s:activeProfile", ns) if item.text]
    if active != list(baseline.get("active_profiles") or []):
        raise BuildMaterializationError("settings.xml active profiles differ from the approved archetype baseline.")
    if root.findall("s:servers/s:server", ns):
        raise BuildMaterializationError("Maven server credentials must not be present in settings.xml.")
    text = source.decode("utf-8")
    if PARAM_RE.search(text):
        raise BuildMaterializationError("settings.xml contains an unresolved generator placeholder.")
    return source


def build_payloads(root: Path, yaml: Any) -> tuple[dict[str, bytes], dict[str, Any], dict[str, str]]:
    spec, _ = read_yaml(root / SERVICE_SPEC, root, yaml)
    plan, _ = read_yaml(root / PLAN, root, yaml)
    params, _ = read_yaml(root / PARAMETERS, root, yaml)
    arch, _ = read_yaml(root / ARCHETYPE_ROOT / "archetype.yml", root, yaml)
    allowed, resolved = validate_build_plan(spec, plan, params, arch)
    pom_template = (root / ARCHETYPE_ROOT / "template/pom.xml").read_bytes()
    settings_template = (root / ARCHETYPE_ROOT / "template/settings.xml").read_bytes()
    pom_output = materialize_pom(pom_template, arch, resolved)
    baseline_pom_repositories = ((arch.get("maven") or {}).get("approved_corporate_baseline") or {}).get("pom_repositories") or []
    pom_root = ET.fromstring(pom_output)
    pom_ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    actual_pom_repositories = [(child_text(item, "id"), child_text(item, "url"))
                               for item in pom_root.findall("m:repositories/m:repository", pom_ns)]
    expected_pom_repositories = [(item["id"], item["url"]) for item in baseline_pom_repositories]
    if actual_pom_repositories != expected_pom_repositories:
        raise BuildMaterializationError("Materialized POM repositories differ from the approved archetype baseline.")
    if pom_root.findall("m:pluginRepositories/m:pluginRepository", pom_ns):
        raise BuildMaterializationError("POM plugin repositories are not present in the approved reference baseline.")
    settings_output = validate_settings(settings_template, arch)

    output_root = root / OUTPUT
    manifest_path = output_root / MANIFEST
    manifest, _ = read_yaml(manifest_path, root, yaml)
    existing_paths = {item["path"] for item in manifest.get("generatedFiles") or []}
    disk_paths = {item.relative_to(output_root).as_posix() for item in output_root.rglob("*") if item.is_file()}
    if disk_paths != existing_paths | {MANIFEST}:
        raise BuildMaterializationError("Existing scaffold inventory no longer matches its manifest; refusing partial update.")
    if {"pom.xml", "settings.xml"}.intersection(existing_paths | set(existing_paths)):
        raise BuildMaterializationError("Build files already appear in the manifest; refusing to overwrite.")
    for build_path in ("pom.xml", "settings.xml"):
        if (output_root / build_path).exists():
            raise BuildMaterializationError(f"Build file already exists and will not be overwritten: {build_path}")

    manifest["inputs"] = {
        "serviceSpec": {"path": SERVICE_SPEC.as_posix(), "fingerprint": sha256((root / SERVICE_SPEC).read_bytes())},
        "implementationPlan": {"path": PLAN.as_posix(), "fingerprint": sha256((root / PLAN).read_bytes())},
        "generationParameters": {"path": PARAMETERS.as_posix(),
                                 "fingerprint": sha256((root / PARAMETERS).read_bytes())},
        "archetype": {"path": ARCHETYPE_ROOT.as_posix(), "version": (arch.get("archetype") or {}).get("version"),
                      "fingerprint": tree_fingerprint(root / ARCHETYPE_ROOT)},
    }
    generated = list(manifest.get("generatedFiles") or [])
    generated.extend([
        {"path": "pom.xml", "source": f"{ARCHETYPE_ROOT.as_posix()}/template/pom.xml",
         "reason": "Approved Maven archetype template parameterized with resolved coordinates and D-009 corporate repository baseline.",
         "traceability": ["archetype.yml#/template_inventory/10", "archetype.yml#/maven/coordinates",
                          "archetype.yml#/maven/approved_corporate_baseline", "generation-parameters.yml#/resolved"]},
        {"path": "settings.xml", "source": f"{ARCHETYPE_ROOT.as_posix()}/template/settings.xml",
         "reason": "Copied approved static non-secret D-009 Maven settings baseline; contains no server credentials.",
         "traceability": ["archetype.yml#/template_inventory/11", "archetype.yml#/maven/approved_corporate_baseline",
                          "archetypes/claro-spring-ms/v1.0.0/decisions.md#D-009"]},
    ])
    manifest["generatedFiles"] = sorted(generated, key=lambda item: item["path"])
    manifest["omittedFiles"] = sorted([item for item in manifest.get("omittedFiles") or []
                                       if item.get("path") not in {"pom.xml", "settings.xml"}],
                                      key=lambda item: str(item.get("path")))
    manifest["readiness"] = {
        "sourceGenerationReady": (plan.get("readiness") or {}).get("sourceGenerationReady"),
        "buildFileGenerationReady": (plan.get("readiness") or {}).get("buildFileGenerationReady"),
        "buildExecutionReady": (plan.get("readiness") or {}).get("buildExecutionReady"),
        "deploymentGenerationReady": (plan.get("readiness") or {}).get("deploymentGenerationReady"),
        "strictImplementationReady": (plan.get("readiness") or {}).get("strictImplementationReady"),
        "scaffoldImplementationReady": (plan.get("readiness") or {}).get("scaffoldImplementationReady"),
    }
    manifest_payload = encode_yaml(manifest, yaml)
    return {"pom.xml": pom_output, "settings.xml": settings_output, MANIFEST: manifest_payload}, manifest, allowed


def write_temp(path: Path, files: dict[str, bytes]) -> None:
    path.mkdir(parents=True, exist_ok=False)
    for name, data in sorted(files.items()):
        target = path / name
        target.write_bytes(data)


def hashes(files: dict[str, bytes]) -> list[tuple[str, str]]:
    return [(name, sha256(files[name])) for name in sorted(files)]


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
    parser.add_argument("--verify-determinism", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        yaml = yaml_module()
        output_root = root / OUTPUT
        if output_root.is_symlink() or not output_root.is_dir():
            raise BuildMaterializationError(f"Existing scaffold directory is missing or unsafe: {OUTPUT}")
        existing_before = {item.relative_to(output_root).as_posix(): sha256(item.read_bytes())
                           for item in output_root.rglob("*") if item.is_file()
                           and item.relative_to(output_root).as_posix() not in {"pom.xml", "settings.xml", MANIFEST}}
        files, manifest, _ = build_payloads(root, yaml)
        if args.verify_determinism:
            with tempfile.TemporaryDirectory(dir=output_root.parent, prefix=".build-files-check-a-") as temp_a, \
                 tempfile.TemporaryDirectory(dir=output_root.parent, prefix=".build-files-check-b-") as temp_b:
                files_a, _, _ = build_payloads(root, yaml)
                files_b, _, _ = build_payloads(root, yaml)
                write_temp(Path(temp_a) / "output", files_a)
                write_temp(Path(temp_b) / "output", files_b)
                if hashes(files_a) != hashes(files_b):
                    raise BuildMaterializationError("Two clean build-file materializations were not byte-identical.")

        # Write only the two absent build files and the required manifest update.
        for name in ("pom.xml", "settings.xml"):
            (output_root / name).write_bytes(files[name])
        (output_root / MANIFEST).write_bytes(files[MANIFEST])

        existing_after = {item.relative_to(output_root).as_posix(): sha256(item.read_bytes())
                          for item in output_root.rglob("*") if item.is_file()
                          and item.relative_to(output_root).as_posix() not in {"pom.xml", "settings.xml", MANIFEST}}
        if existing_before != existing_after:
            raise BuildMaterializationError("An existing scaffold file changed during Maven file materialization.")
        final_files = {item.relative_to(output_root).as_posix(): item.read_bytes()
                       for item in output_root.rglob("*") if item.is_file()}
        output_tree_hash = sha256("".join(f"{name}\0{sha256(final_files[name])}\n"
                                          for name in sorted(final_files)).encode("utf-8"))
        print({"materialized": ["pom.xml", "settings.xml"],
               "outputFileCount": len(final_files),
               "pomSha256": sha256(files["pom.xml"]),
               "settingsSha256": sha256(files["settings.xml"]),
               "manifestSha256": sha256(files[MANIFEST]),
               "outputTreeSha256": output_tree_hash,
               "determinismVerified": bool(args.verify_determinism),
               "readiness": manifest["readiness"]})
        return 0
    except (BuildMaterializationError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"materialize_build_files.py: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
