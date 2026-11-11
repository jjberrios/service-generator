"""Closed FULL batch variant for the evidence-backed payment synchronization flow.

This extension does not enable arbitrary Java snippets or replace archetype policy.
Every payload remains plan-owned and all original batch gate/protection controls apply.
"""
import re
import hashlib
import json
from batch_shell_contract import GENERIC_FIELDS, GENERIC_KEYS, PROPERTY, identifier, keys, require

VARIANT = 'payment-sync-v1'
STEP_IDS = ('authentication', 'collections', 'financing', 'join', 'installments', 'completion')
# Closed interpreted semantics, including the explicit delegated wire assumptions.
# A changed mapping/algorithm/policy requires a reviewed extension, never silent omission.
SEMANTIC_SHA256 = '4120290eeb9360f7b4da73fb4f9354ac1e3e898314c076949bda576143b769b4'


def semantics(value):
    if isinstance(value, dict):
        return {key: semantics(item) for key, item in value.items() if key != 'evidence'}
    if isinstance(value, list):
        return [semantics(item) for item in value]
    return value


def java_inventory(package):
    return [f'src/main/java/{package}/client/PaymentHttpClient.java',
            f'src/test/java/{package}/client/PaymentHttpClientTest.java']


def maven_additions():
    return [
        {'groupId': 'com.fasterxml.jackson.core', 'artifactId': 'jackson-databind', 'version': '2.18.5',
         'justification': 'Nested REST JSON arrays, numeric values and explicit JSON null; Java 8 compatible addition',
         'requiredBy': VARIANT},
        {'groupId': 'org.apache.httpcomponents', 'artifactId': 'httpclient', 'version': '4.5.14',
         'justification': 'Java 8 REST transport with PATCH, bounded timeouts and no automatic retries',
         'requiredBy': VARIANT}]


def validate(batch):
    allowed = ('version', 'variant', 'properties', 'connections', 'steps', 'outcomes', 'sourceBindings', 'decisions', 'model')
    keys(batch, allowed, allowed)
    require(batch['version'] == 1 and batch['variant'] == VARIANT, 'unknown payment synchronization model')
    require(batch['connections'] == [], 'payment REST flow has no SFTP or database connections')
    bindings = set()
    require(isinstance(batch['sourceBindings'], list) and batch['sourceBindings'], 'source bindings required')
    for binding in batch['sourceBindings']:
        keys(binding, ('id', 'path', 'sha256'), ('id', 'path', 'sha256'))
        name = identifier(binding['id'])
        require(name not in bindings, 'duplicate source binding')
        bindings.add(name)
        path = binding['path']
        require(isinstance(path, str) and path.startswith('input/sparx/') and '\\' not in path
                and not set(path.split('/')) & {'', '.', '..'} and ':' not in path, 'unsafe Sparx path')
        require(re.fullmatch('[a-f0-9]{64}', str(binding['sha256'])), 'source SHA-256 required')

    def evidence(obj):
        refs = obj.get('evidence')
        require(isinstance(refs, list) and refs and all(isinstance(r, str) and '#' in r
                and r.split('#', 1)[0] in bindings and len(r.split('#', 1)[1].strip()) >= 5 for r in refs),
                'bound literal evidence required')

    def walk(node):
        if isinstance(node, dict):
            if 'evidence' in node:
                evidence(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    require(isinstance(batch['properties'], list) and batch['properties'], 'external properties required')
    props, fields = set(GENERIC_KEYS), set(GENERIC_FIELDS)
    for prop in batch['properties']:
        keys(prop, ('key', 'field', 'secret', 'evidence'), ('key', 'field', 'secret', 'evidence'))
        require(PROPERTY.fullmatch(str(prop['key'])) and prop['key'] not in props, 'duplicate/invalid property')
        field = identifier(prop['field'])
        require(field not in fields and isinstance(prop['secret'], bool), 'duplicate field or invalid secret flag')
        props.add(prop['key'])
        fields.add(field)
    require(isinstance(batch['steps'], list) and tuple(s.get('id') for s in batch['steps']) == STEP_IDS,
            'payment workflow must include all six ordered phases')
    for step in batch['steps']:
        keys(step, ('id', 'kind', 'evidence'), ('id', 'kind', 'evidence'))
        require(step['kind'] == step['id'], 'unsupported payment workflow step')
    keys(batch['outcomes'], ('success', 'generalFailure', 'evidence'), ('success', 'generalFailure', 'evidence'))
    require(batch['outcomes']['success'] == 'idf0' and batch['outcomes']['generalFailure'] == 'idt1',
            'unsupported technical log outcomes')
    require(isinstance(batch['decisions'], list) and batch['decisions'], 'explicit delegated decisions required')
    ids = set()
    for decision in batch['decisions']:
        keys(decision, ('id', 'selection', 'rationale', 'evidence'), ('id', 'selection', 'rationale', 'evidence'))
        require(isinstance(decision['id'], str) and decision['id'] and decision['id'] not in ids, 'unique decision id required')
        ids.add(decision['id'])
        require(all(isinstance(decision[k], str) and decision[k].strip() for k in ('selection', 'rationale')),
                'decision selection and rationale required')
    require(isinstance(batch['model'], dict) and batch['model'], 'complete typed payment model required')
    model = batch['model']
    require(tuple(c.get('id') for c in model.get('calls', [])) == (
        'authenticate', 'getCollectedPayments', 'getFinancingInstallments',
        'patchFinancingInstallments', 'patchFinancingAgreement'), 'all five typed calls required')
    require(model.get('omittedBehavior') == [] and model.get('scaffoldFallback') is False,
            'FULL payment model cannot omit behaviour')
    digest = hashlib.sha256(json.dumps(semantics(model), sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=True).encode('utf-8')).hexdigest()
    require(digest == SEMANTIC_SHA256, 'unsupported payment semantic change; extend and review the closed backend')
    require(ids == {'PD-' + str(i).zfill(2) for i in range(1, 14)}, 'all thirteen delegated decisions required')
    expected = {p['key']: (p['name'], p['secret']) for p in model['properties']}
    expected.update({'rest.connect.timeout.ms': ('restConnectTimeoutMs', False),
                     'rest.read.timeout.ms': ('restReadTimeoutMs', False)})
    actual = {p['key']: (p['field'], p['secret']) for p in batch['properties']}
    require(actual == expected, 'complete typed external configuration required')
    walk(batch)
    return batch
