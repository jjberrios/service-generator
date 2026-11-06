"""Consolidate the service-spec of a BFF that has no Sparx and no own Swagger.

Reads `.factory/bff-contract-definition.yml` and the normalized backend contracts it names (`.factory/backend-contracts/*.openapi-spec.yml`),
verifies them against the live sources and writes `.factory/service-spec.yml` through the shared deterministic derivation (`bff_source.py`).
Run through `workspace_cli.py run <service> consolidate_bff_spec.py` (post-gate skill: the BFF consistency gate must be CLEARED).
"""
from __future__ import annotations

from pathlib import Path
import sys

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'service-workspace' / 'scripts'))
import bff_source as source  # noqa: E402


def main() -> int:
    repo = Path.cwd()
    ws = repo / '.factory'
    try:
        definition = source.load(ws / source.DEFINITION)
        service = definition['service']
        spec = source.derive(definition, source.backend_contracts(ws, repo, definition), service)
        from artifact_integrity import write_atomic
        write_atomic(ws / 'service-spec.yml', yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    except (source.SourceError, KeyError, OSError, yaml.YAMLError) as error:
        print(f'consolidate-bff-spec: {error}', file=sys.stderr)
        return 3
    print({'service': service, 'operations': len(spec['operations']), 'bound': [o['operationId'] for o in spec['operations'] if 'bffBinding' in o],
           'omittedBehavior': [o['operationId'] for o in spec['omittedBehavior']]})
    return 0


if __name__ == '__main__':
    sys.exit(main())
