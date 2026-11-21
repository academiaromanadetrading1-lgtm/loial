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


def test_legacy_qr_enrollment_has_rate_limit_and_full_uuid():
    source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    handler = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "qr_enroll"
    )
    decorator_text = ast.get_source_segment(source, handler.decorator_list[-1])
    assert decorator_text == 'limiter.limit("10/minute")'
    assert any(arg.arg == "request" for arg in handler.args.args)
    handler_src = ast.get_source_segment(source, handler)
    assert "str(uuid.uuid4())" in handler_src
    assert "str(uuid.uuid4())[:8]" not in handler_src
    assert "len(name) <= 120" in handler_src
    assert "len(req.email) > 254" in handler_src
    assert "len(req.phone) > 40" in handler_src


def test_public_qr_generator_rejects_unbounded_payloads():
    source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    handlers = [node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "generate_raw_qr_png"]
    assert len(handlers) == 1
    handler = handlers[0]
    assert any(arg.arg == "request" for arg in handler.args.args)
    assert any(ast.get_source_segment(source, dec) == 'limiter.limit("30/minute")'
               for dec in handler.decorator_list)
    body = ast.get_source_segment(source, handler)
    assert "len(code_text) <= 512" in body
    assert 're.fullmatch(r"#[0-9a-fA-F]{6}", color)' in body
    assert "len(initial) > 32" in body
    assert body.index("len(code_text) <= 512") < body.index("create_premium_qr_bytes(")


def test_join_card_updates_use_private_wallet_scope():
    join = Path(__file__).resolve().parents[1].joinpath("join.html").read_text(encoding="utf-8")
    assert "/api/presence/" not in join
    assert "/api/customer-status/" not in join
    assert "'/api/wallet-profile/' + encodeURIComponent(uuid)" in join
    assert "'X-Loial-Wallet-Token': privateToken" in join
    assert "if (!privateToken) return;" in join
    assert "if (document.hidden) return;" in join
    assert "if (window.loialPrivateCardInterval) clearInterval" in join
    assert "cache: 'no-store'" in join
