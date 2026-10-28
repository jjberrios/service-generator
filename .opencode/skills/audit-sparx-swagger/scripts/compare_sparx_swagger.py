"""Deterministic Sparx vs Swagger/OpenAPI comparison (read-only audit; no generation, no source edits).

Consumes ONLY artifacts produced by the existing pipeline:
  - normalized OpenAPI  (parse-openapi / normalize_openapi.py)
  - authoritative endpoint detail (parse-sparx / build_authoritative_endpoint_detail.py), authoritative branch only
and optional agent-authored semantic findings (supplemental file) which are validated, never trusted blindly.

Every result is exactly one of:
  - contradiccion-verificada : both sources make normative, incompatible statements about the same element
  - diferencia-documental    : an element/rule documented in one source and absent or structured differently in the other
  - no verificado            : (separate list) behavior that cannot be established, or sources that cannot be compared
Not findings: contradictions internal to Sparx, absent constraints when each source owns different concerns, matches.

Writes a structured findings registry that build_report_docx.py renders deterministically.
Something is reported only when BOTH sources (or an authoritative absence record) provide evidence.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
import unicodedata
import yaml

import sparx_methods as sm
import source_currency as currency

SEVERITIES = ('Alta', 'Media', 'Baja')
CATEGORIES = ('contradiccion-verificada', 'diferencia-documental')
CATEGORY_LABELS = {'contradiccion-verificada': 'Contradicciones verificadas', 'diferencia-documental': 'Diferencias documentales'}
UNVERIFIED_CATEGORIES = {'comportamiento-no-especificado': 'Comportamiento no especificado', 'contradiccion-interna-sparx': 'Contradicción interna de Sparx (no es una diferencia con Swagger)',
                         'fuente-no-comparable': 'Fuentes no comparables', 'verificacion-pendiente': 'Verificación pendiente'}
KINDS = ('contradiction', 'missing-in-swagger', 'missing-in-sparx', 'requirement-difference', 'type-or-structure-difference',
         'http-status-difference', 'operation-lifecycle', 'route-difference', 'behavior-difference', 'conditional-rule-difference', 'naming-difference')
KIND_CATEGORY = {'contradiction': 'contradiccion-verificada', 'requirement-difference': 'contradiccion-verificada', 'type-or-structure-difference': 'contradiccion-verificada',
                 'operation-lifecycle': 'contradiccion-verificada', 'missing-in-swagger': 'diferencia-documental', 'missing-in-sparx': 'diferencia-documental',
                 'http-status-difference': 'diferencia-documental', 'route-difference': 'diferencia-documental', 'behavior-difference': 'diferencia-documental', 'conditional-rule-difference': 'diferencia-documental', 'naming-difference': 'diferencia-documental'}
REQUIRED_FINDING_FIELDS = ('operation', 'element', 'sparx', 'swagger', 'inconsistency', 'evidence', 'severity', 'kind', 'category')
# Swagger evidence that illustrates but does not define behavior cannot, by itself, establish a contradiction.
NON_NORMATIVE_SWAGGER = re.compile(r'/(examples?|description|summary)(/|$)')
# Elements whose presence in only one source reflects different responsibilities, not an inconsistency.
RESPONSIBILITY_CLASSES = ('constraint', 'internal-column', 'error-envelope')
SATISFACTORY = re.compile(r'sin diferencias|\bcoinciden?\b|\bconsistentes?\b|no es (una )?inconsistencia|sin inconsistencias|\bcorrectos?\b|verificad[oa]s? sin', re.I)
YES = {'si', 's', 'yes', 'y', 'true', 'obligatorio', 'required'}
NO = {'no', 'n', 'false', 'opcional', 'optional'}
TYPE_FAMILIES = {
    'integer': {'integer', 'int', 'long', 'bigint', 'smallint', 'int32', 'int64', 'short'},
    'decimal': {'number', 'decimal', 'double', 'float', 'numeric', 'bigdecimal'},
    'string': {'string', 'varchar', 'varchar2', 'char', 'text', 'clob', 'nvarchar', 'nvarchar2'},
    'boolean': {'boolean', 'bool'},
    'datetime': {'date', 'datetime', 'date-time', 'timestamp', 'localdatetime', 'localdate'},
}


def plain(value) -> str:
    text = unicodedata.normalize('NFD', str(value or '').strip().lower())
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def required_flag(value):
    token = plain(value)
    if token in YES:
        return True
    if token in NO:
        return False
    return None


def requirement_mode(value):
    """'required' | 'optional' | 'conditional' (a trailing * in Sparx marks a requirement qualified by CONSIDERACIONES) | None when not readable."""
    token = plain(value)
    star = token.endswith('*')
    token = token.rstrip('*').strip()
    base = True if token in YES else False if token in NO else None
    if base is None:
        return None
    return 'conditional' if star else ('required' if base else 'optional')


AT_LEAST_ONE = re.compile(r'al\s+menos\s+(?:uno|un)\b', re.I)
DEPENDS = re.compile(r'\bsi\s+([A-Za-z_][\w.]*)\s+(?:viene|se\s+env\w+|est\w*\s+presente|es\s+enviado|se\s+informa)[^,.;]*[,;]?\s*([A-Za-z_][\w.]*)\s+(?:tambi\w+\s+)?(?:debe\s+ser|es|ser\w+)\s+obligatori', re.I)


TOGETHER = re.compile(r'([A-Za-z_]\w*)\s+y\s+([A-Za-z_]\w*)\s+(?:es|son)\s+opcional\w*[^.]*?(?:ambos|ambas)\s+deben\s+(?:enviarse|informarse|venir)\s+conjuntamente', re.I)


def conditional_rules(lines):
    """Rules stated in the CONSIDERACIONES of a validation Activity that qualify starred requirements ('No*')."""
    rules = {'atLeastOne': False, 'depends': [], 'together': [], 'texts': []}
    for line in lines or []:
        text = line.get('text') if isinstance(line, dict) else str(line)
        text = ' '.join(str(text or '').split())
        if AT_LEAST_ONE.search(text):
            rules['atLeastOne'] = True
            rules['texts'].append(text)
        for first, second in TOGETHER.findall(text):
            rules['together'].append((first, second))
            rules['texts'].append(text)
        for trigger, dependent in DEPENDS.findall(text):
            rules['depends'].append((trigger, dependent))
            rules['texts'].append(text)
    return rules


def family(type_name, fmt=None):
    token = plain(type_name)
    if fmt and plain(fmt) in ('date', 'date-time'):
        return 'datetime'
    for name, aliases in TYPE_FAMILIES.items():
        if token in aliases:
            return name
    return None


def route_key(path: str) -> str:
    """Route identity ignoring a leading /api, a version segment (/v1) and path-parameter names."""
    text = '/' + str(path or '').strip().strip('/').lower()
    text = re.sub(r'^/api(?=/|$)', '', text)
    text = re.sub(r'^/v\d+(?=/|$)', '', text)
    return re.sub(r'\{[^}]*\}', '{}', text) or '/'


def esc(pointer_token: str) -> str:
    return pointer_token.replace('~', '~0').replace('/', '~1')


def schema_of(node):
    return (node or {}).get('resolved') or node or {}


def header_key(name: str) -> str:
    """Comparable identity of a header ignoring the conventional x- prefix, separators and case (x-user-id ~ userId)."""
    return re.sub(r'[^a-z0-9]', '', re.sub(r'^x[-_]', '', str(name or '').strip().lower()))


def flatten_schema(schema: dict, pointer: str, prefix: str = '') -> dict:
    """Flatten an object schema to {dotted.path: {type, format, required, pointer}}; arrays use '[]'."""
    out = {}
    schema = schema_of(schema)
    required = set(schema.get('required') or [])
    for name, child in (schema.get('properties') or {}).items():
        child_schema = schema_of(child)
        path = f'{prefix}{name}'
        entry = {'type': child_schema.get('type'), 'format': child_schema.get('format'), 'required': name in required,
                 'pointer': f'{pointer}/properties/{esc(name)}'}
        out[path] = entry
        if child_schema.get('type') == 'object':
            out.update(flatten_schema(child_schema, entry['pointer'], path + '.'))
        elif child_schema.get('type') == 'array' and child_schema.get('items'):
            items = schema_of(child_schema['items'])
            out[path]['pointer'] = entry['pointer']
            if items.get('type') == 'object':
                out.update(flatten_schema(items, entry['pointer'] + '/items', path + '[].'))
    return out


def json_schema_pointer(operation_index: int, location: str) -> str:
    return f'#/operations/{operation_index}/{location}'


class Auditor:
    def __init__(self, service, openapi, detail, authority_branch, decisions=None, sparx_methods=None):
        self.service = service
        self.openapi = openapi
        self.detail = detail
        self.branch = authority_branch
        self.decisions = decisions or []
        self.findings = {}
        self.unverified = []
        self.discarded = []
        self.sparx_methods = sparx_methods or []
        self.verified_equal = 0

    # ------------------------------------------------------------------ helpers
    def sparx_evidence(self, op, activity=None, row=None, element=None, extra=None):
        method = op.get('sparxMethod') or {}
        evidence = {'branch': self.branch, 'element': element or method.get('name'), 'guid': method.get('guid'), 'page': method.get('page')}
        if activity:
            info = activity.get('activity') or {}
            evidence.update({'activity': info.get('name'), 'activityGuid': info.get('uuid'), 'page': info.get('page', evidence['page'])})
            linkdoc = (activity.get('embeddedLinkdoc') or {}).get('resolvedFile')
            if linkdoc:
                evidence['linkdoc'] = linkdoc
        if row and row.get('evidenceId'):
            evidence['evidenceId'] = row['evidenceId']
        evidence.update(extra or {})
        return {k: v for k, v in evidence.items() if v}

    def add(self, key, **finding):
        if key in self.findings:
            return
        finding.setdefault('category', KIND_CATEGORY.get(finding.get('kind')))
        missing = [f for f in REQUIRED_FINDING_FIELDS if f not in finding]
        if missing:
            raise ValueError(f'finding {key} lacks {missing}')
        self.findings[key] = {'key': key, **finding}

    def cant_verify(self, operation, topic, reason, category='verificacion-pendiente'):
        """List something that could not be established. Matches and satisfactory checks never belong here."""
        if category not in UNVERIFIED_CATEGORIES:
            raise ValueError(f'unverified category {category!r} is not allowed')
        if SATISFACTORY.search(f'{topic} {reason}'):
            raise ValueError('successful verifications and matches are not "no verificado"')
        item = {'operation': operation, 'topic': topic, 'reason': reason, 'category': category}
        if item not in self.unverified:
            self.unverified.append(item)

    def discard(self, operation, element, reason):
        """Traceability of reviewed candidates that are not findings (never rendered)."""
        item = {'operation': operation, 'element': element, 'reason': reason}
        if item not in self.discarded:
            self.discarded.append(item)

    # ------------------------------------------------------------------ audit
    def run(self):
        sparx_by_key = {(o['method'].upper(), o['path']): o for o in self.detail.get('operations', [])}
        for index, spec_op in enumerate(self.openapi['operations']):
            key = (spec_op['method'].upper(), spec_op['path'])
            label = {'method': key[0], 'path': key[1], 'operationId': spec_op.get('operationId')}
            sparx_op = sparx_by_key.get(key)
            status = (sparx_op or {}).get('status')
            if sparx_op is None or status == 'no-sparx-method-in-authoritative-branch':
                self.operation_absent(index, label)
                continue
            if status and status != 'active':
                self.operation_inactive(index, label, sparx_op, status)
                continue
            self.compare_operation(index, label, spec_op, sparx_op)
        return self

    def operation_absent(self, index, label):
        """Before reporting a missing operation verify route prefix equivalence and «Invoca» relations of the service's own methods."""
        key = route_key(label['path'])
        swagger_ref = {'method': label['method'], 'path': label['path'], 'pointer': json_schema_pointer(index, 'path')}
        candidates = [m for m in self.sparx_methods if m['method'] == label['method'] and route_key(m['path']) == key]
        active = [m for m in candidates if m['lifecycle'] == 'active']
        inactive = [m for m in candidates if m['lifecycle'] == 'inactive']
        unknown = [m for m in candidates if m['lifecycle'] == 'unknown']
        if len(active) == 1 and not unknown:
            method = active[0]
            callers = [i for i in method['invokedVia'] if not i['ownedByTargetService']]
            own_invokers = [i for i in method['invokedVia'] if i['ownedByTargetService']]
            note = ''
            if callers:
                note = ' Relación «Invoca» verificada: ' + '; '.join(f'{c["name"]} pertenece al servicio {c["ownerService"] or "no identificado"} (invocador, no es una ruta de este servicio)' for c in callers) + '.'
            if own_invokers:
                self.cant_verify(label, 'Relación «Invoca» interna al servicio', f'{method["name"]} es invocado por métodos del propio servicio ({", ".join(i["name"] for i in own_invokers)}); no se determinó cuál es la ruta expuesta.')
            evidence = [{'branch': self.branch, 'element': f'«Método» {method["name"]}', 'guid': method['guid'], 'page': method['page'], 'status': method['status']}]
            evidence += [{'branch': self.branch, 'element': f'Relación «Invoca» desde «Método» {c["name"]}', 'guid': c['guid'], 'page': c['page']} for c in callers]
            self.add((label['method'], label['path'], 'route', 'route-difference'), operation=label, element='Ruta de la operación', kind='route-difference', severity='Media',
                     sparx={'text': f'El único método activo del servicio con el mismo verbo y recurso es {method["name"]} (estado {method["status"]}).' + note},
                     swagger={'text': f'{label["method"]} {label["path"]} (operationId {label["operationId"]}).'},
                     inconsistency=f'Sparx documenta la ruta {method["path"]} y Swagger declara {label["path"]}: el verbo y el recurso son los mismos y solo difiere el prefijo. No se trata de una operación inexistente.',
                     evidence={'sparx': evidence, 'swagger': [swagger_ref]})
        elif len(active) > 1 or unknown:
            self.cant_verify(label, 'Método Sparx equivalente por ruta', 'Hay varios métodos candidatos o su estado de ciclo de vida no es legible; no se pudo asociar la operación.')
        elif inactive:
            method = inactive[0]
            self.add((label['method'], label['path'], 'operation', 'lifecycle'), operation=label, element='Estado de la operación', kind='operation-lifecycle', severity='Alta',
                     sparx={'text': f'El método equivalente {method["name"]} figura con estado {method["status"]}.'}, swagger={'text': 'La operación está declarada y no está marcada como deprecated.'},
                     inconsistency='Swagger expone una operación que Sparx documenta como inactiva/eliminada.',
                     evidence={'sparx': [{'branch': self.branch, 'element': f'«Método» {method["name"]}', 'guid': method['guid'], 'page': method['page'], 'status': method['status']}], 'swagger': [swagger_ref]})
        else:
            self.add((label['method'], label['path'], 'operation', 'missing-in-sparx'), operation=label, element='Operación', kind='missing-in-sparx', severity='Alta',
                     sparx={'text': f'Ningún método del servicio en la rama autoritativa de Sparx coincide con {label["method"]} {label["path"]} ni por prefijo de ruta.'},
                     swagger={'text': f'{label["method"]} {label["path"]} declarada (operationId {label["operationId"]}).'},
                     inconsistency='La operación del Swagger no tiene método equivalente en la rama autoritativa de Sparx.',
                     evidence={'sparx': [{'branch': self.branch, 'element': 'Catálogo de métodos del servicio en la rama autoritativa', 'authorityFile': 'sparx-target-authority.yml'}],
                               'swagger': [swagger_ref]})

    def operation_inactive(self, index, label, sparx_op, status):
        self.add((label['method'], label['path'], 'operation', 'lifecycle'), operation=label, element='Estado de la operacion', kind='operation-lifecycle', severity='Alta',
                 sparx={'text': f'El metodo figura con estado {status}.'}, swagger={'text': 'La operacion esta declarada y no esta marcada como deprecated.'},
                 inconsistency='Swagger expone una operacion que Sparx documenta como inactiva/eliminada.',
                 evidence={'sparx': [self.sparx_evidence(sparx_op)], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': json_schema_pointer(index, '')}]})

    def compare_operation(self, index, label, spec_op, sparx_op):
        activities = sparx_op.get('activities') or []
        sections = {}
        for activity in activities:
            normalized = activity.get('normalized') or {}
            for name in ('headerrequest', 'path', 'query', 'body'):
                block = (normalized.get('validation') or {}).get(name)
                if block:
                    sections[name] = (activity, block)
            if normalized.get('input'):
                sections['input'] = (activity, normalized['input'])
            if normalized.get('output'):
                sections['output'] = (activity, normalized['output'])
        if not sections:
            self.cant_verify(label, 'Parámetros, mappings y cuerpo', 'No se extrajeron tablas estructuradas de Sparx para la operación.')
        validation_activity = next((a for a in activities if (a.get('normalized') or {}).get('activityRole') == 'validation'), None)
        self._rules = conditional_rules((((validation_activity or {}).get('normalized') or {}).get('considerations') or {}).get('lines'))
        self._header_rows = [r for r in ((sections.get('headerrequest') or (None, {}))[1].get('rows') or [])]
        self._request_inputs = {str(r.get('input') or '').strip() for r in ((sections.get('input') or (None, {}))[1].get('rows') or []) if plain(r.get('origin')) in ('request', 'body', 'requestbody')}
        parameters = spec_op.get('parameters') or {}
        for sparx_name, swagger_in in (('headerrequest', 'header'), ('path', 'path'), ('query', 'query')):
            if sparx_name in sections:
                self.compare_parameters(index, label, sparx_op, sections[sparx_name], parameters.get(swagger_in) or [], sparx_name, swagger_in)
        if 'body' in sections:
            self.compare_body(index, label, spec_op, sparx_op, sections['body'])
        if 'input' in sections:
            self.compare_inputs(index, label, sparx_op, sections['input'], parameters, spec_op)
        if 'output' in sections:
            self.compare_outputs(index, label, spec_op, sparx_op, sections['output'])
        self.compare_status_codes(index, label, spec_op, sparx_op)

    # ------------------------------------------------------------------ requirement (required / optional / conditional)
    def compare_requirement(self, label, kind_label, name, row, swagger_required, min_properties, sparx_evidence, swagger_pointer, group_pointer, ident):
        """Compare Sparx obligatoriedad (including conditional 'No*' qualified by CONSIDERACIONES) with Swagger; conditional is never reduced to a boolean."""
        mode = requirement_mode(row.get('required'))
        if mode is None:
            return
        raw = row.get('required')
        rules = getattr(self, '_rules', {'atLeastOne': False, 'depends': [], 'texts': []})
        element = f'{kind_label} {name}'
        swagger_ref = {'method': label['method'], 'path': label['path'], 'pointer': swagger_pointer}
        rule_text = next(iter(rules['texts']), '')
        if mode == 'conditional':
            partner = next((t for t in rules.get('together', []) if str(name).lower() in (t[0].lower(), t[1].lower())), None)
            if partner:
                other = partner[1] if partner[0].lower() == str(name).lower() else partner[0]
                if swagger_required:
                    self.add(ident + ('requirement-difference',), operation=label, element=element, kind='requirement-difference', severity='Alta',
                             sparx={'text': f'Opcional ("{raw}"): según CONSIDERACIONES {partner[0]} y {partner[1]} son opcionales pero, si se usan, ambos deben enviarse juntos.'},
                             swagger={'text': 'required: true (obligatorio siempre).'}, inconsistency='Sparx lo define opcional con una regla de envío conjunto y Swagger lo declara obligatorio.',
                             evidence={'sparx': [sparx_evidence], 'swagger': [swagger_ref]})
                else:
                    self.add((label['method'], label['path'], 'group', f'together:{plain(partner[0])}:{plain(partner[1])}'), operation=label, element=f'{kind_label} {partner[0]} y {partner[1]} (envío conjunto)', kind='conditional-rule-difference', severity='Media',
                             sparx={'text': f'CONSIDERACIONES: {partner[0]} y {partner[1]} son opcionales, pero si se usa uno deben enviarse ambos; si solo llega uno, la respuesta es 400.'},
                             swagger={'text': f'Declara {partner[0]} y {partner[1]} como opcionales independientes; no expresa la regla de envío conjunto.'},
                             inconsistency='La regla de envío conjunto de Sparx (y su error 400) no está expresada en Swagger.', evidence={'sparx': [sparx_evidence], 'swagger': [swagger_ref]})
                return
            dependent = next((t for t in rules['depends'] if t[1].lower() == str(name).lower()), None)
            trigger = next((t for t in rules['depends'] if t[0].lower() == str(name).lower()), None)
            if dependent:
                sparx_text = f'Obligatoriedad condicional ("{raw}"): según CONSIDERACIONES, si {dependent[0]} viene, {name} es obligatorio; en otro caso es opcional.'
                if swagger_required:
                    self.add(ident + ('requirement-difference',), operation=label, element=element, kind='requirement-difference', severity='Alta',
                             sparx={'text': sparx_text}, swagger={'text': 'required: true (obligatorio siempre).'},
                             inconsistency='Sparx define la obligatoriedad como condicional y Swagger la declara incondicional.',
                             evidence={'sparx': [sparx_evidence], 'swagger': [swagger_ref]})
                else:
                    self.add(ident + ('conditional-rule-difference',), operation=label, element=element, kind='conditional-rule-difference', severity='Media',
                             sparx={'text': sparx_text}, swagger={'text': 'required: false (opcional) y no expresa la condición.'},
                             inconsistency='La obligatoriedad condicional de Sparx no está expresada en Swagger.',
                             evidence={'sparx': [sparx_evidence], 'swagger': [swagger_ref]})
                return
            if trigger:
                mode, raw_note = 'optional', f'opcional; si viene, hace obligatorio a {trigger[1]} ("{raw}")'
                row = {**row, 'required': 'No'}
            elif rules['atLeastOne']:
                if swagger_required:
                    self.add(ident + ('requirement-difference',), operation=label, element=element, kind='requirement-difference', severity='Alta',
                             sparx={'text': f'Obligatoriedad condicional ("{raw}"): según CONSIDERACIONES debe enviarse al menos uno de los campos marcados, no cada uno.'},
                             swagger={'text': 'required: true (obligatorio siempre).'}, inconsistency='Sparx exige "al menos uno" de un grupo de campos y Swagger exige este campo siempre.',
                             evidence={'sparx': [sparx_evidence], 'swagger': [swagger_ref]})
                elif not (min_properties and min_properties >= 1):
                    self.add((label['method'], label['path'], 'group', 'at-least-one'), operation=label, element=f'{kind_label} (regla "al menos uno")', kind='conditional-rule-difference', severity='Media',
                             sparx={'text': 'CONSIDERACIONES: se debe enviar al menos uno de los campos marcados con * o el servicio rechaza la petición.'},
                             swagger={'text': 'Los campos son opcionales y el esquema no exige un mínimo de propiedades (minProperties).'},
                             inconsistency='La regla "al menos uno" de Sparx no está expresada en Swagger.', evidence={'sparx': [sparx_evidence], 'swagger': [{**swagger_ref, 'pointer': group_pointer}]})
                else:
                    self.verified_equal += 1
                return
            else:
                self.cant_verify(label, f'Obligatoriedad condicional de {element}', f'Sparx la marca "{raw}" pero CONSIDERACIONES no explica la condición.', 'comportamiento-no-especificado')
                return
        sparx_required = mode == 'required'
        if sparx_required != bool(swagger_required):
            self.add(ident + ('requirement-difference',), operation=label, element=element, kind='requirement-difference', severity='Alta' if (sparx_required or kind_label in ('query', 'path', 'body')) else 'Media',
                     sparx={'text': f'Obligatorio: {raw}.'}, swagger={'text': f'required: {str(bool(swagger_required)).lower()}.'},
                     inconsistency='La obligatoriedad difiere entre Sparx y Swagger.', evidence={'sparx': [sparx_evidence], 'swagger': [swagger_ref]})
        else:
            self.verified_equal += 1

    # ------------------------------------------------------------------ parameters
    def compare_parameters(self, index, label, sparx_op, section, swagger_params, sparx_name, swagger_in):
        activity, block = section
        rows = {}
        for row in block.get('rows') or []:
            name = row.get(sparx_name) or row.get('header') or row.get('name')
            if name:
                rows[str(name).strip()] = row
        swagger = {p['name']: (i, p) for i, p in enumerate(swagger_params)}
        base = f'#/operations/{index}/parameters/{swagger_in}'
        for name, row in rows.items():
            ident = (label['method'], label['path'], f'{swagger_in}:{plain(name)}')
            if name not in swagger:
                self.add(ident + ('missing-in-swagger',), operation=label, element=f'{swagger_in} {name}', kind='missing-in-swagger', severity='Media',
                         sparx={'text': f'Documenta el {swagger_in} "{name}" (requerido: {row.get("required") or "no indicado"}, tipo: {row.get("type") or row.get("tipo") or "no indicado"}).'},
                         swagger={'text': f'No declara el {swagger_in} "{name}".'}, inconsistency=f'El {swagger_in} documentado en Sparx no existe en el Swagger.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, activity, row)], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': base}]})
                continue
            position, param = swagger[name]
            pointer = f'{base}/{position}'
            self.compare_requirement(label, swagger_in, name, row, param.get('required'), None, self.sparx_evidence(sparx_op, activity, row), pointer + '/required', pointer, ident)
            s_type = row.get('type') or row.get('tipo')
            sw_schema = param.get('schema') or {}
            fs, fw = family(s_type), family(sw_schema.get('type'), sw_schema.get('format'))
            if fs and fw and fs != fw:
                self.add(ident + ('type-or-structure-difference',), operation=label, element=f'{swagger_in} {name}', kind='type-or-structure-difference', severity='Media',
                         sparx={'text': f'Tipo: {s_type}.'}, swagger={'text': f'type: {sw_schema.get("type")}' + (f', format: {sw_schema.get("format")}' if sw_schema.get('format') else '') + '.'},
                         inconsistency='El tipo de dato difiere entre Sparx y Swagger.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, activity, row)], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': pointer + '/schema'}]})
            elif s_type and not (fs and fw):
                self.cant_verify(label, f'Tipo de {swagger_in} {name}', f'Tipos no comparables: Sparx "{s_type}" / Swagger "{sw_schema.get("type")}".', 'fuente-no-comparable')
        for name, (position, param) in swagger.items():
            if name in rows:
                continue
            self.add((label['method'], label['path'], f'{swagger_in}:{plain(name)}', 'missing-in-sparx'), operation=label, element=f'{swagger_in} {name}', kind='missing-in-sparx',
                     severity='Media' if param.get('required') else 'Baja',
                     sparx={'text': f'No lista el {swagger_in} "{name}" en la tabla de validacion.'},
                     swagger={'text': f'Declara el {swagger_in} "{name}" (required: {str(bool(param.get("required"))).lower()}).'},
                     inconsistency=f'El {swagger_in} declarado en Swagger no esta documentado en Sparx.',
                     evidence={'sparx': [self.sparx_evidence(sparx_op, activity, extra={'section': sparx_name})],
                               'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': f'{base}/{position}'}]})

    # ------------------------------------------------------------------ body
    def request_schema(self, spec_op, index):
        content = ((spec_op.get('requestBody') or {}).get('content') or {})
        for media, node in content.items():
            return flatten_schema(node.get('schema'), f'#/operations/{index}/requestBody/content/{esc(media)}/schema')
        return {}

    def request_min_properties(self, spec_op):
        for media, node in ((spec_op.get('requestBody') or {}).get('content') or {}).items():
            return schema_of(node.get('schema')).get('minProperties')
        return None

    def compare_body(self, index, label, spec_op, sparx_op, section):
        activity, block = section
        flat = self.request_schema(spec_op, index)
        rows = {}
        for row in block.get('rows') or []:
            name = row.get('body') or row.get('name')
            if not name:
                continue
            if not str(row.get('required') or '').strip() and not str(row.get('type') or '').strip():
                # A row without obligatoriedad and type is a section label of the table, not a field.
                self.discard(label, f'body {name}', 'Rótulo de sección de la tabla Body de Sparx, no es un campo.')
                continue
            rows[str(name).strip()] = row
        # A field documented only in the Sparx validation table and a field declared only in Swagger that Sparx maps (INPUT) under the other name
        # are one concept with inconsistent naming: report once instead of two unrelated "missing" findings.
        inputs = getattr(self, '_request_inputs', set())
        sparx_only = [n for n in rows if n not in flat and n not in inputs]
        swagger_only = [n for n, f in flat.items() if n not in rows and f['type'] not in ('object', 'array') and n in inputs]
        paired = set()
        if len(sparx_only) == 1 and len(swagger_only) == 1:
            sp, sw = sparx_only[0], swagger_only[0]
            paired = {sp, sw}
            self.add((label['method'], label['path'], f'body:{plain(sp)}~{plain(sw)}', 'naming-difference'), operation=label, element=f'body {sp} / {sw}', kind='naming-difference', severity='Media',
                     sparx={'text': f'La tabla Body de validación documenta "{sp}", mientras el mapping INPUT de la misma operación usa "{sw}".'},
                     swagger={'text': f'El esquema del request declara "{sw}" y no "{sp}".'},
                     inconsistency=f'El campo se llama "{sp}" en la tabla de validación de Sparx y "{sw}" en el mapping INPUT y en Swagger; no se puede confirmar que sea el mismo campo sin una aclaración.',
                     evidence={'sparx': [self.sparx_evidence(sparx_op, activity, rows[sp])], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': flat[sw]['pointer']}]})
        for name, row in rows.items():
            if name in paired:
                continue
            ident = (label['method'], label['path'], f'body:{plain(name)}')
            field = flat.get(name)
            if field is None:
                self.add(ident + ('missing-in-swagger',), operation=label, element=f'body {name}', kind='missing-in-swagger', severity='Media',
                         sparx={'text': f'Documenta el campo "{name}" (requerido: {row.get("required") or "no indicado"}, tipo: {row.get("type") or "no indicado"}).'},
                         swagger={'text': f'El esquema del request no contiene "{name}".'}, inconsistency='El campo documentado en Sparx no existe en el request de Swagger.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, activity, row)], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': f'#/operations/{index}/requestBody'}]})
                continue
            self.compare_requirement(label, 'body', name, row, field['required'], self.request_min_properties(spec_op), self.sparx_evidence(sparx_op, activity, row), field['pointer'], f'#/operations/{index}/requestBody', ident)
            fs, fw = family(row.get('type')), family(field['type'], field['format'])
            if fs and fw and fs != fw:
                self.add(ident + ('type-or-structure-difference',), operation=label, element=f'body {name}', kind='type-or-structure-difference', severity='Media',
                         sparx={'text': f'Tipo: {row.get("type")}.'}, swagger={'text': f'type: {field["type"]}.'}, inconsistency='El tipo del campo difiere entre Sparx y Swagger.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, activity, row)], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': field['pointer']}]})
        for name, field in flat.items():
            if name in rows or name in paired or field['type'] in ('object', 'array'):
                continue
            self.add((label['method'], label['path'], f'body:{plain(name)}', 'missing-in-sparx'), operation=label, element=f'body {name}', kind='missing-in-sparx',
                     severity='Media' if field['required'] else 'Baja', sparx={'text': f'La tabla Body no lista "{name}".'},
                     swagger={'text': f'Declara "{name}" (required: {str(field["required"]).lower()}).'}, inconsistency='El campo del request de Swagger no esta documentado en Sparx.',
                     evidence={'sparx': [self.sparx_evidence(sparx_op, activity, extra={'section': 'Body'})], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': field['pointer']}]})

    # ------------------------------------------------------------------ mappings
    def compare_inputs(self, index, label, sparx_op, section, parameters, spec_op):
        activity, block = section
        known = {'queryparam': 'query', 'query': 'query', 'pathparam': 'path', 'path': 'path', 'header': 'header', 'headerrequest': 'header'}
        body_flat = self.request_schema(spec_op, index)
        for row in block.get('rows') or []:
            origin, name = plain(row.get('origin')), str(row.get('input') or '').strip()
            if origin == 'request':
                origin = 'body'
            if not name or origin not in known and origin not in ('body', 'requestbody'):
                if name:
                    self.cant_verify(label, f'INPUT {name}', f'Origen "{row.get("origin")}" no comparable con Swagger.', 'fuente-no-comparable')
                continue
            if origin in ('body', 'requestbody'):
                exists = name in body_flat
                pointer = f'#/operations/{index}/requestBody'
            else:
                exists = any(p['name'] == name for p in parameters.get(known[origin]) or [])
                pointer = f'#/operations/{index}/parameters/{known[origin]}'
                if not exists and known[origin] == 'header':
                    # An internal name that corresponds to a header documented in the Sparx HeaderRequest table (x-user-id ~ userId): the
                    # evidence is that table row; the header itself is compared by compare_parameters, so this mapping is not a missing input.
                    wanted = header_key(name)
                    counterparts = [str(r.get('headerrequest') or '').strip() for r in getattr(self, '_header_rows', []) if header_key(r.get('headerrequest')) == wanted]
                    if len(counterparts) == 1:
                        exists = True
            if not exists:
                self.add((label['method'], label['path'], f'input:{plain(name)}', 'missing-in-swagger'), operation=label, element=f'INPUT {name}', kind='missing-in-swagger', severity='Media',
                         sparx={'text': f'El mapping INPUT usa "{name}" con origen {row.get("origin")} hacia {row.get("destination")}.'},
                         swagger={'text': f'No existe "{name}" en {origin}.'}, inconsistency='El mapping INPUT de Sparx referencia una entrada que Swagger no declara.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, activity, row)], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': pointer}]})

    def compare_outputs(self, index, label, spec_op, sparx_op, section):
        activity, block = section
        success = next((c for c in sorted(spec_op.get('responses') or {}) if str(c).startswith('2')), None)
        if success is None:
            self.cant_verify(label, 'OUTPUT', 'Swagger no declara respuesta 2xx.', 'fuente-no-comparable')
            return
        content = (spec_op['responses'][success].get('content') or {})
        flat = {}
        for media, node in content.items():
            flat = flatten_schema(node.get('schema'), f'#/operations/{index}/responses/{success}/content/{esc(media)}/schema')
            break
        destinations = set()
        for row in block.get('rows') or []:
            destination = str(row.get('destination') or '').strip()
            if not destination:
                continue
            destinations.add(destination)
            field = flat.get(destination)
            ident = (label['method'], label['path'], f'output:{plain(destination)}')
            if field is None:
                self.add(ident + ('missing-in-swagger',), operation=label, element=f'OUTPUT {destination}', kind='missing-in-swagger', severity='Media',
                         sparx={'text': f'El mapping OUTPUT {row.get("output")} se entrega en "{destination}" (tipo {row.get("type") or "no indicado"}).'},
                         swagger={'text': f'La respuesta {success} no contiene "{destination}".'}, inconsistency='El destino del mapping OUTPUT no existe en la respuesta de Swagger.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, activity, row)], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': f'#/operations/{index}/responses/{success}'}]})
                continue
            fs, fw = family(row.get('type')), family(field['type'], field['format'])
            if fs and fw and fs != fw:
                # The OUTPUT "Tipo" column types the SELECT source column, not the response contract: not a Sparx/Swagger contradiction.
                self.cant_verify(label, f'Tipo de OUTPUT {destination}', f'La columna de origen {row.get("output")} figura como {row.get("type")} y el campo de respuesta de Swagger es {field["type"]}; '
                                 'el tipo del mapping describe el origen de datos, no el contrato de respuesta.', 'fuente-no-comparable')
        for name, field in flat.items():
            if name in destinations or field['type'] in ('object', 'array') or name in ('code', 'message'):
                continue
            if any(d.startswith(name + '.') or d.startswith(name + '[]') for d in destinations):
                continue
            self.add((label['method'], label['path'], f'output:{plain(name)}', 'missing-in-sparx'), operation=label, element=f'response {name}', kind='missing-in-sparx', severity='Baja',
                     sparx={'text': f'Ningun mapping OUTPUT entrega "{name}".'}, swagger={'text': f'La respuesta {success} declara "{name}".'},
                     inconsistency='El campo de respuesta de Swagger no tiene mapping OUTPUT en Sparx.',
                     evidence={'sparx': [self.sparx_evidence(sparx_op, activity, extra={'section': 'OUTPUT'})], 'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': field['pointer']}]})

    def compare_status_codes(self, index, label, spec_op, sparx_op):
        sparx_codes = {str(e.get('label')).strip(): e for e in sparx_op.get('endEvents') or [] if re.fullmatch(r'\d{3}', str(e.get('label')).strip())}
        if not sparx_codes:
            self.cant_verify(label, 'Códigos HTTP', 'Sparx no expone eventos de fin con código HTTP para la operación.')
            return
        swagger_codes = {str(c): c for c in (spec_op.get('responses') or {}) if re.fullmatch(r'\d{3}', str(c))}
        for code, event in sparx_codes.items():
            if code not in swagger_codes:
                self.add((label['method'], label['path'], f'status:{code}', 'missing-in-swagger'), operation=label, element=f'HTTP {code}', kind='http-status-difference', severity='Media',
                         sparx={'text': f'El proceso termina con {code}.'}, swagger={'text': f'No declara respuesta {code}.'}, inconsistency='Codigo HTTP del proceso Sparx ausente en Swagger.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, element=f'Evento de fin {code}', extra={'guid': event.get('guid'), 'page': event.get('page')})],
                                   'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': f'#/operations/{index}/responses'}]})
        for code in swagger_codes:
            if code not in sparx_codes:
                self.add((label['method'], label['path'], f'status:{code}', 'missing-in-sparx'), operation=label, element=f'HTTP {code}', kind='http-status-difference',
                         severity='Media' if code.startswith('4') else 'Baja', sparx={'text': f'Ningun evento de fin del proceso es {code}.'},
                         swagger={'text': f'Declara la respuesta {code}.'}, inconsistency='Codigo HTTP de Swagger ausente en el proceso Sparx.',
                         evidence={'sparx': [self.sparx_evidence(sparx_op, element='Eventos de fin del proceso')],
                                   'swagger': [{'method': label['method'], 'path': label['path'], 'pointer': f'#/operations/{index}/responses/{code}'}]})

    # ------------------------------------------------------------------ supplemental (agent-authored) findings
    def merge_supplemental(self, supplemental: dict):
        """Semantic findings written by the agent after reading CONSIDERACIONES/prose. Rejected unless fully evidenced and correctly classified."""
        for number, item in enumerate((supplemental or {}).get('findings') or [], 1):
            problems = [f for f in REQUIRED_FINDING_FIELDS if not item.get(f)]
            evidence = item.get('evidence') or {}
            if not (evidence.get('sparx') and evidence.get('swagger')):
                problems.append('evidence on both sources')
            if item.get('severity') not in SEVERITIES:
                problems.append('severity')
            if item.get('kind') not in KINDS:
                problems.append('kind')
            if item.get('category') not in CATEGORIES:
                problems.append('category (contradiccion-verificada | diferencia-documental)')
            op = item.get('operation') or {}
            if problems:
                self.cant_verify(op, f'Hallazgo suplementario #{number} rechazado', 'Incompleto: ' + ', '.join(problems) + '.')
                continue
            if item.get('elementClass') in RESPONSIBILITY_CLASSES and item['category'] == 'diferencia-documental':
                self.discard(op, item['element'], f'Diferencia de responsabilidades entre fuentes ({item["elementClass"]}); la ausencia en la otra fuente no es una inconsistencia.')
                continue
            if item['category'] == 'contradiccion-verificada' and all(NON_NORMATIVE_SWAGGER.search(e.get('pointer', '')) for e in evidence['swagger']):
                self.cant_verify(op, f'Hallazgo suplementario #{number} reclasificado', 'Una contradicción no puede sustentarse solo en ejemplos o descripciones de Swagger; debe registrarse como diferencia documental.')
                continue
            if item['category'] == 'contradiccion-verificada' and item.get('sparxInternal'):
                self.cant_verify(op, item['element'], 'La contradicción es interna a Sparx.', 'contradiccion-interna-sparx')
                continue
            ident = (op.get('method'), op.get('path'), 'supplemental', plain(item['element']), item['kind'])
            self.add(ident, **{k: v for k, v in item.items() if k not in ('key', 'elementClass', 'sparxInternal')})
        for entry in (supplemental or {}).get('unverified') or []:
            try:
                self.cant_verify(entry.get('operation'), entry.get('topic'), entry.get('reason'), entry.get('category'))
            except ValueError as error:
                self.discard(entry.get('operation'), entry.get('topic'), f'Entrada no verificada rechazada: {error}')
        for entry in (supplemental or {}).get('discarded') or []:
            self.discard(entry.get('operation'), entry.get('element'), entry.get('reason'))

    def decision_context(self):
        context = {}
        for decision in self.decisions:
            if not isinstance(decision, dict):
                continue
            ops = decision.get('operations') or decision.get('operationIds') or []
            for op in ops if isinstance(ops, list) else [ops]:
                context.setdefault(str(op), []).append(decision.get('id'))
        return context

    def registry(self):
        context = self.decision_context()
        order = {'GET': 0, 'POST': 1, 'PUT': 2, 'PATCH': 3, 'DELETE': 4}
        items = sorted(self.findings.values(), key=lambda f: (f['operation']['path'], order.get(f['operation']['method'], 9), CATEGORIES.index(f['category']), f['key'][2:] if isinstance(f['key'], tuple) else str(f['key'])))
        findings = []
        for number, item in enumerate(items, 1):
            record = {k: v for k, v in item.items() if k != 'key'}
            record['id'] = f'INC-{number:03d}'
            record['key'] = '|'.join(str(p) for p in item['key'])
            refs = [d for k in (record['operation'].get('operationId'), record['operation']['method'] + ' ' + record['operation']['path']) for d in context.get(str(k), [])]
            if refs:
                record['humanDecisionContext'] = sorted({str(r) for r in refs if r})
            findings.append(record)
        return findings


