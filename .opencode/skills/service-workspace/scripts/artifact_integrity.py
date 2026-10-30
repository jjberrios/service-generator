"""Profile-neutral artifact integrity. No business, runtime or quality policy lives here."""
from contextlib import contextmanager
from fnmatch import fnmatch
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile

import file_protection as fp
from generation_context import load_mapping


class IntegrityError(ValueError):
    pass


def safe_path(root, relative):
    """Validate before opening anything, including parent symlinks/junction escapes."""
    root = Path(root)
    text = str(relative)
    path = PurePosixPath(text)
    if not text or not path.parts or '\\' in text or ':' in text or path.is_absolute() or '..' in path.parts or str(path) != text:
        raise IntegrityError(f'unsafe-artifact-path: {relative}')
    target = root / text
    if not target.resolve().is_relative_to(root.resolve()):
        raise IntegrityError(f'artifact-path-escape: {relative}')
    if target.resolve() != root.resolve().joinpath(*path.parts):
        raise IntegrityError(f'artifact-path-redirection: {relative}')
    for parent in [target, *target.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise IntegrityError(f'artifact-symlink: {relative}')
    return target


def protected(relative):
    return fnmatch(PurePosixPath(str(relative)).name, 'application*.properties')


def template_paths(root):
    """Declared, non-protected template paths; exclude before stat/open."""
    root = Path(root)
    manifest = load_mapping(safe_path(root, 'archetype.yml'))
    inventory = manifest.get('templateInventory', manifest.get('template_inventory'))
    if not isinstance(inventory, list):
        raise IntegrityError('archetype-inventory-required')
    paths = []
    for item in inventory:
        rel = item.get('path') if isinstance(item, dict) else item
        if not isinstance(rel, str):
            raise IntegrityError('invalid-archetype-inventory')
        rel = rel if rel.startswith('template/') else 'template/' + rel
        if not protected(rel):
            safe_path(root, rel)
            paths.append(rel.removeprefix('template/'))
    if len(paths) != len(set(paths)):
        raise IntegrityError('duplicate-archetype-inventory')
    return sorted(paths)


def archetype_hashes(root):
    """Versioned allowlist: manifest + declared templates; docs have a separate hash.

    Cache/local files never participate. Protected configuration is excluded before
    stat/open. Changes to the allowlist itself are bound by archetype.yml.
    """
    root = Path(root)
    paths = ['archetype.yml'] + ['template/' + path for path in template_paths(root)]
    def digest(files):
        chunks = []
        for rel in sorted(files):
            target = safe_path(root, rel)
            chunks.append(f'{rel}\0{hashlib.sha256(target.read_bytes()).hexdigest()}\n')
        return hashlib.sha256(('archetype-integrity-v1\n' + ''.join(chunks)).encode()).hexdigest()
    docs = [name for name in ('conventions.md', 'generation-rules.md', 'decisions.md')
            if safe_path(root, name).is_file()]
    return {'version': 1, 'technical': digest(paths), 'documentation': digest(docs)}


def write_atomic(target, data):
    """Unique same-directory staging; readers see old or new complete file bytes."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def service_lock(repo, service):
    if not service or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in service):
        raise IntegrityError('invalid-lock-service')
    target = safe_path(Path(repo), '.factory/.locks/' + service + '.lock')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise IntegrityError(f'service-busy: {service}; inspect stale locks explicitly, never discard automatically') from error
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        target.unlink()


def prepare(output, workspace, payload, *, reject_obsolete=False):
    """Whole-inventory preflight, even for identical manual/user-owned files."""
    output = Path(output)
    if output.is_symlink() or output.resolve() != output.parent.resolve() / output.name:
        raise IntegrityError('output-directory-escape')
    for rel in [*payload, fp.MANIFEST]:
        if protected(rel):
            raise IntegrityError(f'protected-configuration: {rel}')
        safe_path(output, rel)
    report_path = safe_path(workspace, 'materialization-report.yml')
    manifest_path = safe_path(output, fp.MANIFEST)
    untrusted_manifest = False
    if report_path.is_file() and manifest_path.is_file():
        recorded = load_mapping(report_path).get('manifestSha256')
        if recorded and recorded != hashlib.sha256(manifest_path.read_bytes()).hexdigest():
            untrusted_manifest = True
            auth = fp.load_list(Path(workspace) / 'overwrite-authorizations.yml', 'authorizations')
            decision = fp.decide('update', fp.classify(output, fp.MANIFEST, {}, [fp.MANIFEST], auth))
            if decision['decision'] == 'blocked-needs-authorization':
                raise fp.ProtectedFileError('generation manifest was modified; exact-content authorization required')
    try:
        previous = fp.generated_hashes(output)
    except (ValueError, TypeError, KeyError) as error:
        raise IntegrityError(f'invalid-generation-manifest: {error}') from error
    for rel in previous:
        if not protected(rel):
            safe_path(output, rel)
    if reject_obsolete and {rel for rel in previous if not protected(rel)} - set(payload):
        raise IntegrityError('obsolete-tracked-files: explicit migration required')
    decisions = fp.evaluate(output, [{'path': p, 'action': 'update'} for p in [*payload, fp.MANIFEST]], workspace)
    if untrusted_manifest:
        # Authorization to replace metadata is NOT authorization to adopt every
        # file described by that metadata. Require each existing payload file's
        # own exact-content authorization during recovery.
        owned = fp.load_list(Path(workspace) / 'user-owned-files.yml', 'patterns')
        authorizations = fp.load_list(Path(workspace) / 'overwrite-authorizations.yml', 'authorizations')
        decisions = [fp.decide('update', fp.classify(output, p, {}, owned, authorizations)) for p in payload] + decisions[-1:]
    blocked = fp.blocked(decisions)
    if blocked:
        error = fp.ProtectedFileError(str(blocked))
        error.details = {'blocked': blocked}
        raise error
    changed = {p: data for p, data in payload.items()
               if not (Path(output) / p).is_file() or (Path(output) / p).read_bytes() != data}
    return changed, sorted(set(payload) - set(changed))


def publish(output, workspace, payload, manifest):
    """Recheck the entire payload before any write, then guard each atomic write.

    Manifest is the commit marker and is always written last. This is per-file
    atomic, not a filesystem-wide transaction; interrupted runs are detected by
    manifest hashes and are not silently adopted.
    """
    changed, _ = prepare(output, workspace, payload)
    fp.guard_write(output, fp.MANIFEST, workspace)
    for rel, data in sorted(changed.items()):
        if fp.guard_write(output, rel, workspace):
            write_atomic(safe_path(output, rel), data)
    if fp.guard_write(output, fp.MANIFEST, workspace):
        write_atomic(safe_path(output, fp.MANIFEST), manifest)
