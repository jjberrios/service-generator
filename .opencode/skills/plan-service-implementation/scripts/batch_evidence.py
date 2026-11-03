"""Grounding of batch IR evidence against the bound Sparx pages.

An evidence entry is `<bindingId>#<literal text>`. The literal text must occur in the visible text of the
bound Sparx page (HTML tags, scripts and styles removed; case, accents and whitespace ignored). A slug or a
paraphrase that the page does not contain is rejected. Grounding proves that the cited words exist in the
cited source; it does not prove that the IR interprets them correctly (that stays the semantic review).
"""
from pathlib import Path
import html
import re
import unicodedata

MIN_LENGTH = 5


class EvidenceError(ValueError):
    pass


def normalize(text: str) -> str:
    text = html.unescape(text)
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text).casefold().strip()


def page_text(data: bytes) -> str:
    raw = data.decode('utf-8', errors='replace')
    raw = re.sub(r'<(script|style)\b.*?</\1>', ' ', raw, flags=re.S | re.I)
    return normalize(re.sub(r'<[^>]+>', ' ', raw))


def _evidence_lists(batch: dict):
    for section in ('properties', 'connections', 'steps'):
        for item in batch.get(section, []):
            yield from _walk(item, f'{section}[{item.get("id", item.get("key"))}]')
    for item in batch.get('omittedBehavior', []):
        yield f'omittedBehavior[{item.get("id")}]', item.get('evidence', [])
    for section in ('dtos', 'ports'):
        for item in batch.get(section, []):
            yield f'{section}[{item.get("name", item.get("id"))}]', item.get('evidence', [])
            for method in item.get('methods', []) or []:
                yield f'ports[{item.get("id")}].{method.get("name")}', method.get('evidence', [])
    yield from _flow(batch.get('flow', []) or [], 'flow')
    for adapter in batch.get('adapters', []) or []:
        yield f'adapters[{adapter.get("port")}]', adapter.get('evidence', [])
        for method in adapter.get('methods', []) or []:
            yield f'adapters[{adapter.get("port")}].{method.get("name")}', method.get('evidence', [])
    yield 'outcomes', batch['outcomes'].get('evidence', [])


def _flow(steps, label):
    for step in steps:
        yield f'{label}/{step.get("id")}', step.get('evidence', [])
        for key in ('steps', 'then', 'else'):
            yield from _flow(step.get(key, []) or [], f'{label}/{step.get("id")}')


def _walk(item: dict, label: str):
    yield label, item.get('evidence', [])
    for child in item.get('steps', []) or []:
        yield from _walk(child, f'{label}/{child.get("id")}')


def verify(batch: dict, repo: Path) -> None:
    """Raise EvidenceError unless every evidence literal occurs in its bound page. Call after validate()."""
    texts = {}
    for binding in batch['sourceBindings']:
        path = Path(repo) / binding['path']
        texts[binding['id']] = page_text(path.read_bytes())
    problems = []
    for label, entries in _evidence_lists(batch):
        for entry in entries:
            binding, _, fragment = entry.partition('#')
            wanted = normalize(fragment)
            if binding not in texts:
                problems.append(f'{label}: unknown binding {binding!r}')
            elif len(wanted) < MIN_LENGTH:
                problems.append(f'{label}: evidence text {fragment!r} is too short to ground')
            elif wanted not in texts[binding]:
                problems.append(f'{label}: {fragment!r} not found in {binding}')
    if problems:
        raise EvidenceError('ungrounded batch evidence: ' + '; '.join(problems))
