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
    assert 'href="/wallet">Deschide portofelul' not in source
    assert 'loial-premium.css' in read("main.py")
