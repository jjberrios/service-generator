"""Obtain authentic visual evidence for each finding of a registry, fully automatically, and record it in findings.yml.

The fragments are DERIVED from the structured data already stored in each finding (no supplemental.yml, no manual capture specs):
  Swagger  evidence.swagger[].pointer -> resolved (following local $ref) against the ORIGINAL OpenAPI file -> verbatim lines rendered as an image
  Sparx    evidence.sparx[] (element, activity, linkdoc/page, section, evidenceId) + the finding texts -> matched against the ORIGINAL Sparx page
           rendered in a real headless browser -> screenshot cropped to the justifying rows / text
Images are grayscale, never retouched, fitted inside the margins and show no internal references ($ref lines are replaced by a visible
ellipsis). If an authentic image cannot be obtained, the finding stays text-only and the cause is recorded in findings.yml
(visualEvidence.<source>.reason, never rendered in the Word). Existing `capture` specs in evidence items are still honored (compatibility).
"""
from pathlib import Path
import argparse
import hashlib
import shutil
import sys
import yaml
from PIL import Image

import evidence_locator as loc
import visual_evidence as ve

BROWSERS = ('C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
            'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
            '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
VIEWPORT_WIDTH = 800
PAD_X, PAD_Y = 8, 3
MERGE_GAP = 24
DIVIDER = 14

LEAF_ROWS_JS = "const leafRows = () => Array.from(document.querySelectorAll('tr')).filter(tr => !tr.querySelector('tr'));"

MODEL_JS = "() => {" + LEAF_ROWS_JS + r"""
  const trs = leafRows();
  const flat = (s) => s.replace(/\s+/g, ' ').trim();
  const rows = trs.map((tr, i) => {
    const table = tr.closest('table');
    const first = trs.findIndex(t => t.closest('table') === table);
    return {i, first, cells: Array.from(tr.children).filter(c => /^(TD|TH)$/.test(c.tagName)).map(c => flat(c.innerText))};
  });
  const blocks = Array.from(document.querySelectorAll('td,th,p,li,div'))
    .filter(e => !e.querySelector('table,tr,td,th') && flat(e.innerText).length >= 20)
    .map(e => ({text: flat(e.innerText), lines: e.innerText.split('\n').map(flat).filter(l => l.length)}));
  return {rows, blocks, text: document.body.innerText};
}"""

LOCATE_JS = "(regions) => {" + LEAF_ROWS_JS + r"""
  const sel = getSelection();
  const find1 = (text) => window.find(text, true, false, false, false, false, false);
  // A phrase may continue on another visual line (<br>); fall back to its leading words, which still locate the same place.
  const find = (text) => { const w = text.split(' '); for (let n = w.length; n >= 1; n--) { if (find1(w.slice(0, n).join(' '))) return true; } return false; };
  const box = (b) => ({x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height});
  const out = [];
  const trs = leafRows();
  for (const reg of regions) {
    const kind = reg.kind || 'row';
    if (kind === 'rowindex') {
      const el = trs[reg.index];
      if (!el) return {error: 'row not found'};
      out.push({...box(el.getBoundingClientRect()), text: el.innerText, pad: false});
      continue;
    }
    sel.removeAllRanges(); window.scrollTo(0, 0);
    let ok = true;
    for (let i = 0; i < (reg.occurrence || 1); i++) { ok = find(reg.text); if (!ok) break; }
    if (!ok) return {error: 'text not found: ' + reg.text};
    const range = sel.getRangeAt(0).cloneRange();
    if (kind === 'span') {
      if (!find(reg.to)) return {error: 'end text not found: ' + reg.to};
      const end = sel.getRangeAt(0);
      range.setEnd(end.endContainer, end.endOffset);
      out.push({...box(range.getBoundingClientRect()), text: range.toString(), pad: true});
    } else if (kind === 'text') {
      out.push({...box(range.getBoundingClientRect()), text: range.toString(), pad: true});
    } else {
      const node = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
      const el = kind === 'row' ? node.closest('tr') : node.closest('td,p,div,li');
      if (!el) return {error: 'no ' + kind + ' container for: ' + reg.text};
      out.push({...box(el.getBoundingClientRect()), text: el.innerText, pad: false});
    }
  }
  sel.removeAllRanges(); window.scrollTo(0, 0);
  return {regions: out};
}"""


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_browser():
    return next((b for b in BROWSERS if Path(b).is_file()), None)


def merge_rects(rects):
    """Union rects that touch (gap <= MERGE_GAP); separate fragments stay separate."""
    rects = sorted(rects, key=lambda r: (r['y'], r['x']))
    merged = []
    for rect in rects:
        if merged and rect['y'] <= merged[-1]['y'] + merged[-1]['h'] + MERGE_GAP:
            last = merged[-1]
            left, top = min(last['x'], rect['x']), min(last['y'], rect['y'])
            right, bottom = max(last['x'] + last['w'], rect['x'] + rect['w']), max(last['y'] + last['h'], rect['y'] + rect['h'])
            last.update(x=left, y=top, w=right - left, h=bottom - top)
        else:
            merged.append(dict(rect))
    return merged


def stitch(crops: list[Image.Image]) -> Image.Image:
    width = max(c.width for c in crops)
    height = sum(c.height for c in crops) + DIVIDER * (len(crops) - 1)
    canvas = Image.new('L', (width, height), 255)
    y = 0
    for index, crop in enumerate(crops):
        canvas.paste(crop, (0, y))
        y += crop.height
        if index < len(crops) - 1:
            canvas.paste(Image.new('L', (width, 2), 150), (0, y + DIVIDER // 2 - 1))
            y += DIVIDER
    return canvas


class SparxPages:
    """Headless browser with cached page models (one page per original Sparx file)."""

    def __init__(self, browser_path: str):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(executable_path=browser_path, headless=True)
        self._pages = {}

    def open(self, file: Path):
        key = str(file)
        if key not in self._pages:
            page = self._browser.new_page(viewport={'width': VIEWPORT_WIDTH, 'height': 900}, device_scale_factor=2)
            page.goto(file.resolve().as_uri())
            self._pages[key] = (page, page.evaluate(MODEL_JS))
        return self._pages[key]

    def close(self):
        self._browser.close()
        self._pw.stop()


def shoot(page, regions: list[dict], output: Path) -> dict:
    located = page.evaluate(LOCATE_JS, regions)
    if 'error' in located:
        return {'status': 'unavailable', 'reason': located['error']}
    texts = [r['text'] for r in located['regions']]
    if ve.leaks(texts):
        return {'status': 'unavailable', 'reason': 'the fragment would show internal references'}
    shot = output.with_suffix('.full.png')
    page.screenshot(path=str(shot), full_page=True)
    full = Image.open(shot).convert('L')
    crops = []
    for rect in merge_rects([{**r, 'x': r['x'] - (PAD_X if r['pad'] else 0), 'y': r['y'] - (PAD_Y if r['pad'] else 0),
                              'w': r['w'] + (2 * PAD_X if r['pad'] else 0), 'h': r['h'] + (2 * PAD_Y if r['pad'] else 0)} for r in located['regions']]):
        box = (max(0, int(rect['x'] * 2)), max(0, int(rect['y'] * 2)), min(full.width, int((rect['x'] + rect['w']) * 2)), min(full.height, int((rect['y'] + rect['h']) * 2)))
        crops.append(full.crop(box))
    image = stitch(crops)
    full.close()
    shot.unlink(missing_ok=True)
    image.save(output, dpi=(ve.DPI, ve.DPI))
    return {'status': 'captured', 'kind': 'browser-screenshot', 'capturedText': [' '.join(t.split()) for t in texts], 'widthPx': image.width, 'heightPx': image.height}


def capture_sparx(page_file: Path, regions: list[dict], output: Path, browser_path: str) -> dict:
    """Capture explicit regions of one Sparx page (compatibility entry point and test helper)."""
    pages = SparxPages(browser_path)
    try:
        page, _ = pages.open(page_file)
        return shoot(page, regions, output)
    finally:
        pages.close()


def capture_swagger(source_file: Path, spec: dict, output: Path) -> dict:
    lines = ve.yaml_fragments(source_file.read_text(encoding='utf-8'), spec['nodes'], spec.get('maxLines', loc.MAX_LINES), bool(spec.get('relative')))
    if not lines:
        return {'status': 'unavailable', 'reason': 'the requested node does not exist or exceeds the line limit'}
    if ve.leaks(lines):
        return {'status': 'unavailable', 'reason': 'the fragment would show internal references'}
    try:
        width, height = ve.render_text_image(lines, output)
    except RuntimeError as error:
        return {'status': 'unavailable', 'reason': str(error)}
    return {'status': 'captured', 'kind': 'source-lines-render', 'capturedText': lines, 'widthPx': width, 'heightPx': height}


def finalize(result: dict, output: Path, registry_dir: Path, source: Path, rel_source: str) -> dict:
    if result['status'] != 'captured':
        output.unlink(missing_ok=True)
        return result
    _, _, scale = ve.fit_cm(result['widthPx'], result['heightPx'])
    if scale < ve.MIN_SCALE:
        output.unlink(missing_ok=True)
        return {'status': 'unavailable', 'reason': f'illegible once fitted to the page margins (scale {scale:.2f})'}
    with Image.open(output) as image:
        gray = ve.is_grayscale(image)
    if not gray:
        with Image.open(output) as image:
            converted = image.convert('L')
        converted.save(output, dpi=(ve.DPI, ve.DPI))
    result.update(image=output.relative_to(registry_dir).as_posix(), imageSha256=sha(output), sourceFile=rel_source, sourceSha256=sha(source), fitScale=round(scale, 3))
    return result


def sparx_file(evidence: dict, root: Path):
    rel = (evidence.get('capture') or {}).get('file') or evidence.get('linkdoc') or evidence.get('page')
    return rel, (root / rel if rel else None)


def work_documents(registry: dict, repo: Path):
    manifest_rel = (registry.get('sourceCurrency') or {}).get('snapshotManifest')
    manifest_path = repo / manifest_rel if manifest_rel else None
    if not manifest_path or not manifest_path.is_file():
        return {}, {}
    work = repo / yaml.safe_load(manifest_path.read_bytes())['work']
    load = lambda name: yaml.safe_load((work / name).read_bytes()) if (work / name).is_file() else {}
    return load('openapi-spec.yml'), load('sparx-authoritative-endpoint-detail.yml')


def derive_swagger(finding: dict, swagger: 'loc.Swagger | None'):
    """First evidence pointer that resolves against the original contract (explicit capture specs win)."""
    reasons = []
    for index, evidence in enumerate(finding['evidence']['swagger']):
        if evidence.get('capture'):
            return {'evidenceIndex': index, 'spec': evidence['capture'], 'automatic': False}, None
        if swagger is None:
            return None, 'the original contract or its normalized snapshot is not available'
        derived = swagger.derive(evidence.get('pointer', ''))
        if 'reason' in derived:
            reasons.append(derived['reason'])
            continue
        return {'evidenceIndex': index, 'spec': derived, 'automatic': True}, None
    return None, '; '.join(dict.fromkeys(reasons)) or 'the finding has no Swagger evidence'


def derive_sparx(finding: dict, pages: 'SparxPages | None', root: Path, detail: dict, service: str):
    """Best-scoring evidence item (explicit capture specs win) with the regions to capture."""
    best, reasons = None, []
    for index, evidence in enumerate(finding['evidence']['sparx']):
        rel, file = sparx_file(evidence, root)
        if not rel or not file or not file.is_file():
            reasons.append('original Sparx page not found')
            continue
        if evidence.get('capture'):
            plan = {'regions': evidence['capture']['regions'], 'anchors': ['explicit capture'], 'score': 1000, 'automatic': False}
        else:
            if pages is None:
                return None, 'no browser available to take a real screenshot'
            _, model = pages.open(file)
            values = loc.row_values_for(detail, evidence['evidenceId']) if evidence.get('evidenceId') else None
            plan = {**loc.plan_sparx(finding, evidence, model, values, service), 'automatic': True}
        if 'regions' not in plan:
            reasons.append(plan['reason'])
            continue
        if best is None or plan['score'] > best['plan']['score']:
            best = {'evidenceIndex': index, 'rel': rel, 'file': file, 'plan': plan}
    if best:
        return best, None
    return None, '; '.join(dict.fromkeys(reasons)) or 'the finding has no Sparx evidence'


def run(registry_path: Path, repo: Path) -> dict:
    registry = yaml.safe_load(registry_path.read_bytes())
    registry_dir = registry_path.parent
    images = registry_dir / 'images'
    shutil.rmtree(images, ignore_errors=True)
    images.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    pages = SparxPages(browser) if browser else None
    sparx_root = repo / registry['sources']['sparxRoot']
    openapi_rel = registry['sources']['openapi']['path']
    normalized, detail = work_documents(registry, repo)
    swagger = loc.Swagger((repo / openapi_rel).read_text(encoding='utf-8'), normalized) if normalized and (repo / openapi_rel).is_file() else None
    summary = {'captured': 0, 'unavailable': 0, 'automatic': 0}
    try:
        for finding in registry['findings']:
            finding['visualEvidence'] = {}
            for source in ('sparx', 'swagger'):
                output = images / f'{finding["id"]}-{source}.png'
                try:
                    if source == 'sparx':
                        found, reason = derive_sparx(finding, pages, sparx_root, detail, registry['service'])
                        if found:
                            if pages is None:
                                raise RuntimeError('no browser available')
                            page, _ = pages.open(found['file'])
                            result = shoot(page, found['plan']['regions'], output)
                            origin, rel = found['file'], (sparx_root / found['rel']).relative_to(repo).as_posix()
                            derived = {'evidenceIndex': found['evidenceIndex'], 'file': found['rel'], 'regions': found['plan']['regions'], 'anchors': found['plan']['anchors'],
                                       'automatic': found['plan']['automatic']}
                    else:
                        found, reason = derive_swagger(finding, swagger)
                        if found:
                            origin, rel = repo / openapi_rel, openapi_rel
                            result = capture_swagger(origin, found['spec'], output)
                            derived = {'evidenceIndex': found['evidenceIndex'], 'nodes': found['spec']['nodes'], 'relative': bool(found['spec'].get('relative')),
                                       'maxLines': found['spec'].get('maxLines', loc.MAX_LINES), 'automatic': found['automatic']}
                    if not found:
                        result = {'status': 'unavailable', 'reason': reason}
                    else:
                        result = finalize(result, output, registry_dir, origin, rel)
                        if result['status'] == 'captured':
                            result['derivedSpec'] = derived
                except Exception as error:  # authenticity first: any failure keeps the finding text-only
                    output.unlink(missing_ok=True)
                    result = {'status': 'unavailable', 'reason': ('no browser available to take a real screenshot' if isinstance(error, RuntimeError) else f'capture failed: {type(error).__name__}')}
                finding['visualEvidence'][source] = result
                if result['status'] == 'captured':
                    summary['captured'] += 1
                    summary['automatic'] += bool(result['derivedSpec']['automatic'])
                else:
                    summary['unavailable'] += 1
    finally:
        if pages:
            pages.close()
    registry['visualEvidenceSummary'] = summary
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False, allow_unicode=True, width=200), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registry', type=Path)
    args = parser.parse_args()
    print(yaml.safe_dump(run(args.registry.resolve(), Path.cwd().resolve())))


if __name__ == '__main__':
    sys.exit(main())
