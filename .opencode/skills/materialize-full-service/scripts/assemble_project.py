"""Deterministic Maven project assembler: completes the generated Java with the technical files of the approved archetype.

It is a pure function of (implementation plan, workspace generation parameters, archetype template). `full_materializer.materialize` calls it
behind the consistency gate and file protection; every file it renders is written through `guard_write` and recorded with its hash in
`.generation-manifest.yml`, exactly like the generated Java.

Assembled (archetype template, token substitution only; the POM and the Checkstyle/JaCoCo rules are never edited):
  build   pom.xml, settings.xml, .gitignore, .gitattributes, .mvn/wrapper/maven-wrapper.properties, mvnw, mvnw.cmd, src/main/resources/checkstyle.xml, src/main/resources/logback.xml
  java    <application class>, configuration/swagger/SwaggerConfig, configuration/security/SecurityConfig, security/filter/JwtRequestFilter, security/service/JwtValidatorService(+Impl)
  deploy  Dockerfile, Jenkinsfile, config/*.j2  -- only when the plan says deploymentGenerationAuthorized is true

Also created when absent (D-015, never tracked, never read or overwritten once it exists): src/main/resources/application.properties built only from archetype.yml#/runtime/application_properties; secrets are ${ENV} placeholders.
Never assembled into the payload: src/main/resources/application*.properties (local environment configuration: not read, not compared, not overwritten),
and the template files that the materializer already generates from the plan (ActivityLogger, ConstanApi, ActivityLoggerTest).

Parameters: plan.service (name, package, packagePath, groupId, projectVersion, applicationClass) and `values` of the workspace `generation-parameters.yml`.
Derivations follow approved decisions only: group_id = base_package and the default version 1.0.0-SNAPSHOT (D-010), artifact_id = service name.
A missing required parameter or an unresolved token stops the assembly before anything is written.
"""
import fnmatch
import hashlib
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'plan-service-implementation' / 'scripts'))
import file_protection as fp  # noqa: E402
import pom_baseline  # noqa: E402

VERSION = 'assemble-project-2'
EXAMPLE = 'src/main/resources/application.properties'
BLOCKS = (('APPLICATION', ('server.', 'spring.threads.', 'spring.application.')), ('LOGGING', ('logging.',)), ('SWAGGER', ('springdoc.',)),
          ('ACTUATOR', ('management.',)), ('DATA SOURCE', ('spring.datasource.url', 'spring.datasource.username', 'spring.datasource.password', 'spring.datasource.driver')),
          ('HIKARI', ('spring.datasource.hikari.',)), ('JPA / HIBERNATE', ('spring.jpa.',)), ('JWT TOKEN', ('security.jwt.',)), ('SPRING CLOUD', ('spring.cloud.',)))
