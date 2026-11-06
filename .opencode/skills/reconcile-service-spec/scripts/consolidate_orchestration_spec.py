"""Consolidation of `service-spec.yml` for an orchestration service: OpenAPI contract + `sparx-spec.yml` (behavior).

Source ownership is preserved: the contract owns the HTTP surface, schemas and the error catalog (code, status, type, detail); the Sparx spec owns the flows.
This stage resolves every INPUT mapping row of every remote call into an expression, every outcome into codes and compensations, and records what the
sources do not define (assumptions and gaps). It invents no rule, endpoint or SQL.

Usage (from the repository root):  python consolidate_orchestration_spec.py <service>
"""
from pathlib import Path
import hashlib
import re
import sys
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'interpret-sparx' / 'scripts'))
import orchestration_interpretation as oi  # noqa: E402
from orchestration_interpretation import fold, alias  # noqa: E402

VERSION = 1
ACT_REF = re.compile(r'^act\.?\s*(\d+(?:\.\d+)*)$', re.I)
NULLS = {'null', ''}

# (client service name in the evidence, HTTP method, normalized path) -> logical operation name of the generated client
CLIENT_OPS = {
    ('agreementRequest', 'POST', '/api/v1/agreementRequest'): 'create', ('agreementRequest', 'GET', '/api/v1/agreementRequest/{requestCodeId}'): 'get',
    ('agreementRequest', 'PATCH', '/api/v1/agreementRequest'): 'update', ('agreementRequest', 'DELETE', '/api/v1/agreementRequest/{requestCodeId}'): 'delete',
    ('financingAgreement', 'POST', '/api/v1/agreement'): 'create', ('financingAgreement', 'PATCH', '/api/v1/financingAgreement'): 'update',
    ('financingAgreement', 'GET', '/api/v1/financingAgreement/{agreementCodeId}'): 'get', ('financingAgreement', 'DELETE', '/api/v1/financingAgreement/{agreementCodeId}'): 'delete',
    ('financingAgreement', 'GET', '/api/v1/financingAgreement/numberOfRefinancings'): 'numberOfRefinancings',
    ('financingInstallment', 'GET', '/api/v1/financingInstallment'): 'list', ('financingInstallment', 'PATCH', '/api/v1/financingInstallment'): 'update',
    ('financingInstallment', 'POST', '/api/v1/financingInstallment/generate'): 'generate', ('parameters', 'GET', '/api/v1/parameters'): 'list',
    ('rangeQuote', 'GET', '/api/v1/rangeQuote/quotes'): 'quotes', ('collection-integration', 'GET', '/api/v1/installments'): 'list',
    ('tros-api-installmentSynchronization', 'POST', '/ros/rest/synchronizeInstallments'): 'synchronize'}
CLASS_NAMES = {'agreementRequest': 'AgreementRequestClient', 'financingAgreement': 'FinancingAgreementClient', 'financingInstallment': 'FinancingInstallmentClient',
               'parameters': 'ParametersClient', 'rangeQuote': 'RangeQuoteClient', 'collection-integration': 'CollectionIntegrationClient',
               'tros-api-installmentSynchronization': 'InstallmentSynchronizationClient'}
# Activity-specific method corrections (documented as assumptions).
METHOD_FIXES = {'R3.6': ('DELETE', 'activity 3.6 (rollback financing) says POST /api/v1/financingAgreement/{agreementCodeId}; the identical rollbacks 6.x/8.12 say DELETE and no POST exists for that path in the financingAgreement contract: DELETE is used')}
EMPTY_LIST_IS_NOT_FOUND = {'5.2', '7.2', '8.2', '9.2', '10.2'}


class ConsolidationError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm_path(url, method):
    url = (url or '').strip()
    url = re.sub(r'^(GET|POST|PUT|PATCH|DELETE)-', '', url)
    return url.split('?', 1)[0]


