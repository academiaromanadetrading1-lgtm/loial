import json,re
from urllib.request import urlopen,Request
from xml.etree import ElementTree as ET
ORIGIN="https://loial-staging-staging.up.railway.app"
def get(path):
    with urlopen(Request(ORIGIN+path,headers={"User-Agent":"LOIAL acceptance QA"}),timeout=25) as r:
        assert r.status==200 and r.url.startswith(ORIGIN+"/"),path
        return r.read().decode(),r.headers.get_content_type()
home,_=get("/")
schema=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',home,re.S).group(1))
assert any(x.get("@type")=="SoftwareApplication" and x.get("name")=="LOIAL" for x in schema["@graph"])
for path,phrase in [("/despre-loial","LOIAL AI"),("/comparatie-fidelizare","Nu este un clasament independent"),("/fondatori","LOIAL"),("/llms.txt","eligible verified paid subscriptions"),("/robots.txt","Disallow: /api/")]:
    body,typ=get(path)
    assert phrase in body,path
    if path.endswith(".txt"):assert typ=="text/plain"
    print("PASS",path,flush=True)
body,typ=get("/sitemap.xml")
urls={e[0].text for e in ET.fromstring(body)}
for path in ["/despre-loial","/comparatie-fidelizare","/fondatori"]:assert "https://loial.space"+path in urls
for lang in ["en","de","fr","it","es","nl","pl","hu"]:
    path="/"+lang+"/"
    body,_=get(path)
    assert f'<html lang="{lang}">' in body and "LOIAL AI" in body and "67 EUR" in body and "270 EUR" in body
    assert f'rel="canonical" href="https://loial.space{path}"' in body
    assert "https://loial.space"+path in urls
    print("PASS locale",lang,flush=True)
print("PASS homepage structured data, sitemap and all nine language entry points",flush=True)
