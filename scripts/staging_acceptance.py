"""Explicit opt-in staging-only acceptance. Creates synthetic accounts; no real email.
Run: python -m pip install opencv-python-headless
     python scripts/staging_acceptance.py --create-test-data
"""
import argparse, base64, json, secrets, uuid, os, getpass
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlparse, parse_qs
import cv2
import numpy as np

ORIGIN = "https://loial-staging-staging.up.railway.app"
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener = build_opener(NoRedirect())
def call(path, body=None, headers=None, expected=200, method=None):
    req = Request(ORIGIN + path, data=None if body is None else json.dumps(body).encode(),
                  headers={"Content-Type":"application/json", **(headers or {})},
                  method=method or ("GET" if body is None else "POST"))
    try:
        with opener.open(req, timeout=25) as res:
            status, raw = res.status, res.read()
    except HTTPError as err:
        status, raw = err.code, err.read()
    allowed = (expected,) if isinstance(expected,int) else expected
    if status not in allowed:
        raise RuntimeError(f"{path.split('?')[0]}: expected {allowed}, got {status}")
    return json.loads(raw)
def check(condition, label):
    if not condition:
        raise RuntimeError(label)
    print("PASS", label, flush=True)
def token_from_url(url, name, path):
    u = urlparse(url)
    check(u.scheme == "https" and u.netloc == urlparse(ORIGIN).netloc and u.path == path,
          "QR uses staging origin and route")
    return parse_qs(u.query)[name][0]
