"""Synthetic services for materializer, validator and linter tests (temporary directories only; no real service, no frozen fixture)."""
from pathlib import Path
import hashlib
import shutil
import sys
import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'tests'))
sys.path.insert(0, str(SKILLS / 'service-workspace' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'materialize-full-service' / 'scripts'))
sys.path.insert(0, str(SKILLS / 'plan-service-implementation' / 'scripts'))
import fixtures as wfx  # noqa: E402
import consistency_gate as gate  # noqa: E402
import workspace as wsm  # noqa: E402
import build_implementation_plan as planner_base  # noqa: E402
import plan_builder as pb  # noqa: E402

APPROVER = 'Test User (fixture)'
ARCHETYPE = 'archetypes/claro-spring-ms/v1.0.1'
ERRORS_A = {400: {'status': 'BAD_REQUEST', 'type': 'MissingParameters', 'sub': 'E1', 'detail': 'Missing or invalid parameters.'},
            404: {'status': 'NOT_FOUND', 'type': 'NotFound', 'sub': 'E2', 'detail': 'Nothing found.'},
            500: {'status': 'INTERNAL_SERVER_ERROR', 'type': 'InternalError', 'sub': 'T3', 'detail': 'Internal failure [ERROR_DETAIL]'},
            503: {'status': 'SERVICE_UNAVAILABLE', 'type': 'ServiceUnavailable', 'sub': 'T2', 'detail': 'Unavailable.'},
            504: {'status': 'GATEWAY_TIMEOUT', 'type': 'TimeoutException', 'sub': 'T1', 'detail': 'Timeout.'}}
ERRORS_B = {400: {'status': 'BAD_REQUEST', 'type': 'Invalid', 'sub': 'B1', 'detail': 'Bad invoice request.'},
            404: {'status': 'NOT_FOUND', 'type': 'Missing', 'sub': 'B2', 'detail': 'No invoices.'},
            500: {'status': 'INTERNAL_SERVER_ERROR', 'type': 'Internal', 'sub': 'B3', 'detail': 'Billing failure.'},
            503: {'status': 'SERVICE_UNAVAILABLE', 'type': 'Down', 'sub': 'B4', 'detail': 'Billing down.'}}

SERVICES = {
    'inventory-service': {
        'package': 'com.acme.inventory.core', 'table': 'ITEM', 'entity': 'ItemEntity', 'repo': 'ItemRepository', 'route': '/api/v1/items', 'prefix': 'Item',
        'fields': [('ID', 'id', 'Long', False, True, None), ('NAME', 'name', 'String', False, False, None), ('NOTES', 'notes', 'String', True, False, None),
                   ('SKU', 'sku', 'BigDecimal', False, False, 'NUMBER(8,2)'), ('STATE', 'state', 'Integer', False, False, 'NUMBER(1)'), ('CREATED_BY', 'createdBy', 'String', False, False, None),
                   ('CREATED_AT', 'createdAt', 'LocalDateTime', False, False, None), ('UPDATED_BY', 'updatedBy', 'String', False, False, None), ('UPDATED_AT', 'updatedAt', 'LocalDateTime', False, False, None)],
        'headers': ['transactionId', 'userId'], 'header_names': ['x-correlation-id', 'x-user-id'], 'header_constraints': {'x-correlation-id': {'minLength': 1, 'maxLength': 36, 'pattern': '^[A-Za-z0-9-]+$'}}, 'metadata': ['transactionId', 'userId'],
        'constants': [('ACT1_VALIDAR_ENTRADA', 'VALIDAR_ENTRADA', None), ('ACT2_CONSULTAR', 'CONSULTAR', {'LOG_TIMEOUT_ACT2_CONSULTAR': 'Timeout en CONSULTAR: '})],
        'errors': ERRORS_A},
    'billing-service': {
        'package': 'org.example.billing', 'table': 'INVOICE', 'entity': 'InvoiceEntity', 'repo': 'InvoiceRepository', 'route': '/billing/v2/invoices', 'prefix': 'Invoice',
        'fields': [('INVOICE_ID', 'invoiceId', 'Long', False, True, None), ('TOTAL', 'total', 'BigDecimal', False, False, 'NUMBER(10,2)'), ('ISSUED_AT', 'issuedAt', 'LocalDateTime', False, False, None),
                   ('CUSTOMER', 'customer', 'String', False, False, None), ('AUDIT_USER', 'auditUser', 'String', False, False, None)],
        'headers': ['transactionId', 'userId', 'applicationName'], 'header_names': ['x-trace-id', 'x-user', 'x-app'], 'header_constraints': {'x-trace-id': {'maxLength': 64}}, 'metadata': ['applicationName', 'transactionId', 'userId'],
        'constants': [('ACT1_VALIDAR', 'VALIDAR', None)], 'errors': ERRORS_B},
}
ROLE_HEADERS = {'transactionId': 0, 'userId': 1, 'applicationName': 2}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_repo(tmp: Path) -> Path:
    repo = wfx.make_repo(Path(tmp).resolve())
    shutil.copytree(REPO_ROOT / ARCHETYPE, repo / ARCHETYPE)          # read-only copy of the archetype into the temporary repository
    return repo


