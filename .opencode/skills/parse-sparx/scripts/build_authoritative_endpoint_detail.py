"""Build the authoritative endpoint-detail artifact (and the non-authoritative evidence register).

Input is the branch-authority artifact from resolve_target_authority.py. Only the authoritative
branch's active operations are extracted: for each operation every Activity reached through explicit
parent links is processed with extract_endpoint_detail (embedded linkdoc loaded, bounded), and
data-structure elements linked from those Activities' relationship tables are extracted as data
definitions. Nothing from another branch is merged. Prior artifacts are scanned only to register
which of their source pages belong to non-authoritative branches.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import extract_endpoint_detail as ed  # noqa: E402
import resolve_target_authority as ra  # noqa: E402

REQUEST_PARTS = {"headerrequest", "header", "headers", "path", "query", "body"}
PAGE_RE = re.compile(r"EARoot/EA\d+(?:/[A-Za-z0-9_]+)*\.htm")


def dump_bytes(value: Any) -> bytes:
    import yaml

    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=140).encode("utf-8")


def normalize_activity(entry: dict[str, Any]) -> dict[str, Any]:
    emb = entry["embeddedContent"][0] if entry["embeddedContent"] else {"sections": []}
    result: dict[str, Any] = {"validation": {}, "descriptor": None, "input": None, "output": None, "considerations": None, "variablesProperties": None}
    for section in emb["sections"]:
        kind, key = section["kind"], section.get("key")
        if kind == "columnar" and key in REQUEST_PARTS:
            result["validation"][key] = {"sectionEvidenceId": section["evidenceId"], "columns": [c["literal"] for c in section["columns"]],
                                         "rows": [{"evidenceId": r["evidenceId"], **r["values"]} for r in section["rows"]]}
        elif kind == "columnar" and key in {"input", "output"}:
            result[key] = {"sectionEvidenceId": section["evidenceId"], "columns": [c["literal"] for c in section["columns"]],
                           "rows": [{"evidenceId": r["evidenceId"], **r["values"]} for r in section["rows"]], "emptyRowCount": section["emptyRowCount"]}
        elif kind == "keyValue":
            result["descriptor"] = {"sectionEvidenceId": section["evidenceId"], **{x["key"]: x["value"] for x in section["entries"]},
                                    "evidenceIds": {x["key"]: x["evidenceId"] for x in section["entries"]}}
        elif kind == "text" and key == "considerations":
            result["considerations"] = {k: section.get(k) for k in ("evidenceId", "lines", "statements", "notes", "responseCodeBlock", "codeMentions", "proseLineIndexes")}
        elif kind == "text" and key == "variablesProperties":
            result["variablesProperties"] = {"evidenceId": section["evidenceId"], "empty": section["empty"], "lines": section.get("lines", [])}
    descriptor = result["descriptor"]
    result["activityRole"] = ("behavior" if descriptor and descriptor.get("operation") else "validation" if result["validation"] else "unclassified")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nonauthoritative-output", type=Path, required=True)
    parser.add_argument("--prior-artifact", action="append", default=[], type=Path)
    args = parser.parse_args()
    import yaml

    repo = Path.cwd().resolve()
    root = (repo / args.source_root).resolve()
    authority = yaml.safe_load(args.authority.read_bytes())
    if authority["selection"]["status"] != "resolved":
        raise SystemExit("authority is ambiguous; refusing to extract")
    branch_id = authority["selection"]["authoritativeBranchRootId"]
    branch = next(b for b in authority["branches"] if b["branchRootId"] == branch_id)
    inactive = {(d["method"], d["path"]) for d in branch["reviewedLifecycleDecisions"] if d.get("disposition") == "inactive"}
    _, toc_elements, _ = ra.load_toc(root / "js" / "data")
    toc_by_page = {e["page"]: e for e in toc_elements}
    branch_identity = {key: branch[key] for key in ("branchRootId", "branchRootGuid", "name", "pagePathPrefix")}
    branch_identity["authorityClass"] = branch["authorityClass"]
    complements = [b for b in authority["branches"] if b["authorityClass"] == "authoritative-complement"]

    def complement_evidence(op: dict[str, Any]) -> list[dict[str, Any]]:
        found = []
        for comp in complements:
            comp_identity = {key: comp[key] for key in ("branchRootId", "branchRootGuid", "name", "pagePathPrefix")}
            comp_identity["authorityClass"] = comp["authorityClass"]
            comp_op = next((o for o in comp["operations"] if (o["method"], o["path"]) == (op["method"], op["path"])), None)
            for item in (comp_op or {}).get("complementEvidence", []):
                found.append({"branchIdentity": comp_identity, "matchedBy": comp_op.get("matchedBy"), "ambiguity": comp_op.get("ambiguity"),
                              "lane": item["lane"], "flowElements": item["elements"]})
        return found

    data_pages: dict[str, dict[str, Any]] = {}
    operations_out: list[dict[str, Any]] = []
    for op in branch["operations"]:
        if (op["method"], op["path"]) in inactive:
            continue
        if not op["sparxMethodElements"]:
            extra = complement_evidence(op)
            operations_out.append({"method": op["method"], "path": op["path"],
                                   "status": "complement-only" if extra else "no-sparx-method-in-authoritative-branch",
                                   "complementEvidence": extra})
            continue
        elements = op["elements"]
        method_page_path = (root / op["sparxMethod"]["page"]).relative_to(repo).as_posix()
        method_entry = ed.process_page(method_page_path, repo, root, {}, 1)
        service_page = branch["service"]["page"]
        service_links = [r for r in method_entry["outerRelationships"] if r.get("targetPage") == service_page]
        op["methodOwner"] = {**op["methodOwner"], "explicitServiceRelationship": [
            {"object": r["object"], "connection": r["connection"], "direction": r["direction"]} for r in service_links]}
        for rel in method_entry["outerRelationships"]:
            target = rel.get("targetPage")
            toc = toc_by_page.get(target) if target else None
            if toc and toc["stereotype"] and ed.fold(toc["stereotype"]).replace(" ", "") in ed.DATA_STEREOTYPES:
                data_pages.setdefault(target, {"referencedBy": []})["referencedBy"].append(
                    {"operation": f"{op['method']} {op['path']}", "methodPage": op["sparxMethod"]["page"], "methodGuid": op["sparxMethod"]["guid"], "relationship": rel})
        by_own = {e["ownId"]: e for e in elements if e["ownId"]}
        activities = []
        for element in elements:
            if element["role"] != "activity":
                continue
            page_path = (root / element["page"]).relative_to(repo).as_posix()
            entry = ed.process_page(page_path, repo, root, {page_path: [f"{op['method']} {op['path']}"]}, 1)
            normalized = normalize_activity(entry)
            lane = by_own.get(element["parentId"])
            for rel in entry["outerRelationships"]:
                target = rel.get("targetPage")
                toc = toc_by_page.get(target) if target else None
                if toc and toc["stereotype"] and ed.fold(toc["stereotype"]).replace(" ", "") in ed.DATA_STEREOTYPES:
                    data_pages.setdefault(target, {"referencedBy": []})["referencedBy"].append(
                        {"operation": f"{op['method']} {op['path']}", "activityPage": element["page"], "activityGuid": element["guid"], "relationship": rel})
            activities.append({
                "activity": {"name": element["name"], "uuid": entry["activity"]["uuid"], "tocGuid": element["guid"], "status": entry["activity"]["status"],
                             "modified": entry["activity"]["modified"], "page": page_path, "pageSha256": entry["sha256"], "pageEvidenceKey": entry["pageEvidenceKey"]},
                "lane": {"name": lane["name"], "page": lane["page"]} if lane else None,
                "errorEvents": [{"name": e["name"], "page": e["page"], "guid": e["guid"]} for e in elements if e["parentId"] == element["ownId"] and e["role"] == "intermediateEvent"],
                "embeddedLinkdoc": ({k: entry["embeddedContent"][0][k] for k in ("resolvedFile", "sha256", "evidenceId", "ownEvidenceKey", "depth", "classification")}
                                    if entry["embeddedContent"] else None),
                "normalized": normalized,
                "sections": entry["embeddedContent"][0]["sections"] if entry["embeddedContent"] else [],
                "unresolvedEmbeddedReferences": entry["unresolvedEmbeddedReferences"],
                "outerRelationships": entry["outerRelationships"],
                "branchIdentity": branch_identity,
            })
        operations_out.append({
            "method": op["method"], "path": op["path"], "operationId": op["operationId"], "status": "active",
            "sparxMethod": op["sparxMethod"], "methodOwner": op["methodOwner"], "methodRelationships": method_entry["outerRelationships"],
            "process": next((e for e in elements if e["role"] == "process"), None),
            "diagrams": [e for e in elements if e["role"] == "diagram"],
            "lanes": [e for e in elements if e["role"] == "lane"],
            "startEvents": [e for e in elements if e["role"] == "startEvent"],
            "endEvents": [{"label": e["name"], "page": e["page"], "guid": e["guid"]} for e in elements if e["role"] == "endEvent"],
            "activities": activities,
            "matchedBy": op.get("matchedBy"),
            "alternateSparxMethods": op.get("alternateSparxMethods", []),
            "ambiguity": op.get("ambiguity"),
            "complementEvidence": complement_evidence(op),
            "branchIdentity": branch_identity,
        })

    data_definitions = []
    for page in sorted(data_pages):
        definition = ed.extract_data_definition((root / page).relative_to(repo).as_posix(), repo, root)
        definition["branchIdentity"] = branch_identity
        definition["inAuthoritativeBranch"] = page.startswith(branch["pagePathPrefix"] + "/")
        definition["referencedBy"] = data_pages[page]["referencedBy"]
        definition["definesColumns"] = bool(definition["columns"])
        data_definitions.append(definition)

    document = {
        "version": 1, "kind": "sparx-authoritative-endpoint-detail",
        "authority": {"file": args.authority.as_posix(), "sha256": hashlib.sha256(args.authority.read_bytes()).hexdigest(),
                      "branch": branch_identity, "selectionRule": authority["selection"]["rule"]},
        "excludedInactiveOperations": [{"method": m, "path": p} for m, p in sorted(inactive)],
        "operations": operations_out,
        "dataDefinitions": data_definitions,
        "scope": {"onlyAuthoritativeBranchEvidence": True, "httpToCrudInferred": False, "sqlInvented": False,
                  "complementBranches": [c["branchRootId"] for c in complements]},
    }
    args.output.write_bytes(dump_bytes(document))
    # Include target-owned linked documents as a separate evidence artifact. This
    # inventory never changes normalized endpoint semantics or follows model links.
    import sparx_attachments
    attachments = sparx_attachments.inventory(repo, root, sparx_attachments.authorized_pages(authority))
    args.output.with_name('sparx-attachments.yml').write_bytes(dump_bytes(attachments))

    # ---- non-authoritative evidence register (prior artifacts classified by source-page branch)
    prefixes = {b["branchRootId"]: b for b in authority["branches"]}

    def branch_for(page: str) -> dict[str, Any] | None:
        for b in authority["branches"]:
            if page.startswith(b["pagePathPrefix"] + "/"):
                return b
        return None

    register = []
    for artifact in args.prior_artifact:
        paths = artifact.rglob("*.yml") if artifact.is_dir() else [artifact]
        counts: dict[str, set[str]] = {}
        for file in sorted(paths):
            for page in set(PAGE_RE.findall(file.read_bytes().decode("utf-8", errors="replace"))):
                b = branch_for(page)
                counts.setdefault(b["branchRootId"] if b else "unmapped", set()).add(page)
        non_auth = {bid: sorted(p) for bid, p in counts.items() if bid in prefixes and prefixes[bid]["authorityClass"] not in ("authoritative-candidate", "authoritative-complement")}
        files = sorted(artifact.rglob("*.yml")) if artifact.is_dir() else [artifact]
        register.append({
            "artifact": artifact.as_posix(),
            "sha256": hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest(),
            "pagesByBranch": {bid: len(p) for bid, p in sorted(counts.items())},
            "mixedBranches": len([b for b in counts if b != "unmapped"]) > 1,
            "nonAuthoritativePages": non_auth,
            "classification": ("stale-for-code-generation" if non_auth else "no-non-authoritative-source-pages"),
        })
    nonauth_doc = {
        "version": 1, "kind": "sparx-nonauthoritative-evidence",
        "authority": document["authority"],
        "policy": "Retained for traceability only. Evidence from backup/historical/ambiguous branches must not feed specification or code generation, and must not be merged with authoritative evidence by name, route or label similarity.",
        "nonAuthoritativeBranches": [{k: b[k] for k in ("branchRootId", "branchRootGuid", "name", "pagePathPrefix", "authorityClass", "authorityReasons")}
                                     for b in authority["branches"] if b["authorityClass"] not in ("authoritative-candidate", "authoritative-complement")],
        "nonAuthoritativeOperationStructure": [
            {"branchRootId": b["branchRootId"], "operations": [{"method": o["method"], "path": o["path"], "sparxMethodPage": (o.get("sparxMethod") or {}).get("page"),
                                                                  "activityPages": [e["page"] for e in o.get("elements", []) if e["role"] == "activity"]}
                                                                 for o in b["operations"]]}
            for b in authority["branches"] if b["authorityClass"] not in ("authoritative-candidate", "authoritative-complement")],
        "priorArtifacts": register,
    }
    args.nonauthoritative_output.write_bytes(dump_bytes(nonauth_doc))
    print({"operations": [(o["method"], o["status"], len(o.get("activities", []))) for o in operations_out],
           "dataDefinitions": [d["page"] for d in data_definitions], "register": [(r["artifact"], r["classification"], r["pagesByBranch"]) for r in register]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
