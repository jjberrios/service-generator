"""Deterministic full planning for the reference-owned Spring XML batch profile."""
from pathlib import Path
import re

import build_implementation_plan as base
from batch_shell_contract import PROFILE, identifier, require, validate, features_of

TOKEN = re.compile(r'@@([A-Z][A-Z0-9_]*)@@')


def safe_path(path):
    require(isinstance(path, str) and path and '\\' not in path and ':' not in path
            and not path.startswith('/') and not set(path.split('/')) & {'', '.', '..'}, f'unsafe path {path!r}')
    return path


def substitute(text, values):
    missing = set(TOKEN.findall(text)) - set(values)
    require(not missing, f'unresolved template parameters {sorted(missing)}')
    text = TOKEN.sub(lambda m: values[m.group(1)], text)
    require(not TOKEN.search(text), 'remaining template tokens')
    return text


def build(repo, spec, cfg):
    """Pure planning; file reads are limited to the selected archetype, never reference sources."""
    require(not set(spec) - {'service', 'batch', 'readiness', 'unresolved', 'validation', 'sources',
                            'traceability', 'warnings', 'statistics', 'operations', 'inactive'}, 'unsupported specification sections')
    require(not set(cfg) - {'target', 'template_parameters'}, 'unsupported planning input sections')
    target = cfg['target']
    require(not set(target) - {'service', 'archetype', 'output_directory'}, 'batch identity belongs in explicit template_parameters')
    service = target['service']
    require(re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', service), 'unsafe service name')
    require(spec.get('service', {}).get('name') == service and spec['service'].get('profile') == 'batch-shell', 'wrong service/profile')
    require(target.get('output_directory') == f'output/{service}', 'output must be output/<service>')
    require(not spec.get('operations') and not spec.get('inactive'), 'HTTP/inactive operations are not supported by this batch IR')
    require(not any((spec.get('unresolved') or {}).values()), 'unresolved functional specification')
    require(not (spec.get('validation') or {}).get('errors'), 'specification validation failed')
    ready = spec.get('readiness') or {}
    require(ready.get('functionalCodeGenerationReady') is True and ready.get('strictImplementationReady') is True
            and not ready.get('blockers') and not ready.get('incompleteOperations'), 'full batch readiness is required')
    arch_path = safe_path(target['archetype'])
    require(arch_path.startswith('archetypes/'), 'archetype must be versioned under archetypes/')
    arch_root = repo / arch_path
    require(arch_root.resolve().is_relative_to((repo / 'archetypes').resolve()), 'archetype escapes repository')
    yaml = base.yaml_module()
    arch, _ = base.read_yaml(arch_root / 'archetype.yml', repo, yaml)
    generation, identity = arch.get('generation', {}), arch.get('identity', {})
    features = features_of(generation)
    unsupported = [m['id'] for m in generation.get('featureModules', ()) if isinstance(m, dict)
                   and m.get('defaultEnabled') is True and m['id'] not in features]
    require(not unsupported, f'archetype feature modules not implemented by this backend: {unsupported}')
    batch = validate(spec.get('batch'), features)
    require(generation.get('profile') == PROFILE and identity.get('profile') == 'batch-shell', 'archetype profile mismatch')
    require(identity.get('approved') is True and identity.get('generationEnabled') is True, 'archetype not approved/enabled for generation')
    platform = arch.get('platform') or {}
    require(platform.get('java') == '1.8' and platform.get('springBoot') == 'not-used'
            and platform.get('springStyle') == 'xml-context-plus-component-scan-annotations'
            and platform.get('httpEndpoints') == 'none', 'unsupported batch platform')
    style = generation.get('style') or {}
    require(style.get('constantsClass') == 'util.Constantes' and style.get('externalPropertiesClass') == 'util.PropertiesExterno'
            and style.get('hardcodedLiterals') == 'allowed', 'unsupported or missing reference style')
    require(generation.get('packaging', {}).get('type') == 'jar'
            and generation.get('persistence', {}).get('mechanism') == 'not-present-in-reference'
            and generation.get('tests', {}).get('framework') == 'JUnit4'
            and generation.get('quality', {}).get('checkstyle') == 'not-applicable'
            and generation.get('logging', {}).get('activityLogger') == 'not-applicable', 'unsupported technical baseline')
    values = dict(cfg.get('template_parameters') or {})
    allowed = set(arch['parameters'])
    require(not set(values) - allowed, 'unknown template parameter')
    for key in allowed - {'BASE_PACKAGE_PATH', 'SERVICE_FIELD'}:
        require(key in values and isinstance(values[key], str), f'explicit parameter {key} required')
    derived = {'BASE_PACKAGE_PATH': values['BASE_PACKAGE'].replace('.', '/'),
               'SERVICE_FIELD': values['SERVICE_INTERFACE'][:1].lower() + values['SERVICE_INTERFACE'][1:]}
    for key, value in derived.items():
        require(key not in values or values[key] == value, f'conflicting derived parameter {key}')
        values[key] = value
    for key, meta in arch['parameters'].items():
        require(re.fullmatch(meta['pattern'], values[key]), f'invalid parameter {key}')
    for part in values['BASE_PACKAGE'].split('.'):
        identifier(part)
    for key in ('MAIN_CLASS', 'SERVICE_INTERFACE', 'SERVICE_FIELD'):
        identifier(values[key])
    require(values['MAIN_CLASS'] != values['SERVICE_INTERFACE'], 'colliding class names')
    require(values['MAIN_CLASS'] not in (values['SERVICE_INTERFACE'] + 'Impl', 'PropertiesExterno'), 'colliding Spring component names')
    entries = []
    template_root = arch_root / 'template'
    declared = {e['path'] for e in arch['templateInventory']}
    actual = {p.relative_to(template_root).as_posix() for p in template_root.rglob('*') if p.is_file()}
    require(actual == declared, 'archetype template inventory differs from actual files')
    for rel in sorted(declared):
        safe_path(rel)
        require(not Path(rel).name.lower().startswith('application') or not rel.lower().endswith('.properties'), 'protected configuration in template')
        source = template_root / rel
        require(source.resolve().is_relative_to(template_root.resolve()), 'template symlink escapes archetype')
        path = safe_path(substitute(rel, values))
        substitute(source.read_text(encoding='utf-8'), values)
        entries.append({'path': path, 'action': 'update' if (repo / target['output_directory'] / path).exists() else 'create',
                        'componentType': 'batch-archetype-template', 'template': rel})
    package = values['BASE_PACKAGE_PATH']
    for root, name, ct in (('src/main/java', values['SERVICE_INTERFACE'] + 'Impl', 'batch-service'),
                           ('src/test/java', values['SERVICE_INTERFACE'] + 'ImplTest', 'batch-unit-test')):
        path = f'{root}/{package}/service/{name}.java'
        entries.append({'path': path, 'action': 'update' if (repo / target['output_directory'] / path).exists() else 'create', 'componentType': ct})
    require(len({e['path'] for e in entries}) == len(entries), 'planned path collision')
    return {'plan': {'version': 3, 'mode': 'full', 'profile': PROFILE},
            'service': {'name': service, 'profile': 'batch-shell', 'basePackage': values['BASE_PACKAGE'], 'outputDirectory': target['output_directory']},
            'inputs': {'archetype': {'path': arch_path, 'fingerprint': base.archetype_fingerprint(arch_root)}},
            'templateParameters': values, 'batch': batch, 'technicalProfile': generation,
            'readiness': ready, 'qualityGates': {'checkstyle': {'status': 'not-applicable', 'reason': 'not-present-in-reference'}},
            'files': {'generate': entries}, 'generation': {'functionalGenerationReady': True},
            'limitations': ['Database persistence, mail notification, nested loops and unrecognized steps are unsupported; SOAP credential decryption only when the archetype feature credential-decrypt-soap is implemented.',
                            'External properties/log4j and Lib/ artifacts must be supplied by the operator.',
                            'Maven, runtime, remote connections and coverage are not verified by materialization.']}


def write_plan(repo, yaml, planning_input):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'service-workspace' / 'scripts'))
    import consistency_gate as gate
    path = repo / planning_input
    cfg, raw_cfg = base.read_yaml(path, repo, yaml)
    ws = path.parent
    gate.check_cleared(ws, repo, cfg['target']['service'])
    state, _ = base.read_yaml(ws / 'service-generation-state.yml', repo, yaml)
    require(cfg['target']['archetype'] == state['archetype']['path'], 'planning input differs from selected archetype')
    spec, raw_spec = base.read_yaml(ws / 'service-spec.yml', repo, yaml)
    try:
        plan = build(repo, spec, cfg)
    except ValueError as error:
        raise base.PlanError(str(error)) from error
    params = {'parameters': {'version': 2, 'profile': PROFILE}, 'values': plan['templateParameters']}
    params_raw = base.dump_yaml(params, yaml)
    plan['inputs'].update({'serviceSpec': {'artifactSha256': base.sha256(raw_spec)},
                          'generationParameters': {'path': '.factory/generation-parameters.yml', 'sha256': base.sha256(params_raw)},
                          'planningInput': {'path': '.factory/full-planning-input.yml', 'sha256': base.sha256(raw_cfg)}})
    raw_plan = base.dump_yaml(plan, yaml)
    # All checks precede writes; reproducible bytes, no timestamps.
    from artifact_integrity import write_atomic, safe_path
    for name in ('generation-parameters.yml', 'implementation-plan.yml'):
        safe_path(ws, name)
    for name, payload in (('generation-parameters.yml', params_raw), ('implementation-plan.yml', raw_plan)):
        dst = ws / name
        require(not dst.is_symlink(), 'artifact symlink is forbidden')
        write_atomic(dst, payload)
    print({'profile': PROFILE, 'files': len(plan['files']['generate']), 'sha256': base.sha256(raw_plan)})
    return 0
