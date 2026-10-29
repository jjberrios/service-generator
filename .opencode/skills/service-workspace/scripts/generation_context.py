"""Runtime selection shared by pipeline entry points; no implicit baseline."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import os
import re
import yaml


class SelectionError(ValueError):
    pass


def load_mapping(path):
    path = Path(path)
    if not path.exists():
        return {}
    if path.is_symlink():
        raise SelectionError(f"unsafe-selection-input: {path}")
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if key in result:
                raise SelectionError(f"duplicate-selection-key: {key} in {path}")
            result[key] = loader.construct_object(value_node)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        value = yaml.load(path.read_bytes(), Loader=UniqueLoader)
    except yaml.YAMLError as error:
        raise SelectionError(f'invalid-selection-yaml: {path}') from error
    if not isinstance(value, dict):
        raise SelectionError(f"invalid-selection-document: {path}")
    return value


def normalized(value):
    if not isinstance(value, str) or '\\' in value:
        raise SelectionError('invalid-archetype-path')
    path = PurePosixPath(value)
    if path.name == 'archetype.yml':
        path = path.parent
    if path.is_absolute() or '..' in path.parts or len(path.parts) != 3 or path.parts[0] != 'archetypes':
        raise SelectionError(f"invalid-archetype-path: {value}")
    return path.as_posix()


@dataclass(frozen=True)
class GenerationContext:
    root: Path
    workspace: Path
    service: str | None
    archetype: Path
    selection_sources: tuple

    @property
    def output(self):
        if not self.service:
            raise SelectionError('missing-target-service')
        return Path('output') / self.service


def dig(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def resolve_context(root, *, workspace=None, service=None, explicit=None, environ=None):
    root = Path(root).resolve()
    if service and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', service):
        raise SelectionError('invalid-target-service')
    ws = Path(workspace) if workspace else root / '.factory' / 'services' / service if service else root / '.factory'
    if not ws.is_absolute():
        ws = root / ws
    if not ws.resolve().is_relative_to((root / '.factory').resolve()):
        raise SelectionError('workspace-outside-factory')
    state = load_mapping(ws / 'service-generation-state.yml')
    plan = load_mapping(ws / 'implementation-plan.yml')
    cfg = load_mapping(ws / 'full-planning-input.yml')
    spec = load_mapping(ws / 'service-spec.yml')
    params = load_mapping(ws / 'generation-parameters.yml')
    params_service = dig(params, 'service')
    if isinstance(params_service, dict):
        params_service = params_service.get('name')
    targets = [v for v in (service, dig(state, 'targetService'), dig(plan, 'service', 'name'),
                          dig(cfg, 'target', 'service'), dig(spec, 'service', 'name'), params_service) if v]
    if len(set(targets)) > 1:
        raise SelectionError(f"target-selection-conflict: {targets}")
    target = targets[0] if targets else None
    if target and not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', target):
        raise SelectionError('invalid-target-service')
    if ws.parent == root / '.factory/services' and target and ws.name != target:
        raise SelectionError('workspace-target-conflict')
    if ws == root / '.factory' and (ws / 'services').is_dir():
        raise SelectionError('service-workspace-required: legacy root is not a generation context')
    env = os.environ if environ is None else environ
    choices = {'explicit': explicit, 'environment': env.get('SERVICE_ARCHETYPE_PATH'),
               'checkpoint': dig(state, 'archetype', 'path'),
               'plan': dig(plan, 'inputs', 'archetype', 'path'),
               'parameters': dig(params, 'inputs', 'archetype', 'path'),
               'planning-input': dig(cfg, 'target', 'archetype')}
    choices = {k: normalized(v) for k, v in choices.items() if v}
    if not choices:
        raise SelectionError('missing-archetype-selection: select a version explicitly')
    if len(set(choices.values())) != 1:
        raise SelectionError(f"archetype-selection-conflict: {choices}")
    selected = Path(next(iter(choices.values())))
    base = (root / 'archetypes').resolve()
    actual = root / selected
    if not actual.resolve().is_relative_to(base) or actual.is_symlink() or not (actual / 'archetype.yml').is_file():
        raise SelectionError(f"missing-or-unsafe-archetype: {selected}")
    for key in ('outputDirectory',):
        value = dig(plan, 'service', key)
        if value and target and value.rstrip('/') != f'output/{target}':
            raise SelectionError('output-selection-conflict')
    value = dig(cfg, 'target', 'output_directory')
    if value and target and value.rstrip('/') != f'output/{target}':
        raise SelectionError('output-selection-conflict')
    return GenerationContext(root, ws.resolve(), target, selected, tuple(choices))


def resolve_archetype(root, **kwargs):
    return resolve_context(root, **kwargs).archetype
