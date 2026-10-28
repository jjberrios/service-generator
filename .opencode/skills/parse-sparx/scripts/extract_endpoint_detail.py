"""Generic, deterministic extraction of structured technical sections from
explicitly authorized Sparx pages and the local content they embed.

Sparx exports render rich "linked document" bodies (specification tables,
pseudocode) inside an ``<iframe>`` that points at a local ``linkdocs`` file.
The global indexer only warns about such iframes. This module:

* resolves an iframe/object/embed reference found on an authorized page and
  loads it ONLY when it is local to the same export, is an HTML file, and is
  within the bounded embed depth (default 1, nested embeds are recorded, never
  loaded);
* distinguishes ``embeddedContent`` from ``ordinaryOutOfScopeLink``;
* preserves key/value tables, columnar (header/body) tables, free-text sections,
  literal statements, assignments, predicates, notes and numeric code mentions
  as SOURCE TEXT / STRUCTURED EVIDENCE.

Nothing here knows about a service, table, field or HTTP method. It never
invents SQL and never infers behavior; it only restructures literal source text.
"""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import index_sparx as ix  # noqa: E402  (shared page parser / evidence-id scheme)

HTML_SUFFIXES = {".htm", ".html"}
EMBED_TAGS = {"iframe", "object", "embed"}
SECTION_VOCABULARY = {
    "tipo": "type", "nombre": "name", "operacion": "operation",
    "url / tnsnames / jndi": "connection", "origen": "origin", "destino": "destination",
    "transformacion": "transformation", "input": "input", "output": "output",
    "consideraciones": "considerations", "variables properties": "variablesProperties",
    "descripcion": "description", "necesario": "required",
}
STATEMENT_START = ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE")
CLAUSE_KEYWORDS = (
    "SELECT", "INSERT INTO", "UPDATE", "DELETE FROM", "MERGE INTO", "FROM", "WHERE", "SET", "VALUES",
    "ORDER BY", "GROUP BY", "HAVING", "LIMIT", "OFFSET", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "JOIN",
)
CLAUSE_RE = re.compile(r"\b(" + "|".join(k.replace(" ", r"\s+") for k in CLAUSE_KEYWORDS) + r")\b(?!\s*=)")
ASSIGN_RE = re.compile(
    r"(?P<column>[A-Za-z_][A-Za-z0-9_.\[\]]*)\s*(?P<operator>=|<>|!=|<=|>=)\s*"
    r"(?P<value><[^>]+>|'[^']*'|[A-Za-z0-9_.]+(?:\([^)]*\))?)"
)
PLACEHOLDER_RE = re.compile(r"<[^<>\s][^<>]*>")
CODE_RE = re.compile(r"(?<![\w.])([1-5]\d\d)(?![\w.])")


def fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def section_key(label: str) -> str:
    folded = " ".join(fold(label).rstrip(":").split())
    if folded in SECTION_VOCABULARY:
        return SECTION_VOCABULARY[folded]
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "unnamed"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def squash(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


# --------------------------------------------------------------------------------------
# Fragment parsing: tables -> rows -> cells -> lines (with bold prefix / list marker)
# --------------------------------------------------------------------------------------

class FragmentParser(HTMLParser):
    LINE_BREAK_TAGS = {"br", "li", "ul", "ol", "p", "div", "tr", "td", "th", "table", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self.nested_table_count = 0
        self.embedded_references: list[dict[str, str]] = []
        self._ignored = 0
        self._table_depth = 0
        self._rows: list[list[dict[str, Any]]] | None = None
        self._cells: list[dict[str, Any]] | None = None
        self._lines: list[dict[str, Any]] | None = None
        self._segments: list[tuple[str, bool]] = []
        self._bold = 0
        self._list_item = False

    def _flush_line(self) -> None:
        if self._lines is None:
            self._segments = []
            return
        segments, self._segments = self._segments, []
        text = squash("".join(part for part, _ in segments))
        if text:
            prefix: list[str] = []
            for part, is_bold in segments:
                if not part.strip() and not prefix:
                    continue
                if is_bold:
                    prefix.append(part)
                elif part.strip():
                    break
                else:
                    prefix.append(part)
            bold_prefix = squash("".join(prefix)) or None
            self._lines.append({"text": text, "boldPrefix": bold_prefix, "listItem": self._list_item})

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
            return
        if self._ignored:
            return
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if tag in EMBED_TAGS:
            self.embedded_references.append(
                {"tag": tag, "src": attributes.get("src") or attributes.get("data") or "", "id": attributes.get("id", "")}
            )
        if tag == "table":
            self._table_depth += 1
            if self._table_depth > 1:
                self.nested_table_count += 1
                return
            self._rows = []
            return
        if self._table_depth != 1 or self._rows is None:
            return
        if tag == "tr":
            self._cells = []
            return
        if tag in {"td", "th"}:
            self._lines = []
            self._segments = []
            self._bold = 0
            self._list_item = False
            return
        if tag in {"b", "strong"}:
            self._bold += 1
        if tag == "li":
            self._flush_line()
            self._list_item = True
        elif tag in self.LINE_BREAK_TAGS:
            self._flush_line()
            if tag in {"ul", "ol"}:
                self._list_item = False

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in {"br", "col", "img", "hr", "meta", "input", "link"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored = max(0, self._ignored - 1)
            return
        if self._ignored:
            return
        if tag == "table":
            if self._table_depth == 1 and self._rows is not None:
                self.tables.append(self._rows)
                self._rows = None
            self._table_depth = max(0, self._table_depth - 1)
            return
        if self._table_depth != 1 or self._rows is None:
            return
        if tag in {"td", "th"}:
            self._flush_line()
            if self._cells is not None and self._lines is not None:
                lines = self._lines
                self._cells.append({
                    "lines": lines,
                    "text": "\n".join(line["text"] for line in lines),
                    "allBold": bool(lines) and all(line["boldPrefix"] == line["text"] for line in lines),
                })
            self._lines = None
            self._list_item = False
        elif tag == "tr":
            if self._cells is not None:
                self._rows.append(self._cells)
            self._cells = None
        elif tag in {"b", "strong"}:
            self._bold = max(0, self._bold - 1)
        elif tag == "li":
            self._flush_line()
            self._list_item = False
        elif tag in self.LINE_BREAK_TAGS:
            self._flush_line()

    def handle_data(self, data: str) -> None:
        if self._ignored or self._lines is None:
            return
        self._segments.append((data.replace("\r", "").replace("\n", " "), self._bold > 0))


# --------------------------------------------------------------------------------------
# Section classification
# --------------------------------------------------------------------------------------

def header_row(row: list[dict[str, Any]]) -> bool:
    non_empty = [cell for cell in row if cell["text"]]
    return len(row) >= 2 and bool(non_empty) and all(cell["allBold"] for cell in non_empty) and bool(row[0]["text"])


def unique_column_keys(row: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: dict[str, int] = {}
    columns: list[dict[str, str]] = []
    for index, cell in enumerate(row):
        literal = cell["text"]
        key = section_key(literal) if literal else f"column{index + 1}"
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key}{seen[key]}"
        columns.append({"literal": literal, "key": key})
    return columns


def parse_statement(lines: list[str]) -> dict[str, Any]:
    """Restructure literal pseudocode/SQL-like text. No semantics added."""
    flat = squash(" ".join(lines))
    leading = flat.split(" ", 1)[0]
    matches = [
        m for m in CLAUSE_RE.finditer(flat)
        if not flat[:m.start()].rstrip().endswith((",", "("))      # keyword-like name inside a list
        and not flat[m.end():].lstrip().startswith((",", ")"))
    ]
    clauses: list[dict[str, Any]] = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(flat)
        keyword = " ".join(match.group(1).split())
        text = flat[match.end():end].strip()
        clauses.append({"keyword": keyword, "text": text})
    statement: dict[str, Any] = {
        "leadingKeyword": leading,
        "literalLines": lines,
        "normalizedText": flat,
        "clauses": clauses,
        "placeholders": sorted(set(PLACEHOLDER_RE.findall(flat))),
        "derivation": "literal-restructuring-only; no SQL inferred",
    }

    def assignments(text: str) -> list[dict[str, Any]]:
        found = []
        for hit in ASSIGN_RE.finditer(text):
            tail = text[hit.end():].lstrip()
            found.append({
                "column": hit.group("column"), "operator": hit.group("operator"), "value": hit.group("value"),
                "separatorAfter": "," if tail.startswith(",") else None,
            })
        return found

    def split_top(text: str) -> list[str]:
        parts, depth, current = [], 0, ""
        for char in text:
            if char in "(<":
                depth += 1
            elif char in ")>":
                depth = max(0, depth - 1)
            if char == "," and depth == 0:
                parts.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            parts.append(current.strip())
        return parts

    for clause in clauses:
        kw = clause["keyword"]
        if kw == "SET":
            statement["setAssignments"] = assignments(clause["text"])
        elif kw == "WHERE":
            conds = []
            for part in re.split(r"\b(?=AND\b|OR\b)", clause["text"]):
                part = part.strip()
                connector = None
                head = re.match(r"(AND|OR)\b\s*", part)
                if head:
                    connector, part = head.group(1), part[head.end():]
                for hit in assignments(part):
                    conds.append({"connector": connector, **hit})
                    connector = None
            statement["whereText"] = clause["text"]
            statement["predicates"] = conds
        elif kw == "SELECT":
            statement["selectList"] = split_top(clause["text"])
        elif kw in {"INSERT INTO", "DELETE FROM", "UPDATE"} or (kw == "FROM" and "selectList" in statement):
            token = re.match(r"[A-Za-z_][A-Za-z0-9_.]*", clause["text"])
            if token:
                statement["targetToken"] = token.group(0)
            if kw == "INSERT INTO":
                paren = re.search(r"\((.*)\)", clause["text"])
                if paren:
                    statement["columnList"] = split_top(paren.group(1))
        elif kw == "VALUES":
            paren = re.search(r"\((.*)\)", clause["text"])
            if paren:
                statement["valueList"] = split_top(paren.group(1))
        elif kw in {"ORDER BY", "GROUP BY", "HAVING", "LIMIT", "OFFSET"}:
            statement.setdefault("trailingClauses", []).append({"keyword": kw, "text": clause["text"]})
    columns, values = statement.get("columnList"), statement.get("valueList")
    if columns is not None and values is not None:
        statement["positionalPairs"] = (
            [{"column": c, "value": v} for c, v in zip(columns, values)] if len(columns) == len(values) else None
        )
        statement["positionalPairsNote"] = "pairing is positional order of the two literal lists" if len(columns) == len(values) else "list lengths differ; not paired"
    return statement


HEADING_RE = re.compile(r"^(notas?|notes?|c[oó]digos?\s+de\s+respuesta|response\s+codes?)\s*:", re.IGNORECASE)


def heading_label(line: dict[str, Any]) -> str | None:
    """Literal heading text when a line introduces a note/response-code block (bold prefix or 'Label:')."""
    if line["boldPrefix"]:
        return line["boldPrefix"]
    match = HEADING_RE.match(fold(line["text"]) if False else line["text"])
    return line["text"][: match.end()].strip() if match else None


def analyse_text_section(lines: list[dict[str, Any]], evidence) -> dict[str, Any]:
    statements: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    code_block: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    index = 0
    mode = "text"
    current_note: dict[str, Any] | None = None
    consumed: set[int] = set()
    while index < len(lines):
        line = lines[index]
        prefix = heading_label(line)
        words = line["text"].split(" ", 1)
        if prefix:
            consumed.add(index)
            folded = fold(prefix)
            current_note = None
            if folded.startswith("nota"):
                mode = "note"
                body = squash(line["text"][len(prefix):]).lstrip(": ").strip()
                current_note = {"evidenceId": evidence("note"), "label": prefix, "lines": [body] if body else []}
                notes.append(current_note)
            elif folded.startswith("codigos de respuesta") or folded.startswith("response codes"):
                mode = "codes"
                remainder = squash(line["text"][len(prefix):]).lstrip(": ").strip()
                if remainder:
                    code_block.append({"evidenceId": evidence("response-code-line"), "text": remainder,
                                       "listItem": line["listItem"], "codes": [int(x) for x in CODE_RE.findall(remainder)]})
            else:
                mode = "text"
            index += 1
            continue
        if words[0] in STATEMENT_START and not line["listItem"] and not words[0].isdigit():
            collected = [line["text"]]
            consumed.add(index)
            index += 1
            while index < len(lines) and not heading_label(lines[index]) and not lines[index]["boldPrefix"] and not lines[index]["listItem"]:
                collected.append(lines[index]["text"])
                consumed.add(index)
                index += 1
            statement = parse_statement(collected)
            statement["evidenceId"] = evidence("statement")
            statements.append(statement)
            mode = "text"
            continue
        if mode == "note" and current_note is not None:
            consumed.add(index)
            current_note["lines"].append(line["text"])
        elif mode == "codes":
            consumed.add(index)
            code_block.append({"evidenceId": evidence("response-code-line"), "text": line["text"], "listItem": line["listItem"],
                               "codes": [int(x) for x in CODE_RE.findall(line["text"])]})
        index += 1
    for position, line in enumerate(lines):
        for code in CODE_RE.findall(line["text"]):
            mentions.append({"code": int(code), "line": line["text"], "lineIndex": position})
    return {
        "lines": [{"index": n, **line} for n, line in enumerate(lines)],
        "statements": statements,
        "notes": notes,
        "responseCodeBlock": code_block,
        "codeMentions": mentions,
        "listItems": [line["text"] for line in lines if line["listItem"]],
        "proseLineIndexes": [n for n in range(len(lines)) if n not in consumed],
    }


def extract_sections(tables: list[list[list[dict[str, Any]]]], evidence_key: str) -> tuple[list[dict[str, Any]], list[str]]:
    counters: dict[str, int] = {}

    def make_evidence(kind: str) -> str:
        counters[kind] = counters.get(kind, -1) + 1
        return ix.evidence_id(evidence_key, kind, counters[kind])

    sections: list[dict[str, Any]] = []
    warnings: list[str] = []
    pending: dict[str, Any] | None = None
    for table_index, rows in enumerate(tables):
        rows = [row for row in rows if row]
        if not rows:
            continue
        # headerless body for a preceding header-only table with the same column count
        if pending is not None and not header_row(rows[0]) and all(len(row) == len(pending["columns"]) for row in rows):
            for row in rows:
                if not any(cell["text"] for cell in row):
                    pending["emptyRowCount"] += 1
                    continue
                pending["rows"].append(make_row(pending["columns"], row, make_evidence))
            pending = None
            continue
        pending = None
        if all(len(row) == 2 for row in rows) and all(row[0]["allBold"] for row in rows):
            entries = [{
                "evidenceId": make_evidence("embedded-field"),
                "label": row[0]["text"], "key": section_key(row[0]["text"]),
                "value": row[1]["text"], "valueLines": [line["text"] for line in row[1]["lines"]],
            } for row in rows]
            sections.append({"evidenceId": make_evidence("embedded-section"), "kind": "keyValue", "tableIndex": table_index, "entries": entries})
            continue
        if header_row(rows[0]):
            columns = unique_column_keys(rows[0])
            section = {
                "evidenceId": make_evidence("embedded-section"), "kind": "columnar", "tableIndex": table_index,
                "label": columns[0]["literal"], "key": section_key(columns[0]["literal"]),
                "columns": columns, "rows": [], "emptyRowCount": 0,
            }
            for row in rows[1:]:
                if len(row) != len(columns):
                    warnings.append(f"table {table_index}: row width {len(row)} differs from header width {len(columns)}")
                if not any(cell["text"] for cell in row):
                    section["emptyRowCount"] += 1
                    continue
                section["rows"].append(make_row(columns, row, make_evidence))
            sections.append(section)
            if len(rows) == 1:
                pending = section
            continue
        if all(len(row) == 1 for row in rows):
            first = rows[0][0]
            label = first["text"] if first["allBold"] else None
            body_rows = rows[1:] if label else rows
            lines = [line for row in body_rows for line in row[0]["lines"]]
            section = {
                "evidenceId": make_evidence("embedded-section"), "kind": "text", "tableIndex": table_index,
                "label": label, "key": section_key(label) if label else None,
            }
            section.update(analyse_text_section(lines, make_evidence))
            section["empty"] = not lines
            sections.append(section)
            continue
        warnings.append(f"table {table_index}: unclassified shape ({len(rows)} rows); preserved as raw rows")
        sections.append({
            "evidenceId": make_evidence("embedded-section"), "kind": "raw", "tableIndex": table_index,
            "rows": [[cell["text"] for cell in row] for row in rows],
        })
    return sections, warnings


def make_row(columns: list[dict[str, str]], row: list[dict[str, Any]], make_evidence) -> dict[str, Any]:
    values = {}
    for index, column in enumerate(columns):
        if index < len(row):
            values[column["key"]] = row[index]["text"]
    extra = [cell["text"] for cell in row[len(columns):]]
    result: dict[str, Any] = {"evidenceId": make_evidence("embedded-row"), "values": values}
    if extra:
        result["extraCells"] = extra
    return result


# --------------------------------------------------------------------------------------
# Embedded resolution (bounded, local, same export)
# --------------------------------------------------------------------------------------

def resolve_embedded(src: str, outer_relative: str, source_root: Path) -> tuple[str | None, str]:
    raw = src.strip()
    if not raw:
        return None, "missing-src"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) or raw.startswith(("//", "/", "\\")):
        return None, "external-or-absolute-reference"
    path_part = raw.split("#", 1)[0].split("?", 1)[0]
    if "%" in path_part or "\\" in path_part:
        return None, "encoded-or-backslash-path-not-followed"
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(outer_relative), path_part))
    if joined.startswith("../") or joined == "..":
        return None, "escapes-source-root"
    if PurePosixPath(joined).suffix.lower() not in HTML_SUFFIXES:
        return None, "not-html"
    target = (source_root / PurePosixPath(joined)).resolve()
    try:
        target.relative_to(source_root.resolve())
    except ValueError:
        return None, "escapes-source-root"
    if not target.is_file():
        return None, "missing-local-file"
    return joined, "resolved"


