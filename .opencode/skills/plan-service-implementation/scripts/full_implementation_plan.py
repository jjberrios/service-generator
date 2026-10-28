"""Full relational planning from the approved service spec, never raw Sparx.

Persistence technology is inherited from the approved archetype (`archetype.yml#/persistence`,
decision D-011): Spring Data JPA / Hibernate / Oracle / HikariCP. The planner may not select
another technology for simplicity; an override needs explicit user instruction or an explicit
target technical requirement, and no alternative backend is implemented (fails closed).

Domain names, connection coordinates and technical selections are planning inputs.
Business mappings and SQL action kinds come exclusively from service-spec.yml.
This module writes plans/parameters only; it cannot materialize application files.
"""
from __future__ import annotations

import copy
import hashlib
import unicodedata
import json
import re
from pathlib import Path
from typing import Any

import build_implementation_plan as base
import pom_baseline as pom

SPEC = Path('.factory/service-spec.yml')
PARAMS = Path('.factory/generation-parameters.yml')
PLAN = Path('.factory/implementation-plan.yml')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unref(node: Any) -> dict:
    while isinstance(node, dict) and isinstance(node.get('resolved'), dict):
        node = node['resolved']
    return node or {}


def ref(pointer: str) -> str:
    return f'.factory/service-spec.yml#{pointer}'


def check(condition: bool, message: str) -> None:
    if not condition:
        raise base.PlanError(message)


def checkstyle_gate(archetype: dict, archetype_root: Path, planned_paths: list[str]) -> dict:
    """D-014: the reference Checkstyle is a mandatory gate for generated main AND test Java; fail closed when it is not defined."""
    quality = (archetype.get('quality') or {}).get('checkstyle') or {}
    check(quality.get('mandatory_generation_gate') is True and quality.get('approved_decision') == 'D-014',
          'archetype quality.checkstyle must declare the mandatory generation gate (D-014); refusing to plan without it')
    check(quality.get('include_test_source_directory') is True and set(quality.get('sources') or []) == {'src/main/java', 'src/test/java'},
          'Checkstyle gate must cover src/main/java and src/test/java (includeTestSourceDirectory=true)')
    check(not quality.get('suppressions_allowed') and not quality.get('generated_code_exclusions_allowed') and not quality.get('weakening_allowed'),
          'Checkstyle rules may not be weakened, suppressed or excluded for generated code')
    config_file = archetype_root / 'template' / quality['config']
    check(config_file.is_file(), 'reference checkstyle.xml is missing from the archetype template')
    main = sorted(p for p in planned_paths if p.startswith('src/main/java/') and p.endswith('.java'))
    tests = sorted(p for p in planned_paths if p.startswith('src/test/java/') and p.endswith('.java'))
    return {'decision': 'D-014', 'mandatory': True, 'authority': quality['authority'], 'config': quality['config'], 'configSha256': digest(config_file),
            'sources': ['src/main/java', 'src/test/java'], 'includeTestSourceDirectory': True,
            'suppressionsAllowed': False, 'generatedCodeExclusionsAllowed': False, 'weakeningAllowed': False,
            'syntaxParseSubstitutesCheckstyle': False, 'knownViolatingPatternsToAvoid': list(quality.get('known_violating_patterns') or []),
            'appliesTo': {'mainJavaFiles': main, 'testJavaFiles': tests},
            'validationOrder': ['expected file inventory', 'Java syntax', 'imports and basic structure', 'reference Checkstyle (main and test)', 'generation manifest consistency'],
            'verification': {'command': 'mvnw -s settings.xml validate', 'offlineVariant': 'mvnw -o -s settings.xml validate', 'passRequires': '0 violations',
                             'unexecutableStatus': 'unverified'},
            'completionRule': 'Generation is not complete until the Checkstyle gate is passed with 0 violations; unverified or failed blocks completion.'}


def persistence_authority(archetype: dict, config: dict) -> dict:
    """Persistence technology authority: explicit user instruction > target technical requirement > archetype."""
    inherited = archetype.get('persistence') or {}
    check(inherited.get('technology') == 'spring-data-jpa' and inherited.get('inherited_from_archetype') is True,
          'The archetype declares no inherited persistence architecture (archetype.yml#/persistence, D-011).')
    technical = config['technical']
    requested = technical.get('persistence_mechanism', inherited['technology'])
    override = technical.get('persistence_override')
    if requested != inherited['technology']:
        valid = (isinstance(override, dict) and override.get('authority') in ('explicit-user-instruction', 'explicit-target-technical-requirement')
                 and override.get('provenance'))
        check(bool(valid), f"Persistence technology '{requested}' differs from the archetype ({inherited['technology']}) without an explicit user instruction or target technical requirement; simplicity is not a reason.")
        raise base.PlanError(f"Technical planning failure: persistence override '{requested}' is authorized but no backend is implemented; extend the planner explicitly.")
    return {'technology': inherited['technology'], 'provider': inherited['provider'], 'pool': inherited['connection_pool'],
            'source': 'archetype', 'decision': inherited['approved_decision'], 'override': None}


def context(root: Path, yaml: Any, input_path: Path) -> tuple:
    service, _ = base.read_yaml(root / SPEC, root, yaml)
    config, _ = base.read_yaml(root / input_path, root, yaml)
    target = config['target']
    archetype_root = root / target['archetype']
    archetype, _ = base.read_yaml(archetype_root / 'archetype.yml', root, yaml)
    ready = service.get('readiness', {})
    check(ready.get('functionalCodeGenerationReady') is True, 'Full planning requires functionalCodeGenerationReady: true.')
    check(ready.get('strictImplementationReady') is True, 'Full planning requires strictImplementationReady: true.')
    check(target['service'] == service['service']['name'], 'Planning target differs from service-spec.')
    active_keys = {(o['method'], o['path']) for o in service['operations']}
    inactive_keys = {(o['method'], o['path']) for o in service.get('inactive', {}).get('operations', [])}
    check(not (active_keys & inactive_keys), 'Active/inactive operation collision.')
    check(not any(service.get('unresolved', {}).values()), 'Full planning cannot omit unresolved business requirements.')
    persistence_authority(archetype, config)
    check(config['technical']['database_product'] == 'oracle', 'This relational backend implements the Oracle dialect only.')
    check(re.fullmatch(r'[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+', target['base_package']) is not None, 'Unsafe Java package.')
    check(not Path(target['output_directory']).is_absolute() and Path(target['output_directory']).parts[0] == 'output'
          and '..' not in Path(target['output_directory']).parts, 'Output must stay under output/.')
    return service, config, archetype, archetype_root


