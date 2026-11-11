"""Invocation-local YAML parsing reuse, never a cache of filesystem currency or authority.

Callers still read live bytes and recompute their gates and hashes. Parsed values
are returned as independent copies; nothing survives the outer read session.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
import yaml

MAX_ENTRIES = 32
MAX_BYTES = 8 * 1024 * 1024
_session = ContextVar('artifact_read_session', default=None)
SafeLoader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)


class DuplicateKeyError(yaml.YAMLError):
    pass


class UniqueLoader(SafeLoader):
    pass


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise DuplicateKeyError(str(key))
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


@contextmanager
def read_session():
    """Nested scopes share parsing only; separate runs never share verdicts/data."""
    current = _session.get()
    if current is not None:
        yield current
        return
    current = {'entries': OrderedDict(), 'bytes': 0, 'parses': 0, 'hits': 0,
               'prepared': {}, 'preparedHits': 0}
    token = _session.set(current)
    try:
        yield current
    finally:
        current['entries'].clear()
        current['prepared'].clear()
        _session.reset(token)


def read_scoped(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with read_session():
            return function(*args, **kwargs)
    return wrapped


def load_yaml(data, *, reject_duplicates=False):
    """Safe YAML from supplied live bytes. No paths, stat cache or approvals."""
    raw = data.encode('utf-8') if isinstance(data, str) else data
    state = _session.get()
    key = (reject_duplicates, hashlib.sha256(raw).digest()) if state is not None else None
    if state is not None and key in state['entries']:
        state['hits'] += 1
        state['entries'].move_to_end(key)
        return deepcopy(state['entries'][key][0])
    value = yaml.load(raw, Loader=UniqueLoader if reject_duplicates else SafeLoader)
    if state is not None:
        state['parses'] += 1
        if len(raw) <= MAX_BYTES:
            while state['entries'] and (len(state['entries']) >= MAX_ENTRIES
                                       or state['bytes'] + len(raw) > MAX_BYTES):
                _, (_, size) = state['entries'].popitem(last=False)
                state['bytes'] -= size
            state['entries'][key] = (deepcopy(value), len(raw))
            state['bytes'] += len(raw)
    return value


def reuse_preparation(namespace, fingerprint, build):
    """One last pure result per namespace, valid only for freshly hashed inputs.

    Never use this for gates, reviews, file protection or publication. The caller
    must read and hash current dependencies BEFORE supplying the fingerprint.
    """
    state = _session.get()
    if state is None:
        return build()
    prior = state['prepared'].get(namespace)
    if prior is not None and prior[0] == fingerprint:
        state['preparedHits'] += 1
        return deepcopy(prior[1])
    value = build()
    state['prepared'][namespace] = (fingerprint, deepcopy(value))
    return value
