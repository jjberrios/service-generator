"""Automatic derivation of the fragments to capture from the structured data of a finding (no manual capture specs).

Swagger: the evidence pointer (a JSON Pointer into the normalized contract) is resolved against the ORIGINAL OpenAPI file, following local
`$ref` references as needed to locate the node, and expressed as YAML nodes whose verbatim lines will be rendered.
Sparx: the evidence element/activity/section/row id and the finding texts are matched against a model of the ORIGINAL Sparx page
(rows and text blocks) to choose the table rows and text spans that justify the finding.

Everything here is pure (no browser, no files) so it can be tested with synthetic inputs. Nothing is invented: a fragment is produced only
when the original source contains it; otherwise a reason is returned and the finding stays text-only.
"""
from collections import Counter
import re
import unicodedata
import yaml

import visual_evidence as ve

MAX_LINES = 40
STOPWORDS = set('''para como pero sino este esta estos estas esas esos entre desde hasta sobre cuando donde tiene tienen puede pueden segun solo
solamente tambien cada todos todas otra otro otros otras mismo misma ellos ellas debe deben haya sean sido ser estar hacia contra durante
sparx swagger declara declaran documenta documentan define definen respuesta respuestas campo campos tipo valor valores elemento elementos
operacion servicio fuente fuentes diferencia diferencias existe existen incluye incluyen muestra indica indican'''.split())
SECTION_LABELS = {'headerrequest': 'HeaderRequest', 'header': 'HeaderRequest', 'query': 'Query', 'path': 'Path', 'body': 'Body', 'input': 'INPUT', 'output': 'OUTPUT'}
HEADER_SECOND_CELLS = {'schemaobject', 'anonschemaobject'}


def fold(text) -> str:
    text = unicodedata.normalize('NFD', str(text or '').lower())
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def words(text) -> list[str]:
    return re.findall(r'[a-z0-9_]+', fold(text))


def stem(word: str) -> str:
    return word[:6]


def distinctive_stems(text) -> set[str]:
    return {stem(w) for w in words(text) if len(w) >= 5 and w not in STOPWORDS}


def identifiers(text) -> list[str]:
    """Identifier-like tokens (field names such as code, subtype, x-user-id, data.items[].age) in order of appearance."""
    seen, out = set(), []
    for token in re.findall(r'[A-Za-z_][A-Za-z0-9_\-.\[\]]*', text or ''):
        token = token.strip('.-')
        if len(token) >= 3 and token not in seen:
            seen.add(token)
            out.append(token)
    return out


# ---------------------------------------------------------------------------------------------------------------- Swagger
def pointer_tokens(pointer: str) -> list[str]:
    return [t.replace('~1', '/').replace('~0', '~') for t in pointer.lstrip('#').strip('/').split('/') if t != '']