def parameters(root: Path, yaml: Any, input_path: Path, ctx: tuple) -> dict:
    service, config, archetype, archetype_root = ctx
    # Previously approved engineering values of THIS service workspace, when a prior generation-parameters.yml exists; a new service starts from the archetype.
    prior = base.read_yaml(root / PARAMS, root, yaml)[0] if (root / PARAMS).is_file() else {}
    # Previous parameters are a source of approved engineering values, not behavior.
    archetype_names = {item['name'] for item in archetype.get('parameters', [])}
    # Obsolete/superseded parameters (for example POM exclusion and POM repository parameters removed by D-012) are dropped.
    resolved = {r['name']: copy.deepcopy(r) for r in prior.get('resolved', [])
                if r.get('value') is not None and r['name'] in archetype_names and not r['name'].startswith(('vault_', 'k8s_', 'secret_'))}
    target = config['target']
    current = {'base_package': target['base_package'], 'base_package_path': target['base_package'].replace('.', '/'),
               'group_id': target['group_id'], 'project_version': target['project_version'],
               'service_name': target['service'], 'artifact_id': target['service'],
               'application_class': base.pascal(target['service']) + 'Application'}
    for key in ('application_log_level', 'corporate_logger_level', 'http_log_level', 'root_log_level', 'log_time_zone', 'jwt_roles_claim'):
        current[key] = config['technical'][key]
    for name, value in current.items():
        resolved[name] = {**resolved.get(name, {}), 'name': name, 'value': value,
                          'status': 'approved-target-value' if name in target else 'technical-implementation-choice',
                          'source': f'{input_path.as_posix()}#/' + ('target' if name in target else 'technical'),
                          'required': True}
    current['java_version'] = archetype['platform']['java']['version']
    current['spring_boot_version'] = archetype['platform']['spring_boot']['version']
    for name in ('java_version', 'spring_boot_version'):
        resolved[name] = {'name': name, 'value': current[name], 'status': 'archetype-baseline',
                          'source': target['archetype'] + '/archetype.yml#/platform', 'required': True}
    # Do not carry scaffold-era empty service-property payload into functional generation.
    resolved.pop('specification_owned_application_properties', None)
    resolved.pop('external_secret_additional_data', None)
    baseline = pom.baseline_config(archetype)
    maven_values = {sub['parameter']: current[sub['parameter']] for sub in baseline['substitutions']}
    check(digest_bytes((archetype_root / baseline['template']).read_bytes()) == baseline['template_sha256'],
          'Archetype POM template differs from the recorded reference baseline hash (D-012).')
    additions = copy.deepcopy(config['technical'].get('maven_additions') or [])
    for addition in additions:
        check(bool(addition.get('justification')) and bool(addition.get('requiredBy')),
              f"Maven addition {addition.get('artifactId')} needs a justification and requiredBy (D-012).")
    template = archetype_root / 'template/src/main/resources/application.properties'
    template_text = template.read_text(encoding='utf-8')
    blocks = re.findall(r'# = ([A-Za-z /]+)\r?\n', template_text)
    check('SUBTYPES IDF' not in template_text and not re.search(r'(?m)^(subtype|detail|message)\.', template_text), 'Archetype properties template contains excluded domain sections.')
    check(all(v in template_text for v in ('${DB_URL}', '${DB_USERNAME}', '${DB_PASSWORD}')), 'Archetype template must use environment datasource values.')
    db = {'spring.datasource.url': '${DB_URL}', 'spring.datasource.username': '${DB_USERNAME}', 'spring.datasource.password': '${DB_PASSWORD}',
          'spring.datasource.driver-class-name': 'oracle.jdbc.OracleDriver'}
    return {'version': 2, 'mode': 'full', 'service': target['service'], 'values': current,
            'approvedResolutions': prior.get('approvedResolutions', []),
            'resolved': [resolved[k] for k in sorted(resolved)], 'unresolved': [],
            'inputs': {'serviceSpec': {'path': SPEC.as_posix(), 'sha256': digest(root / SPEC)},
                       'archetype': {'path': target['archetype'], 'fingerprint': base.archetype_fingerprint(archetype_root)},
                       'planningInput': {'path': input_path.as_posix(), 'sha256': digest(root / input_path)}},
            'functional': {'naming': config['naming'], 'technical': config['technical'],
                           'database': {'environmentVariables': ['DB_URL', 'DB_USERNAME', 'DB_PASSWORD'],
                                        'nonSecretConnectionExample': config['technical']['jdbc_url'],
                                        'properties': db, 'credentialValues': 'runtime environment only; no defaults or stored values',
                                        'connectionTestPerformed': False},
                           'runtimeEnvironmentOnly': ['JWT_SECRET_KEY'],
                           'persistence': persistence_authority(archetype, config),
                           'applicationProperties': {'renderFrom': template.relative_to(root).as_posix(), 'sha256': digest(template), 'baselineBlocks': blocks,
                                                     'replacements': {'__SERVICE_NAME__': target['service'], '__BASE_PACKAGE__': target['base_package'],
                                                                      '__JWT_ROLES_CLAIM__': config['technical']['jwt_roles_claim']},
                                                     'explicitTargetPort': target.get('server_port'),
                                                     'excludedSections': ['SUBTYPES IDF (subtype.*, detail.*, message.*)'],
'referenceCredentialsCopied': False},
                           'maven': {'baseline': 'reference-pom (D-012)', 'mandatory': True, 'templatePath': baseline['template'], 'templateSha256': baseline['template_sha256'],
                                     'referenceSha256': baseline['reference_sha256'], 'values': maven_values,
                                     'inventory': {k: len(v) for k, v in baseline['inventory'].items()}, 'additions': additions,
                                     'pruningBaselineItemsAllowed': False}},
            'readiness': {'functionalGenerationReady': True, 'deploymentGenerationAuthorized': False,
                          'databaseExecutionReady': 'not assessed; existing schema/key generator and credentials must be provisioned at runtime'},
            'secretsStored': False, 'validation': {'errors': []}}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


ROLE_RULES = {
    'transactionId': {'mandatory': True},
    'userId': {'mandatory': False},
    'applicationName': {'mandatory': False},
}


def activity_key(name: str) -> tuple[str, str, str]:
    """'1. Validar parametros' -> (1, 'VALIDAR_PARAMETROS', 'ACT1_VALIDAR_PARAMETROS'). Deterministic, traceable to the spec name."""
    match = re.match(r'^\s*(\d+)\s*[.)-]\s*(.+?)\s*$', name)
    check(match is not None, f"Activity '{name}' has no leading ordinal; constants cannot be derived deterministically (D-013).")
    ordinal, label = match.group(1), match.group(2)
    folded = ''.join(c for c in unicodedata.normalize('NFKD', label) if not unicodedata.combining(c))
    value = re.sub(r'[^A-Za-z0-9]+', '_', folded).strip('_').upper()
    check(bool(value), f"Activity '{name}' normalizes to an empty constant.")
    return ordinal, value, f'ACT{ordinal}_{value}'


def header_roles(header_names: list[str], overrides: dict) -> dict:
    """Map reference RequestHeaders roles to declared target headers (explicit override > deterministic derivation)."""
    names = sorted(header_names)
    simple = {n: re.sub(r'[^a-z0-9]', '', re.sub(r'^x-', '', n.lower())) for n in names}
    roles: dict[str, dict] = {}
    for role in ROLE_RULES:
        if overrides.get(role):
            check(overrides[role] in names, f"Header role '{role}' is mapped to '{overrides[role]}', which the contract does not declare.")
            roles[role] = {'header': overrides[role], 'source': 'explicit-planning-input'}
            continue
        if role == 'transactionId':
            exact = [n for n in names if simple[n] == 'transactionid']
            candidates = exact or [n for n in names if 'correlation' in n.lower()]
        elif role == 'userId':
            candidates = [n for n in names if simple[n] == 'userid']
        else:
            candidates = [n for n in names if simple[n] in ('applicationname', 'appid')]
        if len(candidates) == 1:
            roles[role] = {'header': candidates[0], 'source': 'derived-by-archetype-role-matching'}
        else:
            check(not ROLE_RULES[role]['mandatory'], f"Header role '{role}' is ambiguous or missing ({candidates}); map it explicitly in technical.header_roles (D-013).")
    return roles


