"""Signed Apple/Google Wallet passes for Loial premium loyalty & ambassador cards.

No credential -> no official "Add to Wallet" link; the Black Metal web preview
still works. Never sign a pass from a public QR alone. Card QR values are public
membership/referral locators, never authorization credentials.
"""
import hashlib
import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from jose import JWTError, jwt
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from loial_inbox import WalletInboxAccess, access_hash
from loial_identity import BusinessAmbassadorLink

BLACK = "#0D0E11"
GOLD = "#D8BE7A"
GOLD_SOFT = "#F3E6BE"

def member_status(stamps:int,target:int)->str:
    if target>0 and stamps>=target:
        return "RECOMPENSA DISPONIBILA"
    return "MEMBRU LOIAL"

def premium_card(holder,role,entity,qr_value,card_id,stamps=0,target=0,status=None):
    """Strict presentation data; holder identity must be checked before calling."""
    if role not in ("customer","ambassador"):
        raise ValueError("Invalid card role")
    if not isinstance(qr_value,str) or len(qr_value)>512:
        raise ValueError("QR value invalid")
    result={"id":str(card_id)[:100],"holder":str(holder or "Titular Loial")[:80],
            "role":role,"brand":"LOIAL","entity":str(entity)[:75],
            "status":str(status or (member_status(stamps,target) if role=="customer" else "AMBASADOR"))[:60],
            "qr_value":qr_value,"theme":"black-metal","issuer":"Loial",
            "is_payment_card":False}
    if role=="customer":
        result["stamps"]=int(stamps)
        result["target"]=int(target)
    return result

def apple_ready():
    names=("LOIAL_APPLE_PASS_TYPE_ID","LOIAL_APPLE_TEAM_ID",
           "LOIAL_APPLE_PASS_CERT_PEM","LOIAL_APPLE_PASS_KEY_PEM",
           "LOIAL_APPLE_WWDR_CERT_PEM")
    return all(bool(os.getenv(x,"").strip()) for x in names)

def google_ready(role):
    account=os.getenv("LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON","")
    class_id=os.getenv("LOIAL_GOOGLE_LOYALTY_CLASS_ID" if role=="customer"
                       else "LOIAL_GOOGLE_AMBASSADOR_CLASS_ID","")
    return bool(account and class_id)

def localized(value,lang="ro"):
    return {"defaultValue":{"language":lang,"value":value[:100]}}

def google_pass_payload(card,issuer,class_id):
    if not re.fullmatch(r"[0-9]{6,}\.[A-Za-z0-9._-]+",class_id):
        raise ValueError("Google class ID must be issuerId.classSuffix")
    obj_id=class_id.split(".")[0]+"."+hashlib.sha256(
        ("loial:"+card["id"]+":"+card["role"]).encode()).hexdigest()[:32]
    common={"id":obj_id,"classId":class_id,"state":"ACTIVE",
            "barcode":{"type":"QR_CODE","value":card["qr_value"]}}
    if card["role"]=="customer":
        common.update({"accountId":hashlib.sha256(card["id"].encode()).hexdigest()[:12].upper(),
                       "accountName":card["holder"],
                       "loyaltyPoints":{"label":"Stampile","balance":{"int":card["stamps"]}}})
        payload={"loyaltyObjects":[common]}
    else:
        common.update({"genericType":"GENERIC_TYPE_UNSPECIFIED",
                       "hexBackgroundColor":BLACK,
                       "cardTitle":localized("LOIAL • BLACK METAL"),
                       "header":localized(card["holder"]),
                       "subheader":localized(card["status"]),
                       "textModulesData":[{"id":"role","header":"Statut","body":card["status"]}]})
        payload={"genericObjects":[common]}
    return {"iss":issuer,"aud":"google","typ":"savetowallet",
            "iat":int(time.time()),"origins":[],"payload":payload}