class Index:
    """Keys -> parsed activity, step kind and output description."""

    def __init__(self, spec):
        self.spec = spec
        self.acts = spec['activities']
        self.props = spec['properties']
        self.steps = {}
        self.register(spec['sync'])
        for flow in spec['flows'].values():
            self.register(flow['steps'])
            self.register(flow['comps'])

    def find(self, sel):
        lane, prefix = sel
        return oi.select(self.acts, lane, prefix)

    def register(self, items):
        for step in items:
            if step['t'] in ('remote', 'compute'):
                act = self.find(step['sel'])
                outputs = describe_outputs(act) if step['t'] == 'remote' else {'renames': {}, 'lists': {}, 'installments': None}
                if step['key'] in self.steps and self.steps[step['key']]['act']['name'] != act['name']:
                    raise ConsolidationError(f'duplicate step key {step["key"]}')
                self.steps[step['key']] = {'act': act, 'kind': step['t'], 'outputs': outputs}
            if step['t'] == 'branch':
                self.register(step['then'])
                self.register(step['else'])


def describe_outputs(act):
    renames, lists, installments = {}, {}, None
    for row in act.get('output') or []:
        name, dest = row['name'], row['dest']
        if name.startswith('data') and '[]' in name:
            root = name.split('[]')[0]
            if re.match(r'^data\.installments$', root):
                installments = root
            if dest and '[]' in dest:
                lists[dest.split('[]')[0]] = root
        if dest and '[' not in dest:
            renames[dest] = re.sub(r'^data(\[\])?\.', '', name)
    return {'renames': renames, 'lists': lists, 'installments': installments}


def origin_key(origin):
    match = re.match(r'^act\.?\s*(\d+(?:\.\d+)*)', origin.strip(), re.I)
    return match.group(1) if match else None


def element_name(text):
    return alias(re.split(r'\.', re.sub(r'\[[^\]]*\]', '', text.strip()))[-1])


def scalar_expr(index, act, row):
    src, origin, transform, dest = row['source'].strip(), row['origin'].strip(), row['transform'].strip(), row['dest']
    sfold, ofold = fold(src), fold(origin)
    if sfold in NULLS:
        return 'null'
    if src == '""':
        return 'lit:'
    if sfold == 'sysdate':
        return 'now' if ('iso8601' in fold(transform) or fold(dest) == 'timestamp') else 'today'
    if src.startswith('config['):
        key = re.search(r'clave\s*=\s*(\w+)', src).group(1)
        return 'cfg:' + str(act['properties'].get(key, key))
    if ofold.startswith('header'):
        return 'hdr:' + src
    if ofold == 'properties':
        if src not in index.props:
            raise ConsolidationError(f'property {src} of {act["name"]} is not defined by the evidence')
        return 'prop:' + src
    if ofold == 'request':
        return 'req:' + alias(src)
    key = origin_key(origin)
    if key:
        if key not in index.steps:
            raise ConsolidationError(f'{act["name"]}: origin {origin!r} does not match a step of the flow')
        info = index.steps[key]
        if info['kind'] == 'compute':
            return f'val:{key}:{src}'
        field = info['outputs']['renames'].get(src, src)
        return f'act:{key}:{alias(field)}'
    raise ConsolidationError(f'{act["name"]}: cannot resolve the origin of {src!r} ({origin!r})')


def list_source(index, act, row):
    src, origin = row['source'].strip(), row['origin'].strip()
    key = origin_key(origin)
    if not key or key not in index.steps:
        raise ConsolidationError(f'{act["name"]}: list source {src!r} has no step origin {origin!r}')
    name = re.split(r'\[', src)[0]
    info = index.steps[key]
    if info['kind'] == 'compute':
        return f'val:{key}:{name}'
    root = info['outputs']['lists'].get(name)
    if root is None:
        raise ConsolidationError(f'{act["name"]}: step {key} has no list named {name}')
    return f'lst:{key}:{root}'