def activity_logging_plan(service: dict, config: dict, archetype: dict, operations: list[dict]) -> dict:
    """Derive the activity-logging plan from service-spec and the archetype convention (D-013); no raw sources."""
    convention = archetype.get('activity_logging') or {}
    check(convention.get('mandatory') is True and convention.get('approved_decision') == 'D-013',
          'The archetype declares no mandatory activity-logging convention (archetype.yml#/activity_logging, D-013).')
    header_sets = [{h['name'] for h in op['contract']['headers']['request']} for op in service['operations']]
    declared = sorted(set.intersection(*header_sets)) if header_sets else []
    roles = header_roles(declared, (config['technical'].get('header_roles') or {}))
    ops = []
    constants: dict[str, dict] = {}
    for index, (spec_op, plan_op) in enumerate(zip(service['operations'], operations)):
        behavior = spec_op['behavior']
        sources = behavior['sources']
        by_name = {sources['validationActivity']['name']: ('validation', sources['validationActivity']),
                   sources['behaviorActivity']['name']: ('behavior', sources['behaviorActivity'])}
        edges = behavior['processes'][0]['flow']['normal']
        start = [e for e in edges if e['fromRole'] == 'startEvent']
        check(len(start) == 1, f"{spec_op['operationId']}: the normal flow must have exactly one start edge.")
        chain, current = [], start[0]
        seen = set()
        while current['toRole'] == 'activity':
            check(current['to'] not in seen, 'Cyclic activity flow.')
            seen.add(current['to'])
            check(current['to'] in by_name, f"{spec_op['operationId']}: flow activity '{current['to']}' has no authoritative source activity in service-spec.")
            chain.append(current)
            following = [e for e in edges if e['from'] == current['to'] and e['fromRole'] == 'activity']
            check(len(following) == 1, f"{spec_op['operationId']}: ambiguous or missing successor of '{current['to']}'.")
            current = following[0]
        check(current['toRole'] == 'endEvent' and bool(chain), f"{spec_op['operationId']}: the normal flow does not end in an end event.")
        sequence = []
        for order, edge in enumerate(chain, 1):
            role, source = by_name[edge['to']]
            ordinal, value, constant = activity_key(edge['to'])
            entry = constants.setdefault(constant, {'constant': constant, 'value': value, 'activityName': edge['to'], 'role': role, 'usedBy': [], 'sources': []})
            check(entry['value'] == value and entry['role'] == role, f"Activity constant {constant} would be ambiguous across operations.")
            entry['usedBy'].append(spec_op['operationId'])
            entry['sources'].append({'operationId': spec_op['operationId'], 'activityUuid': source['uuid'], 'page': source['page'], 'pageSha256': source.get('pageSha256'),
                                     'flowEvidence': edge['evidence']})
            action = plan_op['actionKind']
            wraps = (['request-entry logging helper', 'domain validation'] if role == 'validation' else
                     {'select': ['repository search', 'empty-result outcome'], 'insert': ['entity mapping', 'repository save'],
                      'update': ['load entity by key', 'not-found outcome', 'apply supplied properties', 'repository save']}[action])
            sequence.append({'order': order, 'constant': constant, 'value': value, 'sourceActivity': edge['to'], 'role': role,
                             'sourceActivityUuid': source['uuid'], 'flowEvidence': edge['evidence'], 'wraps': wraps,
                             'startEndLogging': 'ActivityLogger.inicioActividad/finActividad through ejecutarActividad', 'technicalErrorLogging': role == 'behavior'})
        behavior_act = next(a for a in sequence if a['role'] == 'behavior')
        outcomes = plan_op['outcomes']['byStatus']
        business = [{'activity': behavior_act['constant'], 'status': int(code), 'condition': info['condition'],
                     'logPattern': 'ERROR_BUSINESS_PATTERN code={} detail={}', 'thenThrows': 'business exception with the approved status'}
                    for code, info in sorted(outcomes.items()) if code == '404']
        validation_act = next(a for a in sequence if a['role'] == 'validation')
        business.append({'activity': validation_act['constant'], 'status': 400, 'condition': outcomes['400']['condition'],
                         'logPattern': 'ejecutarActividad business-exception log: ERROR [activity] message=', 'thenThrows': 'business exception with the approved status'})
        contract = spec_op['contract']
        params = contract.get('parameters') or {}
        request_values = [p['name'] for k in ('path', 'query') for p in (params.get(k) or [])]
        body = contract.get('requestBody')
        body_type = base.field_java_type(next(iter(body['content'].values()))['schema']) if body else None
        operation_id = spec_op['operationId']
        verb = re.match(r'[a-z]+', operation_id).group(0)
        label = operation_id[0].upper() + operation_id[1:]
        ops.append({
            'operationId': operation_id, 'method': spec_op['method'], 'path': spec_op['path'],
            'transactionSource': {'headerRole': 'transactionId', 'header': roles['transactionId']['header'], 'component': 'RequestHeaders.transactionId',
                                  'prefix': 'String tx = headers != null ? headers.transactionId() : null; String menTran = tx != null ? "[" + tx + "] " : NO_TRANSACTION_PREFIX;',
                                  'noTransactionPrefix': '[SIN-TRANSACTION] '},
            'requestEntryLogging': {'controller': {'message': f"{operation_id} - transactionId: {{}}" + (', usuario: {}' if plan_op['actionKind'] != 'select' else ''),
                                                   'arguments': ['transactionId'] + (['userId'] if plan_op['actionKind'] != 'select' else [])},
                                    'serviceHelper': f"log{verb.capitalize()}", 'metadataLabel': label,
                                    'metadataFields': [r for r in ('applicationName', 'transactionId', 'userId') if r in roles], 'requestValues': request_values,
                                    'insideActivity': validation_act['constant']},
            'bodyLogging': ({'helper': 'ActivityLogger.logContenido', 'message': f'{label} body: {{}}', 'type': body_type, 'applies': True,
                             'neverBodyToString': True, 'masking': 'none in the reference; none added'} if body else {'applies': False}),
            'activitySequence': sequence,
            'startEndLogging': 'ActivityLogger.inicioActividad / ActivityLogger.finActividad inside ejecutarActividad for every activity',
            'businessErrorLogging': business,
            'technicalErrorLogging': [{'activity': behavior_act['constant'], 'exception': 'QueryTimeoutException', 'logConstant': f"LOG_TIMEOUT_{behavior_act['constant']}",
                                       'pattern': 'ERROR_TECHNICAL_PATTERN', 'then': 'approved persistence error translation (status mapping unchanged)'},
                                      {'activity': behavior_act['constant'], 'exception': 'DataAccessException', 'logConstant': f"LOG_ERROR_DATOS_{behavior_act['constant']}",
                                       'pattern': 'ERROR_TECHNICAL_PATTERN', 'then': 'approved persistence error translation (status mapping unchanged)'}],
            'unexpectedExceptions': 'logged by ejecutarActividad as unexpected exception and rethrown',
            'activityLoggerUsage': ['inicioActividad', 'finActividad'] + (['logContenido'] if body else []),
            'sourceRefs': [ref(f'/operations/{index}/behavior/processes'), ref(f'/operations/{index}/behavior/actions')],
        })
    for entry in constants.values():
        if entry['role'] == 'behavior':
            entry['logMessages'] = {f"LOG_TIMEOUT_{entry['constant']}": f"Timeout en la actividad {entry['value']}: ",
                                    f"LOG_ERROR_DATOS_{entry['constant']}": f"Error de acceso a datos en la actividad {entry['value']}: "}
    validation_constants = sorted({a['constant'] for o in ops for a in o['activitySequence'] if a['role'] == 'validation'})
    return {
        'decision': 'D-013', 'mandatory': True, 'archetypeSection': 'archetype.yml#/activity_logging',
        'requestHeaders': {'location': 'dto/request/RequestHeaders', 'type': 'record', 'roles': roles,
                           'components': [r for r in ('transactionId', 'userId', 'applicationName') if r in roles],
                           'omittedReferenceRoles': ['msgid', 'timestamp'] + [r for r in ROLE_RULES if r not in roles and r != 'transactionId'],
                           'note': 'transactionId is a technical header (never a business field); declared headers without a reference role are not carried'},
        'serviceMethodsReceiveRequestHeaders': True, 'activityWrapper': convention['activity_wrapper']['name'],
        'activityConstants': sorted(constants.values(), key=lambda e: e['constant']),
        'validationActivityShared': len(validation_constants) == 1, 'handlerValidationActivity': validation_constants[0] if len(validation_constants) == 1 else None,
        'transactionHeaderConstant': roles['transactionId']['header'],
        'logger': {'declaration': 'Lombok @Slf4j (reference)', 'activityLoggerPackage': 'utils', 'constantsClass': 'utils/ConstanApi'},
        'masking': 'none (reference applies none)', 'inventedActivities': False, 'operations': ops,
    }


IGNORED_OUTPUT = ('.idea/', 'target/', '.git/')
IGNORED_SUFFIXES = ('.iml',)


def jpa_type(column: dict, primary_key: bool) -> dict:
    """Reference conventions: Long keys, Integer flags, String text (Lob for CLOB), LocalDateTime dates."""
    sql_type = column['dataType'].upper()
    if sql_type.startswith(('CLOB', 'NCLOB')):
        return {'javaType': 'String', 'lob': True}
    if sql_type.startswith(('VARCHAR', 'CHAR', 'NVARCHAR')):
        return {'javaType': 'String', 'lob': False}
    if sql_type.startswith('DATE') or sql_type.startswith('TIMESTAMP'):
        return {'javaType': 'LocalDateTime', 'lob': False}
    match = re.fullmatch(r'NUMBER(?:\((\d+)(?:,(\d+))?\))?', sql_type)
    if match:
        precision, scale = int(match.group(1) or 0), int(match.group(2) or 0)
        if scale > 0:
            return {'javaType': 'BigDecimal', 'lob': False}
        if primary_key or precision == 0 or precision > 9:
            return {'javaType': 'Long', 'lob': False}
        return {'javaType': 'Integer', 'lob': False}
    raise base.PlanError(f'No JPA type policy for {sql_type}.')


def column_mapping(entry: dict, columns: dict, properties: dict, pk: str) -> dict:
    column = entry['column']['physicalColumn']
    check(column in columns, f'Effective column {column} absent from table.')
    return {**copy.deepcopy(entry), 'physicalColumn': column, 'modelProperty': properties[column], **jpa_type(columns[column], column == pk)}


def operation_plan(operation: dict, index: int, table: dict, names: dict, pk: str) -> dict:
    pointer = f'/operations/{index}'
    behavior = operation['behavior']
    check(len(behavior['persistence']) == 1, 'Full JPA planning requires one explicit persistence action per operation.')
    persistence = behavior['persistence'][0]
    action = persistence['actionKind']
    check(action in ('select', 'insert', 'update'), f'Unsupported literal persistence action {action}.')
    columns = {c['column']: c for c in table['columns']}
    properties = names['properties']
    result = {'operationId': operation['operationId'], 'method': operation['method'], 'path': operation['path'],
              'actionKind': action, 'sourceRefs': [ref(pointer + '/contract'), ref(pointer + '/behavior')],
              'businessAuthority': behavior['authoritativeBranch'], 'contract': copy.deepcopy(operation['contract']),
              'effectiveStatusCodes': sorted(r['status'] for r in operation['contract']['effectiveResponses']),
              'effectiveContractDeltas': copy.deepcopy(operation['contract'].get('contractDeltas', [])),
              'validation': copy.deepcopy(behavior['validations']), 'outcomes': copy.deepcopy(behavior['errors'][0]),
              'flow': copy.deepcopy(behavior['processes'][0]['flow']), 'modelMappings': [],
              'technicalChoiceRefs': ['persistence', 'conversion', 'validation', 'errors', 'transactions', 'audit-timestamps'],
              'doNotExecuteTraceabilityDml': True}
    if action == 'select':
        query = persistence['query']
        filters = [column_mapping(f, columns, properties, pk) for f in query['businessFilters']]
        selected = [column_mapping(s, columns, properties, pk) for s in query['selectedColumns']]
        result['query'] = {'filterPolicy': copy.deepcopy(query['filterPolicy']), 'filters': filters, 'selectedColumns': selected,
                           'pagination': copy.deepcopy(query['pagination']), 'orderBy': copy.deepcopy(query['orderBy']),
                           'mechanism': 'Spring Data JPA: repository extends JpaRepository plus JpaSpecificationExecutor; Specification built with the Criteria API',
                           'algorithm': ['Validate supplied business filters and the limit/offset pairing before any repository call.',
                                         'Add one Criteria predicate per supplied filter from the whitelist of mapped entity properties; values are bound by the JPA provider.',
                                         'Combine the active predicates with the approved combinator (OR) in one Specification; absent filters add no predicate.',
                                         'Text filters: LOWER(attribute) LIKE lowered pattern with escaped wildcards (literal contains). Numeric filters: equality on the typed attribute.',
                                         'Always sort ascending by the entity key; with both pagination inputs use an offset-based Pageable (absolute offset, limit as page size), otherwise sort only.',
                                         'Map entities to the declared response fields only; apply the specified empty-result outcome.'],
                           'containsExpression': 'cb.like(cb.lower(attribute), escapedLoweredPattern, escapeChar)',
                           'exactExpression': 'cb.equal(attribute, typedValue)',
                           'textPatternPolicy': '%, _ and the escape character in user input are escaped so contains is a literal substring; do not trim or split comma-delimited values.',
                           'noManualSql': True}
        result['modelMappings'] = selected
    else:
        key = 'columnValues' if action == 'insert' else 'assignments'
        writes = [column_mapping(e, columns, properties, pk) for e in persistence[key]]
        result['write'] = {'mappings': writes, 'suppliedValuesOnly': copy.deepcopy(persistence['suppliedValuesOnly']),
                           'mechanism': 'Spring Data JPA repository.save on the mapped entity',
                           'algorithm': (['Create the entity from supplied request values using the explicit property mappings; leave omitted properties null.',
                                          'Set the audit user from the user header mapping and the audit date with the reference convention LocalDateTime.now(ZoneId.systemDefault()).',
                                          'Save once; omitted (null) properties do not appear in the INSERT (@DynamicInsert) so database defaults are preserved.',
                                          'Do not expose the generated key in an undeclared public response.']
                                         if action == 'insert' else
                                         ['Load the entity by the path key with repository.findById; absent -> specified not-found outcome without saving.',
                                          'Apply only supplied request properties (internal presence tracking) through the explicit mappings.',
                                          'Set the audit user and audit date (reference convention) only after the entity was found.',
                                          'Save once; only changed columns appear in the UPDATE (@DynamicUpdate), so omitted properties are not overwritten.'])}
        result['modelMappings'] = writes
        result['auditHeaderMappings'] = copy.deepcopy(behavior['mappings'][0].get('headerDerivedMappings', []))
        if action == 'update':
            result['write']['where'] = [column_mapping(w, columns, properties, pk) for w in persistence['whereClause']]
            result['write']['noMatchingRecordOutcome'] = copy.deepcopy(persistence['noMatchingRecordOutcome'])
            result['write']['presencePolicy'] = 'Track declared JSON property presence in request setters; reject present null for nonnullable input schemas, update supplied values only; no audit-only update.'
    return result