class Swagger:
    def __init__(self, source_text: str, normalized: dict):
        self.root = yaml.compose(source_text, Loader=yaml.SafeLoader)
        self.text = source_text
        self.normalized = normalized

    def get(self, path):
        node = self.root
        for part in path:
            found = ve.child(node, part)
            if not found:
                return None
            node = found[1]
        return node

    def deref(self, path):
        """Follow local $ref references until a concrete node is reached; returns (path, node)."""
        path = list(path)
        for _ in range(12):
            node = self.get(path)
            ref = ve.child(node, '$ref') if isinstance(node, yaml.MappingNode) else None
            if ref and isinstance(ref[1], yaml.ScalarNode) and ref[1].value.startswith('#/'):
                path = [t.replace('~1', '/').replace('~0', '~') for t in ref[1].value[2:].split('/')]
                continue
            return path, node
        return path, None

    def scalar(self, node, key):
        found = ve.child(node, key) if node is not None else None
        return found[1].value if found and isinstance(found[1], yaml.ScalarNode) else None

    def find_parameter(self, base, name, location):
        candidates = [(base + ['parameters'], self.get(base + ['parameters'])), (base[:2] + ['parameters'], self.get(base[:2] + ['parameters']))]
        for list_path, sequence in candidates:
            if not isinstance(sequence, yaml.SequenceNode):
                continue
            for index in range(len(sequence.value)):
                path, node = self.deref(list_path + [index])
                if node is not None and self.scalar(node, 'name') == name and self.scalar(node, 'in') == location:
                    return path
        return None

    def walk(self, path, tokens):
        for token in tokens:
            path, node = self.deref(path)
            if ve.child(node, token) is None:
                return None, token
            path = path + [token]
        path, _ = self.deref(path)
        return path, None

    def shallow(self, path):
        """Key line plus the direct children (scalar children with their value, nested ones as bare key lines)."""
        node = self.get(path)
        nodes = [{'path': path, 'keyOnly': True}]
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                nodes.append({'path': path + [key_node.value], 'keyOnly': not isinstance(value_node, yaml.ScalarNode)})
        return {'nodes': nodes, 'relative': True}

    def derive(self, pointer: str) -> dict:
        tokens = pointer_tokens(pointer)
        if len(tokens) < 2 or tokens[0] != 'operations' or not tokens[1].isdigit():
            return {'reason': 'the evidence pointer does not reference an operation of the contract'}
        operations = self.normalized.get('operations') or []
        index = int(tokens[1])
        if index >= len(operations):
            return {'reason': 'the evidence pointer references an unknown operation'}
        operation = operations[index]
        method, route = operation['method'].lower(), operation['path']
        base = ['paths', route, method]
        if self.get(base) is None:
            return {'reason': 'the operation was not found in the original contract'}
        rest = tokens[2:]
        spec = None
        if not rest or rest == ['path']:
            spec = {'nodes': [{'path': ['paths', route], 'keyOnly': True}, {'path': base, 'keyOnly': True}], 'relative': True}
        elif rest[0] == 'parameters' and len(rest) >= 2:
            location = rest[1]
            listed = (operation.get('parameters') or {}).get(location) or []
            if len(rest) == 2:
                paths = [self.find_parameter(base, p['name'], location) for p in listed]
            else:
                position = int(rest[2]) if rest[2].isdigit() else -1
                paths = [self.find_parameter(base, listed[position]['name'], location)] if 0 <= position < len(listed) else []
            if not paths or any(p is None for p in paths):
                return {'reason': 'the parameter was not found in the original contract'}
            # A parameter reached through $ref is shown by its own definition, without the name of the shared component.
            spec = {'nodes': [{'path': p, 'valueOnly': True} if p[0] == 'components' else {'path': p} for p in paths]}
        elif rest == ['responses']:
            responses = base + ['responses']
            node = self.get(responses)
            if not isinstance(node, yaml.MappingNode):
                return {'reason': 'the operation declares no responses in the original contract'}
            spec = {'nodes': [{'path': responses, 'keyOnly': True}] + [{'path': responses + [k.value], 'keyOnly': True} for k, _ in node.value], 'relative': True}
        else:
            path, missing = self.walk(base, rest)
            if path is None:
                return {'reason': f'element "{missing}" was not found in the original contract'}
            spec = {'nodes': [{'path': path}]}
        lines = ve.yaml_fragments(self.text, spec['nodes'], MAX_LINES, bool(spec.get('relative')))
        if lines is None and len(spec['nodes']) == 1:
            spec = self.shallow(spec['nodes'][0]['path'])
            lines = ve.yaml_fragments(self.text, spec['nodes'], MAX_LINES, True)
        if not lines:
            return {'reason': 'the fragment is too large to be shown legibly'}
        return {**spec, 'maxLines': MAX_LINES}


