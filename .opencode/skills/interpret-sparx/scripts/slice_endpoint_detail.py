"""Slice an endpoint-detail index into bounded semantic units (generic, deterministic).

Input is the artifact produced by parse-sparx/scripts/extract_endpoint_detail.py. Each
non-empty embedded section becomes a unit. Units are classified as either
``deterministic-normalization`` (structured literals that need no interpretation:
key/value fields, columnar mappings, literal statements) or
``semantic-interpretation-required`` (free prose, notes and conditional outcomes).
No business meaning is added here.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


def dump(value: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=140).encode("utf-8")


def evidence_ids(value: Any) -> list[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key == "evidenceId" and isinstance(item, str):
                    found.add(item)
                else:
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return sorted(found)


def build_units(index: dict[str, Any], authority: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def branch_stamp(page_path: str) -> dict[str, Any] | None:
        """Branch provenance from sparx-target-authority.yml; part of the unit fingerprint so branches never merge."""
        for branch in (authority or {}).get("branches", []):
            if branch.get("pagePathPrefix") and f"/{branch['pagePathPrefix']}/" in page_path:
                return {key: branch.get(key) for key in ("branchRootId", "branchRootGuid", "authorityClass")}
        return None

    def add(page: dict[str, Any], embedded: dict[str, Any], section: dict[str, Any], part: str,
            processing: str, content: dict[str, Any], reasons: list[str]) -> None:
        unit = {
            "page": page["page"],
            "pageSha256": page["sha256"],
            "activity": page["activity"]["name"],
            "activityUuid": page["activity"]["uuid"],
            "operationScope": page["operationScope"],
            "embeddedFile": embedded["resolvedFile"],
            "embeddedSha256": embedded["sha256"],
            "sectionEvidenceId": section["evidenceId"],
            "sectionKind": section["kind"],
            "sectionLabel": section.get("label"),
            "part": part,
            "processing": processing,
            "interpretationReasons": reasons,
            "content": content,
        }
        stamp = branch_stamp(page["page"])
        if authority is not None:
            unit["authorityBranch"] = stamp
        unit["evidenceIds"] = evidence_ids(content) + [section["evidenceId"], embedded["evidenceId"]]
        unit["evidenceIds"] = sorted(set(unit["evidenceIds"]))
        unit["inputFingerprint"] = hashlib.sha256(dump(unit)).hexdigest()
        units.append(unit)

    for page in index["pages"]:
        for embedded in page["embeddedContent"]:
            for section in embedded["sections"]:
                kind = section["kind"]
                if kind == "keyValue":
                    add(page, embedded, section, "key-value", "deterministic-normalization", {"entries": section["entries"]}, [])
                elif kind == "columnar":
                    if not section["rows"]:
                        skipped.append({"page": page["page"], "sectionEvidenceId": section["evidenceId"], "label": section["label"], "reason": "no non-empty rows"})
                        continue
                    add(page, embedded, section, "columnar", "deterministic-normalization",
                        {"columns": section["columns"], "rows": section["rows"], "emptyRowCount": section["emptyRowCount"]}, [])
                elif kind == "text":
                    if section["empty"]:
                        skipped.append({"page": page["page"], "sectionEvidenceId": section["evidenceId"], "label": section["label"], "reason": "empty text section"})
                        continue
                    if section["statements"]:
                        add(page, embedded, section, "literal-statements", "deterministic-normalization", {"statements": section["statements"]}, [])
                    prose = [section["lines"][i] for i in section["proseLineIndexes"]]
                    reasons: list[str] = []
                    if prose:
                        reasons.append("free prose lines")
                    if section["notes"]:
                        reasons.append("notes with conditional/optionality wording")
                    if any(not row["codes"] for row in section["responseCodeBlock"]):
                        reasons.append("outcome statements without an explicit code")
                    if section["responseCodeBlock"]:
                        reasons.append("response outcomes expressed as conditional sentences")
                    if prose or section["notes"] or section["responseCodeBlock"]:
                        add(page, embedded, section, "prose-and-outcomes", "semantic-interpretation-required",
                            {"proseLines": prose, "notes": section["notes"], "responseCodeBlock": section["responseCodeBlock"],
                             "codeMentions": section["codeMentions"]}, reasons)
                else:
                    skipped.append({"page": page["page"], "sectionEvidenceId": section["evidenceId"], "label": section.get("label"), "reason": f"unclassified {kind}"})
    for number, unit in enumerate(units, start=1):
        unit["unitId"] = f"unit-{number:04d}"
    return units, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--authority", type=Path, help="sparx-target-authority.yml; stamps branch provenance into every unit and fingerprint")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"refusing to overwrite existing directory: {args.output_dir}")
    index_bytes = args.index.read_bytes()
    index = yaml.safe_load(index_bytes)
    authority = yaml.safe_load(args.authority.read_bytes()) if args.authority else None
    units, skipped = build_units(index, authority)
    args.output_dir.mkdir(parents=True)
    unit_rows = []
    for unit in units:
        data = dump(unit)
        (args.output_dir / f"{unit['unitId']}.yml").write_bytes(data)
        unit_rows.append({
            "unitId": unit["unitId"], "file": f"{unit['unitId']}.yml", "sha256": hashlib.sha256(data).hexdigest(),
            "activity": unit["activity"], "operationScope": unit["operationScope"], "part": unit["part"],
            "sectionLabel": unit["sectionLabel"], "processing": unit["processing"], "inputFingerprint": unit["inputFingerprint"],
        })
    manifest = {
        "version": 1,
        "kind": "sparx-endpoint-detail-semantic-units",
        "source": {"index": args.index.as_posix(), "sha256": hashlib.sha256(index_bytes).hexdigest()},
        "counts": {
            "units": len(units),
            "deterministicNormalization": sum(u["processing"] == "deterministic-normalization" for u in units),
            "semanticInterpretationRequired": sum(u["processing"] == "semantic-interpretation-required" for u in units),
            "skippedEmptySections": len(skipped),
        },
        "units": unit_rows,
        "skippedSections": skipped,
    }
    (args.output_dir / "manifest.yml").write_bytes(dump(manifest))
    print(manifest["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
