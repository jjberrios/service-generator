"""Currency (vigencia) of the audited sources: the Swagger file AND the Sparx export.

A snapshot manifest records, at snapshot time, the sha256 of the OpenAPI source, of every Sparx hierarchy (TOC) file, of
every snapshot artifact and, per cited page, the page sha256. `verify` recomputes them from the live inputs, so a changed
or replaced source makes the audit stale instead of silently mixing old extractions with new sources.
"""
from pathlib import Path
import hashlib
import sys

PARSE_SPARX = Path(__file__).resolve().parents[2] / 'parse-sparx' / 'scripts'
sys.path.insert(0, str(PARSE_SPARX))
import resolve_target_authority as ra  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sparx_state(root: Path) -> dict:
    _, _, hashes = ra.load_toc(Path(root) / 'js' / 'data')
    return hashes


def verify(manifest: dict, repo: Path, workspace: Path | None = None) -> dict:
    """Return {'status': 'current'|'stale', 'checks': {...}, 'stale': [reasons]}."""
    checks, reasons = {}, []

    def record(name, ok, why):
        checks[name] = bool(ok)
        if not ok:
            reasons.append(why)

    openapi = repo / manifest['openapi']['path']
    record('openapiSourceUnchanged', openapi.is_file() and sha(openapi) == manifest['openapi']['sha256'],
           f'El archivo Swagger {manifest["openapi"]["path"]} cambió o no existe desde el snapshot.')
    root = repo / manifest['sparx']['root']
    live = sparx_state(root) if (root / 'js' / 'data').is_dir() else {}
    record('sparxHierarchyUnchanged', live == manifest['sparx']['tocFiles'],
           f'La jerarquía de la exportación Sparx {manifest["sparx"]["root"]} cambió o no existe desde el snapshot.')
    # Snapshots kept inside a service workspace (.factory/services/<service>) are addressed relative to that workspace.
    work = (workspace if (manifest.get('workspaceRelative') and workspace) else repo) / manifest['work']
    for name, digest in manifest['artifacts'].items():
        record(f'artifact:{name}', (work / name).is_file() and sha(work / name) == digest, f'El snapshot {name} fue modificado o falta.')
    for page, digest in (manifest.get('pages') or {}).items():
        record(f'page:{page}', (root / page).is_file() and sha(root / page) == digest, f'La página Sparx {page} cambió o no existe desde el snapshot.')
    return {'status': 'current' if not reasons else 'stale', 'checks': checks, 'stale': reasons}
