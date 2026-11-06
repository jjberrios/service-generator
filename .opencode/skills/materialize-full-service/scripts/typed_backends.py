"""Registry of typed-model service backends (per-service JPA materializers that are not covered by the single-table FULL planner).

A backend module is any `*_materializer.py` in this directory that declares a module level tuple `TYPED_BACKEND_SERVICES = ('serviceName', ...)` and exposes
`preflight(repo, service)` and `materialize_unlocked(repo, service, dry_run=False, assemble=True)`. Discovery reads the module source text only (no import of the other
backends), so adding a service never edits this file and never changes the behaviour of the services that are already supported.
"""
from pathlib import Path
import ast
import importlib

HERE = Path(__file__).resolve().parent
DECLARATION = 'TYPED_BACKEND_SERVICES'


def declared(path):
    try:
        tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == DECLARATION for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return ()
            return tuple(str(v) for v in value) if isinstance(value, (tuple, list)) else ()
    return ()


def module_name(service):
    """Name of the backend module that declares `service`, or None."""
    for path in sorted(HERE.glob('*_materializer.py')):
        if service in declared(path):
            return path.stem
    return None


def load(service):
    name = module_name(service)
    return importlib.import_module(name) if name else None
