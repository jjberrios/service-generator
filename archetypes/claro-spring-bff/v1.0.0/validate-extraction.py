"""Static profile validator for claro-spring-bff/1.0.0. Read-only; never reads application*.properties."""
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
REF = ROOT / 'input/reference/bff-customerbillconfiguration-Feature-300864@ccdb2c4c953'
T = HERE / 'template'
RENDER = {
    '@@BASE_PACKAGE_PATH@@': 'com/claro/factelectronica/bffcustomerbillconfiguration/support',
    '@@BASE_PACKAGE@@': 'com.claro.factelectronica.bffcustomerbillconfiguration.support',
    '@@APPLICATION_CLASS@@': 'BffCustomerBillConfigurationApplication',
    '@@ARTIFACT_ID@@': 'bff-customerBillConfiguration',
    '@@GROUP_ID@@': 'com.claro.factelectronica',
    '@@PROJECT_VERSION@@': '0.0.1-SNAPSHOT',
}
LEAK = re.compile(r'ManualSeries|manual\.series|soap\.audit|CustomerBill|factelectronica|bffdocument|ACT\d_', re.I)
SECRET = re.compile(r'''(password|secret(-key)?)\s*[=:]\s*["']?[A-Za-z0-9]{6,}''', re.I)


def render(text):
    for key, value in RENDER.items():
        text = text.replace(key, value)
    return text


def main():
    issues, notes = [], []
    shared = subprocess.run([sys.executable, str(ROOT / '.opencode/skills/extract-archetype/scripts/validate_inventory.py'), str(HERE)],
                            capture_output=True, text=True)
    if shared.returncode != 0:
        issues.append('shared validator failed')
    # reference unchanged
    recs = []
    for p in sorted(REF.rglob('*')):
        if p.is_file() and not (p.name.lower().startswith('application') and p.name.lower().endswith('.properties')):
            recs.append([p.relative_to(REF).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()])
    base = (HERE / 'reference-content-baseline.yml').read_text(encoding='utf-8')
    if hashlib.sha256(json.dumps(recs, separators=(',', ':')).encode()).hexdigest() not in base:
        issues.append('reference content changed since extraction')
    # POM fidelity
    pom = render((T / 'pom.xml').read_text(encoding='utf-8'))
    if pom != (REF / 'pom.xml').read_text(encoding='utf-8'):
        issues.append('pom.xml differs from reference after rendering')
    # byte-identical static files and verbatim classes
    for name in ['.gitattributes', '.gitignore', 'mvnw', 'mvnw.cmd', '.mvn/wrapper/maven-wrapper.properties', 'README.md', 'settings.xml',
                 'src/main/resources/checkstyle.xml', 'src/main/resources/logback.xml', 'config/ExternalSecret.yml.j2']:
        if (T / name).read_bytes() != (REF / name).read_bytes():
            issues.append('static file differs from reference: ' + name)
    src = 'src/main/java/com/claro/factelectronica/bffcustomerbillconfiguration/support/'
    for name in ['configuration/WsResponseProperties.java', 'configuration/security/SecurityConfig.java', 'dto/response/ApiResponseData.java',
                 'dto/response/ErrorResponse.java', 'dto/response/ResponseAudit.java', 'exception/BusinessException.java',
                 'exception/GlobalExceptionHandler.java', 'security/filter/JwtRequestFilter.java', 'security/service/JwtValidatorService.java',
                 'security/service/impl/JwtValidatorServiceImpl.java', 'utils/ActivityLogger.java']:
        tpl = T / 'src/main/java/@@BASE_PACKAGE_PATH@@' / name
        if render(tpl.read_text(encoding='utf-8')) != (REF / src / name).read_text(encoding='utf-8'):
            issues.append('verbatim class differs from reference: ' + name)
    # leakage / secrets / protected files
    for p in T.rglob('*'):
        if not p.is_file():
            continue
        rel = p.relative_to(T).as_posix()
        if p.name.lower().startswith('application') and p.name.lower().endswith('.properties'):
            issues.append('protected file in template: ' + rel)
        text = p.read_text(encoding='utf-8')
        if LEAK.search(text) or LEAK.search(rel):
            issues.append('reference/domain leakage: ' + rel)
        if p.name not in ('mvnw', 'mvnw.cmd') and SECRET.search(text):
            issues.append('possible secret: ' + rel)
    # reference files not templated (for reviewer, must match exclusions)
    templated = {p.relative_to(T).as_posix().replace('@@BASE_PACKAGE_PATH@@', 'com/claro/factelectronica/bffcustomerbillconfiguration/support')
                 .replace('@@APPLICATION_CLASS@@', 'BffCustomerBillConfigurationApplication') for p in T.rglob('*') if p.is_file()}
    for r, _ in recs:
        if r not in templated:
            notes.append('excluded: ' + r)
    result = {'status': 'failed' if issues else 'passed', 'issues': issues, 'excludedReferenceFiles': len(notes), 'excluded': notes,
              'scope': 'static-only', 'maven': 'not-run', 'checkstyle': 'unverified', 'runtime': 'not-verified'}
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if issues else 0)


if __name__ == '__main__':
    main()
