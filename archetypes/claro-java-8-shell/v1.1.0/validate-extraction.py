"""Read-only static checks for archetype claro-java-8-shell/1.1.0.

No writes, Maven, network, database or protected-configuration value access.
Run: python archetypes/claro-java-8-shell/v1.1.0/validate-extraction.py [--print-baseline]
(requires PyYAML). This is NOT a generator, Java compiler, Maven run or Checkstyle gate.
"""
import fnmatch
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        assert key not in result, "Duplicate YAML key: %r" % (key,)
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


def norm(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def rtext(path):
    return norm(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- reference baseline
def is_protected(rel):
    name = Path(rel).name.lower()
    if name.startswith("application") and name.endswith(".properties"):
        return True
    return "/" not in rel and name.endswith(".properties")  # root-level env configuration


records, paths = [], []
for p in sorted((reference).rglob("*")):
    if not p.is_file():
        continue
    rel = p.relative_to(reference).as_posix()
    paths.append(rel)
    if is_protected(rel):
        continue  # never read or hashed
    records.append([rel, p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()])
records.sort(key=lambda r: r[0])
permitted_sha = hashlib.sha256(json.dumps(records, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
paths_sha = hashlib.sha256(json.dumps(sorted(paths), ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
pom_sha = hashlib.sha256((reference / "pom.xml").read_bytes()).hexdigest()
if "--print-baseline" in sys.argv:
    print(json.dumps({"fileCount": len(paths), "contentHashedFileCount": len(records),
                      "contentExcludedFileCount": len(paths) - len(records),
                      "permittedRecordsSha256": permitted_sha, "filePathsSha256": paths_sha,
                      "referencePomSha256": pom_sha}, indent=2))
    sys.exit(0)
b = a["provenance"]["baseline"]
assert len(paths) == b["fileCount"] and len(records) == b["contentHashedFileCount"]
assert len(paths) - len(records) == b["contentExcludedFileCount"]
assert permitted_sha == b["permittedRecordsSha256"], "Reference content changed (permitted files)"
assert paths_sha == b["filePathsSha256"], "Reference file inventory changed"
assert pom_sha == a["provenance"]["referencePomSha256"]

# ---------------------------------------------------------------- identity / governance
ident = a["identity"]
assert ident["name"] == "claro-java-8-shell" and ident["version"] == "1.1.0" and ident["baseVersion"] == "1.0.0"
assert ident["operation"] == "extract" and ident["profile"] == "batch-shell"
assert ident["frozen"] is False and ident["generationEnabled"] is True
assert ident["readyToFreeze"] is False
assert ident["status"] == "approved-generation-enabled-not-frozen"
assert ident["approved"] is True
assert ident["approvalScope"] == "user-instructed-recovery-of-reusable-technical-infrastructure"
assert not (root / "archetypes/claro-java-8-shell/v1.1.0").samefile(root / "archetypes/claro-java-8-shell/v1.0.0")
assert a["provenance"]["futureContractsInspected"] is False and a["provenance"]["sparxInspected"] is False
assert a["provenance"]["inheritedDecisions"] == []
assert a["readiness"]["freezeAuthorized"] is False and a["readiness"]["serviceGenerationAuthorized"] is False
assert a["readiness"]["generationEnablementAuthorized"] is True
assert a["readiness"]["releaseDecision"] == "SH-D-017"
assert set(a["provenance"]["approvedDecisionRefs"]) == {"SH-D-%03d" % n for n in range(1, 18)}
assert set(a["provenance"]["carriedForwardDecisions"]) == {"SH-D-%03d" % n for n in range(1, 11)}
# honest backend declaration: the IR v1 backend does not support the new steps
assert a["readiness"]["generatorBackend"].startswith("implemented-bounded")
assert a["readiness"]["generatorBackendValidation"].startswith("synthetic-python-tests")
for step in ("decrypted-soap", "Mail"):
    assert step in a["readiness"]["generatorBackendDetail"], step
modules = {m["id"]: m for m in a["generation"]["featureModules"]}
assert set(modules) == {"credential-decrypt-soap", "mail-notification"}
assert modules["credential-decrypt-soap"]["backendSupport"] == "supported-batch-ir-v1-decrypted-soap"
assert modules["mail-notification"]["status"] == "not-present-in-reference-source"
# v1.0.0 must stay frozen and untouched (its own validator is the authority for its content)
v100 = yaml.load((root / "archetypes/claro-java-8-shell/v1.0.0/archetype.yml").read_text(encoding="utf-8"), Loader=UniqueLoader)
assert v100["identity"]["version"] == "1.0.0" and v100["identity"]["frozen"] is True
assert a["readiness"]["baselineDecisionsApproved"] is True
assert a["platform"]["httpEndpoints"] == "none" and a["execution"]["httpEndpoints"] == "none"
assert a["execution"]["kind"] == "batch-shell"
own = a["generationOwnership"]
assert own["apiContract"].startswith("not-applicable") and own["httpValidation"] == "not-applicable"
assert own["businessBehavior"] == "Sparx" and own["integrations"] == "Sparx"
assert own["persistenceBehavior"] == "Sparx" and own["inventedFutureBehavior"] is False
assert own["localConfigurationAndSecrets"] == "environment-operator"

# ---------------------------------------------------------------- template inventory
assert set(files) == {v["path"] for v in a["templateInventory"]}, "templateInventory != template tree"
assert len(files) == 20, len(files)
for p in files.values():
    assert not (p.name.lower().startswith("application") and p.suffix.lower() == ".properties")
    assert p.suffix.lower() != ".jar" and p.suffix.lower() != ".class"

token = re.compile(r"@@([A-Z_]+)@@")
usage = {}
for name, p in files.items():
    for key in set(token.findall(name + "\n" + p.read_text(encoding="utf-8"))):
        usage.setdefault(key, set()).add(name)
assert set(usage) == set(a["parameters"]), (set(usage) ^ set(a["parameters"]))
for key, definition in a["parameters"].items():
    assert usage[key] == set(definition["affectedFiles"]), key

values = {
    "GROUP_ID": "org.example.batch", "ARTIFACT_ID": "SH_SampleJob", "PROJECT_VERSION": "0.1.0",
    "BASE_PACKAGE": "org.example.batch.samplejob", "BASE_PACKAGE_PATH": "org/example/batch/samplejob",
    "MAIN_CLASS": "SampleJobMain", "SERVICE_INTERFACE": "SampleJobService",
    "SERVICE_FIELD": "sampleJobService", "PROPERTIES_FILE_BASENAME": "SampleJob",
}
assert set(values) == set(a["parameters"])
for key, value in values.items():
    assert re.fullmatch(a["parameters"][key]["pattern"], value), key
assert values["BASE_PACKAGE_PATH"] == values["BASE_PACKAGE"].replace(".", "/")
assert values["SERVICE_FIELD"] == values["SERVICE_INTERFACE"][0].lower() + values["SERVICE_INTERFACE"][1:]


def render(text, vals=values):
    return token.sub(lambda m: vals[m[1]], text)


xml_count = java_count = 0
for name, p in files.items():
    text = p.read_text(encoding="utf-8")
    rn, rt = render(name), render(text)
    assert not token.search(rn + rt) and ".." not in Path(rn).parts
    if p.suffix == ".xml":
        ET.fromstring(text.encode("utf-8")) if name != "pom.xml" else ET.fromstring(text.encode("utf-8"))
        ET.fromstring(rt.encode("utf-8"))
        xml_count += 1
    if p.suffix == ".java":
        assert re.search(r"^package " + re.escape(values["BASE_PACKAGE"]) + r"[.;]", rt, re.M), name
        assert "public class " + Path(rn).stem + " " in rt or "public interface " + Path(rn).stem + " " in rt, name
        assert rt.count("{") == rt.count("}") and rt.count("(") == rt.count(")")
        java_count += 1
    if name.endswith(".j2"):
        assert text.count("{{") == text.count("}}") and "{%" not in text
        for line in text.splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                assert re.fullmatch(r"[A-Za-z0-9.]+=\{\{ [a-z0-9_]+ \}\}", line.strip()), line

# ---------------------------------------------------------------- exact fidelity to the reference
ref_vals = {
    "GROUP_ID": "pe.com.claro.shell", "ARTIFACT_ID": "SH_ObtenerTrasladarArchivosMTC", "PROJECT_VERSION": "1.0.0",
    "BASE_PACKAGE": "pe.com.claro.shell.trasladararchivosmtc", "BASE_PACKAGE_PATH": "pe/com/claro/shell/trasladararchivosmtc",
    "MAIN_CLASS": "ObtenerTrasladarArchivosMTCMain", "SERVICE_INTERFACE": "ObtenerTrasladarArchivosService",
    "SERVICE_FIELD": "obtenerTrasladarArchivosService", "PROPERTIES_FILE_BASENAME": "ObtenerTrasladarArchivosMTC",
}
src_main = reference / "src/main/java/pe/com/claro/shell/trasladararchivosmtc"
identical = {
    ".gitignore": reference / ".gitignore",
    ".editorConfig": reference / ".editorConfig",
    "src/main/java/@@BASE_PACKAGE_PATH@@/@@MAIN_CLASS@@.java": src_main / "ObtenerTrasladarArchivosMTCMain.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/service/@@SERVICE_INTERFACE@@.java": src_main / "service/ObtenerTrasladarArchivosService.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/util/UtilSFTP.java": src_main / "util/UtilSFTP.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/proxy/EbsConsultaClavesWSService.java": src_main / "proxy/EbsConsultaClavesWSService.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/proxy/EbsConsultaClavesWSServiceImpl.java": src_main / "proxy/EbsConsultaClavesWSServiceImpl.java",
    "src/main/resources/applicationProxyWS.xml": reference / "src/main/resources/applicationProxyWS.xml",
    "src/main/resources/applicationContext.xml": reference / "src/main/resources/applicationContext.xml",
}
for exc in ["BaseException", "BaseExceptionSFTP", "SFTPException", "WSException", "PropertiesException"]:
    identical["src/main/java/@@BASE_PACKAGE_PATH@@/exception/%s.java" % exc] = src_main / ("exception/%s.java" % exc)
for name, src in identical.items():
    assert render(rtext(files[name]), ref_vals).rstrip() == rtext(src).rstrip(), "Template differs from reference beyond tokens: " + name

# applicationContext.xml: v1.1.0 restores the proxy import (identical to the reference after token render, checked above)
ctx_ref = rtext(reference / "src/main/resources/applicationContext.xml")
assert '<import resource="applicationProxyWS.xml"/>' in rtext(files["src/main/resources/applicationContext.xml"])

# Mixed files: every declaration line must exist in the reference (only removals allowed)
for name, src in {
    "src/main/java/@@BASE_PACKAGE_PATH@@/util/Constantes.java": src_main / "util/Constantes.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/util/PropertiesExterno.java": src_main / "util/PropertiesExterno.java",
}.items():
    ref_lines = {l.strip() for l in rtext(src).splitlines()}
    for line in render(rtext(files[name]), ref_vals).splitlines():
        s = line.strip()
        if s.startswith(("public ", "@Value", "@Component")):
            assert s in ref_lines, "Not in reference (invented): " + s
# exact removals from the mixed files (v1.1.0 removes ONLY MTC business items and service-specific property keys)
def public_lines(text):
    return {l.strip() for l in text.splitlines() if l.strip().startswith("public ") and "=" in l}


const_ref = rtext(src_main / "util/Constantes.java")
const_tpl = render(rtext(files["src/main/java/@@BASE_PACKAGE_PATH@@/util/Constantes.java"]), ref_vals)
removed_consts = public_lines(const_ref) - public_lines(const_tpl)
assert {re.search(r"String (\w+)", l)[1] for l in removed_consts} == {"REPLACE_FECHA_DDMMYYYY", "REPLACE_FECHA_YYYYMMDD", "MTC_", "ERROR_CONEXION_MTC"}, removed_consts
for name in ["DESENCRIPTAR", "ID_TRANSACCION", "CODIGO_APLICACION", "USUARIO", "CODIGO_RESULTADO", "MENSAJE_RESULTADO", "WS_EXITO", "TRAZA"]:
    assert re.search(r"\b" + name + r"\b", const_tpl), name
prop_ref = rtext(src_main / "util/PropertiesExterno.java")
prop_tpl = render(rtext(files["src/main/java/@@BASE_PACKAGE_PATH@@/util/PropertiesExterno.java"]), ref_vals)
keys_ref = set(re.findall(r'^\s*@Value\("\$\{([^}]+)\}"\)', prop_ref, re.M))
keys_tpl = set(re.findall(r'^\s*@Value\("\$\{([^}]+)\}"\)', prop_tpl, re.M))
assert keys_tpl < keys_ref
assert all(k.startswith(("ftp.", "sftp.mtc.", "ruta.temp.")) for k in keys_ref - keys_tpl), keys_ref - keys_tpl
assert keys_tpl == {"log4j.file.dir"} | {"idf%d.%s" % (i, f) for i in (0, 1) for f in ("codigo", "mensaje")} \
    | {"idt%d.%s" % (i, f) for i in (1, 2, 3) for f in ("codigo", "mensaje")} \
    | {"ws.ebsConsultaClavesWS.url", "ws.ebsConsultaClavesWS.max.request.timeout", "ws.ebsConsultaClavesWS.max.connection.timeout", "ws.ebsConsultaClavesWS.codigo.aplicacion"}, keys_tpl
# external-property contract: j2 keys == PropertiesExterno keys == placeholders used by the proxy XML
j2_text = rtext(files["config/@@PROPERTIES_FILE_BASENAME@@.properties.j2"])
j2_keys = {l.split("=")[0] for l in j2_text.splitlines() if "=" in l and not l.lstrip().startswith("#")}
assert j2_keys == keys_tpl, j2_keys ^ keys_tpl
proxy_xml = rtext(files["src/main/resources/applicationProxyWS.xml"])
assert set(re.findall(r"\$\{([^}]+)\}", proxy_xml)) <= keys_tpl
assert not re.search(r"https?://[^\s\"<]*:[0-9]{2,5}", proxy_xml.replace("http://www.springframework.org", "").replace("http://jax-ws.dev.java.net", ""))
j2_vars = set(re.findall(r"\{\{ ([a-z0-9_]+) \}\}", j2_text))
cfg_vars = {it["template"]: it.get("variables", {}) for it in a["generation"]["configuration"]["items"]}
declared_vars = set(cfg_vars["config/@@PROPERTIES_FILE_BASENAME@@.properties.j2"])
assert {v for v in j2_vars if v.startswith("ws_")} == declared_vars, (j2_vars, declared_vars)
for v, d in cfg_vars["config/@@PROPERTIES_FILE_BASENAME@@.properties.j2"].items():
    assert d["key"] in keys_tpl and d["secret"] is False and d["source"] == "operator-environment"

sftp_t = rtext(files["src/main/java/@@BASE_PACKAGE_PATH@@/util/SFTPConnectionManager.java"])
sftp_r = rtext(src_main / "util/SFTPConnectionManager.java")
sig = re.compile(r"^\s*public [^=;{]+\([^)]*\)", re.M)
ref_sigs = {re.sub(r"\s+", " ", s.strip()) for s in sig.findall(sftp_r)}
tpl_sigs = {re.sub(r"\s+", " ", s.strip()) for s in sig.findall(sftp_t)}
assert tpl_sigs < ref_sigs and len(ref_sigs - tpl_sigs) == 1, (ref_sigs - tpl_sigs)
assert "boolean incluirMargenMedianoche" in (ref_sigs - tpl_sigs).pop()
assert "medianoche" not in sftp_t.lower() and "StrictHostKeyChecking" in sftp_t and "setTimeout(60000)" in sftp_t

# ---------------------------------------------------------------- POM
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
source = ET.fromstring((reference / "pom.xml").read_bytes())
dest = ET.fromstring(render(rtext(files["pom.xml"]), ref_vals).encode("utf-8"))


def canon(e):
    return (e.tag, (e.text or "").strip(), tuple(sorted(e.attrib.items())), tuple(canon(c) for c in e))


def fields(e):
    return {c.tag.split("}")[-1]: (c.text or "").strip() for c in e}


s_props, d_props = fields(source.find("m:properties", ns)), fields(dest.find("m:properties", ns))
assert set(s_props) == set(d_props)
changed = {k for k in s_props if re.sub(r"\s+", "", s_props[k]) != re.sub(r"\s+", "", d_props[k])}
assert changed == {"sonar.coverage.exclusions", "sonar.exclusions"}, changed
for k in changed:  # only removals (concrete redundant patterns) and no new pattern
    s_set = {x.strip() for x in s_props[k].split(",")}
    d_set = {x.strip() for x in d_props[k].split(",")}
    assert d_set < s_set, k
    assert all(x.endswith(("/proxy/*.java", "/exception/*.java", "/util/*.java", "Main.java")) for x in d_set)
for k in changed:
    source.find("m:properties/m:" + k, ns).text = dest.find("m:properties/m:" + k, ns).text
assert canon(source) == canon(dest), "POM changed outside authorized transformations"
deps = [fields(e) for e in dest.findall("m:dependencies/m:dependency", ns)]
assert len(deps) == len(a["build"]["dependencies"]) == a["build"]["dependencyInventorySemantics"]["count"] == 14
for actual, declared in zip(deps, a["build"]["dependencies"]):
    expected = {k: str(v) for k, v in declared.items() if k != "purpose"}
    assert actual == expected, (actual, expected)
plugins = dest.findall("m:build/m:plugins/m:plugin", ns)
assert len(plugins) == len(a["build"]["plugins"]) == 7
for e, d in zip(plugins, a["build"]["plugins"]):
    for key in ["groupId", "artifactId", "version"]:
        assert e.findtext("m:" + key, default=None, namespaces=ns) == d.get(key), (key, d)
    ex = [{"id": z.findtext("m:id", namespaces=ns), "phase": z.findtext("m:phase", namespaces=ns),
           "goals": [g.text for g in z.findall("m:goals/m:goal", ns)]} for z in e.findall("m:executions/m:execution", ns)]
    if ex:
        assert ex == d["executions"], (ex, d["executions"])
assert not any("checkstyle" in d["artifactId"].lower() for d in a["build"]["plugins"])
assert not any("checkstyle" in x.name.lower() for x in reference.rglob("*") if ".idea" not in x.parts)
dep_text = "\n".join(d["artifactId"] for d in a["build"]["dependencies"])
assert "EnvioCorreo" not in rtext(files["pom.xml"]) and "enviocorreo" not in dep_text.lower() and "ojdbc" not in dep_text.lower()
assert a["build"]["profiles"] == [] and a["build"]["pluginRepositories"] == []
assert dest.find("m:profiles", ns) is None and dest.find("m:parent", ns) is None
cs = a["quality"]["checkstyle"]
assert cs["status"] == "not-present-in-reference" and cs["policyRequired"] is False
assert cs["execution"] == a["validation"]["checkstyle"] == "not-applicable"

# ---------------------------------------------------------------- dependency usage vs Java imports (src only)
java_sources = list((reference / "src").rglob("*.java"))
java_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in java_sources)
for prefix in ["org.slf4j", "org.apache.commons", "org.springframework.web"]:
    assert not re.search(r"\bimport\s+" + re.escape(prefix) + r"[.;]", java_text), prefix
for api in ["org.springframework.beans.factory.annotation.Autowired", "org.springframework.context.support.ClassPathXmlApplicationContext",
            "org.apache.log4j.Logger", "org.apache.log4j.PropertyConfigurator", "com.jcraft.jsch.JSch",
            "org.junit.Test", "org.mockito.junit.MockitoJUnitRunner", "org.assertj.core.api.Assertions",
            "org.springframework.core.NestedRuntimeException"]:
    assert api in java_text, api
assert "JaxWsPortProxyFactoryBean" in (reference / "src/main/resources/applicationProxyWS.xml").read_text(encoding="utf-8")
usage_inv = a["build"]["dependencyUsage"]
assert set(usage_inv) == {d["artifactId"] for d in a["build"]["dependencies"]}
evidence = a["evidence"]["entries"]
for item in usage_inv.values():
    assert item["status"] and item["observation"] and set(item["evidence"]).issubset(evidence)
assert not re.search(r"System\.exit", java_text) and a["execution"]["exitCode"]["systemExitCalled"] is False
assert not re.search(r"(?i)enviocorreo|enviarcorreo|javax\.mail", java_text + (reference / "pom.xml").read_text(encoding="utf-8")), "mail usage appeared in the reference"
assert not re.search(r"(?i)enviocorreo", (reference / "src/main/resources/applicationContext.xml").read_text(encoding="utf-8") + proxy_xml)
assert not re.search(r"@RestController|@Controller|@RequestMapping|springframework\.data|@Entity|ch\.qos\.logback", java_text)
assert "ClassPathXmlApplicationContext(Constantes.CONFIG_PATH)" in java_text and 'file:${properties}' in ctx_ref
assert "String idTransaction = args[0];" in java_text
assert not re.search(r"@RestController|@RequestMapping|System\.exit|ch\.qos\.logback|springframework\.data",
                     "\n".join(p.read_text(encoding="utf-8") for n, p in files.items() if n.endswith(".java")))

# ---------------------------------------------------------------- reference inventory coverage
rules = a["referenceInventory"]["rules"]
for r in rules:
    if r["disposition"] == "template":
        assert r["template"] in files, r
        assert (reference / r["path"]).is_file(), r
    else:
        assert r["reason"], r
for rel in paths:
    matched = [r for r in rules if fnmatch.fnmatch(rel, r["path"]) or rel == r["path"]]
    assert len(matched) >= 1, "Reference file without disposition: " + rel
    assert len([m for m in matched if m["disposition"] == "template"]) <= 1
templated = {r["template"] for r in rules if r["disposition"] == "template"}
assert templated == {n for n in files if n != "config/@@PROPERTIES_FILE_BASENAME@@.properties.j2"}, templated ^ set(files)
for e in evidence.values():
    assert (reference / e["path"]).exists(), e["path"]
for item in a["templateInventory"]:
    assert set(item["evidence"]).issubset(evidence)

# ---------------------------------------------------------------- decisions / documents consistency
decisions = (target / "decisions.md").read_text(encoding="utf-8")
conventions = (target / "conventions.md").read_text(encoding="utf-8")
rules_md = (target / "generation-rules.md").read_text(encoding="utf-8")
prov = a["provenance"]
for d in prov["approvedDecisionRefs"] + prov["proposedDecisionRefs"]:
    assert re.search(r"^### " + d + r" ", decisions, re.M), d
resolved = {q["id"] for q in a["resolvedQuestions"]}
assert resolved == set(prov["resolvedQuestionRefs"])
for q in prov["pendingQuestionRefs"] + prov["resolvedQuestionRefs"]:
    assert "**" + q + " " in decisions, q
assert {q["id"] for q in a["unresolvedAmbiguities"]} == set(prov["pendingQuestionRefs"])
assert not resolved & set(prov["pendingQuestionRefs"])
assert resolved | set(prov["pendingQuestionRefs"]) == {f"SH-Q-{n:03d}" for n in range(1, 13)}
if a["readiness"]["baselineDecisionsApproved"]:
    assert a["identity"]["approved"] and not prov["proposedDecisionRefs"]
    assert not prov["pendingQuestionRefs"] and not a["unresolvedAmbiguities"]
assert re.findall(r"SH-D-\d{3}", decisions) and set(re.findall(r"SH-D-\d{3}", decisions)) == set(prov["approvedDecisionRefs"] + prov["proposedDecisionRefs"])
for text in (decisions, conventions, rules_md):
    assert set(re.findall(r"SH-[DQ]-\d{3}", text)) <= set(prov["approvedDecisionRefs"] + prov["proposedDecisionRefs"] + prov["pendingQuestionRefs"] + prov["resolvedQuestionRefs"])
for item in a["templateInventory"]:
    assert set(item["decisionRefs"]) <= set(prov["approvedDecisionRefs"] + prov["proposedDecisionRefs"])
assert "Estado de los pendientes" not in decisions
for q in prov["pendingQuestionRefs"]:
    assert q in conventions or q in rules_md or q in decisions
style = a["generation"]["style"]
assert style["hardcodedLiterals"] in ("allowed", "forbidden") and style["constantsClass"] == "util.Constantes"
assert style["externalPropertiesClass"] == "util.PropertiesExterno"
assert a["generation"]["persistence"]["mechanism"] == "not-present-in-reference"
assert a["generation"]["logging"]["activityLogger"] == "not-applicable"
util_items = a["generation"]["utilities"]["items"]
assert {i["template"] for i in util_items} <= set(files)
assert len(util_items) == 11
cfg_items = a["generation"]["configuration"]["items"]
assert {i["template"] for i in cfg_items} <= set(files)
const_text = rtext(files["src/main/java/@@BASE_PACKAGE_PATH@@/util/Constantes.java"])
for it in util_items:
    for name, val in it["requiredConstants"].items():
        m = re.search(r"\b" + re.escape(name) + r"\s*=\s*(.+?);", const_text)
        assert m, name
        lit = m.group(1).strip()
        lit = lit[1:-1] if lit[0] in "\"'" else lit
        assert lit.replace("\\\\", "\\") == str(val), (name, lit, val)

# ---------------------------------------------------------------- leakage and secrets
leakage = re.compile(r"(?i)trasladararchivosmtc|ObtenerTrasladar|\bMTC\b|MTC_|Suspensi[oó]n|Notificaci[oó]n|Titular|SUSPEN|IDETIT|SFTPDMZ|cobsdb|biometr|ms-individual")
ws_leak = re.compile(r"(?i)EbsConsultaClaves|consultaclaves|desencriptar")
mail_leak = re.compile(r"(?i)EnvioCorreo|enviarcorreo|\bsmtp\b|javax\.mail")
for name, p in files.items():
    text = name + "\n" + p.read_text(encoding="utf-8")
    assert not leakage.search(text), "Domain leakage: " + name
    assert not mail_leak.search(text), "Mail behavior invented: " + name
# v1.1.0 intentionally includes the credential-decrypt module (SH-D-012): it may appear ONLY in these files
expected_ws_files = {
    "pom.xml", "README.MD", "config/@@PROPERTIES_FILE_BASENAME@@.properties.j2",
    "src/main/resources/applicationProxyWS.xml",
    "src/main/java/@@BASE_PACKAGE_PATH@@/proxy/EbsConsultaClavesWSService.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/proxy/EbsConsultaClavesWSServiceImpl.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/util/Constantes.java",
    "src/main/java/@@BASE_PACKAGE_PATH@@/util/PropertiesExterno.java",
}
actual_ws_files = {n for n in files if ws_leak.search(n + "\n" + files[n].read_text(encoding="utf-8"))}
assert actual_ws_files == expected_ws_files, actual_ws_files ^ expected_ws_files
module = next(m for m in a["generation"]["featureModules"] if m["id"] == "credential-decrypt-soap")
assert set(module["templates"]) <= set(files) and set(module["touches"]) <= set(files)
# no jar/WSDL/env endpoint copied; the WSDL decision is recorded
assert not [n for n in files if n.lower().endswith((".jar", ".wsdl", ".class"))]
assert not any("soap:address" in files[n].read_text(encoding="utf-8") for n in files)
wsdl_rule = next(r for r in a["referenceInventory"]["rules"] if r["path"].endswith(".wsdl"))
assert wsdl_rule["disposition"] == "excluded" and "environment" in wsdl_rule["reason"]

# credential-decrypt contract documented in the manifest agrees with the reference WSDL (read-only, field names only)
wsdl = (reference / "pe/com/claro/eai/ebs/operaciones/consultaclaves/ebsConsultaClavesService.wsdl").read_text(encoding="utf-8")
contract = a["generation"]["servicePatterns"]["credentialDecryptContract"]
req_block = re.search(r'name="desencriptarRequest">(.*?)</xsd:element>', wsdl, re.S)[1]
res_block = re.search(r'name="desencriptarResponse">(.*?)</xsd:element>', wsdl, re.S)[1]
assert re.findall(r'element name="(\w+)"', req_block) == contract["requestFields"]
assert re.findall(r'element name="(\w+)"', res_block) == contract["responseFields"]
assert contract["namespace"] in wsdl and contract["serviceName"] in wsdl and contract["portNameSoap11"] in wsdl
assert contract["namespace"] in proxy_xml and contract["serviceName"] in proxy_xml and contract["portNameSoap11"] in proxy_xml
impl_ref = rtext(src_main / "service/ObtenerTrasladarArchivosServiceImpl.java")
for f in contract["requestFieldsSetByReferenceCode"]:
    assert "request.set" + f[0].upper() + f[1:] + "(" in impl_ref, f
for f in contract["requestFieldsNotSetByReferenceCode"]:
    assert "request.set" + f[0].upper() + f[1:] + "(" not in impl_ref, f

# servicePatterns: each documented technical/business method sits in the cited reference line range
impl_lines = impl_ref.split("\n")
expected_token = {
    "SP-DECRYPT-HELPER": "desencriptarCredenciales", "SP-DECRYPT-CALL": "desencriptarCredenciales(",
    "SP-CONN-FACTORY": "crearConexionSFTP", "SP-ERROR-HANDLING": "catch (", "SP-TESTABILITY-DELEGATIONS": "invocarUtilSFTPListar",
    "SP-DATE-FORMAT": "obtenerFechaProcesoFormato", "SP-LOG-FRAME": "INICIO_METODO", "SP-FILE-TYPE-MAP": "tiposArchivos",
    "SP-RESPONSE-RULE": "idf0Codigo",
}
pattern_items = {i["id"]: i for i in a["generation"]["servicePatterns"]["items"]}
assert set(pattern_items) == set(expected_token), set(pattern_items) ^ set(expected_token)
for pid, item in pattern_items.items():
    chunk = ""
    for part in item["lines"].split(" and "):
        lo, hi = [int(x) for x in part.split("-")]
        chunk += "\n".join(impl_lines[lo - 1:hi]) + "\n"
    assert expected_token[pid] in chunk, (pid, item["lines"])
assert {i["classification"] for i in pattern_items.values() if i["classification"].startswith("business")} == {"business-excluded"}
assert {pid for pid, i in pattern_items.items() if i["classification"] == "business-excluded"} == {"SP-FILE-TYPE-MAP", "SP-RESPONSE-RULE"}

# decrypt client jar content (entry listing only, nothing extracted) matches the documented package; mail jar is not declared/used
import zipfile
with zipfile.ZipFile(reference / "Lib/eai/ebsConsultaClavesService-Client/1.0.0/ebsConsultaClavesService-Client-1.0.0.jar") as z:
    entries = set(z.namelist())
for cls in ["DesencriptarRequest", "DesencriptarResponse", "EbsConsultaClavesPortType"]:
    assert "pe/com/claro/eai/ebs/operaciones/consultaclaves/%s.class" % cls in entries, cls

secret_patterns = [
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", r"AKIA[A-Z0-9]{16}",
    r"(?i)https?://[^/\s<>]+:[^/\s<>]+@",
    r"(?i)(?:password|passwd|secret|token)\s*[:=]\s*['\"][^@\s][^'\"\n]{3,}['\"]",
    r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9.]+\b",
    r"\b[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b",
]
for p in target.rglob("*"):
    if p.is_file() and p != Path(__file__).resolve():
        text = p.read_text(encoding="utf-8")
        assert not any(re.search(pat, text) for pat in secret_patterns), "Potential secret/IP: " + p.relative_to(target).as_posix()
        assert not (p.name.lower().startswith("application") and p.suffix.lower() == ".properties")

print(json.dumps({
    "yaml": "passed-unique-keys", "templates": len(files), "parametersUsedExactly": len(usage),
    "xmlWellFormedOriginalAndRendered": xml_count, "javaStructuralRenderOnly": java_count,
    "javaSyntaxCompilation": "not-run", "templatesIdenticalToReferenceAfterTokenRender": len(identical) + 1,
    "mixedTemplatesOnlyRemovalsVsReference": 3, "credentialDecryptContractMatchesReferenceWsdl": True,
    "servicePatternsVerifiedAgainstReferenceLines": len(pattern_items), "externalPropertyKeysConsistentJ2PropertiesXml": len(keys_tpl),
    "v1_0_0_untouched_frozen": True, "pomAuthorizedTransformsOnly": True,
    "dependencies": len(deps), "plugins": len(plugins), "dependencyUsageEntries": len(usage_inv),
    "referenceFiles": len(paths), "referenceFilesWithDisposition": len(paths),
    "permittedReferenceRecordsUnchanged": len(records), "protectedFilesNotHashed": len(paths) - len(records),
    "approvedDecisions": len(prov["approvedDecisionRefs"]), "proposedDecisions": len(prov["proposedDecisionRefs"]),
    "pendingQuestions": len(prov["pendingQuestionRefs"]),
    "templateDomainLeakageMatches": 0, "templateMailBehaviorMatches": 0,
    "credentialDecryptFilesExactlyExpected": len(actual_ws_files), "archetypeSecretOrIpHeuristicMatches": 0,
    "maven": "not-run", "tests": "not-run", "checkstyle": "not-applicable; not-present-in-reference",
    "jacocoSonar": "not-run", "springJava8Compatibility": "unverified",
    "extractionComplete": a["readiness"]["extractionComplete"],
    "baselineDecisionsApproved": a["readiness"]["baselineDecisionsApproved"],
    "frozen": a["identity"]["frozen"],
    "generationEnabled": a["identity"]["generationEnabled"],
    "generatorBackend": a["readiness"]["generatorBackend"], "readyToFreeze": a["identity"]["readyToFreeze"],
}, ensure_ascii=False, indent=2))
