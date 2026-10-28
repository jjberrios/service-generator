"""Deterministic DOCX rendering of a Sparx/Swagger inconsistency registry (python-docx).

Same registry in -> same document content out. Black text on white, Calibri 11, no cover, header, footer, page numbers,
logos, colors or generic introductions; the document starts directly with the findings grouped by HTTP operation.
Each finding is a two-column structured table (bold black labels) that never splits across pages.
"""
from pathlib import Path
import argparse
import sys
import yaml
from docx import Document

import visual_evidence as ve
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

FONT = 'Calibri'
SIZE = Pt(11)
BLACK = RGBColor(0, 0, 0)
LABELS = ('ID', 'Operación', 'Elemento afectado', 'Sparx', 'Swagger', 'Inconsistencia detectada', 'Severidad')
BODY_LABELS = LABELS[1:6]
EMPTY_TEXT = 'No se detectaron inconsistencias verificables.'
CATEGORY_ORDER = ('contradiccion-verificada', 'diferencia-documental')
CATEGORY_LABELS = {'contradiccion-verificada': 'Contradicciones verificadas', 'diferencia-documental': 'Diferencias documentales'}
UNVERIFIED_LABELS = {'comportamiento-no-especificado': 'Comportamiento no especificado', 'contradiccion-interna-sparx': 'Contradicción interna de Sparx (no es una diferencia con Swagger)',
                     'fuente-no-comparable': 'Fuentes no comparables', 'verificacion-pendiente': 'Verificación pendiente'}
MARGIN = Cm(2.0)
PAGE_TEXT_WIDTH = Cm(21.0) - 2 * MARGIN  # A4 portrait
COL_ID, COL_ID_VALUE, COL_SEVERITY = Cm(3.3), Cm(4.7), Cm(2.4)


def operation_title(operation: dict) -> str:
    return f'{operation["method"]} {operation["path"]}'


def finding_rows(finding: dict) -> list[tuple[str, list[str]]]:
    """Rows shown in the Word table. Evidence stays in findings.yml and is never rendered."""
    operation = finding['operation']
    inconsistency = [finding['inconsistency']]
    if finding.get('humanDecisionContext'):
        inconsistency.append(f'Existe una decisión humana registrada sobre esta operación ({", ".join(finding["humanDecisionContext"])}); no elimina la diferencia entre las fuentes originales.')
    return [('Operación', [operation_title(operation) + (f' ({operation["operationId"]})' if operation.get('operationId') else '')]),
            ('Elemento afectado', [finding['element']]), ('Sparx', [finding['sparx']['text']]), ('Swagger', [finding['swagger']['text']]),
            ('Inconsistencia detectada', inconsistency)]


def style_run(run, bold=False):
    run.font.name = FONT
    run.font.size = SIZE
    run.font.bold = bold
    run.font.color.rgb = BLACK
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn('w:rFonts'))
    if fonts is None:
        fonts = OxmlElement('w:rFonts')
        rpr.append(fonts)
    for attribute in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        fonts.set(qn(attribute), FONT)


def neutralize_theme_colors(document):
    """The default template carries blue/accent theme colors in heading and table styles; force every color to black."""
    root = document.styles.element
    for element in root.iter(qn('w:color')):
        element.set(qn('w:val'), '000000')
        for attribute in ('w:themeColor', 'w:themeShade', 'w:themeTint'):
            if element.get(qn(attribute)) is not None:
                del element.attrib[qn(attribute)]
    for element in root.iter(qn('w:shd')):
        element.set(qn('w:fill'), 'FFFFFF')
        for attribute in ('w:themeFill', 'w:themeFillShade', 'w:themeFillTint', 'w:themeColor'):
            if element.get(qn(attribute)) is not None:
                del element.attrib[qn(attribute)]
    for element in root.iter(qn('w:bottom'), qn('w:top'), qn('w:left'), qn('w:right'), qn('w:insideH'), qn('w:insideV')):
        element.set(qn('w:color'), '000000')
        for attribute in ('w:themeColor', 'w:themeShade', 'w:themeTint'):
            if element.get(qn(attribute)) is not None:
                del element.attrib[qn(attribute)]


def black_styles(document):
    for style in document.styles:
        font = getattr(style, 'font', None)
        if font is None:
            continue
        font.color.rgb = BLACK
        if style.type == 1 or style.name in ('Normal',):
            font.name = FONT
            font.size = SIZE
    neutralize_theme_colors(document)


def set_cell_borders(cell):
    properties = cell._tc.get_or_add_tcPr()
    borders = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        element = OxmlElement(f'w:{edge}')
        element.set(qn('w:val'), 'single')
        element.set(qn('w:sz'), '4')
        element.set(qn('w:color'), '000000')
        borders.append(element)
    properties.append(borders)


