"""Preventive style lint for generated Java (heuristic, fast, no Maven).

It looks for the patterns that the reference checkstyle.xml is known to flag in generated code: annotation-array indentation, magic numbers,
whitespace around keywords/operators, local-variable declaration/use distance, line length, star/unused imports and missing braces.

THIS IS NOT CHECKSTYLE. It never reports the official gate as passed: the result always states `checkstyleOfficial: not-verified` and the
mandatory D-014 gate (maven-checkstyle-plugin, main and test sources, 0 violations) still decides. It only helps reach zero before running it.
It reads the ignore list of MagicNumber from the project's own checkstyle.xml when available; it never edits or relaxes any rule.
"""
from pathlib import Path
import argparse
import re
import sys
import xml.etree.ElementTree as ET
import yaml

DEFAULT_IGNORED_NUMBERS = {-1, 0, 1, 2, 4, 200, 201, 400, 401, 403, 404, 418, 500, 1000}
LINE_LENGTH = 250
ALLOWED_DISTANCE = 3
EXCLUDED = re.compile(r'(^|/)src/main/resources/application[^/]*\.properties$')
NUMBER = re.compile(r'(?<![\w.$])-?\d+(?:\.\d+)?(?:[lLfFdD])?(?![\w.])')
DECLARATION = re.compile(r'^\s*(?!return\b|throw\b|new\b|else\b)(?:final\s+)?([A-Z][\w<>\[\],.? ]*|int|long|double|boolean|char|byte|short|float|var)\s+([a-z_]\w*)\s*=\s*[^=].*$')
KEYWORD_PAREN = re.compile(r'(?<![\w.])(if|for|while|switch|catch|synchronized)\(')
OPERATOR_NO_SPACE = re.compile(r'[A-Za-z0-9_\])]\s*(?:==|!=|<=|>=|&&|\|\||->)\S|\S(?:==|!=|<=|>=|&&|\|\||->)\s*[A-Za-z0-9_("\[]')


def ignored_numbers(checkstyle: Path | None) -> set:
    if checkstyle and Path(checkstyle).is_file():
        for module in ET.parse(checkstyle).getroot().iter('module'):
            if module.get('name') == 'MagicNumber':
                for prop in module.findall('property'):
                    if prop.get('name') == 'ignoreNumbers':
                        return {float(v.strip()) for v in prop.get('value', '').split(',') if v.strip()}
    return set(DEFAULT_IGNORED_NUMBERS)


def strip_code(lines: list[str]) -> list[str]:
    """Same lines with comments and string/char literal contents blanked, so patterns only see code."""
    out, in_block = [], False
    for line in lines:
        text, i, result = line, 0, []
        while i < len(text):
            if in_block:
                end = text.find('*/', i)
                if end < 0:
                    i = len(text)
                else:
                    in_block, i = False, end + 2
                continue
            two = text[i:i + 2]
            if two == '/*':
                in_block, i = True, i + 2
            elif two == '//':
                break
            elif text[i] in '"\'':
                quote = text[i]
                result.append(quote)
                i += 1
                while i < len(text) and text[i] != quote:
                    i += 2 if text[i] == '\\' else 1
                result.append(quote)
                i += 1
            else:
                result.append(text[i])
                i += 1
        out.append(''.join(result))
    return out


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


