"""Read-only checks: no writes, Maven, network or protected configuration access.

Run: python <archetype>/validate-extraction.py (requires available PyYAML).
This is not a generator, Java compiler or Checkstyle gate.
"""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import yaml
import sys


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        assert key not in result, "Duplicate YAML key"
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
target = Path(__file__).resolve().parent
root = target.parents[2]
sys.path.insert(0, str(root / '.opencode/skills/extract-archetype/scripts'))
from validate_inventory import validate
inventory_validation = validate(target)
assert inventory_validation['status'] == 'passed', inventory_validation
a = yaml.load((target / "archetype.yml").read_text(encoding="utf-8"), Loader=UniqueLoader)
reference = root / a["provenance"]["reference"]
template = target / "template"
files = {p.relative_to(template).as_posix(): p for p in template.rglob("*") if p.is_file()}
assert set(files) == {v["path"] for v in a["templateInventory"]}
assert a["identity"]["name"] == target.parent.name and 'v' + str(a["identity"]["version"]) == target.name
assert a["identity"]["approved"] is True
assert a["identity"]["approvalScope"] == "reference-based-extraction-baseline-only"
if a["identity"]["frozen"]:
    assert a["readiness"]["freezeAuthorized"] and a["identity"]["readyToFreeze"]
assert a["identity"]["generationEnabled"] is True  # J8-D-007
assert a["readiness"]["extractionComplete"] and a["readiness"]["baselineDecisionsApproved"]
assert a["readiness"]["runtimeCompatibility"] == "unverified"
assert a["unresolvedAmbiguities"] == []
for p in files.values():
    assert not (p.name.lower().startswith("application") and p.suffix.lower() == ".properties")
token = re.compile(r"@@([A-Z_]+)@@")
usage = {}
for name, p in files.items():
    for key in set(token.findall(name + "\n" + p.read_text(encoding="utf-8"))):
        usage.setdefault(key, set()).add(name)
assert set(usage) == set(a["parameters"])
for key, definition in a["parameters"].items():
    assert usage[key] == set(definition["affectedFiles"]), key
values = {
    "GROUP_ID": "org.example", "ARTIFACT_ID": "sample-service", "PROJECT_VERSION": "0.1.0",
    "BASE_PACKAGE": "org.example.sample", "BASE_PACKAGE_PATH": "org/example/sample",
    "APPLICATION_CLASS": "SampleApplication", "CONFIG_ROOT_PROPERTY": "sample.properties",
    "CONFIG_SUBDIRECTORY": "sample-service", "LOG_DIRECTORY": "/var/log/sample-service",
    "CONTEXT_ROOT": "sample-service", "CORPORATE_REPOSITORY_URL": "https://repo.example.invalid/releases/",
}
for key, value in values.items():
    assert re.fullmatch(a["parameters"][key]["pattern"], value), key
assert re.fullmatch(a["parameters"]["CORPORATE_REPOSITORY_URL"]["pattern"], "http://repo.example.invalid/releases/")
for bad in ["https://user:pass@repo.example.invalid/", "https://repo.example.invalid/?credential=value", "file:///local"]:
    assert not re.fullmatch(a["parameters"]["CORPORATE_REPOSITORY_URL"]["pattern"], bad)
assert values["BASE_PACKAGE_PATH"] == values["BASE_PACKAGE"].replace(".", "/")


def render(text):
    return token.sub(lambda match: values[match[1]], text)