def file_entry(path, kind, order, action='create', **extra):
    return {'path': path, 'componentType': kind, 'action': action, 'generationOrder': order, 'operationsServed': [], **extra}


def inventory_shape(spec, fields):
    entity_fields = {f[1]: f for f in fields}
    models = [
        pb.model('SearchItemsResponse', 'response', [pb.f('code', 'Integer', True, ['@NotNull']), pb.f('data', 'SearchItemsData', True, ['@NotNull', '@Valid']), pb.f('message', 'String', True, ['@NotNull'])]),
        pb.model('SearchItemsData', 'response', [pb.f('items', 'List<ItemView>', True, ['@NotNull', '@Valid'])]),
        pb.model('ItemView', 'response', [pb.f('id'), pb.f('name'), pb.f('notes'), pb.f('sku'), pb.f('state', constraints={'enum': ['0', '1']})]),
        pb.model('CreateItemRequest', 'request', [pb.f('name', required=True, annotations=['@NotNull', '@Size(min = 2, max = 40)']), pb.f('notes'), pb.f('sku'), pb.f('state', constraints={'type': 'string', 'enum': ['0', '1']})]),
        pb.model('CreateItemResponse', 'response', [pb.f('code', 'Integer', True, ['@NotNull']), pb.f('message', 'String', True, ['@NotNull'])]),
        pb.model('PatchItemRequest', 'request', [pb.f('name'), pb.f('notes'), pb.f('sku'), pb.f('state', constraints={'enum': ['0', '1']})]),
        pb.model('PatchItemResponse', 'response', [pb.f('code', 'Integer', True, ['@NotNull']), pb.f('message', 'String', True, ['@NotNull'])])]
    search_spec = {'filters': [('id', 'id', 'Long', 'exact', 'NUMBER(0)'), ('name', 'name', 'String', 'contains', 'VARCHAR2(50)'), ('notes', 'notes', 'String', 'contains', 'CLOB'),
                               ('sku', 'sku', 'BigDecimal', 'exact', 'NUMBER(8,2)'), ('state', 'state', 'Integer', 'exact', 'NUMBER(1)')],
                   'list': 'items', 'columns': [('id', 'id'), ('name', 'name'), ('notes', 'notes'), ('sku', 'sku'), ('state', 'state')], 'order': 'ID', 'filter_constraints': {'name': {'maxLength': 20}, 'state': {'pattern': '^[01]$'}}, 'limit_constraints': {'maximum': 100}}
    params, query = pb.search_op(search_spec, True, 'OR')
    write_maps = lambda user, date: [pb.mapping('name', 'String', 'NAME', 'name'), pb.mapping('notes', 'String', 'NOTES', 'notes'),
                                     pb.mapping('sku', 'BigDecimal', 'SKU', 'sku', sql='NUMBER(8,2)'), pb.mapping('state', 'Integer', 'STATE', 'state', sql='NUMBER(1)'),
                                     pb.mapping(user, 'String', user.upper(), 'userId', origin='headerRequest'), pb.mapping(date, 'LocalDateTime', date.upper(), kind='database-function', literal='sysdate')]
    ops = [
        {'id': 'searchItems', 'method': 'GET', 'path': '/api/v1/items', 'kind': 'select', 'response': 'SearchItemsResponse', 'message': 'Consulta exitosa', 'error_message': 'ITEM_SEARCH_ERROR',
         'statuses': [200, 400, 404, 500, 503, 504], 'query_params': params, 'query': query, 'constants': ['ACT1_VALIDAR_ENTRADA', 'ACT2_CONSULTAR'], 'label': 'SearchItems', 'helper': 'logSearch',
         'log_values': ['id', 'name', 'notes', 'sku', 'state', 'limit', 'offset'], 'controller_args': ['transactionId'], 'summary': 'Search items.', 'description': 'Searches the items.',
         'rules': [{'ruleId': 'S1', 'kind': 'pagination-pairing', 'parameters': ['limit', 'offset']}, {'ruleId': 'S2', 'kind': 'failed-validation-outcome', 'status': 400}]},
        {'id': 'createItem', 'method': 'POST', 'path': '/api/v1/items', 'kind': 'insert', 'response': 'CreateItemResponse', 'request': 'CreateItemRequest', 'message': 'Item registrado',
         'error_message': 'ITEM_CREATE_ERROR', 'statuses': [200, 400, 409, 500, 503, 504], 'constants': ['ACT1_VALIDAR_ENTRADA', 'ACT2_CREAR'], 'label': 'CreateItem', 'helper': 'logCreate',
         'controller_args': ['transactionId', 'userId'], 'mappings': write_maps('createdBy', 'createdAt'), 'summary': 'Create an item.',
         'rules': [{'ruleId': 'C1', 'kind': 'conditional-required', 'when': 'sku is supplied', 'requires': ['notes']}, {'ruleId': 'C2', 'kind': 'validation-success-continues'}]},
        {'id': 'patchItem', 'method': 'PATCH', 'path': '/api/v1/items/{id}', 'kind': 'update', 'response': 'PatchItemResponse', 'request': 'PatchItemRequest', 'message': 'Item actualizado',
         'error_message': 'ITEM_PATCH_ERROR', 'statuses': [200, 400, 404, 409, 500, 503, 504], 'constants': ['ACT1_VALIDAR_ENTRADA', 'ACT2_ACTUALIZAR'], 'label': 'PatchItem', 'helper': 'logUpdate',
         'log_values': ['id'], 'controller_args': ['transactionId', 'userId'], 'path_params': [pb.param('id', 'path', required=True, minLength=1)], 'mappings': write_maps('updatedBy', 'updatedAt'),
         'rules': [{'ruleId': 'P1', 'kind': 'at-least-one-of', 'scope': 'body fields'}]}]
    return ops, models


