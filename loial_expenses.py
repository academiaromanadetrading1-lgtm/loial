"""Owner-verified business expenses, with provenance and VAT-basis separation.

Photographs/screenshots are previews, never accounting records until the
merchant explicitly confirms date, supplier, category, amount, currency and
whether amount includes VAT. No hidden formulas or guessed tax adjustments.
"""
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
from typing import Optional
import re

from fastapi import APIRouter,Depends,HTTPException,Request
from jose import JWTError,jwt
from pydantic import BaseModel,Field
from sqlalchemy import Column,Integer,String,Boolean,UniqueConstraint,func
from sqlalchemy.orm import declarative_base,Session

ExpenseBase=declarative_base()
CATEGORIES={
 "rent":"Chirie","utilities":"Utilitati","personnel":"Personal",
 "supplies":"Materiale si piese","marketing":"Marketing",
 "transport":"Transport","services":"Servicii externe",
 "taxes":"Taxe si contributii","other":"Altele"
}
BASES={"net","gross"}

def money_minor(value):
    try:
        d=Decimal(str(value))
        if not d.is_finite() or d<=0 or d>Decimal("100000000"):
            raise ValueError("Suma invalida")
        cents=d*100
        if cents!=cents.to_integral_value():
            raise ValueError("Foloseste maximum doua zecimale")
        return int(cents)
    except (InvalidOperation,TypeError) as exc:
        raise ValueError("Suma invalida") from exc

class VerifiedExpense(ExpenseBase):
    __tablename__="loial_verified_expenses"
    id=Column(Integer,primary_key=True)
    business_id=Column(Integer,index=True,nullable=False)
    source_document_id=Column(Integer,nullable=True)
    invoice_ref=Column(String(100),nullable=False)
    supplier=Column(String(160),nullable=False)
    incurred_on=Column(String(10),nullable=False)
    category=Column(String(30),nullable=False)
    amount_minor=Column(Integer,nullable=False)
    vat_basis=Column(String(10),nullable=False)
    currency=Column(String(3),nullable=False)
    confirmed_by_owner=Column(Boolean,default=True,nullable=False)
    created_at=Column(String(40),nullable=False)
    voided_at=Column(String(40))
    __table_args__=(UniqueConstraint("business_id","invoice_ref",
                    name="uq_loial_expense_business_invoice"),)

class ExpenseRequest(BaseModel):
    document_id:Optional[int]=Field(default=None,gt=0)
    invoice_ref:str=Field(min_length=2,max_length=100)
    supplier:str=Field(min_length=2,max_length=160)
    incurred_on:str=Field(min_length=10,max_length=10)
    category:str=Field(min_length=3,max_length=30)
    amount:float=Field(gt=0,le=100000000)
    vat_basis:str=Field(default="gross")
    currency:str=Field(default="RON",min_length=3,max_length=3)
    owner_confirmed:bool=False

def expense_totals(expenses):
    groups={}
    for e in expenses:
        key=(e.currency,e.vat_basis,e.category)
        groups[key]=groups.get(key,0)+e.amount_minor
    return [{"currency":currency,"vat_basis":basis,
             "category":category,"category_label":CATEGORIES.get(category,category),
             "total":round(minor/100,2)}
            for (currency,basis,category),minor in sorted(groups.items())]

