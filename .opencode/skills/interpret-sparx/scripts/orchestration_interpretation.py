"""Evidence-bound interpretation of an orchestration service (remote calls + decisions + compensations).

Input: the authoritative endpoint-detail artifact of a service workspace (.factory/services/<service>/sparx-authoritative-endpoint-detail.yml),
the authoritative branch pages of the Sparx export (only for the process graph: gateways and sequence flows) and the linkdoc pages of activities
whose tables were not structured by the indexer (free prose such as formulas).

Output (`build`): the `sparx-spec.yml` document: parsed activities with evidence, the process graph, the per-request-type flows (steps, decisions,
compensation chains), the discrepancies between activity prose and the process graph, and the behavior that the sources do not define.
The structural facts of every remote call (method, URL, mapping rows, outcome codes) are PARSED from the evidence. The ordering of the steps, the
decisions (gateway text) and the compensation chains come from the process graph and are written down in FLOWS below; `build` verifies each of them
against the evidence (activity found, gateway text found, sequence edge found) and fails instead of approximating.
Nothing here is specific to a JVM or to a template: it is a behavior description.
"""
from pathlib import Path
import hashlib
import html
import re
import unicodedata
import yaml

KIND = 'sparx-spec'
VERSION = 1


class InterpretationError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fold(text) -> str:
    """Accent- and case-insensitive comparison key."""
    text = html.unescape(str(text or '')).replace('\ufffd', '')
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'\s+', ' ', ''.join(c for c in text if not unicodedata.combining(c))).strip().lower()


# --------------------------------------------------------------------------- request field aliases
# Spelling quirks of the evidence mapped to the contract field (documented as assumptions by the consolidation stage).
FIELD_ALIASES = {'line': 'line', 'clientecode': 'clientCode', 'agreemanamementcodeid': 'agreementCodeId', 'requesttype': 'requestTypeId',
                 'quoteexperationdate': 'quoteExpirationDate', 'createdate': 'createdAt', 'createat': 'createdAt', 'createuser': 'createdBy',
                 'lastuserupdate': 'updatedBy', 'lastdateupdate': 'updatedAt'}


def alias(name: str) -> str:
    return FIELD_ALIASES.get(fold(name).replace(' ', ''), name)


# --------------------------------------------------------------------------- parsing of one activity
SECTION_MARKERS = {'headers': 'headers', 'path param': 'path', 'path params': 'path', 'query param': 'query', 'queryparam': 'query', 'query params': 'query',
                   'body': 'body', 'body request': 'body'}


def section_by_label(activity, *labels):
    wanted = {fold(label) for label in labels}
    for section in activity.get('sections') or []:
        if fold(section.get('label')) in wanted:
            return section
    return None


def rows_of(section):
    return [[str(v if v is not None else '').strip() for v in row['values'].values()] for row in (section or {}).get('rows') or []]


def text_lines(section):
    return [line['text'].strip() for line in (section or {}).get('lines') or [] if line.get('text', '').strip()]


def key_value_call(activity):
    for section in activity.get('sections') or []:
        if section.get('kind') == 'keyValue':
            entries = {e['key']: str(e.get('value') or '').strip() for e in section['entries']}
            return {'type': entries.get('type'), 'name': entries.get('name'), 'method': entries.get('operation'), 'url': entries.get('connection')}
    return None


def parse_properties(activity):
    out = {}
    for line in text_lines(section_by_label(activity, 'VARIABLES PROPERTIES')):
        if line.startswith('#'):
            continue
        match = re.match(r'^(\w+)\s*=\s*(.*)$', line)
        if match:
            value = match.group(2).strip()
            out[match.group(1)] = int(value) if re.fullmatch(r'-?\d+', value) else value
    return out


OUT_CODE = re.compile(r'\b(IDF\d{3}|IDT)\b')


def parse_outcomes(lines):
    """CONSIDERACIONES prose -> ok statuses, per-status codes, otherwise code, technical failure and compensation names."""
    outcome = {'ok': [], 'byStatus': {}, 'otherwise': None, 'otherwiseCompensation': None, 'technicalCompensation': None, 'ignoreFailure': False, 'logOnly': False}
    for line in lines:
        folded = fold(line)
        status = re.search(r'http status = (\d{3})', folded)
        rollback = re.search(r'(?:ejecutar|realizar)\s+["\'\u201c]([^"\'\u201d]+)["\'\u201d]', fold(line).replace('\u2018', "'")) or re.search(
            r'(?:ejecutar|realizar)\s+[\'"]([^\'"]+)[\'"]', folded)
        compensation = fold(rollback.group(1)) if rollback else None
        code = OUT_CODE.search(line)
        if status and 'continuar' in folded:
            outcome['ok'].append(int(status.group(1)))
        elif status and code:
            outcome['byStatus'][int(status.group(1))] = code.group(1)
        elif folded.startswith('caso contrario') and code:
            outcome['otherwise'], outcome['otherwiseCompensation'] = code.group(1), compensation
        elif 'no disponible' in folded:
            outcome['technicalCompensation'] = compensation
        elif folded.startswith('si se genera un error') and code:
            outcome['otherwise'], outcome['otherwiseCompensation'] = code.group(1), compensation
        elif folded.startswith('si se genera un error'):
            outcome['otherwise'] = None
        elif folded.startswith('continuar con la siguiente actividad'):
            outcome['ignoreFailure'] = True
        elif folded.startswith('pintar en el log'):
            outcome['logOnly'] = True
    return outcome


