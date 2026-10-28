"""Validate the audit registry and its DOCX report (read-only checks; visual review is reported honestly)."""
from pathlib import Path
import argparse
import re
import shutil
import subprocess
import sys
import zipfile
import yaml
from docx import Document

import source_currency as currency
import visual_evidence as ve
import evidence_locator as loc
import capture_evidence
from compare_sparx_swagger import CATEGORIES, UNVERIFIED_CATEGORIES, SATISFACTORY, NON_NORMATIVE_SWAGGER

FORBIDDEN_PHRASES = ('objetivo del documento', 'alcance', 'metodología', 'metodologia', 'propósito', 'proposito', 'introducción', 'introduccion', 'conclusión', 'conclusion',
                     'el presente documento', 'este documento')
REQUIRED_LABELS = ('ID', 'Operación', 'Elemento afectado', 'Sparx', 'Swagger', 'Inconsistencia detectada', 'Severidad')
# Internal traceability data (kept only in findings.yml) must never appear in the Word report.
INTERNAL_REFERENCE = ve.INTERNAL_REFERENCE
COLOR_ATTR = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val'


def registry_checks(registry: dict, expected_service: str) -> dict:
    findings = registry.get('findings') or []
    keys = [f['key'] for f in findings]
    ids = [f['id'] for f in findings]
    branches = {e.get('branch') for f in findings for e in f['evidence']['sparx'] if e.get('branch')}
    sparx_ok = all(f['evidence']['sparx'] and all(any(e.get(k) for k in ('guid', 'page', 'authorityFile', 'evidenceId')) for e in f['evidence']['sparx']) for f in findings)
    swagger_ok = all(f['evidence']['swagger'] and all(e.get('method') and e.get('path') and e.get('pointer') for e in f['evidence']['swagger']) for f in findings)
    operations = {(o['method'], o['path']) for o in registry.get('operationsAudited') or []}
    unverified = registry.get('unverified') or []
    return {
        'everyFindingHasAVerifiedCategory': all(f.get('category') in CATEGORIES for f in findings),
        'contradictionsRestOnNormativeSwaggerEvidence': all(any(not NON_NORMATIVE_SWAGGER.search(e.get('pointer', '')) for e in f['evidence']['swagger'])
                                                              for f in findings if f.get('category') == 'contradiccion-verificada'),
        'unverifiedItemsAreCategorizedAndNeverSatisfactory': all(u.get('category') in UNVERIFIED_CATEGORIES and not SATISFACTORY.search(f'{u.get("topic")} {u.get("reason")}') for u in unverified),
        'sourceCurrencyRecordedAsCurrent': (registry.get('sourceCurrency') or {}).get('status') == 'current',
        'registryBelongsToRequestedService': registry.get('service') == expected_service,
        'everyFindingHasSparxEvidence': sparx_ok,
        'everyFindingHasSwaggerEvidence': swagger_ok,
        'noDuplicateFindings': len(keys) == len(set(keys)) and len(ids) == len(set(ids)),
        'singleSparxBranch': len(branches) <= 1,
        'findingsBelongToAuditedOperations': all((f['operation']['method'], f['operation']['path']) in operations for f in findings),
        'allFindingFieldsPresent': all(all(f.get(k) for k in ('id', 'operation', 'element', 'sparx', 'swagger', 'inconsistency', 'severity')) for f in findings),
        'readOnlyAudit': registry.get('readOnlyAudit') is True,
    }


def currency_checks(registry: dict, repo: Path) -> dict:
    """Re-verify against the live inputs that the Swagger file, the Sparx hierarchy, the snapshots and every cited Sparx page are unchanged."""
    manifest_path = repo / registry['sourceCurrency']['snapshotManifest']
    if not manifest_path.is_file():
        return {'sourcesStillCurrent': False}
    manifest = yaml.safe_load(manifest_path.read_bytes())
    live = currency.verify(manifest, repo)
    root = repo / registry['sources']['sparxRoot']
    pages = registry['sourceCurrency'].get('citedPageHashes') or {}
    return {'sourcesStillCurrent': live['status'] == 'current' and manifest['service'] == registry['service'],
            'citedSparxPagesUnchanged': all((root / page).is_file() and currency.sha(root / page) == digest for page, digest in pages.items()),
            'registryMatchesSnapshotOpenapi': registry['sources']['openapi']['sha256'] == manifest['openapi']['sha256']}


