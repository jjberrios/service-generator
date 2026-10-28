"""Shared helpers for the visual evidence of the audit report (no browser dependency).

Visual evidence is always authentic: either a real browser screenshot of the original Sparx HTML page/linkdoc, or a rendering of the verbatim
lines of the original OpenAPI file. Images are grayscale, contain only the fragment that justifies a finding, and never show internal
references (GUIDs, pointers, page or file names). Anything that cannot be obtained authentically is left as text only.
"""
from pathlib import Path
import re
import yaml
from PIL import Image, ImageDraw, ImageFont

DPI = 192                      # screenshots are taken at device scale factor 2 (96 dpi x 2); the text render uses the same density
MAX_WIDTH_CM = 16.9            # text area of an A4 page with 2 cm margins is 17 cm
MAX_HEIGHT_CM = 12.0
MIN_SCALE = 0.55               # below this the text of the image is considered illegible
# Internal traceability data (kept only in findings.yml) must never appear in the Word report nor inside its images.
INTERNAL_REFERENCE = re.compile(r'\{[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27}\}|#/[A-Za-z]|\bEA\d{2,}\b|\.htm\b|\blinkdocs?/|EARoot|\.ya?ml\b|findings|snapshot|reports/|\\|pageSha|[0-9a-f]{32,}', re.I)
FONT_CANDIDATES = ('C:/Windows/Fonts/consola.ttf', 'C:/Windows/Fonts/cour.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', '/Library/Fonts/Courier New.ttf')


def fit_cm(width_px: int, height_px: int) -> tuple[float, float, float]:
    """Display size in cm that keeps the image inside the margins; third value is the scale applied to the natural size."""
    natural_w, natural_h = width_px / DPI * 2.54, height_px / DPI * 2.54
    scale = min(1.0, MAX_WIDTH_CM / natural_w, MAX_HEIGHT_CM / natural_h)
    return natural_w * scale, natural_h * scale, scale


def is_grayscale(image: Image.Image) -> bool:
    if image.mode in ('L', '1'):
        return True
    if image.mode == 'LA':
        return True
    rgb = image.convert('RGB')
    return all(r == g == b for r, g, b in rgb.getdata())


def leaks(texts) -> list[str]:
    return [t for t in texts if INTERNAL_REFERENCE.search(t)]


# ------------------------------------------------------------------------------------------------------------ YAML fragments
REF_LINE = re.compile(r'^(\s*)(-\s+)?\$ref\s*:')
ELISION = '…'


def child(node, key):
    """Child of a composed YAML node by mapping key (str) or sequence index (int); returns (key_node, value_node) or None."""
    if isinstance(node, yaml.MappingNode) and isinstance(key, str):
        for key_node, value_node in node.value:
            if key_node.value == key:
                return key_node, value_node
    if isinstance(node, yaml.SequenceNode) and isinstance(key, int) and 0 <= key < len(node.value):
        return None, node.value[key]
    return None


def yaml_fragment(source_text: str, node_path: list, key_only: bool = False, value_only: bool = False) -> list[str] | None:
    """Verbatim source lines of the node at node_path (key line plus value; a list item starts at its own line) or None if the path does not exist."""
    node = yaml.compose(source_text, Loader=yaml.SafeLoader)
    key_node = None
    for part in node_path:
        found = child(node, part)
        if not found:
            return None
        key_node, node = found
    lines = source_text.splitlines()
    start = key_node.start_mark.line if (key_node is not None and not value_only) else node.start_mark.line
    if key_only:
        return [lines[start]]
    end = min(node.end_mark.line, len(lines) - 1)
    at_end_of_file = node.end_mark.line >= len(lines)
    # A block collection ends where the next token starts; if that mark sits at the beginning (indent) of a later line, that line is not part of the node.
    if end > start and not at_end_of_file and not lines[end][:node.end_mark.column].strip():
        end -= 1
    block = lines[start:end + 1]
    while block and not block[-1].strip():
        block.pop()
    return block


def elide_references(lines: list[str]) -> tuple[list[str], int]:
    """Reference lines ($ref) are technical: they are replaced, visibly, by an ellipsis so the Word never shows them."""
    out, count = [], 0
    for line in lines:
        match = REF_LINE.match(line)
        if match:
            out.append(match.group(1) + (' ' * len(match.group(2)) if match.group(2) else '') + ELISION)
            count += 1
        else:
            out.append(line)
    return out, count


def yaml_fragments(source_text: str, nodes: list[dict], max_lines: int = 40, relative: bool = False, elide: bool = True) -> list[str] | None:
    """Verbatim lines of one or more YAML nodes. Each fragment is dedented on its own and separated by a blank line, unless
    `relative` is set, in which case the nodes form one nested excerpt that keeps its relative indentation."""
    blocks = []
    for spec in nodes:
        block = yaml_fragment(source_text, spec['path'], bool(spec.get('keyOnly')), bool(spec.get('valueOnly')))
        if not block:
            return None
        blocks.append(elide_references(block)[0] if elide else block)
    indent_of = lambda lines: min(len(l) - len(l.lstrip(' ')) for l in lines if l.strip())
    lines = []
    if relative:
        indent = indent_of([l for block in blocks for l in block])
        lines = [l[indent:] for block in blocks for l in block]
    else:
        for index, block in enumerate(blocks):
            if index:
                lines.append('')
            indent = indent_of(block)
            lines.extend(l[indent:] for l in block)
    return lines if len(lines) <= max_lines else None


def render_text_image(lines: list[str], output: Path) -> tuple[int, int]:
    """Grayscale rendering of verbatim source lines (monospaced, black on white). Raises if no font is available."""
    font = None
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            font = ImageFont.truetype(candidate, 22)
            break
    if font is None:
        raise RuntimeError('no monospaced font available')
    pad, line_height = 18, 31
    probe = ImageDraw.Draw(Image.new('L', (10, 10)))
    width = max(int(probe.textlength(line.replace('\t', '    '), font=font)) for line in lines) + 2 * pad
    height = line_height * len(lines) + 2 * pad
    image = Image.new('L', (max(width, 200), height), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, image.width - 1, image.height - 1], outline=140, width=2)
    for index, line in enumerate(lines):
        draw.text((pad, pad + index * line_height), line.replace('\t', '    '), fill=0, font=font)
    image.save(output, dpi=(DPI, DPI))
    return image.width, image.height
