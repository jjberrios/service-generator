"""Command line for service workspaces, the consistency gate, migration, file protection and the sandbox runner.

  workspace_cli.py list
  workspace_cli.py init <service>
  workspace_cli.py status <service>
  workspace_cli.py migrate-archive <service> <archive-dir>
  workspace_cli.py migrate-root
  workspace_cli.py run <service> <script> [args...]           (existing pipeline scripts against the workspace; post-gate scripts need a cleared gate)
  workspace_cli.py gate-evaluate <service>                    (recompute the audit; writes consistency/findings.yml, gate.yml and the checkpoint)
  workspace_cli.py gate-resolve <service> <item-id> --disposition D --justification T --approved-by NAME [--scope S ...] [--decision ID]
  workspace_cli.py gate-authorize <service> --by NAME --statement "user words"
  workspace_cli.py gate-check <service>                       (exit 3 unless CLEARED)
  workspace_cli.py resume <service>                           (re-evaluates; a blocked service stays blocked)
  workspace_cli.py preflight <service>                        (read-only YAML feasibility; exit 4 unless all mandatory requirements supported)
  workspace_cli.py materialize <service> [--supported-only] [--dry-run] [--no-assemble]   (deterministic FULL materializer; gate and file protection enforced inside)
  workspace_cli.py protect-check <service> --plan <implementation-plan.yml>   (exit 3 when manual content would be overwritten)
  workspace_cli.py protect-authorize <service> <relative-path> --by NAME --reason TEXT
  workspace_cli.py decision-request-create <service> --proposal <workspace-relative.yml>
  workspace_cli.py decision-request-list <service>
  workspace_cli.py decision-request-show <service> <request-id>
  workspace_cli.py decision-request-context <service> [--purpose PURPOSE | --request REQUEST_ID]
  workspace_cli.py decision-request-status <service> <request-id>
  workspace_cli.py decision-request-stale <service>

Decision requests are proposals only. Legacy gate-resolve/gate-authorize remain
unchanged and do NOT authenticate humans (H-02 remains open pending stage 2B).
"""
from pathlib import Path
import argparse
import json
import sys
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import consistency_gate as gate  # noqa: E402
import file_protection as fp  # noqa: E402
import migrate_legacy as mig  # noqa: E402
import workspace as wsm  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    for name in ('init', 'status', 'gate-evaluate', 'gate-check', 'resume', 'preflight'):
        sub.add_parser(name).add_argument('service')
    m = sub.add_parser('migrate-archive')
    m.add_argument('service')
    m.add_argument('archive')
    sub.add_parser('migrate-root')
    lc = sub.add_parser('lifecycle')
    lc.add_argument('service')
    r = sub.add_parser('run')
    r.add_argument('service')
    r.add_argument('script')
    r.add_argument('args', nargs=argparse.REMAINDER)
    g = sub.add_parser('gate-resolve')
    g.add_argument('service')
    g.add_argument('item')
    g.add_argument('--disposition', required=True, choices=gate.DISPOSITIONS)
    g.add_argument('--justification', required=True)
    g.add_argument('--approved-by', required=True)
    g.add_argument('--scope', action='append')
    g.add_argument('--decision')
    a = sub.add_parser('gate-authorize')
    a.add_argument('service')
    a.add_argument('--by', required=True)
    a.add_argument('--statement', required=True)
    mz = sub.add_parser('materialize')
    mz.add_argument('--no-assemble', action='store_true')
    mz.add_argument('service')
    mz.add_argument('--supported-only', action='store_true')
    mz.add_argument('--dry-run', action='store_true')
    pc = sub.add_parser('protect-check')
    pc.add_argument('service')
    pc.add_argument('--plan', type=Path, required=True)
    pa = sub.add_parser('protect-authorize')
    pa.add_argument('service')
    pa.add_argument('path')
    pa.add_argument('--by', required=True)
    pa.add_argument('--reason', required=True)
    import decision_context as dc
    for name in ('decision-request-create', 'decision-request-list', 'decision-request-show',
                 'decision-request-context', 'decision-request-status', 'decision-request-stale'):
        cmd = sub.add_parser(name)
        cmd.add_argument('service')
        if name == 'decision-request-create':
            cmd.add_argument('--proposal', required=True)
        if name in ('decision-request-show', 'decision-request-status'):
            cmd.add_argument('request_id')
        if name == 'decision-request-context':
            choice = cmd.add_mutually_exclusive_group(required=True)
            choice.add_argument('--purpose', choices=dc.PURPOSES)
            choice.add_argument('--request')
    args = parser.parse_args(argv)
    repo = Path.cwd().resolve()
    try:
        if args.command == 'list':
            print(yaml.safe_dump(wsm.list_services(repo)))
            return 0
        if args.command == 'migrate-root':
            print(yaml.safe_dump(mig.migrate_root_active(repo), allow_unicode=True))
            return 0
        ws = wsm.Workspace(repo, args.service)
        if args.command.startswith('decision-request-'):
            return decision_command(args, ws)
        if args.command == 'init':
            ws.ensure()
            ws.set_state(schemaVersion=1, status=ws.state().get('status', 'idle'))
            print(ws.dir)
        elif args.command == 'lifecycle':
            import lifecycle
            state = ws.state()
            path = (state.get('archetype') or {}).get('path')
            out = {'service': lifecycle.service_lifecycle(repo, args.service, gate)}
            if path:
                out['archetype'] = lifecycle.archetype_lifecycle(repo, path)
            print(yaml.safe_dump(out, allow_unicode=True, sort_keys=False))
        elif args.command == 'status':
            print(yaml.safe_dump({'workspace': ws.dir.relative_to(repo).as_posix(), 'state': ws.state(), 'gate': gate.load(gate.paths(ws.dir)['gate'])}, allow_unicode=True, sort_keys=False))
        elif args.command == 'migrate-archive':
            print(yaml.safe_dump(mig.migrate_archived_run(repo, Path(args.archive), args.service)))
        elif args.command == 'run':
            done = wsm.run_script(ws, Path(args.script), args.args)
            sys.stdout.write(done.stdout)
            sys.stderr.write(done.stderr)
            return done.returncode
        elif args.command == 'gate-evaluate':
            result = ws.refresh_gate()
            print(yaml.safe_dump({k: result[k] for k in ('status', 'counts', 'evaluationHash')} | {'blocking': [{k: i[k] for k in ('id', 'category', 'element')} for i in result['blocking']], 'topics': result['topics'], 'coveredByDecision': [{'id': i['id'], 'decision': i['coveredBy']['decisionId']} for i in result['coveredByDecision']], 'coverageProblems': result['coverageProblems']}, allow_unicode=True, sort_keys=False))
            return 0 if result['status'] == gate.CLEARED else 3
        elif args.command == 'gate-resolve':
            entry = gate.record_resolution(ws.dir, repo, ws.service, args.item, args.disposition, args.justification, args.approved_by, args.scope, args.decision)
            print(yaml.safe_dump(entry, allow_unicode=True))
        elif args.command == 'gate-authorize':
            print(yaml.safe_dump(gate.authorize(ws.dir, repo, ws.service, args.by, args.statement), allow_unicode=True))
            ws.refresh_gate()
        elif args.command == 'gate-check':
            gate.check_cleared(ws.dir, repo, ws.service)
            print('CLEARED')
        elif args.command == 'resume':
            result = ws.resume()
            print(json.dumps({'resumable': result['resumable'], 'status': result['gate']['status']}))
            return 0 if result['resumable'] else 3
        elif args.command == 'preflight':
            scripts = Path(__file__).resolve().parents[2] / 'materialize-full-service' / 'scripts'
            sys.path.insert(0, str(scripts))
            import full_materializer  # initializes shared backend imports
            import feasibility_preflight
            report = feasibility_preflight.evaluate(repo, args.service)
            print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
            return 0 if report['feasible'] else 4
        elif args.command == 'materialize':
            script = Path(__file__).resolve().parents[2] / 'materialize-full-service' / 'scripts' / 'full_materializer.py'
            import subprocess
            done = subprocess.run([sys.executable, str(script), args.service] + (['--supported-only'] if args.supported_only else []) + (['--dry-run'] if args.dry_run else []) + (['--no-assemble'] if getattr(args, 'no_assemble', False) else []), cwd=repo)
            return done.returncode
        elif args.command == 'protect-check':
            plan = yaml.safe_load(args.plan.read_bytes())
            out_dir = repo / plan['service']['outputDirectory']
            decisions = fp.evaluate(out_dir, [{'path': f['path'], 'action': f['action']} for f in plan['files']['generate']], ws.dir)
            blocked = fp.blocked(decisions)
            print(yaml.safe_dump({'blocked': [{k: d[k] for k in ('path', 'state', 'reason')} for d in blocked], 'excludedUntouched': sum(d['decision'] == 'skip-excluded' for d in decisions)}, allow_unicode=True))
            return 3 if blocked else 0
        elif args.command == 'protect-authorize':
            out_dir = repo / (ws.state().get('outputDirectory') or f'output/{ws.service}')
            print(yaml.safe_dump(fp.authorize_overwrite(out_dir, args.path, ws.dir, args.by, args.reason), allow_unicode=True))
        return 0
    except (gate.GateError, wsm.WorkspaceError, mig.MigrationError, fp.ProtectedFileError) as error:
        print(f'workspace_cli: {type(error).__name__}: {error}', file=sys.stderr)
        return 3


