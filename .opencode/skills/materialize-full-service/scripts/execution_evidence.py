"""Records a really executed javac compilation or JUnit-launcher run (never Maven, Checkstyle or JaCoCo) bound to the current generated tree.

Usage: python execution_evidence.py <service> <javac-compilation|junit-launcher-tests> <passed|failed> --method "<how>" [--detail "<text>"]
"""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_support as ts  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service')
    parser.add_argument('tool')
    parser.add_argument('status')
    parser.add_argument('--method', required=True)
    parser.add_argument('--detail', default='')
    args = parser.parse_args(argv)
    repo = Path.cwd().resolve()
    ws = repo / '.factory' / 'services' / args.service
    plan = yaml.safe_load((ws / 'implementation-plan.yml').read_bytes())
    manifest = yaml.safe_load((repo / plan['service']['outputDirectory'] / '.generation-manifest.yml').read_bytes())
    ts.record_execution(ws, args.tool, args.status, args.method, args.detail, manifest['payloadTreeSha256'])
    print(f'recorded {args.tool}={args.status} for {args.service} (payloadTreeSha256 {manifest["payloadTreeSha256"][:12]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
