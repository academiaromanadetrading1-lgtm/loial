import base64
from io import BytesIO
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from loial_founders import FoundersBase, Founder, FounderApproval, approve, public_directory, clean_logo

@pytest.fixture
def db():
    engine=create_engine("sqlite://")
    FoundersBase.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()

def firm(i=1):
    return SimpleNamespace(id=i,name=f"Test firm {i}")

def consent(**kw):
    return FounderApproval(**{"verified":True,"consent_reference":"test written permission","city":"Madrid",**kw})

def test_no_approval_without_consent(db):
    with pytest.raises(HTTPException) as err:
        approve(db,firm(),consent(verified=False))
    assert err.value.status_code==422
    assert public_directory(db)=={"capacity":500,"reserved":0,"remaining":500,"members":[]}

def test_stable_slots_and_public_privacy(db):
    assert approve(db,firm(),consent())==1
    assert approve(db,firm(),consent(city="Timișoara"))==1
    assert approve(db,firm(2),consent())==2
    data=public_directory(db)
    assert data["remaining"]==498
    assert data["members"][0]=={"slot":1,"name":"Test firm 1","city":"Timișoara","has_logo":False}
    assert "consent_reference" not in str(data)
    row=db.get(Founder,1)
    row.visible=False
    db.commit()
    data=public_directory(db)
    assert data["reserved"]==2 and data["remaining"]==498
    assert [r["slot"] for r in data["members"]]==[2]
    assert approve(db,firm(),consent())==1

def test_permanent_capacity(db):
    db.add_all([Founder(slot=i,business_id=i,name="Test",city="",consent_reference="test permission",approved_at="2026-11-19",visible=False) for i in range(1,501)])
    db.commit()
    assert public_directory(db)["remaining"]==0
    with pytest.raises(HTTPException) as err:
        approve(db,firm(501),consent())
    assert err.value.status_code==409
    assert approve(db,firm(1),consent())==1

def png(size=(32,32),format="PNG"):
    f=BytesIO()
    Image.new("RGB",size,"green").save(f,format=format)
    return base64.b64encode(f.getvalue()).decode("ascii")

@pytest.mark.parametrize("invalid",["invalid!",png((801,1)),png(format="JPEG")])
def test_reject_invalid_logo(invalid):
    with pytest.raises(HTTPException) as err:
        clean_logo(invalid)
    assert err.value.status_code==422

def test_png_logo_reflected_in_public_listing(db):
    logo=png()
    assert clean_logo(logo)==logo
    approve(db,firm(),consent(logo_png=logo))
    assert public_directory(db)["members"][0]["has_logo"] is True
    assert logo not in str(public_directory(db))