def install_expenses(app,engine,factory,BusinessAccount,AIDocument,secret,algorithm):
    ExpenseBase.metadata.create_all(bind=engine)
    router=APIRouter(prefix="/api/loial-expenses",tags=["Verified managerial expenses"])

    def session():
        db=factory()
        try:
            yield db
        finally:
            db.close()

    def owner(request:Request,db:Session=Depends(session)):
        raw=request.headers.get("Authorization","")
        if not raw.startswith("Bearer "):
            raise HTTPException(status_code=401,detail="Autentificare necesara")
        try:
            payload=jwt.decode(raw[7:],secret,algorithms=[algorithm])
        except JWTError:
            raise HTTPException(status_code=401,detail="Token invalid")
        if payload.get("role")!="business":
            raise HTTPException(status_code=403,detail="Doar administratorul firmei")
        biz=db.query(BusinessAccount).filter(
            BusinessAccount.email==payload.get("sub")).first()
        if not biz or (payload.get("business_id") and payload["business_id"]!=biz.id):
            raise HTTPException(status_code=403,detail="Acces interzis")
        if (biz.plan or "").lower() not in (
            "business","probusiness","pro","premium","enterprise"):
            raise HTTPException(status_code=403,detail="Loial AI este inclus in Business")
        return biz

    @router.get("/categories")
    def categories(biz=Depends(owner)):
        return {"categories":[{"key":k,"label":v} for k,v in CATEGORIES.items()],
                "vat_basis":["net","gross"],
                "guidance":"Nu compara direct sume cu TVA cu sume fara TVA."}

    @router.post("/confirm")
    def confirm(req:ExpenseRequest,biz=Depends(owner),db:Session=Depends(session)):
        if not req.owner_confirmed:
            raise HTTPException(status_code=422,detail="Administratorul trebuie sa confirme datele")
        if req.category not in CATEGORIES or req.vat_basis not in BASES:
            raise HTTPException(status_code=422,detail="Categoria sau tratamentul TVA invalid")
        if req.currency.upper() not in ("RON","EUR","USD","GBP"):
            raise HTTPException(status_code=422,detail="Moneda nu este suportata")
        try:
            incurred=date.fromisoformat(req.incurred_on)
            if incurred>date.today():
                raise ValueError("Data facturii nu poate fi in viitor")
            total=money_minor(req.amount)
        except ValueError as exc:
            raise HTTPException(status_code=422,detail=str(exc))
        if db.query(VerifiedExpense).filter(
            VerifiedExpense.business_id==biz.id,
            VerifiedExpense.invoice_ref==req.invoice_ref.strip()).first():
            raise HTTPException(status_code=409,detail="Referinta facturii exista deja")
        if req.document_id:
            doc=db.query(AIDocument).filter(
                AIDocument.business_id==biz.id,
                AIDocument.id==req.document_id).first()
            if not doc:
                raise HTTPException(status_code=404,detail="Documentul nu apartine firmei")
            if doc.kind not in ("photo_preview","pdf_text","invoice_preview","expense_preview"):
                raise HTTPException(status_code=422,detail="Documentul nu este o factura/previzualizare")
        row=VerifiedExpense(business_id=biz.id,
            source_document_id=req.document_id,
            invoice_ref=req.invoice_ref.strip(),
            supplier=req.supplier.strip(),
            incurred_on=incurred.isoformat(),category=req.category,
            amount_minor=total,vat_basis=req.vat_basis,
            currency=req.currency.upper(),confirmed_by_owner=True,
            created_at=datetime.now(timezone.utc).isoformat())
        db.add(row);db.commit()
        return {"status":"confirmed","id":row.id,"amount":round(row.amount_minor/100,2),
                "currency":row.currency,"vat_basis":row.vat_basis,
                "source":"merchant_confirmed","ai_calls":0}

    @router.get("/summary")
    def summary(period:Optional[str]=None,biz=Depends(owner),db:Session=Depends(session)):
        if period and not re.fullmatch(r"\d{4}-\d{2}",period):
            raise HTTPException(status_code=422,detail="Perioada trebuie sa fie YYYY-MM")
        records=db.query(VerifiedExpense).filter(
            VerifiedExpense.business_id==biz.id,
            VerifiedExpense.voided_at.is_(None)).all()
        if period:
            records=[row for row in records if row.incurred_on.startswith(period)]
        totals=expense_totals(records)
        return {"period":period,"items":len(records),"totals":totals,
                "limitations":[
                    "Cheltuielile sunt numai cele confirmate si introduse de administrator.",
                    "Valorile cu TVA si fara TVA sunt prezentate separat.",
                    "Nu calcula profitul net din aceasta lista incompleta.",
                    "Nu sunt deduse automat cote de TVA sau cheltuieli fiscale."],
                "ai_calls":0}

    @router.get("/recent")
    def recent(biz=Depends(owner),db:Session=Depends(session)):
        records=db.query(VerifiedExpense).filter(
            VerifiedExpense.business_id==biz.id).order_by(
            VerifiedExpense.id.desc()).limit(100).all()
        return [{"id":x.id,"invoice_ref":x.invoice_ref,"supplier":x.supplier,
                 "incurred_on":x.incurred_on,"category":x.category,
                 "amount":round(x.amount_minor/100,2),"vat_basis":x.vat_basis,
                 "currency":x.currency,"voided":x.voided_at is not None}
                for x in records]

    @router.post("/{expense_id}/void")
    def void(expense_id:int,biz=Depends(owner),db:Session=Depends(session)):
        row=db.query(VerifiedExpense).filter(
            VerifiedExpense.id==expense_id,
            VerifiedExpense.business_id==biz.id).first()
        if not row:
            raise HTTPException(status_code=404,detail="Cheltuiala nu apartine firmei")
        if row.voided_at is None:
            row.voided_at=datetime.now(timezone.utc).isoformat()
            db.commit()
        return {"status":"voided","effect":"excluded_from_aggregates"}

    app.include_router(router)
