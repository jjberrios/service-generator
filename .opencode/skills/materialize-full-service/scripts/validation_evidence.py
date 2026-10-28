"""Official validation evidence: runs (only when explicitly authorized) or ingests a real Maven build and records what the REPORTS say.

Nothing is inferred: every status comes from files produced by the build (Maven log, surefire TEST-*.xml, checkstyle-result.xml, jacoco.csv). The record is bound to the SHA-256
of the exact generated project (the manifest rows hashed from the files on disk); when the project changes the evidence is reported `stale`, never `passed`.
A tool that did not run is `not-executed` / `unverified` / `not-verified`.

Usage (Maven is executed only with --authorized-maven; offline, with the project's own settings.xml unless --settings is given):
  python validation_evidence.py run <service> --workdir <temporary directory> --authorized-maven [--settings PATH] [--mvn mvn]
  python validation_evidence.py ingest <service> --build-dir <directory of an existing Maven build> --log <maven log> --exit-code N
  python validation_evidence.py status <service>
"""
import argparse
import csv
import hashlib
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
import consistency_gate as gate  # noqa: E402
import file_protection as fp  # noqa: E402
import test_support as ts  # noqa: E402

VERSION = 'validation-evidence-1'
MANIFEST = '.generation-manifest.yml'


class EvidenceError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(rows: dict) -> str:
    return sha(''.join(f'{p}\0{h}\n' for p, h in sorted(rows.items())).encode('utf-8'))


def project_rows(out_dir: Path) -> tuple[dict, list]:
    """({path: sha of the file ON DISK}, drift) for every file of the generation manifest; a changed or missing file is drift."""
    manifest = yaml.safe_load((Path(out_dir) / MANIFEST).read_bytes())
    disk, drift = {}, []
    for row in manifest.get('fileInventory') or []:
        target = Path(out_dir) / row['path']
        if not target.is_file():
            disk[row['path']] = 'MISSING'
            drift.append(row['path'])
            continue
        disk[row['path']] = sha(target.read_bytes())
        if disk[row['path']] != row['sha256']:
            drift.append(row['path'])
    return disk, drift


def project_hash(out_dir: Path) -> tuple[str, list]:
    rows, drift = project_rows(out_dir)
    return tree_hash(rows), drift


# ----------------------------------------------------------------------------------------------------------------------------------------- parsing
def parse_tests(build: Path) -> dict:
    files = sorted((build / 'target' / 'surefire-reports').glob('TEST-*.xml'))
    if not files:
        return {'status': 'not-executed'}
    total = failures = errors = skipped = 0
    for f in files:
        suite = ET.parse(f).getroot()
        total += int(suite.get('tests', 0))
        failures += int(suite.get('failures', 0))
        errors += int(suite.get('errors', 0))
        skipped += int(suite.get('skipped', 0))
    passed = total > 0 and failures == 0 and errors == 0
    return {'status': 'passed' if passed else 'failed', 'total': total, 'passed': total - failures - errors - skipped, 'failures': failures, 'errors': errors, 'skipped': skipped, 'reportFiles': len(files)}


def parse_checkstyle(build: Path, log: str) -> dict:
    result = build / 'target' / 'checkstyle-result.xml'
    if not result.is_file() or not re.search(r'--- (?:maven-)?checkstyle:[\d.]+:check', log):
        return {'status': 'unverified'}
    root = ET.parse(result).getroot()
    files = root.findall('file')
    violations = sum(len(f.findall('error')) for f in files)
    by_rule = {}
    for f in files:
        for e in f.findall('error'):
            rule = (e.get('source') or '').rsplit('.', 1)[-1]
            by_rule[rule] = by_rule.get(rule, 0) + 1
    config = re.search(r'with (\S+) ruleset', log)
    version = re.search(r'reported by Checkstyle ([\d.]+)', log)
    return {'status': 'passed' if violations == 0 else 'failed', 'violations': violations, 'filesChecked': len(files), 'byRule': dict(sorted(by_rule.items())),
            'version': version.group(1) if version else None,
            'rules': config.group(1).replace('\\', '/').split('/')[-1] if config else None, 'sourceSets': ['src/main/java', 'src/test/java']}


