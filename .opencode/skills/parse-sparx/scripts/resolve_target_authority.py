"""Generic source-authority resolution for a target service in a Sparx HTML export.

Sparx exports can contain parallel representations of the same service (current, backup, historical
copies). Names and routes match across them, so they MUST NOT be merged. This resolver reads only
the export's hierarchy metadata (js/data/*.xml table-of-contents rows) plus a handful of element
pages of the target, and writes a branch-authority artifact:

* candidate branches (the children of the lowest common ancestor that contain the target),
* explicit provenance markers (backup / historical wording in package names) with the twin evidence
  that makes them decisive (an unmarked sibling with the same normalized name),
* per-operation structure (method -> process -> pool -> lane -> activities/events) taken from
  explicit parent links, matched to OpenAPI operations by the literal ``METHOD-path`` element name,
* page-path prefixes so later stages can tell which branch a page belongs to.

No behavior is interpreted here and no business or service-specific rule exists in this module.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import index_sparx as ix  # noqa: E402

ROW_RE = re.compile(r"new Array\((.*)\);")
FIELD_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
STEREOTYPE_RE = re.compile(r"^\s*[«<]+\s*([^»>]+?)\s*[»>]+\s*(.*)$")
BACKUP_TOKENS = {"bkp", "backup", "bak", "copia", "copy"}
HISTORICAL_TOKENS = {"hist", "historic", "historical", "historico", "old", "legacy", "obsoleto", "obsolete", "deprecated", "anterior"}
ROLE_VOCABULARY = {
    "proceso": "process", "process": "process", "pool": "pool", "lane": "lane", "activity": "activity",
    "startevent": "startEvent", "endevent": "endEvent", "intermediateevent": "intermediateEvent",
    "metodo": "method", "method": "method", "servicio": "service", "service": "service",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold()


def split_stereotype(name: str) -> tuple[str | None, str]:
    match = STEREOTYPE_RE.match(name)
    return (match.group(1).strip(), match.group(2).strip()) if match else (None, name.strip())


def load_toc(data_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    packages: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for path in sorted(data_dir.glob("*.xml")):
        text = path.read_bytes().decode("utf-8", errors="replace")
        used = False
        for line in text.splitlines():
            match = ROW_RE.search(line)
            if not match:
                continue
            fields = FIELD_RE.findall(match.group(1))
            if len(fields) < 9 or not fields[0].startswith("0"):
                continue
            used = True
            stereotype, plain = split_stereotype(fields[2])
            if ":" not in fields[0]:
                packages.append({"id": fields[0], "name": fields[2], "page": fields[3], "guid": fields[7], "tocFile": path.name})
            else:
                elements.append({
                    "id": fields[0], "package": fields[0].rsplit(":", 1)[0], "stereotype": stereotype, "name": plain,
                    "rawName": fields[2], "page": fields[3], "ownId": fields[5], "parentId": fields[6], "tocType": fields[8],
                    "guid": fields[9] if len(fields) > 9 else "", "tocFile": path.name,
                })
        if used:
            hashes[path.name] = sha256(path)
    return packages, elements, hashes


def tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z0-9]+", fold(name)) if t]


def markers_for(name: str, where: str) -> list[dict[str, str]]:
    found = []
    for token in tokens(name):
        if token in BACKUP_TOKENS:
            found.append({"token": token, "class": "backup", "where": where})
        elif token in HISTORICAL_TOKENS:
            found.append({"token": token, "class": "historical", "where": where})
    return found


def normalized_name(name: str) -> str:
    keep = [t for t in tokens(name) if t not in BACKUP_TOKENS | HISTORICAL_TOKENS]
    return " ".join(keep)


def page_metadata(page: str, root: Path) -> dict[str, Any]:
    path = root / page
    if not path.is_file():
        return {"page": page, "available": False}
    issues = ix.IssueCollector()
    parser = ix.parse_html_page(path, page, issues)
    props: dict[str, str] = {}
    for item in ix.extract_properties(parser.tables):
        props.setdefault(ix.clean_text(str(item["name"])), str(item["value"]))
    return {
        "page": page, "available": True, "sha256": sha256(path),
        "created": props.get("Created"), "modified": props.get("Modified"), "status": props.get("Status"),
        "version": props.get("Version"), "author": props.get("Author"), "uuid": props.get("UUID"),
    }


def descendants(parent_own_id: str, children: dict[str, list[dict[str, Any]]], seen: set[str], depth: int = 0) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in children.get(parent_own_id, []):
        result.append({**row, "depth": depth})
        if row["ownId"] and row["ownId"] not in seen:
            seen.add(row["ownId"])
            result.extend(descendants(row["ownId"], children, seen, depth + 1))
    return result


def role_of(row: dict[str, Any]) -> str | None:
    if row["stereotype"]:
        return ROLE_VOCABULARY.get(fold(row["stereotype"]).replace(" ", ""))
    return "diagram" if "diagram" in fold(row["tocType"]) else None


def element_view(row: dict[str, Any], root: Path) -> dict[str, Any]:
    page_file = root / row["page"] if row["page"] else None
    return {
        "role": role_of(row), "stereotype": row["stereotype"], "name": row["name"], "page": row["page"], "guid": row["guid"],
        "ownId": row["ownId"], "parentId": row["parentId"], "depth": row.get("depth"),
        "pageSha256": sha256(page_file) if page_file and page_file.is_file() else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source_root", type=Path, help="Sparx export root containing js/data (e.g. input/sparx)")
    parser.add_argument("output", type=Path)
    parser.add_argument("--target", required=True, help="Exact element name of the target service")
    parser.add_argument("--openapi", type=Path, help=".factory/openapi-spec.yml; alternative to --sparx-only or --non-http")
    parser.add_argument("--non-http", action="store_true",
                        help="target has no HTTP contract (batch/shell): no OpenAPI is read, no operation matching is done; "
                              "only the branch of the exactly named service element is resolved")
    parser.add_argument("--sparx-only", action="store_true",
                        help="HTTP service without Swagger; discover literal METHOD-path operations from target-owned Sparx methods")
    parser.add_argument("--reviewed-decisions", type=Path)
    parser.add_argument("--source-authority-decision", type=Path,
                        help="Approved human decision (YAML: decisionId, primaryBranchRootId, complementBranchRootIds[], operationMatch) "
                             "that resolves parallel branches as primary + authoritative complements; without it ambiguity stops extraction")
    args = parser.parse_args()
    import yaml

    repo = Path.cwd().resolve()
    root = (repo / args.source_root).resolve()
    packages, elements, toc_hashes = load_toc(root / "js" / "data")
    pkg_by_id = {p["id"]: p for p in packages}
    if sum((args.non_http, args.sparx_only, args.openapi is not None)) != 1:
        raise SystemExit("exactly one of --openapi, --sparx-only (HTTP without Swagger), or --non-http is required")
    if args.non_http or args.sparx_only:
        operations = []
    else:
        openapi = yaml.safe_load(args.openapi.read_bytes())
        operations = [{"method": o["method"], "path": o["path"], "operationId": o.get("operationId")} for o in openapi["operations"]]

    matches = [e for e in elements if e["name"] == args.target]
    paths = sorted({m["package"] for m in matches})

    def ancestors(package_id: str) -> list[str]:
        parts = package_id.split(".")
        return [".".join(parts[: i + 1]) for i in range(len(parts))]

    common = os.path.commonprefix([ancestors(p) for p in paths]) if paths else []
    if isinstance(common, str):
        common = []
    lca = common[-1] if common and len(paths) > 1 else None
    if len(paths) == 1:
        lca = ancestors(paths[0])[0]
    branch_roots: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        chain = ancestors(match["package"])
        index = chain.index(lca) + 1 if lca in chain else 1
        branch_roots.setdefault(chain[min(index, len(chain) - 1)], []).append(match)

    decisions = []
    if args.reviewed_decisions and args.reviewed_decisions.is_file():
        decisions = yaml.safe_load(args.reviewed_decisions.read_bytes()).get("decisions", [])
    element_by_page = {e["page"]: e for e in elements}
    authority_decision: dict[str, Any] | None = None
    if args.source_authority_decision:
        authority_decision = yaml.safe_load(args.source_authority_decision.read_bytes()) or {}
        for key in ("decisionId", "primaryBranchRootId"):
            if not authority_decision.get(key):
                raise SystemExit(f"source-authority decision is missing '{key}'")
        authority_decision.setdefault("complementBranchRootIds", [])
        if authority_decision.get("operationMatch", "method-name") != "method-name":
            raise SystemExit("source-authority decision operationMatch must be 'method-name'")
        known = set(branch_roots)
        declared = {authority_decision["primaryBranchRootId"], *authority_decision["complementBranchRootIds"]}
        if not declared <= known or authority_decision["primaryBranchRootId"] in authority_decision["complementBranchRootIds"]:
            raise SystemExit(f"source-authority decision references unknown/duplicated branches {sorted(declared)}; candidates are {sorted(known)}")
    complement_ids = set(authority_decision["complementBranchRootIds"]) if authority_decision else set()
    primary_id = authority_decision["primaryBranchRootId"] if authority_decision else None

    def branch_of_page(page: str) -> str | None:
        rel = page if page.startswith("EARoot") else page.split("PROYECT/", 1)[-1]
        element = element_by_page.get(rel)
        if not element:
            return None
        for branch_id in branch_roots:
            if element["package"] == branch_id or element["package"].startswith(branch_id + "."):
                return branch_id
        return None

    branches: list[dict[str, Any]] = []
    for branch_id, service_rows in sorted(branch_roots.items()):
        package = pkg_by_id.get(branch_id, {"name": branch_id, "page": "", "guid": ""})
        chain_names = [pkg_by_id[a]["name"] for a in ancestors(service_rows[0]["package"]) if a in pkg_by_id]
        below = [a for a in ancestors(service_rows[0]["package"]) if a == branch_id or a.startswith(branch_id + ".")]
        marker_list = markers_for(package["name"], f"branch-root:{branch_id}")
        for ancestor in below[1:]:
            marker_list += markers_for(pkg_by_id.get(ancestor, {}).get("name", ""), f"package:{ancestor}")
        branch_elements = [e for e in elements if e["package"] == branch_id or e["package"].startswith(branch_id + ".")]
        children: dict[str, list[dict[str, Any]]] = {}
        for e in branch_elements:
            children.setdefault(e["parentId"], []).append(e)
        prefixes = sorted({posixpath.dirname(e["page"].replace("\\", "/")) for e in branch_elements if e["page"]})
        page_prefix = posixpath.commonpath([p for p in prefixes if p]) if any(prefixes) else ""
        service = service_rows[0]
        branch_ops = []
        method_rows = [e for e in branch_elements if role_of(e) == "method"]
        service_ids = {r["ownId"] for r in service_rows if role_of(r) == "service"} or {service["ownId"]}
        is_complement = branch_id in complement_ids
        lane_rows = [e for e in branch_elements if role_of(e) == "lane"]
        branch_operations = operations
        if args.sparx_only:
            branch_operations = []
            for row in method_rows:
                match = re.fullmatch(r'(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)[ -](/\S+)', row['name'])
                if row['parentId'] in service_ids and match:
                    branch_operations.append({'method': match[1], 'path': match[2], 'operationId': None})
        for op in branch_operations:
            literal = f"{op['method']}-{op['path']}"
            hits = [m for m in method_rows if m["name"] in (literal, f"{op['method']} {op['path']}")]
            if args.sparx_only:
                hits = [m for m in hits if m['parentId'] in service_ids]
            segment = op["path"].rstrip("/").rsplit("/", 1)[-1]
            matched_by = "literal-method-path"
            if not hits and authority_decision and not is_complement:
                hits = [m for m in method_rows if m["name"] == segment and m["parentId"] in service_ids]
                matched_by = "method-name-owned-by-target-service"
            entry: dict[str, Any] = {"method": op["method"], "path": op["path"], "operationId": op["operationId"], "sparxMethodElements": len(hits)}
            if is_complement:
                lanes = [lane for lane in lane_rows if lane["name"] == segment]
                entry["sparxMethodElements"] = 0
                entry["complementLanes"] = len(lanes)
                entry["matchedBy"] = "lane-name"
                if lanes:
                    entry["complementEvidence"] = [{
                        "lane": element_view(lane, root),
                        "elements": [element_view(t, root) for t in descendants(lane["ownId"], children, set())],
                    } for lane in lanes]
                    if len(lanes) > 1:
                        entry["ambiguity"] = "multiple lanes share the operation name in this complement branch"
                branch_ops.append(entry)
                continue
            if hits:
                entry["matchedBy"] = matched_by
                if len(hits) > 1:
                    entry["alternateSparxMethods"] = [element_view(h, root) for h in hits[1:]]
                method = hits[0]
                tree = descendants(method["ownId"], children, set())
                owner = next((e for e in branch_elements if e["ownId"] == method["parentId"]), None)
                entry.update({
                    "sparxMethod": element_view(method, root),
                    "methodOwner": {"name": owner["name"] if owner else None, "stereotype": owner["stereotype"] if owner else None,
                                    "isTargetService": bool(owner and owner["ownId"] == service["ownId"])},
                    "elements": [element_view(t, root) for t in tree],
                })
                if len(hits) > 1:
                    entry["ambiguity"] = "multiple Sparx method elements share the literal name in this branch"
            branch_ops.append(entry)
        sparx_only = [element_view(m, root) for m in method_rows
                      if m["parentId"] in service_ids and all(m["name"] not in (f"{o['method']}-{o['path']}", f"{o['method']} {o['path']}") for o in branch_operations)
                      and not (authority_decision and any(m["name"] == o["path"].rstrip("/").rsplit("/", 1)[-1] for o in operations))]
        branches.append({
            "branchRootId": branch_id, "branchRootGuid": package["guid"], "name": package["name"], "page": package["page"],
            "pagePathPrefix": page_prefix, "packagePath": chain_names,
            "service": {**element_view(service, root), "tocId": service["id"], "package": service["package"]},
            "markers": marker_list, "normalizedName": normalized_name(package["name"]),
            "metadata": {"branchRoot": page_metadata(package["page"], root) if package["page"] else None,
                         "service": page_metadata(service["page"], root)},
            "operations": branch_ops, "sparxOnlyMethods": sparx_only,
            **({'unresolvedHttpMethods': [element_view(m, root) for m in method_rows
                 if m['parentId'] in service_ids and not re.fullmatch(
                     r'(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)[ -](/\S+)', m['name'])]}
               if args.sparx_only else {}),
        })

    # --- authority classification (explicit structural/provenance evidence only)
    by_normalized: dict[str, list[dict[str, Any]]] = {}
    for b in branches:
        by_normalized.setdefault(b["normalizedName"], []).append(b)
    for b in branches:
        classes = {m["class"] for m in b["markers"]}
        twins = [t for t in by_normalized[b["normalizedName"]] if t is not b]
        reasons: list[str] = []
        if authority_decision and b["branchRootId"] == primary_id:
            b["authorityClass"] = "authoritative-candidate"
            reasons.append(f"human decision {authority_decision['decisionId']}: primary authoritative branch")
        elif authority_decision and b["branchRootId"] in complement_ids:
            b["authorityClass"] = "authoritative-complement"
            reasons.append(f"human decision {authority_decision['decisionId']}: authoritative complement (never merged by similarity; evidence cited per branch)")
        elif authority_decision:
            b["authorityClass"] = "non-authoritative"
            reasons.append(f"human decision {authority_decision['decisionId']}: branch not selected")
        elif "backup" in classes:
            b["authorityClass"] = "backup"
            reasons.append("branch path carries an explicit backup marker: " + ", ".join(f"{m['token']}@{m['where']}" for m in b["markers"] if m["class"] == "backup"))
            if any(not t["markers"] for t in twins):
                reasons.append("an unmarked twin branch with the same normalized name exists")
        elif "historical" in classes:
            b["authorityClass"] = "historical"
            reasons.append("branch path carries an explicit historical marker")
        elif len(branches) == 1:
            b["authorityClass"] = "authoritative-candidate"
            reasons.append("sole branch containing the target")
        else:
            marked_twins = [t for t in twins if t["markers"]]
            if marked_twins:
                b["authorityClass"] = "authoritative-candidate"
                reasons.append("unmarked branch whose same-name twin carries a backup/historical marker: "
                               + ", ".join(t["branchRootId"] for t in marked_twins))
            else:
                b["authorityClass"] = "ambiguous"
                reasons.append("no provenance marker or other structural evidence distinguishes this branch from its siblings")
        b["authorityReasons"] = reasons
    candidates = [b for b in branches if b["authorityClass"] == "authoritative-candidate"]
    ambiguities: list[str] = []
    if len(candidates) != 1:
        ambiguities.append(f"{len(candidates)} authoritative candidates found; selection withheld")
    selection = {
        "status": "resolved" if len(candidates) == 1 and not any(b["authorityClass"] == "ambiguous" for b in branches) else "ambiguous",
        "authoritativeBranchRootId": candidates[0]["branchRootId"] if len(candidates) == 1 else None,
        "rule": "unmarked branch is authoritative only when every other parallel branch is explicitly marked backup/historical (or is the only branch); ambiguity is reported, never merged",
        "timestampsUsedAsRule": False,
    }
    if authority_decision:
        selection["rule"] = ("human-approved source-authority decision: primary branch plus authoritative complements, matched by exact "
                             "operation name only; branches are never merged by similarity")
        selection["decision"] = {"decisionId": authority_decision["decisionId"], "primaryBranchRootId": primary_id,
                                 "complementBranchRootIds": sorted(complement_ids), "operationMatch": "method-name",
                                 "file": args.source_authority_decision.as_posix(), "sha256": sha256(args.source_authority_decision)}
        selection["complementBranchRootIds"] = sorted(complement_ids)

    # --- structural findings and reviewed lifecycle decisions, per branch (never merged across branches)
    for b in branches:
        findings = []
        if b["branchRootId"] in complement_ids:
            b["structuralFindings"] = [{"kind": "openapi-operation-without-complement-lane", "operation": f"{op['method']} {op['path']}"}
                                       for op in b["operations"] if not op.get("complementLanes")]
            b["reviewedLifecycleDecisions"] = []
            continue
        for op in b["operations"]:
            if not op["sparxMethodElements"]:
                findings.append({"kind": "openapi-operation-without-sparx-method", "operation": f"{op['method']} {op['path']}"})
            elif not op["methodOwner"]["isTargetService"]:
                findings.append({"kind": "sparx-method-owned-by-non-service-element", "operation": f"{op['method']} {op['path']}",
                                 "owner": op["methodOwner"]["name"], "ownerStereotype": op["methodOwner"]["stereotype"]})
        b["structuralFindings"] = findings
        lifecycle = []
        for d in decisions:
            target = d.get("target") or {}
            branch_hits = {branch_of_page(sp["file"]) for sp in d.get("sourcePages", [])}
            if b["branchRootId"] in branch_hits:
                lifecycle.append({"decisionId": d["decisionId"], "method": target.get("method"), "path": target.get("path"),
                                  "lifecycleState": target.get("lifecycleState"), "disposition": target.get("disposition")})
        b["reviewedLifecycleDecisions"] = lifecycle
    timestamps = {b["branchRootId"]: b["metadata"]["service"].get("modified") for b in branches}

    document = {
        "version": 1, "kind": "sparx-target-authority",
        "contractMode": "sparx-only" if args.sparx_only else "non-http" if args.non_http else "openapi",
        "target": {"name": args.target, "sourceRoot": args.source_root.as_posix(), "matchedElements": len(matches)},
        "hierarchySources": {"tocFiles": toc_hashes, "openapi": ({"file": args.openapi.as_posix(), "sha256": sha256(args.openapi)} if args.openapi else None),
                             "reviewedDecisions": ({"file": args.reviewed_decisions.as_posix(), "sha256": sha256(args.reviewed_decisions)}
                                                   if args.reviewed_decisions else None)},
        "lowestCommonAncestor": lca,
        "selection": selection,
        "ambiguities": ambiguities,
        "branches": branches,
        "observations": {"serviceModifiedByBranch": timestamps,
                         "note": "timestamps are reported only; they are not an authority rule"},
    }

    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    args.output.write_bytes(yaml.dump(document, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=140).encode("utf-8"))
    print({"branches": [(b["branchRootId"], b["name"], b["authorityClass"]) for b in branches], "selection": selection["authoritativeBranchRootId"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