xml_count, java_count = 0, 0
for name, p in files.items():
    text = p.read_text(encoding="utf-8")
    rn, rt = render(name), render(text)
    assert not token.search(rn + rt) and ".." not in Path(rn).parts
    if p.suffix == ".xml":
        ET.fromstring(text)
        ET.fromstring(rt)
        xml_count += 1
    if p.suffix == ".java":
        expected_package = Path(rn).parent.relative_to('src/main/java').as_posix().replace('/', '.')
        assert "package " + expected_package + ";" in rt
        assert re.search(r'public\s+(?:final\s+)?class\s+' + re.escape(Path(rn).stem) + r'\b', rt)
        assert rt.count("{") == rt.count("}") and "record " not in rt
        java_count += 1
    assert not (p.name.lower().startswith("application") and p.suffix.lower() == ".properties")
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
source = ET.fromstring((reference / "pom.xml").read_bytes())
dest = ET.fromstring(files["pom.xml"].read_bytes())


def canon(e):
    return (e.tag, (e.text or "").strip(), tuple(sorted(e.attrib.items())), tuple(canon(c) for c in e))


def direct(e, xpath):
    return e.findall(xpath, ns)


def fields(e):
    return {c.tag.split("}")[-1]: (c.text or "").strip() for c in e}


for xpath in ["m:dependencies/m:dependency", "m:build/m:plugins/m:plugin", "m:parent", "m:pluginRepositories"]:
    assert [canon(v) for v in direct(source, xpath)] == [canon(v) for v in direct(dest, xpath)], xpath
dependencies = [fields(e) for e in direct(dest, "m:dependencies/m:dependency")]
assert len(dependencies) == len(a["build"]["dependencies"]) == a["build"]["dependencyInventorySemantics"]["count"] == 24
for actual, declared in zip(dependencies, a["build"]["dependencies"]):
    expected = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in declared.items() if k != "purpose"}
    assert actual == expected
plugins = direct(dest, "m:build/m:plugins/m:plugin")
assert len(plugins) == len(a["build"]["plugins"]) == 4
for e, d in zip(plugins, a["build"]["plugins"]):
    for key in ["groupId", "artifactId", "version"]:
        assert e.findtext("m:" + key, default=None, namespaces=ns) == d.get(key)
    config = e.find("m:configuration", ns)
    if config is not None:
        assert fields(config) == {k: str(v).lower() for k, v in d["configuration"].items()}
    executions = direct(e, "m:executions/m:execution")
    if executions:
        assert [{"id": z.findtext("m:id", namespaces=ns), "phase": z.findtext("m:phase", namespaces=ns),
                 "goals": [g.text for g in direct(z, "m:goals/m:goal")]} for z in executions] == d["executions"]
before, after = fields(source.find("m:properties", ns)), fields(dest.find("m:properties", ns))
assert after == a["build"]["properties"] and set(before) == set(after)
assert {k for k in before if before[k] != after[k]} == {"sonar.coverage.exclusions", "sonar.exclusions"}
# Full POM equivalence except explicitly authorized identity/environment/domain removals.
# No dependency/plugin/profile/version/scope change can hide behind the inventory.
for xpath in ["m:groupId", "m:artifactId", "m:version", "m:name", "m:description",
              "m:properties/m:sonar.coverage.exclusions", "m:properties/m:sonar.exclusions",
              "m:repositories/m:repository/m:url"]:
    source.find(xpath, ns).text = dest.find(xpath, ns).text
assert canon(source) == canon(dest), "POM changed outside authorized transformations"
repos = direct(dest, "m:repositories/m:repository")
assert len(repos) == len(a["build"]["repositories"]) == 1
for e, d in zip(repos, a["build"]["repositories"]):
    assert fields(e) == {k: d[k] for k in ["id", "name", "url"]}
plugin_repos = direct(dest, "m:pluginRepositories/m:pluginRepository")
assert len(plugin_repos) == len(a["build"]["pluginRepositories"]) == 2
for e, d in zip(plugin_repos, a["build"]["pluginRepositories"]):
    for key in ["id", "name", "url"]:
        assert e.findtext("m:" + key, namespaces=ns) == d[key]
    for policy in ["releases", "snapshots"]:
        enabled = e.findtext("m:" + policy + "/m:enabled", default=None, namespaces=ns)
        assert enabled == (str(d[policy]["enabled"]).lower() if policy in d else None)
