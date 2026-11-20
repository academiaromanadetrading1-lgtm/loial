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


def test_ambassador_slider_executes_real_script_and_matches_server_policy():
    import json
    import shutil
    import subprocess
    import pytest
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from loial_growth import install_growth
    from loial_plans import simulate_portfolio

    node = shutil.which("node")
    assert node, "Node.js is required for the commission slider regression"
    app = FastAPI()
    install_growth(app, {})
    with TestClient(app) as client:
        source = client.get("/ambasadori").text
    tags = Markup(source).tags
    ranges = [attrs for tag, attrs in tags if tag == "input" and attrs.get("type") == "range"]
    assert len(ranges) == 1
    assert ranges[0]["id"] == "portfolioRange"
    assert (ranges[0]["min"], ranges[0]["max"], ranges[0]["step"], ranges[0]["value"]) == ("0", "100", "1", "20")
    assert not any(tag == "input" and attrs.get("type") == "number" for tag, attrs in tags)
    assert not any(tag == "button" and attrs.get("type") == "submit" for tag, attrs in tags)
    scripts = [x for x in re.findall(r"<script>(.*?)</script>", source, flags=re.S)
               if "portfolioRange" in x]
    assert len(scripts) == 1
    cases = []
    for plan in ("business", "probusiness"):
        for n in (0, 1, 20, 25, 26, 50, 51, 100):
            pro = plan == "probusiness"
            first = simulate_portfolio(new_pro=n) if pro else simulate_portfolio(new_business=n)
            renewal = simulate_portfolio(renewed_pro=n) if pro else simulate_portfolio(renewed_business=n)
            cases.append({"plan": plan, "n": n,
                          "activation": first["activation_cents"] // 100,
                          "renewal": renewal["recurring_cents"] // 100})
    harness = r"""
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const payload=JSON.parse(fs.readFileSync(0,'utf8')),nodes={},events={};
for(const id of ['portfolioCount','portfolioRank','portfolioActivation','portfolioRenewal']) nodes[id]={textContent:''};
nodes.portfolioRange={value:'20',style:{setProperty(){}}};
nodes.portfolioForm={elements:{simPlan:{value:'business'}},
                    addEventListener(name, fn){events[name]=fn;}};
vm.runInNewContext(payload.script,{document:{getElementById:id=>nodes[id]},Intl});
const numeric=id=>Number(nodes[id].textContent.replace(/[^\d]/g,''));
assert.equal(numeric('portfolioActivation'),400);
assert.equal(numeric('portfolioRenewal'),100);
assert.equal(typeof events.input,'function');
assert.equal(typeof events.change,'function');
for(const c of payload.cases){
  nodes.portfolioForm.elements.simPlan.value=c.plan;
  nodes.portfolioRange.value=String(c.n);
  events.input();
  assert.equal(numeric('portfolioCount'),c.n);
  assert.equal(numeric('portfolioActivation'),c.activation);
  assert.equal(numeric('portfolioRenewal'),c.renewal);
  if(c.n===0)assert.match(nodes.portfolioRank.textContent,/Nicio/);
  else assert.match(nodes.portfolioRank.textContent,c.n>=51?/Senior/:c.n>=26?/Manager/:/LOIAL/);
}
nodes.portfolioForm.elements.simPlan.value='business';
events.change();
assert.equal(numeric('portfolioActivation'),2000);
assert.equal(numeric('portfolioRenewal'),1500);
"""
    result = subprocess.run([node, "-e", harness], input=json.dumps({"script": scripts[0], "cases": cases}),
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_approved_ambassador_final_cta_and_probusiness_amount():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from loial_plans import simulate_portfolio
    from loial_growth import install_growth
    app = FastAPI()
    install_growth(app, {})
    with TestClient(app) as client:
        response = client.get("/ambasadori")
    assert response.status_code == 200
    source = response.text
    bottom = source.split('class="loial-bottom-actions">', 1)[1].split("</div>", 1)[0]
    assert "Devino ambasador" in bottom
    assert 'href="/ambasador.html#contAmbasador"' in bottom
    assert "Vezi demonstrația" not in bottom
    assert "Comisioane pentru firme aduse de ambasadorii recrutați de către tine" in source
    assert simulate_portfolio(new_pro=1)["activation_cents"] == 4000
    assert simulate_portfolio(renewed_pro=1)["recurring_cents"] == 2000
    assert simulate_portfolio(recruited_pro=1)["sponsor_cents"] == 4000



def test_multilingual_runtime_regression():
    # This file is already part of the approved CI suite. Reuse the isolated
    # regression without changing the workflow or triggering a runner.
    import runpy
    module = runpy.run_path(str(ROOT / "tests" / "test_loial_i18n_regression.py"))
    module["test_locale_switching_preserves_data_and_form_values"]()
