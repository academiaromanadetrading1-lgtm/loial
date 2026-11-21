"""Regression guard: retired legacy campaign API must never write cross-merchant rows.

Uses only the Python AST so imports, credentials and Railway storage are not required.
"""
import ast
from pathlib import Path
import unittest


class LegacyCampaignSecurityTests(unittest.TestCase):
    def test_legacy_campaign_routes_fail_closed_before_database_write(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        definitions = [
            node for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "generate_campaign"
        ]
        assert len(definitions) == 1, "Expected exactly one legacy campaign handler"
        handler = definitions[0]
        assert any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in ("get", "post")
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and decorator.args[0].value == "/campaign"
            for decorator in handler.decorator_list
        ), "Campaign handler must be tested against the legacy /campaign route"
        first = handler.body[0]
        assert isinstance(first, ast.Raise), "Legacy campaign must fail before any database operations"
        assert isinstance(first.exc, ast.Call)
        assert isinstance(first.exc.func, ast.Name)
        assert first.exc.func.id == "HTTPException"
        assert any(
            keyword.arg == "status_code"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == 410
            for keyword in first.exc.keywords
        ), "Legacy campaign must return HTTP 410"
    
