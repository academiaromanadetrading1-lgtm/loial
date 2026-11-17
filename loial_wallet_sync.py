"""Google Wallet loyalty card refresh after Loial stamp/redeem/receipt events.

OFF until issuer credentials + explicit LOIAL_GOOGLE_WALLET_SYNC_ENABLED=1.
The wallet object is read before PATCH, never overwritten with a partial PUT.
Scopes: https://www.googleapis.com/auth/wallet_object.issuer.
Does not access an actual issuer in tests or before configuration.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import httpx
from jose import jwt
from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import IntegrityError

from loial_premium_wallet import premium_card, google_pass_payload, google_ready

BaseSync=declarative_base()
SYNC_ENABLED="LOIAL_GOOGLE_WALLET_SYNC_ENABLED"
GOOGLE_SCOPE="https://www.googleapis.com/auth/wallet_object.issuer"
GOOGLE_TOKEN_URL="https://oauth2.googleapis.com/token"
GOOGLE_OBJECT_ROOT="https://walletobjects.googleapis.com/walletobjects/v1/loyaltyObject/"
_loop_started=False
_loop_lock=threading.Lock()

class WalletSyncItem(BaseSync):
    __tablename__="loial_google_wallet_sync_items"
    id=Column(Integer,primary_key=True)
    business_id=Column(Integer,nullable=False,index=True)
    wallet_uuid=Column(String(120),nullable=False)
    requested_version=Column(Integer,nullable=False,default=1)
    synced_version=Column(Integer,nullable=False,default=0)
    status=Column(String(25),default="pending")
    attempts=Column(Integer,default=0)
    last_error=Column(String(240),default="")
    updated_at=Column(String(40),nullable=False)
    __table_args__=(UniqueConstraint("business_id","wallet_uuid",name="uq_loial_google_card_sync"),)

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def queue_google_refresh(db,business_id,wallet_uuid):
    """Add to the same DB transaction as stamp/receipt; no external API here."""
    if not wallet_uuid:
        return False
    entry=db.query(WalletSyncItem).filter(
        WalletSyncItem.business_id==business_id,
        WalletSyncItem.wallet_uuid==wallet_uuid).first()
    if entry:
        entry.requested_version+=1
        entry.status="pending"
        entry.attempts=0
        entry.last_error=""
        entry.updated_at=timestamp()
    else:
        db.add(WalletSyncItem(business_id=business_id,wallet_uuid=wallet_uuid,
                              requested_version=1,synced_version=0,
                              status="pending",attempts=0,last_error="",updated_at=timestamp()))
    return True

def sync_active():
    return os.getenv(SYNC_ENABLED,"0")=="1" and google_ready("customer")

def oauth_assertion(service_account,clock=None):
    now_seconds=int(clock if clock is not None else time.time())
    fields=("client_email","private_key","token_uri")
    if any(not service_account.get(key) for key in fields):
        raise ValueError("Google service account is incomplete")
    if service_account["token_uri"]!=GOOGLE_TOKEN_URL:
        raise ValueError("Google OAuth URL not expected")
    claims={"iss":service_account["client_email"],"scope":GOOGLE_SCOPE,
            "aud":GOOGLE_TOKEN_URL,"iat":now_seconds,"exp":now_seconds+3500}
    return jwt.encode(claims,service_account["private_key"],algorithm="RS256")

def google_object_id(card,service_account,class_id):
    payload=google_pass_payload(card,service_account["client_email"],class_id)
    return payload["payload"]["loyaltyObjects"][0]["id"]

def make_customer_card(business,customer,wallet_uuid):
    return premium_card(customer.name,"customer",business.name,
         "https://loial.space/scan.html?wallet_uuid="+wallet_uuid,
         "client:"+str(business.id)+":"+wallet_uuid,
         stamps=customer.stamps or 0,target=getattr(business,"stamps_required",None) or 6)

def google_patch_body(card):
    return {"loyaltyPoints":{"label":"Ștampile",
                             "balance":{"int":int(card["stamps"])}},
            "secondaryLoyaltyPoints":{"label":"Până la premiu",
                                      "balance":{"int":max(0,int(card["target"])-int(card["stamps"]))}},
            "textModulesData":[
                {"id":"status","header":"Statut","body":card["status"]},
                {"id":"merchant","header":"Afacere","body":card["entity"]}]}

def request_google_refresh(card,transport=None):
    """Synchronously fetch, compare and patch an already-created Google LoyaltyObject.

    Called only from the opt-in background worker; never on QR scan's request path.
    """
    if not sync_active():
        return "disabled"
    try:
        credentials=json.loads(os.environ["LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON"])
        assertion=oauth_assertion(credentials)
        from loial_google_issuer import loyalty_class_id_for_business
        # The same class ID must be used when issuing and refreshing each card.
        business_id=int(card["id"].split(":",2)[1])
        class_id=loyalty_class_id_for_business(business_id)
        obj=google_object_id(card,credentials,class_id)
    except (KeyError,ValueError,TypeError) as error:
        raise RuntimeError("Google Wallet issuer configuration invalid") from error
    options={"timeout":12}
    if transport is not None:
        options["transport"]=transport
    with httpx.Client(**options) as client:
        token=client.post(GOOGLE_TOKEN_URL,data={
            "grant_type":"urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion":assertion})
        token.raise_for_status()
        bearer=token.json().get("access_token")
        if not bearer:
            raise RuntimeError("Google OAuth token absent")
        headers={"Authorization":"Bearer "+bearer}
        current=client.get(GOOGLE_OBJECT_ROOT+obj,headers=headers)
        if current.status_code==404:
            return "not_saved"
        current.raise_for_status()
        existing=current.json()
        old=(existing.get("loyaltyPoints") or {}).get("balance") or {}
        secondary=(existing.get("secondaryLoyaltyPoints") or {}).get("balance") or {}
        old_status=next((x.get("body") for x in existing.get("textModulesData",[])
                         if x.get("id")=="status"),None)
        remaining=max(0,int(card["target"])-int(card["stamps"]))
        if (str(old.get("int"))==str(card["stamps"])
            and str(secondary.get("int"))==str(remaining)
            and old_status==card["status"]):
            return "unchanged"
        patch=client.patch(GOOGLE_OBJECT_ROOT+obj,headers=headers,
                           json=google_patch_body(card))
        patch.raise_for_status()
        return "updated"

def run_google_sync_cycle(db,BusinessAccount,Customer,updater=request_google_refresh,
                          max_items=20):
    if not sync_active():
        return {"status":"disabled","processed":0}
    work=db.query(WalletSyncItem).filter(
        WalletSyncItem.status=="pending").order_by(WalletSyncItem.id).limit(max_items).all()
    done=[]
    for entry in work:
        business=db.query(BusinessAccount).filter(BusinessAccount.id==entry.business_id).first()
        customer=db.query(Customer).filter(
            Customer.business_id==entry.business_id,
            (Customer.wallet_uuid==entry.wallet_uuid) |
            (Customer.uuid==entry.wallet_uuid)).first()
        if not business or not customer:
            entry.status="skipped"
            entry.last_error="Cardul Loial nu mai exista"
            db.commit()
            done.append("skipped")
            continue
        version=entry.requested_version
        try:
            card=make_customer_card(business,customer,entry.wallet_uuid)
            outcome=updater(card)
            if outcome in ("updated","unchanged","not_saved"):
                entry.synced_version=version
                entry.status="pending" if entry.requested_version>version else outcome
                entry.attempts=0
                entry.last_error=""
            else:
                entry.status="pending"
                entry.last_error="Emitere Google temporar indisponibila"
        except (httpx.HTTPError,RuntimeError,ValueError,KeyError) as exc:
            entry.attempts+=1
            entry.last_error=type(exc).__name__[:80]
            entry.status="pending" if entry.attempts<5 else "failed"
            outcome="retry"
        entry.updated_at=timestamp()
        db.commit()
        done.append(outcome)
    return {"status":"processed","processed":len(done),"outcomes":done}

def background_loop(factory,models,stop):
    while not stop.is_set():
        db=factory()
        try:
            run_google_sync_cycle(db,*models)
        except Exception:
            db.rollback()
            logging.getLogger("loial_wallet_sync").exception("Google Wallet sync loop failed")
        finally:
            db.close()
        stop.wait(180)

def start_google_sync_worker(engine,factory,models):
    BaseSync.metadata.create_all(bind=engine)
    if not sync_active():
        return False
    global _loop_started
    with _loop_lock:
        if _loop_started:
            return False
        stop=threading.Event()
        worker=threading.Thread(target=background_loop,args=(factory,models,stop),
                                name="loial-google-wallet-sync",daemon=True)
        worker.start()
        _loop_started=True
        return True
