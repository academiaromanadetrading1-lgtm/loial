"""Regression guard for retired unauthenticated LOIAL endpoints.

These routes formerly accepted arbitrary customer UUIDs or email addresses.
They remain mounted for compatibility but intentionally return 410 before
accessing database data. Wallet functionality uses scoped authenticated APIs.
"""
import ast
from pathlib import Path

import pytest

LEGACY = {
    "get_preferences",
    "set_preferences",
    "ping_customer_presence",
    "check_business_presence",
    "get_customer_status",
}


@pytest.mark.parametrize("function_name", sorted(LEGACY))
def test_legacy_route_fails_closed_before_data_access(function_name):
    source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    assert len(matches) == 1, f"Expected exactly one handler: {function_name}"
    handler = matches[0]
    assert len(handler.body) >= 1
    # Never permit a database read or write before the explicit refusal.
    first_statement = handler.body[0]
    if isinstance(first_statement, ast.Expr) and isinstance(first_statement.value, ast.Constant):
        first_statement = handler.body[1]
    assert isinstance(first_statement, ast.Raise), function_name
    exc = first_statement.exc
    assert isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name)
    assert exc.func.id == "HTTPException"
    assert any(
        keyword.arg == "status_code"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value == 410
        for keyword in exc.keywords
    ), function_name


def test_public_pages_do_not_depend_on_retired_apis():
    pages = ("index.html", "loial-wallet.html", "loial-ai.html", "platform.html",
             "scan.html", "dashboard.html", "join.html")
    retired = (
        "/api/presence/",
        "/api/customer-status/",
        "fetch('/preferences",
        'fetch("/preferences',
    )
    root = Path(__file__).resolve().parents[1]
    for page in pages:
        html = (root / page).read_text(encoding="utf-8")
        for fragment in retired:
            assert fragment not in html, f"{page} calls retired API {fragment}"
