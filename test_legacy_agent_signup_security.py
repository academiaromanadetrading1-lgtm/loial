"""No unauthenticated agent signup may bypass password/identity constraints."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")

class AgentSignupGuards(unittest.TestCase):
    def test_signup_validates_password_and_email_before_db(self):
        tree = ast.parse(SOURCE)
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "register_agent"]
        self.assertEqual(len(funcs), 1)
        handler = funcs[0]
        code = ast.get_source_segment(SOURCE, handler)
        self.assertIn('len(password.encode("utf-8")) <= 72', code)
        self.assertIn('email = email.strip().lower()', code)
        self.assertIn('len(email) > 254', code)
        self.assertIn('re.fullmatch', code)
        self.assertIn('len(name.strip()) <= 100', code)
        first_query = code.index('db.query(SalesAgent)')
        self.assertLess(code.index('len(password.encode'), first_query)
        self.assertLess(code.index('re.fullmatch'), first_query)

    def test_email_regex_accepts_valid_and_rejects_whitespace(self):
        import re
        pattern = r"[^@\s]+@[^@\s]+\.[^@\s]+"
        self.assertIsNotNone(re.fullmatch(pattern, "person@example.com"))
        self.assertIsNone(re.fullmatch(pattern, "person name@example.com"))
        self.assertIsNone(re.fullmatch(pattern, "person@example"))
        self.assertIn(pattern, SOURCE)

if __name__ == "__main__":
    unittest.main()