def billing_shape(spec, fields):
    models = [
        pb.model('ListInvoicesResponse', 'response', [pb.f('code', 'Integer', True), pb.f('data', 'ListInvoicesData', True), pb.f('message', 'String', True)]),
        pb.model('ListInvoicesData', 'response', [pb.f('invoices', 'List<InvoiceView>', True, ['@Valid'])]),
        pb.model('InvoiceView', 'response', [pb.f('invoiceId'), pb.f('customer'), pb.f('total')]),
        pb.model('CreateInvoiceRequest', 'request', [pb.f('customer', required=True, annotations=['@NotBlank', '@Size(max = 30)']), pb.f('total', required=True, annotations=['@NotNull'])]),
        pb.model('CreateInvoiceResponse', 'response', [pb.f('code', 'Integer', True), pb.f('message', 'String', True)])]
    search_spec = {'filters': [('customer', 'customer', 'String', 'exact', 'VARCHAR2(80)'), ('total', 'total', 'BigDecimal', 'exact', 'NUMBER(10,2)')],
                   'list': 'invoices', 'columns': [('invoiceId', 'invoiceId'), ('customer', 'customer'), ('total', 'total')], 'order': 'INVOICE_ID', 'filter_constraints': {'customer': {'minLength': 2, 'maxLength': 30, 'pattern': '^[A-Za-z0-9 -]+$'}}}
    params, query = pb.search_op(search_spec, False, 'AND')
    ops = [
        {'id': 'listInvoices', 'method': 'GET', 'path': '/billing/v2/invoices', 'kind': 'select', 'response': 'ListInvoicesResponse', 'message': 'OK', 'error_message': 'BILLING_LIST_FAILED',
         'statuses': [200, 400, 404, 500, 503], 'query_params': params, 'query': query, 'constants': ['ACT1_VALIDAR', 'ACT2_LISTAR'], 'label': 'ListInvoices', 'helper': 'logList',
         'log_values': ['customer', 'total'], 'controller_args': ['transactionId'], 'rules': []},
        {'id': 'createInvoice', 'method': 'POST', 'path': '/billing/v2/invoices', 'kind': 'insert', 'response': 'CreateInvoiceResponse', 'request': 'CreateInvoiceRequest', 'message': 'Created',
         'error_message': 'BILLING_CREATE_FAILED', 'statuses': [200, 400, 500, 503], 'constants': ['ACT1_VALIDAR', 'ACT2_EMITIR'], 'label': 'CreateInvoice', 'helper': 'logCreate',
         'controller_args': ['transactionId', 'userId'], 'rules': [],
         'mappings': [pb.mapping('customer', 'String', 'CUSTOMER', 'customer'), pb.mapping('total', 'BigDecimal', 'TOTAL', 'total', sql='NUMBER(10,2)'),
                      pb.mapping('auditUser', 'String', 'AUDIT_USER', 'userId', origin='headerRequest'), pb.mapping('issuedAt', 'LocalDateTime', 'ISSUED_AT', kind='database-function', literal='sysdate')]}]
    return ops, models


