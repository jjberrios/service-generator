"""Versioned read-only adapters. Never rewrites or borrows another manifest."""
from copy import deepcopy

CONTRACT_VERSION = 1
REGISTRY_VERSION = 1
LEGACY_JPA = 'spring-data-jpa-activity-logger'
JDBC_WAR = 'war-jdbc-callablestatement-junit4'
BATCH_SHELL = 'batch-shell-jar-spring-xml-log4j-sftp-junit4'
BFF = 'jar-springboot3-webmvc-webclient-bff'
CAPABILITIES = {
    LEGACY_JPA: {'version': 1, 'planner': 'full_implementation_plan',
                 'materializer': 'full_materializer', 'inputKind': 'http',
                 'templateDialect': '__TOKEN__', 'scaffold': True,
                 'limits': ['one-relational-table', 'specified-select-insert-update']},
    JDBC_WAR: {'version': 1, 'planner': 'jdbc_war_plan',
               'materializer': 'jdbc_war_materializer', 'inputKind': 'http',
               'templateDialect': '@@TOKEN@@', 'scaffold': False,
               'limits': ['jdbc-callablestatement', 'explicit-jdbc-binding-v1']},
    BFF: {'version': 1, 'planner': 'bff_plan',
          'materializer': 'bff_materializer', 'inputKind': 'http',
          'templateDialect': '@@TOKEN@@', 'scaffold': False,
          'limits': ['structure-and-contract', 'explicit-bff-binding-v1-identity-webclient', 'no-persistence', 'behavior-without-binding-omitted']},
    BATCH_SHELL: {'version': 1, 'planner': 'batch_shell_plan',
                  'materializer': 'batch_shell_materializer', 'inputKind': 'batch',
                  'templateDialect': '@@TOKEN@@', 'scaffold': False,
                  'limits': ['bounded-sftp-ir-v1', 'soap-decryption-only-with-archetype-feature', 'no-persistence', 'no-mail']},
}


class ContractError(ValueError):
    pass


def normalize(source):
    if not isinstance(source, dict):
        raise ContractError('invalid-archetype-manifest')
    if 'identity' in source and 'archetype' in source:
        raise ContractError('ambiguous-archetype-schema')
    if 'identity' in source:
        if source.get('schemaVersion') != 1:
            raise ContractError('unsupported-archetype-schema-version')
        identity = source['identity']
        name, version = identity.get('name'), identity.get('version')
        adapter = 'identity-v1'
        lifecycle = {k: identity.get(k) for k in ('approved', 'frozen', 'generationEnabled')}
        decisions = (source.get('provenance') or {}).get('approvedDecisionRefs', [])
    else:
        identity = source.get('archetype') or {}
        name, version = identity.get('id'), identity.get('version')
        if str(source.get('schema_version')) != '1.0' or name != 'claro-spring-ms' or str(version) not in ('1.0.0', '1.0.1'):
            raise ContractError('unsupported-archetype-schema: no compatibility adapter')
        adapter = 'claro-spring-ms-1.0.0-compat-v1'
        # Legacy manifest lacks flags; preserve unknown rather than inventing approval.
        lifecycle = {k: None for k in ('approved', 'frozen', 'generationEnabled')}
        decisions = (source.get('governance') or {}).get('approved_decision_ids', [])
    if not isinstance(name, str) or not isinstance(version, str) or not name or not version:
        raise ContractError('missing-archetype-identity')
    profile = (source.get('generation') or {}).get('profile')
    if profile is None and adapter == 'claro-spring-ms-1.0.0-compat-v1':
        if (source.get('persistence') or {}).get('technology') != 'spring-data-jpa':
            raise ContractError('legacy-adapter-persistence-conflict')
        profile = LEGACY_JPA
    quality = (source.get('quality') or {}).get('checkstyle') or {}
    if quality.get('mandatory_generation_gate') is True or quality.get('policyRequired') is True:
        checkstyle = 'required'
    elif quality.get('status') == 'not-present-in-reference' or quality.get('execution') == 'not-applicable':
        checkstyle = 'not-applicable'
    elif quality.get('enabled') is True:
        checkstyle = 'present'
    else:
        checkstyle = 'unknown'
    capability = CAPABILITIES.get(profile)
    return {'contractVersion': CONTRACT_VERSION, 'adapter': adapter,
            'identity': {'name': name, 'version': version}, 'lifecycle': lifecycle,
            'profile': profile, 'registryVersion': REGISTRY_VERSION,
            'backend': deepcopy(capability), 'backendSupported': capability is not None,
            'decisions': deepcopy(decisions),
            'quality': {'checkstyle': {'applicability': checkstyle, 'source': deepcopy(quality)}},
            'style': deepcopy((source.get('generation') or {}).get('style')),
            'templateInventory': deepcopy(source.get('templateInventory'))}


def require_backend(contract, *, mode='full'):
    if contract.get('contractVersion') != CONTRACT_VERSION:
        raise ContractError('unsupported-normalized-contract-version')
    if not contract['backendSupported']:
        raise ContractError(f"unsupported-generation-profile: {contract['profile']!r}")
    if mode == 'scaffold' and not contract['backend']['scaffold']:
        raise ContractError(f"unsupported-scaffold-profile: {contract['profile']}")
    if mode not in ('full', 'scaffold'):
        raise ContractError(f'unsupported-generation-mode: {mode}')
    return contract['profile']
