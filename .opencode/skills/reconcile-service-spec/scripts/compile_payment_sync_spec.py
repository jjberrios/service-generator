"""Compile the specialist's closed typed proposal into non-HTTP batch IR.

This is not a source parser or an approval writer. It never authorizes the gate.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import yaml

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / '.opencode/skills/plan-service-implementation/scripts'))
from batch_payment_sync_model import STEP_IDS, validate
import batch_evidence


def compile_spec(repo, service):
    import re
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*', service):
        raise ValueError('unsafe workspace identifier')
    ws = repo / '.factory/services' / service
    read = lambda name: yaml.safe_load((ws / name).read_bytes())
    normalized = read('payment-synchronization-normalized-model.yml')
    original = read('payment-synchronization-semantics.yml')
    proposals = read('delegated-decisions-proposal.yml')
    if normalized['service']['name'] != service or proposals['targetService'] != service:
        raise ValueError('target mismatch')
    expected = normalized['provenance']['originalProposalSha256']
    if hashlib.sha256((ws / 'payment-synchronization-semantics.yml').read_bytes()).hexdigest() != expected:
        raise ValueError('stale specialist proposal')
    bindings = list(normalized['sourceBindings'])
    known = {b['path'] for b in bindings}
    for index, binding in enumerate(original['provenance']['sourceBindings']):
        if binding['path'] not in known:
            bindings.append({'id': 'source' + str(index), 'path': binding['path'], 'sha256': binding['sha256']})
            known.add(binding['path'])
    model = normalized['implementationModel']
    properties = [{'key': p['key'], 'field': p['name'], 'secret': p['secret'], 'evidence': p['evidence']}
                  for p in model['properties']]
    properties.extend({'key': key, 'field': field, 'secret': False, 'evidence': ['auth#consultaClavesWS']}
                      for key, field in [('rest.connect.timeout.ms', 'restConnectTimeoutMs'),
                                         ('rest.read.timeout.ms', 'restReadTimeoutMs')])
    refs = ['auth#consultaClavesWS', 'payments#collection-integration', 'financingRead#financingInstallment',
            'filter#ALGORITMO', 'installmentUpdate#financingInstallment', 'completion#ALGORITMO']
    batch = {'version': 1, 'variant': 'payment-sync-v1', 'properties': properties,
             'connections': [], 'steps': [{'id': name, 'kind': name, 'evidence': [ref]}
                                        for name, ref in zip(STEP_IDS, refs)],
             'outcomes': {'success': 'idf0', 'generalFailure': 'idt1', 'evidence': ['auth#consultaClavesWS']},
             'sourceBindings': bindings,
             'decisions': [{'id': d['id'], 'selection': d['selectedAssumption'], 'rationale': d['rationale'],
                            'evidence': d['evidence']} for d in proposals['decisions']], 'model': model}
    validate(batch)
    checked = batch_evidence.verify(batch, repo)
    if checked:
        raise ValueError('literal evidence verification failed: ' + str(checked))
    for binding in bindings:
        path = repo / binding['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != binding['sha256']:
            raise ValueError('stale source: ' + binding['path'])
    spec = {'service': {'name': service, 'profile': 'batch-shell'}, 'batch': batch,
            'warnings': ['Authentication REST binding and thirteen listed decisions are delegated assumptions, '
                         'not an externally verified contract. Runtime interoperability remains unverified.']}
    payload = yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=160)
    destination = ws / 'sparx-spec.yml'
    if destination.exists() and destination.read_text(encoding='utf-8') != payload:
        raise ValueError('different existing Sparx candidate; explicit analysis revision required')
    destination.write_text(payload, encoding='utf-8', newline='\n')
    return {'status': 'compiled-not-authorized', 'sources': len(bindings), 'decisions': len(batch['decisions']),
            'artifact': str(destination.relative_to(repo)),
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('service')
    args = parser.parse_args()
    print(yaml.safe_dump(compile_spec(REPO, args.service), sort_keys=False))
