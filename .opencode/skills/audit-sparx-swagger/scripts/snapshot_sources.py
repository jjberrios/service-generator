"""Create the OpenAPI and Sparx snapshots of an audit directly under reports/inconsistencias/registros/<service>/work/.

Reuses the existing analyzers without modifying them and without touching .factory/:
  - normalize_openapi.py (imported; its writer is called with the audit work directory as output root)
  - resolve_target_authority.py and build_authoritative_endpoint_detail.py (executed with work-directory outputs)
Writes snapshot-manifest.yml with the hashes used later to verify source currency.
"""
from pathlib import Path
import argparse
import importlib.util
import subprocess
import sys
import yaml

import source_currency as currency

REPO = Path.cwd().resolve()
SKILLS = Path(__file__).resolve().parents[2]


def load_normalizer():
    path = SKILLS / 'parse-openapi' / 'scripts' / 'normalize_openapi.py'
    spec = importlib.util.spec_from_file_location('normalize_openapi', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['normalize_openapi'] = module
    spec.loader.exec_module(module)
    return module


def safe_work_dir(service: str) -> Path:
    base = (REPO / 'reports' / 'inconsistencias' / 'registros').resolve()
    work = (base / service / 'work').resolve()
    if not service or '/' in service or '\\' in service or base not in work.parents:
        raise SystemExit(f'unsafe service name or work path: {service}')
    return work


def normalize(openapi: Path, output: Path):
    nz = load_normalizer()
    contracts = (REPO / 'input' / 'contracts').resolve()
    source = openapi.resolve()
    if not nz.is_within(source, contracts) or not source.is_file():
        raise SystemExit('OpenAPI must be an existing file under input/contracts/')
    yaml_module = nz.load_yaml_module()
    document, source_format, raw = nz.load_document(source, yaml_module)
    issues = nz.IssueCollector()
    nz.validate_document(document, issues)
    normalized = nz.normalize_document(document, source.relative_to(REPO), source_format, raw, issues)
    nz.write_yaml(output.resolve(), normalized, yaml_module, output.resolve().parent)
    errors = normalized['validation']['errors']
    tolerated = [e for e in errors if isinstance(e, dict) and e.get('code') == 'missing_info_field']
    blocking = [e for e in errors if e not in tolerated]
    if tolerated:
        print(f'WARNING: {len(tolerated)} tolerated info-field error(s) (audit only): {tolerated}', file=sys.stderr)
    if blocking:
        raise SystemExit(f'OpenAPI normalization reported {len(blocking)} error(s); audit refused')


def run(command):
    done = subprocess.run([sys.executable, *command], capture_output=True, text=True, cwd=REPO)
    if done.returncode != 0:
        raise SystemExit(f'{command[0]} failed: {(done.stderr or done.stdout)[-600:]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', required=True)
    parser.add_argument('--openapi', type=Path, required=True)
    parser.add_argument('--sparx', type=Path, required=True)
    args = parser.parse_args()
    work = safe_work_dir(args.service)
    work.mkdir(parents=True, exist_ok=True)
    openapi_rel = args.openapi.resolve().relative_to(REPO).as_posix()
    sparx_rel = args.sparx.resolve().relative_to(REPO).as_posix()
    if not openapi_rel.startswith('input/contracts/') or not (sparx_rel == 'input/sparx' or sparx_rel.startswith('input/sparx/')):
        raise SystemExit('sources must live under input/contracts/ and input/sparx/')
    normalize(args.openapi, work / 'openapi-spec.yml')
    parse_sparx = SKILLS / 'parse-sparx' / 'scripts'
    rel = lambda name: (work / name).relative_to(REPO).as_posix()
    run([str(parse_sparx / 'resolve_target_authority.py'), sparx_rel, rel('sparx-target-authority.yml'), '--target', args.service, '--openapi', rel('openapi-spec.yml')])
    run([str(parse_sparx / 'build_authoritative_endpoint_detail.py'), '--authority', rel('sparx-target-authority.yml'), '--source-root', sparx_rel,
         '--output', rel('sparx-authoritative-endpoint-detail.yml'), '--nonauthoritative-output', rel('sparx-nonauthoritative-evidence.yml')])
    artifacts = {n: currency.sha(work / n) for n in ('openapi-spec.yml', 'sparx-target-authority.yml', 'sparx-authoritative-endpoint-detail.yml', 'sparx-nonauthoritative-evidence.yml')}
    manifest = {'schemaVersion': 1, 'kind': 'audit-snapshot-manifest', 'service': args.service, 'work': work.relative_to(REPO).as_posix(),
                'openapi': {'path': openapi_rel, 'sha256': currency.sha(REPO / openapi_rel)},
                'sparx': {'root': sparx_rel, 'tocFiles': currency.sparx_state(REPO / sparx_rel)},
                'artifacts': artifacts, 'pages': {}, 'factoryUsed': False}
    (work / 'snapshot-manifest.yml').write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding='utf-8')
    print(yaml.safe_dump({'service': args.service, 'work': manifest['work'], 'artifacts': list(artifacts), 'factoryUsed': False}, sort_keys=False))


if __name__ == '__main__':
    sys.exit(main())