assert (reference / ".gitignore").read_text(encoding="utf-8").strip() == files[".gitignore"].read_text(encoding="utf-8").strip()
logging = ET.fromstring(files["config/logback.xml"].read_bytes())
assert logging.find("root").attrib["level"] == a["runtime"]["logging"]["level"]
assert logging.findtext("appender/rollingPolicy/maxHistory") == str(a["runtime"]["logging"]["maxHistory"])
assert logging.findtext("appender/rollingPolicy/totalSizeCap") == a["runtime"]["logging"]["totalSizeCap"]
source_logging = ET.fromstring((reference / "config/logback.xml").read_bytes())
for xpath in ["appender/File", "appender/rollingPolicy/fileNamePattern"]:
    source_logging.find(xpath).text = logging.findtext(xpath)
assert canon(source_logging) == canon(logging), "Logging structure differs beyond path/name parameters"
wls_ns = {"w": "http://xmlns.oracle.com/weblogic/weblogic-web-app"}
source_wls = ET.fromstring((reference / "src/main/webapp/WEB-INF/weblogic.xml").read_bytes())
dest_wls = ET.fromstring(files["src/main/webapp/WEB-INF/weblogic.xml"].read_bytes())
source_wls.find("w:context-root", wls_ns).text = dest_wls.findtext("w:context-root", namespaces=wls_ns)
assert canon(source_wls) == canon(dest_wls)
descriptor_path = "src/main/webapp/WEB-INF/dispatcherServlet-servlet.xml"
assert canon(ET.fromstring((reference / descriptor_path).read_bytes())) == canon(ET.fromstring(files[descriptor_path].read_bytes()))
evidence = a["evidence"]["entries"]
for e in evidence.values():
    assert (reference / e["path"]).exists()
for item in a["templateInventory"]:
    assert set(item["evidence"]).issubset(evidence)
    assert item["status"] in {"approved-reference-baseline", "approved-human-decision"} and "blockedBy" not in item
    assert set(item["decisionRefs"]).issubset(a["provenance"]["approvedDecisionRefs"])
assert {q["id"] for q in a["resolvedQuestions"]} == {"J8-Q-%03d" % i for i in range(1, 6)}
assert {"J8-D-%03d" % i for i in range(1, 10)}.issubset(a["provenance"]["approvedDecisionRefs"])
for q in a["resolvedQuestions"]:
    assert q["status"] == "resolved-by-current-human-instruction"
    assert set(q["decisionRefs"]).issubset(a["provenance"]["approvedDecisionRefs"])
    for doc in ["decisions.md", "conventions.md", "generation-rules.md", "extraction-report.md"]:
        assert q["id"] in (target / doc).read_text(encoding="utf-8")
for d in a["provenance"]["approvedDecisionRefs"]:
    for doc in (["decisions.md"] if d in {"J8-D-007", "J8-D-008", "J8-D-009"} else ["decisions.md", "conventions.md"]):
        assert d in (target / doc).read_text(encoding="utf-8")
checkstyle = a["quality"]["checkstyle"]
assert checkstyle["referenceConfigurationObserved"] is False
assert checkstyle["policyRequired"] is False and checkstyle["requiredScopes"] == []
assert checkstyle["status"] == "not-present-in-reference"
assert checkstyle["configurationDecision"] == "J8-D-004"
assert checkstyle["execution"] == a["validation"]["checkstyle"] == "not-applicable"
assert not any("checkstyle" in p.name.lower() for p in reference.rglob("*") if ".idea" not in p.parts)
assert not any(d["artifactId"].lower().find("checkstyle") >= 0 for d in a["build"]["plugins"])