def lint_text(path: str, text: str, ignore: set | None = None) -> list[dict]:
    ignore = ignore if ignore is not None else set(DEFAULT_IGNORED_NUMBERS)
    raw = text.replace('\r\n', '\n').split('\n')
    code = strip_code(raw)
    found = []

    def add(rule, number, message):
        found.append({'file': path, 'line': number, 'rule': rule, 'message': message})

    for n, line in enumerate(raw, 1):
        if len(line) > LINE_LENGTH and not re.match(r'\s*(package|import)\b', line) and not re.search(r'https?://|ftp://|href', line):
            add('LineLength', n, f'line has {len(line)} characters (max {LINE_LENGTH})')
    # imports
    body = '\n'.join(code)
    for n, line in enumerate(raw, 1):
        m = re.match(r'\s*import\s+(?:static\s+)?([\w.]+)(\.\*)?\s*;', line)
        if m:
            if m.group(2):
                add('AvoidStarImport', n, 'star import')
            else:
                simple = m.group(1).rsplit('.', 1)[-1]
                own = re.match(r'\s*package\s+([\w.]+)\s*;', next((r for r in raw if r.strip().startswith('package ')), ''))
                if own and not re.match(r'\s*import\s+static\b', line) and m.group(1).rsplit('.', 1)[0] == own.group(1) and simple[:1].isupper():
                    add('RedundantImport', n, f'redundant import from the same package - {m.group(1)}')
                rest = '\n'.join(c for k, c in enumerate(code, 1) if k != n and not re.match(r'\s*import\b', c))
                if not re.search(rf'\b{re.escape(simple)}\b', rest):
                    add('UnusedImports', n, f'unused import {simple}')
    # first statement of a method/constructor body: one level (4) deeper than the declaration (Indentation 'method def' child)
    declaration = re.compile(r'^(\s+)(?:(?:public|protected|private|static|final|abstract|synchronized|default)\s+)*(?:<[^>]+>\s+)?(?:[\w<>\[\],.? ]+\s+)?[A-Za-z_]\w*\([^;{}]*\)\s*(?:throws [\w., ]+)?\{\s*$')
    for n, line in enumerate(code, 1):
        m = declaration.match(line)
        if m and not re.match(r'\s*(if|for|while|switch|catch|try|else|synchronized|do)\b', line):
            following = next(((k, c) for k, c in enumerate(code[n:], n + 1) if c.strip()), None)
            if following and not following[1].strip().startswith('}') and indent_of(following[1]) != len(m.group(1)) + 4:
                add('Indentation', following[0], f"'method def' child has incorrect indentation level {indent_of(following[1])}, expected level should be {len(m.group(1)) + 4}")
    # annotation array initializers: children at annotation indent + 2 (arrayInitIndent) or + 8 (line wrap)
    depth_start = None
    for n, line in enumerate(code, 1):
        stripped = line.strip()
        if depth_start is None and re.match(r'@\w+\((?:\s*\w+\s*=)?\s*\{\s*$', stripped):
            depth_start = indent_of(line)
            continue
        if depth_start is not None:
            if re.match(r'\}\s*\)', stripped):
                depth_start = None
            elif stripped and indent_of(line) not in (depth_start + 2, depth_start + 8) and not stripped.startswith('//'):
                add('Indentation', n, f'annotation array child at {indent_of(line)}, expected {depth_start + 2} or {depth_start + 8}')
    # magic numbers (constants and string/comment content are ignored)
    for n, line in enumerate(code, 1):
        if re.search(r'\bstatic\s+final\b', line) or re.match(r'\s*(import|package)\b', line):
            continue
        for m in NUMBER.finditer(line):
            token = m.group(0).rstrip('lLfFdD')
            try:
                value = float(token)
            except ValueError:
                continue
            if value not in ignore:
                add('MagicNumber', n, f'{m.group(0)!r} is a magic number')
    # whitespace around keywords, braces, operators
    for n, line in enumerate(code, 1):
        if KEYWORD_PAREN.search(line):
            add('WhitespaceAround', n, 'keyword is not followed by whitespace')
        if re.search(r'\(\s*switch\b', line) and re.search(r'\(switch\b', line):
            add('WhitespaceAround', n, "'switch' is not preceded with whitespace")
        if re.search(r'\)\{|\}(?:else|catch|finally)\b|\b(?:else|try|finally)\{', line):
            add('WhitespaceAround', n, 'brace or keyword without surrounding whitespace')
        for m in re.finditer(r'(?<![=!<>+\-*/%&|^])=(?!=)', line):
            before = line[m.start() - 1] if m.start() else ' '
            after = line[m.end()] if m.end() < len(line) else ' '
            if not before.isspace() or not after.isspace():
                add('WhitespaceAround', n, "'=' is not surrounded by whitespace")
                break
        if OPERATOR_NO_SPACE.search(line) and not re.match(r'\s*(import|package)\b', line):
            add('WhitespaceAround', n, 'operator without surrounding whitespace')
        if re.search(r'^\s*(?:if|for|while)\s*\(.*\)\s*[^{\s].*;\s*$', line) and not line.rstrip().endswith('{'):
            add('NeedBraces', n, 'statement without braces')
    # local variable declaration / first use distance (non-final locals)
    add_distance_findings(code, add)
    return sorted(found, key=lambda f: (f['line'], f['rule']))


