"""Explicit post-release IndexNow notification; no network calls on import or app startup."""
import argparse
import json
import os
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

ORIGIN = "https://loial.space"
HOST = "loial.space"
ENDPOINT = "https://api.indexnow.org/indexnow"
PUBLIC_FIXED = {"/","/despre-loial","/comparatie-fidelizare","/fondatori","/ambasadori","/demo"}
LOCALES = {"en","de","fr","it","es","nl","pl","hu"}

def public_url(url):
    parsed=urlsplit(url)
    if parsed.scheme!="https" or parsed.netloc!=HOST or parsed.query or parsed.fragment:
        return False
    path=parsed.path
    return (path in PUBLIC_FIXED or path in {"/"+lang+"/" for lang in LOCALES}
            or bool(re.fullmatch(r"/solutii/[a-z0-9-]+",path))
            or bool(re.fullmatch(r"/local/[a-z0-9-]+/[a-z0-9-]+",path)))

def sitemap_urls(xml):
    return sorted({node.text for node in ElementTree.fromstring(xml).findall("{*}url/{*}loc")
                   if node.text and public_url(node.text)})

def submission(key, urls):
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}",key):
        raise ValueError("Invalid IndexNow key")
    urls=sorted(set(urls))
    if not urls or len(urls)>10000 or not all(public_url(u) for u in urls):
        raise ValueError("Only canonical public LOIAL URLs are allowed")
    return {"host":HOST,"key":key,"keyLocation":ORIGIN+"/"+key+".txt","urlList":urls}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit",action="store_true",help="Explicitly notify IndexNow")
    parser.add_argument("--url",action="append",default=[],help="Changed canonical URL; repeat as needed")
    parser.add_argument("--initial",action="store_true",help="Initial notification of all eligible sitemap URLs")
    args=parser.parse_args()
    key=os.environ.get("LOIAL_INDEXNOW_KEY","")
    with urlopen(ORIGIN+"/sitemap.xml",timeout=20) as response:
        allowed=set(sitemap_urls(response.read()))
    urls=sorted(allowed) if args.initial else args.url
    if not set(urls)<=allowed:
        raise SystemExit("URL absent from public sitemap")
    payload=submission(key,urls)
    if not args.submit:
        print(f"DRY RUN: {len(payload['urlList'])} public URLs; no notification sent")
        return
    with urlopen(payload["keyLocation"],timeout=20) as response:
        if response.read().decode().strip()!=key:
            raise SystemExit("Production key verification failed")
    request=Request(ENDPOINT,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json; charset=utf-8"},method="POST")
    with urlopen(request,timeout=25) as response:
        if response.status not in (200,202):
            raise SystemExit(f"IndexNow returned HTTP {response.status}")
        print(f"IndexNow accepted {len(payload['urlList'])} URLs: HTTP {response.status}; indexing not guaranteed")

if __name__=="__main__":
    main()