# Dependency declaration is not proof of use. Scan only Java (never protected config).
java_sources = list((reference / "src").rglob("*.java"))
assert len(java_sources) == 51
java_text = "\n".join(p.read_text(encoding="utf-8") for p in java_sources)
usage_inventory = a["build"]["dependencyUsage"]
assert set(usage_inventory) == {d["artifactId"] for d in a["build"]["dependencies"]}
for item in usage_inventory.values():
    assert item["status"] and item["observation"] and set(item["evidence"]).issubset(evidence)
for prefix in ["org.springframework.ws", "javax.el", "javax.persistence", "com.google.gson",
               "org.apache.commons.collections4", "org.apache.commons.lang3", "org.assertj",
               "org.powermock", "javassist", "oracle"]:
    assert not re.search(r"\bimport\s+(?:static\s+)?" + re.escape(prefix) + r"[.;]", java_text)
assert not re.search(r"@ConfigurationProperties\b", java_text)
for api in ["org.springframework.web.bind.annotation", "JndiDataSourceLookup",
            "org.hibernate.dialect.OracleTypesHelper", "org.junit.Test", "org.mockito.Mock",
            "javax.ws.rs.core.HttpHeaders", "com.fasterxml.jackson.databind.ObjectMapper"]:
    assert api in java_text
assert not re.search(r"\bimport\s+org.springframework.data\.|@Entity\b", java_text)
assert a["runtime"]["logging"]["helperTemplated"] is False
assert a["runtime"]["logging"]["activityPatternDecision"] == "J8-D-003"
assert "new ObjectMapper()" in java_text and "inicioActividad(String menTran, String actividad)" in java_text
for method in ["inicioActividad", "finActividad"]:
    assert method + "(String menTran, String actividad)" in java_text
for line in ["logger.info(menTran + Constantes.SEPARADOR);",
             "logger.info(menTran + Constantes.INICIO_ACTIVIDAD + actividad + Constantes.SEPARADOR_ACTIVIDAD);",
             "logger.info(menTran + Constantes.FIN_ACTIVIDAD + actividad + Constantes.SEPARADOR_ACTIVIDAD);"]:
    assert line in java_text
assert 'TIEMPO_TOTAL_PROCESO = " Tiempo total de proceso(ms): [ "' in java_text
assert "writerWithDefaultPrettyPrinter()" in java_text
assert "configure(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS, false)" in java_text
initializer = next(p for name, p in files.items() if name.endswith("/ServletInitializer.java")).read_text(encoding="utf-8")
assert 'System.getProperty("@@CONFIG_ROOT_PROPERTY@@") + "@@CONFIG_SUBDIRECTORY@@" + File.separator' in initializer
assert "new File(" not in initializer
ci = a["deployment"]["ci"]
ci_text = (reference / "Jenkinsfile").read_text(encoding="utf-8")
assert ci["observedCall"] in ci_text
assert re.findall(r"(?m)^\s*(?:springBootPipelineV3\()?([A-Za-z_]+):", ci_text) == ci["parameterKeys"]
assert not ci["sharedLibraryImplementationAvailable"] and not ci["executableTemplateIncluded"]
assert "Jenkinsfile" not in files
assert a["generationOwnership"]["apiContract"] == "OpenAPI"
assert a["generationOwnership"]["businessBehavior"] == "Sparx"
assert a["generationOwnership"]["persistenceBehavior"] == "Sparx"
assert a["generationOwnership"]["inventedFutureBehavior"] is False

# Secret scans never expose matched material. Source identity is allowed in evidence only.
leakage = re.compile(r"(?i)rest-sb-claro-post-atencion|claro-post-atencion|pe\.com\.claro\.post\.atencion|CRMLITE|ConsultarAtencion|ConsultarCheckNotifica|RegistraReglaNotificacion|ConsultarDetNivel|ChekNotifica|DetalleTipi|ResponseAudit|PI_CUENTA_ASESOR|biometr|ms-individual")
for name, p in files.items():
    text = name + "\n" + p.read_text(encoding="utf-8")
    # J8-D-009 explicitly retains the corporate datasource pair in these templates.
    if name in {'config/properties.config.j2', 'jndi/@@ARTIFACT_ID@@.yml'}:
        text = re.sub(r'(?i)CRMLITE', '', text)
    assert not leakage.search(text), 'Domain leakage: ' + name
