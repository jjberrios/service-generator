"""Regression tests for the issues found by the official Maven validation (RedundantImport, Indentation, unused validator helpers)."""
import copy
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))

import synth as fx  # noqa: E402
import full_materializer as mz  # noqa: E402
import service_model as sm  # noqa: E402
import workspace as wsm  # noqa: E402
import java_components as jc  # noqa: E402
import java_components2 as jc2  # noqa: E402
import style_lint  # noqa: E402
from test_generated_tests import Base  # noqa: E402


def helpers_of(text):
    return set(re.findall(r'private static [\w<>]+(?: <T>)? ?[\w<>]* (\w+)\(', text)) | set(re.findall(r'private static <T> \w+<T> (\w+)\(', text))


class ImportTests(unittest.TestCase):
    def test_same_package_imports_are_removed_but_other_imports_stay(self):
        text = 'package a.b;\n\nimport a.b.Other;\nimport a.b.sub.Deep;\nimport a.c.Foo;\nimport static a.b.Other.CONST;\n\nclass T {\n    Other o; Deep d; Foo f; int x = CONST;\n}\n'
        out = jc.prune_imports(text)
        self.assertNotIn('import a.b.Other;', out)
        for kept in ('import a.b.sub.Deep;', 'import a.c.Foo;', 'import static a.b.Other.CONST;'):
            self.assertIn(kept, out)

    def test_no_generated_file_imports_its_own_package(self):
        for name in fx.SERVICES:
            out = self.generated(name)
            for f in out.rglob('*.java'):
                text = f.read_text(encoding='utf-8')
                own = re.search(r'^package ([\w.]+);', text, re.M).group(1)
                for imported in re.findall(r'^import ([\w.]+)\.[A-Z]\w*;', text, re.M):
                    self.assertNotEqual(imported, own, f.name)

    def generated(self, name):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo = fx.make_repo(Path(self.tmp.name))
        fx.ready_service(repo, name)
        mz.materialize(repo, name)
        return repo / 'output' / name


class LintDetectionTests(unittest.TestCase):
    def rules(self, text):
        return [(f['rule'], f['line']) for f in style_lint.lint_text('T.java', text)]

    def test_the_linter_detects_a_same_package_import(self):
        self.assertIn(('RedundantImport', 3), self.rules('package a.b;\n\nimport a.b.Other;\n\nclass T {\n    Other o;\n}\n'))

    def test_the_linter_ignores_static_nested_and_foreign_imports(self):
        text = 'package a.b;\n\nimport a.c.Foo;\nimport static a.b.Other.CONST;\nimport a.b.Outer.Inner;\n\nclass T {\n    Foo f; Inner i; int x = CONST;\n}\n'
        self.assertNotIn('RedundantImport', [r for r, _ in self.rules(text)])

    def test_the_linter_detects_a_misindented_first_statement(self):
        bad = 'package a;\n\nclass T {\n    void x() {\n                int a = 1;\n    }\n}\n'
        self.assertIn(('Indentation', 5), self.rules(bad))
        self.assertEqual([r for r in self.rules(bad.replace('                int', '        int')) if r[0] == 'Indentation'], [])

    def test_the_linter_accepts_nested_blocks_and_empty_bodies(self):
        text = 'package a;\n\nclass T {\n    void x() {\n    }\n\n    void y() {\n        if (true) {\n            return;\n        }\n    }\n}\n'
        self.assertEqual([r for r in self.rules(text) if r[0] == 'Indentation'], [])


class GeneratedIndentationTests(Base):
    def test_every_generated_method_body_starts_one_level_deeper_in_main_and_test(self):
        for name in fx.SERVICES:
            out = self.gen(name)
            report = style_lint.lint_project(out)
            self.assertEqual([f for f in report['findings'] if f['rule'] in ('Indentation', 'RedundantImport')], [])
            self.assertTrue(any('src/test/java' in str(s) for s in report['sourceSets']))

    def test_exception_translation_tests_have_regular_indentation(self):
        out = self.gen('inventory-service')
        text = (out / 'src/test/java/com/acme/inventory/core/service/impl/ItemServiceImplTest.java').read_text(encoding='utf-8')
        i = text.index('void createItemTranslatesAUniqueConstraintViolationTo409()')
        first = text[i:].split('\n')[1]
        self.assertEqual(len(first) - len(first.lstrip()), 8)


