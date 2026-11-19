import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loial_growth import install_growth
from loial_indexnow import public_url, sitemap_urls, submission

KEY="test-key-123456789"
BASE="https://loial.space"
@pytest.mark.parametrize("path",["/","/despre-loial","/en/","/solutii/cafenele","/local/timisoara/cafenele"])
def test_public(path):
    assert public_url(BASE+path)
@pytest.mark.parametrize("url",[BASE+"/api/customers",BASE+"/platform.html",BASE+"/wallet",BASE+"/join/secret",BASE+"/?token=private",BASE+"/#token",BASE+"/local/../secret","https://other.example/","http://loial.space/","https://loial.space.evil.example/"])
def test_private(url):
    assert not public_url(url)
    with pytest.raises(ValueError): submission(KEY,[url])
def test_payload():
    xml='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://loial.space/</loc></url><url><loc>https://loial.space/api/customers</loc></url></urlset>'
    assert sitemap_urls(xml)==[BASE+"/"]
    p=submission(KEY,[BASE+"/",BASE+"/"])
    assert p["urlList"]==[BASE+"/"]
    assert p["keyLocation"]==BASE+"/indexnow/"+KEY+".txt"
    with pytest.raises(ValueError): submission("bad",[BASE+"/"])
def test_key_route(monkeypatch):
    app=FastAPI()
    install_growth(app,{})
    client=TestClient(app)
    monkeypatch.delenv("LOIAL_INDEXNOW_KEY",raising=False)
    assert client.get("/indexnow/"+KEY+".txt").status_code==404
    monkeypatch.setenv("LOIAL_INDEXNOW_KEY",KEY)
    r=client.get("/indexnow/"+KEY+".txt")
    assert r.status_code==200 and r.text==KEY
    assert r.headers["content-type"].startswith("text/plain")
    assert client.get("/indexnow/wrong-key.txt").status_code==404
