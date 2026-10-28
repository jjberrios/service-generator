"""Protection of existing output files against accidental overwrite (reusable by every materializer).

A file under output/<service>/ is classified, without comparing it to the archetype (a difference from the archetype is NOT an error):
  absent               -> may be created
  generated-unmodified -> content hash equals the hash recorded in the generation manifest -> may be updated/removed
  user-modified        -> exists and differs from the recorded generated hash   -> never overwritten without an authorization for that exact content
  untracked-existing   -> exists but was never generated (not in the manifest)  -> treated as manual work, same protection
  user-owned           -> listed by the user in the service workspace (user-owned-files.yml) -> same protection
  excluded             -> local environment configuration (application*.properties): NEVER read, analyzed, reported or written
An overwrite authorization (overwrite-authorizations.yml in the workspace) is bound to the sha256 of the current content; if the user edits the file
again the authorization no longer applies. Existing content is always preserved (the guard only decides, it never writes).
"""
from fnmatch import fnmatch
from pathlib import Path
import datetime
import hashlib
import yaml

EXCLUDED_PATTERNS = ('src/main/resources/application*.properties',)
MANIFEST = '.generation-manifest.yml'
WRITE_ACTIONS = {'create', 'update', 'remove'}

ABSENT, GENERATED, MODIFIED, UNTRACKED, USER_OWNED, EXCLUDED = ('absent', 'generated-unmodified', 'user-modified', 'untracked-existing', 'user-owned', 'excluded')


class ProtectedFileError(RuntimeError):
    pass


def norm(rel) -> str:
    text = str(rel).replace('\\', '/')
    while text.startswith('./'):
        text = text[2:]                          # only a leading './' segment; dot files such as .gitignore keep their name
    return text.lstrip('/')


def is_excluded(rel: str) -> bool:
    rel = norm(rel)
    return any(fnmatch(rel, pattern) for pattern in EXCLUDED_PATTERNS)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generated_hashes(output_dir: Path) -> dict:
    """Hashes recorded by the previous generation (the manifest rows); empty when the service was never generated."""
    manifest = Path(output_dir) / MANIFEST
    if not manifest.is_file():
        return {}
    rows = (yaml.safe_load(manifest.read_bytes()) or {}).get('fileInventory') or []
    return {norm(r['path']): r['sha256'] for r in rows if isinstance(r, dict) and r.get('path') and r.get('sha256')}


def load_list(path: Path, key: str) -> list:
    return ((yaml.safe_load(Path(path).read_bytes()) or {}).get(key) or []) if Path(path).is_file() else []


def classify(output_dir: Path, rel: str, recorded: dict, user_owned: list, authorizations: list) -> dict:
    rel = norm(rel)
    if is_excluded(rel):
        return {'path': rel, 'state': EXCLUDED}            # content is deliberately never opened
    target = Path(output_dir) / rel
    if not target.is_file():
        return {'path': rel, 'state': ABSENT}
    current = sha(target)
    owned = any(fnmatch(rel, norm(p)) for p in user_owned)
    if owned:
        state = USER_OWNED
    elif rel not in recorded:
        state = UNTRACKED
    elif recorded[rel] != current:
        state = MODIFIED
    else:
        state = GENERATED
    authorized = any(norm(a.get('path', '')) == rel and a.get('currentSha256') == current for a in authorizations)
    return {'path': rel, 'state': state, 'currentSha256': current, 'overwriteAuthorized': authorized}


def decide(action: str, info: dict) -> dict:
    state = info['state']
    if action not in WRITE_ACTIONS:
        return {**info, 'action': action, 'decision': 'keep'}
    if state == EXCLUDED:
        return {**info, 'action': action, 'decision': 'skip-excluded', 'reason': 'local environment configuration is never touched by the generator'}
    if action == 'create' and state == ABSENT:
        return {**info, 'action': action, 'decision': 'write'}
    if state in (ABSENT, GENERATED):
        return {**info, 'action': action, 'decision': 'write'}
    if info.get('overwriteAuthorized'):
        return {**info, 'action': action, 'decision': 'write', 'reason': 'overwrite explicitly authorized for this exact content'}
    return {**info, 'action': action, 'decision': 'blocked-needs-authorization',
            'reason': f'{state}: manual content is preserved; ask the user whether it may be replaced'}


def evaluate(output_dir: Path, planned: list[dict], ws_dir: Path) -> list[dict]:
    recorded = generated_hashes(output_dir)
    owned = load_list(Path(ws_dir) / 'user-owned-files.yml', 'patterns')
    authorizations = load_list(Path(ws_dir) / 'overwrite-authorizations.yml', 'authorizations')
    out = []
    for entry in planned:
        rel = norm(entry['path'])
        if rel == MANIFEST:
            out.append({'path': rel, 'state': GENERATED, 'action': entry['action'], 'decision': 'write' if entry['action'] in WRITE_ACTIONS else 'keep'})
            continue
        out.append(decide(entry['action'], classify(output_dir, rel, recorded, owned, authorizations)))
    return out


def blocked(decisions: list[dict]) -> list[dict]:
    return [d for d in decisions if d['decision'] == 'blocked-needs-authorization']


def guard_write(output_dir: Path, rel: str, ws_dir: Path) -> bool:
    """For materializers: True when the file may be written, False when it must be skipped (excluded); raises when authorization is needed."""
    decision = evaluate(output_dir, [{'path': rel, 'action': 'update'}], ws_dir)[0]
    if decision['decision'] == 'skip-excluded':
        return False
    if decision['decision'] == 'blocked-needs-authorization':
        raise ProtectedFileError(f'{decision["path"]}: {decision["reason"]}')
    return True


def authorize_overwrite(output_dir: Path, rel: str, ws_dir: Path, authorized_by: str, reason: str) -> dict:
    rel = norm(rel)
    if is_excluded(rel):
        raise ProtectedFileError(f'{rel} is local environment configuration and cannot be authorized for generation')
    target = Path(output_dir) / rel
    if not target.is_file():
        raise ProtectedFileError(f'{rel} does not exist; nothing to authorize')
    if not str(authorized_by).strip() or str(authorized_by).strip().lower() in ('agent', 'auto', 'automatic', 'system', 'service-generator') or not str(reason).strip():
        raise ProtectedFileError('an overwrite must be authorized by the user with a reason')
    path = Path(ws_dir) / 'overwrite-authorizations.yml'
    data = yaml.safe_load(path.read_bytes()) if path.is_file() else {'schemaVersion': 1, 'authorizations': []}
    entry = {'path': rel, 'currentSha256': sha(target), 'authorizedBy': authorized_by, 'reason': reason,
             'authorizedAt': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    data['authorizations'] = [a for a in data['authorizations'] if not (norm(a['path']) == rel and a['currentSha256'] == entry['currentSha256'])] + [entry]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')
    return entry
