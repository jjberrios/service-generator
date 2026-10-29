"""Generation profile resolution: each archetype owns its generation rules."""
from archetype_contract import LEGACY_JPA, JDBC_WAR, BATCH_SHELL, CAPABILITIES, normalize, require_backend
SUPPORTED = tuple(CAPABILITIES)


def resolve(archetype: dict) -> str:
    return require_backend(normalize(archetype))