# ------------------------------------------------------------------------------------------------------------------ Sparx
def row_values_for(document, evidence_id):
    """Cell values of the Sparx table row identified by an evidenceId in the endpoint detail, or None."""
    stack = [document]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get('evidenceId') == evidence_id and ('values' in node or len(node) > 1):
                values = node.get('values') or {k: v for k, v in node.items() if k != 'evidenceId'}
                values = [str(v).strip() for v in values.values() if isinstance(v, (str, int, float)) and str(v).strip()]
                return values or None
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def row_key(row) -> str:
    return next((c for c in row['cells'] if c.strip()), '')


def norm_cell(text) -> str:
    return ' '.join(fold(text).split())


def match_row(rows, values):
    wanted = [norm_cell(v) for v in values]
    for row in rows:
        cells = {norm_cell(c) for c in row['cells']}
        if all(w in cells for w in wanted):
            return row['i']
    return None


def table_rows(rows, index):
    first = rows[index]['first']
    return [r for r in rows if r['first'] == first]


def scopes_for(rows, mentions):
    """Named sections (a header row such as ResponseAuditType followed by its fields) mentioned in the finding: (header, end, name)."""
    found = []
    for mention in mentions:
        for position, row in enumerate(rows):
            second = norm_cell(row['cells'][1]) if len(row['cells']) > 1 else ''
            if row_key(row) == mention and second in HEADER_SECOND_CELLS:
                end = len(rows)
                for later in range(position + 1, len(rows)):
                    nxt = rows[later]
                    if len(nxt['cells']) > 1 and norm_cell(nxt['cells'][1]) in HEADER_SECOND_CELLS and nxt['first'] == row['first']:
                        end = later
                        break
                found.append((position, end, mention))
    return found


def densest_window(block_words, positions, margin=1):
    if not positions:
        return None
    clusters, current = [], [positions[0]]
    for position in positions[1:]:
        if position - current[-1] <= 6:
            current.append(position)
        else:
            clusters.append(current)
            current = [position]
    clusters.append(current)
    best = max(clusters, key=len)
    return max(0, best[0] - margin), min(len(block_words) - 1, best[-1] + margin)


def phrase_span(text, first_word, last_word):
    """Original substring covering words [first_word..last_word] (indexes over text.split())."""
    tokens = list(re.finditer(r'\S+', text))
    return tokens[first_word].start(), tokens[last_word].end()


def plan_prose(model, wanted_stems, used_rows=()):
    """Text spans/blocks of the page that carry the finding's distinctive vocabulary."""
    scored = []
    for block in model['blocks']:
        block_words = block['text'].split()
        block_stems = {stem(w) for w in words(block['text']) if len(w) >= 5 and w not in STOPWORDS}
        hits = wanted_stems & block_stems
        if len(hits) >= 3:
            scored.append((len(hits), -len(block_words), block, hits))
    if not scored:
        return []
    top = max(item[0] for item in scored)
    # Prefer the most specific (shortest) block among those that carry nearly all of the best hit count.
    best = max((item for item in scored if item[0] >= max(3, int(0.8 * top))), key=lambda item: item[1])
    block, hits = best[2], best[3]
    lines = block.get('lines') or [block['text']]
    line_hits = [len(wanted_stems & {stem(w) for w in words(l) if len(w) >= 5 and w not in STOPWORDS}) for l in lines]
    centre = max(range(len(lines)), key=lambda k: line_hits[k])
    first = last = centre
    while first > 0 and line_hits[first - 1] >= 2:
        first -= 1
    while last < len(lines) - 1 and line_hits[last + 1] >= 2:
        last += 1
    chosen_lines = lines[first:last + 1]
    anchors = sorted(hits)
    if len(lines) == 1 and len(lines[0].split()) <= 60:
        return [{'text': ' '.join(lines[0].split()[:4]), 'kind': 'block', 'anchors': anchors}]
    head, tail = chosen_lines[0], chosen_lines[-1]
    s0, e0 = phrase_span(head, 0, min(2, len(head.split()) - 1))
    s1, e1 = phrase_span(tail, max(len(tail.split()) - 3, 0), len(tail.split()) - 1)
    return [{'text': head[s0:e0], 'to': tail[s1:e1], 'kind': 'span', 'anchors': anchors}]