def parse_jacoco(build: Path, log: str, pom_text: str) -> dict:
    csv_file = build / 'target' / 'site' / 'jacoco' / 'jacoco.csv'
    if not csv_file.is_file():
        return {'status': 'not-verified'}
    config = ts.pom_jacoco(pom_text)
    minimum = float(str(config.get('minimum') or '0').rstrip('%')) / (100 if str(config.get('minimum') or '').endswith('%') else 1)
    counter = config.get('counter') or 'INSTRUCTION'
    packages = {}
    with csv_file.open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            entry = packages.setdefault(row['PACKAGE'], [0, 0])
            entry[0] += int(row[f'{counter}_COVERED'])
            entry[1] += int(row[f'{counter}_MISSED'])
    table = {p: {'covered': c, 'total': c + m, 'ratio': round(c / (c + m), 4) if c + m else 1.0} for p, (c, m) in sorted(packages.items())}
    below = sorted(p for p, v in table.items() if v['ratio'] < minimum)
    ran_check = 'All coverage checks have been met' in log
    violated = 'Rule violated' in log or bool(below)
    status = 'passed' if ran_check and not violated else 'failed' if violated else 'not-verified'
    return {'status': status, 'threshold': {'minimum': config.get('minimum'), 'counter': counter, 'value': config.get('value'), 'element': config.get('element')}, 'packages': table,
            'belowThreshold': below, 'checkGoal': 'met' if ran_check else 'violated' if 'Rule violated' in log else 'not-reported'}


def parse_compilation(log: str) -> dict:
    compiled = re.search(r'--- (?:maven-)?compiler:[\d.]+:compile', log)
    test_compiled = re.search(r'--- (?:maven-)?compiler:[\d.]+:testCompile', log)
    if 'COMPILATION ERROR' in log:
        return {'status': 'failed', 'detail': 'COMPILATION ERROR reported by the compiler plugin'}
    if not compiled or not test_compiled:
        return {'status': 'not-executed', 'detail': 'the build stopped before the compiler plugin ran' if not compiled else 'test compilation did not run'}
    return {'status': 'passed', 'detail': 'main and test sources compiled by maven-compiler-plugin'}


def parse_build(build: Path, log: str, exit_code: int, pom_text: str) -> dict:
    success = exit_code == 0 and 'BUILD SUCCESS' in log
    failure = exit_code != 0 or 'BUILD FAILURE' in log
    return {'maven': {'status': 'passed' if success else 'failed' if failure else 'not-executed', 'exitCode': exit_code, 'buildResult': 'BUILD SUCCESS' if 'BUILD SUCCESS' in log else 'BUILD FAILURE' if 'BUILD FAILURE' in log else 'unknown'},
            'compilation': parse_compilation(log), 'testsExecuted': parse_tests(build), 'checkstyleOfficial': parse_checkstyle(build, log), 'jacoco': parse_jacoco(build, log, pom_text)}


def report_hashes(build: Path, log_bytes: bytes) -> dict:
    out = {'mavenLog': sha(log_bytes), 'surefire': {}}
    for f in sorted((build / 'target' / 'surefire-reports').glob('TEST-*.xml')):
        out['surefire'][f.name] = sha(f.read_bytes())
    for key, rel in (('checkstyleResult', 'target/checkstyle-result.xml'), ('jacocoCsv', 'target/site/jacoco/jacoco.csv'), ('jacocoXml', 'target/site/jacoco/jacoco.xml')):
        if (build / rel).is_file():
            out[key] = sha((build / rel).read_bytes())
    return out


# ------------------------------------------------------------------------------------------------------------------------------------- recording
def context(repo: Path, service: str) -> tuple:
    repo = Path(repo).resolve()
    ws = repo / '.factory' / 'services' / service
    gate.check_cleared(ws, repo, service)                         # no evidence (and no Maven run) for a service whose consistency gate is blocked
    plan = yaml.safe_load((ws / 'implementation-plan.yml').read_bytes())
    out = repo / plan['service']['outputDirectory']
    if not (out / MANIFEST).is_file():
        raise EvidenceError('the service has no generation manifest; generate it first')
    return repo, ws, plan, out


def refresh_scope(ws: Path, out: Path):
    """Brings the workspace coverage-scope tool states in line with the evidence (same function the materializer uses)."""
    scope_path = Path(ws) / 'coverage-scope.yml'
    if not scope_path.is_file():
        return
    scope = yaml.safe_load(scope_path.read_bytes())
    evidence_file = Path(ws) / ts.EVIDENCE
    old = yaml.safe_load(evidence_file.read_bytes()) if evidence_file.is_file() else None
    official_file = Path(ws) / ts.OFFICIAL
    official = yaml.safe_load(official_file.read_bytes()) if official_file.is_file() else None
    scope['tools'] = ts.tool_status(old, project_hash(out)[0], scope['threshold'], official)
    scope['status'], scope['statement'] = ts.scope_status(scope['tools'])
    scope_path.write_text(yaml.safe_dump(scope, sort_keys=False, allow_unicode=True, width=200), encoding='utf-8')


