"""Read-only technical feasibility, using the actual backends' in-memory preview.

No cached verdict is trusted. This is not business authorization or runtime proof.
The private backend entry points are shared implementation, not CLI escape flags.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import yaml


def evaluate(repo, service, *, supported_only=False, assemble=True):
    import full_materializer as fm
    from generation_context import load_mapping, resolve_context
    import archetype_contract as ac

    repo = Path(repo).resolve()
    ws = fm.wsm.Workspace(repo, service)
    rows, fingerprints = [], {}
    result = {'schemaVersion': 1, 'service': service, 'profile': None,
              'archetype': None, 'inputFingerprints': fingerprints,
              'requirements': rows, 'status': 'unknown', 'feasible': False,
              'limitations': ['Static preview does not prove compilation, tests, database or remote integration compatibility.']}

    def add(ident, kind, status, evidence):
        rows.append({'id': str(ident), 'kind': kind, 'required': True,
                     'status': status, 'evidence': [str(evidence)]})

    def finish():
        statuses = {r['status'] for r in rows}
        result['status'] = next((s for s in ('blocked', 'unsupported', 'unknown') if s in statuses), 'supported')
        result['feasible'] = bool(rows) and result['status'] == 'supported'
        result['runId'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        return result

    # Hash only explicit artifacts; never traverse local environment configuration.
    for name in ('implementation-plan.yml', 'service-spec.yml', 'generation-parameters.yml',
                 'full-planning-input.yml', 'service-generation-state.yml', 'sparx-reviewed-decisions.yml',
                 'openapi-spec.yml', 'sparx-spec.yml', 'sparx-target-authority.yml',
                 'sparx-authoritative-endpoint-detail.yml',
                 'consistency/authorization.yml', 'consistency/resolutions.yml',
                 'consistency/supplemental.yml', 'consistency/batch-review.yml'):
        path = ws.dir / name
        try:
            if path.is_file() and not path.is_symlink():
                fingerprints[name] = fm.sha(path.read_bytes())
        except OSError as error:
            add(name, 'input', 'unknown', f'Cannot fingerprint input: {error}')
    # Backend code participates in the verdict identity as well as the plan.
    for directory in (Path(__file__).parent, fm.SKILLS / 'plan-service-implementation' / 'scripts'):
        for path in sorted(directory.glob('*.py')):
            fingerprints[f'{directory.parent.name}/{path.name}'] = fm.sha(path.read_bytes())
    try:
        plan = load_mapping(ws.dir / 'implementation-plan.yml')
        spec = load_mapping(ws.dir / 'service-spec.yml')
        expected_spec = ((plan.get('inputs') or {}).get('serviceSpec') or {}).get('artifactSha256')
        if expected_spec and expected_spec != fingerprints.get('service-spec.yml'):
            raise fm.MaterializationError('stale-plan', 'the plan was not built from the current service-spec of this workspace')
        context = resolve_context(repo, service=service)
        result['archetype'] = Path(context.archetype).as_posix()
        manifest = load_mapping(repo / context.archetype / 'archetype.yml')
        contract = ac.normalize(manifest)
        result['profile'] = contract['profile']
        ac.require_backend(contract)
        from artifact_integrity import archetype_hashes
        fingerprints['archetype'] = archetype_hashes(repo / context.archetype)
        profile = contract['profile']
        declared = (plan.get('plan') or {}).get('profile') or ac.LEGACY_JPA
        if declared != profile:
            add('profile', 'contract', 'blocked', 'Plan profile disagrees with explicitly selected archetype')
        if supported_only:
            add('partial-generation', 'contract', 'unsupported', 'Partial generation is not supported by the FULL preflight')

        operations = (plan.get('api') or {}).get('operations') if profile == ac.LEGACY_JPA else plan.get('operations', [])
        if not isinstance(operations, list):
            raise ValueError('Plan operations must be a list')
        op_rows = []
        for op in operations:
            ident = op.get('operationId')
            if not ident:
                raise ValueError('Operation without operationId')
            add(ident, 'operation', 'unknown', 'Awaiting whole-backend preview')
            op_rows.append(rows[-1])
            # Reuse the actual semantic model check for each operation; also run
            # the complete model below (cross-operation constraints still apply).
            if profile == ac.LEGACY_JPA:
                isolated = deepcopy(plan)
                isolated['api']['operations'] = [op]
                try:
                    fm.sm.build(isolated)
                except fm.rd.Unsupported as error:
                    rows[-1].update(status='unsupported', evidence=[f'service_model.build: {error}'])
                except (KeyError, ValueError, TypeError, IndexError, AttributeError) as error:
                    rows[-1].update(evidence=[f'Malformed operation model: {error}'])
        planned_ids = {r['id'] for r in op_rows}
        for op in spec.get('operations', []):
            ident = op.get('operationId')
            if ident not in planned_ids:
                add(ident or 'missing-operation-id', 'operation', 'unknown', 'service-spec operation absent from materializable plan')
        for op in plan.get('incompleteOperations', []):
            add(op.get('operationId', str(op)) if isinstance(op, dict) else op,
                'operation', 'unsupported', 'implementation-plan.incompleteOperations')
        if profile == ac.BATCH_SHELL:
            import batch_shell_materializer as batch
            b = plan.get('batch') or {}
            if batch.structure_only(b) or batch.ports_flow(b):
                add('batch-flow', 'behavior', 'unsupported', f'Batch scope {b.get("scope")} is functionally incomplete')
            for omitted in b.get('omittedBehavior', []):
                add(str(omitted), 'behavior', 'unsupported', 'batch.omittedBehavior')
            def steps(items):
                for step in items:
                    add(step['id'], 'batch-step', 'unknown', 'Awaiting complete batch planner and renderer validation')
                    steps(step.get('steps', []))
            steps(b.get('steps', []))
        for entry in (plan.get('files') or {}).get('generate', []):
            add(entry['path'], 'component', 'unknown', f'componentType={entry["componentType"]}; awaiting backend preview')
        # JPA classification collects all unsupported file generators, rather
        # than stopping at the first unsupported component.
        if profile == ac.LEGACY_JPA:
            fm.validate_contract(plan)
            work = fm.classify(deepcopy(plan), repo)
            for item in work['unsupported']:
                for row in rows:
                    if row['kind'] == 'component' and row['id'] == item['path']:
                        row.update(status='unsupported', evidence=[item['reason']])
        # This existing dry-run validates provenance, planner reconstruction,
        # assumptions, actual renderers, assembly and file protection. No publish.
        preview = fm._materialize_unlocked(repo, service, False, True, assemble)
        result['backendPreview'] = {k: preview[k] for k in ('status', 'payloadTreeSha256') if k in preview}
        if preview['status'] != 'complete':
            add('backend-preview', 'behavior', 'unsupported', f'Backend reports {preview["status"]}')
        for row in rows:
            if row['status'] == 'unknown' and row['evidence'][0].startswith(('Awaiting', 'componentType=')):
                row.update(status='supported', evidence=['Actual backend complete in-memory preview (including provenance and rendering)'])
    except ac.ContractError as error:
        add('profile', 'contract', 'unsupported', error)
    except fm.gate.GateError as error:
        add('consistency-gate', 'gate', 'blocked', error)
    except fm.MaterializationError as error:
        result['failureKind'] = error.kind
        result['failureDetails'] = error.details
        result['failureMessage'] = str(error).removeprefix(error.kind + ': ')
        status = 'unsupported' if error.kind == 'unsupported' else 'blocked' if error.kind in (
            'stale-plan', 'protected-files', 'pending-functional-assumptions', 'missing-decision') else 'unknown'
        add('backend-validation', 'contract', status, error)
        for item in error.details.get('unsupported', []):
            add(item.get('path', 'backend'), 'component', 'unsupported', item.get('reason', error))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError, yaml.YAMLError, RecursionError) as error:
        add('input-validation', 'contract', 'unknown', f'{type(error).__name__}: {error}')
    return finish()


def enforce(repo, service, **options):
    import full_materializer as fm
    # Authorization always wins over feasibility; no report clears this gate.
    ws = fm.wsm.Workspace(Path(repo).resolve(), service)
    fm.gate.check_cleared(ws.dir, Path(repo).resolve(), service)
    report = evaluate(repo, service, **options)
    if not report['feasible']:
        raise fm.MaterializationError(report.get('failureKind', 'preflight-failed'),
                                      report.get('failureMessage', 'FULL technical feasibility not established; nothing generated'),
                                      {**report.get('failureDetails', {}), 'preflight': report})
    return report
