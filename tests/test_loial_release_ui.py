"""Static release contracts for the responsive LOIAL PWA and private dashboards.

These are regression checks, NOT substitutes for real iOS/Android testing.
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def source(name):
    return (ROOT/name).read_text(encoding="utf-8")


def test_black_metal_pwa_has_installable_manifest_and_offline_shell():
    data=json.loads(source("manifest.json"))
    assert data["display"]=="standalone"
    assert data["start_url"].startswith("/wallet")
    assert data["scope"]=="/"
    icons=data["icons"]
    assert {"192x192","512x512"}.issubset({x["sizes"] for x in icons})
    assert all(x["src"].startswith("/pwa-icon-") for x in icons)
    worker=source("sw.js")
    assert "url.pathname.startsWith('/api/')" in worker
    assert "request.method !== 'GET'" in worker
    assert "'/loial-offline.html'" in worker
    assert "const PUBLIC = new Set(SHELL)" in worker


def test_wallet_is_responsive_and_uses_private_token():
    for file in ("join.html","loial-wallet.html"):
        html=source(file)
        assert 'name="viewport"' in html
        assert 'href="/manifest.json"' in html
        assert "loial-pwa-install.js" in html
        assert "@media" in html
        assert "loial_wallet_inbox_token" in html
    assert "/wallet-recovery.html" in source("loial-wallet.html")


def test_ambassador_has_correct_referral_destinations_and_private_ledger():
    html=source("ambasador.html")
    assert 'name="viewport"' in html and "@media" in html
    assert "ambasador.html?ambref=" in html
    assert "join.html?ambref=" not in html
    assert "/api/loial-revenue/ambassador/me" in html
    assert "/api/ambassador/login" in html
    assert "ambWiseForm" in html
    assert "/api/loial-revenue/ambassador/wise-details" in html
    assert "sessionStorage" in html


def test_admin_dashboard_price_payment_and_export_are_consistent():
    html=source("platform.html")
    assert 'name="viewport"' in html and "@media" in html
    assert "67 EUR" in html
    assert "stripePayButton" in html
    assert "/api/loial-stripe/me" in html
    assert "/api/loial-stripe/checkout" not in html or "stripeLink('checkout')" in html
    assert "downloadCommissionXlsx" in html
    assert "adminActivity" in html
    assert "loadSuperAdmin()" in html
    assert "toggleProPlan(" not in html
