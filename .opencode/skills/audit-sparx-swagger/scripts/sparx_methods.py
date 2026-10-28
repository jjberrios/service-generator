"""Authoritative-branch Sparx method catalogue for route verification (read-only).

Reuses resolve_target_authority (TOC loading, page metadata). Lists every method owned by the target service in the
authoritative branch (including methods that did not match an OpenAPI route literally), with lifecycle status and the
«Invoca» relations of each method, so a route prefix difference or a caller from another service is never reported as
a missing operation.
"""
from pathlib import Path
import posixpath
import re
import sys

PARSE_SPARX = Path(__file__).resolve().parents[2] / 'parse-sparx' / 'scripts'
sys.path.insert(0, str(PARSE_SPARX))
import resolve_target_authority as ra  # noqa: E402

METHOD_NAME = re.compile(r'^([A-Z]+)-(/.*)$')
INVOCA_LINK = re.compile(r'<a href="([^"]+\.htm)">([^<]+)</a>\s*<br\s*/>\s*Actividad\s*«Invoca»')
INACTIVE_STATES = {'eliminado', 'obsoleto', 'deprecado', 'historico', 'baja', 'retirado', 'inactivo'}


def lifecycle(status):
    token = ra.fold(status or '').strip()
    if not token:
        return 'unknown'
    return 'inactive' if token in INACTIVE_STATES else 'active'


def collect(authority: dict, repo: Path) -> list[dict]:
    root = (repo / authority['target']['sourceRoot']).resolve()
    branch_id = authority['selection']['authoritativeBranchRootId']
    branch = next(b for b in authority['branches'] if b['branchRootId'] == branch_id)
    _, elements, _ = ra.load_toc(root / 'js' / 'data')
    by_page = {e['page'].replace('\\', '/'): e for e in elements if e['page']}
    by_own = {e['ownId']: e for e in elements if e['ownId']}
    rows = list(branch.get('sparxOnlyMethods') or []) + [op['sparxMethod'] for op in branch['operations'] if op.get('sparxMethod')]
    methods = []
    for row in rows:
        match = METHOD_NAME.match(row['name'])
        if not match:
            continue
        page = row['page'].replace('\\', '/')
        meta = ra.page_metadata(page, root)
        invokers = []
        page_file = root / page
        if page_file.is_file():
            raw = page_file.read_bytes().decode('utf-8', 'ignore')
            for href, label in INVOCA_LINK.findall(raw):
                target_page = posixpath.normpath(posixpath.join(posixpath.dirname(page), href))
                element = by_page.get(target_page)
                owner = by_own.get(element['parentId']) if element else None
                invokers.append({'name': label.strip(), 'page': target_page, 'guid': element['guid'] if element else None,
                                 'ownerService': owner['name'] if owner else None,
                                 'ownedByTargetService': bool(owner and owner['name'] == authority['target']['name'])})
        methods.append({'method': match.group(1), 'path': match.group(2), 'name': row['name'], 'guid': row.get('guid') or meta.get('uuid'), 'page': page,
                        'pageSha256': meta.get('sha256'), 'status': meta.get('status'), 'lifecycle': lifecycle(meta.get('status')), 'invokedVia': invokers})
    return sorted(methods, key=lambda m: (m['path'], m['method']))