def fix_table(table):
    properties = table._tbl.tblPr
    layout = OxmlElement('w:tblLayout')
    layout.set(qn('w:type'), 'fixed')
    properties.append(layout)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for row in table.rows:
        row_properties = row._tr.get_or_add_trPr()
        row_properties.append(OxmlElement('w:cantSplit'))


def write_cell(cell, lines, bold=False):
    first = True
    for line in lines:
        paragraph = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        paragraph.paragraph_format.space_after = Pt(1)
        style_run(paragraph.add_run(line), bold=bold)
    set_cell_borders(cell)


def add_finding_table(document, finding, images_root=None):
    """Compact grid: ID and Severidad share the first row; the other fields span the full width. Rows never split across pages."""
    rows = finding_rows(finding)
    table = document.add_table(rows=1 + len(rows), cols=4)
    table.autofit = False
    widths = [COL_ID, COL_ID_VALUE, COL_SEVERITY, PAGE_TEXT_WIDTH - Cm(0.1) - COL_ID - COL_ID_VALUE - COL_SEVERITY]
    first = table.rows[0].cells
    for cell, width in zip(first, widths):
        cell.width = width
    write_cell(first[0], ['ID'], bold=True)
    write_cell(first[1], [finding['id']])
    write_cell(first[2], ['Severidad'], bold=True)
    write_cell(first[3], [finding['severity']])
    for row, (label, lines) in zip(table.rows[1:], rows):
        for cell, width in zip(row.cells, widths):
            cell.width = width
        write_cell(row.cells[0], [label], bold=True)
        merged = row.cells[1].merge(row.cells[3])
        write_cell(merged, lines)
        merged.width = widths[1] + widths[2] + widths[3]
    for row in table.rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True
    fix_table(table)
    add_visual_evidence(document, finding, images_root)
    spacer = document.add_paragraph()
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(6)


def add_visual_evidence(document, finding, images_root):
    """Insert the authentic images (grayscale, fitted to the margins) below the table, labelled Sparx and Swagger. Text-only when none exist."""
    for source, label in (('sparx', 'Sparx'), ('swagger', 'Swagger')):
        visual = (finding.get('visualEvidence') or {}).get(source) or {}
        if visual.get('status') != 'captured':
            continue
        image = Path(images_root or '.') / visual['image']
        if not image.is_file():
            raise FileNotFoundError(f'captured image missing for {finding["id"]} ({label}); rerun capture_evidence.py')
        caption = document.add_paragraph()
        caption.paragraph_format.keep_with_next = True
        caption.paragraph_format.space_before = Pt(4)
        caption.paragraph_format.space_after = Pt(1)
        style_run(caption.add_run(label), bold=True)
        width_cm, _, _ = ve.fit_cm(visual['widthPx'], visual['heightPx'])
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(2)
        run = paragraph.add_run()
        style_run(run)
        run.add_picture(str(image), width=Cm(width_cm))


def add_heading_line(document, text):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.space_before = Pt(6)
    style_run(paragraph.add_run(text), bold=True)


def group_by_operation(registry):
    groups = {}
    for finding in registry['findings']:
        groups.setdefault(operation_title(finding['operation']), {}).setdefault(finding['category'], []).append(finding)
    return groups


def unverified_lines(registry):
    lines = []
    for item in registry.get('unverified') or []:
        op = item.get('operation')
        title = operation_title(op) if isinstance(op, dict) and op.get('method') else 'General'
        lines.append((title, f'{title}: {UNVERIFIED_LABELS[item["category"]]}. {item.get("topic")} — {item.get("reason")}'))
    return [text for _, text in sorted(lines)]


def build(registry: dict, output: Path, images_root: Path | None = None):
    document = Document()
    black_styles(document)
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = MARGIN
    section.top_margin = section.bottom_margin = Cm(2.0)
    section.header.is_linked_to_previous = True
    section.footer.is_linked_to_previous = True
    body = document.element.body
    for paragraph in list(document.paragraphs):
        body.remove(paragraph._element)
    groups = group_by_operation(registry)
    if not groups:
        style_run(document.add_paragraph().add_run(EMPTY_TEXT))
    for title in sorted(groups, key=lambda t: (t.split(' ', 1)[1], t)):
        add_heading_line(document, title)
        for category in CATEGORY_ORDER:
            if category in groups[title]:
                add_heading_line(document, CATEGORY_LABELS[category])
                for finding in groups[title][category]:
                    add_finding_table(document, finding, images_root)
    pending = unverified_lines(registry)
    if pending:
        add_heading_line(document, 'No verificado')
        for line in pending:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(2)
            style_run(paragraph.add_run(line))
    output.parent.mkdir(parents=True, exist_ok=True)
    document.core_properties.author = ''
    document.core_properties.title = registry['service']
    document.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registry', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    registry = yaml.safe_load(args.registry.read_bytes())
    build(registry, args.output, args.registry.parent)
    print(args.output)


if __name__ == '__main__':
    sys.exit(main())
