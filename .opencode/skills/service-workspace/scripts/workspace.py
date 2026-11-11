"""Independent service workspaces: .factory/services/<service>/ (state, artifacts, decisions, plan, validation) and the sandbox runner.

Every artifact of a service lives in its own directory, so processing another microservice never archives or overwrites it. Existing pipeline
scripts keep their `.factory/...` relative conventions: the runner executes them in a sandbox whose `.factory`, `input`, `archetypes`, `output`
and `.opencode` entries are directory links to the service workspace and the real folders. Provenance paths therefore stay valid inside a workspace.
"""
from pathlib import Path
from contextlib import contextmanager
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import uuid
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import consistency_gate as gate  # noqa: E402
from artifact_integrity import safe_path, write_atomic  # noqa: E402

SERVICES = Path('.factory') / 'services'
SANDBOXES = Path('.factory') / '.sandboxes'
NAME = re.compile(r'^[A-Za-z][A-Za-z0-9]*(-[A-Za-z0-9]+)*$')
SPARX_MARKERS = ('js/data', 'EARoot', 'index.htm')

CANONICAL = ('openapi-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'sparx-nonauthoritative-evidence.yml', 'sparx-spec.yml',
             'service-spec.yml', 'sparx-reviewed-decisions.yml', 'full-planning-input.yml', 'generation-parameters.yml', 'implementation-plan.yml',
              'service-generation-state.yml', 'sparx-http-contract.yml', 'sparx-attachments.yml')

# Pipeline phases in order. Everything from CONSOLIDATION on requires a cleared Sparx/Swagger consistency gate.
PHASES = ('input-validation', 'openapi-normalization', 'target-authority', 'consistency-validation', 'specification-consolidation',
          'implementation-planning', 'materialization', 'static-validation')
GATED_FROM = PHASES.index('specification-consolidation')
POST_GATE_SKILLS = {'reconcile-service-spec', 'plan-service-implementation', 'materialize-service-scaffold', 'materialize-full-service'}

BLOCKED_BY_INCONSISTENCIES = 'BLOCKED_BY_INCONSISTENCIES'
GATE_STATUS_TO_STATE = {gate.BLOCKED: BLOCKED_BY_INCONSISTENCIES, gate.SEMANTIC_REVIEW_PENDING: 'CONSISTENCY_REVIEW_PENDING',
                        gate.AWAITING_AUTHORIZATION: 'AWAITING_RESUME_AUTHORIZATION', gate.NO_AUDIT: 'CONSISTENCY_REVIEW_PENDING'}


class WorkspaceError(RuntimeError):
    pass


def safe_name(service: str) -> str:
    if not isinstance(service, str) or not NAME.match(service):
        raise WorkspaceError(f'unsafe service name: {service!r}')
    return service


def technical_identifier(service: str) -> str:
    """Lowercase kebab-case form of a service name (Maven artifactId / service_name valid form). camelCase boundaries become hyphens:
    dom-cpeRequest -> dom-cpe-request; already-lowercase names are returned unchanged."""
    safe_name(service)
    text = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', '-', service)
    return re.sub(r'-{2,}', '-', text).lower()


def _is_sparx_root(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in SPARX_MARKERS)