TOKEN = re.compile(r'__[A-Z0-9_]+__')
WRAPPER_IDENTIFIERS = {'__MVNW_ARG0_NAME__', '__MVNW_CMD__', '__MVNW_ERROR__'}       # variables of the unmodified official Maven Wrapper script
MARKER_TOKENS = {'__EXTERNAL_SECRET_ADDITIONAL_DATA__', '__SPECIFICATION_OWNED_APPLICATION_PROPERTIES__'}       # comment markers: the value replaces the whole line
DEPLOYMENT = ('Dockerfile', 'Jenkinsfile', 'config/*')
PLANNED_BASELINES = {'build-baseline': 'pom.xml', 'logging-baseline': 'src/main/resources/logback.xml'}
JAVA_TOKEN_PATH = 'src/main/java/__BASE_PACKAGE_PATH__/'
LEVELS = {'TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'OFF'}
FORMS = {
    'service_name': (r'[a-z][a-z0-9]*(-[a-z0-9]+)*', 'lowercase kebab-case'),
    'artifact_id': (r'[a-z][a-z0-9]*(-[a-z0-9]+)*', 'lowercase kebab-case'),
    'base_package': (r'[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)*', 'lowercase dot-separated Java package'),
    'group_id': (r'[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)*', 'Maven groupId'),
    'project_version': (r'\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?', 'Maven version'),
    'application_class': (r'[A-Z][A-Za-z0-9]*Application', 'UpperCamelCase ending in Application'),
    'container_port': (r'\d{1,5}', 'integer 1-65535'),
    'log_time_zone': (r'[A-Za-z][A-Za-z0-9_+\-/]*', 'Java time-zone identifier'),
    'time_zone': (r'[A-Za-z][A-Za-z0-9_+\-/]*', 'Java time-zone identifier'),
}
LEVEL_PARAMS = ('root_log_level', 'application_log_level', 'corporate_logger_level', 'http_log_level')


class AssemblyError(RuntimeError):
    def __init__(self, kind: str, message: str, details=None):
        super().__init__(f'{kind}: {message}')
        self.kind, self.details = kind, details or {}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parameter_table(archetype_dir: Path) -> dict:
    """{token: parameter name} from archetype.yml#/parameters (the archetype owns the token vocabulary)."""
    data = yaml.safe_load((archetype_dir / 'archetype.yml').read_bytes())
    return {p['token']: p['name'] for p in data.get('parameters', []) if p.get('token')}


def resolve_parameters(plan: dict, ws_dir: Path) -> tuple[dict, dict]:
    """(values, provenance). Plan/derived values first; the workspace generation-parameters `values` fill the rest; a disagreement is a conflict, never a silent choice."""
    svc = plan['service']
    path = Path(ws_dir) / 'generation-parameters.yml'
    supplied = ((yaml.safe_load(path.read_bytes()) or {}).get('values') or {}) if path.is_file() else {}
    derived = {'service_name': (svc.get('name'), 'plan.service.name'), 'base_package': (svc.get('package'), 'plan.service.package'),
               'base_package_path': (svc.get('packagePath'), 'plan.service.packagePath'),
               'artifact_id': (svc.get('name'), 'plan.service.name (artifact id = service name)'),
               'group_id': (svc.get('groupId') or svc.get('package'), 'plan.service.groupId, else base_package (D-010)'),
               'project_version': (svc.get('projectVersion') or '1.0.0-SNAPSHOT', 'plan.service.projectVersion, else the approved default (D-010)')}
    if svc.get('applicationClass'):
        derived['application_class'] = (svc['applicationClass'], 'plan.service.applicationClass')
    values, provenance, conflicts = {}, {}, []
    for name, (value, source) in derived.items():
        if value is None:
            continue
        values[name], provenance[name] = value, source
        if name in supplied and str(supplied[name]) != str(value):
            conflicts.append({'parameter': name, 'plan': value, 'generationParameters': supplied[name]})
    for name, value in supplied.items():
        if name not in values and value is not None:
            values[name], provenance[name] = value, 'workspace generation-parameters.yml#/values'
    if conflicts:
        raise AssemblyError('parameter-conflict', 'the plan and the workspace generation parameters disagree; nothing was written', {'conflicts': conflicts})
    return values, provenance


def check_forms(values: dict, used: set):
    bad = []
    for name in sorted(used):
        value = values.get(name)
        if value is None or name in ('external_secret_additional_data', 'specification_owned_application_properties'):
            continue
        text = str(value)
        if name in FORMS and not re.fullmatch(FORMS[name][0], text):
            bad.append({'parameter': name, 'value': text, 'expected': FORMS[name][1]})
        elif name == 'container_port' and not 1 <= int(text) <= 65535:
            bad.append({'parameter': name, 'value': text, 'expected': 'integer 1-65535'})
        elif name in LEVEL_PARAMS and text.upper() not in LEVELS:
            bad.append({'parameter': name, 'value': text, 'expected': 'one of ' + ', '.join(sorted(LEVELS))})
    if bad:
        raise AssemblyError('invalid-parameter', 'a parameter value does not have the archetype valid form; nothing was written', {'invalid': bad})


def properties_example(archetype_dir: Path, values: dict) -> bytes:
    """application.properties from archetype.yml#/runtime/application_properties only (the real application.properties is never read). Secrets are ${ENV} placeholders."""
    data = yaml.safe_load((archetype_dir / 'archetype.yml').read_bytes())
    config = (data.get('runtime') or {}).get('application_properties')
    if not config:
        raise AssemblyError('missing-archetype-config', 'archetype.yml does not define runtime.application_properties; nothing was written')
    names = {p['token']: p['name'] for p in data.get('parameters', []) if p.get('token')}
    missing = []

    def fill(text):
        for token in sorted(set(TOKEN.findall(str(text)))):
            name = names.get(token)
            if name is None:
                raise AssemblyError('unknown-token', 'archetype.yml runtime.application_properties uses an undeclared token', {'tokens': [token]})
            if values.get(name) is None:
                missing.append({'parameter': name, 'token': token, 'neededBy': [EXAMPLE]})
            else:
                text = str(text).replace(token, str(values[name]))
        return text
    rows = {}
    for key, value in (config.get('static') or {}).items():
        rows[key] = str(value).lower() if isinstance(value, bool) else str(value)
    for key, value in (config.get('parameterized') or {}).items():
        rows[fill(key)] = fill(value)
    for key, env in (config.get('environment_only') or {}).items():
        rows[key] = '${' + env + '}'
    if missing:
        raise AssemblyError('missing-parameter', 'required parameters are not defined; nothing was written. Provide them (approved values) and run again', {'missing': missing})
    lines = ['# Application configuration generated from archetype.yml#/runtime/application_properties (no real values, no secrets).',
             '# Review each value for the target environment and export the environment variables referenced as ${NAME} (secrets must never be written in the file).', '']
    placed = set()
    for block, prefixes in BLOCKS:
        keys = sorted(k for k in rows if k.startswith(prefixes) and k not in placed)
        if keys:
            lines.append(f'# ===== {block} =====')
            lines += [f'{k}={rows[k]}' for k in keys]
            lines.append('')
            placed.update(keys)
    rest = sorted(set(rows) - placed)
    if rest:
        raise AssemblyError('unknown-config-key', 'archetype configuration keys do not belong to a known baseline block; nothing was written', {'keys': rest})
    text = '\n'.join(lines).rstrip('\n') + '\n'
    if unresolved(text):
        raise AssemblyError('unresolved-tokens', 'the example still contains tokens', {'tokens': unresolved(text)})
    return text.encode('utf-8')


def template_files(template_dir: Path) -> list[str]:
    from artifact_integrity import template_paths
    return template_paths(template_dir.parent)


def is_deployment(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in DEPLOYMENT)


def substitute(raw: bytes, mapping: dict, markers: dict) -> bytes:
    text = raw.decode('utf-8')
    for token, value in markers.items():
        lines = text.split('\n')
        out = []
        for line in lines:
            if token in line:
                if str(value).strip():
                    indent = re.match(r'\s*', line).group(0)
                    out.extend(indent + part for part in str(value).rstrip('\n').split('\n'))
                continue
            out.append(line)
        text = '\n'.join(out)
    for token in sorted(mapping, key=len, reverse=True):
        text = text.replace(token, str(mapping[token]))
    return text.encode('utf-8')


def unresolved(text: str) -> list[str]:
    return sorted(t for t in set(TOKEN.findall(text)) if t not in WRAPPER_IDENTIFIERS)


def render(plan: dict, repo: Path, ws_dir: Path, out_dir: Path) -> dict:
    """Pure rendering. Returns {'files': {path: {bytes, source, group}}, 'retainedExisting': [...], 'report': {...}}; raises AssemblyError before anything is written."""
    arch = plan['inputs']['archetype']
    template_dir = Path(repo) / arch['path'] / 'template'
    tokens = parameter_table(Path(repo) / arch['path'])
    values, provenance = resolve_parameters(plan, ws_dir)
    planned_paths = {fp.norm(f['path']) for f in plan['files']['generate'] if f.get('action') in ('create', 'update')
                     and f.get('componentType') not in (*PLANNED_BASELINES, 'existing-technical-baseline', 'runtime-database-configuration', 'generation-provenance-manifest')}
    baseline_entries = {f['path']: f for f in plan['files']['generate'] if f.get('componentType') in PLANNED_BASELINES}
    deploy_authorized = bool((plan.get('readiness') or {}).get('deploymentGenerationAuthorized'))
    package_path = values.get('base_package_path') or str(values.get('base_package', '')).replace('.', '/')
    recorded = fp.generated_hashes(out_dir)
    selected, skipped = [], []
    for rel in template_files(template_dir):
        target = rel.replace('__BASE_PACKAGE_PATH__', package_path).replace('__APPLICATION_CLASS__', str(values.get('application_class', '__APPLICATION_CLASS__')))
        if fp.is_excluded(target) or fp.is_excluded(rel):
            skipped.append({'path': target, 'reason': 'local environment configuration (application*.properties) is excluded by policy; it is never read, copied or written'})
        elif target in planned_paths:
            skipped.append({'path': target, 'reason': 'generated by the materializer from the plan'})
        elif is_deployment(rel) and not deploy_authorized:
            skipped.append({'path': target, 'reason': 'deploymentGenerationAuthorized is not true in the plan'})
        else:
            selected.append((rel, target))
    # parameters actually required by the selected files
    needed, token_files = set(), {}
    raw_by_rel = {}
    for rel, target in selected:
        raw = (template_dir / rel).read_bytes()
        raw_by_rel[rel] = raw
        for token in unresolved(raw.decode('utf-8')) + unresolved(rel):
            token_files.setdefault(token, []).append(target)
    unknown = sorted(t for t in token_files if t not in tokens)
    if unknown:
        raise AssemblyError('unknown-token', 'the archetype template uses tokens that archetype.yml does not declare; nothing was written', {'tokens': unknown})
    missing = []
    for token, files in sorted(token_files.items()):
        name = tokens[token]
        needed.add(name)
        if name not in values or values[name] is None:
            missing.append({'parameter': name, 'token': token, 'neededBy': sorted(set(files))[:6]})
    if missing:
        raise AssemblyError('missing-parameter', 'required parameters are not defined in the plan or in the workspace generation-parameters.yml (#/values); nothing was written. Provide them (approved values) and run again',
                            {'missing': missing})
    check_forms(values, needed)
    mapping = {token: values[tokens[token]] for token in token_files if token not in MARKER_TOKENS}
    markers = {token: values[tokens[token]] for token in token_files if token in MARKER_TOKENS}
    files, retained = {}, []
    for rel, target in selected:
        planned = baseline_entries.get(target)
        if planned and planned['action'] == 'retain' and (Path(out_dir) / target).is_file():
            retained.append({'path': target, 'reason': 'explicit retain action of the implementation plan'})
            continue
        raw = raw_by_rel[rel]
        data = substitute(raw, mapping, markers)
        if planned and planned.get('mavenAdditions'):
            data = pom_baseline.insert_additions(data.decode('utf-8'), planned['mavenAdditions']).encode('utf-8')
        if target.endswith('.java'):
            data = data.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
        left = unresolved(data.decode('utf-8'))
        if left:
            raise AssemblyError('unresolved-tokens', f'{target} still contains tokens after substitution; nothing was written', {'file': target, 'tokens': left})
        existing = Path(out_dir) / target
        if planned and planned.get('expectedSha256') and sha(data) != planned['expectedSha256']:
            raise AssemblyError('baseline-mismatch', f'{target}: assembler bytes do not match the planner expectedSha256; nothing was written')
        explicit_write = planned and planned['action'] in ('create', 'update')
        if existing.is_file() and fp.norm(target) not in recorded and not explicit_write:
            retained.append({'path': target, 'reason': 'exists in the output and is not tracked by the generation manifest: kept as is (never overwritten)'})
            continue
        group = 'deployment' if is_deployment(rel) else 'java' if target.endswith('.java') else 'build'
        files[target] = {'bytes': data, 'source': f'{arch["path"]}/template/{rel}', 'group': group, 'sha256': sha(data)}
    example_target = fp.norm(EXAMPLE)
    create_only = {}
    if (Path(out_dir) / example_target).exists():
        retained.append({'path': example_target, 'reason': 'exists in the output: never read, compared or overwritten (D-015)'})
    else:
        create_only[example_target] = properties_example(Path(repo) / arch['path'], values)
    report = {'assembler': VERSION, 'archetype': arch['path'], 'parameters': {k: values[k] for k in sorted(needed) if k not in MARKER_TOKENS},
              'parameterSources': {k: provenance.get(k, 'unknown') for k in sorted(needed)}, 'markerParameters': sorted(tokens[t] for t in markers),
              'files': [{'path': p, 'group': files[p]['group'], 'source': files[p]['source']} for p in sorted(files)], 'retainedExisting': retained, 'notAssembled': skipped,
              'deploymentArtifacts': 'assembled' if deploy_authorized else 'not-authorized-by-plan',
              'applicationProperties': {'status': 'create-only-when-absent', 'path': EXAMPLE, 'note': 'src/main/resources/application.properties is created only when it does not exist and is never read, compared, tracked or overwritten afterwards (D-015). '
                                        'Export JWT_SECRET_KEY, DB_URL, DB_USERNAME and DB_PASSWORD (environment-only).'}}
    report['parametersSha256'] = sha(yaml.safe_dump({k: str(values[k]) for k in sorted(needed)}, sort_keys=True).encode('utf-8'))
    return {'files': files, 'createOnly': create_only, 'retainedExisting': retained, 'report': report}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Checks the assembly parameters of a service without writing anything.')
    parser.add_argument('service')
    args = parser.parse_args(argv)
    repo = Path.cwd().resolve()
    ws = repo / '.factory' / 'services' / args.service
    plan = yaml.safe_load((ws / 'implementation-plan.yml').read_bytes())
    try:
        result = render(plan, repo, ws, repo / plan['service']['outputDirectory'])
    except AssemblyError as error:
        print(f'assemble_project: {error}', file=sys.stderr)
        print(yaml.safe_dump(error.details, allow_unicode=True), file=sys.stderr)
        return 3
    print(yaml.safe_dump({k: v for k, v in result['report'].items() if k != 'files'}, allow_unicode=True, sort_keys=False))
    print(f'{len(result["files"])} file(s) would be assembled')
    return 0


if __name__ == '__main__':
    sys.exit(main())