def decode_qr(data):
    pixels = cv2.imdecode(np.frombuffer(base64.b64decode(data.split(",",1)[1]), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if pixels is None:
        raise RuntimeError("Invalid QR image")
    value, _, _ = cv2.QRCodeDetector().detectAndDecode(pixels)
    if not value:
        raise RuntimeError("Could not decode approval QR")
    return value
def run():
    tag = uuid.uuid4().hex[:12]
    print("Synthetic run:", tag, flush=True)
    call("/health")
    def merchant(suffix):
        mail = f"qa-{tag}-{suffix}@example.invalid"
        password = secrets.token_urlsafe(24)
        b = call("/api/register", {"email":mail,"password":password,"business_name":f"QA {tag} {suffix}"})
        logged = call("/auth/login", {"email":mail,"password":password})
        check(logged["user"]["role"] == "business" and logged["business_id"] == b["business_id"], "merchant login")
        return b["business_id"], {"Authorization":"Bearer "+logged["access_token"]}
    bid, owner = merchant("a")
    other, other_owner = merchant("b")
    def enroll(business):
        w = call("/api/enroll-sync", {"business_id":business,"name":"QA customer","uuid":str(uuid.uuid4()),"consent_loial_offers":True})
        return {"X-Loial-Wallet-Token":w["inbox_access"]}
    wallet, rival = enroll(bid), enroll(other)
    pin = "7819"
    for candidate in ("7819","8261","9632"):
        result = call("/api/my-business/staff", {"name":"QA staff","pin":candidate}, owner, (200,422))
        if result.get("status") == "added":
            pin = candidate
            break
    else:
        raise RuntimeError("Could not create QA staff")
    prefix = "/api/loial-receipts"
    key = call(prefix+"/integration/rotate", {}, owner)["api_key"]
    integration = {"X-Loial-Receipt-Key":key}
    payload = {"receipt_ref":"QA-"+tag,"currency":"RON","expires_days":1,"lines":[{"product":"QA coffee","quantity":2,"unit_price":12.5}]}
    receipt = call(prefix+"/integration/issue",payload,integration)
    check(receipt["status"]=="awaiting_payment" and receipt["total"]==25,"unpaid receipt")
    check(call(prefix+"/integration/issue",payload,integration)["claim_url"]==receipt["claim_url"],"identical reprint")
    call(prefix+"/integration/issue",{**payload,"lines":[{"product":"QA coffee","quantity":3,"unit_price":12.5}]},integration,409)
    t = token_from_url(receipt["claim_url"],"token","/loial-receipt.html")
    check(decode_qr(receipt["qr_png_base64"])==receipt["claim_url"],"printed QR matches receipt link")
    crm="/api/loial-crm/customers?min_purchases=1&product=QA%20coffee"
    check(call(crm,headers=owner)["total"]==0,"no verified purchase before payment")
    reserved=call(prefix+"/reserve",{"receipt_token":t},wallet)
    call(prefix+"/reserve",{"receipt_token":t},rival,409)
    approval=token_from_url(decode_qr(reserved["approval_qr"]),"receipt_approval","/scan.html")
    pay={"business_id":bid,"pin":pin,"approval_token":approval}
    call(prefix+"/confirm-payment",{**pay,"pin":"1234"},expected=401)
    result=call(prefix+"/confirm-payment",pay)
    check(result["status"]=="claimed" and result["stamp_granted"] and result["stamps"]==1,"paid exactly one stamp")
    call(prefix+"/confirm-payment",pay,expected=409)
    call(prefix+"/integration/issue",payload,integration,409)
    check(call(prefix+"/payment-status?token="+t,headers=wallet)["stamps"]==1,"wallet sees exactly one stamp")
    check(call(crm,headers=owner)["total"]==1,"purchase in merchant CRM")
    check(call(crm,headers=other_owner)["total"]==0,"other merchant CRM isolated")
    threads=call("/api/loial-inbox/threads",headers=wallet)["threads"]
    check(any(x["business_id"]==bid for x in threads),"stamp inbox grouped by merchant")
    # Explicitly exercise marketing permission, reactions and tenant boundaries.
    segment={"min_purchases":1,"product":"QA coffee","min_spend_minor":2500}
    inbox="/api/loial-inbox"
    call(inbox+"/crm-audience",{"segment":segment},owner,403)
    check(True,"FREE cannot access Business campaigns")
    admin_email=os.environ.get("LOIAL_QA_ADMIN_EMAIL") or "ciprianpop@academiadetrading.llc"
    admin_password=os.environ.get("LOIAL_QA_ADMIN_PASSWORD")
    if not admin_password:
        if not os.isatty(0):
            raise RuntimeError("Missing staging-only admin credential; configure runner secret or use local interactive execution")
        admin_password=getpass.getpass("STAGING admin password: ")
    admin_login=call("/auth/login",{"email":admin_email,"password":admin_password})
    check(admin_login["user"]["role"]=="admin","superadministrator login")
    admin={"Authorization":"Bearer "+admin_login["access_token"]}
    call("/api/admin/overview",headers=admin)
    grant_path="/api/admin/business/"+str(bid)+"/manual-plan"
    grant=call(grant_path,{"active":True,"reason":"Synthetic staging acceptance"},admin,method="PUT")
    check(grant["plan"]=="probusiness","manual Business grant without billing")
    check(call(inbox+"/crm-audience",{"segment":segment},owner)["eligible"]==1,"CRM audience preview")
    message={"subject":"QA synthetic offer","text":"Synthetic acceptance only","crm_segment":segment,"idempotency_key":"qa-"+tag}
    sent=call(inbox+"/send",message,owner)
    check(sent["sent"]==1 and sent["external_messages"]==0,"targeted native offer only")
    check(call(inbox+"/send",message,owner)["status"]=="already_delivered","campaign retry idempotent")
    thread=call(inbox+"/threads/"+str(bid),headers=wallet)["messages"]
    delivery=next(m["delivery_id"] for m in thread if m["subject"]==message["subject"])
    call("/api/loial-crm/reaction/"+str(delivery)+"/interested",{},rival,404)
    check(call("/api/loial-crm/reaction/"+str(delivery)+"/interested",{},wallet)["choice"]=="interested","customer offer reaction")
    call(inbox+"/preferences",{"business_id":bid,"enabled":False},wallet)
    check(call(inbox+"/crm-audience",{"segment":segment},owner)["eligible"]==0,"opt-out excludes customer")
    check(call(inbox+"/send",{**message,"idempotency_key":"qa-optout-"+tag},owner)["sent"]==0,"no campaign after opt-out")
    call("/api/admin/overview",headers=owner,expected=(401,403))
    email=f"qa-amb-{tag}@example.invalid"
    password=secrets.token_urlsafe(24)
    call("/api/ambassador/join",{"email":email,"name":"QA ambassador","password":password})
    logged=call("/auth/login",{"email":email,"password":password})
    check(logged["user"]["role"]=="ambassador","ambassador role")
    amb={"Authorization":"Bearer "+call("/api/ambassador/login",{"email":email,"password":password})["access_token"]}
    call("/api/admin/overview",headers=amb,expected=(401,403))
    call("/api/loial-crm/customers",headers=amb,expected=403)
    call(prefix+"/refund",{"receipt_ref":payload["receipt_ref"],"reason":"Synthetic acceptance cleanup"},owner)
    check(call(crm,headers=owner)["total"]==0,"refunded purchase removed from verified CRM")
    revoked=call(grant_path,{"active":False,"reason":"Synthetic staging acceptance complete"},admin,method="PUT")
    check(revoked["plan"]=="free","manual Business grant revoked")
    call(inbox+"/crm-audience",{"segment":segment},owner,403)
    print("PASS API acceptance; synthetic accounts remain in staging. Physical printer and mobile UI not tested.")
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--create-test-data",action="store_true",required=True)
    p.parse_args()
    run()
