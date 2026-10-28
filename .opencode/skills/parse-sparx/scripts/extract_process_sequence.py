"""Extract explicit SequenceFlow connectivity of the authoritative operations (generic).

Reads only the process elements already listed in the authoritative endpoint-detail artifact:
the start event, the activities, the intermediate (error) events and the end events of each active
operation. Each page's connector table ("Element | Name" rows ending in «SequenceFlow») is
preserved; directions are resolved structurally (start events only emit, end events only receive,
error events emit to end events, and activity-to-activity pairs are oriented away from the
already-reached node). Numeric label order is never used as sequence. No behavior is interpreted.
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
import index_sparx as ix  # noqa: E402

FLOW_ROW = re.compile(r"^(?P<name>.*?)\s+(?P<ntype>\S+)\s+[«<]+(?P<conn>[^»>]+)[»>]+\s*$")


def read_flow_page(page: str, repo: Path, root: Path) -> dict[str, Any]:
    absolute = (root / page).resolve()
    rel = absolute.relative_to(root.resolve()).as_posix()
    issues = ix.IssueCollector()
    parser = ix.parse_html_page(absolute, rel, issues)
    key = ix.evidence_page_key(rel)
    flows: list[dict[str, Any]] = []
    for table_index, table in enumerate(parser.tables):
        rows = [[ix.clean_text(str(c.get("text", ""))) for c in row] for row in table.rows]
        if not rows or len(rows[0]) < 2 or ix.clean_text(rows[0][0]).casefold() not in {"element", "elemento"}:
            continue
        for row in rows[1:]:
            match = FLOW_ROW.match(row[0]) if row else None
            if match and "sequenceflow" in match.group("conn").casefold().replace(" ", ""):
                flows.append({"neighborName": match.group("name").strip(), "neighborType": match.group("ntype"),
                              "connector": match.group("conn"), "label": row[1] if len(row) > 1 else "",
                              "tableOrdinal": table_index, "evidenceId": ix.evidence_id(key, "flow", len(flows))})
    return {"page": absolute.relative_to(repo).as_posix(), "relativePage": rel, "sha256": hashlib.sha256(absolute.read_bytes()).hexdigest(), "flows": flows}


def orient(op: dict[str, Any], pages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    nodes = {e["page"]: e for e in op["elements"] if e["role"] in {"startEvent", "endEvent", "intermediateEvent", "activity"}}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for e in nodes.values():
        by_name.setdefault(e["name"], []).append(e)
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    ambiguous: list[dict[str, Any]] = []
    pairs: list[tuple[str, str, dict[str, Any]]] = []

    def add(src: str, dst: str, label: str, evidence: str, via: str) -> None:
        edges.setdefault((src, dst), {"from": src, "to": dst, "label": label, "evidence": [], "orientation": via})["evidence"].append(evidence)

    for page, node in nodes.items():
        record = pages.get(page)
        if not record:
            continue
        for flow in record["flows"]:
            candidates = by_name.get(flow["neighborName"], [])
            if flow["neighborType"] == "NodoDeObjeto" or len(candidates) != 1:
                ambiguous.append({"page": page, "flow": flow, "candidates": [c["page"] for c in candidates]})
                continue
            other = candidates[0]
            if node["role"] == "startEvent":
                add(page, other["page"], flow["label"], flow["evidenceId"], "start-event-emits")
            elif node["role"] == "intermediateEvent" and other["role"] == "endEvent":
                add(page, other["page"], flow["label"], flow["evidenceId"], "error-event-emits-to-end-event")
            elif node["role"] == "endEvent":
                add(other["page"], page, flow["label"], flow["evidenceId"], "end-event-receives")
            elif node["role"] == "activity" and other["role"] == "endEvent":
                add(page, other["page"], flow["label"], flow["evidenceId"], "activity-to-end-event")
            elif node["role"] == "activity" and other["role"] == "startEvent":
                add(other["page"], page, flow["label"], flow["evidenceId"], "start-event-emits")
            elif node["role"] == "activity" and other["role"] == "activity":
                pairs.append((page, other["page"], flow))
    reached = {dst for (_, dst) in edges if nodes[edges[(_, dst)]["from"]]["role"] == "startEvent"}
    reached |= {src for (src, _) in edges if nodes[src]["role"] == "startEvent"}
    changed = True
    while changed:
        changed = False
        for a, b, flow in pairs:
            for src, dst in ((a, b), (b, a)):
                if src in reached and dst not in reached and (src, dst) not in edges and (dst, src) not in edges:
                    add(src, dst, flow["label"], flow["evidenceId"], "oriented-away-from-reached-node")
                    reached.add(dst)
                    changed = True
    # error events attach to the activity named by explicit parent link
    attachments = []
    for e in op["elements"]:
        if e["role"] == "intermediateEvent":
            parent = next((n for n in nodes.values() if n["ownId"] == e["parentId"]), None)
            attachments.append({"errorEventPage": e["page"], "attachedActivityPage": parent["page"] if parent else None,
                                "attachedActivity": parent["name"] if parent else None})
    def view(edge: dict[str, Any]) -> dict[str, Any]:
        return {**edge, "fromName": nodes[edge["from"]]["name"], "toName": nodes[edge["to"]]["name"],
                "fromRole": nodes[edge["from"]]["role"], "toRole": nodes[edge["to"]]["role"]}
    return {"edges": [view(e) for e in sorted(edges.values(), key=lambda x: (x["from"], x["to"]))],
            "errorEventAttachments": attachments, "unresolvedAmbiguousFlowRows": ambiguous}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import yaml

    repo = Path.cwd().resolve()
    root = (repo / args.source_root).resolve()
    authority = yaml.safe_load(args.authority.read_bytes())
    branch = next(b for b in authority["branches"] if b["branchRootId"] == authority["selection"]["authoritativeBranchRootId"])
    inactive = {(d["method"], d["path"]) for d in branch["reviewedLifecycleDecisions"] if d.get("disposition") == "inactive"}
    out_ops = []
    for op in branch["operations"]:
        if (op["method"], op["path"]) in inactive or not op["sparxMethodElements"]:
            continue
        pages: dict[str, dict[str, Any]] = {}
        for e in op["elements"]:
            if e["role"] in {"startEvent", "endEvent", "intermediateEvent", "activity"}:
                pages[e["page"]] = read_flow_page(e["page"], repo, root)
        result = orient(op, pages)
        out_ops.append({"method": op["method"], "path": op["path"], "pagesRead": {p: {"sha256": r["sha256"], "flowRows": len(r["flows"])} for p, r in sorted(pages.items())},
                        **result})

    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    document = {"version": 1, "kind": "sparx-authoritative-sequence-flow",
                "authority": {"file": args.authority.as_posix(), "sha256": hashlib.sha256(args.authority.read_bytes()).hexdigest(),
                              "branchRootId": branch["branchRootId"], "authorityClass": branch["authorityClass"]},
                "scope": {"onlyAuthoritativeBranch": True, "numericLabelOrderUsedAsSequence": False}, "operations": out_ops}
    args.output.write_bytes(yaml.dump(document, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=140).encode("utf-8"))
    print([(o["method"], len(o["edges"]), len(o["unresolvedAmbiguousFlowRows"])) for o in out_ops])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
