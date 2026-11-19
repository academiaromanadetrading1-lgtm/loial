"""Founders are verified and opted in; examples never enter this registry."""
import base64
import binascii
import io
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Boolean, Text, func
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import IntegrityError
from PIL import Image

FoundersBase=declarative_base()
CAP=500
class Founder(FoundersBase):
    __tablename__="loial_founders"
    slot=Column(Integer,primary_key=True,autoincrement=False)
    business_id=Column(Integer,unique=True,nullable=False)
    name=Column(String(120),nullable=False)
    city=Column(String(80),nullable=False,default="")
    logo=Column(Text,nullable=True)
    consent_reference=Column(String(200),nullable=False)
    approved_at=Column(String(40),nullable=False)
    visible=Column(Boolean,nullable=False,default=True)

class FounderApproval(BaseModel):
    city:str=Field(default="",max_length=80)
    consent_reference:str=Field(min_length=8,max_length=200)
    verified:bool=False
    logo_png:str|None=Field(default=None,max_length=180000)

def clean_logo(value):
    if not value:return None
    try:
        raw=base64.b64decode(value,validate=True)
        if len(raw)>120000:raise ValueError()
        with Image.open(io.BytesIO(raw)) as im:
            if im.format!="PNG" or max(im.size)>800 or min(im.size)<1:raise ValueError()
            im.verify()
        return base64.b64encode(raw).decode("ascii")
    except (ValueError,OSError,binascii.Error,Image.DecompressionBombError):
        raise HTTPException(422,"Logo PNG invalid (maxim 120 KB, 800 px)")

def public_directory(db):
    occupied=db.query(Founder).count()
    rows=db.query(Founder).filter(Founder.visible.is_(True)).order_by(Founder.slot).all()
    return {"capacity":CAP,"reserved":occupied,"remaining":max(0,CAP-occupied),
            "members":[{"slot":x.slot,"name":x.name,"city":x.city,"has_logo":bool(x.logo)} for x in rows]}

def approve(db,business,req):
    if not req.verified or not req.consent_reference.strip():
        raise HTTPException(422,"Confirmă validarea firmei și acordul documentat")
    logo=clean_logo(req.logo_png)
    existing=db.query(Founder).filter_by(business_id=business.id).first()
    if existing:
        existing.visible=True;existing.name=business.name[:120]
        existing.city=req.city.strip();existing.consent_reference=req.consent_reference.strip()
        if logo:existing.logo=logo
        db.commit();return existing.slot
    for attempt in range(3):
        slot=(db.query(func.max(Founder.slot)).scalar() or 0)+1
        if slot>CAP:raise HTTPException(409,"Toate cele 500 de locuri sunt rezervate")
        db.add(Founder(slot=slot,business_id=business.id,name=business.name[:120],
            city=req.city.strip(),logo=logo,consent_reference=req.consent_reference.strip(),
            approved_at=datetime.now(timezone.utc).isoformat(),visible=True))
        try:db.commit();return slot
        except IntegrityError:
            db.rollback()
            if db.query(Founder).filter_by(business_id=business.id).first():
                raise HTTPException(409,"Firma a fost deja validată")
    raise HTTPException(409,"Înscriere concurentă; reîncearcă")
