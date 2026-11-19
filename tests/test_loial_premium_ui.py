from pathlib import Path
from html.parser import HTMLParser
import re

ROOT = Path(__file__).resolve().parents[1]

class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

def read(name):
    return (ROOT / name).read_text(encoding="utf-8")

def test_role_pages_have_shared_design_and_valid_shortcuts():
    for name in ("platform.html", "loial-wallet.html", "ambasador.html"):
        source = read(name)
        tags = Markup(source).tags
        ids = {a["id"] for _, a in tags if "id" in a}
        assert any(a.get("href") == "/loial-premium.css" for _, a in tags)
        assert "Spațiul tău loial" in source
        for tag, attrs in tags:
            if tag == "a" and attrs.get("href", "").startswith("#") and attrs["href"] != "#":
                assert attrs["href"][1:] in ids, (name, attrs["href"])

def test_premium_shortcuts_have_entitlement_labels_and_workspace_targets():
    source = read("platform.html")
    ai = read("loial-ai.html")
    for feature in ("messages", "reports"):
        url = "/loial-ai.html#" + feature
        match = re.search(r'<a[^>]*data-premium-url="' + re.escape(url) + r'"[^>]*>.*?</a>', source)
        assert match
        assert 'aria-disabled="true"' in match.group()
        assert "data-lock-label" in match.group()
        assert 'data-view="' + feature + '"' in ai
    assert "#loialQuickActions [data-premium-url]" in source

def test_public_guides_and_branding_are_present():
    source = read("loial_growth.py")
    assert source.count('class="loial-guide-step"') >= 9
    for route in ("/pentru-clienti", "/pentru-firme", "/ambasadori"):
        assert '@app.get("' + route + '")' in source
    assert "Spațiul tău loial" in source
    assert 'href="/wallet">Deschide portofelul' in source
    assert 'href="/wallet-recovery.html"' in source
    assert '@router.get("/wallet"' in read("loial_pwa.py")
    assert 'loial-premium.css' in read("main.py")


def test_public_role_pages_render_with_consistent_menu_and_correct_account_links():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from loial_growth import install_growth

    app = FastAPI()
    install_growth(app, {})
    expected = ["/", "/#cum-functioneaza", "/pentru-clienti", "/ambasadori",
                "/pentru-firme", "/#preturi", "/despre-loial"]
    with TestClient(app) as client:
        for path, account, action in (
            ("/pentru-clienti", "/wallet", "/wallet"),
            ("/pentru-firme", "/login.html", "/register.html"),
            ("/ambasadori", "/ambasador.html#contAmbasador", "/ambasador.html#contAmbasador"),
        ):
            response = client.get(path)
            assert response.status_code == 200
            source = response.text
            header = source.split("</header>", 1)[0]
            menu = header.split('<nav aria-label="Navigare principală">', 1)[1].split("</nav>", 1)[0]
            links = [a["href"] for tag, a in Markup(menu).tags if tag == "a"]
            assert links == expected
            assert 'href="' + account + '"' in header
            assert 'href="' + action + '"' in source
            assert source.count("<h1>") == 1
            assert 'class="loial-hero"' in source
            assert 'class="loial-tiers"' in source
            assert 'https://loial.space' + path in source
            assert not re.search(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', source)
            if path == "/ambasadori":
                assert 'id="portfolioForm"' in source
                assert 'id="portfolioResult"' in source

def test_home_and_ambassador_entry_menu_matches_public_navigation():
    expected = ["/", "/#cum-functioneaza", "/pentru-clienti", "/ambasadori",
                "/pentru-firme", "/#preturi", "/despre-loial"]
    for name in ("index.html", "ambasador.html"):
        source = read(name)
        menu = source.split('class="loial-global-links"', 1)[1].split("</div>" if name == "index.html" else "</nav>", 1)[0]
        assert [a["href"] for tag, a in Markup("<div" + menu).tags if tag == "a"] == expected
    assert 'id="cum-functioneaza"' in read("index.html")
    assert 'id="preturi"' in read("index.html")
    assert 'id="contAmbasador"' in read("ambasador.html")
