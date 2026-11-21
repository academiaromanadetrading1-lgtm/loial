"""Stripe merchant JWT authorization guards, without importing the app."""
import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).with_name("loial_stripe_billing.py").read_text(encoding="utf-8")


class StripeBusinessTokenTests(unittest.TestCase):
    def test_checkout_and_portal_owner_resolver_checks_exact_integer_id(self):
        tree = ast.parse(SOURCE)
        installers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "install_stripe_billing"]
        self.assertEqual(len(installers), 1)
        owners = [n for n in installers[0].body if isinstance(n, ast.FunctionDef)
                  and n.name == "own_business"]
        self.assertEqual(len(owners), 1)
        owner_source = ast.get_source_segment(SOURCE, owners[0])
        self.assertIn('type(claims.get("business_id")) is not int', owner_source)
        self.assertIn('claims["business_id"] <= 0', owner_source)
        self.assertIn('Business.id==claims["business_id"]', owner_source)
        self.assertIn('Business.email==claims.get("sub")', owner_source)

    def test_entitlement_middleware_validates_business_id(self):
        tree = ast.parse(SOURCE)
        installers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "install_stripe_billing"]
        middleware = [n for n in ast.walk(installers[0])
                      if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == "enforce_premium_access"]
        self.assertEqual(len(middleware), 1)
        code = ast.get_source_segment(SOURCE, middleware[0])
        self.assertIn('type(claims.get("business_id")) is int', code)
        self.assertIn('claims["business_id"] > 0', code)


if __name__ == "__main__":
    unittest.main()
