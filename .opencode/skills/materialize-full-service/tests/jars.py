"""Local-jar classpaths for the optional javac/JUnit-launcher checks (no Maven is run; versions follow the Boot 3.4.x line)."""
import re
from pathlib import Path

M2 = Path.home() / '.m2' / 'repository'
PINS = {('org.springframework', None): '6.2.1', ('org.springframework.data', None): '3.4.1', ('org.hibernate.orm', 'hibernate-core'): '6.6.4.Final', ('org.hibernate.validator', 'hibernate-validator'): '8.0.2.Final',
        ('org.junit.jupiter', None): '5.11.4', ('org.junit.platform', None): '1.11.4', ('org.mockito', None): '5.14.2', ('org.apache.tomcat.embed', None): '10.1.34', ('com.jayway.jsonpath', None): '2.9.0',
        ('ch.qos.logback', None): '1.5.18', ('org.hamcrest', 'hamcrest'): '2.2', ('org.opentest4j', 'opentest4j'): '1.3.0', ('org.objenesis', 'objenesis'): '3.3'}
GROUPS = ('org.springframework', 'jakarta', 'com.fasterxml', 'org.hibernate', 'io.swagger', 'org.projectlombok', 'org.slf4j', 'org.apache.tomcat', 'ch.qos', 'io.micrometer', 'org.aspectj', 'org.junit',
          'org.mockito', 'net.bytebuddy', 'org.objenesis', 'com.jayway', 'net.minidev', 'org.hamcrest', 'org.opentest4j', 'org.apiguardian', 'org.jboss.logging', 'com.zaxxer', 'com.h2database', 'org.antlr', 'net.bytebuddy')


def version_key(version):
    return [int(x) if x.isdigit() else 0 for x in re.split(r'[.\-]', version)]


def collect(runtime=False):
    best = {}
    for jar in M2.rglob('*.jar'):
        art, ver = jar.parent.parent.name, jar.parent.name
        group = str(jar.parent.parent.parent.relative_to(M2)).replace('\\', '.').replace('/', '.')
        if jar.name != f'{art}-{ver}.jar' or not group.startswith(GROUPS):
            continue
        if runtime:
            pin = PINS.get((group, art)) or PINS.get((group, None))
            if pin and not ver.startswith(pin):
                continue
            if not pin and group.startswith(('org.springframework', 'org.junit', 'org.mockito', 'jakarta.validation')) and ver.split('.')[0] in ('7', '6') and group.startswith('org.springframework') and not ver.startswith('6.2'):
                continue
            if group.startswith('com.fasterxml.jackson') and (not ver.startswith('2.18') or 'dataformat' in art):
                continue
            if group.startswith('org.springframework.boot'):
                continue
        if (group, art) not in best or version_key(ver) > version_key(best[(group, art)][0]):
            best[(group, art)] = (ver, str(jar))
    return sorted(j for _, j in best.values())