def cases(operation: dict) -> list[dict]:
    """Test expectations are selected by effective persistence features, not HTTP->CRUD inference."""
    rows = []

    def add(name, given, expect):
        rows.append({'case': name, 'given': given, 'expect': expect, 'sourceRefs': operation['sourceRefs']})
    action = operation['actionKind']
    if action == 'select':
        add('single-filter', 'One supplied business filter', 'Only that predicate participates; nonempty result returns 200')
        add('multiple-or-filters', 'Two supplied filters matching different rows', 'OR composition of the supplied predicates, not AND; omitted filters add no predicate')
        add('textual-contains', 'Text containing literal %, _ or quote characters', 'Case-insensitive literal contains through the Specification; wildcard characters are escaped; values are bound')
        add('exact-nontext-filters', 'Each numeric filter separately supplied', 'Exact typed equality; no substring comparison; canonical numeric output without invented zero-padding')
        add('pagination', 'Both limit and offset supplied with a business filter', 'Offset-based Pageable with the absolute offset and limit, sorted by the key; never converted to a page index')
        add('limit-without-offset', 'Only pagination limit supplied', '400 and repository not invoked')
        add('offset-without-limit', 'Only pagination offset supplied', '400 and repository not invoked')
        add('no-filter', 'Headers and pagination controls only', '400; headers, limit and offset do not count as business filters')
        add('invalid-filter-value', 'Invalid numeric identifier, undeclared flag value or invalid pagination value', '400; do not invoke the repository or silently coerce the input')
        add('empty-result', 'Query returns no entities', '404')
        add('response-exposure', 'Stored entity also has audit properties', 'Only declared response fields are serialized; reviewed output mapping is applied')
    elif action == 'insert':
        add('creation', 'Valid body with all required fields and invoking-user header', '200; entity populated from the explicit mappings, audit user from the user header, audit date from the application clock')
        add('conditional-required', 'Related business identifier present but recipient absent', '400; specification conditional validation exercised apart from contract-required fields')
        add('validation-failure', 'Required field missing or invalid email/enum/numeric value', '400; no save')
        add('explicit-null', 'Optional but nonnullable declared request field explicitly null', '400 during JSON binding; absence remains permitted')
        add('generated-key', 'Repository save returns the entity with its IDENTITY-generated key', 'Key populated by the persistence provider, never invented by the service and not exposed as a new response field')
        add('optional-fields', 'Optional fields omitted', 'Properties stay null so @DynamicInsert omits their columns; no invented default value')
        add('unique-conflict', 'Oracle unique-constraint violation surfaced as a Spring data-access exception', '409 with the existing ErrorResponse shape; original OpenAPI omission remains in provenance')
    elif action == 'update':
        add('partial-single-field', 'Exactly one mutable field supplied', 'Only that property plus the audit properties change on the loaded entity')
        add('multiple-fields', 'Several mutable fields supplied', 'Only supplied properties change, all others retained')
        for mapping in operation['write']['mappings']:
            value = mapping['value']
            if value.get('origin') == 'request':
                add('field-' + value['input'], f"Only {value['input']} supplied", f"{mapping['modelProperty']} changes; omitted properties keep their loaded values")
        add('no-body-field', 'Empty body object', '400; no repository access')
        add('explicit-null', 'Declared nonnullable field explicitly null', '400, distinguished from absent; never silently clear the stored value')
        add('target-not-found', 'findById returns empty', '404; nothing saved, no success envelope')
        add('unique-conflict', 'Oracle unique-constraint violation surfaced as a Spring data-access exception', '409 using ErrorResponse')
    for status, outcome in operation['outcomes']['byStatus'].items():
        if status in ('500', '503', '504'):
            add('error-' + status, outcome['condition'], f'Central advice maps to {status}; not every integrity or connection exception is 409')
    add('headers-separate', 'Technical request header differs from the business field', 'Correlation header never enters the entity mapping; only the specified invoking-user header drives audit')
    add('physical-mapping', 'Distinct values for every mapped field', 'Each field reaches its explicit entity property and physical column; audit columns are never exposed')
    return rows


