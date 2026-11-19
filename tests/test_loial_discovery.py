import json
import re
from pathlib import Path
from xml.etree import ElementTree
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loial_growth import install_growth, LANGUAGES
from loial_seo_locales import DISCOVERY, landing

def test_public_discovery_routes():
    app=FastAPI()
    install_growth(app, {})
    with TestClient(app) as client:
        for path in ("/despre-loial","/comparatie-fidelizare","/llms.txt","/robots.txt","/sitemap.xml"):
            response=client.get(path)
            assert response.status_code==200,path
        reference=client.get("/llms.txt")
        assert reference.headers["content-type"].startswith("text/plain")
        assert "eligible verified paid subscriptions" in reference.text
        assert "No claim of independent ranking" in reference.text
        sitemap=ElementTree.fromstring(client.get("/sitemap.xml").content)
        urls={node[0].text for node in sitemap}
        assert {"https://loial.space/despre-loial","https://loial.space/comparatie-fidelizare","https://loial.space/fondatori"}<=urls
        assert "Disallow: /api/" in client.get("/robots.txt").text

def test_all_locales_have_product_positioning():
    assert set(DISCOVERY)==set(LANGUAGES)
    for lang in LANGUAGES:
        html=landing(lang)
        assert f'<html lang="{lang}">' in html
        assert "LOIAL AI" in html
        assert "67 EUR" in html and "270 EUR" in html
        for other in LANGUAGES:
            assert f'hreflang="{other}"' in html

def test_homepage_software_schema():
    html=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
    match=re.search(r'<script type="application/ld\+json">(.*?)</script>',html,re.S)
    assert match
    graph=json.loads(match.group(1))["@graph"]
    software=next(x for x in graph if x["@type"]=="SoftwareApplication")
    assert software["name"]=="LOIAL"
    assert software["offers"]["price"]==0
    assert "aggregateRating" not in software
    assert 'href="/despre-loial"' in html
