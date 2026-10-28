"""Non destructive migration of existing artifacts into per-service workspaces.

  migrate_archived_run(repo, archive_dir, service)  copy an archived run (e.g. .factory/archive/dom-document-mailing-info-run/) into
                                                    .factory/services/<service>/ after verifying that it belongs to that service
  migrate_root_active(repo)                         copy the artifacts that sit directly in .factory/ for the active service of the root
                                                    checkpoint, only those that can be identified with certainty as belonging to it

Nothing is deleted, moved or rewritten: sources stay untouched (their hashes are re-verified), existing destination files are never overwritten
(a different file at the destination aborts the migration), content is copied byte for byte, and no decision or checkpoint is invented. Provenance
paths inside artifacts keep their `.factory/...` form, which is exactly how the sandbox runner presents a workspace to the pipeline scripts.
"""
from pathlib import Path
import datetime
import hashlib
import shutil
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workspace as wsm  # noqa: E402

SKIP_DIRS = {'__pycache__'}
SKIP_SUFFIXES = {'.pyc'}
ROOT_ARTIFACTS = ('openapi-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'sparx-nonauthoritative-evidence.yml', 'sparx-spec.yml',
                  'service-spec.yml', 'sparx-reviewed-decisions.yml', 'full-planning-input.yml', 'generation-parameters.yml', 'implementation-plan.yml')


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path: Path):
    return yaml.safe_load(Path(path).read_bytes()) if Path(path).is_file() else None


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class MigrationError(RuntimeError):
    pass


def identity_of(directory: Path, name: str):
    """Service named by one artifact of a legacy run (None when the artifact does not state it)."""
    data = load(directory / name)
    if not isinstance(data, dict):
        return None
    if name == 'service-spec.yml':
        return (data.get('service') or {}).get('name')
    if name == 'implementation-plan.yml':
        return (data.get('service') or {}).get('name')
    if name == 'generation-parameters.yml':
        return data.get('service')
    if name == 'full-planning-input.yml':
        return (data.get('target') or {}).get('service')
    if name == 'openapi-spec.yml':
        return (data.get('service') or {}).get('title')
    if name == 'sparx-target-authority.yml':
        return (data.get('target') or {}).get('name')
    return None


def verified_identities(directory: Path) -> dict:
    return {n: i for n in ('service-spec.yml', 'implementation-plan.yml', 'generation-parameters.yml', 'full-planning-input.yml', 'openapi-spec.yml', 'sparx-target-authority.yml')
            if (i := identity_of(directory, n))}


def files_of(root: Path):
    for path in sorted(Path(root).rglob('*')):
        if path.is_file() and not (set(path.relative_to(root).parts) & SKIP_DIRS) and path.suffix not in SKIP_SUFFIXES:
            yield path


def copy_tree(source: Path, destination: Path, relative_files=None) -> list[dict]:
    rows = []
    items = [(source / r, r) for r in relative_files] if relative_files is not None else [(p, p.relative_to(source)) for p in files_of(source)]
    for src, rel in items:
        dst = destination / rel
        if dst.exists():
            if sha(dst) != sha(src):
                raise MigrationError(f'destination already contains a different file: {rel}')
            rows.append({'path': Path(rel).as_posix(), 'sha256': sha(src), 'status': 'already-present'})
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if sha(dst) != sha(src):
            raise MigrationError(f'copy verification failed: {rel}')
        rows.append({'path': Path(rel).as_posix(), 'sha256': sha(src), 'status': 'copied'})
    return rows


def write_manifest(ws: 'wsm.Workspace', name: str, body: dict):
    target = ws.dir / 'migration' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f'{target.stem}-{now().replace(":", "")}{target.suffix}')
    target.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=200), encoding='utf-8')
    return target


