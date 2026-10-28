#!/usr/bin/env python3
"""Select a deterministic, bounded context from an approved Sparx Stage 1 index."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tempfile
import unicodedata
from collections import deque
from pathlib import Path
from typing import Any, Iterable


MAX_TRAVERSAL_DEPTH = 3
EVIDENCE_FIELDS = (
    "headings",
    "properties",
    "textBlocks",
    "tables",
    "operations",
    "activities",
    "processes",
    "links",
    "imageMaps",
    "notes",
)


class SelectionFailure(Exception):
    """Raised when deterministic context selection cannot safely continue."""


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministically select bounded context from .factory/sparx-index.yml."
    )
    parser.add_argument("input", type=Path, help="Approved .factory/sparx-index.yml")
    parser.add_argument("output", type=Path, help="Context YAML file under .factory/")
    parser.add_argument("--hint", action="append", default=[], help="Generic observable hint")
    parser.add_argument("--title", action="append", default=[], help="Page-title hint")
    parser.add_argument(
        "--ancestor-title", action="append", default=[], help="Breadcrumb/ancestor-title hint"
    )
    parser.add_argument("--element-name", action="append", default=[], help="Element-name hint")
    parser.add_argument("--package-name", action="append", default=[], help="Package-name hint")
    parser.add_argument("--page-path", action="append", default=[], help="Repository-relative page path hint")
    parser.add_argument("--identifier", action="append", default=[], help="Explicit page identifier hint")
    parser.add_argument("--search-term", action="append", default=[], help="Broad source-text search term")
    parser.add_argument(
        "--traversal-depth",
        type=int,
        default=1,
        help=f"Structural traversal depth from the selected root (0-{MAX_TRAVERSAL_DEPTH}; default: 1)",
    )
    return parser.parse_args()


def load_yaml_module() -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SelectionFailure(
            "PyYAML is required to read and emit Sparx context. Install it in the managed "
            "environment; packages are never installed dynamically."
        ) from exc
    return yaml


def find_repository_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (
            (candidate / "AGENTS.md").is_file()
            and (candidate / ".factory").is_dir()
            and (candidate / ".opencode").is_dir()
        ):
            return candidate
    raise SelectionFailure("Cannot locate the repository root containing AGENTS.md and .factory/.")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    return " ".join(text.replace("\xa0", " ").split()).casefold()


def normalize_identifier(value: Any) -> str:
    normalized = normalize(value)
    candidate = normalized.strip().strip("{}")
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        candidate,
    ):
        return candidate
    return normalized


def unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").replace("\xa0", " ").split())
        key = normalize(text)
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def split_title(value: Any) -> list[str]:
    return unique_strings(re.split(r"\s*::\s*", str(value or "")))


def scalar_texts(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key in value:
            if key == "evidenceId":
                continue
            yield from scalar_texts(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from scalar_texts(item)
    elif value is not None:
        yield str(value)


def page_fields(page: dict[str, Any]) -> dict[str, list[str]]:
    breadcrumb_entries = page.get("breadcrumb") or []
    current_file = normalize(page.get("file"))
    ancestor_entries = [
        item
        for item in breadcrumb_entries
        if normalize(item.get("target")) != current_file
    ]
    breadcrumbs = unique_strings(item.get("text") for item in ancestor_entries)
    breadcrumb_segments = unique_strings(
        segment
        for item in ancestor_entries
        for segment in (item.get("segments") or split_title(item.get("text")))
    )
    headings = unique_strings(item.get("text") for item in page.get("headings") or [])
    properties = unique_strings(scalar_texts(page.get("properties") or []))
    links = unique_strings(scalar_texts(page.get("links") or []))
    broad = unique_strings(
        value
        for field in (
            "headings",
            "properties",
            "textBlocks",
            "tables",
            "operations",
            "activities",
            "processes",
            "links",
            "imageMaps",
            "notes",
        )
        for value in scalar_texts(page.get(field) or [])
    )
    return {
        "title": unique_strings([page.get("title")]),
        "titleSegment": split_title(page.get("title")),
        "breadcrumb": breadcrumbs,
        "breadcrumbSegment": breadcrumb_segments,
        "elementName": unique_strings([page.get("elementName")]),
        "packageName": unique_strings([page.get("packageName")]),
        "pagePath": unique_strings([page.get("file"), Path(str(page.get("file") or "")).name]),
        "identifier": unique_strings([page.get("id")]),
        "heading": headings,
        "property": properties,
        "link": links,
        "broad": broad,
    }


def best_match(hint: dict[str, str], fields: dict[str, list[str]]) -> dict[str, Any] | None:
    default_value = (
        normalize_identifier(hint["value"])
        if hint["kind"] == "identifier"
        else normalize(hint["value"])
    )
    if not default_value:
        return None

    kind = hint["kind"]
    rules: list[tuple[str, int, str]]
    if kind == "title":
        rules = [("title", 220, "exact"), ("titleSegment", 180, "exact")]
    elif kind == "ancestor-title":
        rules = [("breadcrumb", 190, "exact"), ("breadcrumbSegment", 180, "exact")]
    elif kind == "element-name":
        rules = [("elementName", 220, "exact")]
    elif kind == "package-name":
        rules = [("packageName", 220, "exact")]
    elif kind == "page-path":
        rules = [("pagePath", 240, "exact"), ("pagePath", 140, "contains")]
    elif kind == "identifier":
        rules = [("identifier", 240, "exact")]
    elif kind == "search-term":
        rules = [("broad", 60, "exact"), ("broad", 25, "contains")]
    else:
        rules = [
            ("identifier", 240, "exact"),
            ("pagePath", 240, "exact"),
            ("title", 220, "exact"),
            ("titleSegment", 180, "exact"),
            ("elementName", 170, "exact"),
            ("packageName", 170, "exact"),
            ("breadcrumb", 150, "exact"),
            ("breadcrumbSegment", 140, "exact"),
            ("heading", 120, "exact"),
            ("property", 100, "exact"),
            ("link", 80, "exact"),
            ("pagePath", 70, "contains"),
            ("broad", 20, "contains"),
        ]

    matches: list[dict[str, Any]] = []
    for field, weight, mode in rules:
        value = normalize_identifier(hint["value"]) if field == "identifier" else default_value
        for observed in fields[field]:
            observed_normalized = (
                normalize_identifier(observed) if field == "identifier" else normalize(observed)
            )
            matched = observed_normalized == value if mode == "exact" else value in observed_normalized
            if matched:
                matches.append(
                    {
                        "hintKind": kind,
                        "hint": hint["value"],
                        "field": field,
                        "match": mode,
                        "observed": observed,
                        "weight": weight,
                    }
                )
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda item: (-item["weight"], item["field"], normalize(item["observed"]), item["observed"]),
    )[0]


def collect_hints(arguments: argparse.Namespace) -> list[dict[str, str]]:
    groups = (
        ("hint", arguments.hint),
        ("title", arguments.title),
        ("ancestor-title", arguments.ancestor_title),
        ("element-name", arguments.element_name),
        ("package-name", arguments.package_name),
        ("page-path", arguments.page_path),
        ("identifier", arguments.identifier),
        ("search-term", arguments.search_term),
    )
    hints: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, values in groups:
        for value in values:
            cleaned = " ".join(str(value).replace("\xa0", " ").split())
            key = (kind, normalize(cleaned))
            if cleaned and key not in seen:
                seen.add(key)
                hints.append({"kind": kind, "value": cleaned})
    if not hints:
        raise SelectionFailure("At least one explicit selection hint is required.")
    return hints


def score_candidates(pages: list[dict[str, Any]], hints: list[dict[str, str]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        fields = page_fields(page)
        matches = [best_match(hint, fields) for hint in hints]
        if any(match is None for match in matches):
            continue
        concrete_matches = [match for match in matches if match is not None]
        candidates.append(
            {
                "file": page.get("file"),
                "id": page.get("id"),
                "title": page.get("title"),
                "score": sum(match["weight"] for match in concrete_matches),
                "matchedHints": concrete_matches,
            }
        )
    return sorted(candidates, key=lambda item: (-item["score"], item["file"] or ""))


def choose_root(
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    if not candidates:
        return (
            None,
            {"detected": False, "reason": None, "candidates": []},
            {"detected": True, "reason": "No page matches every supplied hint."},
        )
    highest_score = candidates[0]["score"]
    highest = [candidate for candidate in candidates if candidate["score"] == highest_score]
    if len(highest) != 1:
        return (
            None,
            {
                "detected": True,
                "reason": "Several pages have the same highest observable-evidence score.",
                "candidates": highest,
            },
            {"detected": False, "reason": None},
        )
    return (
        highest[0],
        {"detected": False, "reason": None, "candidates": []},
        {"detected": False, "reason": None},
    )


def select_structural_context(
    root: dict[str, Any],
    pages_by_file: dict[str, dict[str, Any]],
    relationships: list[dict[str, Any]],
    traversal_depth: int,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    adjacency: dict[str, list[tuple[str, str, str]]] = {}
    for relationship in relationships:
        parent = str(relationship.get("parent") or "")
        child = str(relationship.get("child") or "")
        source = str(relationship.get("source") or "")
        if (
            relationship.get("type") == "contains"
            and source in {"breadcrumb", "project-browser"}
            and parent in pages_by_file
            and child in pages_by_file
        ):
            adjacency.setdefault(parent, []).append((child, "structural-child", source))
            adjacency.setdefault(child, []).append((parent, "structural-parent", source))
    for file in adjacency:
        adjacency[file].sort(key=lambda item: (item[0], item[1], item[2]))

    root_file = str(root["file"])
    reasons: dict[str, list[dict[str, Any]]] = {
        root_file: [
            {
                "type": "query-root",
                "score": root["score"],
                "matchedHints": root["matchedHints"],
            }
        ]
    }
    minimum_depth = {root_file: 0}
    queue: deque[tuple[str, int]] = deque([(root_file, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= traversal_depth:
            continue
        for neighbor, relation_type, source in adjacency.get(current, []):
            next_depth = depth + 1
            reason = {
                "type": relation_type,
                "via": current,
                "relationshipSource": source,
                "depth": next_depth,
            }
            if reason not in reasons.setdefault(neighbor, []):
                reasons[neighbor].append(reason)
            if neighbor not in minimum_depth or next_depth < minimum_depth[neighbor]:
                minimum_depth[neighbor] = next_depth
                queue.append((neighbor, next_depth))

    selected_files = set(reasons)
    selected_relationships = [
        relationship
        for relationship in relationships
        if relationship.get("parent") in selected_files and relationship.get("child") in selected_files
        and relationship.get("type") == "contains"
        and relationship.get("source") in {"breadcrumb", "project-browser"}
    ]
    selected_relationships.sort(
        key=lambda item: (
            item.get("parent") or "",
            item.get("child") or "",
            item.get("type") or "",
            item.get("source") or "",
        )
    )
    for file in reasons:
        reasons[file].sort(
            key=lambda item: (
                0 if item["type"] == "query-root" else 1,
                item.get("depth", 0),
                item["type"],
                item.get("via", ""),
                item.get("relationshipSource", ""),
            )
        )
    return reasons, selected_relationships


def relevant_unresolved_assets(
    selected_pages: list[dict[str, Any]], index_warnings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in selected_pages:
        source = str(page.get("file") or "")
        for index, link in enumerate(page.get("links") or []):
            if link.get("kind") == "local-asset" and not link.get("resolved"):
                reference = str(link.get("href") or link.get("target") or "")
                result.append(
                    {
                        "code": "relevant_local_asset_unresolved",
                        "source": source,
                        "referenceType": "link",
                        "referenceIndex": index,
                        "reference": reference,
                        "target": link.get("target"),
                        "evidenceId": link.get("evidenceId"),
                        "message": "A selected page references a local asset that Stage 1 could not resolve.",
                    },
                )
        for index, image in enumerate(page.get("imageReferences") or []):
            if image.get("kind") == "local-asset" and not image.get("resolved"):
                reference = str(image.get("source") or image.get("target") or "")
                result.append(
                    {
                        "code": "relevant_local_asset_unresolved",
                        "source": source,
                        "referenceType": "image",
                        "referenceIndex": index,
                        "reference": reference,
                        "target": image.get("target"),
                        "evidenceId": None,
                        "message": "A selected page references an image asset that Stage 1 could not resolve.",
                    },
                )
    selected_files = {str(page.get("file") or "") for page in selected_pages}
    for warning in index_warnings:
        if warning.get("code") != "local_asset_unresolved" or warning.get("source") not in selected_files:
            continue
        reference = str(warning.get("target") or "")
        matching_occurrences = [
            item
            for item in result
            if item["source"] == warning.get("source") and item["reference"] == reference
        ]
        if matching_occurrences:
            for item in matching_occurrences:
                item["stage1Warning"] = warning
        else:
            result.append({
                "code": "relevant_local_asset_unresolved",
                "source": warning.get("source"),
                "referenceType": "stage1-warning",
                "referenceIndex": None,
                "reference": reference,
                "target": warning.get("target"),
                "evidenceId": None,
                "message": warning.get("message"),
                "stage1Warning": warning,
            })
    return sorted(
        result,
        key=lambda item: (
            item.get("source") or "",
            item.get("referenceType") or "",
            item.get("reference") or "",
            item.get("evidenceId") or "",
            item.get("referenceIndex") if item.get("referenceIndex") is not None else -1,
        ),
    )


def relevant_stage1_issues(
    issues: list[dict[str, Any]],
    selected_files: set[str],
    selected_identifiers: set[str],
    excluded_code: str | None = None,
) -> list[dict[str, Any]]:
    result = [
        {"origin": "stage1", **issue}
        for issue in issues
        if issue.get("code") != excluded_code
        and (
            issue.get("source") in selected_files
            or (
                issue.get("code") == "duplicate_page_identifier"
                and normalize_identifier(issue.get("target")) in selected_identifiers
            )
        )
    ]
    return sorted(
        result,
        key=lambda item: (
            item.get("source") or "",
            item.get("code") or "",
            item.get("target") or "",
            item.get("message") or "",
        ),
    )


def count_evidence(pages: list[dict[str, Any]]) -> int:
    return sum(
        1
        for page in pages
        for field in EVIDENCE_FIELDS
        for item in page.get(field) or []
        if isinstance(item, dict) and item.get("evidenceId")
    ) + sum(
        1
        for page in pages
        for image_map in page.get("imageMaps") or []
        for area in image_map.get("areas") or []
        if isinstance(area, dict) and area.get("evidenceId")
    )


def read_index(path: Path, yaml_module: Any) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SelectionFailure(f"Cannot read approved Sparx index: {exc.strerror or type(exc).__name__}.") from exc
    try:
        loader = getattr(yaml_module, "CSafeLoader", yaml_module.SafeLoader)
        index = yaml_module.load(payload, Loader=loader)
    except yaml_module.YAMLError as exc:
        raise SelectionFailure(f"Cannot parse approved Sparx index: {exc}.") from exc
    if not isinstance(index, dict) or not isinstance(index.get("pages"), list):
        raise SelectionFailure("Approved Sparx index has an invalid root or pages structure.")
    if not isinstance(index.get("relationships"), list):
        raise SelectionFailure("Approved Sparx index has an invalid relationships structure.")
    return index, hashlib.sha256(payload).hexdigest()


def build_context(
    index: dict[str, Any],
    index_sha256: str,
    hints: list[dict[str, str]],
    traversal_depth: int,
) -> dict[str, Any]:
    pages = index["pages"]
    pages_by_file = {str(page.get("file") or ""): page for page in pages}
    if len(pages_by_file) != len(pages):
        raise SelectionFailure("Approved Sparx index contains duplicate or empty page paths.")

    candidates = score_candidates(pages, hints)
    root, ambiguity, no_match = choose_root(candidates)
    selected_pages: list[dict[str, Any]] = []
    selected_relationships: list[dict[str, Any]] = []
    if root is not None:
        reasons, selected_relationships = select_structural_context(
            root, pages_by_file, index["relationships"], traversal_depth
        )
        for file in sorted(reasons):
            selected_pages.append({"selectionReasons": reasons[file], **pages_by_file[file]})

    selected_files = {str(page.get("file") or "") for page in selected_pages}
    selected_identifiers = {
        normalize_identifier(page.get("id")) for page in selected_pages if page.get("id")
    }
    stage1_validation = index.get("validation") or {}
    asset_warnings = relevant_unresolved_assets(
        selected_pages, stage1_validation.get("warnings") or []
    )
    warnings = relevant_stage1_issues(
        stage1_validation.get("warnings") or [],
        selected_files,
        selected_identifiers,
        "local_asset_unresolved",
    ) + asset_warnings
    warnings.sort(
        key=lambda item: (
            item.get("source") or "",
            item.get("code") or "",
            item.get("reference") or item.get("target") or "",
            item.get("message") or "",
        )
    )
    errors: list[dict[str, Any]] = relevant_stage1_issues(
        stage1_validation.get("errors") or [], selected_files, selected_identifiers
    )
    if ambiguity["detected"]:
        errors.append(
            {
                "code": "selection_ambiguous",
                "source": ".factory/sparx-index.yml",
                "message": ambiguity["reason"],
            }
        )
    if no_match["detected"]:
        errors.append(
            {
                "code": "selection_no_match",
                "source": ".factory/sparx-index.yml",
                "message": no_match["reason"],
            }
        )

    unresolved_internal = sum(
        1
        for page in selected_pages
        for link in page.get("links") or []
        if link.get("kind") == "internal-page" and not link.get("resolved")
    )
    unresolved_asset_links = sum(
        1
        for page in selected_pages
        for link in page.get("links") or []
        if link.get("kind") == "local-asset" and not link.get("resolved")
    )
    return {
        "source": {
            "index": ".factory/sparx-index.yml",
            "indexSha256": index_sha256,
            "export": (index.get("source") or {}).get("path"),
            "fingerprint": (index.get("source") or {}).get("fingerprint"),
        },
        "query": {"hints": hints, "traversalDepth": traversal_depth},
        "statistics": {
            "candidatePages": len(candidates),
            "selectedPages": len(selected_pages),
            "evidenceItems": count_evidence(selected_pages),
            "unresolvedRelevantLinks": unresolved_internal + unresolved_asset_links,
            "unresolvedRelevantAssets": len(asset_warnings),
        },
        "selection": {
            "rootCandidates": candidates,
            "selectedRoot": root,
            "ambiguity": ambiguity,
            "noMatch": no_match,
        },
        "pages": selected_pages,
        "relationships": selected_relationships,
        "validation": {"warnings": warnings, "errors": errors},
    }


def write_yaml(path: Path, value: dict[str, Any], yaml_module: Any, factory_root: Path) -> None:
    if not is_within(path, factory_root) or path == factory_root:
        raise SelectionFailure("Context output must be a file under .factory/.")

    class StableDumper(yaml_module.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    payload = yaml_module.dump(
        value,
        Dumper=StableDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
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
        raise SelectionFailure(f"Cannot write Sparx context: {exc.strerror or type(exc).__name__}.") from exc


def validate_paths(arguments: argparse.Namespace, repository_root: Path) -> tuple[Path, Path, Path]:
    expected_input = (repository_root / ".factory" / "sparx-index.yml").absolute()
    logical_input = (
        arguments.input if arguments.input.is_absolute() else repository_root / arguments.input
    ).absolute()
    logical_output = (
        arguments.output if arguments.output.is_absolute() else repository_root / arguments.output
    ).absolute()
    try:
        factory_root = (repository_root / ".factory").resolve()
        input_path = logical_input.resolve()
        output_path = logical_output.resolve()
        expected_resolved = expected_input.resolve()
    except (OSError, RuntimeError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else None
        raise SelectionFailure(f"Cannot resolve Stage 1.5 paths safely: {detail or type(exc).__name__}.") from exc

    if logical_input != expected_input or input_path != expected_resolved:
        raise SelectionFailure("Stage 1.5 input must be exactly .factory/sparx-index.yml.")
    if not is_within(input_path, factory_root):
        raise SelectionFailure("Stage 1.5 input must resolve inside .factory/.")
    if not input_path.is_file():
        raise SelectionFailure("Approved .factory/sparx-index.yml does not exist.")
    if not is_within(logical_output, (repository_root / ".factory").absolute()):
        raise SelectionFailure("Stage 1.5 output must be located under .factory/.")
    if not is_within(output_path, factory_root) or output_path == factory_root:
        raise SelectionFailure("Stage 1.5 output must resolve to a file under .factory/.")
    if output_path == input_path:
        raise SelectionFailure("Stage 1.5 must not overwrite .factory/sparx-index.yml.")
    protected_names = {
        "sparx-spec.yml",
        "sparx-spec.yaml",
        "openapi-spec.yml",
        "openapi-spec.yaml",
    }
    protected_targets = {
        (repository_root / ".factory" / name).resolve() for name in protected_names
    }
    if (
        arguments.output.name.casefold() in protected_names
        or output_path.name.casefold() in protected_names
        or output_path in protected_targets
    ):
        raise SelectionFailure("Stage 1.5 cannot overwrite protected factory specifications.")
    if output_path.suffix.casefold() not in {".yml", ".yaml"}:
        raise SelectionFailure("Stage 1.5 output must use a .yml or .yaml suffix.")
    if output_path.exists() and output_path.is_dir():
        raise SelectionFailure("Stage 1.5 output must be a YAML file, not a directory.")
    return input_path, output_path, factory_root


def main() -> int:
    arguments = parse_arguments()
    try:
        if not 0 <= arguments.traversal_depth <= MAX_TRAVERSAL_DEPTH:
            raise SelectionFailure(
                f"Traversal depth must be between 0 and {MAX_TRAVERSAL_DEPTH}."
            )
        repository_root = find_repository_root()
        input_path, output_path, factory_root = validate_paths(arguments, repository_root)
        hints = collect_hints(arguments)
        yaml_module = load_yaml_module()
        index, index_sha256 = read_index(input_path, yaml_module)
        context = build_context(index, index_sha256, hints, arguments.traversal_depth)
        write_yaml(output_path, context, yaml_module, factory_root)
    except SelectionFailure as exc:
        print(f"select_sparx_context.py: error: {exc}", file=sys.stderr)
        return 2

    statistics = context["statistics"]
    print(
        f"Wrote '{output_path}' with {statistics['candidatePages']} candidate page(s), "
        f"{statistics['selectedPages']} selected page(s), "
        f"{len(context['validation']['warnings'])} warning(s), and "
        f"{len(context['validation']['errors'])} error(s).",
        file=sys.stderr,
    )
    return 1 if context["validation"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
