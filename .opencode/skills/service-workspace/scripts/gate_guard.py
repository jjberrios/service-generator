"""Guard imported by every post-gate script (consolidation, planning, materialization).

Each script calls `enforce()` at the top of main(): it recomputes the Sparx/Swagger consistency gate for the workspace that the script sees as
`.factory/` (a service workspace through the sandbox runner) and refuses to continue (exit code 3) unless the gate is CLEARED. A plain repository
`.factory/` without a service workspace cannot clear the gate, so there is no alternative route around the control.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import consistency_gate as gate  # noqa: E402


def enforce(root: Path | None = None) -> int | None:
    """None when the gate is cleared, otherwise the exit code (3) after explaining why development is stopped."""
    root = Path(root or Path.cwd()).resolve()
    try:
        gate.check_cleared(root / '.factory', root)
        return None
    except gate.GateError as error:
        blocking = (error.details or {}).get('blocking') or []
        print(f'GATE BLOCKED ({error.status}): {error}. No planning, scaffold or Java generation is allowed.', file=sys.stderr)
        for item in blocking[:20]:
            print(f'  - {item["id"]} [{item["category"]}] {item["element"]}', file=sys.stderr)
        return 3
    except Exception as error:  # unreadable or inconsistent workspace never clears the gate
        print(f'GATE BLOCKED (cannot evaluate): {type(error).__name__}: {error}', file=sys.stderr)
        return 3
