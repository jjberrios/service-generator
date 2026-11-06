"""Planner of the remote-orchestration pattern: writes `full-planning-input.yml`, `generation-parameters.yml` and `implementation-plan.yml` of a service workspace
from its `service-spec.yml` (pattern `remote-orchestration`) and an explicitly selected archetype.

Usage (repository root):  python remote_orchestration_plan.py <service> --archetype archetypes/<name>/<version>
The planned inventory is the exact set of components the deterministic materializer generates; the plan carries the complete orchestration model so the
materializer never rereads Sparx or OpenAPI.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import sys
import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'materialize-full-service' / 'scripts'))
import build_implementation_plan as planner_base  # noqa: E402
import remote_orchestration_materializer as rom  # noqa: E402
import workspace as wsm  # noqa: E402

VALUES = {'application_log_level': 'INFO', 'corporate_logger_level': 'INFO', 'http_log_level': 'INFO', 'root_log_level': 'INFO', 'log_time_zone': 'UTC', 'jwt_roles_claim': 'roles',
          'java_version': '21', 'spring_boot_version': '3.4.1'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(doc):
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=200).encode('utf-8')


def build(repo: Path, service: str, archetype: str):
    ws = wsm.Workspace(repo, service)
    spec_bytes = (ws.dir / 'service-spec.yml').read_bytes()
    spec = yaml.safe_load(spec_bytes)
    if spec.get('pattern') != rom.PATTERN or spec['service']['name'] != service:
        raise ValueError('service-spec.yml is not a remote-orchestration specification of this service')
    if not (spec.get('readiness') or {}).get('functionalGenerationReady'):
        raise ValueError('the specification is not ready for functional generation')
    fingerprint = planner_base.archetype_fingerprint(repo / archetype)
    package = spec['service']['package']
    technical = wsm.technical_identifier(service)
    values = {'base_package': package, 'base_package_path': package.replace('.', '/'), 'group_id': package, 'project_version': '1.0.0-SNAPSHOT',
              'application_class': spec['service']['applicationClass'], **VALUES, 'service_name': technical, 'artifact_id': technical}
    planning = {'version': 1, 'kind': 'full-planning-input', 'target': {'service': service, 'archetype': archetype, 'output_directory': f'output/{service}'},
                'pattern': rom.PATTERN, 'decisions': {'basis': 'user delegation: decisions taken by the agent, conservative options recorded as assumptions (service-spec derivedAssumptions)'}}
    params = {'version': 2, 'mode': 'full', 'service': service, 'values': values,
              'inputs': {'serviceSpec': {'sha256': sha(spec_bytes)}, 'archetype': {'path': archetype, 'fingerprint': fingerprint}},
              'readiness': {'functionalGenerationReady': True}, 'unresolved': [], 'validation': {'errors': []}}
    plan = {'plan': {'version': 3, 'mode': 'full', 'pattern': rom.PATTERN, 'patternVersion': 1},
            'service': {'name': service, 'package': package, 'packagePath': package.replace('.', '/'), 'groupId': package, 'projectVersion': '1.0.0-SNAPSHOT', 'javaVersion': '21',
                        'springBootVersion': '3.4.1', 'outputDirectory': f'output/{service}', 'applicationClass': spec['service']['applicationClass']},
            'inputs': {'serviceSpec': {'path': f'.factory/services/{service}/service-spec.yml', 'artifactSha256': sha(spec_bytes)}, 'archetype': {'path': archetype, 'fingerprint': fingerprint},
                       'generationParameters': {'path': f'.factory/services/{service}/generation-parameters.yml', 'sha256': sha(dump(params))},
                       'planningInput': {'path': f'.factory/services/{service}/full-planning-input.yml', 'sha256': sha(dump(planning))}},
            'generation': {'functionalGenerationReady': True, 'scope': 'full', 'unsupported': []},
            'readiness': {'deploymentGenerationAuthorized': False},
            'api': {'operations': [{'operationId': spec['contract']['operationId'][0].lower() + spec['contract']['operationId'][1:], 'contractOperationId': spec['contract']['operationId'], 'method': spec['contract']['method'], 'path': spec['contract']['path'], 'actionKind': 'remote-orchestration',
                                    'effectiveStatusCodes': spec['contract']['statuses']}]},
            'models': [], 'persistenceModel': {'storage': 'none', 'reason': 'the operation accesses no database; every integration is a remote call'},
            'activityLogging': {'requestHeaders': {'components': ['transactionId', 'userId', 'applicationName']}},
            'technicalChoices': {'http-client': {'mechanism': 'Spring RestClient with JSON bodies (Jackson trees), timeouts and paths as environment parameters'}},
            'contract': spec['contract'], 'orchestration': copy.deepcopy(spec['orchestration']),
            'assumptions': spec['derivedAssumptions'], 'gaps': spec['gaps'], 'files': {'generate': []}}
    generated, _ = rom.generate(copy.deepcopy(plan))
    plan['files']['generate'] = [{'path': path, 'action': 'create', 'componentType': rom.component_type(path), 'generationOrder': index, 'dependencies': []}
                                 for index, path in enumerate(sorted(generated))]
    plan['files']['generate'].append({'path': rom.MANIFEST, 'action': 'create', 'componentType': 'generation-provenance-manifest', 'generationOrder': len(generated), 'dependencies': []})
    return planning, params, plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service')
    parser.add_argument('--archetype', required=True)
    args = parser.parse_args(argv)
    repo = Path.cwd().resolve()
    ws = wsm.Workspace(repo, args.service)
    planning, params, plan = build(repo, args.service, args.archetype)
    from artifact_integrity import write_atomic
    write_atomic(ws.dir / 'full-planning-input.yml', dump(planning))
    write_atomic(ws.dir / 'generation-parameters.yml', dump(params))
    write_atomic(ws.dir / 'implementation-plan.yml', dump(plan))
    ws.set_state(archetype={'path': args.archetype})
    print({'planned': len(plan['files']['generate']), 'archetype': args.archetype})
    return 0


if __name__ == '__main__':
    sys.exit(main())