def ingest(repo: Path, service: str, build_dir: Path, log_path: Path, exit_code: int, command: str = None, settings: Path = None) -> dict:
    repo, ws, plan, out = context(repo, service)
    build_dir = Path(build_dir)
    digest, drift = project_hash(out)
    if drift:
        raise EvidenceError(f'the generated project differs from its manifest ({len(drift)} file(s), for example {drift[0]}); regenerate or restore it before recording evidence')
    # the build must have been made from exactly this project: every manifest file in the build directory has the manifest hash
    rows, _ = project_rows(out)
    foreign = [p for p, h in rows.items() if not (build_dir / p).is_file() or sha((build_dir / p).read_bytes()) != h]
    if foreign:
        raise EvidenceError(f'the build directory is not a build of the current project ({len(foreign)} file(s) differ, for example {foreign[0]})')
    log_bytes = Path(log_path).read_bytes()
    log = log_bytes.decode('utf-8', errors='replace')
    pom_text = (build_dir / 'pom.xml').read_text(encoding='utf-8')
    tools = parse_build(build_dir, log, exit_code, pom_text)
    record = {'schemaVersion': 2, 'recorder': VERSION, 'service': service, 'projectTreeSha256': digest, 'fileCount': len(rows),
              'command': command or 'mvn -o -B -s <settings> verify (as recorded by the caller)',
              'settings': ({'name': Path(settings).name, 'sha256': sha(Path(settings).read_bytes())} if settings and Path(settings).is_file() else None),
              'reports': report_hashes(build_dir, log_bytes), 'tools': tools}
    (ws / ts.OFFICIAL).write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=200), encoding='utf-8')
    refresh_scope(ws, out)
    return record


def run_official(repo: Path, service: str, workdir: Path, authorized: bool, settings: Path = None, mvn: str = 'mvn', timeout: int = 1800) -> dict:
    if not authorized:
        raise EvidenceError('running Maven needs explicit authorization (--authorized-maven); nothing was executed')
    repo, ws, plan, out = context(repo, service)
    digest, drift = project_hash(out)
    if drift:
        raise EvidenceError(f'the generated project differs from its manifest ({len(drift)} file(s)); nothing was executed')
    rows, _ = project_rows(out)
    build = Path(workdir) / service
    if build.exists():
        shutil.rmtree(build)
    for rel in rows:
        target = build / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / rel, target)                          # the real output is never used as a Maven working directory: no target/ is created inside it
    settings = Path(settings) if settings else build / 'settings.xml'
    if not settings.is_file():
        raise EvidenceError('settings.xml was not found; the offline build needs the corporate Maven settings of the archetype')
    command = [shutil.which(mvn) or mvn, '-o', '-B', '-s', str(settings), 'verify']
    done = subprocess.run(command, cwd=build, capture_output=True, text=True, timeout=timeout)
    log_path = Path(workdir) / f'{service}-maven.log'
    log_path.write_bytes((done.stdout + done.stderr).encode('utf-8'))
    return ingest(repo, service, build, log_path, done.returncode, 'mvn -o -B -s <settings> verify', settings)


def status(repo: Path, service: str) -> dict:
    repo = Path(repo).resolve()
    ws = repo / '.factory' / 'services' / service
    plan = yaml.safe_load((ws / 'implementation-plan.yml').read_bytes())
    out = repo / plan['service']['outputDirectory']
    official = yaml.safe_load((ws / ts.OFFICIAL).read_bytes()) if (ws / ts.OFFICIAL).is_file() else None
    digest, drift = project_hash(out) if (out / MANIFEST).is_file() else (None, [])
    tools = ts.tool_status(None, digest, {}, official)
    return {'projectTreeSha256': digest, 'drift': drift, 'tools': {k: tools[k]['status'] for k in ts.OFFICIAL_TOOLS}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('service')
    r.add_argument('--workdir', type=Path, required=True)
    r.add_argument('--authorized-maven', action='store_true')
    r.add_argument('--settings', type=Path)
    r.add_argument('--mvn', default='mvn')
    i = sub.add_parser('ingest')
    i.add_argument('service')
    i.add_argument('--build-dir', type=Path, required=True)
    i.add_argument('--log', type=Path, required=True)
    i.add_argument('--exit-code', type=int, required=True)
    s = sub.add_parser('status')
    s.add_argument('service')
    args = parser.parse_args(argv)
    repo = Path.cwd()
    try:
        if args.command == 'run':
            result = run_official(repo, args.service, args.workdir, args.authorized_maven, args.settings, args.mvn)
        elif args.command == 'ingest':
            result = ingest(repo, args.service, args.build_dir, args.log, args.exit_code)
        else:
            result = status(repo, args.service)
    except (EvidenceError, gate.GateError) as error:
        print(f'validation_evidence: {error}', file=sys.stderr)
        return 3
    print(yaml.safe_dump(result if args.command == 'status' else {'tools': {k: v.get('status') for k, v in result['tools'].items()}, 'projectTreeSha256': result['projectTreeSha256']}, sort_keys=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
