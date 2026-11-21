"""Guard platform-wide privileges against legacy owner and demo accounts."""
import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")


class PlatformPrivilegeTests(unittest.TestCase):
    def test_no_admin_route_accepts_legacy_owner_role(self):
        self.assertNotIn('current_user.role not in ["admin", "owner"]', SOURCE)
        self.assertNotIn('operator.role in ("admin", "owner")', SOURCE)
        self.assertNotIn('admin.role not in ("admin", "owner")', SOURCE)
        self.assertNotIn('claims.get("role") in ("admin", "owner")', SOURCE)

    def test_default_and_demo_accounts_are_unprivileged(self):
        tree = ast.parse(SOURCE)
        user_models = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "User"]
        self.assertEqual(len(user_models), 1)
        model = user_models[0]
        roles = [n.value for n in model.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "role" for t in n.targets)]
        self.assertEqual(len(roles), 1)
        self.assertIsInstance(roles[0], ast.Call)
        self.assertTrue(any(k.arg == "default" and isinstance(k.value, ast.Constant)
                            and k.value.value == "user" for k in roles[0].keywords))
        self.assertIn('name="Cont demo", plan="starter", role="user"', SOURCE)

    def test_platform_admin_checker_rejects_owner(self):
        tree = ast.parse(SOURCE)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name == "require_platform_admin"]
        self.assertEqual(len(functions), 1)
        code = ast.get_source_segment(SOURCE, functions[0])
        self.assertIn('admin.role != "admin"', code)
        self.assertIn('claims.get("role") != "admin"', code)

    def test_merchant_direct_access_refuses_owner(self):
        tree = ast.parse(SOURCE)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name == "require_business_owner_or_admin"]
        self.assertEqual(len(functions), 1)
        code = ast.get_source_segment(SOURCE, functions[0])
        self.assertIn('claims.get("role") == "admin"', code)
        self.assertNotIn('"owner"', code)


if __name__ == "__main__":
    unittest.main()
