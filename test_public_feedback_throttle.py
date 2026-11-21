"""Static regression test for rate-limiting public review submissions."""
import ast
from pathlib import Path
import unittest


class PublicFeedbackSafetyTest(unittest.TestCase):
    def test_unauthenticated_feedback_is_throttled(self):
        tree = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
        handlers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "save_public_review_feedback"]
        self.assertEqual(len(handlers), 1)
        handler = handlers[0]
        decorators = [d for d in handler.decorator_list if isinstance(d, ast.Call)]
        paths = [d.args[0].value for d in decorators if isinstance(d.func, ast.Attribute)
                 and d.func.attr == "post" and d.args
                 and isinstance(d.args[0], ast.Constant)]
        self.assertIn("/api/private-feedback", paths)
        self.assertTrue(any(
            isinstance(d.func, ast.Attribute) and d.func.attr == "limit"
            and isinstance(d.func.value, ast.Name) and d.func.value.id == "limiter"
            and d.args and isinstance(d.args[0], ast.Constant)
            and d.args[0].value == "10/minute"
            for d in decorators
        ), "Public reviews must be throttled at the server")
        self.assertTrue(any(a.arg == "request" for a in handler.args.args),
                        "slowapi requires a Request parameter")


if __name__ == "__main__":
    unittest.main()
