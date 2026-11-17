"""Google Wallet issuer provisioning for the Loial-first 100-firm pilot.

Uses one Google Wallet issuer account for Loial. Merchants get distinct branded
loyalty classes, while each customer receives an independently refreshable object.
Actual HTTP calls are impossible without explicit Google issuer credentials.
"""
import json
import os
import re
import threading
import time

import httpx

GOOGLE_API = "https://walletobjects.googleapis.com/walletobjects/v1"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/wallet_object.issuer"
LOGO_URI = "https://loial.space/api/premium-wallet/brand.png"
_cache = {}
_lock = threading.Lock()

def merchant_classes_enabled():
    return os.getenv("LOIAL_GOOGLE_MERCHANT_CLASSES","0") == "1"

def configured_issuer():
    try:
        account=json.loads(os.environ["LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON"])
        if not account["client_email"].endswith(".gserviceaccount.com"):
            return None
        if not account["private_key"]:
            return None
        return account
    except (KeyError,ValueError,TypeError):
        return None

def valid_class_id(value):
    return isinstance(value,str) and bool(re.fullmatch(
        r"[0-9]{6,}\.[A-Za-z0-9._-]+", value))

def loyalty_class_id_for_business(business_id):
    configured=os.getenv("LOIAL_GOOGLE_LOYALTY_CLASS_ID","")
    if not valid_class_id(configured):
        raise ValueError("Google Wallet Loyalty Class ID invalid")
    if not merchant_classes_enabled():
        return configured
    if not isinstance(business_id,int) or business_id<=0:
        raise ValueError("Business ID invalid")
    issuer=configured.split(".",1)[0]
    return issuer+".loial_business_"+str(business_id)+"_v1"

def merchant_class_payload(class_id, merchant_name):
    if not valid_class_id(class_id):
        raise ValueError("Google Wallet class ID invalid")
    label=(merchant_name or "Loial").strip()
    if not label:
        label="Loial"
    return {
        "id":class_id,
        "issuerName":"Loial",
        "programName":label[:80],
        "programLogo":{"sourceUri":{"uri":LOGO_URI},
                       "contentDescription":{"defaultValue":{
                         "language":"ro","value":"Loial Black Metal"}}},
        "reviewStatus":"UNDER_REVIEW",
        "hexBackgroundColor":"#0D0E11",
        "accountNameLabel":"Titular",
        "accountIdLabel":"Card Loial",
        "rewardsTierLabel":"Statut",
        "countryCode":"RO",
        "homepageUri":{"uri":"https://loial.space","description":"Portofel Loial"},
    }

def generic_class_payload(class_id):
    if not valid_class_id(class_id):
        raise ValueError("Google Wallet class ID invalid")
    return {"id":class_id}

def obtain_google_oauth_token(client, account):
    from loial_wallet_sync import oauth_assertion, GOOGLE_TOKEN_URL
    jwt_assertion=oauth_assertion(account)
    response=client.post(GOOGLE_TOKEN_URL,data={
        "grant_type":"urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion":jwt_assertion})
    response.raise_for_status()
    bearer=response.json().get("access_token")
    if not bearer:
        raise RuntimeError("Google Wallet API access token missing")
    return bearer

def ensure_google_class(kind, class_id, merchant_name="Loial", transport=None,
                        now=None):
    """Ensure issuer-side template exists. Only called for a verified pass holder.

    Only our fixed official API base is contacted, so user-provided names are never
    used as request URLs. A cache avoids API requests for every card in one process.
    """
    if kind not in ("loyalty","generic"):
        raise ValueError("Unsupported Wallet class")
    if not valid_class_id(class_id):
        raise ValueError("Invalid Wallet class")
    account=configured_issuer()
    if account is None:
        raise ValueError("Google Wallet issuer not configured")
    ts=time.monotonic() if now is None else now
    key=(kind,class_id)
    if transport is None and _cache.get(key,0)>ts:
        return class_id
    path="loyaltyClass" if kind=="loyalty" else "genericClass"
    payload=merchant_class_payload(class_id,merchant_name) if kind=="loyalty" else generic_class_payload(class_id)
    config={"timeout":12}
    if transport is not None:
        config["transport"]=transport
    with httpx.Client(**config) as client:
        bearer=obtain_google_oauth_token(client,account)
        headers={"Authorization":"Bearer "+bearer}
        existing=client.get(f"{GOOGLE_API}/{path}/{class_id}",headers=headers)
        if existing.status_code==404:
            created=client.post(f"{GOOGLE_API}/{path}",headers=headers,json=payload)
            # Multiple workers may have created the same class concurrently.
            if created.status_code==409:
                created=client.get(f"{GOOGLE_API}/{path}/{class_id}",headers=headers)
            created.raise_for_status()
            result=created.json()
        else:
            existing.raise_for_status()
            result=existing.json()
        if result.get("id") != class_id:
            raise RuntimeError("Google Wallet class ID mismatch")
        if kind=="loyalty":
            review=str(result.get("reviewStatus","")).upper()
            if (review in ("DRAFT","REVIEW_STATUS_UNSPECIFIED","REJECTED","")
                    or review not in ("UNDER_REVIEW","APPROVED")):
                raise RuntimeError("Google Wallet class is not ready; review status: "+review)
    if transport is None:
        with _lock:
            _cache[key]=ts+3600
    return class_id