def migrate_archived_run(repo: Path, archive_dir: Path, service: str) -> dict:
    repo, archive_dir = Path(repo).resolve(), Path(archive_dir).resolve()
    ws = wsm.Workspace(repo, service)
    if not archive_dir.is_dir():
        raise MigrationError(f'archive not found: {archive_dir}')
    identities = verified_identities(archive_dir)
    if not identities or set(identities.values()) != {service}:
        raise MigrationError(f'the archive cannot be identified with certainty as {service}: {identities}')
    before = {p.relative_to(archive_dir).as_posix(): sha(p) for p in files_of(archive_dir)}
    ws.ensure()
    # The archived checkpoint is not copied into the workspace root (it is stored under migration/ below) so a later, advanced checkpoint never conflicts with a rerun.
    rows = copy_tree(archive_dir, ws.dir, [p.relative_to(archive_dir) for p in files_of(archive_dir) if p.relative_to(archive_dir).as_posix() != 'service-generation-state.yml'])
    after = {p.relative_to(archive_dir).as_posix(): sha(p) for p in files_of(archive_dir)}
    if before != after:
        raise MigrationError('the archive changed during migration')
    # The archived checkpoint is kept verbatim; the workspace checkpoint only records what the files themselves prove.
    archived_state = archive_dir / 'service-generation-state.yml'
    legacy_state_copy = ws.dir / 'migration' / 'archived-service-generation-state.yml'
    legacy_state_copy.parent.mkdir(parents=True, exist_ok=True)
    if archived_state.is_file() and not legacy_state_copy.exists():
        shutil.copy2(archived_state, legacy_state_copy)
    spec = load(ws.dir / 'service-spec.yml') or {}
    plan = load(ws.dir / 'implementation-plan.yml') or {}
    readiness = spec.get('readiness') or {}
    state = {'schemaVersion': 1, 'status': 'legacy-migrated', 'targetService': service, 'runId': None,
             'inputs': {'openapi': {'path': ((load(ws.dir / 'openapi-spec.yml') or {}).get('source') or {}).get('path'), 'sha256': ((load(ws.dir / 'openapi-spec.yml') or {}).get('source') or {}).get('sha256')},
                        'sparxExport': {'path': ((load(ws.dir / 'sparx-target-authority.yml') or {}).get('target') or {}).get('sourceRoot')}},
             'archetype': (plan.get('inputs') or {}).get('archetype') or {'path': 'archetypes/claro-spring-ms/v1.0.0'},
             'completedPhases': [], 'currentPhase': None,
             'legacyEvidence': {'note': 'Recovered from an archived run that predates the consistency gate and per-service workspaces; phases are not asserted.',
                                'sourceArchive': archive_dir.relative_to(repo).as_posix(), 'serviceSpecPresent': bool(spec), 'implementationPlanMode': (plan.get('plan') or {}).get('mode'),
                                'readiness': {k: readiness.get(k) for k in ('strictImplementationReady', 'functionalCodeGenerationReady') if k in readiness},
                                'humanDecisionsPresent': (ws.dir / 'sparx-reviewed-decisions.yml').is_file()},
             'consistencyGate': {'status': 'NOT_EVALUATED', 'note': 'Must be evaluated and cleared before any further planning or generation.'},
             'reviewedDecisions': {'path': '.factory/sparx-reviewed-decisions.yml', 'sha256': sha(ws.dir / 'sparx-reviewed-decisions.yml') if (ws.dir / 'sparx-reviewed-decisions.yml').is_file() else None},
             'blockers': [], 'pendingQuestion': None}
    if not (ws.dir / 'migration' / 'workspace-state-written').exists():
        # The archived idle state (targetService: null) is replaced in the workspace root by the identified legacy checkpoint; the original stays in migration/ and in the archive.
        ws.write_state(state)
        (ws.dir / 'migration' / 'workspace-state-written').write_text(now(), encoding='utf-8')
    manifest = write_manifest(ws, 'archived-run-migration.yml', {'service': service, 'migratedAt': now(), 'source': archive_dir.relative_to(repo).as_posix(), 'identifiedBy': identities,
                                                              'files': rows, 'copied': sum(r['status'] == 'copied' for r in rows), 'sourceUnchanged': True})
    return {'service': service, 'files': len(rows), 'copied': sum(r['status'] == 'copied' for r in rows), 'manifest': manifest.relative_to(repo).as_posix()}


def migrate_root_active(repo: Path) -> dict:
    """Copy the root-level artifacts of the active service of .factory/service-generation-state.yml when each one can be tied to it."""
    repo = Path(repo).resolve()
    factory = repo / '.factory'
    state = load(factory / 'service-generation-state.yml') or {}
    service = state.get('targetService')
    if not service:
        return {'service': None, 'migrated': [], 'skipped': [], 'reason': 'the root checkpoint has no active service'}
    ws = wsm.Workspace(repo, service)
    verified, skipped = [], []
    authority = factory / 'sparx-target-authority.yml'
    for name in ROOT_ARTIFACTS:
        path = factory / name
        if not path.is_file():
            continue
        identity = identity_of(factory, name)
        if identity is not None:
            ok = identity == service
        elif name in ('sparx-authoritative-endpoint-detail.yml', 'sparx-nonauthoritative-evidence.yml') and authority.is_file():
            ok = (load(path).get('authority') or {}).get('sha256') == sha(authority) and identity_of(factory, 'sparx-target-authority.yml') == service
        else:
            ok = False
        (verified if ok else skipped).append(name)
    ws.ensure()
    rows = copy_tree(factory, ws.dir, relative_files=verified)
    if not ws.state_file.is_file():
        rows += copy_tree(factory, ws.dir, relative_files=['service-generation-state.yml'])
    else:
        rows.append({'path': 'service-generation-state.yml', 'sha256': sha(factory / 'service-generation-state.yml'), 'status': 'not-copied-workspace-already-has-a-checkpoint'})
    manifest = write_manifest(ws, 'root-migration.yml', {'service': service, 'migratedAt': now(), 'source': '.factory', 'files': rows, 'skippedNotIdentifiable': skipped,
                                                         'rootFilesLeftInPlace': True, 'note': 'Root files are copied, not moved; the pipeline now reads only the workspace.'})
    return {'service': service, 'migrated': [r['path'] for r in rows if r['status'] != 'not-copied-workspace-already-has-a-checkpoint'], 'skipped': skipped, 'manifest': manifest.relative_to(repo).as_posix()}
