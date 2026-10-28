"""Generic validator and preventive style lint tests (synthetic services; no fixed class names or counts)."""
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synth as fx
import full_materializer as mz
import validate_generated_service as vg
import style_lint as sl
import gate_guard  # noqa: F401  (imported to prove the guard module loads alongside the validator)


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = fx.make_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def generate(self, name, **kwargs):
        fx.ready_service(self.repo, name, **kwargs)
        mz.materialize(self.repo, name)
        return self.repo / 'output' / name

    def failed(self, name):
        return sorted(v['check'] for v in vg.validate(self.repo, name)['violations'])

    def test_it_passes_for_different_synthetic_services_without_fixed_names_or_counts(self):
        for name in fx.SERVICES:
            self.generate(name)
            result = vg.validate(self.repo, name)
            self.assertEqual(result['status'], 'passed', result['violations'])
            self.assertEqual(result['gate'], 'CLEARED')
        self.assertNotEqual(len(vg.validate(self.repo, 'inventory-service')['checks']), 0)
        source = (HERE.parent / 'scripts' / 'validate_generated_service.py').read_text(encoding='utf-8')
        for fixed in ('MailingInfo', 'mailing', 'Mailing'):
            self.assertNotIn(fixed, source)

    def test_it_never_claims_the_official_checkstyle_gate_and_reports_the_preventive_lint_separately(self):
        self.generate('inventory-service')
        result = vg.validate(self.repo, 'inventory-service')
        self.assertEqual(result['checkstyleOfficial'], 'unverified')
        self.assertEqual(result['preventiveStyleLint']['preventiveResult'], 'clean')
        self.assertFalse(result['applicationPropertiesRead'])

    def test_missing_modified_unplanned_and_misplaced_files_are_detected(self):
        out = self.generate('inventory-service')
        base = out / 'src/main/java/com/acme/inventory/core'
        (base / 'repository/ItemRepository.java').unlink()
        self.assertIn('plannedFilesPresent', self.failed('inventory-service'))
        self.generate('inventory-service')
        (base / 'model/ItemEntity.java').write_text((base / 'model/ItemEntity.java').read_text(encoding='utf-8') + '\n// edit\n', encoding='utf-8')
        self.assertIn('manifestRowsMatchDisk', self.failed('inventory-service'))
        (base / 'model/ItemEntity.java').write_text('x', encoding='utf-8')
        (base / 'extra').mkdir()
        (base / 'extra/Rogue.java').write_text('package com.acme.inventory.core.extra;\npublic class Rogue {\n}\n', encoding='utf-8')
        failed = self.failed('inventory-service')
        self.assertIn('noUnplannedJava', failed)
        self.assertIn('javaStructure', failed)

    def test_structure_problems_package_type_braces_and_imports(self):
        problems = vg.java_structure('src/main/java/com/acme/x/Foo.java', 'package com.other;\nimport java.util.*;\nimport java.util.List;\nimport java.util.List;\npublic class Bar {\n')
        joined = ' '.join(problems)
        for expected in ('does not match the path', 'no type named Foo', 'unbalanced braces', 'star import', 'duplicate import'):
            self.assertIn(expected, joined)
        self.assertEqual(vg.java_structure('src/main/java/com/acme/x/Foo.java', 'package com.acme.x;\n\npublic record Foo(String a) {\n}\n'), [])

    def test_planned_jpa_components_and_logging_components_must_match_the_plan(self):
        out = self.generate('billing-service')
        entity = out / 'src/main/java/org/example/billing/model/InvoiceEntity.java'
        entity.write_text(entity.read_text(encoding='utf-8').replace('@Column(name = "TOTAL")', '@Column(name = "OTHER")'), encoding='utf-8')
        self.assertIn('jpaEntity:src/main/java/org/example/billing/model/InvoiceEntity.java', self.failed('billing-service'))
        out = self.generate('inventory-service')
        logger = out / 'src/main/java/com/acme/inventory/core/utils/ActivityLogger.java'
        logger.write_text(logger.read_text(encoding='utf-8').replace('logContenido', 'logOther'), encoding='utf-8')
        self.assertIn('activityLogger:src/main/java/com/acme/inventory/core/utils/ActivityLogger.java', self.failed('inventory-service'))

    def test_a_plan_or_spec_changed_after_generation_is_detected(self):
        self.generate('inventory-service')
        spec = self.repo / '.factory/services/inventory-service/service-spec.yml'
        spec.write_text(spec.read_text(encoding='utf-8') + '\n# changed\n', encoding='utf-8')
        self.assertIn('manifestInputsCurrent', self.failed('inventory-service'))

    def test_inactive_operations_must_not_appear_in_generated_java(self):
        out = self.generate('inventory-service')
        extra = out / 'src/main/java/com/acme/inventory/core/utils/ConstanApi.java'
        extra.write_text(extra.read_text(encoding='utf-8').replace('private ConstanApi', '// @GetMapping(path = "/api/v1/items/{id}")\n    private ConstanApi', 1), encoding='utf-8')
        failed = self.failed('inventory-service')
        self.assertIn('inactiveOperationsNotGenerated', failed)

    def test_java_present_while_the_gate_is_not_cleared_is_a_violation(self):
        self.generate('inventory-service')
        fx.wfx.make_service(self.repo, 'inventory-service', path='/api/v1/items', sparx_required='Si')         # a new contradiction appears after generation
        ws = fx.wsm.Workspace(self.repo, 'inventory-service')
        fx.wfx.review(ws.dir)
        result = vg.validate(self.repo, 'inventory-service')
        self.assertNotEqual(result['gate'], 'CLEARED')
        self.assertIn('javaOnlyWhileGateCleared', [v['check'] for v in result['violations']])

    def test_direct_agent_writes_are_detected_as_unplanned_or_untracked_java(self):
        out = self.generate('inventory-service')
        direct = out / 'src/main/java/com/acme/inventory/core/service/HandWritten.java'
        direct.parent.mkdir(parents=True, exist_ok=True)
        direct.write_text('package com.acme.inventory.core.service;\n\npublic class HandWritten {\n}\n', encoding='utf-8')
        self.assertIn('noUnplannedJava', self.failed('inventory-service'))

    def test_partial_runs_are_validated_against_the_supported_subset_and_flagged_incomplete(self):
        fx.ready_service(self.repo, 'inventory-service', with_unsupported=True)
        mz.materialize(self.repo, 'inventory-service', supported_only=True)
        result = vg.validate(self.repo, 'inventory-service')
        self.assertEqual(result['status'], 'passed', result['violations'])
        self.assertFalse(result['complete'])

    def test_application_properties_is_neither_read_nor_reported(self):
        out = self.generate('inventory-service')
        props = out / 'src/main/resources/application.properties'
        props.parent.mkdir(parents=True, exist_ok=True)
        props.write_text('spring.datasource.password=secret-local\n', encoding='utf-8')
        before = props.read_bytes()
        result = vg.validate(self.repo, 'inventory-service')
        self.assertNotIn('secret-local', yaml.safe_dump(result))
        self.assertEqual(props.read_bytes(), before)


