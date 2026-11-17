"""ProBusiness group access. Only verified direct subscriptions can create groups.
A member is an independently authenticated business account. No implicit ownership
claim, transfer of customer records, or access to a member's private AI messages.
"""
import hashlib
import secrets
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import Column, Integer, String, UniqueConstraint, or_
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import IntegrityError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from jose import JWTError, jwt

GroupBase = declarative_base()

class GroupMember(GroupBase):
    __tablename__ = "loial_location_members"
    business_id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, nullable=False, index=True)
    slot = Column(Integer, nullable=False)
    linked_at = Column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("parent_id","slot",name="uq_loial_group_slot"),)

class GroupInvitation(GroupBase):
    __tablename__ = "loial_location_invites"
    token_hash = Column(String(64), primary_key=True)
    parent_id = Column(Integer, nullable=False, index=True)
    target_id = Column(Integer, nullable=False)
    expires_at = Column(String(40), nullable=False)
    accepted_at = Column(String(40))

class InviteInput(BaseModel):
    business_id: int = Field(gt=0)

class AcceptInput(BaseModel):
    code: str = Field(min_length=32,max_length=100)

def utcnow():
    return datetime.now(timezone.utc)

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def direct_plan(db,business_id,state=None):
    from loial_stripe_billing import LoialSubscription, entitlements
    from loial_revenue_commissions import PaidMerchantInvoice
    state = state if state is not None else db.get(LoialSubscription,business_id)
    if not entitlements(state)["active"]:
        return "start"
    if state.last_paid_invoice:
        proof=db.query(PaidMerchantInvoice).filter(
            PaidMerchantInvoice.external_invoice_id==state.last_paid_invoice,
            PaidMerchantInvoice.business_id==business_id,
            PaidMerchantInvoice.subscription_id==state.subscription_id,
            PaidMerchantInvoice.eligible==1,
            PaidMerchantInvoice.refunded==0,
        ).first()
        if (proof and proof.gross_paid_cents==27000 and
                proof.net_revenue_cents==27000 and proof.review_reason=="stripe_verified_probusiness"):
            return "probusiness"
    return "business"

def inherited_access(db,business_id):
    from loial_stripe_billing import LoialSubscription, entitlements
    link=db.get(GroupMember,business_id)
    if not link or not 2<=link.slot<=5:
        return None
    # Only direct proof, never recursive entitlements.
    state=db.get(LoialSubscription,link.parent_id)
    if direct_plan(db,link.parent_id,state)!="probusiness":
        return None
    return {**entitlements(state),"plan":"probusiness_member",
            "status":"group_member","parent_id":link.parent_id}

def available_slot(used):
    return next((n for n in range(2,6) if n not in used),None)

def month_range(period):
    try:
        first=datetime.strptime(period,"%Y-%m").date()
        if first.strftime("%Y-%m")!=period:
            raise ValueError()
        nxt=first.replace(year=first.year+1,month=1) if first.month==12 else first.replace(month=first.month+1)
        return first.isoformat(),nxt.isoformat()
    except (TypeError,ValueError,OverflowError):
        raise HTTPException(422,"Perioada trebuie sa fie YYYY-MM")

