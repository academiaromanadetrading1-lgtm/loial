"""Allowlisted acquisition sources. No tracking cookies or customer identifiers."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, func
from sqlalchemy.orm import declarative_base

AcquisitionBase=declarative_base()
SOURCES=frozenset(("card","receipt","poster","demo","ambassador","industry","review","direct"))
class Acquisition(AcquisitionBase):
    __tablename__="loial_business_acquisition"
    business_id=Column(Integer,primary_key=True)
    source=Column(String(24),nullable=False,index=True)
    created_at=Column(String(40),nullable=False)

def normalize_source(source):
    source=(source or "").strip().lower()
    return source if source in SOURCES else "direct"

def record_registration(db,business_id,source,has_ambassador=False):
    db.add(Acquisition(business_id=business_id,
        source="ambassador" if has_ambassador else normalize_source(source),
        created_at=datetime.now(timezone.utc).isoformat()))

def pilot_snapshot(db,Business,Customer,StampAward):
    # Only enrolled business accounts attributed after the instrumentation launch.
    # This counts accounts, not verified unique legal entities or paid subscriptions.
    rows=db.query(Acquisition.source,func.count(Acquisition.business_id)).join(
        Business,Business.id==Acquisition.business_id).group_by(Acquisition.source).all()
    by_source={source:int(count) for source,count in rows}
    ids=db.query(Acquisition.business_id).join(Business,Business.id==Acquisition.business_id)
    cards=db.query(Customer).filter(Customer.business_id.in_(ids)).count()
    stamps=db.query(StampAward).filter(StampAward.business_id.in_(ids)).count()
    return {"tracked_business_accounts":sum(by_source.values()),"by_source":by_source,
            "registered_cards":cards,"stamp_operations":stamps,"pilot_goal":100,
            "scope":"Accounts recorded since attribution launch; includes unverified accounts; not a count of unique firms."}
