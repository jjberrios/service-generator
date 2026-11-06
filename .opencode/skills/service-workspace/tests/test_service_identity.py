from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import workspace as wsm  # noqa: E402


class ServiceNameTests(unittest.TestCase):
    def test_mixed_case_and_lowercase_names_are_accepted(self):
        for name in ('dom-cpeRequest', 'dom-cperequest', 'dom-cpe-request', 'sod-general-configurations'):
            self.assertEqual(wsm.safe_name(name), name)

    def test_unsafe_names_are_rejected(self):
        for name in ('', '1abc', '../x', 'a/b', 'a_b', 'a--b', '-a', 'a-', 'a b'):
            with self.assertRaises(wsm.WorkspaceError):
                wsm.safe_name(name)

    def test_technical_identifier_is_lowercase_kebab(self):
        self.assertEqual(wsm.technical_identifier('dom-cpeRequest'), 'dom-cpe-request')
        self.assertEqual(wsm.technical_identifier('dom-customerBillQuery'), 'dom-customer-bill-query')
        self.assertEqual(wsm.technical_identifier('sod-general-configurations'), 'sod-general-configurations')

    def test_workspace_rejects_case_only_clash(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / '.factory' / 'services' / 'dom-cperequest').mkdir(parents=True)
            with self.assertRaises(wsm.WorkspaceError):
                wsm.Workspace(repo, 'dom-cpeRequest')
            self.assertEqual(wsm.Workspace(repo, 'dom-cperequest').service, 'dom-cperequest')


class SparxRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / 'input' / 'sparx').mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, folder):
        (folder / 'EARoot').mkdir(parents=True)
        (folder / 'index.htm').write_text('x', encoding='utf-8')

    def test_export_directly_under_input_sparx(self):
        self.export(self.repo / 'input' / 'sparx')
        for requested in ('input/sparx/PROYECT/', 'input/sparx', '/sparx', 'sparx/', 'input\\sparx\\PROYECT'):
            self.assertEqual(wsm.resolve_sparx_root(self.repo, requested), 'input/sparx')

    def test_export_in_proyect_subfolder(self):
        self.export(self.repo / 'input' / 'sparx' / 'PROYECT')
        for requested in ('input/sparx/PROYECT/', 'input/sparx', 'sparx'):
            self.assertEqual(wsm.resolve_sparx_root(self.repo, requested), 'input/sparx/PROYECT')

    def test_ambiguous_children_fail(self):
        self.export(self.repo / 'input' / 'sparx' / 'A')
        self.export(self.repo / 'input' / 'sparx' / 'B')
        with self.assertRaises(wsm.WorkspaceError):
            wsm.resolve_sparx_root(self.repo, 'input/sparx')

    def test_escape_and_missing_fail(self):
        with self.assertRaises(wsm.WorkspaceError):
            wsm.resolve_sparx_root(self.repo, '../outside')
        with self.assertRaises(wsm.WorkspaceError):
            wsm.resolve_sparx_root(self.repo, 'input/sparx/PROYECT')


if __name__ == '__main__':
    unittest.main()