class ConditionalHelperTests(Base):
    def validator(self, name):
        out = self.gen(name)
        return next(out.rglob('*Validator.java')).read_text(encoding='utf-8')

    def test_a_service_with_patch_integers_and_enums_keeps_every_helper_it_uses(self):
        text = self.validator('inventory-service')
        self.assertEqual(helpers_of(text), {'supplied', 'field', 'toLong', 'toInteger', 'toDecimal', 'toBoundedDecimal', 'oneOf'})
        self.assertIn('record Field<T>', text)

    def test_a_service_without_patch_enums_or_integers_emits_only_what_it_calls(self):
        text = self.validator('billing-service')
        self.assertEqual(helpers_of(text), {'supplied', 'toDecimal', 'toBoundedDecimal'})
        for gone in ('Field<', 'toLong', 'toInteger', 'oneOf', 'Supplier', 'Set<'):
            self.assertNotIn(gone, text)

    def test_every_emitted_helper_is_called_somewhere_in_the_class(self):
        for name in fx.SERVICES:
            text = self.validator(name)
            for helper in helpers_of(text):
                calls = len(re.findall(r'\b' + helper + r'\(', text))
                self.assertGreaterEqual(calls, 2, f'{name}: {helper} is declared but never called')       # declaration + at least one call

    def model(self, name):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = fx.make_repo(Path(tmp.name))
        fx.ready_service(repo, name)
        plan, _ = mz.load_plan(wsm.Workspace(repo, name), repo)
        return sm.build(plan)

    def render(self, model):
        return jc2.validator(model, model['paths']['business-validator'])

    def test_helpers_follow_the_operations_present_in_the_plan_model(self):
        base = self.model('inventory-service')
        no_update = copy.deepcopy(base)
        no_update['ops'] = [o for o in no_update['ops'] if o['kind'] != 'update']
        text = self.render(no_update)
        self.assertNotIn('Field<', text)
        self.assertNotIn('field(', text)
        no_select = copy.deepcopy(base)
        no_select['ops'] = [o for o in no_select['ops'] if o['kind'] != 'select']
        self.assertNotIn('supplied(', self.render(no_select).replace('supplied.', ''))

    def test_numeric_helpers_follow_the_declared_types(self):
        base = self.model('inventory-service')
        only_text = copy.deepcopy(base)
        for op in only_text['ops']:
            op['fields'] = [f for f in op.get('fields', []) if f['type'] == 'String']
            if op['kind'] == 'select':
                op['filters'] = [f for f in op['filters'] if f['type'] == 'String']
                op['params']['query'] = [p for p in op['params']['query'] if p['java'] in {f['param'] for f in op['filters']} or p['java'] in (op['page'] or [])]
        text = self.render(only_text)
        for gone in ('toInteger', 'toDecimal', 'toBoundedDecimal', 'oneOf'):
            self.assertNotIn(gone, text)
        self.assertIn('toLong', text)                       # the PATCH path identifier is still a Long
        without_update = copy.deepcopy(only_text)
        without_update['ops'] = [o for o in without_update['ops'] if o['kind'] != 'update']
        self.assertNotIn('toLong', self.render(without_update))

    def test_enum_helper_exists_only_with_enum_fields(self):
        base = self.model('inventory-service')
        plain = copy.deepcopy(base)
        for op in plain['ops']:
            for f in op.get('fields', []):
                f['enum'] = None
        self.assertNotIn('oneOf', self.render(plain))
        self.assertIn('oneOf', self.render(base))

    def test_the_billing_validator_has_no_dead_instructions_left_for_jacoco(self):
        text = self.validator('billing-service')
        declared = helpers_of(text)
        called = {h for h in declared if len(re.findall(r'\b' + h + r'\(', text)) >= 2}
        self.assertEqual(declared, called)


class PipelineProtectionTests(Base):
    def test_output_is_deterministic_and_idempotent_with_the_new_renderers(self):
        out = self.gen('billing-service')
        first = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob('*.java')}
        again = mz.materialize(self.repo, 'billing-service')
        self.assertEqual(again['written'], [])
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = fx.make_repo(Path(tmp))
            fx.ready_service(repo, 'billing-service')
            mz.materialize(repo, 'billing-service')
            other = repo / 'output' / 'billing-service'
            self.assertEqual(first, {p.relative_to(other).as_posix(): p.read_bytes() for p in other.rglob('*.java')})

    def test_blocked_gate_still_writes_nothing(self):
        fx.blocked_gate(self.repo, 'billing-service', fx.SERVICES['billing-service']['route'])
        fx.make_plan(self.repo, 'billing-service')
        with self.assertRaises(Exception):
            mz.materialize(self.repo, 'billing-service')
        self.assertFalse((self.repo / 'output' / 'billing-service').exists())

    def test_manual_files_are_still_protected(self):
        out = self.gen('billing-service')
        target = next(out.rglob('InvoiceValidator.java'))
        target.write_text(target.read_text(encoding='utf-8') + '\n// manual\n', encoding='utf-8')
        with self.assertRaises(mz.MaterializationError) as caught:
            mz.materialize(self.repo, 'billing-service')
        self.assertEqual(caught.exception.kind, 'protected-files')


if __name__ == '__main__':
    unittest.main()
