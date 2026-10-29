import sys
import tempfile
import unittest
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from generation_context import resolve_context, SelectionError


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = self.root / '.factory/services/alpha'
        self.ws.mkdir(parents=True)
        for name in ('one', 'two'):
            path = self.root / f'archetypes/{name}/v1'
            path.mkdir(parents=True)
            (path / 'archetype.yml').write_text('identity: {}')

    def put(self, name, value):
        (self.ws / name).write_text(yaml.safe_dump(value))

    def resolve(self, **kwargs):
        return resolve_context(self.root, service='alpha', environ={}, **kwargs)

    def test_no_default(self):
        with self.assertRaisesRegex(SelectionError, 'missing-archetype'):
            self.resolve()

    def test_each_archetype_independent(self):
        for name in ('one', 'two'):
            result = self.resolve(explicit=f'archetypes/{name}/v1')
            self.assertEqual(result.archetype.as_posix(), f'archetypes/{name}/v1')
            self.assertEqual(result.output.as_posix(), 'output/alpha')

    def test_resume_uses_checkpoint(self):
        self.put('service-generation-state.yml', {'targetService': 'alpha', 'archetype': {'path': 'archetypes/two/v1'}})
        self.assertEqual(self.resolve().archetype.as_posix(), 'archetypes/two/v1')
        with self.assertRaisesRegex(SelectionError, 'archetype-selection-conflict'):
            self.resolve(explicit='archetypes/one/v1')

    def test_environment_cannot_override_checkpoint(self):
        self.put('service-generation-state.yml', {'archetype': {'path': 'archetypes/two/v1'}})
        with self.assertRaisesRegex(SelectionError, 'archetype-selection-conflict'):
            resolve_context(self.root, service='alpha', environ={'SERVICE_ARCHETYPE_PATH': 'archetypes/one/v1'})

    def test_plan_conflict(self):
        self.put('implementation-plan.yml', {'inputs': {'archetype': {'path': 'archetypes/two/v1'}}})
        with self.assertRaisesRegex(SelectionError, 'archetype-selection-conflict'):
            self.resolve(explicit='archetypes/one/v1')

    def test_cross_service_rejected(self):
        self.put('service-spec.yml', {'service': {'name': 'beta'}})
        with self.assertRaisesRegex(SelectionError, 'target-selection-conflict'):
            self.resolve(explicit='archetypes/one/v1')

    def test_duplicate_yaml_rejected(self):
        (self.ws / 'service-generation-state.yml').write_text('targetService: alpha\ntargetService: beta\n')
        with self.assertRaisesRegex(SelectionError, 'duplicate-selection-key'):
            self.resolve(explicit='archetypes/one/v1')

    def test_unknown_migration_stays_unknown(self):
        self.put('service-generation-state.yml', {'archetype': {'path': None, 'status': 'unknown-requires-selection'}})
        with self.assertRaisesRegex(SelectionError, 'missing-archetype'):
            self.resolve()

    def test_traversal_and_output_conflict(self):
        with self.assertRaisesRegex(SelectionError, 'invalid-archetype-path'):
            self.resolve(explicit='archetypes/../other/v1')
        self.put('implementation-plan.yml', {'service': {'name': 'alpha', 'outputDirectory': 'output/beta'}})
        with self.assertRaisesRegex(SelectionError, 'output-selection-conflict'):
            self.resolve(explicit='archetypes/one/v1')

    def test_legacy_root_not_used(self):
        with self.assertRaisesRegex(SelectionError, 'service-workspace-required'):
            resolve_context(self.root, explicit='archetypes/one/v1', environ={})

    def test_import_does_not_select(self):
        scripts = Path(__file__).resolve().parents[2] / 'plan-service-implementation/scripts'
        sys.path.insert(0, str(scripts))
        import build_implementation_plan as planner
        self.assertFalse(hasattr(planner, 'ARCHETYPE_ROOT'))
