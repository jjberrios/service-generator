"""Read-only attachment inventory for explicitly authorized Sparx pages; no crawling or execution."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import argparse
import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
import yaml

LIMIT = 20 * 1024 * 1024
DOCUMENTS = {'.pdf', '.docx', '.doc', '.rtf', '.txt', '.md', '.csv', '.xlsx', '.xls', '.xml', '.json', '.yml', '.yaml'}


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references, self.text = [], []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.ignored += 1
        if self.ignored:
            return
        ref = attrs.get('data' if tag == 'object' else 'href' if tag == 'a' else 'src')
        if ref and tag in ('a', 'iframe', 'object', 'embed'):
            suffix = Path(unquote(urlsplit(ref).path)).suffix.lower()
            if tag != 'a' or suffix in DOCUMENTS or 'download' in attrs or 'linkdoc' in ref.lower():
                self.references.append(ref)

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored and data.strip():
            self.text.append(data.strip())


def extract_text(path):
    if path.stat().st_size > LIMIT:
        raise ValueError('document-size-limit')
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == '.docx':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            member = archive.getinfo('word/document.xml')
            if member.file_size > LIMIT:
                raise ValueError('document-size-limit')
            tree = ET.fromstring(archive.read(member))
            return '\n'.join(''.join(p.itertext()) for p in tree.iter() if p.tag.endswith('}p'))
    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ValueError('pdf-reader-unavailable') from error
        try:
            texts = [page.extract_text() or '' for page in PdfReader(io.BytesIO(data)).pages]
        except Exception as error:
            # Optional PDF libraries expose different parser/encryption exceptions.
            # Malformed evidence must remain a gap, not abort the whole inventory.
            raise ValueError('pdf-unreadable: ' + type(error).__name__) from error
        if not any(t.strip() for t in texts):
            raise ValueError('pdf-no-extractable-text')
        return '\n'.join(f'[page {i + 1}]\n{text}' for i, text in enumerate(texts))
    if suffix in ('.htm', '.html'):
        parser = References()
        parser.feed(data.decode('utf-8', errors='replace'))
        return '\n'.join(parser.text)
    if suffix in {'.txt', '.md', '.csv', '.xml', '.json', '.yml', '.yaml'}:
        return data.decode('utf-8-sig')
    raise ValueError('unsupported-document-format')


def inventory(repo, source_root, pages):
    repo, source_root = Path(repo).resolve(), Path(source_root).resolve()
    workspace = (repo / '.factory').resolve()
    if workspace.parent.name == 'services' and workspace.parent.parent.name == '.factory':
        repo = workspace.parents[2]
    if not source_root.is_relative_to((repo / 'input/sparx').resolve()):
        raise ValueError('source root must be under input/sparx')
    records, sources = [], {}
    for page in sorted(set(pages)):
        path = (repo / page).resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise ValueError(f'missing/unsafe authorized page: {page}')
        sources[page] = hashlib.sha256(path.read_bytes()).hexdigest()
        parser = References()
        parser.feed(path.read_text(encoding='utf-8', errors='replace'))
        for ref in parser.references:
            record = {'sourcePage': page, 'reference': ref}
            records.append(record)
            parts = urlsplit(ref)
            if parts.scheme or parts.netloc or unquote(parts.path).startswith(('/', '\\')) or '\\' in unquote(parts.path):
                record['status'] = 'external-or-absolute-reference'
                continue
            target = (path.parent / unquote(parts.path)).resolve()
            if not target.is_relative_to(source_root):
                record['status'] = 'escapes-source-root'
                continue
            rel = target.relative_to(repo).as_posix()
            record['path'] = rel
            if not target.is_file():
                record['status'] = 'missing-local-file'
                continue
            record['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            sources[rel] = record['sha256']
            try:
                record['text'] = extract_text(target)
                if not record['text'].strip():
                    raise ValueError('empty-document')
                record['status'] = 'extracted'
                record['locator'] = 'text lines (PDF page markers; DOCX paragraphs in document order)'
                if target.suffix.lower() in ('.htm', '.html'):
                    nested = References()
                    nested.feed(target.read_text(encoding='utf-8', errors='replace'))
                    record['nestedReferencesNotLoaded'] = nested.references
            except (ValueError, OSError, UnicodeError, zipfile.BadZipFile, KeyError, ET.ParseError) as error:
                record['status'], record['reason'] = 'unverified', str(error)
    return {'schemaVersion': 1, 'kind': 'sparx-attachments', 'sourceRoot': source_root.relative_to(repo).as_posix(),
            'sourceBindings': [{'path': p, 'sha256': h} for p, h in sorted(sources.items())], 'documents': records}


def authorized_pages(authority):
    root = authority['target']['sourceRoot'].rstrip('/')
    selection = authority.get('selection') or {}
    ids = {selection.get('authoritativeBranchRootId'), *(selection.get('complementBranchRootIds') or [])}
    pages = set()

    def collect(node):
        if isinstance(node, dict):
            if node.get('page'):
                pages.add(root + '/' + node['page'])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    for branch in authority.get('branches', []):
        if branch.get('branchRootId') in ids:
            collect(branch)
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--page', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(Path.cwd(), args.source_root, args.page)
    args.output.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding='utf-8')


if __name__ == '__main__':
    main()