def captured_images(registry: dict) -> list[tuple[dict, str, dict]]:
    return [(f, source, f['visualEvidence'][source]) for f in registry.get('findings') or [] for source in ('sparx', 'swagger')
            if ((f.get('visualEvidence') or {}).get(source) or {}).get('status') == 'captured']


def normalized(text: str) -> str:
    return re.sub(r'\s+', '', text)


def visual_checks(registry: dict, docx_path: Path, registry_dir: Path, repo: Path) -> dict:
    """Authenticity and presentation of the images: grayscale, inside the margins, readable, no internal references, verbatim sources."""
    from PIL import Image
    import html
    import io
    captured = captured_images(registry)
    document = Document(str(docx_path))
    section = document.sections[0]
    usable = section.page_width - section.left_margin - section.right_margin
    shapes = document.inline_shapes
    checks = {'imageCountMatchesRegistry': len(shapes) == len(captured)}
    files_ok = hashes_ok = gray_ok = fit_ok = legible_ok = clean_ok = verbatim_ok = source_ok = labelled_ok = rederived_ok = related_ok = True
    normalized_spec, _ = capture_evidence.work_documents(registry, repo) if (registry.get('sourceCurrency') or {}).get('snapshotManifest') else ({}, {})
    for (finding, source, visual), shape in zip(captured, shapes):
        path = registry_dir / visual['image']
        files_ok &= path.is_file()
        if not path.is_file():
            continue
        hashes_ok &= currency.sha(path) == visual['imageSha256']
        with Image.open(path) as image:
            gray_ok &= ve.is_grayscale(image)
            natural_cm = image.width / ve.DPI * 2.54
            shown_cm = shape.width / 360000
            fit_ok &= shape.width <= usable + 1000 and shape.height / 360000 <= ve.MAX_HEIGHT_CM + 0.05
            legible_ok &= shown_cm / natural_cm >= ve.MIN_SCALE - 0.01
        clean_ok &= not ve.leaks(visual['capturedText'])
        origin = repo / visual['sourceFile']
        source_ok &= origin.is_file() and currency.sha(origin) == visual['sourceSha256']
        if not origin.is_file():
            continue
        spec = visual.get('derivedSpec') or {}
        if source == 'swagger':
            text = origin.read_text(encoding='utf-8')
            verbatim_ok &= ve.yaml_fragments(text, spec['nodes'], spec.get('maxLines', 40), bool(spec.get('relative'))) == visual['capturedText']
            if spec.get('automatic') and normalized_spec:
                derived = loc.Swagger(text, normalized_spec).derive(finding['evidence']['swagger'][spec['evidenceIndex']].get('pointer', ''))
                rederived_ok &= derived.get('nodes') == spec['nodes'] and bool(derived.get('relative')) == bool(spec.get('relative'))
        else:
            plain = normalized(html.unescape(re.sub(r'<[^>]+>', '', origin.read_bytes().decode('utf-8', 'ignore'))))
            verbatim_ok &= all(normalized(t).replace('\u2022', '') in plain for t in visual['capturedText'])
            rederived_ok &= bool(spec.get('regions')) and spec.get('evidenceIndex') is not None
        finding_words = {w for t in (finding['element'], finding['sparx']['text'], finding['swagger']['text'], finding['inconsistency']) for w in loc.words(t) if len(w) >= 4}
        captured_words = {w for t in visual['capturedText'] for w in loc.words(t) if len(w) >= 4}
        related_ok &= bool(finding_words & captured_words)
    bold = [p.text for p in document.paragraphs if p.runs and all(r.bold for r in p.runs)]
    labelled_ok = bold.count('Sparx') == sum(1 for _, s_, _ in captured if s_ == 'sparx') and bold.count('Swagger') == sum(1 for _, s_, _ in captured if s_ == 'swagger')
    checks.update({'imageFilesExist': files_ok, 'imagesMatchRecordedHashes': hashes_ok, 'imagesAreGrayscale': gray_ok, 'imagesInsideMargins': fit_ok,
                   'imagesLegible': legible_ok, 'imagesShowNoInternalReferences': clean_ok, 'imageSourcesUnchanged': source_ok,
                   'imageFragmentsMatchOriginalSources': verbatim_ok, 'captureSpecsReproducibleFromFindings': rederived_ok, 'imagesRelateToTheirFinding': related_ok, 'imagesLabelledSparxAndSwagger': labelled_ok,
                   'unavailableEvidenceStaysTextOnly': all(((f.get('visualEvidence') or {}).get(src) or {}).get('status') in (None, 'captured', 'unavailable')
                                                            and (((f.get('visualEvidence') or {}).get(src) or {}).get('status') != 'unavailable' or 'image' not in f['visualEvidence'][src])
                                                            for f in registry.get('findings') or [] for src in ('sparx', 'swagger'))})
    return checks


