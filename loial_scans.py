"""Auditable and idempotent loyalty stamp grants.

Each unique staff scan operation can be applied once; a short server-side
anti-double-scan period prevents accidental duplicate rewards from reloads.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base

ScanBase=declarative_base()

class StampAward(ScanBase):
    __tablename__="loial_stamp_awards"
    id=Column(Integer,primary_key=True)
    business_id=Column(Integer,nullable=False,index=True)
    customer_id=Column(Integer,nullable=False,index=True)
    operation_key=Column(String(120),nullable=False)
    source=Column(String(30),nullable=False)
    stamps_after=Column(Integer,nullable=False)
    created_at=Column(String(40),nullable=False)
    __table_args__=(UniqueConstraint("business_id","operation_key",
                    name="uq_loial_stamp_business_operation"),)

def recent_duplicate(db,business_id,customer_id,now=None,cooldown_seconds=12):
    now=now or datetime.now(timezone.utc)
    threshold=(now-timedelta(seconds=cooldown_seconds)).isoformat()
    return db.query(StampAward).filter(
        StampAward.business_id==business_id,
        StampAward.customer_id==customer_id,
        StampAward.created_at>=threshold).order_by(StampAward.id.desc()).first()

def existing_operation(db,business_id,operation_key):
    return db.query(StampAward).filter(
        StampAward.business_id==business_id,
        StampAward.operation_key==operation_key).first()

def record_award(db,business_id,customer_id,operation_key,source,stamps_after,at=None):
    if not operation_key or len(operation_key)>120:
        raise ValueError("Invalid stamp operation")
    award=StampAward(business_id=business_id,customer_id=customer_id,
                     operation_key=operation_key,source=source,stamps_after=stamps_after,
                     created_at=(at or datetime.now(timezone.utc)).isoformat())
    db.add(award)
    return award