CLEAN = textwrap.dedent('''\
    package a.b;

    import java.util.List;

    public class Clean {
        private static final int PAGE = 20;

        @Operation(responses = {
          @Response(code = 200),
          @Response(code = 404)
        })
        public int run(List<String> values) {
            int total = 0;
            for (String value : values) {
                total += value.length();
            }
            if (total > PAGE) {
                return 1;
            }
            return total;
        }
    }
''')


class StyleLintTests(unittest.TestCase):
    def rules(self, text, ignore=None):
        return sorted({f['rule'] for f in sl.lint_text('src/main/java/a/b/Clean.java', text, ignore)})

    def test_clean_code_has_no_findings(self):
        self.assertEqual(sl.lint_text('f.java', CLEAN), [])

    def test_annotation_array_indentation_follows_array_init_indent_not_generic_style(self):
        bad = CLEAN.replace('      @Response(code = 200),', '        @Response(code = 200),')
        findings = sl.lint_text('f.java', bad)
        self.assertEqual([f['rule'] for f in findings], ['Indentation'])
        self.assertIn('expected 6 or 12', findings[0]['message'])
        wrapped = CLEAN.replace('      @Response(code = 200),', '            @Response(code = 200),').replace('      @Response(code = 404)', '            @Response(code = 404)')
        self.assertEqual(sl.lint_text('f.java', wrapped), [])            # line-wrap indentation (+8) is also accepted

    def test_magic_numbers_are_flagged_outside_constants_and_respect_the_configured_ignore_list(self):
        text = CLEAN.replace('if (total > PAGE) {', 'if (total > 20) {').replace('return 1;', 'return 7;')
        found = [f['message'] for f in sl.lint_text('f.java', text) if f['rule'] == 'MagicNumber']
        self.assertEqual(len(found), 2)
        self.assertEqual([f for f in sl.lint_text('f.java', CLEAN.replace('return total;', 'return 404 + 0 + -1;')) if f['rule'] == 'MagicNumber'], [])     # ignored by default list
        self.assertTrue([f for f in sl.lint_text('f.java', 'class A {\n    int x = 7;\n}\n') if f['rule'] == 'MagicNumber'])
        self.assertFalse([f for f in sl.lint_text('f.java', 'class A {\n    String s = "7 and 20"; // 99\n}\n') if f['rule'] == 'MagicNumber'])

    def test_the_magic_number_ignore_list_is_read_from_the_projects_checkstyle_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml = Path(tmp) / 'checkstyle.xml'
            xml.write_text('<module name="Checker"><module name="TreeWalker"><module name="MagicNumber"><property name="ignoreNumbers" value="0, 1, 20"/></module></module></module>', encoding='utf-8')
            ignored = sl.ignored_numbers(xml)
            self.assertIn(20.0, ignored)
            self.assertNotIn(404.0, ignored)
            self.assertEqual(sl.ignored_numbers(Path(tmp) / 'missing.xml'), set(sl.DEFAULT_IGNORED_NUMBERS))

    def test_whitespace_patterns_including_switch_after_a_parenthesis(self):
        for line in ('if(x) {', 'x = foo(switch (a) { default -> 2; });', 'int a=b;', 'if (a==b) {', 'try{', 'if (a&&b) {'):
            body = f'class A {{\n    void m() {{\n        {line}\n    }}\n}}\n'
            self.assertIn('WhitespaceAround', self.rules(body), line)
        self.assertNotIn('WhitespaceAround', self.rules('class A {\n    void m() {\n        String message = switch (a) {\n            default -> "x";\n        };\n    }\n}\n'))

    def test_variable_declaration_usage_distance_matches_the_known_patterns(self):
        far = textwrap.dedent('''\
            class A {
                void m() {
                    Headers headers = build();
                    one();
                    two();
                    three();
                    four();
                    five();
                    use(headers);
                }
            }
        ''')
        findings = [f for f in sl.lint_text('f.java', far) if f['rule'] == 'VariableDeclarationUsageDistance']
        self.assertEqual(len(findings), 1)
        near = far.replace('    Headers headers = build();\n', '').replace('        use(headers);', '        Headers headers = build();\n        use(headers);')
        self.assertEqual([f for f in sl.lint_text('f.java', near) if f['rule'] == 'VariableDeclarationUsageDistance'], [])
        final = far.replace('Headers headers', 'final Headers headers')
        self.assertEqual([f for f in sl.lint_text('f.java', final) if f['rule'] == 'VariableDeclarationUsageDistance'], [])
        nested = far.replace('        use(headers);', '        if (ready) {\n            use(headers);\n        }')
        self.assertEqual([f for f in sl.lint_text('f.java', nested) if f['rule'] == 'VariableDeclarationUsageDistance'], [])        # first use in a nested block is not measured

    def test_other_known_patterns_line_length_imports_and_braces(self):
        self.assertIn('LineLength', self.rules('class A {\n    String s = "' + 'x' * 260 + '";\n}\n'))
        self.assertEqual({f['rule'] for f in sl.lint_text('f.java', 'import java.util.*;\nimport java.util.Map;\nclass A {\n}\n')}, {'AvoidStarImport', 'UnusedImports'})
        self.assertIn('NeedBraces', self.rules('class A {\n    void m() {\n        if (a) return;\n    }\n}\n'))

    def test_project_lint_covers_main_and_test_sources_skips_properties_and_never_claims_the_official_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'src/main/java/a').mkdir(parents=True)
            (out / 'src/test/java/a').mkdir(parents=True)
            (out / 'src/main/resources').mkdir(parents=True)
            (out / 'src/main/java/a/A.java').write_text('package a;\n\nclass A {\n    int x = 77;\n}\n', encoding='utf-8')
            (out / 'src/test/java/a/ATest.java').write_text('package a;\n\nclass ATest {\n    int y = 88;\n}\n', encoding='utf-8')
            (out / 'src/main/resources/application.properties').write_text('x=99999\n', encoding='utf-8')
            result = sl.lint_project(out)
            self.assertEqual(sorted({f['file'] for f in result['findings']}), ['src/main/java/a/A.java', 'src/test/java/a/ATest.java'])
            self.assertEqual(result['checkstyleOfficial'], 'not-verified')
            self.assertEqual(result['preventiveResult'], 'findings')
            self.assertIn('official gate', result['note'])
            self.assertEqual(sl.main([str(out)]), 1)


if __name__ == '__main__':
    unittest.main()