def decision_command(args, ws):
    """Proposal-only CLI branch; intentionally never refreshes gate/checkpoint."""
    import decision_context as dc
    import decision_requests as dr
    from artifact_integrity import safe_path, protected
    from generation_context import load_mapping
    try:
        command = args.command.removeprefix('decision-request-')
        code = 0
        if command == 'create':
            if protected(args.proposal):
                raise dc.DecisionError('protected-proposal-path')
            proposal = load_mapping(safe_path(ws.dir, args.proposal))
            out = dr.create(ws.repo, ws.service, proposal)
        elif command in ('list', 'stale'):
            out = dr.list_requests(ws.repo, ws.service, stale_only=command == 'stale')
        elif command == 'show':
            out = dr.read(ws.repo, ws.service, args.request_id)
        elif command == 'status':
            out = dr.status(ws.repo, ws.service, args.request_id)
            code = 0 if out['validity'] == 'current' else 4
        elif args.request:
            out = dr.read(ws.repo, ws.service, args.request)['context']
        else:
            out = dc.build(ws.repo, ws.service, args.purpose)
        print(yaml.safe_dump(out, sort_keys=True, allow_unicode=True, width=100))
        return code
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError, yaml.YAMLError) as error:
        print(f'decision-request: {type(error).__name__}: {error}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