def google_save_url(card):
    try:
        account=json.loads(os.environ["LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON"])
        issuer=account["client_email"]
        key=account["private_key"]
        class_id=os.environ["LOIAL_GOOGLE_LOYALTY_CLASS_ID"
                           if card["role"]=="customer" else "LOIAL_GOOGLE_AMBASSADOR_CLASS_ID"]
        if not issuer.endswith(".gserviceaccount.com"):
            raise ValueError("Google service account invalid")
        payload=google_pass_payload(card,issuer,class_id)
        token=jwt.encode(payload,key,algorithm="RS256")
        return "https://pay.google.com/gp/v/save/"+token
    except (KeyError,ValueError,TypeError) as exc:
        raise ValueError("Google Wallet issuer is not configured correctly") from exc

def apple_pass_json(card):
    pass_id=os.environ["LOIAL_APPLE_PASS_TYPE_ID"]
    team_id=os.environ["LOIAL_APPLE_TEAM_ID"]
    serial=hashlib.sha256(("loial:"+card["role"]+":"+card["id"]).encode()).hexdigest()[:32]
    common={
        "formatVersion":1,"passTypeIdentifier":pass_id,"teamIdentifier":team_id,
        "serialNumber":serial,"organizationName":"Loial",
        "description":"Card digital Loial • nu este card bancar",
        "logoText":"LOIAL  BLACK METAL",
        "foregroundColor":"rgb(239,224,185)",
        "labelColor":"rgb(199,176,123)",
        "backgroundColor":"rgb(12,13,16)",
        "barcodes":[{"format":"PKBarcodeFormatQR","message":card["qr_value"],
                      "messageEncoding":"iso-8859-1"}],
        "sharingProhibited":False
    }
    # Activam suportul de actualizare Apple doar cand sunt configurate secretele
    # emitentului si stocarea criptata a tokenurilor de dispozitiv.
    from loial_apple_updates import apple_updates_ready, pass_authentication_token
    if apple_updates_ready():
        common["webServiceURL"]=os.environ["LOIAL_APPLE_WEB_SERVICE_URL"].rstrip("/")+"/"
        common["authenticationToken"]=pass_authentication_token(serial)
    fields={
        "primaryFields":[{"key":"holder","label":"TITULAR","value":card["holder"]}],
        "secondaryFields":[{"key":"status","label":"STATUT","value":card["status"]}],
        "auxiliaryFields":[{"key":"entity","label":"CARD LOIAL","value":card["entity"]}],
        "backFields":[{"key":"disclaimer","label":"Tip card","value":"Card de fidelitate, nu instrument de plata."}]
    }
    if card["role"]=="customer":
        fields["auxiliaryFields"].append(
            {"key":"stamps","label":"STAMPile","value":str(card["stamps"])+"/"+str(card["target"])})
        common["storeCard"]=fields
    else:
        common["generic"]=fields
    return common