def load_yaml(path: Path):
    return yaml.safe_load(path.read_bytes())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp_pages(findings, source_root: Path):
    """Record the sha256 of every cited Sparx page at audit time (verified again when the report is validated)."""
    pages = {}
    for finding in findings:
        for evidence in finding['evidence']['sparx']:
            page = evidence.get('page')
            if page and (source_root / page).is_file():
                evidence['pageSha256'] = currency.sha(source_root / page)
                pages[page] = evidence['pageSha256']
    return pages


def build_registry(service, openapi_path, detail_path, authority_path, output, supplemental_path=None, decisions_path=None, snapshot_manifest=None, repo=None, workspace=None):
    repo = Path(repo or Path.cwd()).resolve()
    openapi, detail, authority = load_yaml(openapi_path), load_yaml(detail_path), load_yaml(authority_path)
    branch_node = (detail.get('authority') or {}).get('branch') or {}
    if not branch_node:
        raise SystemExit('endpoint detail does not identify the authoritative branch; run the snapshot step first')
    branch_label = f"rama autoritativa {branch_node.get('pagePathPrefix', '')} ({branch_node.get('branchRootId')})"
    # Currency of BOTH sources (Swagger file and Sparx export) and of the snapshot artifacts; stale sources abort the audit.
    manifest = load_yaml(Path(snapshot_manifest)) if snapshot_manifest else None
    if manifest is None:
        raise SystemExit('a snapshot manifest is required to verify source currency; run snapshot_sources.py first')
    if manifest.get('service') != service:
        raise SystemExit(f'snapshot belongs to {manifest.get("service")}, not {service}')
    freshness = currency.verify(manifest, repo, workspace)
    if freshness['status'] != 'current':
        raise SystemExit('stale sources, rerun snapshot_sources.py: ' + ' | '.join(freshness['stale']))
    decisions = []
    if decisions_path and Path(decisions_path).exists():
        raw = load_yaml(Path(decisions_path)) or {}
        decisions = raw.get('decisions') if isinstance(raw, dict) else raw
        decisions = [d for d in (decisions or []) if isinstance(d, dict)]
    methods = sm.collect(authority, repo)
    auditor = Auditor(service, openapi, detail, branch_label, decisions, methods).run()
    supplemental = load_yaml(Path(supplemental_path)) if supplemental_path and Path(supplemental_path).exists() else None
    if supplemental and supplemental.get('service') not in (None, service):
        raise SystemExit(f'supplemental findings belong to {supplemental.get("service")}, not {service}')
    auditor.merge_supplemental(supplemental)
    findings = auditor.registry()
    source_root = repo / manifest['sparx']['root']
    pages = stamp_pages(findings, source_root)
    registry = {
        'schemaVersion': 2, 'kind': 'sparx-swagger-inconsistency-registry', 'service': service,
        'sources': {'openapi': {'path': manifest['openapi']['path'], 'sha256': manifest['openapi']['sha256']}, 'sparxRoot': manifest['sparx']['root'],
                    'sparxAuthoritativeBranch': branch_label, 'endpointDetailSha256': sha(detail_path), 'authoritySha256': sha(authority_path)},
        'sourceCurrency': {'status': freshness['status'], 'verified': ['openapiSourceUnchanged', 'sparxHierarchyUnchanged', 'snapshotArtifactsUnchanged'],
                           'snapshotManifest': Path(snapshot_manifest).as_posix(), 'citedPageHashes': pages},
        'operationsAudited': [{'method': o['method'].upper(), 'path': o['path'], 'operationId': o.get('operationId')} for o in openapi['operations']],
        'findings': findings,
        'unverified': auditor.unverified,
        'discardedCandidates': auditor.discarded,
        'readOnlyAudit': True,
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(yaml.safe_dump(registry, sort_keys=False, allow_unicode=True, width=200), encoding='utf-8')
    return registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', required=True)
    parser.add_argument('--openapi', type=Path, required=True)
    parser.add_argument('--detail', type=Path, required=True)
    parser.add_argument('--authority', type=Path, required=True)
    parser.add_argument('--snapshot-manifest', type=Path, required=True)
    parser.add_argument('--supplemental', type=Path)
    parser.add_argument('--decisions', type=Path, help='Existing reviewed decisions, read only, used as context')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    registry = build_registry(args.service, args.openapi, args.detail, args.authority, args.output, args.supplemental, args.decisions, args.snapshot_manifest)
    print(json.dumps({'service': registry['service'], 'findings': len(registry['findings']), 'unverified': len(registry['unverified']), 'discarded': len(registry['discardedCandidates'])}))


if __name__ == '__main__':
    sys.exit(main())
