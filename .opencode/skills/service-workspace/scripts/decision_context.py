"""Decision context v1. Content identity, NEVER human identity or authorization."""
import hashlib
import json
from pathlib import Path
import sys

from generation_context import load_mapping, resolve_context
from artifact_integrity import safe_path, archetype_hashes, protected
import workspace as wsm
import consistency_gate as gate

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'plan-service-implementation/scripts'))
import archetype_contract as ac

PURPOSES = ('resolve-findings', 'clarify-analysis', 'technical-choice', 'authorize-operation')
ARTIFACTS = ('openapi-spec.yml', 'sparx-target-authority.yml',
             'sparx-authoritative-endpoint-detail.yml', 'sparx-spec.yml', 'service-spec.yml',
             'sparx-reviewed-decisions.yml', 'consistency/resolutions.yml',
             'consistency/decision-coverage.yml', 'consistency/supplemental.yml',
             'consistency/batch-review.yml')


class DecisionError(ValueError):
    pass


def canonical(value):
    try:
        return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                           separators=(',', ':')) + '\n').encode('utf-8')
    except (ValueError, TypeError, RecursionError) as error:
        raise DecisionError('non-json-decision-contract') from error


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def source_path(repo, rel):
    if not isinstance(rel, str) or not rel.startswith(('input/contracts/', 'input/sparx/')) or protected(rel):
        raise DecisionError('invalid-decision-source-path')
    return safe_path(repo, rel)


def build(repo, service, purpose):
    """Read-only snapshot; no gate persistence, checkpoint refresh or approvals.

    Incomplete/stale audit remains representable for analysis requests. Unexpected
    parser failures propagate; they are not converted into a successful context.
    """
    if purpose not in PURPOSES:
        raise DecisionError('invalid-decision-purpose')
    repo = Path(repo).resolve()
    ws = wsm.Workspace(repo, service)
    safe_path(repo, f'.factory/services/{service}')
    selection = resolve_context(repo, service=service)
    arch = safe_path(repo, selection.archetype.as_posix())
    contract = ac.normalize(load_mapping(safe_path(arch, 'archetype.yml')))
    artifacts = {name: load_mapping(safe_path(ws.dir, name)) for name in ARTIFACTS}
    authority = artifacts['sparx-target-authority.yml']
    if authority.get('target', {}).get('name') not in (None, service):
        raise DecisionError('decision-authority-service-mismatch')
    root = authority.get('target', {}).get('sourceRoot')
    if root is not None:
        source_path(repo, root.rstrip('/') + '/placeholder')
    sources = set()
    source = artifacts['openapi-spec.yml'].get('source', {}).get('path')
    if source:
        source_path(repo, source)
        sources.add(source)

    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'path' and isinstance(value, str) and value.startswith('input/'):
                    source_path(repo, value)
                    sources.add(value)
                elif key in ('page', 'pagePath') and isinstance(value, str) and root:
                    rel = root.rstrip('/') + '/' + value.split('#', 1)[0]
                    source_path(repo, rel)
                    sources.add(rel)
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    for value in artifacts.values():
        collect(value)
    # Same live TOC inventory used by resolve_target_authority/source_currency;
    # no whole-export scan, no execution of the HTML or JavaScript.
    if root:
        data = source_path(repo, root.rstrip('/') + '/js/data')
        for path in sorted(data.glob('*.xml')):
            rel = path.relative_to(repo).as_posix()
            source_path(repo, rel)
            sources.add(rel)
    live = {rel: hashlib.sha256(source_path(repo, rel).read_bytes()).hexdigest()
            if source_path(repo, rel).is_file() else None for rel in sorted(sources)}
    # Validate all recorded TOC references too, before the legacy evaluator reads.
    for rel in authority.get('hierarchySources', {}).get('tocFiles', {}) or {}:
        # Recorded TOC keys are filenames, scoped to js/data by the parser.
        if root:
            source_path(repo, root.rstrip('/') + '/js/data/' + rel)
    try:
        evaluation = gate.current_decision(ws.dir, repo, service, persist=False)
        registry = evaluation.get('_registry') or {}
        findings = gate.blocking_items(registry)
        audit = {'state': 'evaluated', 'comparison': evaluation.get('comparison', 'sparx-openapi'),
                 'problems': evaluation.get('problems', []) if not registry else []}
    except gate.GateError as error:
        findings = []
        audit = {'state': 'unavailable', 'reason': error.status}
    context = {
        'schemaVersion': 1, 'kind': 'decision-context',
        'repository': {'id': digest({'localLocation': repo.as_posix()}),
                       'identityKind': 'local-location-untrusted'},
        'service': service, 'purpose': purpose,
        'archetype': {'path': selection.archetype.as_posix(), 'identity': contract['identity'],
                      'profile': contract['profile'], 'fingerprints': archetype_hashes(arch)},
        'artifactFingerprints': {name: digest(value) for name, value in artifacts.items()},
        'sources': live, 'findings': sorted(findings, key=lambda x: (x['fingerprint'], x['id'])),
        'semanticReview': {name: artifacts[name] for name in
                           ('consistency/supplemental.yml', 'consistency/batch-review.yml')},
        'previousDecisions': artifacts['sparx-reviewed-decisions.yml'],
        'audit': audit,
        'security': 'proposal-only; hashes do not authenticate humans; H-02 remains open',
    }
    context['contextId'] = digest(context)
    return context