SHAPES = {'inventory-service': inventory_shape, 'billing-service': billing_shape}


APPLICATION = {'inventory-service': 'InventoryServiceApplication', 'billing-service': 'BillingServiceApplication'}
ASSEMBLY_VALUES = {'root_log_level': 'INFO', 'application_log_level': 'DEBUG', 'corporate_logger_level': 'INFO', 'http_log_level': 'WARN', 'log_time_zone': 'UTC', 'jwt_roles_claim': 'roles',
                   'vault_name': 'vault-fixture', 'builder_image': 'builder.example/maven:fixture', 'runtime_image': 'runtime.example/jre:fixture', 'container_port': '8085',
                   'spring_config_location': 'file:/config/', 'time_zone': 'UTC', 'k8s_namespace': 'fixture-ns', 'k8s_part_of': 'fixture', 'k8s_managed_by': 'factory', 'environment': 'dev',
                   'k8s_owner': 'team-fixture', 'replica_count': '1', 'k8s_tier': 'backend', 'source_repository_url': 'https://git.example/fixture.git', 'image_tag': 'fixture',
                   'service_account_name': 'fixture-sa', 'config_map_name': 'fixture-config', 'container_registry': 'registry.example', 'image_repository': 'fixture/image',
                   'image_pull_policy': 'IfNotPresent', 'secret_name': 'fixture-secret', 'config_mount_path': '/config', 'external_secret_refresh_interval': '1h',
                   'vault_secret_store_name': 'fixture-store', 'vault_secret_store_kind': 'ClusterSecretStore', 'vault_secret_path': 'fixture/path', 'jwt_secret_property': 'jwt-key',
                   'external_secret_additional_data': '', 'specification_owned_application_properties': ''}