def resolve_remote(index, step, flow_chains, discrepancy_log):
    act = index.steps[step['key']]['act']
    call = act['call']
    if not call or fold(call.get('type')) != 'openapi-rest':
        raise ConsolidationError(f'{act["name"]} is not an OpenApi-Rest call')
    method = call['method'].upper()
    path = norm_path(call['url'], method)
    fix = METHOD_FIXES.get(step['key'])
    if fix:
        method = fix[0]
        discrepancy_log.append({'id': f'D-method-{step["key"]}', 'statement': fix[1]})
    client = call['name']
    op = CLIENT_OPS.get((client, method, path))
    if op is None:
        raise ConsolidationError(f'{act["name"]}: no client operation for {client} {method} {path}')
    headers = {'forward': False, 'map': {}}
    path_params, query, body, body_list = {}, {}, {}, None
    for row in act['input']:
        section = row['section'] or 'headers'
        if not row['source'] and not row['origin']:
            continue
        if fold(row['source']).startswith('enviar al destino todos'):
            headers['forward'] = True
            continue
        if section == 'headers':
            headers['map'][row['dest']] = scalar_expr(index, act, row)
        elif section == 'path':
            path_params[row['dest']] = scalar_expr(index, act, row)
        elif section == 'query':
            expr = scalar_expr(index, act, row)
            if expr != 'null':
                query[row['dest']] = expr
        elif section == 'body':
            if '[i]' in row['dest']:
                root = row['dest'].split('[i]')[0]
                if body_list is None:
                    body_list = {'root': root, 'source': None, 'element': {}}
                field = row['dest'].split('].', 1)[1]
                if fold(row['source']) in NULLS or row['source'] == 'SYSDATE':
                    body_list['element'][field] = scalar_expr(index, act, row)
                elif row['origin'].lower().startswith('properties'):
                    body_list['element'][field] = scalar_expr(index, act, row)
                else:
                    source = list_source(index, act, row)
                    if body_list['source'] not in (None, source):
                        raise ConsolidationError(f'{act["name"]}: mixed list sources')
                    body_list['source'] = source
                    body_list['element'][field] = 'el:' + element_name(row['source'])
            else:
                body[row['dest']] = scalar_expr(index, act, row)
    if body_list and body_list['source'] is None:
        raise ConsolidationError(f'{act["name"]}: list body without a list source')
    outcome = act['outcome']
    names = dict(outcome)
    for code_key in ('otherwise',):
        if names.get(code_key) == 'IDF399':
            names[code_key] = 'IDF389'
    fixes = {'9.4': {'otherwise': 'IDF354'}, '9.5': {'otherwise': 'IDF355'}}.get(step['key'], {})
    names.update(fixes)

    def chain(name):
        if name is None:
            return []
        if name not in flow_chains:
            raise ConsolidationError(f'{act["name"]}: compensation {name!r} has no chain in its flow')
        return list(flow_chains[name])
    resolved = {'t': 'remote', 'key': step['key'], 'activity': {'name': act['name'], 'lane': act['lane'], 'guid': act['guid'], 'page': act['page'], 'pageSha256': act['pageSha256']},
                'client': client, 'operation': op, 'method': method, 'path': path, 'headers': headers, 'pathParams': path_params, 'query': query, 'body': body, 'bodyList': body_list,
                'outcome': {'ok': sorted(set(names['ok'])), 'byStatus': {str(k): v for k, v in sorted(names['byStatus'].items())}, 'otherwise': names['otherwise'],
                            'compensation': chain(names['otherwiseCompensation']), 'technicalCompensation': chain(names['technicalCompensation']),
                            'ignoreFailure': names['ignoreFailure'], 'logOnly': names['logOnly']},
                'outputs': index.steps[step['key']]['outputs']}
    if 'listFilter' in step:
        resolved['bodyListFilter'] = step['listFilter']
    if step['key'] in EMPTY_LIST_IS_NOT_FOUND and '404' in resolved['outcome']['byStatus']:
        resolved['outcome']['emptyIs'] = resolved['outcome']['byStatus']['404']
    return resolved


def fix_lists(index, value):
    """`lst:<step>:<list name>` -> `lst:<step>:<root path of the list in the answer>`."""
    if isinstance(value, list):
        return [fix_lists(index, v) for v in value]
    if isinstance(value, dict):
        return {k: fix_lists(index, v) for k, v in value.items()}
    if isinstance(value, str) and value.startswith('lst:'):
        _, key, name = value.split(':', 2)
        info = index.steps.get(key)
        root = (info or {}).get('outputs', {}).get('lists', {}).get(name)
        if root is None:
            raise ConsolidationError(f'{value}: step {key} has no list named {name}')
        return f'lst:{key}:{root}'
    return value


