"""Phase 8.5: decision-aware readiness reassessment and authoritative spec consolidation.

Stages
  --stage reassess      derive the effective behavior of every active operation from
                        OpenAPI + authoritative Sparx + approved human-reviewed decisions, classify every
                        conflict, and write .factory/sparx-decision-reassessment.yml (gates only).
  --stage consolidate   run the reassessment and, ONLY if strictImplementationReady and
                        functionalCodeGenerationReady are both true, archive the previous specs and write
                        .factory/sparx-spec.yml and .factory/service-spec.yml.

Everything is deterministic (no timestamps, no model calls). Non-authoritative (backup/historical) evidence is
never read for semantics. Human-reviewed decisions are applied through their machine-readable `machineEffects`,
each exactly once, and always side by side with the source evidence they override.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path.cwd().resolve()
F = ROOT / ".factory"
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import reconcile_specs as rs  # noqa: E402  (contract builder shared with the existing reconciliation script)

PATHS = {
    "openapi": ".factory/openapi-spec.yml",
    "detail": ".factory/sparx-authoritative-endpoint-detail.yml",
    "authority": ".factory/sparx-target-authority.yml",
    "decisions": ".factory/sparx-reviewed-decisions.yml",
    "sequence": ".factory/sparx-authoritative-sequence-flow.yml",
    "prose": ".factory/sparx-authoritative-prose-interpretation.yml",
    "previousReassessment": ".factory/sparx-authoritative-reassessment.yml",
    "nonAuthoritative": ".factory/sparx-nonauthoritative-evidence.yml",
}
TEXTUAL = ("VARCHAR", "CLOB", "CHAR", "NVARCHAR", "NCLOB")
HASH_LIKE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def load(key_or_path: str) -> Any:
    path = PATHS.get(key_or_path, key_or_path)
    return yaml.safe_load((ROOT / path).read_bytes())


def encode(value: Any) -> bytes:
    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    return yaml.dump(value, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=140).encode("utf-8")


def unref(schema: Any) -> Any:
    while isinstance(schema, dict) and "resolved" in schema:
        schema = schema["resolved"]
    return schema or {}


def evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key in {"evidenceId", "sectionEvidenceId"} and isinstance(item, str):
                    found.add(item)
                else:
                    walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return found


# ---------------------------------------------------------------------------------------------
# derivation
# ---------------------------------------------------------------------------------------------

class Context:
    def __init__(self) -> None:
        self.api = load("openapi")
        self.detail = load("detail")
        self.authority = load("authority")
        self.decisions = load("decisions")["decisions"]
        self.sequence = load("sequence")
        self.prose = load("prose")
        self.previous = load("previousReassessment")
        self.branch = self.authority["branches"][[b["branchRootId"] for b in self.authority["branches"]].index(self.authority["selection"]["authoritativeBranchRootId"])]
        self.branch_identity = self.detail["authority"]["branch"]
        tables = [d for d in self.detail["dataDefinitions"] if d["definesColumns"]]
        assert len(tables) == 1, "exactly one authoritative data definition with columns expected"
        self.table = tables[0]
        self.columns = {c["column"]: c for c in self.table["columns"]}
        self.pk = [d for d in self.table["keyAndIndexDeclarations"] if d["kind"] == "primaryKey"]
        effects = {d["decisionId"]: d.get("machineEffects", {}) for d in self.decisions if d.get("machineEffects")}
        self.effects = effects
        self.consumed: dict[str, list[str]] = {k: [] for k in effects}

    def decision(self, decision_id: str) -> dict[str, Any]:
        return next(d for d in self.decisions if d["decisionId"] == decision_id)

    def effect(self, effect_key: str) -> list[tuple[str, Any]]:
        return [(did, eff[effect_key]) for did, eff in self.effects.items() if effect_key in eff]

    def op_detail(self, method: str) -> dict[str, Any]:
        return next(o for o in self.detail["operations"] if o["method"] == method)

    def api_op(self, method: str) -> tuple[int, dict[str, Any]]:
        for index, op in enumerate(self.api["operations"]):
            if op["method"] == method:
                return index, op
        raise KeyError(method)


def physical(ctx: Context, literal: str) -> tuple[str, dict[str, Any] | None]:
    """Normalize a DML column token through the approved alias decision; verify against the table definition."""
    aliases: dict[str, str] = {}
    for did, effect in ctx.effect("columnAliases"):
        aliases.update(effect["aliases"])
    target = aliases.get(literal, literal)
    alias_info = None
    if target != literal:
        alias_info = {"literalToken": literal, "physicalColumn": target, "decisionId": next(d for d, e in ctx.effect("columnAliases"))}
        ctx.consumed[alias_info["decisionId"]].append(f"alias {literal}->{target}")
    return target, alias_info


def is_textual(data_type: str) -> bool:
    return data_type.upper().startswith(TEXTUAL)


def derive_operation(ctx: Context, method: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    op = ctx.op_detail(method)
    api_index, api_op = ctx.api_op(method)
    validation = next(a for a in op["activities"] if a["normalized"]["activityRole"] == "validation")
    behavior = next(a for a in op["activities"] if a["normalized"]["activityRole"] == "behavior")
    nb, nv = behavior["normalized"], validation["normalized"]
    statement = nb["considerations"]["statements"][0]
    descriptor = nb["descriptor"]
    inputs = {r["input"]: r for r in nb["input"]["rows"]}
    by_destination = {r["destination"]: r for r in nb["input"]["rows"]}
    prose = ctx.prose["operations"][method]
    out: dict[str, Any] = {"method": method, "path": op["path"], "operationId": op["operationId"]}

    def blocker(code: str, description: str, **kw: Any) -> None:
        blockers.append({"id": code, "classification": "unresolved-business-blocker", "operation": f"{method} {op['path']}", "description": description, **kw})

    def input_for(placeholder: str) -> dict[str, Any] | None:
        name = placeholder.strip("<>")
        row = by_destination.get(name)
        if row is None:
            blocker("placeholder-without-input", f"Statement placeholder {placeholder} has no INPUT row with that destination.", statementEvidenceId=statement["evidenceId"])
            return None
        return {"input": row["input"], "origin": row["origin"], "destination": row["destination"], "evidenceId": row["evidenceId"]}

    def column_ref(literal: str, strict: bool = True) -> dict[str, Any]:
        target, alias = physical(ctx, literal)
        if strict and target not in ctx.columns:
            blocker("column-not-in-authoritative-table", f"{target} (from {literal}) is not defined by the authoritative table.")
        col = ctx.columns.get(target)
        if not strict and col is None:
            return {"literalToken": literal, "physicalColumn": None, "absentFromTable": True, "aliasApplied": False, "aliasDecisionId": None, "dataType": None, "columnEvidenceId": None}
        return {"literalToken": literal, "physicalColumn": target, "aliasApplied": alias is not None, "aliasDecisionId": alias["decisionId"] if alias else None,
                "dataType": col["dataType"] if col else None, "columnEvidenceId": col["evidenceId"] if col else None}

    out["sources"] = {
        "authoritativeBranch": ctx.branch_identity,
        "method": {"page": op["sparxMethod"]["page"], "guid": op["sparxMethod"]["guid"], "pageSha256": op["sparxMethod"]["pageSha256"]},
        "process": {"page": op["process"]["page"], "guid": op["process"]["guid"], "name": op["process"]["name"]},
        "validationActivity": {k: validation["activity"][k] for k in ("name", "uuid", "page", "pageSha256", "modified", "status")},
        "behaviorActivity": {k: behavior["activity"][k] for k in ("name", "uuid", "page", "pageSha256", "modified", "status")},
        "validationLinkdoc": {k: validation["embeddedLinkdoc"][k] for k in ("resolvedFile", "sha256", "evidenceId")},
        "behaviorLinkdoc": {k: behavior["embeddedLinkdoc"][k] for k in ("resolvedFile", "sha256", "evidenceId")},
        "dataDefinition": {"page": ctx.table["page"], "uuid": ctx.table["identity"]["uuid"], "sha256": ctx.table["sha256"]},
    }
    # ---- sequencing (explicit SequenceFlow connectors)
    seq = next(o for o in ctx.sequence["operations"] if o["method"] == method)
    activity_by_page = {validation["activity"]["page"]: "validation", behavior["activity"]["page"]: "behavior"}
    out["flow"] = {
        "normal": [{"from": e["fromName"], "fromRole": e["fromRole"], "to": e["toName"], "toRole": e["toRole"], "evidence": e["evidence"], "orientation": e["orientation"]}
                   for e in seq["edges"] if e["fromRole"] != "intermediateEvent"],
        "errorPaths": [{"attachedActivity": next((a["attachedActivity"] for a in seq["errorEventAttachments"] if a["errorEventPage"] == e["from"]), None),
                        "attachedRole": activity_by_page.get(next((a["attachedActivityPage"] for a in seq["errorEventAttachments"] if a["errorEventPage"] == e["from"]), ""), None),
                        "label": e["label"], "endEvent": e["toName"], "evidence": e["evidence"]}
                       for e in seq["edges"] if e["fromRole"] == "intermediateEvent"],
        "numericLabelOrderUsedAsSequence": False,
    }
    # ---- validation
    header_rows = nv["validation"]["headerrequest"]["rows"]
    api_headers = sorted(p["name"] for p in api_op["parameters"]["header"])
    sparx_headers = sorted(r["headerrequest"] for r in header_rows)
    if api_headers != sparx_headers:
        blocker("header-set-mismatch", "Sparx HeaderRequest rows differ from OpenAPI header parameters.", openapi=api_headers, sparx=sparx_headers)
    out["validation"] = {
        "headers": {"sparxRows": [{"name": r["headerrequest"], "required": r.get("necesario"), "type": r.get("tipo"), "evidenceId": r["evidenceId"]} for r in header_rows],
                    "matchesOpenapiHeaderParameters": api_headers == sparx_headers},
        "parts": {k: {"sectionEvidenceId": v["sectionEvidenceId"], "rows": v["rows"]} for k, v in nv["validation"].items() if k != "headerrequest" and v["rows"]},
        "rules": [{**r, "authority": "authoritative-sparx"} for r in prose["validationRules"]],
        "contractDeclaredValidationOwner": "openapi",
    }
    # ---- persistence statement and mappings
    kind = descriptor["operation"].upper()
    action = {"SELECT": "select", "INSERT": "insert", "UPDATE": "update", "DELETE": "delete"}.get(kind)
    if action is None:
        blocker("unknown-operation-literal", f"Descriptor operation {kind!r} is not a recognised statement kind.")
    persistence: dict[str, Any] = {
        "descriptor": {"type": descriptor["type"], "name": descriptor["name"], "operation": descriptor["operation"], "connection": descriptor["connection"] or None,
                       "evidenceIds": descriptor["evidenceIds"]},
        "actionKind": action, "actionKindBasis": "literal Sparx Operación field (not inferred from the HTTP method)",
        "literalStatement": {"text": statement["normalizedText"], "evidenceId": statement["evidenceId"], "literalLines": statement["literalLines"]},
        "targetDataDefinition": {"name": ctx.table["identity"]["name"], "page": ctx.table["page"], "uuid": ctx.table["identity"]["uuid"]},
        "participationRules": prose["behaviorRules"],
    }
    mappings: dict[str, Any] = {"input": [], "output": []}
    decisions_used: list[dict[str, Any]] = []
    if action == "select":
        predicates = []
        policy = ctx.effect("filterPolicy")[0]
        for pred in statement["predicates"]:
            ref = column_ref(pred["column"]); source = input_for(pred["value"])
            textual = bool(ref["dataType"]) and is_textual(ref["dataType"])
            predicates.append({"sparxLiteral": {"connector": pred["connector"], "column": pred["column"], "operator": pred["operator"], "value": pred["value"]},
                               "parameter": source["input"] if source else None, "parameterOrigin": source["origin"] if source else None, "inputEvidenceId": source["evidenceId"] if source else None,
                               "column": ref, "effectiveMatch": policy[1]["textualMatch"] if textual else policy[1]["nonTextualMatch"],
                               "effectiveMatchBasis": "human-reviewed filter policy by physical column type", "sparxMatch": "equality (=)"})
        trailing = {t["keyword"]: t["text"] for t in statement.get("trailingClauses", [])}
        pagination = {k: {"literal": trailing.get(k.upper()), "parameter": (input_for(trailing[k.upper()]) or {}).get("input")} for k in ("limit", "offset") if trailing.get(k.upper())}
        order = trailing.get("ORDER BY")
        ctx.consumed[policy[0]].append("filterPolicy GET")
        decisions_used.append({"decisionId": policy[0], "effect": "filterPolicy"})
        persistence["query"] = {
            "filterPolicy": {"minimumActiveFilters": policy[1]["minimumActiveFilters"], "combinator": policy[1]["combinator"], "textualMatch": policy[1]["textualMatch"],
                             "nonTextualMatch": policy[1]["nonTextualMatch"], "caseSensitivity": policy[1]["caseSensitivity"], "violationOutcome": policy[1]["violationOutcome"],
                             "decisionId": policy[0], "overridesSparx": policy[1]["overrides"]},
            "businessFilters": predicates, "sparxLiteralPredicateCombinator": sorted({p["sparxLiteral"]["connector"] for p in predicates if p["sparxLiteral"]["connector"]}),
            "pagination": pagination, "paginationRule": next(r["ruleId"] for r in prose["validationRules"] if r["kind"] == "pagination-pairing"),
            "orderBy": {"literal": order, "physicalColumn": column_ref(order)["physicalColumn"] if order else None},
            "sparxSelectListLiteral": [column_ref(c, strict=False) for c in statement["selectList"]],
        }
        # response selection derived from OpenAPI response fields (decision 3 exposure rule)
        _, ok_resp = ctx.api_op(method)
        response_schema = unref(next(iter(ok_resp["responses"]["200"]["content"].values()))["schema"])
        items = unref(unref(unref(response_schema["properties"]["data"])["properties"]["mailingInfo"])["items"])
        api_fields = sorted(items["properties"])
        output_rows = {r["destination"].rsplit(".", 1)[-1]: r for r in nb["output"]["rows"]}
        added = {m["contractField"].rsplit(".", 1)[-1]: (did, m) for did, effs in ctx.effect("fieldMappings") for m in effs
                 if m["operation"]["method"] == method and m["direction"] == "column-to-response"}
        selected = []
        for field in api_fields:
            if field in output_rows:
                token = output_rows[field]["output"].split(".", 1)[-1]
                ref = column_ref(token)
                selected.append({"responseField": f"data.mailingInfo[].{field}", "column": ref, "origin": "authoritative-sparx-output-mapping",
                                 "sparxOutput": {"output": output_rows[field]["output"], "type": output_rows[field]["type"], "destination": output_rows[field]["destination"], "evidenceId": output_rows[field]["evidenceId"]}})
            elif field in added:
                did, m = added[field]
                ref = column_ref(m["column"])
                ctx.consumed[did].append(f"GET {m['column']}->{field}")
                selected.append({"responseField": f"data.mailingInfo[].{field}", "column": ref, "origin": "human-reviewed-decision", "decisionId": did})
                decisions_used.append({"decisionId": did, "effect": "fieldMappings GET"})
            else:
                blocker("response-field-without-source-column", f"OpenAPI response field {field} has no Sparx output mapping or reviewed mapping.")
        excluded = [{"sparxOutput": r["output"], "destination": r["destination"], "reason": "not declared by the OpenAPI response; audit/internal columns are not exposed (human-reviewed exposure rule)",
                     "evidenceId": r["evidenceId"], "decisionId": "human-reviewed-mailing-info-emailbody-mapping"}
                    for field, r in output_rows.items() if field not in api_fields]
        used_literals = {s["column"]["literalToken"] for s in selected}
        persistence["query"]["selectedColumns"] = selected
        persistence["query"]["sparxSelectColumnsNotSelected"] = [s["literalToken"] for s in persistence["query"]["sparxSelectListLiteral"] if s["literalToken"] not in used_literals and s["physicalColumn"] not in {x["column"]["physicalColumn"] for x in selected}]
        mappings["input"] = [{"parameter": r["input"], "origin": r["origin"], "destination": r["destination"], "evidenceId": r["evidenceId"]} for r in nb["input"]["rows"]]
        mappings["output"] = selected
        mappings["excludedSparxOutputs"] = excluded
        # TEMPLATEID-type leftovers: the Sparx select list names columns absent from the authoritative table
        persistence["query"]["sparxSelectColumnsAbsentFromTable"] = [s["literalToken"] for s in persistence["query"]["sparxSelectListLiteral"] if s.get("absentFromTable")]
        ctx.consumed["human-reviewed-mailing-info-emailbody-mapping"].append("responseExposureRule GET")
        decisions_used.append({"decisionId": "human-reviewed-mailing-info-emailbody-mapping", "effect": "responseExposureRule"})
    elif action in {"insert", "update"}:
        pairs: list[dict[str, Any]] = []
        raw = ([{"column": a["column"], "value": a["value"]} for a in statement.get("setAssignments", [])] if action == "update" else
               [{"column": p["column"], "value": p["value"]} for p in (statement.get("positionalPairs") or [])])
        for item in raw:
            ref = column_ref(item["column"])
            if item["value"].startswith("<"):
                src = input_for(item["value"])
                pairs.append({"column": ref, "value": {"kind": "request-input", "placeholder": item["value"], "input": src["input"] if src else None, "origin": src["origin"] if src else None, "inputEvidenceId": src["evidenceId"] if src else None},
                              "origin": "authoritative-sparx"})
            else:
                pairs.append({"column": ref, "value": {"kind": "database-function", "literal": item["value"]}, "origin": "authoritative-sparx"})
        added = [(did, m) for did, effs in ctx.effect("fieldMappings") for m in effs if m["operation"]["method"] == method and m["direction"] == "request-to-column"]
        for did, m in added:
            if any(p["column"]["physicalColumn"] == m["column"] for p in pairs):
                continue
            ref = column_ref(m["column"])
            ctx.consumed[did].append(f"{method} {m['contractField']}->{m['column']}")
            decisions_used.append({"decisionId": did, "effect": "fieldMappings request-to-column"})
            pairs.append({"column": ref, "value": {"kind": "request-input", "input": m["contractField"], "origin": "request", "inputEvidenceId": None}, "origin": "human-reviewed-decision", "decisionId": did})
        key = "assignments" if action == "update" else "columnValues"
        persistence[key] = pairs
        persistence["suppliedValuesOnly"] = {"rule": [r["ruleId"] for r in prose["behaviorRules"] if r["kind"] == "optional-clause-participation"],
                                             "effect": "only request fields with a supplied value participate; database functions and audit assignments are not request fields"}
        if action == "update":
            persistence["whereClause"] = [{"column": column_ref(p["column"]), "operator": p["operator"], "value": p["value"], "parameter": (input_for(p["value"]) or {}).get("input"),
                                           "origin": (input_for(p["value"]) or {}).get("origin")} for p in statement["predicates"]]
            for oc_did, oc in ctx.effect("outcomeSemantics"):
                for item in oc:
                    if item["operation"]["method"] == method:
                        ctx.consumed[oc_did].append(f"{method} not-found")
                        decisions_used.append({"decisionId": oc_did, "effect": "outcomeSemantics"})
                        persistence["noMatchingRecordOutcome"] = {"identifies": item["identifies"], "pathParameter": item["pathParameter"], "condition": item["condition"], "status": item["status"], "decisionId": oc_did}
        # OpenAPI request fields must each be mapped by Sparx or by a reviewed decision
        schema = unref(next(iter(api_op["requestBody"]["content"].values()))["schema"])
        mapped_inputs = {p["value"].get("input") for p in pairs if p["value"]["kind"] == "request-input"}
        missing = sorted(set(schema["properties"]) - mapped_inputs)
        if missing:
            blocker("openapi-request-field-without-mapping", f"OpenAPI request fields without a persistence mapping: {missing}")
        mappings["input"] = [{"parameter": r["input"], "origin": r["origin"], "destination": r["destination"], "evidenceId": r["evidenceId"]} for r in nb["input"]["rows"]]
        mappings["output"] = []
        mappings["excludedSparxOutputs"] = [{"sparxOutput": r["output"], "destination": r["destination"], "transformation": r.get("transformation"), "evidenceId": r["evidenceId"],
                                             "reason": "not declared by the OpenAPI response; OpenAPI owns response schemas"} for r in (nb["output"]["rows"] if nb["output"] else [])]
        # header-origin audit input
        header_inputs = [r for r in nb["input"]["rows"] if r["origin"].lower().startswith("header")]
        derived = []
        for row in header_inputs:
            norm = re.sub(r"[^a-z0-9]", "", row["destination"].casefold())
            candidates = [h for h in header_rows if re.sub(r"[^a-z0-9]", "", re.sub(r"^x-", "", h["headerrequest"].casefold())) == norm]
            if len(candidates) == 1:
                derived.append({"input": row["input"], "headerName": candidates[0]["headerrequest"], "headerDescription": candidates[0].get("descripcion-ejemplo"), "basis": "derived-structural: only HeaderRequest row whose name normalizes to the INPUT destination", "evidenceIds": [row["evidenceId"], candidates[0]["evidenceId"]]})
            else:
                blocker("header-input-unmapped", f"INPUT {row['input']} from headerRequest cannot be tied to exactly one HeaderRequest row.")
        mappings["headerDerivedMappings"] = derived
    else:
        blocker("unsupported-action-kind", f"No consolidation rule for {kind}.")
    if action == "select":
        mappings["headerDerivedMappings"] = []
    persistence["decisionsApplied"] = decisions_used
    out["persistence"] = persistence
    out["mappings"] = mappings
    # ---- outcomes (effective)
    statuses = {}
    for rule in prose["outcomes"]:
        status = rule["status"]
        if status is None:
            continue
        statuses[str(status)] = {"status": status, "condition": rule["condition"], "origin": "authoritative-sparx", "ruleId": rule["ruleId"], "evidenceId": rule["source"]["evidenceId"], "sourceText": rule["source"]["sourceText"]}
    for rule in prose["validationRules"]:
        if rule["kind"] == "failed-validation-outcome":
            statuses.setdefault(str(rule["status"]), {"status": rule["status"], "condition": "request fails validation", "origin": "authoritative-sparx", "ruleId": rule["ruleId"], "evidenceId": rule["source"]["sectionEvidenceId"], "sourceText": rule["source"]["sourceText"]})
    success = [e["label"] for e in op["endEvents"] if e["label"].isdigit() and e["label"].startswith("2")]
    for label in success:
        statuses[label] = {"status": int(label), "condition": "normal flow completes", "origin": "authoritative-sparx-end-event", "evidenceId": next(e["guid"] for e in op["endEvents"] if e["label"] == label)}
    persistence_not_found = persistence.get("noMatchingRecordOutcome")
    if persistence_not_found:
        statuses["404"] = {"status": 404, "condition": persistence_not_found["condition"], "origin": "human-reviewed-decision", "decisionId": persistence_not_found["decisionId"],
                           "sparxCorroboration": [p for p in out["flow"]["errorPaths"] if p["endEvent"] == "404"]}
    declared = set(api_op["responses"])
    amendments = []
    for did, items in ctx.effect("contractAmendments"):
        for item in items:
            if any(o["method"] == method for o in item["operations"]):
                amendments.append({"status": item["statusCode"], "decisionId": did, "item": item})
                ctx.consumed[did].append(f"{method} {item['statusCode']}")
                decisions_used.append({"decisionId": did, "effect": "contractAmendments"})
    effective_codes = declared | {a["status"] for a in amendments}
    for code, info in statuses.items():
        if code in {a["status"] for a in amendments}:
            info["effectiveContractOrigin"] = "human-reviewed-contract-amendment"
        if code not in effective_codes:
            blocker("status-outside-effective-contract", f"Status {code} is neither declared by OpenAPI nor approved by a reviewed amendment.", status=code)
    end_labels = {e["label"] for e in op["endEvents"]}
    out["outcomes"] = {"byStatus": dict(sorted(statuses.items())), "sparxEndEvents": sorted(end_labels),
                       "uncoveredSparxEndEvents": sorted(end_labels - set(statuses)), "declaredByOpenapi": sorted(declared)}
    for label in end_labels - set(statuses):
        blocker("end-event-without-outcome-rule", f"Sparx end event {label} has no stated condition.")
    out["effectiveResponses"] = [{"status": s, "origin": "openapi", "jsonPointer": f"/operations/{api_index}/responses/{rs.json_pointer_token(s)}"} for s in sorted(declared)] + \
        [{"status": a["status"], "origin": "human-reviewed-contract-amendment", "decisionId": a["decisionId"], "originalOpenapi": "absent",
          "authoritativeSparx": "present (unique-constraint error)", "schemaBasis": "reuses the operation's declared error response schema; no example or error subtype text is invented"} for a in amendments]
    out["decisionsApplied"] = sorted({d["decisionId"] for d in decisions_used})
    return out


def assess() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]], Context]:
    ctx = Context()
    blockers: list[dict[str, Any]] = []
    derived = {m: derive_operation(ctx, m, blockers) for m in ("GET", "POST", "PATCH")}
    for did in ctx.effects:  # every machine-effect decision must be consumed
        if not ctx.consumed[did]:
            blockers.append({"id": "decision-not-applied", "classification": "unresolved-business-blocker", "decisionId": did, "description": "Approved decision had no effect on any operation."})
    prev_resolved = {c["id"]: c for c in ctx.previous["conflictsDisappearedBecauseBackupExcluded"]}
    prev_genuine = {c["id"]: c for c in ctx.previous["genuineRemainingConflicts"]}
    prev_ownership = {c["id"]: c for c in ctx.previous["ownershipOrTechnicalResolutions"]}
    items: list[dict[str, Any]] = []

    def add(id_: str, title: str, classification: str, **kw: Any) -> None:
        items.append({"id": id_, "title": title, "classification": classification, **kw})

    for cid, c in prev_resolved.items():
        add(cid, c["title"], "resolved-by-authority-selection", resolvedBy="authoritative branch 0.2 (EA2) selected; backup branch 0.3 (EA3) retained for traceability only")
    human = {"GET-filter-policy-authority-conflict": "human-reviewed-mailing-info-get-search-filter-policy",
             "DML-column-names-vs-table-definition": "human-reviewed-mailing-info-physical-column-names",
             "POST-emailBody-not-persisted-in-sparx": "human-reviewed-mailing-info-emailbody-mapping",
             "GET-response-emailBody-and-TEMPLATEID": "human-reviewed-mailing-info-emailbody-mapping",
             "409-declared-only-by-sparx": "human-reviewed-mailing-info-http-409-contract-amendment",
             "PATCH-404-trigger-not-specified": "human-reviewed-mailing-info-patch-not-found-404"}
    for cid, did in human.items():
        add(cid, prev_genuine[cid]["title"], "resolved-by-human-reviewed-decision", decisionId=did,
            sparxEvidencePreserved=True, previousStatus=prev_genuine[cid]["status"])
    technical_basis = {
        "external-types-string-vs-integer": "OpenAPI owns external types; numeric/string adapters are implementation",
        "POST-response-data-id": "OpenAPI owns response shape; Sparx OUTPUT ID retained as traceability, not exposed",
        "PATCH-validation-field-body-vs-emailBody": "OpenAPI owns declared validation; INPUT/DML use emailBody",
        "POST-optionality-sparx-vs-openapi": "OpenAPI owns required-field validation",
        "DML-pseudocode-missing-separator": "pseudocode typo normalized deterministically",
        "REQUESTID-NUMBER-8-2-vs-integer": "type adapter chosen from the table definition (NUMBER(8,2))",
        "POST-method-owner-lane-vs-service": "explicit Fuerte relationship to the target service in the authoritative branch",
    }
    for cid, basis in technical_basis.items():
        classification = "resolved-by-authority-selection" if cid == "POST-method-owner-lane-vs-service" else "technical-implementation-choice"
        add(cid, prev_ownership[cid]["title"], classification, basis=basis)
    for cid, title, basis in [
        ("case-sensitivity-of-contains", "Case sensitivity of textual contains matching", "decision 1 leaves it to implementation unless a convention defines it"),
        ("persistence-technology-and-repositories", "JPA/repository implementation, SQL generation mechanics, mapper organization, persistence adapter structure", "archetype-owned technical choices"),
        ("id-allocation-and-database-wiring", "Primary key allocation and database/DataSource wiring (URL/TNSNAMES/JNDI empty in Sparx)", "technical configuration owned by the archetype"),
        ("audit-plumbing", "Population of CREATIONUSER/LASTMODIFIEDUSER from the user header and sysdate", "behavior is literal in Sparx; plumbing is technical"),
        ("pagination-implementation", "Applying LIMIT/OFFSET and ORDER BY ID", "behavior is literal in Sparx; mechanism is technical"),
        ("exception-to-status-mapping", "Mapping unique-constraint/availability/timeout/other exceptions to 409/503/504/500", "statuses are explicit; mapping mechanism is technical"),
        ("response-envelope-population", "code/message values for success and error responses", "taken from the OpenAPI schemas/examples and archetype error conventions; no wording invented"),
        ("numeric-parse-failures", "id/successfulDelivery/requestId that cannot be parsed to the column type", "treated as failed validation (400) per the Sparx validation rule"),
        ("user-header-derived-mapping", "INPUT userId (headerRequest) tied to the x-user-id header", "derived-structural mapping, reported for visibility"),
    ]:
        add(cid, title, "technical-implementation-choice", basis=basis)
    classes: dict[str, int] = {}
    for item in items:
        classes[item["classification"]] = classes.get(item["classification"], 0) + 1
    return {"items": items, "classificationCounts": dict(sorted(classes.items()))}, blockers, derived, ctx


def readiness_for(blockers: list[dict[str, Any]], derived: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_op = {}
    for method in derived:
        own = [b for b in blockers if b.get("operation", "").startswith(method + " ")]
        per_op[method] = {"classification": "implementation-ready" if not own else "blocked", "businessBlockers": [b["id"] for b in own]}
    global_blockers = [b for b in blockers if "operation" not in b]
    strict = not blockers
    return {"operations": per_op, "strictImplementationReady": strict, "implementationReady": strict,
            "functionalCodeGenerationReady": strict and all(v["classification"] == "implementation-ready" for v in per_op.values()),
            "unresolvedBusinessBlockers": blockers, "globalBlockers": global_blockers}


# ---------------------------------------------------------------------------------------------
# consolidation
# ---------------------------------------------------------------------------------------------

def archive_previous() -> dict[str, Any]:
    folder = F / "archive" / "pre-phase-8.5"
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.yml"
    entries = {}
    for name in ("sparx-spec.yml", "service-spec.yml"):
        target = folder / name
        if not target.exists():
            shutil.copy2(F / name, target)
        entries[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    if not manifest_path.exists():
        manifest_path.write_bytes(encode({"version": 1, "reason": "specs replaced by Phase 8.5 consolidation; retained for traceability", "sha256": entries}))
    return {"folder": folder.relative_to(ROOT).as_posix(), "sha256": entries}


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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=["reassess", "consolidate"], required=True)
    parser.add_argument("--archetype", default=(__import__("os").environ.get("SERVICE_ARCHETYPE_PATH") or "archetypes/claro-spring-ms/v1.0.0").rstrip("/") + "/archetype.yml")
    args = parser.parse_args()
    register, blockers, derived, ctx = assess()
    readiness = readiness_for(blockers, derived)
    source_hashes = {k: {"file": v, "sha256": sha256_file(v)} for k, v in PATHS.items()}
    reassessment = {
        "version": 1, "kind": "sparx-decision-reassessment", "phase": "8.5",
        "basis": {"authoritativeBranch": ctx.branch_identity, "sources": source_hashes, "nonAuthoritativeEvidenceUsedForSemantics": False,
                  "staleBackupConflictsCarriedForward": False,
                  "archetype": {"file": args.archetype, "sha256": sha256_file(args.archetype)}},
        "conflictRegister": register, "readiness": readiness,
        "decisionApplication": {did: {"appliedEffects": sorted(set(ctx.consumed[did])), "applicationCountRecorded": 1} for did in ctx.effects},
    }
    (F / "sparx-decision-reassessment.yml").write_bytes(encode(reassessment))
    print({"stage": args.stage, "strict": readiness["strictImplementationReady"], "functional": readiness["functionalCodeGenerationReady"],
           "blockers": [b["id"] for b in blockers], "classes": register["classificationCounts"]})
    if args.stage == "reassess":
        return 0
    if not (readiness["strictImplementationReady"] and readiness["functionalCodeGenerationReady"]):
        print("Gates are not both true; specs were NOT consolidated.")
        return 2
    import consolidate_emit as emit  # noqa: E402  (spec writers)

    archive = archive_previous()
    emit.write_specs(ctx, derived, register, readiness, source_hashes, archive, args.archetype)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