def make_plan(repo: Path, service: str, with_unsupported: bool = False, extra_files=None, fields=None, mutate=None, derived_assumptions=None, assembly_values=None, deploy=True, write_params=True):
    spec = SERVICES[service]
    package, package_path = spec['package'], spec['package'].replace('.', '/')
    main, test = f'src/main/java/{package_path}/', f'src/test/java/{package_path}/'
    ws = repo / '.factory' / 'services' / service
    (ws / 'service-spec.yml').write_text(yaml.safe_dump({'service': {'name': service}, 'readiness': {'strictImplementationReady': True}, 'derivedAssumptions': derived_assumptions or []}), encoding='utf-8')
    field_rows = [tuple(r) + (None,) * (6 - len(r)) for r in (fields or spec['fields'])]
    persistence_fields = [{'physicalColumn': c, 'property': p, 'javaType': t, 'lob': lob, 'primaryKey': pk, 'sqlType': sql} for c, p, t, lob, pk, sql in field_rows]
    ops, models = SHAPES[service](spec, field_rows)
    built = pb.build({'ops': ops, 'models': models, 'header_names': spec['header_names'], 'header_constraints': spec.get('header_constraints'), 'errors': spec['errors'], 'metadata': spec['metadata']})
    prefix = spec['prefix']
    has_page = any(o['kind'] == 'select' and o.get('query', {}).get('pagination') for o in ops)
    file_list = [('activity-constants', f'utils/ConstanApi.java', {'activityConstants': built['constants'], 'insertAfter': '    // ================= ACTIVIDADES (LOGS) ================='}),
                 ('archetype-activity-logger', 'utils/ActivityLogger.java', {}),
                 ('request-headers-model', 'dto/request/RequestHeaders.java', {'components': spec['headers']}),
                 ('internal-typed-exception', 'exception/ServiceOperationException.java', {}),
                 ('jpa-entity', f'model/{spec["entity"]}.java', {}), ('spring-data-jpa-repository', f'repository/{spec["repo"]}.java', {}),
                 ('jpa-specification', f'repository/{prefix}Specifications.java', {}), ('internal-query-model', f'model/{prefix}SearchCriteria.java', {}),
                 ('business-validator', f'validation/{prefix}Validator.java', {}), ('explicit-contract-data-mapper', f'dto/mapper/{prefix}Mapper.java', {}),
                 ('application-service-contract', f'service/{prefix}Service.java', {}), ('application-service-implementation', f'service/impl/{prefix}ServiceImpl.java', {}),
                 ('contract-api-interface', f'controller/{prefix}Api.java', {}), ('controller-implementation', f'controller/impl/{prefix}Controller.java', {}),
                 ('data-access-error-translator', 'exception/PersistenceExceptionTranslator.java', {}), ('central-contract-error-advice', 'exception/GlobalExceptionHandler.java', {})]
    if has_page:
        file_list.append(('offset-based-pageable', 'repository/OffsetLimitRequest.java', {}))
    entries = [file_entry(main + rel, kind, i + 1, **extra) for i, (kind, rel, extra) in enumerate(file_list)]
    for m in built['models']:
        folder = 'request' if 'request' in m['requestResponseScope'] else 'response'
        entries.append(file_entry(main + f'dto/{folder}/{m["name"]}.java', 'contract-dto', 30))
    entries.append(file_entry(test + 'utils/ActivityLoggerTest.java', 'archetype-activity-logger-test', 50))
    entries += [file_entry('pom.xml', 'build-baseline', 0, 'create'), file_entry('src/main/resources/application.properties', 'runtime-database-configuration', 0, 'update'),
                file_entry('.generation-manifest.yml', 'generation-provenance-manifest', 99, 'update')]
    for rel, kind in ((f'validation/{prefix}ValidatorTest', 'unit-mapping-persistence-test'), (f'dto/mapper/{prefix}MapperTest', 'unit-mapping-persistence-test'),
                      (f'repository/{prefix}SpecificationsTest', 'unit-mapping-persistence-test'), (f'service/impl/{prefix}ServiceImplTest', 'unit-mapping-persistence-test'),
                      (f'model/{spec["entity"]}Test', 'unit-mapping-persistence-test'), (f'controller/impl/{prefix}ControllerTest', 'controller-contract-test'),
                      ('exception/GlobalExceptionHandlerTest', 'controller-contract-test'), ('utils/ActivityLoggingTest', 'activity-logging-test')):
        entries.append(file_entry(test + rel + '.java', kind, 51))
    if with_unsupported:
        entries.append(file_entry(test + f'repository/{spec["repo"]}PersistenceTest.java', 'repository-persistence-test', 52))
    entries += extra_files or []
    roles = {c: {'header': spec['header_names'][ROLE_HEADERS[c]]} for c in spec['headers']}
    plan = {'plan': {'version': 3, 'mode': 'full'}, 'generation': {'functionalGenerationReady': True},
            'service': {'name': service, 'package': package, 'packagePath': package_path, 'outputDirectory': f'output/{service}'},
            'inputs': {'serviceSpec': {'path': '.factory/service-spec.yml', 'artifactSha256': sha((ws / 'service-spec.yml').read_bytes())},
                       'archetype': {'path': ARCHETYPE, 'fingerprint': planner_base.archetype_fingerprint(repo / ARCHETYPE)}},
            'persistenceModel': {'table': spec['table'], 'entityClass': spec['entity'], 'fields': persistence_fields},
            'technicalChoices': {'generated-id': {'mechanism': '@GeneratedValue(strategy = GenerationType.IDENTITY) on the primary key'}, 'entity-dml-shaping': {'mechanism': 'dynamic'},
                                 'audit-timestamps': {'mechanism': 'LocalDateTime.now(ZoneId.systemDefault()) in the service'}},
            'models': built['models'],
            'api': {'operations': built['ops'], 'inactiveOperationsExcluded': [{'method': 'GET', 'path': spec['route'] + '/{id}'}]},
            'activityLogging': {'requestHeaders': {'components': spec['headers'], 'roleMapping': roles}, 'handlerValidationActivity': spec['constants'][0][0],
                                'transactionHeaderConstant': spec['header_names'][0], 'operations': built['activityOps'], 'activityConstants': built['constants']},
            'planningBlockers': [], 'files': {'generate': entries}}
    plan['service'].update({'groupId': package, 'projectVersion': '1.0.0-SNAPSHOT', 'applicationClass': APPLICATION[service]})
    plan['readiness'] = {'deploymentGenerationAuthorized': deploy}
    if mutate:
        mutate(plan)
    if write_params:
        values = dict(ASSEMBLY_VALUES, **(assembly_values or {}))
        provenance = {'serviceSpec': {'sha256': plan['inputs']['serviceSpec']['artifactSha256']},
                      'archetype': {'fingerprint': plan['inputs']['archetype']['fingerprint']}}
        (ws / 'generation-parameters.yml').write_text(yaml.safe_dump({'version': 2, 'service': service, 'inputs': provenance, 'values': {k: v for k, v in values.items() if v is not None}}, sort_keys=True), encoding='utf-8')
        plan['inputs']['generationParameters'] = {'path': '.factory/generation-parameters.yml', 'sha256': sha((ws / 'generation-parameters.yml').read_bytes())}
    (ws / 'implementation-plan.yml').write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True), encoding='utf-8')
    return plan


def clear_gate(repo: Path, service: str, route: str):
    """A consistent synthetic service whose gate is cleared by the legitimate path (review + authorization) inside the temporary repository only."""
    wfx.make_service(repo, service, path=route)
    ws = wsm.Workspace(repo, service)
    wfx.review(ws.dir)
    result = gate.evaluate(ws.dir, repo, service)
    assert not result['blocking'], result['blocking']
    gate.authorize(ws.dir, repo, service, APPROVER, 'authorize (fixture)')
    return ws


def blocked_gate(repo: Path, service: str, route: str):
    """Same service with a verified contradiction (required flag differs) and the gate evaluated: BLOCKED_BY_INCONSISTENCIES."""
    wfx.make_service(repo, service, path=route, sparx_required='Si', swagger_required=False)
    ws = wsm.Workspace(repo, service)
    wfx.review(ws.dir)
    ws.refresh_gate()
    return ws


def ready_service(repo: Path, service: str, **plan_kwargs):
    spec = SERVICES[service]
    ws = clear_gate(repo, service, spec['route'])
    make_plan(repo, service, **plan_kwargs)
    return ws


def tree(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(Path(path).rglob('*')) if p.is_file()} if Path(path).exists() else {}
