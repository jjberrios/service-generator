"""Deterministic consolidation of a non-HTTP batch service specification.

Run through `workspace_cli.py run <service> .opencode/skills/reconcile-service-spec/scripts/consolidate_batch_spec.py`.
The batch gate is evaluated on the candidate `.factory/sparx-spec.yml` (normalized Sparx behavior, bound to resolved target
authority, grounded evidence, semantic review and human authorization), so it can be CLEARED before the service
specification exists. This script then copies the approved IR into `.factory/service-spec.yml`; it adds no behavior.
"""
from pathlib import Path
import sys
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(HERE.parents[1] / 'plan-service-implementation' / 'scripts'))
import gate_guard  # noqa: E402
import artifact_integrity as ai  # noqa: E402

SPARX = 'sparx-spec.yml'
TARGET = 'service-spec.yml'


def build(sparx: dict) -> dict:
    if set(sparx) - {'service', 'batch', 'warnings'}:
        raise ValueError('sparx-spec of a batch service may only contain service, batch and warnings')
    if set(sparx.get('service') or {}) != {'name', 'profile'} or sparx['service']['profile'] != 'batch-shell':
        raise ValueError('batch-shell service identity required')
    if not all(isinstance(w, str) and w for w in sparx.get('warnings', [])):
        raise ValueError('warnings must be non-empty strings')
    return {'service': sparx['service'], 'batch': sparx['batch'],
            'readiness': {'strictImplementationReady': True, 'functionalCodeGenerationReady': True},
            'unresolved': {}, 'warnings': list(sparx.get('warnings', []))}


def main() -> int:
    code = gate_guard.enforce()
    if code is not None:
        return code
    root = Path.cwd() / '.factory'
    try:
        sparx = yaml.safe_load(ai.safe_path(root, SPARX).read_bytes())
        spec = build(sparx)
        data = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=140).encode('utf-8')
        ai.write_atomic(ai.safe_path(root, TARGET), data)
    except (ValueError, OSError, ai.IntegrityError) as error:
        print(f'batch consolidation failed: {error}', file=sys.stderr)
        return 2
    print({'serviceSpec': '.factory/' + TARGET, 'steps': len(spec['batch']['steps'])})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