def parse_mapping(rows, kind):
    """INPUT/OUTPUT columnar rows -> sectioned list of dicts."""
    section, parsed = None, []
    for row in rows:
        row = (row + ['', '', '', ''])[:4]
        name, origin, dest, transform = row
        if not name and not origin and dest:
            section = SECTION_MARKERS.get(fold(dest), section)
            continue
        if kind == 'input':
            parsed.append({'section': section, 'source': name, 'origin': origin, 'dest': dest, 'transform': transform})
        else:
            parsed.append({'name': name, 'type': origin, 'dest': dest, 'transform': transform})
    return parsed


def parse_activity(activity):
    head = activity['activity']
    record = {'name': head['name'], 'lane': activity['lane']['name'], 'guid': head.get('uuid'), 'page': head.get('page'), 'pageSha256': head.get('pageSha256'),
              'status': head.get('status'), 'call': key_value_call(activity)}
    inputs, outputs = section_by_label(activity, 'INPUT'), section_by_label(activity, 'OUTPUT')
    record['input'] = parse_mapping(rows_of(inputs), 'input') if inputs else []
    record['output'] = parse_mapping(rows_of(outputs), 'output') if outputs else []
    record['outcome'] = parse_outcomes(text_lines(section_by_label(activity, 'CONSIDERACIONES')))
    record['properties'] = parse_properties(activity)
    record['validations'] = text_lines(section_by_label(activity, 'VALIDACIONES'))
    record['body'] = [row for row in rows_of(section_by_label(activity, 'BODY', 'HeaderRequest'))]
    record['notes'] = text_lines(section_by_label(activity, 'NOTA', 'NOTAS'))
    record['algorithm'] = text_lines(section_by_label(activity, 'ALGORITMO'))
    record['linkdoc'] = (activity.get('embeddedLinkdoc') or {}).get('resolvedFile')
    record['linkdocSha256'] = (activity.get('embeddedLinkdoc') or {}).get('sha256')
    return record


def lane_of(record):
    return fold(record['lane'])


def select(activities, lane, prefix):
    """Activity selector `lane/prefix`: lane equality (folded), name starts with the numeric/text prefix."""
    matches = [a for a in activities if lane_of(a) == fold(lane) and (fold(a['name']).startswith(fold(prefix) + ' ') or fold(a['name']).startswith(fold(prefix) + '.')
                                                                     or fold(a['name']) == fold(prefix) or fold(a['name']).startswith(fold(prefix)))]
    exact = [a for a in matches if re.match(rf'^{re.escape(fold(prefix))}[\s.]', fold(a['name']) + ' ') or fold(a['name']) == fold(prefix)]
    matches = exact or matches
    if len(matches) != 1:
        raise InterpretationError(f'activity selector {lane}/{prefix} matched {len(matches)} activities')
    return matches[0]


# --------------------------------------------------------------------------- process graph (raw pages of the authoritative branch)
def _clean(fragment: str) -> str:
    fragment = re.sub(r'<br\s*/?>', ' | ', fragment)
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', '', fragment)).split())


def load_process_graph(repo: Path, detail_op: dict, source_root: Path, page_prefix: str):
    """Reads the pages of the authoritative branch that belong to the operation's process: element name/type and its outgoing sequence flows."""
    method_name = detail_op['sparxMethod']['name']
    process_name = detail_op['process']['name']
    needle = f'{method_name} / {process_name}'
    folder = source_root / page_prefix
    nodes = {}
    for page in sorted(folder.glob('EA*.htm')):
        text = page.read_text(encoding='utf-8', errors='replace')
        crumb = _clean(text[:6000])
        if needle not in crumb:
            continue
        plain = html.unescape(re.sub(r'<[^>]+>', '\n', text))
        head = re.search(r'\n\s*([^\n]*?)\s*:\s*Public\s+\S*?(\w+)\S*\s+(\w+)\s*\n', plain)
        if not head:
            continue
        node = {'page': page.name, 'name': head.group(1).strip(), 'type': head.group(3), 'sha256': sha(page.read_bytes()), 'to': []}
        block = re.search(r'id="Flow&HastaTable">(.*?)</table>', text, re.S)
        if block:
            for row in re.finditer(r'<tr>\s*<td width="50%" class="TableRow"[^>]*>(.*?)</td>\s*<td width="50%" class="TableRow"[^>]*>(.*?)</td>', block.group(1), re.S):
                link = re.search(r'href="([^"]+)">(.*?)</a>', row.group(1), re.S)
                if link:
                    node['to'].append({'page': link.group(1), 'name': _clean(link.group(2)), 'label': _clean(row.group(2))})
        nodes[page.name] = node
    return nodes


def graph_codes_after(nodes, activity_name_part, hops=3):
    """IDF codes reachable from the activity page through its failure branches (gateway 'No'/unlabelled -> [intermediate] -> end event)."""
    start = next((n for n in nodes.values() if n['type'] == 'Actividad' and fold(n['name']).startswith(fold(activity_name_part))), None)
    if not start:
        return None
    codes, frontier, seen = set(), [start['page']], set()
    for _ in range(hops):
        following = []
        for page in frontier:
            node = nodes.get(page)
            if not node or page in seen:
                continue
            seen.add(page)
            for edge in node['to']:
                target = nodes.get(edge['page'])
                if not target:
                    continue
                if target['type'] == 'EndEvent':
                    codes.update(OUT_CODE.findall(target['name']))
                elif target['type'] in ('Gateway', 'IntermediateEvent'):
                    following.append(target['page'])
        frontier = following
    return codes


def graph_has_edge(nodes, source_part, target_part):
    for node in nodes.values():
        if fold(source_part) in fold(node['name']):
            for edge in node['to']:
                if fold(target_part) in fold(edge['name']):
                    return True
    return False


def graph_has_node(nodes, text):
    return any(fold(text) in fold(n['name']) for n in nodes.values())
