"""Administrator grants and ambassador invitations; no financial side effects."""
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

GrantBase=declarative_base()

class ManualBusinessGrant(GrantBase):
    __tablename__="loial_manual_business_grants"
    business_id=Column(Integer,primary_key=True)
    active=Column(Integer,nullable=False,default=1)
    actor_id=Column(Integer,nullable=False)
    reason=Column(String(300),nullable=False)
    updated_at=Column(String(50),nullable=False)

class AmbassadorInvite(GrantBase):
    __tablename__="loial_manual_ambassador_invites"
    email=Column(String(254),primary_key=True)
    name=Column(String(120),nullable=False)
    token_hash=Column(String(64),unique=True,nullable=False)
    expires_at=Column(String(50),nullable=False)
    actor_id=Column(Integer,nullable=False)
    source=Column(String(100),nullable=False)
    used_at=Column(String(50))

class ManualAdminAudit(GrantBase):
    __tablename__="loial_manual_admin_audit"
    id=Column(Integer,primary_key=True)
    actor_id=Column(Integer,nullable=False)
    action=Column(String(50),nullable=False)
    subject=Column(String(300),nullable=False)
    reason=Column(String(300),nullable=False)
    created_at=Column(String(50),nullable=False)

def utc_now():
    return datetime.now(timezone.utc)

def audit(db,actor,action,subject,reason):
    db.add(ManualAdminAudit(actor_id=actor.id,action=action,
        subject=str(subject),reason=reason,created_at=utc_now().isoformat()))

def manual_grant(db,business_id):
    row=db.get(ManualBusinessGrant,business_id)
    return bool(row and row.active)

def issue_invite(db,email,name,source,actor):
    token=secrets.token_urlsafe(32)
    row=db.get(AmbassadorInvite,email)
    if not row:
        row=AmbassadorInvite(email=email)
        db.add(row)
    row.name=name
    row.token_hash=hashlib.sha256(token.encode()).hexdigest()
    row.expires_at=(utc_now()+timedelta(hours=24)).isoformat()
    row.actor_id=actor.id
    row.source=source
    row.used_at=None
    audit(db,actor,"ambassador_invite",email,source)
    return token

def claim_invite(db,token):
    if not isinstance(token,str) or not 40<=len(token)<=100:
        return None
    digest=hashlib.sha256(token.encode()).hexdigest()
    row=db.query(AmbassadorInvite).filter(
        AmbassadorInvite.token_hash==digest,
        AmbassadorInvite.used_at.is_(None)).first()
    if not row or datetime.fromisoformat(row.expires_at)<=utc_now():
        return None
    updated=db.query(AmbassadorInvite).filter(
        AmbassadorInvite.email==row.email,
        AmbassadorInvite.token_hash==digest,
        AmbassadorInvite.used_at.is_(None)).update(
            {AmbassadorInvite.used_at:utc_now().isoformat()},synchronize_session=False)
    return row if updated==1 else None