def resolve_sparx_root(repo: Path, requested: str) -> str:
    """Resolve the Sparx export root as a repo-relative POSIX path under input/sparx.

    Accepts `input/sparx/PROYECT[/]`, `input/sparx[/]`, `sparx[/]` and `/sparx`. A requested folder that is not itself an export root falls back to the
    export root at `input/sparx`, or to its single child export root; several candidates are ambiguous and fail instead of being guessed."""
    repo = Path(repo).resolve()
    base = (repo / 'input' / 'sparx').resolve()
    text = str(requested).strip().replace('\\', '/').strip('/')
    # User-facing /input/sparx is a repository path, not a drive-root path.
    if text == 'sparx' or text.startswith('sparx/'):
        text = 'input/' + text
    candidate = (repo / text).resolve() if text else base
    if candidate != base and base not in candidate.parents:
        raise WorkspaceError(f'Sparx path must be under input/sparx: {requested!r}')
    if _is_sparx_root(candidate):
        return candidate.relative_to(repo).as_posix()
    probe = candidate
    while probe != base and not probe.is_dir():
        probe = probe.parent
    if _is_sparx_root(base) and probe == base:
        return base.relative_to(repo).as_posix()
    children = [child for child in sorted(probe.iterdir()) if _is_sparx_root(child)] if probe.is_dir() else []
    if len(children) == 1 and probe == candidate:
        return children[0].relative_to(repo).as_posix()
    if len(children) > 1:
        raise WorkspaceError(f'ambiguous Sparx export root under {probe.relative_to(repo).as_posix()}: ' + ', '.join(c.name for c in children))
    if _is_sparx_root(base):
        return base.relative_to(repo).as_posix()
    raise WorkspaceError(f'no Sparx export root found for {requested!r}')


class Workspace:
    def __init__(self, repo: Path, service: str):
        self.repo = Path(repo).resolve()
        self.service = safe_name(service)
        self.dir = self.repo / SERVICES / self.service
        base = (self.repo / SERVICES).resolve()
        if base not in self.dir.resolve().parents:
            raise WorkspaceError('workspace escapes .factory/services')
        if base.is_dir():
            clash = [p.name for p in base.iterdir() if p.is_dir() and p.name != self.service and p.name.lower() == self.service.lower()]
            if clash:
                raise WorkspaceError(f'service name {self.service!r} differs only by case from existing workspace {clash[0]!r}')

    def path(self, name: str) -> Path:
        if '/' in name or '\\' in name or name.startswith('..'):
            raise WorkspaceError(f'unsafe artifact name {name}')
        return self.dir / name

    @property
    def state_file(self) -> Path:
        return self.dir / 'service-generation-state.yml'

    def exists(self) -> bool:
        return self.dir.is_dir()

    def ensure(self) -> 'Workspace':
        self.dir.mkdir(parents=True, exist_ok=True)
        return self

    def state(self) -> dict:
        state = yaml.safe_load(self.state_file.read_bytes()) if self.state_file.is_file() else {}
        if state is None:
            return {}
        self._validate_state(state)
        return state

    def _validate_state(self, state):
        if not isinstance(state, dict):
            raise WorkspaceError('checkpoint must be a mapping')
        if state.get('targetService') not in (None, self.service):
            raise WorkspaceError(f'state belongs to {state.get("targetService")}, not {self.service}')

    @contextmanager
    def _checkpoint_lock(self, timeout=5.0):
        """Short cooperative writer lock, independent of the materializer lock.

        Never evict stale locks. Direct/manual writers must serialize with this
        lock too; this is not an authentication or approval boundary.
        """
        self.ensure()
        # Validate the stable directory, not a contended lock-file pathname:
        # Windows resolve() can observe DELETE_PENDING during another release.
        directory = safe_path(self.repo, self.dir.relative_to(self.repo).as_posix())
        target = directory / '.checkpoint.lock'
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                break
            except (FileExistsError, PermissionError) as error:
                # Windows can report EACCES rather than EEXIST while the prior
                # owner's lock is pending deletion. Retry boundedly, never unlink.
                if time.monotonic() >= deadline:
                    raise WorkspaceError('checkpoint busy; inspect stale lock manually') from error
                time.sleep(0.01)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(str(os.getpid()))
            yield
        finally:
            target.unlink()

    def _write_state(self, state: dict):
        self._validate_state(state)
        write_atomic(safe_path(self.dir, self.state_file.name),
                     yaml.safe_dump(state, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))

    def write_state(self, state: dict):
        """Explicit full replacement; callers must not pass stale snapshots.

        Normal checkpoint updates use set_state/complete_phase instead. Approval
        records and manual output files are never written by this API.
        """
        with self._checkpoint_lock():
            self._write_state(state)

    def _update_state(self, update):
        with self._checkpoint_lock():
            target = safe_path(self.dir, self.state_file.name)
            before = target.read_bytes() if target.exists() else None
            state = yaml.safe_load(before) if before is not None else None
            state = state if state is not None else {'schemaVersion': 1, 'targetService': self.service}
            self._validate_state(state)
            update(state)
            # Fail conservatively if a non-cooperating/manual writer changed the
            # checkpoint during this update. External writers still need the lock
            # to close the final check/replace race.
            if (target.read_bytes() if target.exists() else None) != before:
                raise WorkspaceError('checkpoint changed concurrently; retry after serializing writers')
            self._write_state(state)
            return state

    def set_state(self, **fields) -> dict:
        return self._update_state(lambda state: state.update({'targetService': self.service, **fields}))

    def refresh_gate(self) -> dict:
        """Evaluate the consistency gate and mirror the outcome in the checkpoint (BLOCKED_BY_INCONSISTENCIES, ...)."""
        result = gate.evaluate(self.dir, self.repo, self.service)
        if result['status'] == gate.CLEARED:
            fields = {'consistencyGate': {'status': gate.CLEARED, 'evaluationHash': result['evaluationHash'], 'evaluatedAt': result['evaluatedAt']}}
            def update(state):
                if state.get('status') in set(GATE_STATUS_TO_STATE.values()):
                    state.update(status='in-progress', pendingQuestion=None)
                state.update(fields)
            self._update_state(update)
        else:
            blockers = [{'id': i['id'], 'category': i['category'], 'element': i['element']} for i in result['blocking']]
            self.set_state(status=GATE_STATUS_TO_STATE.get(result['status'], BLOCKED_BY_INCONSISTENCIES), currentPhase='consistency-validation',
                           consistencyGate={'status': result['status'], 'evaluationHash': result['evaluationHash'], 'evaluatedAt': result['evaluatedAt']}, blockers=blockers,
                           pendingQuestion={'kind': 'sparx-swagger-inconsistencies', 'items': [i['id'] for i in result['blocking']],
                                            'continuation': 'resolve each item with an explicit decision (or correct the documentation), then authorize resuming'})
        return result

    def enter_phase(self, phase: str) -> dict:
        """Checkpoint transition. Phases at or after consolidation are refused unless the gate is cleared right now."""
        if phase not in PHASES:
            raise WorkspaceError(f'unknown phase {phase}')
        if PHASES.index(phase) >= GATED_FROM:
            gate.check_cleared(self.dir, self.repo, self.service)
        return self.set_state(currentPhase=phase, status='in-progress')

    def complete_phase(self, phase: str) -> dict:
        def update(state):
            done = list(state.get('completedPhases') or [])
            if phase not in done:
                done.append(phase)
            state['completedPhases'] = done
        return self._update_state(update)

    def resume(self) -> dict:
        """Resuming never trusts the stored checkpoint: the gate is recomputed and a blocked service stays blocked."""
        result = self.refresh_gate()
        return {'resumable': result['status'] == gate.CLEARED, 'gate': result}