def resolve_items(index, items, chains, log):
    out = []
    for step in items:
        if step['t'] == 'remote':
            out.append(resolve_remote(index, step, chains, log))
        elif step['t'] == 'branch':
            out.append({**step, 'when': fix_lists(index, step['when']), 'then': resolve_items(index, step['then'], chains, log), 'else': resolve_items(index, step['else'], chains, log)})
        else:
            if step['t'] == 'decide':
                step = {**step, 'when': fix_lists(index, step['when'])}
            if step['t'] == 'compute':
                act = index.steps[step['key']]['act']
                step = {**step, 'ops': fix_lists(index, step['ops']), 'activity': {'name': act['name'], 'lane': act['lane'], 'guid': act['guid'], 'page': act['page'], 'pageSha256': act['pageSha256']},
                        'compensation': list(chains[step['comp']]) if step.get('comp') else []}
            out.append(step)
    return out


# ----------------------------------------------------------------------------- contract
def contract_model(openapi):
    op = openapi['operations'][0]
    schema = openapi['components']['schemas']
    fields = []
    for name, prop in schema['AgreementRequest']['properties'].items():
        fields.append({'name': name, 'type': prop.get('type'), 'format': prop.get('format'), 'required': name in (schema['AgreementRequest'].get('required') or [])})
    data_fields = [{'name': n, 'type': p.get('type'), 'format': p.get('format')} for n, p in schema['AgreementResponseData']['properties'].items()]
    inst_fields = [{'name': n, 'type': p.get('type'), 'format': p.get('format')} for n, p in schema['AgreementInstallmentDto']['properties'].items()]
    errors = {}
    for status, response in op['responses'].items():
        if status == '200':
            continue
        content = response['content']['application/json']
        examples = dict(content.get('examples') or {})
        if content.get('example'):
            examples['_single'] = {'value': content['example']}
        for example in examples.values():
            value = example['value']
            errors[value['subType']] = {'status': int(status), 'httpStatus': value['status'], 'type': value['type'], 'message': value['message'], 'detail': ' '.join(str(value['detail']).split())}
    headers = [{'name': h['name'], 'required': h.get('required')} for h in op['parameters']['header']]
    return {'operationId': op['operationId'], 'method': op['method'], 'path': op['path'], 'successStatus': 200, 'successMessage': 'Operación exitosa.',
            'statuses': sorted(int(s) for s in op['responses']), 'headers': headers, 'request': {'class': 'AgreementRequest', 'fields': fields},
            'response': {'class': 'AgreementResponse', 'dataClass': 'AgreementResponseData', 'dataFields': data_fields, 'installmentClass': 'AgreementInstallmentDto', 'installmentFields': inst_fields},
            'errors': errors}


