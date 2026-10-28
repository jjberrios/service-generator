#!/usr/bin/env python3
"""Build a deterministic, non-semantic index of a Sparx HTML export."""

from __future__ import annotations

import argparse
import codecs
import difflib
import hashlib
import mmap
import os
import posixpath
import re
import sys
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


HTML_SUFFIXES = {".htm", ".html"}
IGNORED_TAGS = {"script", "style"}
BLOCK_TAGS = {"p", "li", "section", "article", "pre", "blockquote", "dt", "dd"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
UNSUPPORTED_ACTIVE_TAGS = {"iframe", "object", "embed"}
EXTERNAL_SCHEMES = {"http", "https", "mailto", "ftp", "tel"}
EXECUTABLE_SCHEMES = {"javascript", "vbscript", "data"}


class IndexingFailure(Exception):
    """Raised when indexing cannot safely continue."""


class MetaCharsetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.charset: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.charset is not None or tag.casefold() != "meta":
            return
        attributes = {name.casefold(): value or "" for name, value in attrs}
        if attributes.get("charset"):
            self.charset = attributes["charset"]
            return
        if attributes.get("http-equiv", "").casefold() == "content-type":
            match = re.search(
                r"charset\s*=\s*([A-Za-z0-9._-]+)",
                attributes.get("content", ""),
                flags=re.IGNORECASE,
            )
            if match:
                self.charset = match.group(1)


class IssueCollector:
    def __init__(self, source_prefix: str = "") -> None:
        self.source_prefix = source_prefix.rstrip("/")
        self.warnings: list[dict[str, str]] = []
        self.errors: list[dict[str, str]] = []
        self._seen: set[tuple[str, str, str, str, str]] = set()

    def add(
        self,
        severity: str,
        code: str,
        source: str,
        message: str,
        target: str | None = None,
    ) -> None:
        if self.source_prefix and source not in {"", ".", self.source_prefix} and not source.startswith(
            f"{self.source_prefix}/"
        ):
            source = f"{self.source_prefix}/{source}"
        elif source == ".":
            source = self.source_prefix
        key = (severity, code, source, message, target or "")
        if key in self._seen:
            return
        self._seen.add(key)
        issue = {"code": code, "source": source, "message": message}
        if target is not None:
            issue["target"] = target
        (self.errors if severity == "error" else self.warnings).append(issue)

    def warning(self, code: str, source: str, message: str, target: str | None = None) -> None:
        self.add("warning", code, source, message, target)

    def error(self, code: str, source: str, message: str, target: str | None = None) -> None:
        self.add("error", code, source, message, target)

    @staticmethod
    def _sort(issues: list[dict[str, str]]) -> list[dict[str, str]]:
        return sorted(
            issues,
            key=lambda item: (
                item.get("source", ""),
                item.get("code", ""),
                item.get("target", ""),
                item.get("message", ""),
            ),
        )

    def sorted_warnings(self) -> list[dict[str, str]]:
        return self._sort(self.warnings)

    def sorted_errors(self) -> list[dict[str, str]]:
        return self._sort(self.errors)


@dataclass
class ElementFrame:
    tag: str
    attrs: dict[str, str]

    @property
    def classes(self) -> list[str]:
        return sorted(part for part in self.attrs.get("class", "").split() if part)


@dataclass
class TextCapture:
    tag: str
    classes: list[str]
    parts: list[str] = field(default_factory=list)
    html_id: str | None = None
    structural_context: list[dict[str, Any]] = field(default_factory=list)
    preceding_heading: str | None = None


@dataclass
class ListItemCapture:
    context_classes: list[str]
    parts: list[str] = field(default_factory=list)
    image_type: str | None = None
    links: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TableCapture:
    index: int
    class_name: str | None
    html_id: str | None
    context: dict[str, Any] | None
    structural_context: list[dict[str, Any]] = field(default_factory=list)
    preceding_heading: str | None = None
    visual_attributes: dict[str, str] = field(default_factory=dict)
    rows: list[list[dict[str, Any]]] = field(default_factory=list)
    row_visuals: list[dict[str, Any]] = field(default_factory=list)
    current_row: list[dict[str, Any]] | None = None
    current_row_visual: dict[str, Any] = field(default_factory=dict)
    current_cell: dict[str, Any] | None = None
    caption_parts: list[str] = field(default_factory=list)
    in_caption: bool = False
    strong_texts: list[str] = field(default_factory=list)


@dataclass
class VisualCapture:
    tag: str
    attributes: dict[str, Any]
    table_index: int | None
    row_index: int | None
    cell_index: int | None
    capture_text: bool = False
    parts: list[str] = field(default_factory=list)


VISUAL_ATTRIBUTE_NAMES = {
    "class", "style", "bgcolor", "fill", "fillcolor", "fill-color",
    "background", "background-color", "stroke", "color", "status", "state",
    "lifecycle", "data-status", "data-state", "data-lifecycle", "data-legend",
    "aria-label", "aria-describedby", "role", "data-sparx-background-color",
    "sparx-background-color", "data-ea-background-color",
}
LEGEND_TOKENS = {"legend", "legends", "leyenda", "leyendas"}
VISUAL_CLASS_TOKENS = {
    "diagram", "legend", "legends", "leyenda", "leyendas", "swatch", "shape",
    "activity", "process", "lifecycle", "status", "state", "element",
}
LIFECYCLE_PROPERTY_NAMES = {
    "status", "state", "lifecycle", "lifecycle state", "element status", "element state",
}


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = clean_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def structural_tokens(value: str) -> set[str]:
    camel_separated = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    return {
        token for token in re.split(r"[\W_]+", camel_separated.casefold()) if token
    }


def evidence_page_key(relative_file: str) -> str:
    digest = hashlib.sha256(relative_file.encode("utf-8")).hexdigest()
    return f"page-sha256-{digest}"


def evidence_id(page_key: str, evidence_type: str, index: int) -> str:
    return f"{page_key}:{evidence_type}:{index}"


def normalized_visual_style(attributes: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    style = str(attributes.get("style") or "")
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        name, value = declaration.split(":", 1)
        key = name.strip().casefold()
        if key in {"background", "background-color", "fill", "fill-color", "fillcolor", "color"}:
            value = value.strip().casefold()
            if value:
                result[key] = value
    for name in ("bgcolor", "background", "background-color", "fill", "fillcolor", "fill-color", "color"):
        value = str(attributes.get(name) or "").strip().casefold()
        if value:
            result[name] = value
    return dict(sorted(result.items()))


def legend_label_for_row(cells: list[dict[str, Any]], row_style: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]], dict[str, str]]:
    style_sources: list[dict[str, Any]] = []
    visual_style = normalized_visual_style(row_style)
    if visual_style:
        style_sources.append(row_style)
    for cell in cells:
        cell_style = normalized_visual_style(cell)
        if cell_style:
            style_sources.append(cell)
            visual_style.update(cell_style)
    labels = [clean_text(str(cell.get("text", ""))) for cell in cells if clean_text(str(cell.get("text", "")))]
    label = " | ".join(labels) if labels else None
    return label, style_sources, dict(sorted(visual_style.items()))


def visual_has_fill(style: dict[str, str]) -> bool:
    return any(key in style for key in ("background", "background-color", "bgcolor", "fill", "fillcolor", "fill-color"))


def lifecycle_visual_style(attributes: dict[str, Any]) -> dict[str, str]:
    style = normalized_visual_style(attributes)
    result: dict[str, str] = {}
    for key in ("background-color", "background", "bgcolor", "fill-color", "fillcolor", "fill"):
        if style.get(key):
            result["fillColor"] = style[key]
            break
    direct = attributes.get("visualAttributes") or attributes
    for key in ("data-sparx-background-color", "sparx-background-color", "data-ea-background-color"):
        value = str(direct.get(key) or "").strip()
        if value:
            result["sparxBackgroundColor"] = value
            break
    return dict(sorted(result.items()))


def explicit_status_value(attributes: dict[str, Any]) -> str | None:
    values = [
        attributes.get(key)
        for key in ("status", "state", "lifecycle", "data-status", "data-state", "data-lifecycle")
        if attributes.get(key)
    ]
    unique = unique_strings([str(value) for value in values])
    return unique[0] if len(unique) == 1 else None