def add_distance_findings(code: list[str], add):
    depth_before, depth = [], 0
    for line in code:
        depth_before.append(depth)
        depth += line.count('{') - line.count('}')
    for index, line in enumerate(code):
        m = DECLARATION.match(line)
        if not m or re.match(r'\s*final\b', line) or depth_before[index] == 0 or not line.rstrip().endswith(';'):
            continue
        name, level = m.group(2), depth_before[index]
        statements, j = 0, index + 1
        while j < len(code) and depth_before[j] >= level:
            statement_lines = [code[j]]
            k = j
            while not re.search(r'[;{]\s*$', code[k]) and k + 1 < len(code) and depth_before[k + 1] >= level:
                k += 1
                statement_lines.append(code[k])
            if depth_before[j] == level and code[j].strip().startswith('}') and not re.search(r'\w', code[j]):
                break
            block_end = k
            if code[k].rstrip().endswith('{'):
                depth_target = depth_before[k] + 1
                while block_end + 1 < len(code) and depth_before[block_end + 1] >= depth_target:
                    block_end += 1
                    statement_lines.append(code[block_end])
            header_lines = statement_lines[:k - j + 1]
            if not any(re.search(rf'\b{re.escape(name)}\b', h) for h in header_lines) and any(re.search(rf'\b{re.escape(name)}\b', b) for b in statement_lines[k - j + 1:]):
                break                    # first use inside a nested block: not measured (validateBetweenScopes is off in Checkstyle)
            if any(re.search(rf'\b{re.escape(name)}\b', s) for s in statement_lines):
                if statements > ALLOWED_DISTANCE:
                    add('VariableDeclarationUsageDistance', index + 1, f"distance between variable '{name}' declaration and its first usage is {statements}, but allowed {ALLOWED_DISTANCE}")
                break
            statements += 1
            j = block_end + 1


def lint_project(output: Path, checkstyle: Path | None = None) -> dict:
    output = Path(output)
    ignore = ignored_numbers(checkstyle or (output / 'src/main/resources/checkstyle.xml'))
    findings, files = [], 0
    for source_set in ('src/main/java', 'src/test/java'):
        for path in sorted((output / source_set).rglob('*.java')) if (output / source_set).is_dir() else []:
            rel = path.relative_to(output).as_posix()
            if EXCLUDED.search(rel):
                continue
            files += 1
            findings += lint_text(rel, path.read_text(encoding='utf-8'), ignore)
    by_rule = {}
    for f in findings:
        by_rule[f['rule']] = by_rule.get(f['rule'], 0) + 1
    return {'kind': 'preventive-style-lint', 'filesChecked': files, 'sourceSets': ['src/main/java', 'src/test/java'], 'findings': findings, 'byRule': dict(sorted(by_rule.items())),
            'checkstyleOfficial': 'not-verified', 'note': 'Heuristic pre-check only. The official gate is maven-checkstyle-plugin (D-014): 0 violations on main and test sources.',
            'preventiveResult': 'clean' if not findings else 'findings'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--checkstyle', type=Path)
    args = parser.parse_args(argv)
    result = lint_project(args.output, args.checkstyle)
    print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))
    return 0 if not result['findings'] else 1


if __name__ == '__main__':
    sys.exit(main())