def list_services(repo: Path) -> list[str]:
    base = Path(repo) / SERVICES
    return sorted(p.name for p in base.iterdir() if p.is_dir() and NAME.match(p.name)) if base.is_dir() else []


# ------------------------------------------------------------------------------------------------------------------- sandbox
def make_link(link: Path, target: Path):
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            raise
        done = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True)
        if done.returncode != 0:
            raise WorkspaceError(f'cannot create directory link: {done.stdout}{done.stderr}')


def drop_sandbox(box: Path):
    """Remove the links first (rmdir on a link never touches its target), then the empty sandbox directory."""
    if box.is_symlink() or _is_junction(box):
        raise WorkspaceError('refusing redirected sandbox root')
    if not box.is_dir():
        return
    for child in list(box.iterdir()):
        if child.is_symlink():
            child.unlink()
        elif _is_junction(child):
            os.rmdir(child)
        elif child.is_file():
            child.unlink()
        else:
            raise WorkspaceError(f'unexpected directory inside the sandbox: {child.name}')
    box.rmdir()


def _is_junction(path: Path) -> bool:
    """Python <3.12 on Windows has no os.path.isjunction."""
    probe = getattr(os.path, 'isjunction', None)
    if probe is not None:
        return probe(path)
    if os.name == 'nt':
        import stat
        try:
            return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except FileNotFoundError:
            return False
    return False