def _image_assets():
    """Dark metallic-brushed artwork: icon, logo, strip, and retina scales."""
    result={}
    for scale in (1,2,3):
        icon=Image.new("RGBA",(29*scale,29*scale),(12,13,16,255))
        pen=ImageDraw.Draw(icon)
        pen.rounded_rectangle((2*scale,2*scale,27*scale,27*scale),
                              radius=6*scale,outline=(216,190,122),width=2*scale)
        pen.line((8*scale,15*scale,13*scale,21*scale,22*scale,8*scale),
                 fill=(239,224,185),width=2*scale)
        logo=Image.new("RGBA",(160*scale,50*scale),(12,13,16,255))
        d=ImageDraw.Draw(logo)
        d.ellipse((8*scale,7*scale,42*scale,42*scale),
                  outline=(216,190,122),width=3*scale)
        d.line((16*scale,23*scale,23*scale,31*scale,35*scale,14*scale),
               fill=(239,224,185),width=3*scale)
        strip=Image.new("RGB",(375*scale,123*scale),(13,14,17))
        pixels=strip.load()
        for y in range(123*scale):
            for x in range(375*scale):
                shine=max(0,35-abs(x/(375*scale)-.32)*92)
                brush=(y//(3*scale))%4
                tone=int(12+shine+brush)
                pixels[x,y]=(tone,tone+1,tone+3)
        d=ImageDraw.Draw(strip)
        d.line([(10*scale,100*scale),(365*scale,50*scale)],
               fill=(95,80,49),width=2*scale)
        for name,img in (("icon",icon),("logo",logo),("strip",strip)):
            b=io.BytesIO()
            img.save(b,format="PNG")
            suffix="" if scale==1 else "@"+str(scale)+"x"
            result[name+suffix+".png"]=b.getvalue()
    return result

def signed_apple_pkpass(card):
    if not apple_ready():
        raise ValueError("Apple Wallet certificate has not been configured")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key, pkcs7
        from cryptography.hazmat.primitives import hashes
        pem=lambda name:os.environ[name].replace("\\n","\n").encode()
        signer=x509.load_pem_x509_certificate(pem("LOIAL_APPLE_PASS_CERT_PEM"))
        wwdr=x509.load_pem_x509_certificate(pem("LOIAL_APPLE_WWDR_CERT_PEM"))
        key=load_pem_private_key(pem("LOIAL_APPLE_PASS_KEY_PEM"),password=None)
        files=_image_assets()
        files["pass.json"]=json.dumps(apple_pass_json(card),ensure_ascii=False,
                                      separators=(",",":")).encode()
        manifest={name:hashlib.sha1(data).hexdigest() for name,data in sorted(files.items())}
        files["manifest.json"]=json.dumps(manifest,separators=(",",":")).encode()
        files["signature"]=(pkcs7.PKCS7SignatureBuilder()
                            .set_data(files["manifest.json"])
                            .add_signer(signer,key,hashes.SHA256())
                            .add_certificate(wwdr)
                            .sign(Encoding.DER,
                                  [pkcs7.PKCS7Options.DetachedSignature,
                                   pkcs7.PKCS7Options.Binary]))
        output=io.BytesIO()
        with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as z:
            for name,data in files.items():
                z.writestr(name,data)
        return output.getvalue()
    except (KeyError,ValueError,TypeError) as exc:
        raise ValueError("Apple PassKit signing credentials invalid") from exc

def install_premium_wallet(app,engine,session_factory,BusinessAccount,Customer,
                           SalesAgent,Sale,secret,algorithm,tier_func,identity_model):
    router=APIRouter(prefix="/api/premium-wallet",tags=["Loial Premium Wallet"])

    def session():
        db=session_factory()
        try:
            yield db
        finally:
            db.close()

    def wallet(request:Request,db:Session=Depends(session)):
        token=(request.headers.get("X-Loial-Wallet-Token") or "").strip()
        if not (40<=len(token)<=180):
            raise HTTPException(status_code=401,detail="Activeaza mai intai portofelul privat Loial")
        record=db.query(WalletInboxAccess).filter(
            WalletInboxAccess.token_hash==access_hash(token)).first()
        if not record:
            raise HTTPException(status_code=401,detail="Token privat de portofel invalid")
        return record

    def ambassador(request:Request,db:Session=Depends(session)):
        authorization=request.headers.get("Authorization") or ""
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401,detail="Autentificare de ambasador necesara")
        try:
            claims=jwt.decode(authorization[7:],secret,algorithms=[algorithm])
        except JWTError:
            raise HTTPException(status_code=401,detail="Sesiune invalida")
        if claims.get("role")=="ambassador":
            agent=db.query(SalesAgent).filter(SalesAgent.email==claims.get("sub"),
                                             SalesAgent.active.is_(True)).first()
        elif claims.get("role")=="business":
            biz=db.query(BusinessAccount).filter(
                BusinessAccount.email==claims.get("sub")).first()
            linked=db.query(identity_model).filter(
                identity_model.business_id==biz.id).first() if biz else None
            agent=db.query(SalesAgent).filter(SalesAgent.id==linked.agent_id,
                         SalesAgent.active.is_(True)).first() if linked else None
        else:
            agent=None
        if not agent:
            raise HTTPException(status_code=403,detail="Contul de ambasador nu este activ pentru acest profil")
        return agent

    def customer_card(wallet_record,business_id,db):
        matches=db.query(Customer).filter(
            Customer.business_id==business_id,
            (Customer.uuid==wallet_record.wallet_uuid) |
            (Customer.wallet_uuid==wallet_record.wallet_uuid)).all()
        if not matches:
            raise HTTPException(status_code=404,detail="Cardul acestei afaceri nu exista in portofel")
        c=matches[0]
        biz=db.query(BusinessAccount).filter(BusinessAccount.id==business_id).first()
        if not biz:
            raise HTTPException(status_code=404,detail="Afacerea nu exista")
        target=getattr(biz,"stamps_required",None) or 6
        return premium_card(c.name,"customer",biz.name,
              "https://loial.space/scan.html?wallet_uuid="+wallet_record.wallet_uuid,
              "client:"+str(business_id)+":"+wallet_record.wallet_uuid,
              stamps=c.stamps or 0,target=target)

    def ambassador_card(agent,db):
        active=db.query(Sale).filter(Sale.agent_id==agent.id,Sale.status=="completed").count()
        rank=tier_func(active)["rank"]
        return premium_card(agent.name,"ambassador","RETEAUA LOIAL",
              "https://loial.space/register.html?ref="+agent.qr_code,
              "ambassador:"+str(agent.id),status=rank.upper())

    @router.get("/availability")
    def availability():
        return {"apple_ready":apple_ready(),"google_customer_ready":google_ready("customer"),
                "google_ambassador_ready":google_ready("ambassador"),
                "notice":"Cardurile nu sunt carduri bancare; pentru walleturile native se cer certificatele emitentului."}

    @router.get("/customer/cards")
    def customer_cards(wallet_record=Depends(wallet),db:Session=Depends(session)):
        records=db.query(Customer).filter((Customer.wallet_uuid==wallet_record.wallet_uuid) |
                                          (Customer.uuid==wallet_record.wallet_uuid)).all()
        ids=sorted({c.business_id for c in records if c.business_id})
        return {"cards":[customer_card(wallet_record,biz_id,db) for biz_id in ids]}

    def apple_download_ticket(role,subject,business_id=None):
        expires=datetime.now(timezone.utc)+timedelta(seconds=90)
        token=jwt.encode({"purpose":"loial_apple_pass","role":role,
                          "sub":str(subject),"business_id":business_id,
                          "exp":expires},secret,algorithm=algorithm)
        return {"url":"/api/premium-wallet/apple/claim?ticket="+token,
                "expires_in_seconds":90}

    @router.post("/customer/{business_id}/apple-ticket")
    def customer_apple_ticket(business_id:int,wallet_record=Depends(wallet),
                              db:Session=Depends(session)):
        customer_card(wallet_record,business_id,db)
        if not apple_ready():
            raise HTTPException(status_code=503,detail="Apple Wallet nu este inca configurat")
        return apple_download_ticket("customer",wallet_record.wallet_uuid,business_id)

    @router.post("/ambassador/apple-ticket")
    def ambassador_apple_ticket(agent=Depends(ambassador),db:Session=Depends(session)):
        if not apple_ready():
            raise HTTPException(status_code=503,detail="Apple Wallet nu este inca configurat")
        return apple_download_ticket("ambassador",agent.id)

    @router.get("/apple/claim")
    def claim_apple(ticket:str,db:Session=Depends(session)):
        try:
            claims=jwt.decode(ticket,secret,algorithms=[algorithm])
        except JWTError:
            raise HTTPException(status_code=401,detail="Linkul de Wallet a expirat")
        if claims.get("purpose")!="loial_apple_pass":
            raise HTTPException(status_code=403,detail="Link invalid")
        if claims.get("role")=="customer":
            wallet_record=db.query(WalletInboxAccess).filter(
                WalletInboxAccess.wallet_uuid==claims.get("sub")).first()
            if not wallet_record:
                raise HTTPException(status_code=404,detail="Portofel indisponibil")
            card=customer_card(wallet_record,int(claims["business_id"]),db)
        elif claims.get("role")=="ambassador":
            agent=db.query(SalesAgent).filter(
                SalesAgent.id==int(claims["sub"]),
                SalesAgent.active.is_(True)).first()
            if not agent:
                raise HTTPException(status_code=404,detail="Ambasador inactiv")
            card=ambassador_card(agent,db)
        else:
            raise HTTPException(status_code=403,detail="Tip de card invalid")
        try:
            binary=signed_apple_pkpass(card)
        except ValueError as e:
            raise HTTPException(status_code=503,detail=str(e))
        from loial_apple_updates import register_issued_pass
        if card["role"]=="customer":
            register_issued_pass(db,card,business_id=int(claims["business_id"]),
                                 wallet_uuid=claims["sub"])
        else:
            register_issued_pass(db,card,agent_id=int(claims["sub"]))
        db.commit()
        filename="loial-ambassador.pkpass" if card["role"]=="ambassador" else "loial-black-metal.pkpass"
        return Response(content=binary,media_type="application/vnd.apple.pkpass",
                        headers={"Content-Disposition":'attachment; filename="'+filename+'"',
                                 "Cache-Control":"private, no-store",
                                 "Referrer-Policy":"no-referrer",
                                 "X-Content-Type-Options":"nosniff"})

    @router.get("/customer/{business_id}/google")
    def customer_google(business_id:int,wallet_record=Depends(wallet),db:Session=Depends(session)):
        card=customer_card(wallet_record,business_id,db)
        if not google_ready("customer"):
            raise HTTPException(status_code=503,detail="Google Wallet nu este inca configurat pentru emitere")
        try:
            return {"url":google_save_url(card)}
        except ValueError as e:
            raise HTTPException(status_code=503,detail=str(e))

    @router.get("/customer/{business_id}/apple")
    def customer_apple(business_id:int,wallet_record=Depends(wallet),db:Session=Depends(session)):
        card=customer_card(wallet_record,business_id,db)
        try:
            binary=signed_apple_pkpass(card)
        except ValueError as e:
            raise HTTPException(status_code=503,detail=str(e))
        from loial_apple_updates import register_issued_pass
        register_issued_pass(db,card,business_id=business_id,
                             wallet_uuid=wallet_record.wallet_uuid)
        db.commit()
        return Response(content=binary,media_type="application/vnd.apple.pkpass",
                       headers={"Content-Disposition":'attachment; filename="loial-black-metal.pkpass"',
                                "Cache-Control":"private, no-store"})

    @router.get("/ambassador/card")
    def ambassador_profile(agent=Depends(ambassador),db:Session=Depends(session)):
        return ambassador_card(agent,db)

    @router.get("/ambassador/google")
    def ambassador_google(agent=Depends(ambassador),db:Session=Depends(session)):
        if not google_ready("ambassador"):
            raise HTTPException(status_code=503,detail="Google Wallet nu este inca configurat pentru emitere")
        try:
            return {"url":google_save_url(ambassador_card(agent,db))}
        except ValueError as e:
            raise HTTPException(status_code=503,detail=str(e))

    @router.get("/ambassador/apple")
    def ambassador_apple(agent=Depends(ambassador),db:Session=Depends(session)):
        card=ambassador_card(agent,db)
        try:
            binary=signed_apple_pkpass(card)
        except ValueError as e:
            raise HTTPException(status_code=503,detail=str(e))
        from loial_apple_updates import register_issued_pass
        register_issued_pass(db,card,agent_id=agent.id)
        db.commit()
        return Response(content=binary,media_type="application/vnd.apple.pkpass",
                        headers={"Content-Disposition":'attachment; filename="loial-ambassador.pkpass"',
                                 "Cache-Control":"private, no-store"})

    app.include_router(router)