def plan_sparx(finding: dict, evidence: dict, model: dict, row_values=None, service: str = '') -> dict:
    """Regions to capture from the original Sparx page of one evidence item, with a score (number of anchors found)."""
    element = evidence.get('element') or ''
    page_text = model.get('text', '')
    if element.startswith('Relación'):
        return {'reason': 'context-only relation (belongs to another element)', 'score': 0}
    if element.startswith('«Método»'):
        name = element.split('»', 1)[1].strip()
        if name not in page_text:
            return {'reason': 'the method name is not on the original page', 'score': 0}
        regions = [{'text': f'{service} / {name}', 'kind': 'text'}] if f'{service} / {name}' in page_text.replace('\n', ' ') else []
        regions.append({'text': f'{name} : Public', 'to': 'Actividad', 'kind': 'span'})
        return {'regions': regions, 'anchors': [name], 'score': 1}
    if element.startswith('Evento de fin'):
        code = element.split()[-1]
        if f'{code} : Public' not in page_text.replace('\n', ' '):
            return {'reason': 'the end event is not on the original page', 'score': 0}
        return {'regions': [{'text': f'{code} : Public', 'to': 'EndEvent', 'kind': 'span'}], 'anchors': [code], 'score': 1}
    rows = model['rows']
    chosen, anchors = [], []

    def add(index):
        if index is not None and index not in chosen:
            chosen.append(index)

    if row_values:
        index = match_row(rows, row_values)
        if index is not None:
            add(index)
            anchors.append('row')
    section = fold(evidence.get('section') or '')
    if section and not chosen:
        label = SECTION_LABELS.get(section, evidence.get('section'))
        header = next((r for r in rows if norm_cell(row_key(r)) == norm_cell(label)), None)
        if header:
            for r in table_rows(rows, header['i'])[:16]:
                add(r['i'])
            anchors.append(label)
    own_text = ' '.join([finding.get('sparx', {}).get('text', ''), finding.get('element', '')])
    mentions = identifiers(own_text)
    scope = None
    if not chosen:
        element_tokens = identifiers(finding.get('element', ''))
        scopes = scopes_for(rows, mentions)
        # A section is used only if it actually contains rows for the finding's field names.
        for candidate in scopes:
            if any(row_key(r) in element_tokens for r in rows[candidate[0] + 1:candidate[1]]):
                scope = candidate
                break
        for token in element_tokens:
            candidates = [r for r in rows if row_key(r) == token and (scope is None or scope[0] < r['i'] < scope[1])]
            if candidates:
                add(candidates[0]['i'])
                anchors.append(token)
        if scope and chosen:
            for token in mentions:
                for r in rows[scope[0] + 1:scope[1]]:
                    if row_key(r) == token:
                        add(r['i'])
    regions = []
    if chosen:
        ordered = sorted(chosen)
        header_rows = {rows[i]['first'] for i in ordered}
        for first in sorted(header_rows):
            regions.append({'kind': 'rowindex', 'index': first, 'text': ''})
        if scope:
            regions.append({'kind': 'rowindex', 'index': scope[0], 'text': ''})
        regions += [{'kind': 'rowindex', 'index': i, 'text': ''} for i in ordered]
        return {'regions': regions, 'anchors': anchors or ['rows'], 'score': len(ordered)}
    wanted = distinctive_stems(finding.get('sparx', {}).get('text', ''))
    prose = plan_prose(model, wanted)
    if prose:
        return {'regions': [{k: v for k, v in r.items() if k != 'anchors'} for r in prose], 'anchors': prose[0]['anchors'], 'score': len(prose[0]['anchors'])}
    return {'reason': 'no fragment of the original page matches the finding', 'score': 0}