def all_text(document) -> list[str]:
    texts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                texts.extend(p.text for p in cell.paragraphs)
    return texts


def docx_checks(registry: dict, docx_path: Path, expected_service: str) -> dict:
    checks = {}
    try:
        document = Document(str(docx_path))
        checks['docxOpens'] = True
    except Exception:
        return {'docxOpens': False}
    with zipfile.ZipFile(docx_path) as archive:
        xml = {name: archive.read(name).decode('utf-8', 'ignore') for name in archive.namelist() if name.endswith('.xml')}
    body = xml['word/document.xml']
    colors = set(re.findall(r'<w:color [^>]*w:val="([^"]+)"', body))
    style_colors = set(re.findall(r'<w:color [^>]*w:val="([^"]+)"', xml.get('word/styles.xml', '')))
    theme_colors = re.findall(r'w:themeColor="', body + xml.get('word/styles.xml', ''))
    checks['allTextBlack'] = colors <= {'000000'} and style_colors <= {'000000'} and not theme_colors
    checks['everyRunExplicitlyBlackCalibri11'] = all(
        run.font.color is not None and str(run.font.color.rgb) == '000000' and run.font.name == 'Calibri' and run.font.size.pt == 11
        for paragraph in [p for p in document.paragraphs] + [p for t in document.tables for r in t.rows for c in r.cells for p in c.paragraphs] for run in paragraph.runs)
    checks['noFillOrShading'] = not re.search(r'<w:shd [^>]*w:fill="(?!auto|FFFFFF)', body)
    section = document.sections[0]
    checks['noHeaderFooterContent'] = (not any(p.text.strip() for p in section.header.paragraphs) and not any(p.text.strip() for p in section.footer.paragraphs)
                                       and not any(n.startswith(('word/header', 'word/footer')) and re.search(r'<w:t[ >]', xml[n]) for n in xml))
    checks['noPageNumberFields'] = not re.search(r'PAGE|NUMPAGES|w:fldSimple|w:fldChar', body)
    checks['onlyAuthenticEvidenceImages'] = len([n for n in zipfile.ZipFile(docx_path).namelist() if n.startswith('word/media/')]) == len(captured_images(registry))
    texts = all_text(document)
    lowered = '\n'.join(texts).lower()
    checks['noGenericIntroductionsOrSections'] = not any(phrase in lowered for phrase in FORBIDDEN_PHRASES)
    first = next((t for t in texts if t.strip()), '')
    findings = registry.get('findings') or []
    checks['startsDirectlyWithFindings'] = (first == 'No se detectaron inconsistencias verificables.') if not findings else bool(re.match(r'^[A-Z]+ /', first))
    checks['noCoverPage'] = 'w:br w:type="page"' not in body
    cells = [c.text for t in document.tables for r in t.rows for c in r.cells]
    checks['everyFindingHasItsTable'] = len(document.tables) == len(findings)
    bold_lines = [p.text for p in document.paragraphs if p.runs and all(r.bold for r in p.runs)]
    groups = {(f['operation']['method'], f['operation']['path'], f['category']) for f in findings}
    labels = {'contradiccion-verificada': 'Contradicciones verificadas', 'diferencia-documental': 'Diferencias documentales'}
    checks['categorySubheadingsMatchFindings'] = all(bold_lines.count(label) == sum(1 for g in groups if g[2] == cat) for cat, label in labels.items())
    checks['unverifiedSectionOnlyWhenNeeded'] = (('No verificado' in bold_lines) == bool(registry.get('unverified')))
    blob = '\n'.join(cells)
    checks['tablesKeepAllInformation'] = all(
        f['id'] in blob and f['element'] in blob and f['sparx']['text'] in blob and f['swagger']['text'] in blob and f['inconsistency'] in blob and f['severity'] in blob
        and (f['operation']['method'] + ' ' + f['operation']['path']) in blob for f in findings)
    checks['tablesUseRequiredFieldsInBold'] = all(
        [t.rows[0].cells[0].text, t.rows[0].cells[2].text] == ['ID', 'Severidad'] and [r.cells[0].text for r in t.rows[1:]] == list(REQUIRED_LABELS[1:6])
        and all(run.bold for c in (t.rows[0].cells[0], t.rows[0].cells[2]) + tuple(r.cells[0] for r in t.rows[1:]) for p in c.paragraphs for run in p.runs) for t in document.tables)
    checks['noEvidenceFieldInTables'] = not re.search(r'\bEvidencias?\b', blob) and all(len(t.rows) == 1 + len(REQUIRED_LABELS[1:6]) for t in document.tables)
    checks['noInternalReferencesInDocument'] = not [t for t in texts if INTERNAL_REFERENCE.search(t)]
    checks['tablesFixedLayoutAndNeverSplitRows'] = all('w:tblLayout w:type="fixed"' in t._tbl.xml and t._tbl.xml.count('<w:cantSplit') == len(t.rows) for t in document.tables)
    widths_ok = True
    page = section.page_width - section.left_margin - section.right_margin
    for table in document.tables:
        total = sum(c.width for c in table.rows[0].cells if c.width)
        widths_ok &= total <= page + 1000
    checks['tablesFitPageWidth'] = widths_ok
    checks['reportMentionsOnlyRequestedService'] = (registry.get('service') == expected_service and document.core_properties.title == expected_service)
    return checks


