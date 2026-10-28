"""Generation profile resolution: each archetype owns its generation rules."""
LEGACY_JPA = "spring-data-jpa-activity-logger"
JDBC_WAR = "war-jdbc-callablestatement-junit4"
SUPPORTED = (LEGACY_JPA, JDBC_WAR)


def resolve(archetype: dict) -> str:
    declared = (archetype.get("generation") or {}).get("profile")
    if declared:
        profile = str(declared)
    elif ((archetype.get("persistence") or {}).get("technology")) == "spring-data-jpa":
        profile = LEGACY_JPA
    else:
        raise ValueError("archetype declares no supported generation profile")
    if profile not in SUPPORTED:
        raise ValueError("unsupported generation profile: " + profile)
    return profile