class SparxPageParser(HTMLParser):
    """Collect source-observable structure without executing active content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.frames: list[ElementFrame] = []
        self.ignored_depth = 0
        self.title_parts: list[str] | None = None
        self.title: str | None = None
        self.heading_capture: tuple[int, list[str]] | None = None
        self.headings: list[dict[str, Any]] = []
        self.link_capture: dict[str, Any] | None = None
        self.links: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.image_maps: list[dict[str, Any]] = []
        self.image_map_stack: list[dict[str, Any]] = []
        self.image_map_areas: list[dict[str, Any]] = []
        self.blocks: list[TextCapture] = []
        self.block_stack: list[TextCapture] = []
        self.list_items: list[dict[str, Any]] = []
        self.list_item_stack: list[ListItemCapture] = []
        self.tables: list[TableCapture] = []
        self.table_stack: list[TableCapture] = []
        self.strong_stack: list[tuple[TableCapture | None, list[str]]] = []
        self.visual_metadata: list[dict[str, Any]] = []
        self.visual_capture_stack: list[VisualCapture] = []
        self.legend_definitions: list[dict[str, Any]] = []
        self.breadcrumb_parts: list[str] = []
        self.breadcrumb_links: list[dict[str, Any]] = []
        self.anchors: set[str] = set()
        self.malformed_events: list[str] = []
        self.unsupported_tags: set[str] = set()
        self.embedded_references: list[dict[str, str]] = []
        self.last_heading_text: str | None = None

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(name).lower(): value or "" for name, value in attrs}

    def _inside_breadcrumb(self) -> bool:
        return any("breadcrumb" in class_name.casefold() for frame in self.frames for class_name in frame.classes)

    def _context_classes(self) -> list[str]:
        return unique_strings([class_name for frame in self.frames for class_name in frame.classes])

    def _nearest_context(self) -> dict[str, Any] | None:
        for frame in reversed(self.frames):
            if frame.attrs.get("id") or frame.classes:
                return {
                    "tag": frame.tag,
                    "id": frame.attrs.get("id") or None,
                    "classes": frame.classes,
                }
        return None

    def _context_chain(self) -> list[dict[str, Any]]:
        return [
            {
                "tag": frame.tag,
                "id": frame.attrs.get("id") or None,
                "classes": frame.classes,
                "legendReference": frame.attrs.get("data-legend") or None,
                "role": frame.attrs.get("role") or None,
            }
            for frame in self.frames
            if frame.attrs.get("id") or frame.classes
        ]

    def _begin_visual_capture(self, tag: str, attributes: dict[str, str]) -> None:
        visual_attributes = {
            key: value for key, value in attributes.items()
            if key in VISUAL_ATTRIBUTE_NAMES or key.startswith("data-status") or key.startswith("data-state")
            or key.startswith("data-lifecycle")
        }
        has_nonclass_visual_attribute = any(key != "class" for key in visual_attributes)
        class_visual_marker = bool(structural_tokens(attributes.get("class", "")) & VISUAL_CLASS_TOKENS)
        if not has_nonclass_visual_attribute and not class_visual_marker:
            return
        table = self.table_stack[-1] if self.table_stack else None
        row_index = len(table.rows) if table and table.current_row is not None else None
        cell_index = (len(table.current_row) if table and table.current_row is not None
                      and (tag in {"td", "th"} or table.current_cell is not None) else None)
        capture = VisualCapture(
            tag=tag,
            attributes={
                "id": attributes.get("id") or None,
                "class": sorted(attributes.get("class", "").split()),
                "style": attributes.get("style") or None,
                "visualAttributes": visual_attributes,
                "context": self._nearest_context(),
                "hrefContext": next((frame.attrs.get("href") for frame in reversed(self.frames)
                                      if frame.tag == "a" and frame.attrs.get("href")), None),
                "tableIndex": table.index if table else None,
                "rowIndex": row_index,
                "cellIndex": cell_index,
            },
            table_index=table.index if table else None,
            row_index=row_index,
            cell_index=cell_index,
            capture_text=any(key in visual_attributes for key in (
                "status", "state", "lifecycle", "data-status", "data-state", "data-lifecycle",
                "aria-label", "data-legend",
            )),
        )
        self.visual_metadata.append({"tag": tag, **capture.attributes, "text": ""})
        capture_index = len(self.visual_metadata) - 1
        capture.attributes["_captureIndex"] = capture_index
        self.visual_capture_stack.append(capture)

    def _finish_visual_captures(self, tag: str | None = None) -> None:
        if not self.visual_capture_stack:
            return
        matching_index = 0 if tag is None else len(self.visual_capture_stack) - 1
        if tag is not None:
            matching_index = next(
                (i for i in range(len(self.visual_capture_stack) - 1, -1, -1)
                 if self.visual_capture_stack[i].tag == tag),
                -1,
            )
            if matching_index < 0:
                return
        while len(self.visual_capture_stack) > matching_index:
            capture = self.visual_capture_stack.pop()
            index = int(capture.attributes.pop("_captureIndex"))
            self.visual_metadata[index]["text"] = clean_text("".join(capture.parts))

    def _current_map(self) -> str | None:
        for frame in reversed(self.frames):
            if frame.tag == "map":
                return frame.attrs.get("name") or frame.attrs.get("id") or None
        return None

    def _append_spacing(self) -> None:
        if self.title_parts is not None:
            self.title_parts.append(" ")
        if self.heading_capture is not None:
            self.heading_capture[1].append(" ")
        if self.link_capture is not None:
            self.link_capture["parts"].append(" ")
        for capture in self.block_stack:
            capture.parts.append(" ")
        for capture in self.list_item_stack:
            capture.parts.append(" ")
        for table in self.table_stack:
            if table.current_cell is not None:
                table.current_cell["parts"].append(" ")
        for _, parts in self.strong_stack:
            parts.append(" ")

    @staticmethod
    def _finish_cell(table: TableCapture) -> None:
        if table.current_cell is None:
            return
        if table.current_row is None:
            table.current_row = []
        cell = table.current_cell
        cell["text"] = clean_text("".join(cell.pop("parts")))
        table.current_row.append(cell)
        table.current_cell = None

    @classmethod
    def _finish_row(cls, table: TableCapture) -> None:
        cls._finish_cell(table)
        if table.current_row is not None:
            table.rows.append(table.current_row)
            table.row_visuals.append(table.current_row_visual)
            table.current_row = None
            table.current_row_visual = {}

    def _finish_link(self) -> None:
        if self.link_capture is None:
            return
        link = dict(self.link_capture)
        link["text"] = clean_text("".join(link.pop("parts")))
        self.links.append(link)
        if link["inBreadcrumb"]:
            self.breadcrumb_links.append(link)
        if self.list_item_stack:
            self.list_item_stack[-1].links.append(link)
        self.link_capture = None

    def _finish_title(self) -> None:
        if self.title_parts is None:
            return
        self.title = clean_text("".join(self.title_parts)) or None
        self.title_parts = None

    def _finish_heading(self, closing_tag: str | None = None) -> None:
        if self.heading_capture is None:
            return
        level, parts = self.heading_capture
        if closing_tag is not None and closing_tag != f"h{level}":
            self.malformed_events.append(
                f"Heading h{level} was closed by {closing_tag}; partial text was retained."
            )
        text = clean_text("".join(parts))
        if text:
            self.headings.append({"level": level, "text": text})
        self.heading_capture = None

    def _finish_strong(self) -> None:
        if not self.strong_stack:
            return
        table, parts = self.strong_stack.pop()
        text = clean_text("".join(parts))
        if table is not None and text:
            table.strong_texts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = self._attrs(attrs)
        if tag in IGNORED_TAGS:
            self.ignored_depth += 1
            self.frames.append(ElementFrame(tag, attributes))
            return
        if self.ignored_depth:
            self.frames.append(ElementFrame(tag, attributes))
            return

        if attributes.get("id"):
            self.anchors.add(attributes["id"])
        if tag == "a" and attributes.get("name"):
            self.anchors.add(attributes["name"])
        if tag in UNSUPPORTED_ACTIVE_TAGS:
            self.unsupported_tags.add(tag)
            reference = attributes.get("src") or attributes.get("data") or ""
            self.embedded_references.append({"tag": tag, "src": reference, "id": attributes.get("id", "")})
        classes = sorted(part for part in attributes.get("class", "").split() if part)

        if tag == "title":
            if self.title_parts is not None:
                self._finish_title()
                self.malformed_events.append(
                    "A title was implicitly closed by a nested title; partial text was retained."
                )
            self.title_parts = []
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit() and 1 <= int(tag[1]) <= 6:
            if self.heading_capture is not None:
                previous_level = self.heading_capture[0]
                self._finish_heading()
                self.malformed_events.append(
                    f"Heading h{previous_level} was implicitly closed by {tag}; partial text was retained."
                )
            self.heading_capture = (int(tag[1]), [])
        if tag == "a":
            if self.link_capture is not None:
                self._finish_link()
                self.malformed_events.append(
                    "An anchor was implicitly closed by a nested anchor; both links were retained."
                )
            self.link_capture = {
                "tag": "a",
                "href": attributes.get("href", ""),
                "parts": [],
                "title": attributes.get("title") or None,
                "inBreadcrumb": self._inside_breadcrumb(),
                "mapName": self._current_map(),
            }
        if tag == "area":
            area_index = len(self.image_map_areas)
            area = {
                "index": area_index,
                "mapName": self._current_map(),
                "shape": attributes.get("shape") or None,
                "coords": attributes.get("coords") or None,
                "href": attributes.get("href", ""),
                "title": attributes.get("title") or None,
                "alt": attributes.get("alt") or None,
                "attributes": {key: value for key, value in sorted(attributes.items())},
            }
            self.image_map_areas.append(area)
            if self.image_map_stack:
                self.image_map_stack[-1]["areaIndexes"].append(area_index)
            self.links.append(
                {
                    "tag": "area",
                    "href": attributes.get("href", ""),
                    "text": clean_text(attributes.get("alt") or attributes.get("title") or ""),
                    "title": attributes.get("title") or None,
                    "alt": attributes.get("alt") or None,
                    "shape": attributes.get("shape") or None,
                    "coords": attributes.get("coords") or None,
                    "areaIndex": area_index,
                    "inBreadcrumb": self._inside_breadcrumb(),
                    "mapName": self._current_map(),
                }
            )
        if tag == "map":
            image_map = {
                "index": len(self.image_maps),
                "id": attributes.get("id") or None,
                "name": attributes.get("name") or None,
                "attributes": {key: value for key, value in sorted(attributes.items())},
                "areaIndexes": [],
            }
            self.image_maps.append(image_map)
            self.image_map_stack.append(image_map)
        if tag == "img":
            image = {
                "src": attributes.get("src", ""),
                "alt": attributes.get("alt") or None,
                "title": attributes.get("title") or None,
                "class": attributes.get("class") or None,
                "usemap": attributes.get("usemap") or None,
                "contextClasses": unique_strings([*self._context_classes(), *classes]),
            }
            self.images.append(image)
            if self.list_item_stack and image["alt"]:
                self.list_item_stack[-1].image_type = image["alt"]
        if tag == "table":
            table = TableCapture(
                index=len(self.tables),
                class_name=attributes.get("class") or None,
                html_id=attributes.get("id") or None,
                context=self._nearest_context(),
                structural_context=self._context_chain() + [{
                    "tag": tag,
                    "id": attributes.get("id") or None,
                    "classes": classes,
                }],
                preceding_heading=self.last_heading_text,
                visual_attributes={
                    key: value for key, value in attributes.items()
                    if key in VISUAL_ATTRIBUTE_NAMES or key.startswith("data-legend")
                },
            )
            self.tables.append(table)
            self.table_stack.append(table)
        elif tag == "tr" and self.table_stack:
            table = self.table_stack[-1]
            self._finish_row(table)
            table.current_row = []
            table.current_row_visual = {
                key: attributes.get(key)
                for key in ("class", "id", "style", "bgcolor", "fill", "status", "state", "data-status", "data-state", "data-lifecycle")
                if attributes.get(key)
            }
        elif tag in {"td", "th"} and self.table_stack:
            table = self.table_stack[-1]
            self._finish_cell(table)
            if table.current_row is None:
                table.current_row = []
                self.malformed_events.append(
                    f"Table {table.index} contains a {tag} outside an explicit tr; an implicit row was retained."
                )
            table.current_cell = {
                "tag": tag,
                "class": attributes.get("class") or None,
                "id": attributes.get("id") or None,
                "style": attributes.get("style") or None,
                "bgcolor": attributes.get("bgcolor") or None,
                "fill": attributes.get("fill") or None,
                "status": attributes.get("status") or attributes.get("data-status") or None,
                "state": attributes.get("state") or attributes.get("data-state") or None,
                "parts": [],
            }
        elif tag == "caption" and self.table_stack:
            self.table_stack[-1].in_caption = True
        if tag == "strong":
            self.strong_stack.append((self.table_stack[-1] if self.table_stack else None, []))

        if tag in BLOCK_TAGS or (tag == "div" and any(
            marker in class_name.casefold()
            for class_name in classes
            for marker in ("objectdetailsnotes", "objecttitle")
        )):
            capture = TextCapture(
                tag=tag,
                classes=classes,
                html_id=attributes.get("id") or None,
                structural_context=self._context_chain() + [{
                    "tag": tag,
                    "id": attributes.get("id") or None,
                    "classes": classes,
                }],
                preceding_heading=self.last_heading_text,
            )
            self.blocks.append(capture)
            self.block_stack.append(capture)
        if tag == "li":
            self.list_item_stack.append(
                ListItemCapture(
                    context_classes=unique_strings([*self._context_classes(), *classes])
                )
            )
        self._begin_visual_capture(tag, attributes)
        if tag in VOID_TAGS:
            self._finish_visual_captures(tag)
        if tag == "br":
            self._append_spacing()

        if tag not in VOID_TAGS:
            self.frames.append(ElementFrame(tag, attributes))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in {"area", "img", "br", "meta", "link", "input", "hr"}:
            self.handle_endtag(tag)
        elif self.frames and self.frames[-1].tag == tag.lower():
            self.frames.pop()

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        if self.title_parts is not None:
            self.title_parts.append(data)
        if self.heading_capture is not None:
            self.heading_capture[1].append(data)
        if self.link_capture is not None:
            self.link_capture["parts"].append(data)
        if self._inside_breadcrumb():
            self.breadcrumb_parts.append(data)
        for capture in self.block_stack:
            capture.parts.append(data)
        for capture in self.list_item_stack:
            capture.parts.append(data)
        for table in self.table_stack:
            if table.current_cell is not None:
                table.current_cell["parts"].append(data)
            if table.in_caption:
                table.caption_parts.append(data)
        for strong_capture in self.strong_stack:
            strong_capture[1].append(data)
        for capture in self.visual_capture_stack:
            if capture.capture_text:
                capture.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in IGNORED_TAGS:
            if self.ignored_depth:
                self.ignored_depth -= 1
            self._pop_frame(tag)
            return
        if self.ignored_depth:
            self._pop_frame(tag)
            return

        if tag == "title" and self.title_parts is not None:
            self._finish_title()
        if len(tag) == 2 and tag[0] == "h" and self.heading_capture is not None:
            self._finish_heading(tag)
            if self.headings:
                self.last_heading_text = self.headings[-1]["text"]
        if tag == "a" and self.link_capture is not None:
            self._finish_link()
        if tag == "strong" and self.strong_stack:
            self._finish_strong()
        if tag in {"td", "th"} and self.table_stack:
            self._finish_cell(self.table_stack[-1])
        elif tag == "tr" and self.table_stack:
            self._finish_row(self.table_stack[-1])
        elif tag == "caption" and self.table_stack:
            self.table_stack[-1].in_caption = False
        elif tag == "table" and self.table_stack:
            table = self.table_stack[-1]
            self._finish_row(table)
            self.table_stack.pop()
        if tag == "map" and self.image_map_stack:
            self.image_map_stack.pop()

        self._finish_visual_captures(tag)

        for index in range(len(self.block_stack) - 1, -1, -1):
            if self.block_stack[index].tag == tag:
                self.block_stack.pop(index)
                break
        if tag == "li" and self.list_item_stack:
            item = self.list_item_stack.pop()
            self.list_items.append(
                {
                    "text": clean_text("".join(item.parts)),
                    "type": item.image_type,
                    "links": item.links,
                    "contextClasses": item.context_classes,
                }
            )
        self._pop_frame(tag)

    def _pop_frame(self, tag: str) -> None:
        for index in range(len(self.frames) - 1, -1, -1):
            if self.frames[index].tag == tag:
                del self.frames[index:]
                return


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministically index a Sparx Enterprise Architect HTML export."
    )
    parser.add_argument("input", type=Path, help="Sparx HTML export directory under input/sparx/")
    parser.add_argument("output", type=Path, help="YAML index file under .factory/")
    parser.add_argument(
        "--target-audit",
        type=Path,
        help="Index only the exact page set in an approved parser-gap audit artifact under .factory/.",
    )
    return parser.parse_args()


def load_yaml_module() -> Any:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise IndexingFailure(
            "PyYAML is required to emit the Sparx index. Install it in the managed "
            "environment before running this script; packages are never installed dynamically."
        ) from exc
    return yaml


def find_repository_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (
            (candidate / "AGENTS.md").is_file()
            and (candidate / "input" / "sparx").is_dir()
            and (candidate / ".opencode").is_dir()
        ):
            return candidate
    raise IndexingFailure("Cannot locate the repository root containing AGENTS.md and input/sparx/.")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def discover_source_files(source_root: Path, issues: IssueCollector) -> list[tuple[str, Path]]:
    discovered: list[tuple[str, Path]] = []
    try:
        candidates = sorted(source_root.rglob("*"), key=lambda path: path.relative_to(source_root).as_posix())
    except (OSError, RuntimeError) as exc:
        raise IndexingFailure(f"Cannot enumerate Sparx export '{source_root}': {exc}") from exc
    for candidate in candidates:
        relative = candidate.relative_to(source_root).as_posix()
        try:
            is_symlink = candidate.is_symlink()
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            detail = exc.strerror if isinstance(exc, OSError) else None
            issues.error("source_path_unresolvable", relative, f"Cannot resolve source path: {detail or type(exc).__name__}")
            continue
        if not is_within(resolved, source_root):
            issues.error(
                "source_path_outside_root",
                relative,
                "Source entry resolves outside the approved Sparx export and was not read.",
                relative,
            )
            continue
        if is_symlink and not resolved.exists():
            issues.warning("source_symlink_unresolved", relative, "Broken source symlink was not followed.")
            continue
        if is_symlink and resolved.is_dir():
            issues.warning("source_directory_symlink_skipped", relative, "Directory symlink was not traversed.")
            continue
        try:
            is_file = resolved.is_file()
        except OSError as exc:
            issues.error("source_file_unreadable", relative, f"Cannot inspect source entry: {exc.strerror or type(exc).__name__}")
            continue
        if is_file:
            discovered.append((relative, resolved))
    return discovered


def fingerprint_export(files: list[tuple[str, Path]], issues: IssueCollector) -> str:
    export_digest = hashlib.sha256()
    for relative, path in files:
        encoded_path = relative.encode("utf-8")
        export_digest.update(len(encoded_path).to_bytes(8, "big"))
        export_digest.update(encoded_path)
        try:
            file_digest = hashlib.sha256(path.read_bytes()).digest()
        except OSError as exc:
            issues.error(
                "source_file_unreadable",
                relative,
                f"Cannot fingerprint source file: {exc.strerror or type(exc).__name__}",
            )
            file_digest = hashlib.sha256(b"UNREADABLE").digest()
        export_digest.update(file_digest)
    return export_digest.hexdigest()


def decode_html(raw: bytes, source: str, issues: IssueCollector) -> str:
    bom_encodings = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    )
    for bom, encoding in bom_encodings:
        if raw.startswith(bom):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError as exc:
                issues.error("html_decode_failed", source, f"Cannot decode declared BOM encoding: {exc.reason}")
                return raw.decode(encoding, errors="replace")

    header = raw[:4096].decode("ascii", errors="ignore")
    charset_parser = MetaCharsetParser()
    charset_parser.feed(header)
    if charset_parser.charset:
        declared_encoding = charset_parser.charset
        try:
            return raw.decode(declared_encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            issues.warning(
                "html_declared_encoding_failed",
                source,
                f"Declared charset '{declared_encoding}' could not decode the page: {type(exc).__name__}.",
            )

    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    try:
        decoded = raw.decode("cp1252")
    except UnicodeDecodeError as exc:
        issues.error("html_decode_failed", source, f"Cannot decode HTML: {exc}")
        return raw.decode("utf-8", errors="replace")
    issues.warning("html_decode_fallback", source, "HTML was decoded with cp1252 after UTF-8 decoding failed.")
    return decoded


def finalize_partial_html(parser: SparxPageParser, source: str, issues: IssueCollector) -> None:
    partial: list[str] = []
    if parser.title_parts is not None:
        parser._finish_title()
        partial.append("title")
    if parser.heading_capture is not None:
        level = parser.heading_capture[0]
        parser._finish_heading()
        partial.append(f"h{level}")
    if parser.link_capture is not None:
        parser._finish_link()
        partial.append("a")
    while parser.strong_stack:
        parser._finish_strong()
        partial.append("strong")
    for table in parser.table_stack:
        if table.current_cell is not None:
            parser._finish_cell(table)
            partial.append("table-cell")
        if table.current_row is not None:
            parser._finish_row(table)
            partial.append("table-row")
    while parser.list_item_stack:
        item = parser.list_item_stack.pop()
        parser.list_items.append(
            {
                "text": clean_text("".join(item.parts)),
                "type": item.image_type,
                "links": item.links,
                "contextClasses": item.context_classes,
            }
        )
        partial.append("li")
    if parser.visual_capture_stack:
        parser._finish_visual_captures()
        partial.append("visual-element")
    if partial:
        issues.warning(
            "html_partial_structures",
            source,
            f"Unclosed HTML structures were finalized defensively: {', '.join(sorted(set(partial)))}.",
        )
    for message in parser.malformed_events:
        issues.warning("html_mismatched_structure", source, message)
    for tag in sorted(parser.unsupported_tags):
        issues.warning(
            "html_active_structure_ignored",
            source,
            f"Unsupported active HTML element '{tag}' was retained only through surrounding text/metadata and was not loaded.",
        )


def parse_html_page(path: Path, source: str, issues: IssueCollector) -> SparxPageParser:
    parser = SparxPageParser()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        issues.error("html_read_failed", source, f"Cannot read HTML page: {exc.strerror or type(exc).__name__}")
        return parser
    try:
        parser.feed(decode_html(raw, source, issues))
        parser.close()
    except Exception as exc:  # HTMLParser extensions can raise on malformed edge cases.
        issues.error("html_parse_failed", source, f"HTML parsing failed; partial evidence was retained: {exc}")
    if parser.ignored_depth:
        issues.warning(
            "html_unclosed_ignored_content",
            source,
            "An unclosed script/style block was ignored through the end of the document.",
        )
    finalize_partial_html(parser, source, issues)
    return parser


def normalize_local_target(current_file: str, raw_path: str) -> str:
    decoded = unquote(raw_path).replace("\\", "/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(current_file), decoded))


def append_query_and_fragment(path: str, query: str, fragment: str) -> str:
    value = path
    if query:
        value += f"?{query}"
    if fragment:
        value += f"#{fragment}"
    return value


def normalize_link(
    raw: dict[str, Any],
    current_file: str,
    source_root: Path,
    repository_root: Path,
    html_exact: set[str],
    html_folded: dict[str, list[str]],
    issues: IssueCollector,
    out_of_scope_html: set[str] | None = None,
) -> dict[str, Any]:
    original_href = str(raw.get("href", ""))
    href = original_href.strip()
    text = clean_text(str(raw.get("text", "")))
    result: dict[str, Any] = {
        "text": text,
        "href": original_href,
        "normalizedHref": href,
        "kind": None,
        "target": None,
        "fragment": None,
        "fragmentResolved": None,
        "resolved": False,
        "sourceTag": raw.get("tag"),
    }
    if raw.get("mapName"):
        result["mapName"] = raw["mapName"]
    if not href:
        result["kind"] = "unresolved"
        issues.warning("empty_link", current_file, "Link has no href.")
        return result

    if re.match(r"^[A-Za-z]:[\\/]", href) or href.startswith("\\\\"):
        result["kind"] = "unsafe-local"
        result["target"] = href
        issues.error("absolute_local_link_blocked", current_file, "Absolute local path was not followed.", href)
        return result
    try:
        parsed = urlsplit(href)
    except ValueError as exc:
        result["kind"] = "unresolved"
        result["target"] = href
        issues.warning("malformed_link", current_file, f"Malformed link was preserved: {exc}.", href)
        return result
    scheme = parsed.scheme.casefold()
    result["normalizedHref"] = parsed.geturl()
    result["fragment"] = parsed.fragment or None
    if any(char in href for char in "<>\r\n\t"):
        result["kind"] = "unresolved"
        result["target"] = href
        issues.warning("malformed_link", current_file, "Malformed markup-like reference was preserved without resolution.", href)
        return result
    if href.startswith("//") or scheme in EXTERNAL_SCHEMES or (scheme and scheme not in EXECUTABLE_SCHEMES | {"file"}):
        result["kind"] = "external"
        result["target"] = href
        return result
    if scheme == "file":
        result["kind"] = "blocked-file"
        result["target"] = href
        issues.warning("file_link_blocked", current_file, "file: link was preserved but not followed.", href)
        return result
    if scheme in EXECUTABLE_SCHEMES:
        result["kind"] = "blocked-script"
        result["target"] = href
        issues.warning("executable_link_blocked", current_file, "Executable link was preserved but not evaluated.", href)
        return result
    if not parsed.path:
        result["kind"] = "fragment" if parsed.fragment else "page-reference"
        result["target"] = (source_root / PurePosixPath(current_file)).relative_to(repository_root).as_posix()
        result["resolved"] = True
        return result

    relative_target = normalize_local_target(current_file, parsed.path)
    result["normalizedHref"] = append_query_and_fragment(
        relative_target, parsed.query, parsed.fragment
    )
    if relative_target == ".." or relative_target.startswith("../") or PurePosixPath(relative_target).is_absolute():
        result["kind"] = "unsafe-local"
        result["target"] = relative_target
        issues.error("local_link_outside_root", current_file, "Local link escapes the approved Sparx export and was not followed.", href)
        return result
    try:
        candidate = (source_root / PurePosixPath(relative_target)).resolve()
    except (OSError, RuntimeError) as exc:
        result["kind"] = "unsafe-local"
        result["target"] = relative_target
        issues.error(
            "local_link_unresolvable",
            current_file,
            f"Local link could not be resolved safely: {type(exc).__name__}.",
            href,
        )
        return result
    if not is_within(candidate, source_root):
        result["kind"] = "unsafe-local"
        result["target"] = relative_target
        issues.error("local_link_outside_root", current_file, "Resolved local link escapes the approved Sparx export.", href)
        return result

    suffix = PurePosixPath(relative_target).suffix.casefold()
    if suffix in HTML_SUFFIXES:
        result["kind"] = "internal-page"
        if out_of_scope_html and relative_target in out_of_scope_html and relative_target not in html_exact:
            result["target"] = (source_root / PurePosixPath(relative_target)).relative_to(repository_root).as_posix()
            result["outOfScope"] = True
            return result
        if relative_target in html_exact:
            actual_relative = relative_target
        else:
            folded_matches = html_folded.get(relative_target.casefold(), [])
            actual_relative = folded_matches[0] if len(folded_matches) == 1 else None
        if actual_relative is not None:
            result["target"] = (source_root / PurePosixPath(actual_relative)).relative_to(repository_root).as_posix()
            result["resolved"] = True
            if parsed.fragment:
                result["fragmentResolved"] = None
        elif len(html_folded.get(relative_target.casefold(), [])) > 1:
            result["target"] = (source_root / PurePosixPath(relative_target)).relative_to(repository_root).as_posix()
            issues.warning(
                "internal_link_case_ambiguous",
                current_file,
                "Internal target matches multiple pages by case and was not resolved.",
                href,
            )
        else:
            result["target"] = (source_root / PurePosixPath(relative_target)).relative_to(repository_root).as_posix()
            issues.warning("internal_link_unresolved", current_file, "Internal Sparx page target was not found.", href)
        return result

    result["kind"] = "local-asset"
    result["target"] = candidate.relative_to(repository_root).as_posix()
    result["resolved"] = candidate.is_file()
    if not result["resolved"]:
        issues.warning("local_asset_unresolved", current_file, "Local asset target was not found.", href)
    return result


def table_to_output(
    table: TableCapture,
    page_key: str,
    visual_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [[cell.get("text", "") for cell in row] for row in table.rows]
    has_header = bool(table.rows) and any(
        cell.get("tag") == "th" or "tableheading" in str(cell.get("class", "")).casefold()
        for cell in table.rows[0]
    )
    headers = rows[0] if has_header else []
    data_rows = rows[1:] if has_header else rows
    cell_visuals: list[dict[str, Any]] = []
    row_visuals: list[dict[str, Any]] = []
    for row_index, row in enumerate(table.rows):
        row_visual = table.row_visuals[row_index] if row_index < len(table.row_visuals) else {}
        if row_visual:
            row_visuals.append({
                "sourceRowIndex": row_index,
                "evidenceId": evidence_id(page_key, "visual", next(
                    int(item["index"]) for item in visual_metadata
                    if item.get("tableIndex") == table.index and item.get("rowIndex") == row_index
                    and item.get("cellIndex") is None
                )),
                "attributes": row_visual,
            })
        for cell_index, cell in enumerate(row):
            matching = [item for item in visual_metadata if item.get("tableIndex") == table.index
                        and item.get("rowIndex") == row_index and item.get("cellIndex") == cell_index]
            for visual in matching:
                cell_visuals.append({
                    "sourceRowIndex": row_index,
                    "sourceCellIndex": cell_index,
                    "evidenceId": visual["evidenceId"],
                    "tag": visual["tag"],
                    "class": visual.get("class", []),
                    "style": visual.get("style"),
                    "visualAttributes": visual.get("visualAttributes", {}),
                    "text": visual.get("text"),
                })
    return {
        "index": table.index,
        "id": table.html_id,
        "class": table.class_name,
        "context": table.context,
        "caption": clean_text("".join(table.caption_parts)) or None,
        "headers": headers,
        "rows": data_rows,
        "structuralContext": table.structural_context,
        "precedingHeading": table.preceding_heading,
        "rowVisuals": row_visuals,
        "cellVisuals": cell_visuals,
    }


def lifecycle_attributes(raw_visual: dict[str, Any]) -> dict[str, Any]:
    values = dict(raw_visual.get("visualAttributes") or {})
    values.update({key: raw_visual.get(key) for key in ("class", "style") if raw_visual.get(key)})
    return values


def extract_legend_lifecycle(
    parser: SparxPageParser,
    page_key: str,
    properties: list[dict[str, Any]],
    visual_metadata: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    legends: list[dict[str, Any]] = []
    lifecycle_states: list[dict[str, Any]] = []
    mapping_sources: list[dict[str, Any]] = []
    next_mapping_index = 0
    next_label_index = 0
    element_type_tokens = structural_tokens(str(metadata.get("elementType") or ""))
    stereotype_tokens = structural_tokens(str(metadata.get("stereotype") or ""))
    title_tokens = structural_tokens(str(metadata.get("objectTitle") or ""))
    explicit_legend_type_tables = [
        table for table in parser.tables
        if table.class_name and table.class_name.casefold() == "contentmaintable"
        and re.search(
            r"\b(?:public|private|protected|package)\s+(?:legend|leyenda)\b",
            " ".join(str(cell.get("text", "")) for row in table.rows for cell in row),
            flags=re.IGNORECASE,
        )
    ]
    explicit_legend_element = bool(
        (element_type_tokens | stereotype_tokens | title_tokens) & LEGEND_TOKENS
    ) or bool(explicit_legend_type_tables)
    referenced_legend_ids = {
        reference.strip().lstrip("#")
        for visual in visual_metadata
        for key, value in (visual.get("visualAttributes") or {}).items()
        if key in {"data-legend", "aria-describedby"}
        for reference in str(value or "").split()
        if reference.strip()
    }

    for table in parser.tables:
        structural_texts = [
            table.html_id or "",
            table.class_name or "",
            table.preceding_heading or "",
            *[str(value) for context in table.structural_context
              for value in (context.get("id"), *(context.get("classes") or []), context.get("legendReference"), context.get("role"))
              if value],
            *[str(value) for value in table.visual_attributes.values()],
        ]
        tokens = set().union(*(structural_tokens(text) for text in structural_texts)) if structural_texts else set()
        context_ids = {str(context.get("id")) for context in table.structural_context if context.get("id")}
        has_explicit_legend_marker = bool(tokens & LEGEND_TOKENS) or bool(
            (table.html_id and table.html_id in referenced_legend_ids) or context_ids & referenced_legend_ids
        ) or any(
            "legend" in str(value or "").casefold() or "leyenda" in str(value or "").casefold()
            for value in table.visual_attributes.values()
        )
        if not has_explicit_legend_marker:
            continue

        legend_id = evidence_id(page_key, "legend", table.index)
        mapping_records: list[dict[str, Any]] = []
        legend_entries: list[dict[str, Any]] = []
        for row_index, row in enumerate(table.rows):
            row_visual = table.row_visuals[row_index] if row_index < len(table.row_visuals) else {}
            style_values: list[tuple[dict[str, str], list[str]]] = []
            row_style = lifecycle_visual_style(row_visual)
            if row_style:
                row_visual_ids = [
                    evidence_id(page_key, "visual", int(item["index"])) for item in visual_metadata
                    if item.get("tableIndex") == table.index and item.get("rowIndex") == row_index
                    and item.get("cellIndex") is None
                ]
                style_values.append((row_style, row_visual_ids))
            for cell_index, cell in enumerate(row):
                style = lifecycle_visual_style(cell)
                matching_visuals = [item for item in visual_metadata
                                    if item.get("tableIndex") == table.index
                                    and item.get("rowIndex") == row_index
                                    and item.get("cellIndex") == cell_index]
                for item in matching_visuals:
                    style.update(lifecycle_visual_style(lifecycle_attributes(item)))
                if style:
                    visual_ids = [evidence_id(page_key, "visual", int(item["index"])) for item in matching_visuals]
                    style_values.append((dict(sorted(style.items())), visual_ids))
            label, _, _ = legend_label_for_row(row, row_visual)
            if not label:
                continue
            label_evidence_id = evidence_id(page_key, "legend-label", next_label_index)
            next_label_index += 1
            legend_entries.append({
                "evidenceId": label_evidence_id,
                "label": label,
                "sourceTable": table.index,
                "sourceRowIndex": row_index,
            })
            if not style_values:
                continue
            seen_row_styles: set[tuple[tuple[str, str], ...]] = set()
            for style_index, (style, visual_ids) in enumerate(style_values):
                style_key = tuple(sorted(style.items()))
                if style_key in seen_row_styles:
                    continue
                seen_row_styles.add(style_key)
                mapping_record = {
                    "evidenceId": evidence_id(page_key, "legend-mapping", next_mapping_index),
                    "legendEvidenceId": legend_id,
                    "labelEvidenceId": label_evidence_id,
                    "label": label,
                    "visualStyle": style,
                    "visualEvidenceIds": visual_ids,
                    "sourceTable": table.index,
                    "sourceRowIndex": row_index,
                }
                mapping_records.append(mapping_record)
                mapping_sources.append(mapping_record)
                next_mapping_index += 1
        if legend_entries or mapping_records:
            legends.append({
                "evidenceId": legend_id,
                "sourceTable": table.index,
                "structuralEvidence": {
                    "id": table.html_id,
                    "class": table.class_name,
                    "precedingHeading": table.preceding_heading,
                    "context": table.structural_context,
                },
                "entries": legend_entries,
                "mappings": mapping_records,
            })

    if explicit_legend_element:
        legend_index = len(parser.tables)
        legend_id = evidence_id(page_key, "legend", legend_index)
        legend_entries = []
        mapping_records = []
        legend_source_rows: list[tuple[str, str, int, int, str]] = []
        for prop in properties:
            if any(table.index == prop.get("sourceTable") for table in parser.tables):
                continue
            raw_value = str(prop.get("value") or "")
            match = re.search(
                r"#?Back_Ground_Color#?\s*=\s*([^;]+)", raw_value, flags=re.IGNORECASE
            )
            if not match:
                continue
            legend_source_rows.append((prop["name"], match.group(1).strip(),
                                       int(prop.get("sourceTable", -1)), -1, prop["evidenceId"]))
        # EA public Legend elements expose legend entries as rows in their
        # tagged-value/custom-properties tables, not necessarily as CSS-styled
        # HTML cells. The structural Public Legend declaration gates this parse;
        # require a tagged/property table so aggregated content-maintenance text
        # is not mistaken for a legend row.
        for table in parser.tables:
            first_row = table.rows[0] if table.rows else []
            has_explicit_header = any(
                cell.get("tag") == "th" or "tableheading" in str(cell.get("class") or "").casefold()
                for cell in first_row
            )
            header_tokens = set(structural_tokens(" ".join(
                clean_text(str(cell.get("text") or "")) for cell in first_row
            ))) if has_explicit_header else set()
            table_tokens = set(structural_tokens(" ".join(
                [table.html_id or "", table.class_name or ""]
                + [str(value) for ctx in table.structural_context for value in (ctx.get("id"), *(ctx.get("classes") or [])) if value]
            )))
            is_tagged_property_table = (
                bool(header_tokens & {"property", "tag"})
                or "tagged" in table_tokens
                or ("custom" in table_tokens and "properties" in table_tokens)
                or (table.class_name or "").casefold() == "objectdetails"
            )
            if not is_tagged_property_table:
                continue
            for row_index, row in enumerate(table.rows):
                if len(row) < 2:
                    continue
                label = clean_text(str(row[0].get("text") or "")).rstrip(":").strip()
                raw_value = clean_text(str(row[1].get("text") or ""))
                match = re.search(
                    r"#?Back_Ground_Color#?\s*=\s*([^;]+)", raw_value, flags=re.IGNORECASE
                )
                if match:
                    legend_source_rows.append((label, match.group(1).strip(), table.index, row_index,
                                               evidence_id(page_key, "table", table.index)))
        seen_legend_mappings: set[tuple[str, str, int, int]] = set()
        legend_definition_source_ids = [
            evidence_id(page_key, "table", table.index) for table in explicit_legend_type_tables
        ]
        for label, style_value, source_table, source_row, style_evidence_id in legend_source_rows:
            if not label:
                continue
            dedup_key = (label, style_value, source_table, source_row)
            if dedup_key in seen_legend_mappings:
                continue
            seen_legend_mappings.add(dedup_key)
            label_id = evidence_id(page_key, "legend-label", next_label_index)
            next_label_index += 1
            mapping_index = next_mapping_index
            next_mapping_index += 1
            mapping = {
                "evidenceId": evidence_id(page_key, "legend-mapping", mapping_index),
                "legendEvidenceId": legend_id,
                "labelEvidenceId": label_id,
                "label": label,
                "visualStyle": {"sparxBackgroundColor": style_value},
                "visualEvidenceIds": [style_evidence_id],
                "styleEvidenceId": style_evidence_id,
                "sourceTable": source_table,
                "sourceRowIndex": source_row if source_row >= 0 else None,
            }
            mapping_records.append(mapping)
            mapping_sources.append(mapping)
            legend_entries.append({
                "evidenceId": label_id,
                "label": label,
                "styleEvidenceId": style_evidence_id,
                "sourceTable": source_table,
                "sourceRowIndex": source_row if source_row >= 0 else None,
            })
            legend_definition_source_ids.append(style_evidence_id)
        legends.append({
            "evidenceId": legend_id,
            "sourceTable": None,
            "structuralEvidence": {
                "elementType": metadata.get("elementType"),
                "elementTypeEvidenceId": metadata.get("elementTypeEvidenceId"),
                "explicitElementTypeDeclaration": "Sparx visibility/type declaration labels this element as a legend"
                    if explicit_legend_type_tables else None,
                "stereotype": metadata.get("stereotype"),
                "stereotypeEvidenceId": metadata.get("stereotypeEvidenceId"),
                "objectTitle": metadata.get("objectTitle"),
                "evidenceIds": [eid for eid in (
                    metadata.get("elementTypeEvidenceId"), metadata.get("stereotypeEvidenceId"),
                    *legend_definition_source_ids,
                ) if eid],
            },
            "entries": legend_entries,
            "mappings": mapping_records,
        })

    next_lifecycle_index = 0
    for visual in visual_metadata:
        attributes = lifecycle_attributes(visual)
        state = explicit_status_value(attributes)
        visual_id = evidence_id(page_key, "visual", int(visual["index"]))
        if state is not None:
            lifecycle_states.append({
                "evidenceId": evidence_id(page_key, "lifecycle", next_lifecycle_index),
                "value": state,
                "basis": "explicit-status-attribute",
                "elementEvidenceId": visual_id,
                "elementHref": visual.get("hrefContext"),
                "evidenceIds": [visual_id],
                "sourceAttributes": {key: value for key, value in attributes.items()
                                      if key in {"status", "state", "lifecycle", "data-status", "data-state", "data-lifecycle"}},
            })
            next_lifecycle_index += 1
            continue
        if visual.get("tableIndex") is not None and any(
            legend.get("sourceTable") == visual.get("tableIndex") for legend in legends
        ):
            continue
        style = lifecycle_visual_style(attributes)
        if not style:
            continue
        matches = [mapping for mapping in mapping_sources
                   if mapping["visualStyle"] and all(
                       style.get(key) == value for key, value in mapping["visualStyle"].items()
                   )]
        if matches:
            labels = unique_strings([mapping["label"] for mapping in matches])
            evidence_ids = unique_strings([
                eid for mapping in matches
                for eid in (visual_id, mapping["legendEvidenceId"], mapping["evidenceId"],
                            mapping["labelEvidenceId"], *mapping["visualEvidenceIds"])
            ])
            state_record = {
                "evidenceId": evidence_id(page_key, "lifecycle", next_lifecycle_index),
                "value": labels[0] if len(labels) == 1 else None,
                "candidateValues": labels if len(labels) > 1 else [],
                "ambiguous": len(labels) > 1,
                "basis": "explicit-legend-style-match",
                "elementEvidenceId": visual_id,
                "elementHref": visual.get("hrefContext"),
                "visualEvidenceId": visual_id,
                "legendEvidenceIds": unique_strings([mapping["legendEvidenceId"] for mapping in matches]),
                "legendMappingEvidenceIds": unique_strings([mapping["evidenceId"] for mapping in matches]),
                "legendLabelEvidenceIds": unique_strings([mapping["labelEvidenceId"] for mapping in matches]),
                "evidenceIds": evidence_ids,
                "visualStyle": style,
            }
            if len(matches) == 1:
                state_record.update({
                    "legendEvidenceId": matches[0]["legendEvidenceId"],
                    "legendMappingEvidenceId": matches[0]["evidenceId"],
                    "legendLabelEvidenceId": matches[0]["labelEvidenceId"],
                })
            lifecycle_states.append(state_record)
            next_lifecycle_index += 1

    for prop in properties:
        name_key = clean_text(str(prop.get("name") or "")).casefold().replace("_", " ")
        if name_key not in LIFECYCLE_PROPERTY_NAMES or not prop.get("value"):
            continue
        lifecycle_states.append({
            "evidenceId": evidence_id(page_key, "lifecycle", next_lifecycle_index),
            "value": str(prop["value"]),
            "basis": "explicit-tagged-property",
            "elementEvidenceId": prop["evidenceId"],
            "evidenceIds": [prop["evidenceId"]],
            "sourceProperty": prop["name"],
        })
        next_lifecycle_index += 1
    return legends, lifecycle_states


def extract_properties(tables: list[TableCapture]) -> list[dict[str, Any]]:
    properties: list[dict[str, Any]] = []
    for table in tables:
        table_is_details = "objectdetails" in (table.class_name or "").casefold()
        for row in table.rows:
            if len(row) < 2:
                continue
            first = row[0]
            name = clean_text(str(first.get("text", ""))).rstrip(":").strip()
            value = clean_text(" | ".join(str(cell.get("text", "")) for cell in row[1:]))
            first_class = str(first.get("class", "")).casefold()
            if name and ("objectdetailstopic" in first_class or table_is_details):
                properties.append({"name": name, "value": value, "sourceTable": table.index})
    return properties


def property_value(properties: list[dict[str, Any]], names: set[str]) -> str | None:
    for item in properties:
        key = clean_text(str(item["name"])).casefold().replace("_", " ")
        if key in names and item.get("value"):
            return str(item["value"])
    return None


def object_metadata(parser: SparxPageParser, properties: list[dict[str, Any]]) -> dict[str, Any]:
    object_titles = [
        clean_text("".join(block.parts))
        for block in parser.blocks
        if any("objecttitle" in name.casefold() for name in block.classes)
    ]
    object_title = next((value for value in object_titles if value), None)
    inferred_name: str | None = None
    inferred_type: str | None = None
    if object_title:
        if " : " in object_title:
            inferred_name, inferred_type = [part.strip() or None for part in object_title.rsplit(" : ", 1)]
        else:
            inferred_name = object_title
    heading_name = next((item["text"] for item in parser.headings if item["level"] == 1), None)
    element_type = property_value(properties, {"type", "element type"}) or inferred_type
    element_type_evidence = next(
        (item["evidenceId"] for item in properties
         if clean_text(str(item.get("name") or "")).casefold().replace("_", " ") in {"type", "element type"}
         and item.get("value")),
        None,
    )
    stereotype_evidence = next(
        (item["evidenceId"] for item in properties
         if clean_text(str(item.get("name") or "")).casefold() == "stereotype" and item.get("value")),
        None,
    )
    return {
        "objectTitle": object_title,
        "elementName": property_value(properties, {"name", "element name"}) or inferred_name or heading_name,
        "elementType": element_type,
        "elementTypeEvidenceId": element_type_evidence,
        "stereotype": property_value(properties, {"stereotype"}),
        "stereotypeEvidenceId": stereotype_evidence,
        "packageName": property_value(properties, {"package", "package name", "parent package"}),
        "id": property_value(properties, {"id", "guid", "ea guid", "element id"}),
    }


def extract_structured_names(
    parser: SparxPageParser,
    metadata: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    operations: list[dict[str, Any]] = []
    operation_markers = {
        "operation", "operations", "method", "methods",
        "operación", "operaciones", "operacion", "método", "métodos", "metodo", "metodos",
    }
    for table in parser.tables:
        context_id = str((table.context or {}).get("id") or "")
        context_classes = list((table.context or {}).get("classes") or [])
        caption = clean_text("".join(table.caption_parts))
        has_header = bool(table.rows) and any(
            cell.get("tag") == "th"
            or "tableheading" in str(cell.get("class", "")).casefold()
            for cell in table.rows[0]
        )
        first_row_labels = [
            clean_text(str(cell.get("text", ""))).rstrip(":") for cell in table.rows[0]
        ] if has_header else []
        structural_values = [context_id, *context_classes, table.class_name or "", caption]
        tokens: set[str] = set()
        for value in structural_values:
            tokens.update(structural_tokens(value))
        explicitly_operations = bool(tokens & operation_markers) or any(
            label.casefold() in operation_markers for label in first_row_labels
        )
        if explicitly_operations:
            structural_label = " | ".join(value for value in structural_values if value)
            names = [
                clean_text(value)
                for value in table.strong_texts
                if clean_text(value).rstrip(":").casefold()
                not in operation_markers | {"name", "type", "notes"}
            ]
            if not names:
                start_row = 1 if has_header else 0
                names = [
                    clean_text(str(row[0].get("text", "")))
                    for row in table.rows[start_row:]
                    if row and clean_text(str(row[0].get("text", "")))
                    and clean_text(str(row[0].get("text", ""))).rstrip(":").casefold()
                    not in operation_markers
                ]
            for name in unique_strings(names):
                operations.append(
                    {
                        "name": name,
                        "sourceTable": table.index,
                        "structuralLabel": clean_text(structural_label) or None,
                    }
                )

    activities: list[dict[str, Any]] = []
    processes: list[dict[str, Any]] = []
    for item in parser.list_items:
        item_type = clean_text(str(item.get("type") or ""))
        type_key = item_type.casefold()
        if type_key not in {"activity", "actividad", "process", "proceso", "business process"}:
            continue
        first_link = item.get("links", [None])[0] if item.get("links") else None
        evidence = {
            "name": clean_text(str((first_link or {}).get("text") or item.get("text") or "")),
            "type": item_type,
            "href": (first_link or {}).get("href"),
            "source": "typed-list-item",
        }
        (activities if type_key in {"activity", "actividad"} else processes).append(evidence)
    element_type = clean_text(str(metadata.get("elementType") or "")).casefold()
    if metadata.get("elementName") and element_type in {
        "activity", "actividad", "process", "proceso", "business process"
    }:
        evidence = {
            "name": metadata["elementName"],
            "type": metadata["elementType"],
            "href": None,
            "source": "page-element-type",
        }
        (activities if element_type in {"activity", "actividad"} else processes).append(evidence)
    deduplicated_operations: list[dict[str, Any]] = []
    seen_operations: set[tuple[str, int]] = set()
    for operation in operations:
        key = (operation["name"], operation["sourceTable"])
        if key not in seen_operations:
            seen_operations.add(key)
            deduplicated_operations.append(operation)
    return deduplicated_operations, activities, processes


def build_page(
    parser: SparxPageParser,
    relative_file: str,
    source_root: Path,
    repository_root: Path,
    html_exact: set[str],
    html_folded: dict[str, list[str]],
    issues: IssueCollector,
    out_of_scope_html: set[str] | None = None,
) -> dict[str, Any]:
    file_path = (source_root / PurePosixPath(relative_file)).relative_to(repository_root).as_posix()
    page_key = evidence_page_key(relative_file)
    links = []
    for index, raw in enumerate(parser.links):
        normalized = normalize_link(
            raw, relative_file, source_root, repository_root, html_exact, html_folded, issues,
            out_of_scope_html,
        )
        normalized["evidenceId"] = evidence_id(page_key, "link", index)
        if raw.get("tag") == "area":
            normalized.update({key: raw.get(key) for key in ("alt", "shape", "coords", "areaIndex")})
            normalized["title"] = raw.get("title")
        links.append(normalized)
    properties = extract_properties(parser.tables)
    for index, item in enumerate(properties):
        item["evidenceId"] = evidence_id(page_key, "property", index)
    visual_metadata = [
        {"evidenceId": evidence_id(page_key, "visual", index), "index": index, **item}
        for index, item in enumerate(parser.visual_metadata)
    ]
    metadata = object_metadata(parser, properties)
    legends, lifecycle_states = extract_legend_lifecycle(
        parser, page_key, properties, visual_metadata, metadata
    )
    for legend in legends:
        legend["sourceFile"] = file_path
        for mapping in legend.get("mappings", []):
            mapping["legendSourceFile"] = file_path
    operations, activities, processes = extract_structured_names(parser, metadata)
    for index, item in enumerate(operations):
        item["evidenceId"] = evidence_id(page_key, "operation", index)
    for index, item in enumerate(activities):
        item["evidenceId"] = evidence_id(page_key, "activity", index)
    for index, item in enumerate(processes):
        item["evidenceId"] = evidence_id(page_key, "process", index)

    breadcrumb: list[dict[str, Any]] = []
    for raw in parser.breadcrumb_links:
        normalized = normalize_link(
            raw, relative_file, source_root, repository_root, html_exact, html_folded, issues,
            out_of_scope_html,
        )
        breadcrumb.append(
            {
                "text": normalized["text"],
                "segments": [clean_text(segment) for segment in normalized["text"].split("::") if clean_text(segment)],
                "target": normalized["target"],
                "resolved": normalized["resolved"],
            }
        )

    image_references: list[dict[str, Any]] = []
    diagrams: list[dict[str, Any]] = []
    for image in parser.images:
        normalized = normalize_link(
            {"tag": "img", "href": image.get("src", ""), "text": image.get("alt", "")},
            relative_file,
            source_root,
            repository_root,
            html_exact,
            html_folded,
            issues,
        )
        image_output = {
            "source": image.get("src"),
            "alt": image.get("alt"),
            "title": image.get("title"),
            "class": image.get("class"),
            "usemap": image.get("usemap"),
            "kind": normalized["kind"],
            "target": normalized["target"],
            "resolved": normalized["resolved"],
        }
        image_references.append(image_output)
        context_classes = [str(value) for value in image.get("contextClasses", [])]
        image_label = " ".join(
            str(value or "").casefold() for value in (image.get("alt"), image.get("title"))
        )
        structurally_diagrammed = any(
            "diagram" in structural_tokens(value) for value in context_classes
        )
        if image.get("usemap") or "diagram" in image_label or structurally_diagrammed:
            map_name = str(image.get("usemap") or "").lstrip("#") or None
            diagrams.append(
                {
                    "image": image.get("src"),
                    "target": normalized["target"],
                    "resolved": normalized["resolved"],
                    "mapName": map_name,
                    "links": [link for link in links if map_name and link.get("mapName") == map_name],
                }
            )

    text_blocks = []
    notes = []
    for index, block in enumerate(parser.blocks):
        text = clean_text("".join(block.parts))
        if not text:
            continue
        entry = {
            "evidenceId": evidence_id(page_key, "text", index),
            "index": index,
            "tag": block.tag,
            "classes": block.classes,
            "text": text,
        }
        is_notes = any("objectdetailsnotes" in name.casefold() for name in block.classes)
        if is_notes:
            note_id = evidence_id(page_key, "note", len(notes))
            element_identity = {
                "id": metadata.get("id"),
                "name": metadata.get("elementName"),
                "type": metadata.get("elementType"),
                "title": metadata.get("objectTitle"),
            }
            entry.update({
                "evidenceType": "notes-documentation",
                "notesEvidenceId": note_id,
                "rawLabel": "ObjectDetailsNotes",
                "rawType": "Notes/documentation",
                "htmlId": block.html_id,
                "elementIdentity": element_identity,
                "structuralContext": block.structural_context,
                "headingAssociation": block.preceding_heading,
                "propertyAssociation": {"label": "Notes", "basis": "ObjectDetailsNotes class"},
            })
            notes.append({
                "evidenceId": note_id,
                "textBlockEvidenceId": entry["evidenceId"],
                "sourcePage": file_path,
                "rawLabel": "ObjectDetailsNotes",
                "rawType": "Notes/documentation",
                "elementIdentity": element_identity,
                "structuralContext": block.structural_context,
                "headingAssociation": block.preceding_heading,
                "propertyAssociation": {"label": "Notes", "basis": "ObjectDetailsNotes class"},
            })
        text_blocks.append(entry)

    image_maps = []
    for image_map in parser.image_maps:
        map_name = image_map.get("name") or image_map.get("id")
        associated_images = [
            image for image in image_references
            if str(image.get("usemap") or "").lstrip("#") == map_name
        ]
        areas = []
        for area_index in image_map.get("areaIndexes", []):
            area = parser.image_map_areas[area_index]
            link = next((item for item in links if item.get("areaIndex") == area_index), None)
            areas.append({
                "evidenceId": evidence_id(page_key, "image-map-area", area_index),
                "sourcePage": file_path,
                "mapName": area.get("mapName"),
                "shape": area.get("shape"),
                "coords": area.get("coords"),
                "href": area.get("href"),
                "title": area.get("title"),
                "alt": area.get("alt"),
                "linkedPageIdentity": link.get("target") if link else None,
                "linkEvidenceId": link.get("evidenceId") if link else None,
                "attributes": area.get("attributes", {}),
            })
        image_maps.append({
            "evidenceId": evidence_id(page_key, "image-map", image_map["index"]),
            "sourcePage": file_path,
            "id": image_map.get("id"),
            "name": image_map.get("name"),
            "attributes": image_map.get("attributes", {}),
            "associatedDiagramAssets": associated_images,
            "areas": areas,
        })

    page: dict[str, Any] = {
        "id": metadata["id"],
        "evidenceKey": page_key,
        "file": file_path,
        "title": parser.title,
        "objectTitle": metadata["objectTitle"],
        "elementName": metadata["elementName"],
        "elementType": metadata["elementType"],
        "stereotype": metadata["stereotype"],
        "packageName": metadata["packageName"],
        "breadcrumb": breadcrumb,
        "breadcrumbText": clean_text("".join(parser.breadcrumb_parts)) or None,
        "anchors": sorted(parser.anchors),
        "headings": [
            {"evidenceId": evidence_id(page_key, "heading", index), **heading}
            for index, heading in enumerate(parser.headings)
        ],
        "properties": properties,
        "notes": notes,
        "textBlocks": text_blocks,
        "tables": [
            {
                "evidenceId": evidence_id(page_key, "table", table.index),
                **table_to_output(table, page_key, visual_metadata),
            }
            for table in parser.tables
        ],
        "visualMetadata": visual_metadata,
        "legends": legends,
        "lifecycleStates": lifecycle_states,
        "operations": operations,
        "activities": activities,
        "processes": processes,
        "links": links,
        "diagrams": diagrams,
        "imageReferences": image_references,
        "imageMaps": image_maps,
        "parent": None,
        "parentCandidates": [],
        "children": [],
    }
    return page


def apply_export_lifecycle_mappings(pages: list[dict[str, Any]]) -> None:
    """Apply only explicit export legend mappings to matching visual metadata."""
    mappings = [
        {**mapping, "legendSourceFile": legend.get("sourceFile"),
         "legendEvidenceId": legend.get("evidenceId")}
        for legend_page in pages
        for legend in legend_page.get("legends", [])
        for mapping in legend.get("mappings", [])
        if mapping.get("visualStyle")
    ]
    for page in pages:
        existing_visual_ids = {
            state.get("elementEvidenceId") for state in page.get("lifecycleStates", [])
        }
        next_index = len(page.get("lifecycleStates", []))
        page_key = str(page.get("evidenceKey") or "")
        for visual in page.get("visualMetadata", []):
            visual_id = visual.get("evidenceId")
            if not visual_id or visual_id in existing_visual_ids:
                continue
            if any(
                legend.get("sourceFile") == page.get("file")
                and legend.get("sourceTable") is not None
                and visual.get("tableIndex") == legend.get("sourceTable")
                for legend_page in pages for legend in legend_page.get("legends", [])
            ):
                continue
            style = lifecycle_visual_style(lifecycle_attributes(visual))
            if not style:
                continue
            matches = [mapping for mapping in mappings if all(
                style.get(key) == value for key, value in mapping["visualStyle"].items()
            )]
            if not matches:
                continue
            labels = unique_strings([mapping["label"] for mapping in matches])
            ids = unique_strings([
                eid for mapping in matches
                for eid in (visual_id, mapping["legendEvidenceId"], mapping["evidenceId"],
                            mapping["labelEvidenceId"], *mapping.get("visualEvidenceIds", []))
            ])
            record = {
                "evidenceId": evidence_id(page_key, "lifecycle", next_index),
                "value": labels[0] if len(labels) == 1 else None,
                "candidateValues": labels if len(labels) > 1 else [],
                "ambiguous": len(labels) > 1,
                "basis": "explicit-legend-style-match",
                "elementEvidenceId": visual_id,
                "elementHref": visual.get("hrefContext"),
                "visualEvidenceId": visual_id,
                "legendEvidenceIds": unique_strings([str(mapping["legendEvidenceId"]) for mapping in matches]),
                "legendMappingEvidenceIds": unique_strings([str(mapping["evidenceId"]) for mapping in matches]),
                "legendLabelEvidenceIds": unique_strings([str(mapping["labelEvidenceId"]) for mapping in matches]),
                "legendSourceFiles": unique_strings([str(mapping.get("legendSourceFile") or "") for mapping in matches]),
                "evidenceIds": ids,
                "visualStyle": style,
            }
            if len(matches) == 1:
                record.update({
                    "legendEvidenceId": matches[0]["legendEvidenceId"],
                    "legendMappingEvidenceId": matches[0]["evidenceId"],
                    "legendLabelEvidenceId": matches[0]["labelEvidenceId"],
                })
            page.setdefault("lifecycleStates", []).append(record)
            next_index += 1


def build_relationships(
    pages: list[dict[str, Any]], issues: IssueCollector
) -> list[dict[str, Any]]:
    page_files = {page["file"] for page in pages}
    relationships: set[tuple[str, str, str, str]] = set()
    by_file = {page["file"]: page for page in pages}

    for page in pages:
        breadcrumb = page["breadcrumb"]
        self_indexes = [index for index, item in enumerate(breadcrumb) if item.get("target") == page["file"]]
        if self_indexes:
            self_index = self_indexes[-1]
            if self_index > 0:
                parent = breadcrumb[self_index - 1]
                if parent.get("resolved") and parent.get("target") in page_files:
                    relationships.add((parent["target"], page["file"], "contains", "breadcrumb"))
        project_browser_hrefs = {
            raw.get("href")
            for item in page.get("_listItems", [])
            if any(
                value.casefold() == "indexcell"
                for value in item.get("contextClasses", [])
            )
            for raw in item.get("links", [])
        }
        for link in page["links"]:
            if link.get("kind") != "internal-page" or not link.get("resolved"):
                continue
            if (
                link.get("href") in project_browser_hrefs
                and link["target"] != page["file"]
            ):
                relationships.add((page["file"], link["target"], "contains", "project-browser"))

    result = [
        {"parent": parent, "child": child, "type": relation_type, "source": source}
        for parent, child, relation_type, source in sorted(relationships)
    ]
    parent_candidates: dict[str, dict[str, set[str]]] = {}
    for relationship in result:
        parent_candidates.setdefault(relationship["child"], {}).setdefault(
            relationship["parent"], set()
        ).add(relationship["source"])
    for child, candidates in sorted(parent_candidates.items()):
        child_page = by_file.get(child)
        if child_page is None:
            continue
        child_page["parentCandidates"] = [
            {"file": parent, "sources": sorted(sources)}
            for parent, sources in sorted(candidates.items())
        ]
        if len(candidates) == 1:
            parent, sources = next(iter(sorted(candidates.items())))
            child_page["parent"] = {"file": parent, "sources": sorted(sources)}
        else:
            issues.warning(
                "multiple_structural_parents",
                child,
                "Multiple explicit structural parents were preserved without selecting one.",
                ", ".join(sorted(candidates)),
            )
    for relationship in result:
        parent_page = by_file.get(relationship["parent"])
        if parent_page is not None:
            parent_page["children"].append(
                {
                    "file": relationship["child"],
                    "type": relationship["type"],
                    "source": relationship["source"],
                }
            )
    return result


def detect_duplicate_ids(pages: list[dict[str, Any]], issues: IssueCollector) -> None:
    identifiers: dict[str, list[str]] = {}
    displayed_identifiers: dict[str, str] = {}
    for page in pages:
        identifier = page.get("id")
        if identifier:
            displayed_identifier = str(identifier)
            guid_candidate = displayed_identifier.strip().strip("{}")
            if re.fullmatch(
                r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}",
                guid_candidate,
            ):
                key = guid_candidate.casefold()
            else:
                key = displayed_identifier
            identifiers.setdefault(key, []).append(page["file"])
            displayed_identifiers.setdefault(key, displayed_identifier)
    for identifier_key, files in sorted(identifiers.items()):
        unique_files = sorted(set(files))
        if len(unique_files) > 1:
            identifier = displayed_identifiers[identifier_key]
            issues.error(
                "duplicate_page_identifier",
                unique_files[0],
                f"Page identifier '{identifier}' is declared by multiple pages: {', '.join(unique_files)}",
                identifier,
            )


def resolve_fragments(pages: list[dict[str, Any]], issues: IssueCollector) -> None:
    anchors_by_file = {page["file"]: set(page["anchors"]) for page in pages}
    for page in pages:
        for link in page["links"]:
            fragment = link.get("fragment")
            target = link.get("target")
            if not fragment or not link.get("resolved") or target not in anchors_by_file:
                continue
            link["fragmentResolved"] = unquote(str(fragment)) in anchors_by_file[target]
            if not link["fragmentResolved"]:
                issues.warning(
                    "fragment_unresolved",
                    page["file"],
                    "Target page resolved, but the referenced fragment was not found.",
                    link.get("href"),
                )


def write_yaml(path: Path, value: dict[str, Any], yaml_module: Any, output_root: Path) -> None:
    if not is_within(path, output_root) or path == output_root:
        raise IndexingFailure(f"Output path must be a file under '{output_root}'.")

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
        raise IndexingFailure(f"Cannot write Sparx index '{path}': {exc}") from exc


def build_index(
    source_root: Path,
    repository_root: Path,
    issues: IssueCollector,
) -> dict[str, Any]:
    source_files = discover_source_files(source_root, issues)
    fingerprint = fingerprint_export(source_files, issues)
    html_files = [item for item in source_files if Path(item[0]).suffix.casefold() in HTML_SUFFIXES]
    if not html_files:
        issues.warning("no_html_files", source_root.relative_to(repository_root).as_posix(), "No .htm or .html files were discovered.")
    html_exact = {relative for relative, _ in html_files}
    html_folded: dict[str, list[str]] = {}
    for relative, _ in html_files:
        key = relative.casefold()
        html_folded.setdefault(key, []).append(relative)
    for key, matches in sorted(html_folded.items()):
        html_folded[key] = sorted(matches)
        if len(matches) > 1:
            issues.error(
                "case_ambiguous_html_path",
                sorted(matches)[0],
                f"HTML paths differ only by case: {', '.join(sorted(matches))}.",
            )

    pages: list[dict[str, Any]] = []
    for relative, path in html_files:
        parser = parse_html_page(path, relative, issues)
        page = build_page(
            parser, relative, source_root, repository_root, html_exact, html_folded, issues
        )
        page["_listItems"] = parser.list_items
        pages.append(page)

    apply_export_lifecycle_mappings(pages)
    relationships = build_relationships(pages, issues)
    for page in pages:
        page.pop("_listItems", None)
        page["children"] = sorted(
            page["children"], key=lambda item: (item["file"], item["source"], item["type"])
        )
    detect_duplicate_ids(pages, issues)
    resolve_fragments(pages, issues)

    internal_links = sum(
        1 for page in pages for link in page["links"] if link.get("kind") == "internal-page"
    )
    unresolved_links = sum(
        1
        for page in pages
        for link in page["links"]
        if link.get("kind") in {"internal-page", "local-asset", "unresolved"} and not link.get("resolved")
    )
    external_links = sum(
        1 for page in pages for link in page["links"] if link.get("kind") == "external"
    )
    warnings = issues.sorted_warnings()
    errors = issues.sorted_errors()
    return {
        "source": {
            "path": source_root.relative_to(repository_root).as_posix(),
            "fingerprint": fingerprint,
            "fingerprintAlgorithm": "sha256",
            "fileCount": len(source_files),
        },
        "statistics": {
            "htmlFiles": len(html_files),
            "indexedPages": len(pages),
            "internalLinks": internal_links,
            "unresolvedLinks": unresolved_links,
            "externalLinks": external_links,
            "warnings": len(warnings),
            "errors": len(errors),
        },
        "pages": pages,
        "relationships": relationships,
        "validation": {"warnings": warnings, "errors": errors},
    }


def _all_evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        item = value.get("evidenceId")
        if isinstance(item, str):
            found.add(item)
        for nested in value.values():
            found.update(_all_evidence_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_all_evidence_ids(nested))
    return found


def load_bounded_existing_pages(
    index_path: Path, selected_files: set[str], yaml_module: Any
) -> dict[str, dict[str, Any]]:
    """Load only exact existing page records from the global index; never re-index or deserialize all pages."""
    if index_path.is_symlink() or not index_path.is_file() or index_path.stat().st_size == 0:
        raise IndexingFailure("Existing global Sparx index is unavailable for bounded evidence comparison.")
    alternatives = b"|".join(re.escape(path.encode("utf-8")) for path in sorted(selected_files))
    pattern = re.compile(rb"(?m)^  file: (" + alternatives + rb")[ \t]*\r?$")
    records: dict[str, dict[str, Any]] = {}
    with index_path.open("rb") as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            for match in pattern.finditer(mapped):
                selected = match.group(1).decode("utf-8")
                line_start = mapped.rfind(b"\n", 0, match.start()) + 1
                start_marker = mapped.rfind(b"\n- id:", 0, line_start)
                start = 0 if start_marker < 0 and mapped[:3] == b"- id" else start_marker + 1
                end_marker = mapped.find(b"\n- id:", match.end())
                end = len(mapped) if end_marker < 0 else end_marker + 1
                if start >= line_start:
                    continue
                try:
                    record_value = yaml_module.safe_load(mapped[start:end])
                except yaml_module.YAMLError as exc:
                    raise IndexingFailure(f"Could not parse bounded existing index page '{selected}'.") from exc
                record = record_value[0] if isinstance(record_value, list) and record_value else record_value
                if isinstance(record, dict) and record.get("file") == selected:
                    records[selected] = record
    missing = sorted(selected_files - records.keys())
    if missing:
        raise IndexingFailure(f"Existing global index lacks approved target page record(s): {', '.join(missing)}")
    return records


def build_target_index(
    source_root: Path,
    repository_root: Path,
    audit_path: Path,
    issues: IssueCollector,
    yaml_module: Any,
) -> dict[str, Any]:
    """Index only pages explicitly listed in the approved gap audit; linked pages are metadata-only references."""
    factory_root = (repository_root / ".factory").resolve()
    logical_audit = audit_path if audit_path.is_absolute() else repository_root / audit_path
    if logical_audit.is_symlink():
        raise IndexingFailure("Target audit must be a regular file under .factory/.")
    audit_file = logical_audit.resolve()
    if not is_within(audit_file, factory_root) or not audit_file.is_file():
        raise IndexingFailure("Target audit must be a regular file under .factory/.")
    try:
        audit_bytes = audit_file.read_bytes()
        audit = yaml_module.safe_load(audit_bytes) or {}
    except (OSError, yaml_module.YAMLError) as exc:
        raise IndexingFailure(f"Cannot read approved target audit: {type(exc).__name__}.") from exc
    target = audit.get("target") or {}
    repo_source = source_root.relative_to(repository_root).as_posix()
    selected_repo_files = target.get("boundedOriginalPages") or []
    declared_count = target.get("boundedOriginalPageCount")
    if not selected_repo_files or declared_count != len(selected_repo_files):
        raise IndexingFailure("Target audit page list is empty or its declared count does not match.")
    relative_files: list[str] = []
    for repo_file in selected_repo_files:
        if not isinstance(repo_file, str) or not repo_file.startswith(repo_source + "/"):
            raise IndexingFailure("Target audit contains a page outside the requested Sparx export.")
        relative = PurePosixPath(repo_file).relative_to(PurePosixPath(repo_source)).as_posix()
        if PurePosixPath(relative).suffix.casefold() not in HTML_SUFFIXES or relative.startswith("../"):
            raise IndexingFailure("Target audit contains an unsafe or non-HTML page path.")
        resolved = (source_root / PurePosixPath(relative)).resolve()
        if not is_within(resolved, source_root) or not resolved.is_file():
            raise IndexingFailure(f"Approved target page is missing or unsafe: '{repo_file}'.")
        relative_files.append(relative)
    if len(set(relative_files)) != len(relative_files):
        raise IndexingFailure("Target audit contains duplicate page paths.")
    relative_files.sort()
    selected_repo_set = {f"{repo_source}/{relative}" for relative in relative_files}

    external_candidates = audit.get("additionalLinkedPageCandidatesNotLoaded") or []
    out_of_scope_relative: set[str] = set()
    external_reference_records = []
    for entry in external_candidates:
        repo_target = entry.get("targetPage") if isinstance(entry, dict) else None
        if not isinstance(repo_target, str) or not repo_target.startswith(repo_source + "/"):
            raise IndexingFailure("Target audit contains an out-of-scope reference outside the approved export.")
        rel = PurePosixPath(repo_target).relative_to(PurePosixPath(repo_source)).as_posix()
        if rel in relative_files:
            continue
        out_of_scope_relative.add(rel)
        external_reference_records.append({
            "targetPage": repo_target,
            "linkedFromPages": sorted(entry.get("linkedFromPages") or []),
            "status": "out-of-scope-not-loaded",
            "recursiveExpansion": False,
        })
    external_reference_records.sort(key=lambda item: item["targetPage"])

    html_exact = set(relative_files)
    html_folded: dict[str, list[str]] = {}
    for relative in relative_files:
        html_folded.setdefault(relative.casefold(), []).append(relative)
    selected_records = []
    pages: list[dict[str, Any]] = []
    audit_page_hashes = {
        str(row.get("sourcePage")): str(row.get("originalSha256"))
        for row in (audit.get("coverage", {}).get("pages") or [])
        if row.get("sourcePage") and row.get("originalSha256")
    }
    page_fingerprint = hashlib.sha256()
    for relative in relative_files:
        source_file = source_root / PurePosixPath(relative)
        repo_file = source_file.relative_to(repository_root).as_posix()
        try:
            raw = source_file.read_bytes()
        except OSError as exc:
            raise IndexingFailure(f"Cannot read approved target page '{repo_file}'.") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if audit_page_hashes.get(repo_file) != digest:
            issues.error(
                "approved_source_page_changed", repo_file,
                "Selected source page content differs from the approved audit fingerprint.",
            )
        page_fingerprint.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
        parser = parse_html_page(source_file, relative, issues)
        page = build_page(
            parser, relative, source_root, repository_root, html_exact, html_folded,
            issues, out_of_scope_relative,
        )
        page["_listItems"] = parser.list_items
        pages.append(page)
        selected_records.append({"file": repo_file, "sha256": digest})

    target_pages_by_file = {page["file"]: page for page in pages}
    for page in pages:
        for image_map in page.get("imageMaps", []):
            for area in image_map.get("areas", []):
                linked = target_pages_by_file.get(area.get("linkedPageIdentity"))
                if linked is not None:
                    area["linkedPageIdentity"] = {
                        "file": linked["file"],
                        "id": linked.get("id"),
                        "title": linked.get("title"),
                        "elementName": linked.get("elementName"),
                    }

    apply_export_lifecycle_mappings(pages)
    relationships = build_relationships(pages, issues)
    for page in pages:
        page.pop("_listItems", None)
        page["children"] = sorted(page["children"], key=lambda item: (item["file"], item["source"], item["type"]))
    detect_duplicate_ids(pages, issues)
    resolve_fragments(pages, issues)

    existing = load_bounded_existing_pages(repository_root / ".factory" / "sparx-index.yml", selected_repo_set, yaml_module)
    existing_ids = set().union(*(_all_evidence_ids(record) for record in existing.values()))
    target_ids = set().union(*(_all_evidence_ids(page) for page in pages))
    missing_existing_ids = sorted(existing_ids - target_ids)
    if missing_existing_ids:
        issues.error(
            "existing_evidence_ids_changed", ".factory/sparx-index.yml",
            "One or more existing selected-page evidence IDs are absent from the targeted output.",
            ", ".join(missing_existing_ids[:20]),
        )

    expected_notes = []
    for gap in audit.get("parserGaps") or []:
        if gap.get("type") == "notes-not-preserved-in-index":
            for text in gap.get("evidence") or []:
                expected_notes.append({"sourcePage": gap.get("sourcePage"), "text": str(text)})
    captured_notes = [
        {"sourcePage": page["file"], "text": block.get("text", ""), "evidenceId": block.get("notesEvidenceId")}
        for page in pages for block in page.get("textBlocks", [])
        if block.get("evidenceType") == "notes-documentation"
    ]
    matched_note_count = 0
    consumed_note_indexes: set[int] = set()
    for expected in expected_notes:
        expected_text = "".join(clean_text(expected["text"]).casefold().split())
        candidates = []
        for index, item in enumerate(captured_notes):
            if index in consumed_note_indexes or item["sourcePage"] != expected["sourcePage"]:
                continue
            observed = "".join(clean_text(item["text"]).casefold().split())
            if expected_text == observed or observed.startswith(expected_text):
                candidates.append((1.0, index))
            else:
                score = difflib.SequenceMatcher(None, expected_text, observed[:max(len(expected_text), 1)]).ratio()
                if score >= 0.90:
                    candidates.append((score, index))
        if candidates:
            _, matched_index = max(candidates, key=lambda item: (item[0], -item[1]))
            consumed_note_indexes.add(matched_index)
            matched_note_count += 1

    geometry_gaps = [gap for gap in audit.get("parserGaps") or []
                     if gap.get("type") == "image-map-geometry-not-normalized"]
    expected_geometry_pages = sorted(str(gap.get("sourcePage")) for gap in geometry_gaps)
    expected_geometry_areas = sum(len(gap.get("evidence") or []) for gap in geometry_gaps)
    expected_area_signatures = [
        (str(gap.get("sourcePage")), str(area.get("mapName") or ""), str(area.get("href") or ""),
         str(area.get("shape") or ""), str(area.get("coords") or ""))
        for gap in geometry_gaps for area in (gap.get("evidence") or [])
    ]
    captured_area_signatures = [
        (page["file"], str(area.get("mapName") or ""), str(area.get("href") or ""),
         str(area.get("shape") or ""), str(area.get("coords") or ""))
        for page in pages for image_map in page.get("imageMaps", []) for area in image_map.get("areas", [])
    ]
    captured_area_signature_counts: dict[tuple[str, ...], int] = {}
    for signature in captured_area_signatures:
        captured_area_signature_counts[signature] = captured_area_signature_counts.get(signature, 0) + 1
    matched_geometry_areas = 0
    for signature in expected_area_signatures:
        available = captured_area_signature_counts.get(signature, 0)
        if available:
            captured_area_signature_counts[signature] = available - 1
            matched_geometry_areas += 1
    captured_page_lookup = {page["file"]: page for page in pages}
    captured_geometry_pages = sorted(
        page for page in expected_geometry_pages
        if page in captured_page_lookup and captured_page_lookup[page].get("imageMaps")
        and any(area.get("coords") is not None or area.get("shape") is not None
                for image_map in captured_page_lookup[page]["imageMaps"] for area in image_map.get("areas", []))
    )
    captured_geometry_areas = sum(
        len(area_gap.get("evidence") or [])
        for area_gap in geometry_gaps
        if area_gap.get("sourcePage") in captured_page_lookup
        and captured_page_lookup[area_gap["sourcePage"]].get("imageMaps")
    )

    old_asset_owners: dict[str, set[str]] = {}
    new_asset_owners: dict[str, set[str]] = {}
    asset_map_required: dict[str, bool] = {}
    for page_file, record in existing.items():
        for image in record.get("imageReferences") or []:
            asset = image.get("target")
            if asset:
                old_asset_owners.setdefault(asset, set()).add(page_file)
        for link in record.get("links") or []:
            if link.get("kind") == "local-asset" and link.get("target"):
                old_asset_owners.setdefault(link["target"], set()).add(page_file)
    for page in pages:
        for image in page.get("imageReferences") or []:
            asset = image.get("target")
            if asset:
                new_asset_owners.setdefault(asset, set()).add(page["file"])
                if image.get("usemap"):
                    asset_map_required[asset] = True
        for link in page.get("links") or []:
            if link.get("kind") == "local-asset" and link.get("target"):
                new_asset_owners.setdefault(link["target"], set()).add(page["file"])
    audited_assets = audit.get("diagramCoverage", {}).get("assets") or []
    asset_records = []
    audit_asset_details: dict[str, list[dict[str, Any]]] = {}
    audit_asset_pages: dict[str, set[str]] = {}
    for page_row in (audit.get("coverage", {}).get("pages") or []):
        for item in page_row.get("additionalLinkedAssets") or []:
            audit_asset_details.setdefault(item.get("path", ""), []).append(item)
            audit_asset_pages.setdefault(item.get("path", ""), set()).add(page_row.get("sourcePage", ""))
    for asset in sorted(set(str(item) for item in audited_assets)):
        details = audit_asset_details.get(asset, [])
        asset_records.append({
            "path": asset,
            "sourcePages": sorted(audit_asset_pages.get(asset, set())),
            "kinds": sorted({str(item.get("kind")) for item in details}),
            "existsInAudit": any(item.get("exists") for item in details),
            "representedInExistingIndex": asset in old_asset_owners,
            "representedInTargetIndex": asset in new_asset_owners,
            "requiredForImageMapInterpretation": asset_map_required.get(asset, False),
            "assetBytesRead": False,
            "imageSemanticsInterpreted": False,
        })

    links_by_target = {
        link.get("target") for page in pages for link in page.get("links", []) if link.get("outOfScope")
    }
    missing_external_targets = sorted(set(out_of_scope_relative) - {
        PurePosixPath(target_path).relative_to(PurePosixPath(repo_source)).as_posix()
        for target_path in links_by_target if isinstance(target_path, str) and target_path.startswith(repo_source + "/")
    })
    if missing_external_targets:
        issues.error(
            "out_of_scope_reference_not_preserved", ".factory/sparx-parser-gap-audit.yml",
            "An audited out-of-scope target did not appear in bounded page link evidence.",
            ", ".join(missing_external_targets[:20]),
        )

    all_links = [link for page in pages for link in page.get("links", [])]
    warnings = issues.sorted_warnings()
    errors = issues.sorted_errors()
    return {
        "source": {
            "path": repo_source,
            "scope": "targeted-audit-pages-only",
            "targetAudit": audit_file.relative_to(repository_root).as_posix(),
            "targetAuditSha256": hashlib.sha256(audit_bytes).hexdigest(),
            "selectedPageFingerprint": page_fingerprint.hexdigest(),
            "selectedPageFingerprintAlgorithm": "sha256-path-and-content-digests-v1",
            "fileCount": len(relative_files),
            "selectedPages": selected_records,
        },
        "statistics": {
            "indexedPages": len(pages),
            "links": len(all_links),
            "outOfScopeReferences": sum(1 for link in all_links if link.get("outOfScope")),
            "notes": len(captured_notes),
            "imageMaps": sum(len(page.get("imageMaps") or []) for page in pages),
            "imageMapAreas": sum(len(image_map.get("areas") or []) for page in pages
                                  for image_map in page.get("imageMaps") or []),
            "assets": len(asset_records),
            "warnings": len(warnings),
            "errors": len(errors),
        },
        "auditReconciliation": {
            "noteGapPageCount": len({item.get("sourcePage") for item in expected_notes}),
            "expectedMissingNotes": len(expected_notes),
            "expectedMissingNotesCaptured": matched_note_count,
            "expectedMissingNotesUnaccounted": len(expected_notes) - matched_note_count,
            "expectedImageMapPages": expected_geometry_pages,
            "expectedImageMapPagesCaptured": captured_geometry_pages,
            "expectedGeometryAreas": expected_geometry_areas,
            "expectedGeometryAreasCaptured": matched_geometry_areas,
            "expectedGeometryAreasUnaccounted": expected_geometry_areas - matched_geometry_areas,
            "auditedAssets": asset_records,
            "externalReferencesPreservedNotLoaded": external_reference_records,
            "externalReferenceCount": len(external_reference_records),
        },
        "pages": pages,
        "relationships": relationships,
        "validation": {
            "warnings": warnings,
            "errors": errors,
            "existingEvidenceIdsStable": not missing_existing_ids,
            "missingExistingEvidenceIds": missing_existing_ids,
            "approvedOriginalPageHashesMatch": all(
                audit_page_hashes.get(item["file"]) == item["sha256"] for item in selected_records
            ),
            "globalIndexRegenerated": False,
            "pagesOutsideApprovedSetRead": 0,
            "outOfScopeTargetsOpened": 0,
            "semanticInterpretationPerformed": False,
            "stage2BExecuted": False,
        },
    }


def main() -> int:
    arguments = parse_arguments()
    try:
        repository_root = find_repository_root()
        logical_source = (
            arguments.input if arguments.input.is_absolute() else repository_root / arguments.input
        ).absolute()
        logical_output = (
            arguments.output if arguments.output.is_absolute() else repository_root / arguments.output
        ).absolute()
        try:
            sparx_root = (repository_root / "input" / "sparx").resolve()
            factory_root = (repository_root / ".factory").resolve()
            source_root = logical_source.resolve()
            output = logical_output.resolve()
        except (OSError, RuntimeError) as exc:
            detail = exc.strerror if isinstance(exc, OSError) else None
            raise IndexingFailure(
                f"Cannot resolve input/output roots safely: {detail or type(exc).__name__}."
            ) from exc

        if not is_within(logical_source, (repository_root / "input" / "sparx").absolute()):
            raise IndexingFailure("Input directory must be located under 'input/sparx/'.")
        if not is_within(source_root, sparx_root) or source_root == sparx_root:
            raise IndexingFailure("Input directory must resolve under 'input/sparx/'.")
        if not source_root.is_dir():
            raise IndexingFailure(f"Sparx source does not exist or is not a directory: '{source_root}'.")
        if not is_within(logical_output, (repository_root / ".factory").absolute()):
            raise IndexingFailure("Output path must be located under '.factory/'.")
        if not is_within(output, factory_root) or output == factory_root:
            raise IndexingFailure("Output path must resolve to a file under '.factory/'.")
        if output.exists() and output.is_dir():
            raise IndexingFailure("Output path must resolve to a YAML file, not a directory.")
        if is_within(output, source_root):
            raise IndexingFailure("Output path must not overlap the read-only Sparx source directory.")
        reserved_stage_two_output = factory_root / "sparx-spec.yml"
        reserved_alias = False
        if output.exists() and reserved_stage_two_output.exists():
            try:
                reserved_alias = output.samefile(reserved_stage_two_output)
            except OSError as exc:
                raise IndexingFailure(
                    f"Cannot validate output identity safely: {exc.strerror or type(exc).__name__}."
                ) from exc
        if (
            arguments.output.name.casefold() == "sparx-spec.yml"
            or output.name.casefold() == "sparx-spec.yml"
            or reserved_alias
        ):
            raise IndexingFailure("Stage 1 cannot produce sparx-spec.yml; use sparx-index.yml.")
        if (
            arguments.output.suffix.casefold() not in {".yml", ".yaml"}
            or output.suffix.casefold() not in {".yml", ".yaml"}
        ):
            raise IndexingFailure("Stage 1 output must use a .yml or .yaml suffix.")
        if arguments.target_audit is not None:
            global_index = (factory_root / "sparx-index.yml").resolve()
            if output == global_index or output.name.casefold() == "sparx-index.yml":
                raise IndexingFailure("Targeted indexing must not replace the global sparx-index.yml.")

        yaml_module = load_yaml_module()
        issues = IssueCollector(source_root.relative_to(repository_root).as_posix())
        if arguments.target_audit is not None:
            index = build_target_index(
                source_root, repository_root, arguments.target_audit, issues, yaml_module
            )
        else:
            index = build_index(source_root, repository_root, issues)
        write_yaml(output, index, yaml_module, factory_root)
    except IndexingFailure as exc:
        print(f"index_sparx.py: error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Wrote '{output}' with {index['statistics']['indexedPages']} page(s), "
        f"{index['statistics']['warnings']} warning(s), and {index['statistics']['errors']} error(s).",
        file=sys.stderr,
    )
    return 1 if index["validation"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