def visual_review(docx_path: Path) -> dict:
    """Render only when LibreOffice is available; never claim a visual pass otherwise."""
    soffice = shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        return {'status': 'not-executed', 'reason': 'No renderer (LibreOffice/soffice) available; pages were not visually inspected.'}
    out = docx_path.parent / '.render'
    out.mkdir(exist_ok=True)
    done = subprocess.run([soffice, '--headless', '--convert-to', 'pdf', '--outdir', str(out), str(docx_path)], capture_output=True, text=True, timeout=180)
    pdf = out / (docx_path.stem + '.pdf')
    if done.returncode != 0 or not pdf.exists():
        return {'status': 'not-executed', 'reason': 'Renderer failed: ' + (done.stderr or done.stdout)[:200]}
    return {'status': 'rendered-pdf-requires-manual-inspection', 'pdf': str(pdf), 'note': 'PDF generated; page images were not inspected automatically.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--docx', type=Path, required=True)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    registry = yaml.safe_load(args.registry.read_bytes())
    checks = {**registry_checks(registry, args.service), **currency_checks(registry, Path.cwd()), **docx_checks(registry, args.docx, args.service),
              **visual_checks(registry, args.docx, args.registry.parent, Path.cwd())}
    result = {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks, 'visualReview': visual_review(args.docx) if args.render else {'status': 'not-executed', 'reason': 'Not requested'}}
    print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