secret_patterns = [
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", r"AKIA[A-Z0-9]{16}",
    r"(?i)https?://[^/\s<>]+:[^/\s<>]+@",
    r"(?i)(?:password|passwd|secret|token)\s*[:=]\s*['\"][^@\s][^'\"\n]{3,}['\"]",
    r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9.]+\b",
]
for p in target.rglob("*"):
    if p.is_file() and p != Path(__file__).resolve() and '__pycache__' not in p.parts:
        assert not (p.name.lower().startswith("application") and p.suffix.lower() == ".properties")
        text = p.read_text(encoding="utf-8")
        assert not any(re.search(pattern, text) for pattern in secret_patterns), "Potential secret/private-address file: " + p.relative_to(target).as_posix()
records, paths = [], []
for p in sorted(reference.rglob("*")):
    if not p.is_file():
        continue
    relative = p.relative_to(root).as_posix()
    paths.append(relative)
    if p.name.lower().startswith("application") and p.suffix.lower() == ".properties":
        continue  # No content access or metadata comparison for protected files.
    records.append([relative, hashlib.sha256(p.read_bytes()).hexdigest()])
records.sort(key=lambda record: record[0])
serialized = json.dumps(records, ensure_ascii=True, separators=(",", ":"))
# The historical baseline covered every project under input/reference and included
# mtimes. It cannot prove this target's content identity independently. Preserve it
# in the manifest; do not overwrite it with a fresh, self-approving baseline.
reference_current_sha256 = hashlib.sha256(serialized.encode()).hexdigest()
paths_serialized = json.dumps(sorted(paths), ensure_ascii=True, separators=(",", ":"))
assert hashlib.sha256((reference / "pom.xml").read_bytes()).hexdigest() == a["provenance"]["referencePomSha256"]
print(json.dumps({
    "yaml": "passed-unique-keys", "templates": len(files), "parametersUsed": len(usage),
    "xmlWellFormedOriginalAndRendered": xml_count, "javaStructuralRenderOnly": java_count,
    "javaSyntaxCompilation": "not-run", "directDependenciesExact": len(dependencies),
    "pluginsExact": len(plugins), "declaredProperties": len(after), "evidenceLocations": len(evidence),
    "completePomAuthorizedTransformsOnly": True, "dependencyUsageEntries": len(usage_inventory),
    "javaSourceUsageScan": len(java_sources), "resolvedQuestions": len(a["resolvedQuestions"]),
    "approvedDecisionRefs": len(a["provenance"]["approvedDecisionRefs"]), "jenkinsParameterKeys": len(ci["parameterKeys"]),
    "loggingAndDeploymentXmlFidelity": "authorized-parameters-only", "loggingPatternSourceAssertions": "passed",
    "templateDomainLeakageMatches": 0, "archetypeSecretHeuristicMatches": 0,
    "permittedReferenceRecordsInspected": len(records), "referenceFileCount": len(paths),
    "referenceFilePathInventory": "target-only-current-inventory",
    "referenceContentIdentity": "unverified-legacy-baseline-has-global-scope",
    "referenceCurrentContentSha256": reference_current_sha256,
    "protectedFileContentAndMetadataComparison": "not-performed",
    "mavenTestsJacocoSonar": "not-run", "checkstyle": "not-applicable; not-present-in-reference",
    "extractionComplete": True, "baselineDecisionsApproved": True,
    "generatorBackend": a["readiness"]["generatorBackend"], "runtimeCompatibility": a["readiness"]["runtimeCompatibility"],
    "freezeAuthorized": a["readiness"]["freezeAuthorized"], "readyToFreeze": a["identity"]["readyToFreeze"],
}, ensure_ascii=False, indent=2))