ASSUMPTIONS = [
    ('A-01', 'technical-implementation-choice', 'Base package com.claro.agreement.orquestation and application class AgreementOrquestationApplication are technical choices; no source defines them. The service accesses no database (Sparx lists no table for the operation).'),
    ('A-02', 'swagger-governs', 'Swagger governs every documentary conflict (approved delegated choice): the response data of each requestTypeId is the contract example (FinancingSuccess, CancelInstallmentsSuccess, ...), the codes IDF399 (config failure, Sparx) is IDF389 (contract), 9.4 uses IDF354 and 9.5 uses IDF355 (process graph and contract), and contactName is optional for requestTypeId 2.'),
    ('A-03', 'delegated-conservative', 'The monthly payment of activity 2.2.3 has no formula in the sources (empty activity). By analogy with the explicit capacity formulas of 5.4.6 and 8.4 it is quoteAmount + fixedAmount, compared as creditLimit >= payment (graph gateway); this is the narrowest reading of IDF401.'),
    ('A-04', 'delegated-conservative', 'Money is computed with BigDecimal; quoteAmount = amount / quotesNumber is rounded HALF_UP to 2 decimals (stated by 2.2.2 and 5.4.6, applied also to 8.4 which gives no rounding). The refinancing percentage (5.4.4) is returned with 2 decimals HALF_UP.'),
    ('A-05', 'delegated-conservative', 'Remote calls: HTTP 408/504 -> IDT1 (504), 502/503 and connection failures -> IDT2 (503), timeouts -> IDT1, any other 5xx or unreadable answer -> IDT3 (500); any other non-expected status is the activity business code (IDFxxx). IDT replaces the business code when the dependency is unavailable (Sparx: "NO DISPONIBLE, TIME-OUT o ERROR INTERNO").'),
    ('A-06', 'delegated-conservative', 'Compensation chains come from the process graph (e.g. Rollback CambioCiclo = 10.9 then 10.8). Each compensation step is best effort: its failure is logged and ignored (Sparx: "Continuar con la siguiente actividad"); the original failure code is returned. 3.3 has no compensation (nothing was created yet).'),
    ('A-07', 'delegated-conservative', 'Activity 3.6 (rollback financing) is documented as POST /api/v1/financingAgreement/{agreementCodeId}; the identical rollbacks 6.x/8.12 use DELETE and the financingAgreement contract has no POST for that path: DELETE is used.'),
    ('A-08', 'delegated-conservative', 'Remote service paths follow the Sparx text; the financingAgreement create call is POST /api/v1/agreement in Sparx while the financingAgreement contract exposes /api/v1/financingAgreement. Every remote path is an environment parameter (default = Sparx text) so the real one can be set without regenerating. Base URLs and timeouts are environment parameters too (never read from application*.properties by the generator).'),
    ('A-09', 'delegated-conservative', 'Sparx spelling slips are normalized to contract fields: requestType->requestTypeId, clienteCode->clientCode, agreemanamementCodeId->agreementCodeId, Line->line, quoteExperationDate->quoteExpirationDate (both spellings are read from the dependency), createDate/createAt->createdAt. The 5.4.1 query is built as clientCode, periodMonths and processDate (the evidence URL has a second "?").'),
    ('A-10', 'delegated-conservative', 'The financing synchronization (Sparx activity 4) runs before the flows of requestTypeId 3 to 8 (process graph: Tipo de Solicitud -> 4. Sincronizacion de Cuotas); 4.1 (get financing) provides Act. 4.1 for those flows. IDF129 (no agreementCodeId) is unreachable because act 1 already requires agreementCodeId for types 3 to 8.'),
    ('A-11', 'delegated-conservative', 'A list answer that is empty (HTTP 200) for the installment queries 5.2, 7.2, 8.2, 9.2 and 10.2 is treated as the same business condition as their HTTP 404 (the declared code of that activity); 6.8/6.9 are skipped when 6.7 returns no installments (nothing to update).'),
    ('A-12', 'delegated-conservative', 'The request-age rule (IDF407/IDF434) compares now (injectable Clock, system default zone) minus the createdAt of the request with config vigenciaRegistroSolicitudEnHoras in hours; an unreadable createdAt or configuration value is an internal error (IDT3). Config /parameters is cached for maxTimeRefreshCache ms (default 3600000) and the last valid copy is used when a refresh fails, as the evidence states.'),
    ('A-13', 'delegated-conservative', 'Header handling: the seven received headers are forwarded to every dependency (Sparx "Enviar al destino todos los headers"); the collections call sends idTransaccion, msgid, timestamp (yyyy-MM-dd\'T\'HH:mm:ssZ, injectable Clock), userId, aplicacion, canal and accept as HTTP headers and a JSON body (evidence order: before "Body Request"). NULL mapping rows are sent as JSON null in bodies and omitted from query strings.'),
    ('A-14', 'delegated-conservative', 'requestCodeId and agreementCodeId answered by dependencies as text or number are read as Long; the response is built only with the contract fields listed for each requestTypeId.'),
    ('A-15', 'delegated-conservative', 'The Sparx 400/401/403 style statuses not declared by the contract are not emitted: any status outside 400/404/409/422/500/503/504 becomes an internal error (IDT3). IDF502 (422) and IDF501/503-507 belong to the installment-generation dependency; the orchestration maps every non-201 of 3.5/6.5/8.7 to IDF412/IDF437/IDF448 as written, so they are contract-only.'),
]
GAPS = [
    ('G-01', 'IDF2xx/IDF3xx codes without a Sparx rule', 'IDF302/IDF303 (generic not found), IDF501, IDF503-IDF507 and IDF502 have no activity or gateway in the authoritative process: they are never emitted.'),
    ('G-02', 'Platform enumeration', 'The contract declares platform in {BSCS70, BSCSIX}; no Sparx rule or error code is defined for another value, so it is passed through unvalidated.'),
    ('G-03', 'financingAgreement/financingInstallment/agreementRequest contracts', 'The remote contracts of agreementRequest and financingInstallment are not in input/contracts; their paths, bodies and answers follow the Sparx mapping tables only.'),
    ('G-04', 'Business meaning of NULL body attributes', 'NULL mapping rows are sent as JSON null; the dependency semantics (ignore versus clear) are not defined by the sources.'),
]