def decode(raw: bytes) -> str:
    for encoding in ("utf-8", "windows-1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def properties_by_name(parser: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in ix.extract_properties(parser.tables):
        key = ix.clean_text(str(item["name"]))
        result.setdefault(key, str(item["value"]))
    return result


def process_page(
    page_path: str, repository_root: Path, source_root: Path, scopes: dict[str, list[str]], max_depth: int,
) -> dict[str, Any]:
    absolute = (repository_root / page_path).resolve()
    relative = absolute.relative_to(source_root.resolve()).as_posix()
    raw = absolute.read_bytes()
    issues = ix.IssueCollector()
    parser = ix.parse_html_page(absolute, relative, issues)
    props = properties_by_name(parser)
    metadata = ix.object_metadata(parser, ix.extract_properties(parser.tables))
    page_key = ix.evidence_page_key(relative)
    entry: dict[str, Any] = {
        "page": page_path,
        "sha256": sha256_bytes(raw),
        "pageEvidenceKey": page_key,
        "activity": {
            "name": metadata.get("elementName"),
            "objectTitle": metadata.get("objectTitle"),
            "elementType": metadata.get("elementType"),
            "stereotype": metadata.get("stereotype"),
            "uuid": props.get("UUID"),
            "status": props.get("Status"),
            "modified": props.get("Modified"),
        },
        "operationScope": scopes.get(page_path, []),
        "outerRelationships": outer_relationships(parser, relative),
        "ordinaryOutOfScopeLinkCount": len(parser.links),
        "ordinaryOutOfScopeLinksFollowed": 0,
        "embeddedContent": [],
        "unresolvedEmbeddedReferences": [],
        "sections": [],
        "warnings": [],
    }
    for position, reference in enumerate(parser.embedded_references):
        target, status = resolve_embedded(reference["src"], relative, source_root) if max_depth >= 1 else (None, "depth-bound-exceeded")
        reference_evidence = ix.evidence_id(page_key, "embedded-reference", position)
        if target is None:
            entry["unresolvedEmbeddedReferences"].append({
                "evidenceId": reference_evidence, "tag": reference["tag"], "src": reference["src"], "classification": "ordinaryOutOfScopeLink", "reason": status,
            })
            continue
        embedded_path = (source_root / PurePosixPath(target)).resolve()
        data = embedded_path.read_bytes()
        key = ix.evidence_page_key(target)
        fragment = FragmentParser()
        fragment.feed(decode(data))
        fragment.close()
        sections, warnings = extract_sections(fragment.tables, key)
        entry["embeddedContent"].append({
            "evidenceId": reference_evidence,
            "classification": "embeddedContent",
            "tag": reference["tag"],
            "src": reference["src"],
            "resolvedFile": (source_root / PurePosixPath(target)).resolve().relative_to(repository_root.resolve()).as_posix(),
            "sha256": sha256_bytes(data),
            "byteSize": len(data),
            "depth": 1,
            "ownEvidenceKey": key,
            "nestedEmbeddedReferencesNotLoaded": [{"tag": r["tag"], "src": r["src"]} for r in fragment.embedded_references],
            "nestedTableCount": fragment.nested_table_count,
            "sections": sections,
            "warnings": warnings,
        })
    return entry


RELATIONSHIP_HEADER = {"object", "objeto"}
DATA_STEREOTYPES = {"table", "entity", "datastore", "dataobject", "tabla", "entidad"}


def outer_relationships(parser: Any, relative: str) -> list[dict[str, Any]]:
    """Rows of the element's relationship table (Object/Type/Connection/Direction/Notes), with local targets."""
    link_targets = {}
    for link in parser.links:
        text = ix.clean_text(str(link.get("text") or ""))
        href = str(link.get("href") or "")
        if text and href and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", href):
            link_targets.setdefault(text, ix.normalize_local_target(relative, href.split("#", 1)[0]))
    found: list[dict[str, Any]] = []
    for table in parser.tables:
        if not table.rows:
            continue
        header = [fold(ix.clean_text(str(c.get("text", "")))) for c in table.rows[0]]
        if len(header) >= 4 and header[0] in RELATIONSHIP_HEADER:
            for row in table.rows[1:]:
                cells = [ix.clean_text(str(c.get("text", ""))) for c in row]
                if len(cells) >= 4 and cells[0]:
                    found.append({"object": cells[0], "type": cells[1], "connection": cells[2], "direction": cells[3],
                                  "notes": cells[4] if len(cells) > 4 else "", "targetPage": link_targets.get(cells[0])})
    return found


def extract_data_definition(page_path: str, repository_root: Path, source_root: Path) -> dict[str, Any]:
    """Columns/types/descriptions, PK/FK/index declarations and association rows of a data-structure element page."""
    absolute = (repository_root / page_path).resolve()
    relative = absolute.relative_to(source_root.resolve()).as_posix()
    raw = absolute.read_bytes()
    issues = ix.IssueCollector()
    parser = ix.parse_html_page(absolute, relative, issues)
    key = ix.evidence_page_key(relative)
    props = properties_by_name(parser)
    meta = ix.object_metadata(parser, ix.extract_properties(parser.tables))
    counters: dict[str, int] = {}
    title_text = ""
    if parser.tables and parser.tables[0].rows:
        title_text = ix.clean_text(str(parser.tables[0].rows[0][-1].get("text", "")))
    title_match = re.match(r"^(?P<name>.+?)\s*:\s*(?P<visibility>\w+)\s*(?:<<(?P<stereo>[^>]+)>>|\u00ab(?P<stereo2>[^\u00bb]+)\u00bb)?\s*(?P<type>\S+)", title_text)

    def evidence(kind: str) -> str:
        counters[kind] = counters.get(kind, -1) + 1
        return ix.evidence_id(key, kind, counters[kind])

    columns: list[dict[str, Any]] = []
    declarations: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []
    for table in parser.tables:
        rows = [[ix.clean_text(str(c.get("text", ""))) for c in row] for row in table.rows]
        if not rows:
            continue
        head = fold(rows[0][0]) if rows[0] else ""
        if head in {"attribute", "atributo"} and len(rows[0]) >= 3:
            for row in rows[1:]:
                if len(row) >= 3 and row[0]:
                    columns.append({"evidenceId": evidence("column"), "column": row[0], "scope": row[1], "dataType": row[2], "description": None})
                elif len(row) == 1 and columns and fold(row[0]).startswith(("notas", "notes")):
                    columns[-1]["description"] = re.sub(r"^\S+:\s*", "", row[0]).replace("<br/>", "").strip() or None
        elif head in {"operation", "operacion"}:
            for row in rows[1:]:
                match = re.match(r"^(?:Public|Private|Protected)?\s*([A-Za-z0-9_]+)\s*\((.*?)\)\s*:?", row[0]) if row else None
                if match:
                    name = match.group(1)
                    kind = ("primaryKey" if fold(name).startswith("pk") else "foreignKey" if fold(name).startswith("fk")
                            else "index" if fold(name).startswith(("ix", "idx")) else "other")
                    declarations.append({"evidenceId": evidence("declaration"), "name": name, "kind": kind, "parameters": match.group(2).strip().rstrip(","), "literal": row[0]})
        elif head in {"element", "elemento"} and len(rows[0]) >= 3:
            for row in rows[1:]:
                if len(row) >= 3:
                    associations.append({"evidenceId": evidence("association"), "element": row[0], "sourceRole": row[1], "targetRole": row[2]})
    return {
        "page": page_path, "sha256": sha256_bytes(raw), "pageEvidenceKey": key,
        "identity": {"name": title_match.group("name") if title_match else meta.get("elementName"), "objectTitle": (title_match.group(0) if title_match else None) or meta.get("objectTitle"),
                     "stereotype": (title_match.group("stereo") or title_match.group("stereo2")) if title_match else meta.get("stereotype"),
                     "elementType": (title_match.group("type") or None) if title_match else meta.get("elementType"), "uuid": props.get("UUID"), "created": props.get("Created"),
                     "modified": props.get("Modified"), "status": props.get("Status")},
        "columns": columns, "keyAndIndexDeclarations": declarations, "associationRows": associations,
        "relationships": outer_relationships(parser, relative),
    }


def load_scopes(plan: Path | None, repository_root: Path) -> dict[str, list[str]]:
    if plan is None:
        return {}
    import yaml

    data = yaml.safe_load(plan.read_bytes())
    return {row["page"]: list(row.get("operationScopes", [])) for row in data.get("recommendedPages", [])}


def build_summary(pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pageCount": len(pages),
        "pagesWithEmbeddedContent": sum(1 for p in pages if p["embeddedContent"]),
        "embeddedFilesLoaded": sum(len(p["embeddedContent"]) for p in pages),
        "unresolvedEmbeddedReferences": sum(len(p["unresolvedEmbeddedReferences"]) for p in pages),
        "ordinaryLinksFollowed": sum(p["ordinaryOutOfScopeLinksFollowed"] for p in pages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source_root", type=Path, help="Sparx export root (e.g. input/sparx)")
    parser.add_argument("output", type=Path, help="YAML output under .factory/")
    parser.add_argument("--page", action="append", required=True, help="Authorized page path (repeatable)")
    parser.add_argument("--scope-plan", type=Path, help="Optional YAML with recommendedPages[].operationScopes")
    parser.add_argument("--max-embed-depth", type=int, default=1)
    args = parser.parse_args()
    import yaml

    repository_root = Path.cwd().resolve()
    source_root = (repository_root / args.source_root).resolve()
    scopes = load_scopes(args.scope_plan, repository_root)
    pages = [process_page(page, repository_root, source_root, scopes, args.max_embed_depth) for page in args.page]
    document = {
        "version": 1,
        "kind": "sparx-endpoint-detail-index",
        "source": {
            "sourceRoot": args.source_root.as_posix(),
            "authorizedPages": list(args.page),
            "embeddedContentPolicy": {"maxDepth": args.max_embed_depth, "sameExportOnly": True, "htmlOnly": True, "ordinaryLinksFollowed": False},
        },
        "pages": pages,
        "summary": build_summary(pages),
    }

    class Dumper(yaml.SafeDumper):
        def ignore_aliases(self, data: Any) -> bool:
            return True

    args.output.write_bytes(yaml.dump(document, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=140).encode("utf-8"))
    print(document["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
