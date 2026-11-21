"""Unit tests for direct merchant endpoints' token-to-business isolation.

Load only the target function from main.py, so the test does not connect to
Railway's production database or need a JWT signing secret.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class JWTError(Exception):
    pass


class ClaimsJWT:
    claims = {}

    @classmethod
    def decode(cls, token, secret, algorithms):
        return cls.claims


class BusinessAccount:
    id = 1
    email = "merchant@example.invalid"


class User:
    pass


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args):
        return self

    def first(self):
        return self.result


class FakeDB:
    def __init__(self, account):
        self.account = account
        self.queries = 0

    def query(self, model):
        self.queries += 1
        return FakeQuery(self.account)


def load_authorization_function():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "require_business_owner_or_admin"
    ]
    if len(matches) != 1:
        raise AssertionError("Expected exactly one direct merchant authorization function")
    namespace = {
        "jwt": ClaimsJWT,
        "SECRET_KEY": "test-only",
        "ALGORITHM": "HS256",
        "JWTError": JWTError,
        "HTTPException": HTTPException,
        "BusinessAccount": BusinessAccount,
        "User": User,
        "Session": object,
    }
    exec(compile(ast.Module(body=matches, type_ignores=[]), "main.py", "exec"), namespace)
    return namespace["require_business_owner_or_admin"]


class MerchantTokenIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authorize = staticmethod(load_authorization_function())

    def setUp(self):
        self.credentials = SimpleNamespace(credentials="placeholder")

    def assert_forbidden_without_lookup(self, claims, business_id=1):
        ClaimsJWT.claims = {"sub": "merchant@example.invalid", "role": "business", **claims}
        db = FakeDB(BusinessAccount())
        with self.assertRaises(HTTPException) as error:
            self.authorize(business_id, self.credentials, db)
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(db.queries, 0)

    def test_wrong_business_id_is_rejected(self):
        self.assert_forbidden_without_lookup({"business_id": 2})

    def test_missing_business_id_is_rejected(self):
        self.assert_forbidden_without_lookup({})

    def test_boolean_business_id_is_rejected(self):
        self.assert_forbidden_without_lookup({"business_id": True})

    def test_correct_business_id_and_email_can_access(self):
        ClaimsJWT.claims = {
            "sub": "merchant@example.invalid", "role": "business", "business_id": 1
        }
        account = BusinessAccount()
        db = FakeDB(account)
        self.assertIs(self.authorize(1, self.credentials, db), account)
        self.assertEqual(db.queries, 1)


if __name__ == "__main__":
    unittest.main()