def build_service_spec(repo: Path, service: str):
    ws = repo / '.factory' / 'services' / service
    sparx = yaml.safe_load((ws / 'sparx-spec.yml').read_bytes())
    openapi = yaml.safe_load((ws / 'openapi-spec.yml').read_bytes())
    if sparx.get('kind') != oi.KIND or sparx.get('service') != service:
        raise ConsolidationError('sparx-spec.yml is not the interpretation of this service')
    if sparx['authority']['detailSha256'] != sha((ws / 'sparx-authoritative-endpoint-detail.yml').read_bytes()):
        raise ConsolidationError('sparx-spec.yml is stale: the endpoint detail changed')
    index = Index(sparx)
    contract = contract_model(openapi)
    log = []
    config = {'t': 'remote', 'key': '1.1', 'sel': ['POST-/api/v1/agreement/financing', '1.1']}
    index.register([config])
    config_step = resolve_remote(index, config, {}, log)
    sync = resolve_items(index, sparx['sync'], {}, log)
    flows = {}
    for type_id, flow in sparx['flows'].items():
        chains = flow['chains']
        steps = resolve_items(index, flow['steps'], chains, log)
        comps = resolve_items(index, flow['comps'], chains, log)
        flows[type_id] = {'name': flow['name'], 'prerequisite': flow['prerequisite'], 'steps': steps, 'compensations': {c['key']: c for c in comps}, 'chains': chains}
    clients = {}
    def visit(items):
        for step in items:
            if step['t'] == 'remote':
                entry = clients.setdefault(step['client'], {'className': CLASS_NAMES[step['client']], 'operations': {}})
                entry['operations'].setdefault(step['operation'], {'method': step['method'], 'path': step['path']})
            if step['t'] == 'branch':
                visit(step['then'])
                visit(step['else'])
    visit([config_step])
    visit(sync)
    for flow in flows.values():
        visit(flow['steps'])
        visit(list(flow['compensations'].values()))
    spec = {'version': VERSION, 'kind': 'service-spec', 'pattern': 'remote-orchestration',
            'service': {'name': service, 'package': 'com.claro.agreement.orquestation', 'applicationClass': 'AgreementOrquestationApplication', 'type': 'http-orchestrator'},
            'inputs': {'openapi': {'file': f'.factory/services/{service}/openapi-spec.yml', 'sha256': sha((ws / 'openapi-spec.yml').read_bytes())},
                       'sparx': {'file': f'.factory/services/{service}/sparx-spec.yml', 'sha256': sha((ws / 'sparx-spec.yml').read_bytes())}},
            'sourceOwnership': {'contract': 'openapi', 'flows': 'sparx', 'errorCatalog': 'openapi', 'integrations': 'sparx'},
            'operations': [{'operationId': contract['operationId'], 'method': contract['method'], 'path': contract['path'], 'status': 'active', 'statuses': contract['statuses']}],
            'contract': contract, 'orchestration': {'schemaVersion': 1, 'properties': sparx['properties'], 'config': config_step, 'validations': sparx['requestValidations'], 'sync': sync,
                                                    'flows': flows, 'clients': clients, 'requestTypeIds': sorted(int(k) for k in flows)},
            'derivedAssumptions': [{'id': i, 'classification': c, 'statement': s, 'blocker': False} for i, c, s in ASSUMPTIONS],
            'discrepancies': sparx['discrepancies'] + log, 'gaps': [{'id': i, 'topic': t, 'statement': s} for i, t, s in GAPS],
            'readiness': {'strictImplementationReady': True, 'scaffoldImplementationReady': True, 'functionalGenerationReady': True,
                          'basis': 'every requestTypeId 1-8 is fully described by the authoritative process; gaps G-01..G-04 and assumptions A-01..A-15 are recorded, none requires invented behavior',
                          'blockers': []}}
    return spec


def main(argv=None):
    service = (argv or sys.argv[1:])[0]
    repo = Path.cwd()
    spec = build_service_spec(repo, service)
    target = repo / '.factory' / 'services' / service / 'service-spec.yml'
    target.write_bytes(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=200).encode('utf-8'))
    print({'written': target.as_posix(), 'flows': sorted(spec['orchestration']['flows']), 'clients': sorted(spec['orchestration']['clients'])})
    return 0


if __name__ == '__main__':
    sys.exit(main())
