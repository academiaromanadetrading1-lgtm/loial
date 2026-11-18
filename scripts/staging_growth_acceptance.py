"""Opt-in synthetic acceptance on isolated staging only, no real payments."""
import os, uuid, secrets
from staging_acceptance import call, check, token_from_url
def run():
    tag=uuid.uuid4().hex[:12]
    def register(suffix,ref=None):
        email=f"qa-growth-{tag}-{suffix}@example.invalid"
        payload={"email":email,"password":secrets.token_urlsafe(24),"business_name":"QA growth "+tag+" "+suffix}
        if ref:payload["ref_code"]=ref
        data=call("/api/register",payload)
        return data["business_id"],{"Authorization":"Bearer "+data["token"]}
    call("/health")
    root,owner=register("root")
    route="/api/biz-full/"+str(root)
    ent=call(route,headers=owner)
    check(ent["effective_plan"]=="start" and ent["premium_active"] is False,"FREE entitlement initial")
    w=call("/api/enroll-sync",{"business_id":root,"uuid":str(uuid.uuid4()),"name":"QA growth customer","email":f"qa-wallet-{tag}@example.invalid"})
    wallet={"X-Loial-Wallet-Token":w["inbox_access"]}
    prefix="/api/loial-merchant-referrals"
    call(prefix+"/me",expected=401)
    data=call(prefix+"/me",headers=wallet)
    code=data["code"]
    check(data["status"]=="customer" and data["registered_merchants"]==0,"customer referral issued")
    check(token_from_url(data["share_url"],"ref","/register.html")==code,"merchant QR destination")
    details={"name":"QA growth ambassador","email":f"qa-amb-growth-{tag}@example.invalid","password":secrets.token_urlsafe(24),"accept_terms":True}
    call(prefix+"/activate",details,wallet,409)
    referred,ref_owner=register("referred",code)
    data=call(prefix+"/me",headers=wallet)
    check(data["status"]=="eligible_for_activation" and data["registered_merchants"]==1,"first merchant qualifies")
    call(prefix+"/activate",{**details,"accept_terms":False},wallet,422)
    activation=call(prefix+"/activate",details,wallet)
    check(activation["status"]=="ambassador" and activation["assigned_merchants"]==1,"wallet ambassador activation")
    call(prefix+"/activate",details,wallet,409)
    future,_=register("future",code)
    check(call(prefix+"/me",headers=wallet)["registered_merchants"]==2,"future referral recorded")
    am=call("/api/ambassador/login",{"email":details["email"],"password":details["password"]})
    amb={"Authorization":"Bearer "+am["access_token"]}
    ledger=call("/api/loial-revenue/ambassador/me",headers=amb)
    check(ledger["direct_paid_businesses"]==0 and not ledger["entries"],"no commissions on FREE signup")
    check(len([x for x in ledger["firm_activity"] if x["source"]=="direct"])==2,"both firms attributed")
    login=call("/auth/login",{"email":"ciprianpop@academiadetrading.llc","password":os.environ["LOIAL_QA_ADMIN_PASSWORD"]})
    check(login["user"]["role"]=="admin","superadministrator login")
    admin={"Authorization":"Bearer "+login["access_token"]}
    grant="/api/admin/business/"+str(root)+"/manual-plan"
    call(grant,{"active":True,"reason":"Synthetic growth acceptance"},admin,method="PUT")
    try:
        paid=call(route,headers=owner)
        check(paid["premium_active"] is True and paid["effective_plan"] in ("business","probusiness"),"premium entitlement granted")
        check(call("/api/biz-full/"+str(referred),headers=ref_owner)["premium_active"] is False,"other merchant remains free")
    finally:
        call(grant,{"active":False,"reason":"Synthetic growth acceptance cleanup"},admin,method="PUT")
    check(call(route,headers=owner)["premium_active"] is False,"premium revoked")
    print("PASS growth staging acceptance; synthetic data only",flush=True)
if __name__=="__main__":
    run()