def _cancel_process_tree(process):
    if os.name == 'nt':
        # A separate process group plus taskkill /T covers ordinary descendants.
        # This is operational cancellation, not containment of hostile processes.
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _record_run(ws, run_id, metadata):
    """Best effort metadata only; never changes a result or grants authority."""
    try:
        # Stabilize the parent before path validation: concurrent creation of a
        # missing intermediate directory can confuse Windows path resolution.
        (ws.dir / 'runs').mkdir(parents=True, exist_ok=True)
        write_atomic(safe_path(ws.dir, f'runs/{run_id}.json'),
                     json.dumps(metadata, sort_keys=True).encode('utf-8'))
    except Exception:
        pass


def skill_of(script: Path) -> str | None:
    parts = Path(script).resolve().parts
    return parts[parts.index('skills') + 1] if 'skills' in parts else None


def run_script(ws: Workspace, script: Path, args: list[str], *, timeout: float = 900) -> subprocess.CompletedProcess:
    """Run in a unique sandbox; timeout is seconds, explicitly bounded to [1, 86400].

    Does not authorize Maven or concurrent canonical artifact writers. Scripts
    writing the same canonical artifacts must still be scheduled serially.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 86400:
        raise WorkspaceError('runner timeout must be finite seconds in [1, 86400]')
    script = Path(script).resolve()
    allowed = (ws.repo / '.opencode/skills').resolve()
    if (not script.is_relative_to(allowed) or script.parent.name != 'scripts' or script.suffix != '.py'
            or script.name in ('review_cli.py', 'decision_reviews.py')):
        raise WorkspaceError('runner accepts pipeline skill scripts only; manual review is a separate user operation')
    if skill_of(script) in POST_GATE_SKILLS:
        gate.check_cleared(ws.dir, ws.repo, ws.service)
    ws.ensure()
    phase = ws.state().get('currentPhase')
    run_id = uuid.uuid4().hex
    box = safe_path(ws.repo, (SANDBOXES / ws.service / run_id).as_posix())
    box.mkdir(parents=True)
    started = time.monotonic()
    metadata = {'schemaVersion': 1, 'runId': run_id, 'phase': phase if phase in PHASES else None,
                'command': script.name, 'skill': skill_of(script), 'timeoutSeconds': timeout,
                'exitCode': None, 'outcome': 'error'}
    process = None
    try:
        for name, target in (('.factory', ws.dir), ('input', ws.repo / 'input'), ('archetypes', ws.repo / 'archetypes'), ('output', ws.repo / 'output'), ('.opencode', ws.repo / '.opencode')):
            if name == 'output':
                target.mkdir(parents=True, exist_ok=True)
            make_link(box / name, target)
        command = [sys.executable, str(script), *args]
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        process = subprocess.Popen(command, cwd=box, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **options)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            try:
                _cancel_process_tree(process)
            except OSError:
                pass
            # Descendants may have inherited the pipes. Never wait unboundedly.
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.stdout.close()
                process.stderr.close()
            raise
        metadata['outcome'] = 'completed'
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        metadata['outcome'] = 'timeout'
        raise
    except KeyboardInterrupt:
        metadata['outcome'] = 'cancelled'
        raise
    finally:
        metadata['durationSeconds'] = max(0, time.monotonic() - started)
        metadata['exitCode'] = process.returncode if process is not None else None
        _record_run(ws, run_id, metadata)
        # Cleanup must not mask an original timeout/nonzero exit or interruption.
        try:
            drop_sandbox(box)
            try:
                box.parent.rmdir()  # Empty only; another run's sandbox is untouched.
            except OSError:
                pass
        except OSError:
            pass
        except WorkspaceError:
            pass