def build_full(root: Path, yaml: Any, input_path: Path) -> tuple[dict, dict]:
    ctx = context(root, yaml, input_path)
    service, config, archetype, archetype_root = ctx
    persistence_info = persistence_authority(archetype, config)
    params = parameters(root, yaml, input_path, ctx)
    target = config['target']; prefix = config['naming']['domain_prefix']
    package_path = target['base_package'].replace('.', '/')
    main = f'src/main/java/{package_path}/'
    tests_root = f'src/test/java/{package_path}/'
    output = root / target['output_directory']
    all_files = [p for p in sorted(output.rglob('*')) if p.is_file()]
    check(not any(p.is_symlink() for p in output.rglob('*')), 'Existing output contains symlinks.')
    inventory = {p.relative_to(output).as_posix(): digest(p) for p in all_files
                 if not p.relative_to(output).as_posix().startswith(IGNORED_OUTPUT) and not p.name.endswith(IGNORED_SUFFIXES)}
    ignored_untracked = sorted(p.relative_to(output).as_posix() for p in all_files if p.relative_to(output).as_posix() not in inventory)
    prior_manifest_path = output / '.generation-manifest.yml'
    prior_manifest = base.read_yaml(prior_manifest_path, root, yaml)[0] if prior_manifest_path.exists() else {}
    prior_actions = {r['path']: r['action'] for r in prior_manifest.get('fileInventory', []) if isinstance(r, dict)}
    prior_technology = (prior_manifest.get('persistence') or {}).get('technology')
    persistence_changed = prior_technology != persistence_info['technology']
    logging_changed = (prior_manifest.get('activityLogging') or {}).get('decision') != 'D-013'
    definitions = service['behaviorContext']['architecturalEvidence']['dataDefinitions']
    tables = [t for t in definitions if t.get('columns')]
    check(len(tables) == 1, 'Full JPA planner currently requires one physical table; no silent multi-table inference.')
    table = tables[0]; table_name = table['identity']['name']; table_names = config['naming']['table_models'][table_name]
    check(set(table_names['properties']) == {c['column'] for c in table['columns']}, 'Property-name metadata must cover exactly the defined columns.')
    pk_decl = next(d for d in table['keyAndIndexDeclarations'] if d['kind'] == 'primaryKey')
    pk_column = pk_decl['parameters'].split(':', 1)[0].strip()
    operations = [operation_plan(o, i, table, table_names, pk_column) for i, o in enumerate(service['operations'])]
    logging_plan = activity_logging_plan(service, config, archetype, operations)
    served = [o['operationId'] for o in operations]
    method_operations = {o['operationId']: o for o in operations}
    ids_by_action = {kind: [o['operationId'] for o in operations if o['actionKind'] == kind] for kind in ('select', 'insert', 'update')}
    models, _ = base.collect_models(service)
    api_name = base.pascal(target['service']) + 'Api'
    entity_class = table_names['class_name']
    files = {}
    technical_choices = {
        'persistence': {'mechanism': 'Spring Data JPA + Hibernate + Oracle + HikariCP, inherited from the approved archetype',
                        'authority': f"{target['archetype']}/archetype.yml#/persistence (D-011); order: explicit user instruction, target technical requirement, archetype",
                        'override': None, 'jdbcSelectionForSimplicityForbidden': True,
                        'rules': ['@Entity in the model package with Lombok and @Table/@Column; no schema attribute because the specification defines none.',
                                  'Repository: @Repository interface extending JpaRepository<Entity, Long>; JpaSpecificationExecutor is added only because the specified GET needs dynamic OR filters (the reference has no dynamic-query mechanism).',
                                  'No NamedParameterJdbcTemplate, hand-built SQL, SQL builder or RowMapper.']},
        'entity-dml-shaping': {'mechanism': '@DynamicInsert and @DynamicUpdate (Hibernate) on the entity',
                               'reason': 'Target requirement, not a reference convention: only supplied values participate in INSERT/SET, database defaults for omitted columns are preserved and omitted fields are not rewritten.',
                               'rules': ['Applied only to the target entity; does not change the archetype convention.']},
        'case': {'mechanism': 'Criteria LOWER(attribute) LIKE lowered pattern with escaped wildcards', 'authority': ref('/humanDecisions/applied/0/approvedResolution/caseSensitivity'),
                 'reason': 'Case sensitivity is a technical implementation choice; the pattern is a bound value, never concatenated into a query.'},
        'conversion': {'mechanism': 'Reference types: Long for NUMBER keys, Integer for NUMBER(1), BigDecimal for NUMBER with scale, String for CLOB (@Lob) and VARCHAR2, LocalDateTime for DATE',
                       'rules': ['No zero-padding, rounding, truncation, splitting comma lists or forced string trimming.', 'Numeric parse failures and invalid declared enums return 400.',
                                 'An invalid stored value that cannot map to the declared response shape is another failure (500); never silently coerce it to a declared value.',
                                 'Identifiers that are not integral numbers fit a Long key only when exactly representable; otherwise 400.']},
        'validation': {'mechanism': 'Bean Validation owns contract annotations; one domain validator owns cross-field, presence, enum/numeric conversion validation',
                       'rules': ['Do not duplicate Bean Validation annotations on the implementing controller method; follow the interface contract.',
                                 'Setter presence tracking is internal @JsonIgnore metadata, never a new public field.',
                                 'Absent optional field differs from present null; reject explicit null when the schema is nonnullable.',
                                 'Check at least one mutable supplied value before an update; no header/audit-only writes.']},
        'errors': {'mechanism': '@RestControllerAdvice + one typed service exception + one data-access translator used by the service (reference pattern: catch around repository calls)',
                   'rules': ['400 for validation/binding/parse failures, 404 only per recorded query/update conditions.',
                             '409 only for unique violation (Oracle vendor code 1 found in the exception cause chain); not for all DataIntegrityViolationException.',
                             '504 for SQL/query timeouts; timeout is checked before availability.',
                             '503 for unavailable database/connection acquisition (including transaction-creation failures); 500 for other persistence/runtime failures.',
                             'Use the existing ErrorResponse; for 409 use the same schema and HTTP Conflict without an invented subtype or schema.',
                             'Restrict public statuses to the operation effective matrix; an unexpected unique failure during a read is a 500, not an undeclared 409.',
                             'Do not expose credentials, connection details or raw database errors in response bodies.']},
        'transactions': {'mechanism': 'No explicit @Transactional (reference convention); Spring Data repository methods are transactional',
                         'rules': ['PATCH is findById followed by one save; absence of the entity decides 404.', 'A concurrent delete between load and save is an accepted residual risk.']},
        'audit-timestamps': {'mechanism': 'LocalDateTime.now(ZoneId.systemDefault()) set in the service before save (reference convention)',
                             'reason': 'Reference-compatible; the previous database SYSDATE expression is replaced by the application clock.',
                             'rules': ['Creation date only on insert; last-modified date only on an update that found its entity.']},
        'generated-id': {'mechanism': '@GeneratedValue(strategy = GenerationType.IDENTITY) on the primary key (reference convention); the saved entity carries the key',
                         'assumption': config['technical']['generated_id_assumption'],
                         'rules': ['No sequence name, MAX(ID)+1 or application-generated key is invented.', 'Oracle must provide an identity/default mechanism for the key column.'],
                         'runtimeVerificationRequired': True},
        'testing': {'mechanism': 'JUnit Jupiter/Mockito, MockMvcWebTestClient bound to Spring MVC controllers and advice; Criteria collaborators mocked for Specification tests',
                    'rules': ['WebFlux is test-scope only; the application remains MVC.', 'No live database required for unit/contract tests.',
                              'Oracle dialect, Hibernate CLOB/LOWER/LIKE behavior, IDENTITY and schema validation require a later authorized database environment; H2 is not proof.']},
        'activity-logging': {'mechanism': 'Reference ActivityLogger pattern (D-013): ActivityLogger/ConstanApi from the archetype template, RequestHeaders, ejecutarActividad wrapper, per-operation request logging helpers, reference business/technical error logging',
                             'authority': f"{target['archetype']}/archetype.yml#/activity_logging",
                             'rules': ['Activity constants derive only from the authoritative activities in service-spec; no invented activities.', 'The transaction identifier is a mapped technical header, never a business field.', 'No masking is added (reference applies none).', 'Logging is instrumentation; the approved status mapping and return values are unchanged.']},
        'runtime': {'mechanism': 'Application properties rendered from the archetype template: reference blocks APPLICATION, LOGGING, SWAGGER, ACTUATOR, DATA SOURCE, HIKARI, JPA / HIBERNATE, JWT TOKEN, SPRING CLOUD',
                    'rules': ['Datasource values only through DB_URL, DB_USERNAME and DB_PASSWORD; no credentials stored or copied from the reference.', 'SUBTYPES IDF is excluded.',
                              'Preserve the temporary permissive JWT baseline and the D-002 no-fallback secret.']},
    }

    def add(path, component, responsibilities, op_ids=None, refs=None, deps=None, phase=3, mapping_refs=None, validation=None,
            errors=None, persistence=None, test_cases=None, update=False, persistence_dependent=False, changes=None, remove=False,
            logging_dependent=False):
        check(path not in files, f'Duplicate planned file {path}')
        op_ids = served if op_ids is None else op_ids
        refs = refs or [ref(f'/operations/{i}/behavior') for i, o in enumerate(service['operations']) if o['operationId'] in op_ids]
        exists = path in inventory
        if remove:
            action = 'remove'
        elif exists:
            action = 'update' if (update or (persistence_dependent and persistence_changed) or (logging_dependent and logging_changed)) else 'retain'
        else:
            action = 'create'
        files[path] = {'path': path, 'action': action, 'componentType': component, 'operationsServed': op_ids,
                       'sourceSpecificationRefs': refs, 'behaviorResponsibilities': responsibilities,
                       'mappingsUsed': mapping_refs or [], 'dependencies': deps or [],
                       'validationResponsibilities': validation or [], 'errorResponsibilities': errors or [],
                       'persistenceResponsibilities': persistence or [], 'testResponsibilities': test_cases or [],
                       'technicalChoiceRefs': [], 'generationPhase': phase, 'existingSha256': inventory.get(path),
                       'plannedChanges': (changes or responsibilities) if action in ('update', 'remove') else (changes or [])}
    api_file = main + 'controller/' + api_name + '.java'
    controller_file = main + 'controller/impl/' + prefix + 'Controller.java'
    service_file = main + 'service/' + prefix + 'Service.java'
    service_impl = main + 'service/impl/' + prefix + 'ServiceImpl.java'
    entity_file = main + 'model/' + entity_class + '.java'
    repo_file = main + 'repository/' + prefix + 'Repository.java'
    spec_file = main + 'repository/' + prefix + 'Specifications.java'
    offset_file = main + 'repository/OffsetLimitRequest.java'
    mapper_file = main + 'dto/mapper/' + prefix + 'Mapper.java'
    validator_file = main + 'validation/' + prefix + 'Validator.java'
    query_file = main + 'model/' + prefix + 'SearchCriteria.java'
    exception_file = main + 'exception/ServiceOperationException.java'
    translator_file = main + 'exception/PersistenceExceptionTranslator.java'
    handler_file = main + 'exception/GlobalExceptionHandler.java'
    all_refs = [ref(f'/operations/{i}/behavior') for i in range(len(operations))]
    mapping_pointers = [ref(f'/operations/{i}/behavior/persistence/0') for i in range(len(operations))]
    add(api_file, 'contract-api-interface', ['Retain signatures, methods/routes, required headers and schemas; effective 409 documentation is already present.'],
        refs=[ref(f'/operations/{i}/contract') for i in range(len(operations))], phase=1)
    dto_files = []
    for model in models:
        scopes = set(model['requestResponseScope'])
        folder = 'request' if scopes == {'request'} else 'response' if scopes == {'response'} else 'contract'
        path = main + f"dto/{folder}/{model['name']}.java"
        model['filePath'] = path; dto_files.append(path)
        is_request = scopes == {'request'}
        is_patch = any(method_operations[o]['actionKind'] == 'update' for o in model['sourceOperations'] if o in method_operations) and is_request
        already_compatible = False
        if path in inventory:
            text = (output / path).read_text(encoding='utf-8')
            declared = set(re.findall(r'private\s+[\w<>]+\s+(\w+)\s*;', text))
            check(declared == {f['name'] for f in model['fields']}, f'Existing DTO {path} differs from consolidated contract; review rather than blind retention.')
            already_compatible = (not is_request) or ('Nulls.FAIL' in text and '@JsonInclude(JsonInclude.Include.NON_NULL)' in text and (not is_patch or 'suppliedFields' in text))
        add(path, 'contract-dto', ['Preserve contract fields, types and declared validation annotations.'],
            op_ids=model['sourceOperations'], refs=[ref(model['traceability'])], phase=1, update=is_request and not already_compatible,
            validation=['Bean Validation for declared constraints; enum/value checks are centralized in the validator.'],
            changes=(['Nonnullable declared-field setters use @JsonSetter(nulls=Nulls.FAIL); omitted optional fields stay allowed.',
                      'Class-level @JsonInclude(NON_NULL) so ActivityLogger.logContenido (convertValue round trip) can process the DTO without tripping Nulls.FAIL (D-013).'] if is_request else [])
                    + (['Internal @JsonIgnore presence set tracks supplied properties; no extra public JSON property.'] if is_patch else []))
    files[api_file]['dependencies'] = list(dto_files)
    dto_by_name = {model['name']: model['filePath'] for model in models}
    for model in models:
        fields = ' '.join(field['javaType'] for field in model['fields'])
        referenced = set(re.findall(r'\b[A-Za-z][A-Za-z0-9]*\b', fields))
        files[model['filePath']]['dependencies'] = sorted(dto_by_name[n] for n in referenced if n in dto_by_name and n != model['name'])
    add(entity_file, 'jpa-entity', [f'JPA entity for {table_name} with the exact authoritative columns; reference annotation conventions; no TEMPLATEID, extra columns, schema or sequence.'],
        refs=[ref('/behaviorContext/architecturalEvidence/dataDefinitions/0')], phase=1,
        persistence=['@Entity, @Table(name), @Id + @GeneratedValue(IDENTITY), @Column(name) per field, @Lob for CLOB columns, Lombok @Data/@NoArgsConstructor/@AllArgsConstructor, @DynamicInsert/@DynamicUpdate (target requirement).'],
        persistence_dependent=True)
    add(query_file, 'internal-query-model', ['Typed supplied-filter values and absolute offset/limit; not a public API DTO.'], op_ids=ids_by_action['select'], refs=all_refs, phase=1,
        mapping_refs=mapping_pointers, persistence_dependent=True)
    add(exception_file, 'internal-typed-exception', ['Internal operation context and status/category only; no new public error DTO.'], phase=1)
    add(validator_file, 'business-validator', ['Validate approved cross-field/presence rules and convert numeric values (Long keys, Integer flags, BigDecimal request id) once.'], phase=2,
        deps=[exception_file, query_file], persistence_dependent=True,
        validation=['Contract required/format constraints remain Bean Validation responsibilities.', 'GET requires one supplied business filter; limit/offset paired.', 'POST conditional required rule preserved.', 'PATCH requires a supplied mutable field; enforce nonnullable explicit null rules.'])
    add(mapper_file, 'explicit-contract-data-mapper', ['Apply every specified mapping between contract, entity properties and response fields with explicit code; never rely on property-name coincidence.'],
        phase=2, mapping_refs=mapping_pointers, deps=[entity_file, query_file] + dto_files, persistence_dependent=True,
        validation=['Use validator conversion results; avoid repeated parsing.'])
    add(repo_file, 'spring-data-jpa-repository', [f'@Repository interface extending JpaRepository<{entity_class}, Long> and JpaSpecificationExecutor<{entity_class}> (dynamic OR filters); no custom SQL.'],
        phase=2, deps=[entity_file], persistence=['save/findById from JpaRepository; findAll(Specification, Sort/Pageable) from JpaSpecificationExecutor.'], persistence_dependent=True)
    add(spec_file, 'jpa-specification', ['Criteria-API Specification that ORs the supplied predicates: equality for typed numeric attributes, LOWER/LIKE contains with escaped wildcards for text attributes.'],
        op_ids=ids_by_action['select'], phase=2, deps=[entity_file, query_file], mapping_refs=mapping_pointers,
        persistence=['Whitelist of mapped entity attributes; values bound by the provider; empty predicate list never queries everything.'])
    add(offset_file, 'offset-based-pageable', ['Pageable implementation carrying an arbitrary absolute offset, page size = limit and the key sort, so limit/offset need not be page aligned.'],
        op_ids=ids_by_action['select'], phase=2, persistence=['Used only when both pagination inputs are supplied.'])
    add(translator_file, 'data-access-error-translator', ['Classify data-access/persistence cause chains into evidence-backed statuses (409, 503, 504, 500).'], phase=2, deps=[exception_file],
        persistence_dependent=True, errors=['Unique vendor error 1 -> 409; SQL/query timeout -> 504; connection/transaction-creation failure -> 503; other errors -> 500.'])
    logger_file = main + 'utils/ActivityLogger.java'
    constants_file = main + 'utils/ConstanApi.java'
    headers_file = main + 'dto/request/RequestHeaders.java'
    add(logger_file, 'archetype-activity-logger', ['ActivityLogger utility copied from the archetype template (reference pattern): inicioActividad, finActividad, logContenido (D-013).'],
        op_ids=served, phase=1, refs=[f"{target['archetype']}/archetype.yml#/activity_logging", f"{target['archetype']}/template/src/main/java/__BASE_PACKAGE_PATH__/utils/ActivityLogger.java"],
        deps=[constants_file])
    add(constants_file, 'activity-constants', ['Reference technical separators from the archetype template plus the activity and log-message constants generated from the authoritative activities of service-spec (D-013).'],
        op_ids=served, phase=0, refs=[f"{target['archetype']}/template/src/main/java/__BASE_PACKAGE_PATH__/utils/ConstanApi.java"] + [r for o in logging_plan['operations'] for r in o['sourceRefs']])
    files[constants_file]['activityConstants'] = logging_plan['activityConstants']
    files[constants_file]['insertAfter'] = '// ================= ACTIVIDADES (LOGS) ================='
    add(headers_file, 'request-headers-model', ['Java record of the technical header roles mapped from declared target headers (transactionId mandatory); no business field.'],
        op_ids=served, phase=1, refs=[ref(f'/operations/{i}/contract/headers') for i in range(len(operations))])
    files[headers_file]['components'] = logging_plan['requestHeaders']['components']
    files[headers_file]['roleMapping'] = logging_plan['requestHeaders']['roles']
    add(service_file, 'application-service-contract', ['Use the archetype service/service-impl seam with one method per active operation; every method receives RequestHeaders first (D-013).'], phase=3, deps=[entity_file, query_file, headers_file], logging_dependent=True)
    add(service_impl, 'application-service-implementation', ['Validate, persist through the JPA repository with data-access translation, map outcomes; reference-style audit timestamps; no @Transactional.'],
        phase=4, deps=[service_file, repo_file, spec_file, offset_file, mapper_file, validator_file, exception_file, translator_file], mapping_refs=mapping_pointers,
        persistence_dependent=True, logging_dependent=True, validation=['One validation owner for business rules; POST conditional rule preserved.'],
        errors=['Apply the source-defined empty-query and not-found outcomes; wrap repository calls and translate DataAccessException.',
                'Log business errors inside the activity (ERROR [activity] code= detail=) and QueryTimeoutException/DataAccessException with the LOG_* constants, then translate unchanged.'],
        changes=['Add @Slf4j, RequestHeaders parameter, NO_TRANSACTION_PREFIX/menTran, ejecutarActividad wrapper around every authoritative activity, per-operation request-logging helpers, ActivityLogger.logContenido for bodies (D-013).'])
    files[service_impl]['dependencies'] += [logger_file, constants_file, headers_file]
    files[service_impl]['activityLogging'] = logging_plan['operations']
    add(handler_file, 'central-contract-error-advice', ['@RestControllerAdvice maps MVC binding/validation errors and typed persistence/application outcomes to the existing ErrorResponse.'],
        phase=4, deps=[exception_file, translator_file] + [p for p in dto_files if p.endswith('/ErrorResponse.java')],
        errors=['Use operation-specific contract examples where present; no raw SQL/credential leakage, invented subtype or public schema.'],
        logging_dependent=True, changes=['Log the business exception and the framework 400 failures under the shared validation activity with ActivityLogger (reference handler pattern); status mapping unchanged (D-013).'])
    files[handler_file]['dependencies'] += [logger_file, constants_file]
    files[handler_file]['activityLogging'] = {'validationActivity': logging_plan['handlerValidationActivity'], 'transactionHeader': logging_plan['transactionHeaderConstant']}
    add(controller_file, 'controller-implementation', ['Implement the existing API interface exactly; delegate behavior, do not duplicate mapping or Bean Validation annotations.'],
        phase=5, deps=[api_file, service_file], mapping_refs=mapping_pointers,
        logging_dependent=True, validation=['Build RequestHeaders from the mapped technical headers; the user header goes only to declared audit inputs.'],
        errors=['Let centralized advice map typed exceptions; no local catch-all HTTP 200 fallback.'],
        changes=['Add @Slf4j, the controller entry log per operation and construct RequestHeaders for the service (D-013).'])
    files[controller_file]['dependencies'] += [headers_file]
    test_plan = {o['operationId']: cases(o) for o in operations}
    all_cases = [{'operationId': op_id, 'cases': values} for op_id, values in test_plan.items()]
    add(tests_root + 'controller/' + api_name + 'ContractTest.java', 'controller-contract-test', ['MVC WebTestClient contract tests for exactly the active routes, with a mocked JPA repository.'],
        phase=6, persistence_dependent=True, logging_dependent=True, deps=[controller_file, handler_file, repo_file, service_impl, headers_file], test_cases=all_cases)
    for folder, name, dep, text, pd in [
        ('service/impl', prefix + 'ServiceImplTest', service_impl, 'Mockito tests: sequencing, validation, 404/409/503/504/500 outcomes, supplied-only PATCH on a loaded entity, audit properties; activity wrapper preserves return values and rethrows business and technical exceptions (D-013).', True),
        ('validation', prefix + 'ValidatorTest', validator_file, 'GET filter/pagination pairing; POST conditional required; PATCH presence/null; Long/Integer/BigDecimal conversion.', True),
        ('dto/mapper', prefix + 'MapperTest', mapper_file, 'Each physical mapping with distinct sentinel values; only declared response fields; user-header/audit distinction.', True),
        ('repository', prefix + 'SpecificationsTest', spec_file, 'Specification composition with a mocked Criteria API: OR of supplied predicates only, lowered escaped contains pattern, typed equality, empty criteria.', False),
        ('model', entity_class + 'Test', entity_file, 'Reflection test of @Entity/@Table/@Id/IDENTITY/@Column names, @Lob columns, dynamic DML annotations and absence of TEMPLATEID.', False),
        ('exception', 'GlobalExceptionHandlerTest', handler_file, 'Statuses 400/404/409/500/503/504; 409 only unique, timeout before availability; existing ErrorResponse; translator cases for transaction-creation failure.', True),
    ]:
        add(tests_root + folder + '/' + name + '.java', 'unit-mapping-persistence-test', [text], phase=6, deps=[dep], test_cases=all_cases, persistence_dependent=pd,
            logging_dependent=name in (prefix + 'ServiceImplTest', 'GlobalExceptionHandlerTest'))
    add(tests_root + 'utils/ActivityLoggerTest.java', 'archetype-activity-logger-test', ['Reference ActivityLoggerTest copied from the archetype template (logContenido success and serialization-error branches).'],
        op_ids=served, phase=6, deps=[logger_file], refs=[f"{target['archetype']}/template/src/test/java/__BASE_PACKAGE_PATH__/utils/ActivityLoggerTest.java"])
    add(tests_root + 'utils/' + prefix + 'ActivityLoggingTest.java', 'activity-logging-test',
        ['Logging utilities process the target request DTOs safely: logContenido logs (not errors) for POST and PATCH bodies, omits null/unsupplied properties and the internal presence set; start and end markers carry the transaction prefix.'],
        phase=6, deps=[logger_file, constants_file, headers_file], test_cases=[{'operationId': o['operationId'], 'cases': [
            {'case': 'body-logging-safe', 'given': 'Request DTO with omitted optional properties', 'expect': 'ActivityLogger.logContenido emits info, never the serialization error, and no internal field',
             'sourceRefs': o['sourceRefs']}]} for o in logging_plan['operations'] if o['bodyLogging']['applies']])
    maven = params['functional']['maven']
    baseline_cfg = pom.baseline_config(archetype)
    template_text = (archetype_root / baseline_cfg['template']).read_bytes().decode('utf-8')
    expected_pom = pom.render_pom(template_text, baseline_cfg, params['values'], maven['additions']).encode('utf-8')
    expected_pom_sha = digest_bytes(expected_pom)
    component_types = {f['componentType'] for f in files.values()}
    for addition in maven['additions']:
        check(addition['requiredBy'] in component_types, f"Maven addition {addition['artifactId']} is required by '{addition['requiredBy']}', which is not a planned component.")
    pom_changed = inventory.get('pom.xml') != expected_pom_sha
    add('pom.xml', 'build-baseline', ['Render the mandatory reference POM baseline (archetype template, D-012) with the target identifiers plus the justified target-specific additions; never prune a baseline item.'],
        phase=0, update=pom_changed, refs=[f"{target['archetype']}/archetype.yml#/maven/reference_pom_baseline", f"{target['archetype']}/{baseline_cfg['template']}", ref('/behaviorContext/persistence')],
        changes=['Replace the reduced dependency set with the complete reference baseline: all 17 properties (repository-url, tomcat, claro-common-utilities, json, commons-io, httpclient5, jackson.databind.nullable versions), the three repositories composed from repository-url, all 21 dependencies (claro-common-utilities, tomcat-embed-core, micrometer-tracing-bridge-brave, commons-io, json, spring-kafka and httpclient5 added), plugin configuration and the local profile.',
                 'Target identifiers: group id, artifact id and name, version, Sonar application class and JaCoCo package path.', 'Keep only the justified target-specific additions after the baseline.'])
    files['pom.xml']['renderFrom'] = f"{target['archetype']}/{baseline_cfg['template']}"
    files['pom.xml']['expectedSha256'] = expected_pom_sha
    files['pom.xml']['mavenAdditions'] = copy.deepcopy(maven['additions'])
    files['pom.xml']['baselinePolicy'] = 'mandatory reference POM; pruning or altering baseline items is a generation defect'
    add('src/main/resources/application.properties', 'runtime-database-configuration',
        ['Render the archetype application.properties baseline (reference blocks, SUBTYPES IDF excluded) with service-specific values; environment datasource values; no secrets.'],
        phase=0, persistence_dependent=True, refs=[f"{target['archetype']}/template/src/main/resources/application.properties", 'generation-parameters.yml#/functional/applicationProperties'])
    files['src/main/resources/application.properties']['renderFrom'] = params['functional']['applicationProperties']['renderFrom']
    files['src/main/resources/application.properties']['replacements'] = params['functional']['applicationProperties']['replacements']
    files['src/main/resources/application.properties']['excludedSections'] = params['functional']['applicationProperties']['excludedSections']
    add('src/main/resources/logback.xml', 'logging-baseline', ['Render approved JSON-console/corporate logging template with runtime logging parameters.'], phase=0,
        refs=[f"{target['archetype']}/template/src/main/resources/logback.xml"])
    add('.generation-manifest.yml', 'generation-provenance-manifest', ['Refresh full-generation provenance after materialization: persistence technology, hashes, retained/updated/created/removed inventory.'],
        op_ids=[], phase=8, update=True, refs=['implementation-plan.yml#/inputs'],
        changes=['Record persistence technology and file inventory only after materialization.'])
    obsolete = [p for p in sorted(inventory) if p not in files and prior_actions.get(p) in ('create', 'update')
                and not p.startswith('src/main/resources/') and p != 'pom.xml']
    for path in obsolete:
        add(path, 'obsolete-persistence-artifact', ['Remove: superseded by the archetype JPA architecture (D-011); archived before removal.'], op_ids=[], phase=7, remove=True,
            refs=[f"{target['archetype']}/archetype.yml#/persistence"])
    for path in inventory:
        if path in files:
            continue
        add(path, 'existing-technical-baseline', ['Retain reviewed existing technical/bootstrap/security/build-quality file unchanged.'], op_ids=[], phase=0, refs=[f"{target['archetype']}/conventions.md"])
    for item in files.values():
        item['technicalChoiceRefs'] = ['#/technicalChoices/' + key for key in technical_choices if item['componentType'] not in ('existing-technical-baseline', 'obsolete-persistence-artifact')]
    files['.generation-manifest.yml']['dependencies'] = [path for path in files if path != '.generation-manifest.yml']
    operation_signatures = []
    for i, op in enumerate(operations):
        success_codes = [status for status in service['operations'][i]['contract']['responses'] if status.startswith('2')]
        check(len(success_codes) == 1, 'Full method signature needs one unambiguous successful response schema.')
        response_node = next(iter(service['operations'][i]['contract']['responses'][success_codes[0]]['content'].values()))['schema']
        response_type = base.field_java_type(response_node)
        body_node = service['operations'][i]['contract'].get('requestBody')
        body_type = base.field_java_type(next(iter(body_node['content'].values()))['schema']) if body_node else None
        action = op['actionKind']
        params_ = (['RequestHeaders headers', 'Map<String,String> rawBusinessFilters', 'Integer limit', 'Integer offset'] if action == 'select' else
                   ['RequestHeaders headers', f'{body_type} request'] if action == 'insert' else ['RequestHeaders headers', 'String pathId', f'{body_type} request'])
        operation_signatures.append({'operationId': op['operationId'], 'method': f"{response_type} {op['operationId']}({', '.join(params_)})",
                                     'contractRef': ref(f'/operations/{i}/contract'),
                                     'implementationSequence': ['derive menTran from headers.transactionId()', 'ejecutarActividad(validation activity): request logging helper + validator', 'ejecutarActividad(behavior activity): JPA repository action with technical-error logging and not-found/empty outcome', 'map to declared response DTO outside activities']})
    files[service_file]['methodSignatures'] = operation_signatures
    files[service_impl]['methodSignatures'] = operation_signatures
    files[repo_file]['methodSignatures'] = [m for m in [
        {'actionKind': 'select', 'method': f'List<{entity_class}> findAll(Specification<{entity_class}>, Sort) / Page<{entity_class}> findAll(Specification<{entity_class}>, Pageable)  [JpaSpecificationExecutor]'},
        {'actionKind': 'insert', 'method': f'{entity_class} save({entity_class})  [JpaRepository]'},
        {'actionKind': 'update', 'method': f'Optional<{entity_class}> findById(Long); {entity_class} save({entity_class})  [JpaRepository]'}] if ids_by_action[m['actionKind']]]
    files[query_file]['fields'] = [{'parameter': f['parameter'], 'javaType': f['javaType'], 'physicalColumn': f['physicalColumn']}
                                  for op in operations if op['actionKind'] == 'select' for f in op['query']['filters']]
    files[query_file]['fields'] += [{'parameter': key, 'javaType': 'Integer', 'physicalColumn': None} for key in ('limit', 'offset')]
    files[mapper_file]['methodPolicy'] = 'One explicit conversion per operation matrix; validated numeric values come from the validator and are not parsed twice. POST supplied fields are nonnull DTO values after Nulls.FAIL binding; PATCH supplied fields come from internal presence tracking and are applied to the loaded entity.'
    files[controller_file]['headerPolicy'] = 'Delegate all header arguments required by API binding; build RequestHeaders only from the mapped technical roles (transactionId, userId, applicationName). The user header drives audit through RequestHeaders.userId(); other technical headers (including the request-id header) stay technical and never become a business identifier.'
    pending = set(files); order = []
    while pending:
        eligible = sorted((p for p in pending if not (set(files[p]['dependencies']) & pending)), key=lambda p: (files[p]['generationPhase'], p))
        check(bool(eligible), 'Cyclic file dependency graph.')
        for p in eligible:
            check(set(files[p]['dependencies']) <= set(files), f'Unknown file dependency for {p}')
        order.extend(eligible); pending.difference_update(eligible)
    for number, p in enumerate(order, 1):
        files[p]['generationOrder'] = number
    model_matrix = [{'physicalColumn': c['column'], 'property': table_names['properties'][c['column']], 'sqlType': c['dataType'],
                     **jpa_type(c, c['column'] == pk_column), 'description': c.get('description'),
                     'sourceRefs': [ref(f'/behaviorContext/architecturalEvidence/dataDefinitions/0/columns/{i}')],
                     'primaryKey': c['column'] == pk_column, 'nullability': 'not declared; no additional inferred NOT NULL', 'default': 'not declared; no invented default'}
                    for i, c in enumerate(table['columns'])]
    risks = [{'id': 'database-key-generation', 'classification': 'technical-runtime-prerequisite', 'description': technical_choices['generated-id']['assumption'], 'blocksSourceGeneration': False},
             {'id': 'hibernate-schema-validation', 'classification': 'technical-runtime-verification', 'description': 'spring.jpa.hibernate.ddl-auto=validate (reference baseline) must pass against the real MAILINGINFORMATION table: names, CLOB (@Lob), NUMBER and DATE column types, default schema of the connection user (no schema attribute is declared).', 'blocksSourceGeneration': False},
             {'id': 'oracle-clob-lower-like', 'classification': 'technical-runtime-verification', 'description': 'LOWER/LIKE on CLOB columns generated by Hibernate must be verified on the target Oracle version; no connection performed here.', 'blocksSourceGeneration': False},
             {'id': 'reference-hibernate-jdbc-timeout', 'classification': 'technical-runtime-risk', 'description': 'The reference baseline sets spring.jpa.properties.hibernate.jdbc.timeout=1 (second) and Hikari connection-timeout=1000 ms; contains searches over CLOB columns may exceed it and surface as 504.', 'blocksSourceGeneration': False},
             {'id': 'jwt-secret-reference-fallback', 'classification': 'archetype-decision-conflict', 'description': 'The reference JWT property has a development-only default; archetype D-002 (no fallback) is retained and recorded in D-011.', 'blocksSourceGeneration': False},
             {'id': 'corporate-build-resolution', 'classification': 'technical-build-prerequisite', 'description': 'Corporate repository access is required for dependency resolution; Maven was not executed (the previous build attempt was blocked by repository connectivity).', 'blocksSourceGeneration': False}]
    quality_gates = {'checkstyle': checkstyle_gate(archetype, archetype_root, [f['path'] for f in files.values() if f['action'] != 'remove'])}
    plan = {'plan': {'version': 3, 'mode': 'full', 'strictModeAuthorized': True, 'phase': '8.6', 'generatorMustOmitUnresolvedBehavior': False,
                     'revision': config.get('revision')},
            'service': {'name': target['service'], 'package': target['base_package'], 'packagePath': package_path, 'groupId': target['group_id'], 'projectVersion': target['project_version'],
                        'javaVersion': params['values']['java_version'], 'springBootVersion': params['values']['spring_boot_version'],
                        'outputDirectory': target['output_directory'], 'applicationClass': params['values']['application_class']},
            'inputs': {'serviceSpec': {'path': SPEC.as_posix(), 'artifactSha256': digest(root / SPEC)},
                       'archetype': {'path': target['archetype'], 'fingerprint': base.archetype_fingerprint(archetype_root)},
                       'planningInput': {'path': input_path.as_posix(), 'sha256': digest(root / input_path)},
                       'existingOutputInventory': inventory, 'ignoredUntrackedOutput': ignored_untracked},
            'readiness': {**copy.deepcopy(service['readiness']), 'functionalGenerationReady': True, 'implementationPlanMode': 'full'},
            'persistenceAuthority': {**persistence_info, 'authorityOrder': ['explicit user instruction', 'target-specific approved technical requirement', 'approved archetype/reference architecture'],
                                     'priorOutputTechnology': prior_technology or 'plain-jdbc (obsolete, unrecorded)', 'jdbcAllowedBecauseSimpler': False},
            'technicalChoices': technical_choices,
            'activityLogging': logging_plan,
            'qualityGates': quality_gates,
            'architecture': {'style': 'Spring MVC controller interface/impl -> service interface/impl -> Spring Data JPA repository (JpaRepository + JpaSpecificationExecutor); explicit DTO mapper; JPA entity in the model package',
                             'mavenBaseline': {'mandatory': True, 'decision': 'D-012', 'templateSha256': baseline_cfg['template_sha256'], 'referenceSha256': baseline_cfg['reference_sha256'],
                                               'inventory': {k: len(v) for k, v in baseline_cfg['inventory'].items()}, 'additions': maven['additions'],
                                               'expectedPomSha256': expected_pom_sha, 'pruningAllowed': False},
                             'extraDomainOrPortLayers': False, 'entityMechanism': 'JPA @Entity (reference convention)',
                             'configurationMechanism': 'Spring Boot DataSource/Hikari/JPA auto-configuration from the archetype application.properties baseline',
                             'database': params['functional']['database'], 'applicationProperties': params['functional']['applicationProperties'],
                             'generatedId': {'column': pk_column, **technical_choices['generated-id']}, 'transactions': technical_choices['transactions'], 'deploymentTouched': False},
            'api': {'interfaceFile': api_file, 'controllerFile': controller_file, 'operations': operations,
                    'inactiveOperationsExcluded': copy.deepcopy(service.get('inactive', {}).get('operations', []))},
            'models': models, 'persistenceModel': {'table': table_name, 'entityClass': entity_class, 'fields': model_matrix,
                                                  'constraints': copy.deepcopy(table['keyAndIndexDeclarations']), 'schemaDdlGenerated': False,
                                                  'schemaAttribute': None, 'externalRelationshipEntitiesGenerated': False},
            'files': {'generate': [files[p] for p in order], 'omitUnresolved': [], 'archetypeCopy': [], 'archetypeParameterize': []},
            'generationOrdering': order, 'testPlan': test_plan,
            'generationBoundary': {'allowedInputs': [PLAN.as_posix(), PARAMS.as_posix(), SPEC.as_posix(), target['archetype']],
                                   'needsRawSparx': False, 'needsOriginalOpenapi': False, 'needsPlanningInputFile': False, 'needsReferenceProject': False,
                                   'strategy': 'Operation behavior matrices, entity/column maps, technical choices, file responsibilities and test expectations are embedded here; contract schemas remain in service-spec; the persistence architecture is read from the archetype.',
                                   'retainFileGuard': 'Retained and updated output files must match existingSha256 before generation; abort on unexpected edits. Removed files are archived first.'},
            'remainingTechnicalRisks': risks, 'planningBlockers': [],
            'statistics': {'activeOperations': len(operations), 'models': len(models), 'totalPlannedFiles': len(files),
                           'actions': {a: sum(f['action'] == a for f in files.values()) for a in ('retain', 'update', 'create', 'remove')}},
            'validation': {'errors': [], 'status': 'planned; independent validation follows'},
            'generation': {'functionalGenerationReady': True, 'javaWritten': False, 'mavenRun': False, 'deploymentGenerationAuthorized': False}}
    params['functional']['qualityGates'] = {'checkstyle': {'decision': 'D-014', 'mandatory': True, 'configSha256': quality_gates['checkstyle']['configSha256'], 'sources': quality_gates['checkstyle']['sources'],
                                                           'passRequires': '0 violations', 'unexecutableStatus': 'unverified'}}
    params['functional']['activityLogging'] = {'decision': 'D-013', 'transactionHeader': logging_plan['transactionHeaderConstant'], 'requestHeaderComponents': logging_plan['requestHeaders']['components'],
                                              'activityConstants': [c['constant'] for c in logging_plan['activityConstants']], 'masking': logging_plan['masking']}
    return plan, params


def write_full_plan(root: Path, yaml: Any, input_path: Path) -> int:
    plan, params = build_full(root, yaml, input_path)
    (root / PARAMS).write_bytes(base.dump_yaml(params, yaml))
    plan['inputs']['generationParameters'] = {'path': PARAMS.as_posix(), 'sha256': digest(root / PARAMS)}
    (root / PLAN).write_bytes(base.dump_yaml(plan, yaml))
    print({'mode': 'full', 'persistence': plan['persistenceAuthority']['technology'], **plan['statistics'], 'planSha256': digest(root / PLAN), 'parametersSha256': digest(root / PARAMS)})
    return 0
