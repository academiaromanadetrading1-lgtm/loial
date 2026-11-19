"""Synthetic final release acceptance, restricted to staging origin."""
import os, secrets, uuid
from urllib.request import Request
from staging_acceptance import call, check, opener, ORIGIN

def html(path,headers=None):
    with opener.open(Request(ORIGIN+path,headers=headers or {}),timeout=25) as res:
        return res.read().decode("utf-8")

def run():
    tag=uuid.uuid4().hex[:10]
    page=html("/")
    for marker in ('id="walletCard"','id="addStamp"','id="pentru-cine"','id="cum-functioneaza"','data-founders="ticker"','30 exemple fictive'):
        check(marker in page,"homepage "+marker)
    check('data-founders="gallery"' in html("/fondatori"),"founder gallery")
    before=call("/api/loial-founders")
    check(before["capacity"]==500 and before["remaining"]+before["reserved"]==500,"capacity accounting")
    mail=f"qa-founder-{tag}@example.invalid"
    password=secrets.token_urlsafe(24)
    owner=call("/api/register",{"email":mail,"password":password,"business_name":"QA synthetic founder "+tag})
    bid=owner["business_id"]
    bearer={"Authorization":"Bearer "+owner["token"]}
    check('id="walletCard"' in html("/",bearer),"public landing remains public")
    route=f"/api/admin/founders/{bid}"
    payload={"city":"QA","consent_reference":"Synthetic staging approval "+tag,"verified":True}
    call(route,payload,bearer,403,method="PUT")
    logged=call("/auth/login",{"email":"ciprianpop@academiadetrading.llc","password":os.environ["LOIAL_QA_ADMIN_PASSWORD"]})
    check(logged["user"]["role"]=="admin","superadmin login")
    admin={"Authorization":"Bearer "+logged["access_token"]}
    call(route,{**payload,"verified":False},admin,422,method="PUT")
    approved=call(route,payload,admin,method="PUT")
    slot=approved["slot"]
    try:
        public=call("/api/loial-founders")
        member=next(x for x in public["members"] if x["slot"]==slot)
        check(member["name"]=="QA synthetic founder "+tag,"approved firm publicly listed")
        check("consent_reference" not in member and "email" not in member,"private data excluded")
        check(call(route,payload,admin,method="PUT")["slot"]==slot,"no duplicate slot")
    finally:
        call(route,headers=admin,method="DELETE")
    after=call("/api/loial-founders")
    check(all(x["slot"]!=slot for x in after["members"]),"withdrawal hides founder")
    check(after["reserved"]==before["reserved"]+1,"reserved slot retained")
    print("PASS final founders acceptance; synthetic staging only",flush=True)

if __name__=="__main__":
    run()
