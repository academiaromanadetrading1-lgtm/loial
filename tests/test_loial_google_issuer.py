"""Google Wallet direct issuer, merchant-specific branded class and pilot guardrails."""
import json
from urllib.parse import urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from loial_google_issuer import (
    loyalty_class_id_for_business,merchant_class_payload,ensure_google_class,
    configured_issuer,valid_class_id,generic_class_payload
)
from loial_premium_wallet import premium_card,google_pass_payload,google_save_url


@pytest.fixture
def google_config(monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=key.private_bytes(serialization.Encoding.PEM,
                          serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
    account={"client_email":"loial-test@project-000.iam.gserviceaccount.com",
             "private_key":pem,"token_uri":"https://oauth2.googleapis.com/token"}
    monkeypatch.setenv("LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON",json.dumps(account))
    monkeypatch.setenv("LOIAL_GOOGLE_LOYALTY_CLASS_ID","123456789012.loial_default")
    monkeypatch.setenv("LOIAL_GOOGLE_AMBASSADOR_CLASS_ID","123456789012.loial_ambassador")
    monkeypatch.setenv("LOIAL_GOOGLE_MERCHANT_CLASSES","1")
    return account


def test_merchant_branding_is_separate_for_each_business(google_config):
    a=loyalty_class_id_for_business(1)
    b=loyalty_class_id_for_business(100)
    assert a=="123456789012.loial_business_1_v1"
    assert b=="123456789012.loial_business_100_v1"
    assert a!=b
    payload=merchant_class_payload(b,"Service Auto Pop")
    assert payload["programName"]=="Service Auto Pop"
    assert payload["hexBackgroundColor"]=="#0D0E11"
    assert payload["programLogo"]["sourceUri"]["uri"].startswith("https://loial.space/")
    assert payload["reviewStatus"]=="UNDER_REVIEW"


def test_google_direct_class_is_idempotent_and_uses_authorized_official_api(google_config):
    class_id=loyalty_class_id_for_business(7)
    events=[]
    def mock(req):
        events.append((req.method,str(req.url),req.headers.get("authorization")))
        if req.url.path=="/token":
            return httpx.Response(200,json={"access_token":"TEST-OAUTH"})
        assert req.headers["authorization"]=="Bearer TEST-OAUTH"
        assert req.url.host=="walletobjects.googleapis.com"
        if req.method=="GET":
            return httpx.Response(404,json={"error":{"message":"Not found"}})
        payload=json.loads(req.content)
        assert payload["id"]==class_id
        return httpx.Response(200,json=payload)
    result=ensure_google_class("loyalty",class_id,"Atelier Auto",
                               transport=httpx.MockTransport(mock))
    assert result==class_id
    assert [event[0] for event in events]==["POST","GET","POST"]
    assert events[2][1].endswith("/loyaltyClass")


def test_google_existing_class_is_not_recreated(google_config):
    class_id=loyalty_class_id_for_business(5)
    received=[]
    def mock(req):
        received.append(req.method)
        if req.url.path=="/token":
            return httpx.Response(200,json={"access_token":"TEST-OAUTH"})
        return httpx.Response(200,json={"id":class_id,"reviewStatus":"approved"})
    assert ensure_google_class("loyalty",class_id,"Spalatorie",
                               transport=httpx.MockTransport(mock))==class_id
    assert received==["POST","GET"]


def test_google_draft_class_is_not_issued(google_config):
    class_id=loyalty_class_id_for_business(3)
    def mock(req):
        if req.url.path=="/token":
            return httpx.Response(200,json={"access_token":"TEST-OAUTH"})
        return httpx.Response(200,json={"id":class_id,"reviewStatus":"DRAFT"})
    with pytest.raises(RuntimeError,match="not ready"):
        ensure_google_class("loyalty",class_id,"Test",
                            transport=httpx.MockTransport(mock))


def test_google_save_signed_jwt_shows_person_status_and_business(google_config):
    card=premium_card("Alex Test","customer","Self Wash Timișoara",
                      "https://loial.space/scan.html?wallet_uuid=abc",
                      "client:22:abc",stamps=4,target=6)
    class_id=loyalty_class_id_for_business(22)
    link=google_save_url(card,class_id_override=class_id)
    assert link.startswith("https://pay.google.com/gp/v/save/")
    assert len(link)<1800
    token=link.rsplit("/",1)[-1]
    account=google_config
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    signer=load_pem_private_key(account["private_key"].encode(),password=None)
    public_pem=signer.public_key().public_bytes(
       serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    data=jwt.decode(token,public_pem,algorithms=["RS256"],
                    audience="google",options={"verify_iss":False})
    obj=data["payload"]["loyaltyObjects"][0]
    assert obj["classId"]==class_id
    assert obj["accountName"]=="Alex Test"
    assert obj["loyaltyPoints"]["balance"]["int"]==4
    assert obj["secondaryLoyaltyPoints"]["balance"]["int"]==2
    assert any(x["body"]=="Self Wash Timișoara" for x in obj["textModulesData"])


def test_google_ambassador_generic_pass_has_brand_logo(google_config):
    card=premium_card("Alex","ambassador","Loial",
                      "https://loial.space/register.html?ref=LOIAL123",
                      "ambassador:7",status="AMBASADOR SENIOR")
    data=google_pass_payload(card,google_config["client_email"],
                             "123456789012.loial_ambassador")["payload"]["genericObjects"][0]
    assert data["hexBackgroundColor"]=="#0D0E11"
    assert data["logo"]["sourceUri"]["uri"].endswith("/brand.png")
    assert data["subheader"]["defaultValue"]["value"]=="AMBASADOR SENIOR"


def test_no_external_calls_when_google_credentials_are_not_configured(monkeypatch):
    monkeypatch.delenv("LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON",raising=False)
    assert configured_issuer() is None
    with pytest.raises(ValueError,match="not configured"):
        ensure_google_class("loyalty","123456789012.loial_business_1_v1","Firma")
    assert not valid_class_id("https://evil.example/path")

@pytest.mark.parametrize("status",["REJECTED","REVIEW_STATUS_UNSPECIFIED","", "rejected"])
def test_rejected_or_unapproved_google_class_is_blocked(google_config,status):
    class_id=loyalty_class_id_for_business(18)
    def mock(req):
        if req.url.path=="/token":
            return httpx.Response(200,json={"access_token":"TEST-OAUTH"})
        return httpx.Response(200,json={"id":class_id,"reviewStatus":status})
    with pytest.raises(RuntimeError,match="not ready"):
        ensure_google_class("loyalty",class_id,"Salon",
                            transport=httpx.MockTransport(mock))
