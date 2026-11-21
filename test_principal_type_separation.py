"""Regression checks for principal type separation across legacy login handlers."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def function_text(name):
    matches = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one {name}")
    return ast.get_source_segment(SOURCE, matches[0])


class PrincipalSeparationTests(unittest.TestCase):
    def test_user_auth_requires_user_principal(self):
        code = function_text("get_current_user")
        self.assertIn('payload.get("principal_type") != "user"', code)
        self.assertIn('payload.get("role") != user.role', code)

    def test_combined_login_mints_disjoint_principals(self):
        code = function_text("login")
        self.assertIn('"business" if isinstance(authenticated, BusinessAccount)', code)
        self.assertIn('"agent" if isinstance(authenticated, SalesAgent) else "user"', code)
        self.assertIn('"principal_type":principal_type', code)

    def test_agent_login_mints_only_agent_principal(self):
        code = function_text("agent_login")
        self.assertIn('"principal_type": "agent"', code)

    def test_admin_routes_reject_non_user_principals(self):
        for name in ("require_platform_admin", "require_business_owner_or_admin"):
            code = function_text(name)
            self.assertIn('claims.get("principal_type")', code)
        self.assertIn('claims.get("principal_type") != "user"', function_text("require_platform_admin"))

    def test_validation_cannot_assign_admin_role(self):
        code = function_text("validate_agent")
        self.assertIn('if role not in ("agent", "ambassador", "manager"):', code)
        self.assertIn('if not 0 <= commission_own <= 100:', code)


if __name__ == "__main__":
    unittest.main()