def install_multilocation(app,engine,factory,Business,Customer,secret,algorithm):
    from loial_business_ai import AISale,AIDocument,AIProfile
    from loial_expenses import VerifiedExpense, expense_totals
    from loial_scans import StampAward
    from loial_analytics import summarize_sales
    from loial_stripe_billing import effective_entitlements
    GroupBase.metadata.create_all(bind=engine)
    api=APIRouter(prefix="/api/loial-locations",tags=["LOIAL multi-location"])

    def session():
        db=factory()
        try:yield db
        finally:db.close()

    def owner(request: Request,db=Depends(session)):
        auth=request.headers.get("Authorization","")
        if not auth.startswith("Bearer "):
            raise HTTPException(401,"Autentificare obligatorie")
        try:claims=jwt.decode(auth[7:],secret,algorithms=[algorithm])
        except JWTError:raise HTTPException(401,"Sesiune invalida")
        if claims.get("role")!="business":raise HTTPException(403,"Cont de firma necesar")
        biz=db.query(Business).filter(Business.id==claims.get("business_id"),
                                      Business.email==claims.get("sub")).first()
        if not biz:raise HTTPException(403,"Acces interzis")
        return biz

    def parent_only(db,biz):
        if db.get(GroupMember,biz.id) or direct_plan(db,biz.id)!="probusiness":
            raise HTTPException(403,"Abonament ProBusiness direct necesar")

    @api.get("/me")
    def me(biz=Depends(owner),db=Depends(session)):
        access=effective_entitlements(db,biz.id)
        link=db.get(GroupMember,biz.id)
        can_manage=direct_plan(db,biz.id)=="probusiness" and not link
        return {"business_id":biz.id,"plan":access.get("plan","start"),
                "can_manage":can_manage,"member_of":link.parent_id if link else None,
                "locations":[{"business_id":x.business_id,"slot":x.slot}
                  for x in db.query(GroupMember).filter(GroupMember.parent_id==biz.id).order_by(GroupMember.slot).all()]
                   if can_manage else []}

    @api.post("/invite")
    def invite(req:InviteInput,biz=Depends(owner),db=Depends(session)):
        parent_only(db,biz)
        if req.business_id==biz.id:
            raise HTTPException(422,"Alege alta locatie")
        if not db.get(Business,req.business_id):
            raise HTTPException(404,"Locatie indisponibila")
        if db.get(GroupMember,req.business_id):
            raise HTTPException(409,"Locatia este deja asociata")
        code=secrets.token_urlsafe(32)
        db.add(GroupInvitation(token_hash=token_hash(code),parent_id=biz.id,
                 target_id=req.business_id,expires_at=(utcnow()+timedelta(hours=24)).isoformat()))
        db.commit()
        return {"code":code,"expires_in_hours":24}

    @api.post("/accept")
    def accept(req:AcceptInput,biz=Depends(owner),db=Depends(session)):
        import os
        if os.getenv("LOIAL_MULTILOCATION_READY","0")!="1":
            raise HTTPException(503,"Asocierea locatiilor este in pregatire")
        inv=db.get(GroupInvitation,token_hash(req.code.strip()))
        if not inv or inv.target_id!=biz.id or inv.accepted_at or inv.expires_at<=utcnow().isoformat():
            raise HTTPException(409,"Invitatie invalida sau expirata")
        # Serialize changes to both firms on databases supporting row locks.
        parent_id=inv.parent_id
        locked=db.query(Business).filter(Business.id.in_([parent_id,biz.id])).order_by(Business.id).with_for_update().all()
        if len(locked)!=2 or parent_id==biz.id:
            raise HTTPException(409,"Asociere invalida")
        db.refresh(inv)
        if inv.accepted_at or inv.expires_at<=utcnow().isoformat():
            raise HTTPException(409,"Invitatie expirata sau folosita")
        if direct_plan(db,parent_id)!="probusiness" or db.get(GroupMember,parent_id):
            raise HTTPException(403,"Organizatie indisponibila")
        if (db.get(GroupMember,biz.id) or
            db.query(GroupMember).filter(GroupMember.parent_id==biz.id).first() or
            effective_entitlements(db,biz.id)["active"]):
            raise HTTPException(409,"Locatia are deja acces activ sau apartine unei organizatii")
        used={x.slot for x in db.query(GroupMember).filter(GroupMember.parent_id==parent_id).all()}
        slot=available_slot(used)
        if slot is None:raise HTTPException(409,"Limita de 5 locatii a fost atinsa")
        db.add(GroupMember(business_id=biz.id,parent_id=parent_id,slot=slot,linked_at=utcnow().isoformat()))
        inv.accepted_at=utcnow().isoformat()
        try:db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409,"Asocierea s-a modificat; incearca din nou")
        return {"linked":True,"parent_id":parent_id,"slot":slot}

    @api.delete("/member/{business_id}")
    def unlink(business_id:int,biz=Depends(owner),db=Depends(session)):
        link=db.get(GroupMember,business_id)
        if not link or biz.id not in (link.parent_id,link.business_id):
            raise HTTPException(404,"Locatie indisponibila")
        db.delete(link);db.commit()
        return {"unlinked":True}

    @api.get("/report")
    def report(period:str,biz=Depends(owner),db=Depends(session)):
        parent_only(db,biz)
        start,end=month_range(period)
        ids=[biz.id]+[x.business_id for x in db.query(GroupMember).filter(
                       GroupMember.parent_id==biz.id).order_by(GroupMember.slot).all()]
        locations=[]
        for account in db.query(Business).filter(Business.id.in_(ids)).order_by(Business.id).all():
            aid=account.id
            rows=(db.query(AISale).join(AIDocument,AISale.document_id==AIDocument.id)
                 .filter(AISale.business_id==aid,AIDocument.business_id==aid,
                         AIDocument.confirmed==1,AIDocument.kind!="receipt_refunded",
                         AISale.sold_at>=start,AISale.sold_at<end).limit(50001).all())
            if len(rows)>50000:raise HTTPException(422,"Prea multe randuri; raportul necesita agregare separata")
            try:
                summary=summarize_sales([{"product":x.product,"quantity":x.quantity,
                  "unit_price":x.unit_price,"unit_variable_cost":x.unit_variable_cost,
                  "transaction_id":x.transaction_id,"sold_at":x.sold_at} for x in rows])
            except ValueError:raise HTTPException(422,"Date comerciale invalide in una dintre locatii")
            profile=db.get(AIProfile,aid)
            expenses=db.query(VerifiedExpense).filter(VerifiedExpense.business_id==aid,
                VerifiedExpense.confirmed_by_owner.is_(True),VerifiedExpense.voided_at.is_(None),
                VerifiedExpense.incurred_on>=start,VerifiedExpense.incurred_on<end).limit(50001).all()
            if len(expenses)>50000:raise HTTPException(422,"Prea multe cheltuieli pentru acest raport")
            scans=db.query(StampAward).filter(StampAward.business_id==aid,
                    StampAward.created_at>=start,StampAward.created_at<end).count()
            locations.append({"business_id":aid,"name":account.name,
               "registered_cards":db.query(Customer).filter(Customer.business_id==aid).count(),
               "stamp_operations":scans,"currency":profile.currency if profile else None,
               "sales_lines":summary["sales_lines"],
               "recorded_sales":summary["total_revenue"] if rows else None,
               "recorded_contribution":summary["total_contribution"],
               "expense_groups":expense_totals(expenses)})
        # Do not assume locations share accounting basis. Aggregate only recorded
        # sales by declared currency; no fabricated total profit or customer deduplication.
        totals=defaultdict(lambda:Decimal("0"))
        for loc in locations:
            if loc["currency"] and loc["recorded_sales"] is not None:
                totals[loc["currency"]]+=Decimal(str(loc["recorded_sales"]))
        return {"period":period,"locations":locations,
                "recorded_sales_by_declared_currency":{k:float(v) for k,v in totals.items()},
                "registered_cards_sum":sum(x["registered_cards"] for x in locations),
                "stamp_operations_sum":sum(x["stamp_operations"] for x in locations),
                "caveats":["Cardurile nu sunt clienti unici intre locatii.",
                 "Totalurile reflecta numai inregistrarile disponibile; moneda provine din profil.",
                 "Baza TVA si integralitatea contabilitatii nu sunt certificate; profitul consolidat nu este calculat."]}
    app.include_router(api)
