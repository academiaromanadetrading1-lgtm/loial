"""Fail closed regression guard for obsolete QR enrollment.

The current LOIAL join page posts to /api/enroll-sync with wallet secret
verification. /api/enroll must never create unauthenticated orphan cards.
"""
import ast
from pathlib import Path
import unittest


class EnrollmentDeprecationTest(unittest.TestCase):
    def test_legacy_qr_enrollment_returns_410_before_database_access(self):
        code = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        handlers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "qr_enroll"]
        self.assertEqual(len(handlers), 1)
        first = handlers[0].body[0]
        self.assertIsInstance(first, ast.Raise)
        self.assertIsInstance(first.exc, ast.Call)
        self.assertIsInstance(first.exc.func, ast.Name)
        self.assertEqual(first.exc.func.id, "HTTPException")
        self.assertTrue(any(
            item.arg == "status_code" and isinstance(item.value, ast.Constant)
            and item.value.value == 410
            for item in first.exc.keywords
        ))
        self.assertIn("/api/enroll-sync",
                      Path(__file__).with_name("join.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
