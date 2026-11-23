"""Regression tests: missing or invalid join QR URLs cannot enroll the wrong firm."""
import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
JOIN = (ROOT / "join.html").read_text(encoding="utf-8")


class MerchantJoinRoutingTests(unittest.TestCase):
    def test_join_handler_checks_business_exists_before_responding(self):
        tree = ast.parse(MAIN)
        handlers = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "join_qr_page"]
        self.assertEqual(len(handlers), 1)
        handler = handlers[0]
        code = ast.get_source_segment(MAIN, handler)
        self.assertIn("business_id <= 0", code)
        self.assertIn("BusinessAccount.id == business_id", code)
        self.assertIn("status_code=404", code)
        self.assertLess(code.index("status_code=404"), code.index('FileResponse("join.html")'))

    def test_frontend_requires_positive_explicit_merchant_id(self):
        self.assertIn("Number.isSafeInteger(bizId)", JOIN)
        self.assertIn("if (!Number.isSafeInteger(bizId) || bizId <= 0)", JOIN)
        self.assertNotIn("parseInt(location.pathname.split('/').pop()) || 1", JOIN)
        self.assertIn("location.replace('/')", JOIN)

    def test_frontend_has_exact_join_path_pattern(self):
        self.assertIn(r"/^\/join\/([1-9]\d*)\/?$/", JOIN)
        path = re.compile(r"^/join/([1-9]\d*)/?$")
        for good in ("/join/1", "/join/18", "/join/100000/"):
            self.assertIsNotNone(path.fullmatch(good))
        for bad in ("/", "/join.html", "/join/", "/join/0", "/join/-1",
                    "/join/1junk", "/join/1/2", "/join/01", "/join/1?x"):
            self.assertIsNone(path.fullmatch(bad))


if __name__ == "__main__":
    unittest.main()
