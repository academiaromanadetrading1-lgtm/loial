"""Loial AI Business: tenant-isolated managerial chat and confirmed sales data.
No outbound marketing is performed by this module.
"""
import base64
import csv
import hashlib
import io
import json
import os
from datetime import date, datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import Column, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Session, declarative_base

from loial_industries import PROFILES, canonical, profile, weekly_request
from loial_analytics import customer_segments, sector_summary, abc_products, money, manager_findings
from loial_knowledge import guidance
from loial_marketing import TEMPLATES, render as render_template, eligible_segment
from loial_email import email_enabled, send_text_email, unsubscribe_url, parse_unsubscribe_token

BaseAI = declarative_base()

def now():
    return datetime.now(timezone.utc).isoformat()

class AIProfile(BaseAI):
    __tablename__ = "loial_ai_profiles"
    business_id = Column(Integer, primary_key=True)
    sector = Column(String(60), default="general")
    description = Column(Text, default="")
    currency = Column(String(3), default="RON")

class AIMessage(BaseAI):
    __tablename__ = "loial_ai_messages"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, index=True, nullable=False)
    role = Column(String(15), nullable=False)
    topic = Column(String(60), default="general")
    content = Column(Text, nullable=False)
    created_at = Column(String(40), nullable=False)

class AIDocument(BaseAI):
    __tablename__ = "loial_ai_documents"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, index=True, nullable=False)
    filename = Column(String(200))
    sha256 = Column(String(64))
    kind = Column(String(40))
    data_json = Column(Text, default="{}")
    confirmed = Column(Integer, default=0)
    created_at = Column(String(40))
    __table_args__ = (UniqueConstraint("business_id", "sha256", name="uq_loial_document_hash"),)

class AISale(BaseAI):
    __tablename__ = "loial_ai_sales"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, index=True, nullable=False)
    document_id = Column(Integer, nullable=False)
    row_number = Column(Integer, nullable=False)
    sold_at = Column(String(30), nullable=False)
    transaction_id = Column(String(100))
    product = Column(String(200), nullable=False)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    unit_variable_cost = Column(Float)
    customer_uuid = Column(String(100))
    __table_args__ = (UniqueConstraint("document_id", "row_number", name="uq_loial_sale_source"),)

class AIMetric(BaseAI):
    __tablename__ = "loial_ai_metrics"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, index=True, nullable=False)
    period = Column(String(30))
    name = Column(String(60))
    value = Column(Float)
    source = Column(String(100))

class AICampaign(BaseAI):
    __tablename__ = "loial_ai_campaigns"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, index=True, nullable=False)
    audience = Column(String(60))
    objective = Column(String(250))
    subject = Column(String(200))
    content = Column(Text)
    status = Column(String(30), default="draft")

class AIUsage(BaseAI):
    __tablename__ = "loial_ai_usage"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    month = Column(String(7), nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_eur = Column(Float, default=0)
    __table_args__ = (UniqueConstraint("business_id", "month", name="uq_loial_ai_monthly"),)

class AIEmailDispatch(BaseAI):
    __tablename__ = "loial_ai_email_dispatch"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False, index=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False)
    status = Column(String(20), default="sent")
    sent_at = Column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("campaign_id", "customer_id", name="uq_loial_ai_email_campaign_customer"),)

class SendCampaignRequest(BaseModel):
    confirmation: str = Field(min_length=6, max_length=6)

class UnsubscribeRequest(BaseModel):
    token: str = Field(min_length=5, max_length=220)

class ProfileRequest(BaseModel):
    sector: str = Field(max_length=100)
    description: str = Field(default="", max_length=1200)
    currency: str = Field(default="RON", min_length=3, max_length=3)

class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    topic: str = Field(default="general", max_length=60)

class MetricRequest(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    period: str = Field(min_length=4, max_length=30)
    value: float
    source: str = Field(default="administrator", max_length=100)

class CampaignRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=250)
    audience: str = Field(default="inactive_31_90", max_length=60)
    offer: str = Field(default="", max_length=300)

TOPICS = [
    ("performance", "Cum merge afacerea?"),
    ("products", "Ce servicii sau produse imi aduc marja?"),
    ("customers", "Ce clienti nu mai revin?"),
    ("slow", "Ce se vinde mai putin?"),
    ("campaign", "Pregateste o campanie"),
    ("invoices", "Analizeaza facturile"),
    ("margin", "Cum cresc marja?"),
    ("weekly", "Raportul saptamanal"),
]

def parse_sales_csv(raw):
    try:
        value = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV trebuie exportat in UTF-8")
    if not value.strip():
        raise ValueError("Fisier gol")
    try:
        delimiter = csv.Sniffer().sniff(value[:3000], delimiters=",;\t")
    except csv.Error:
        delimiter = csv.excel
    reader = csv.DictReader(io.StringIO(value), dialect=delimiter)
    aliases = {
        "sold_at": ["sold_at", "date", "data", "data_vanzarii"],
        "product": ["product", "produs", "serviciu", "articol", "item"],
        "quantity": ["quantity", "cantitate", "qty"],
        "unit_price": ["unit_price", "pret_unitar", "price"],
        "unit_variable_cost": ["unit_variable_cost", "cost_variabil_unitar"],
        "transaction_id": ["transaction_id", "bon", "id_bon", "order_id"],
        "customer_uuid": ["customer_uuid", "client_uuid"],
    }
    labels = {str(x).strip().lower(): x for x in (reader.fieldnames or [])}
    columns = {key: next((labels[x] for x in variants if x in labels), None)
               for key, variants in aliases.items()}
    if any(columns[k] is None for k in ("sold_at", "product", "quantity", "unit_price")):
        raise ValueError("CSV necesita coloanele: sold_at, product, quantity, unit_price (sau variante in romana)")
    output = []
    for index, row in enumerate(reader):
        if index >= 2000:
            raise ValueError("Maximum 2000 de randuri per import")
        if not any(row.values()):
            continue
        item = {k: (str(row.get(v) or "").strip() if v else "") for k, v in columns.items()}
        try:
            date.fromisoformat(item["sold_at"][:10])
        except ValueError:
            raise ValueError("Data invalida; foloseste YYYY-MM-DD")
        if not item["product"]:
            raise ValueError("Produs/serviciu lipsa")
        for k in ("quantity", "unit_price"):
            item[k] = float(money(item[k]))
            if item[k] < 0:
                raise ValueError("Retururile si valorile negative se importa separat")
        item["unit_variable_cost"] = float(money(item["unit_variable_cost"])) if item["unit_variable_cost"] else None
        output.append(item)
    if not output:
        raise ValueError("Nu exista randuri de vanzari")
    return {"kind": "sales", "rows": output,
            "notes": ["Confirma ca preturile si costurile sunt pe aceeasi baza fara TVA.",
                      "Nu se deduc costurile variabile din costuri lipsa."]}

def parse_xlsx(raw):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    ws = wb.active
    stream = io.StringIO()
    writer = csv.writer(stream)
    for row in ws.iter_rows(max_row=2002, values_only=True):
        writer.writerow(["" if x is None else x for x in row])
    wb.close()
    return parse_sales_csv(stream.getvalue().encode("utf-8"))

def parse_pdf(raw):
    from pypdf import PdfReader
    doc = PdfReader(io.BytesIO(raw))
    if len(doc.pages) > 15:
        raise ValueError("PDF peste 15 pagini")
    content = "\n".join((p.extract_text() or "") for p in doc.pages)
    if not content.strip():
        raise ValueError("PDF scanat; incarca poze dupa activarea extragerii AI")
    return {"kind": "pdf_text", "preview": content[:12000],
            "notes": ["Text extras automat; verifica datele si sumele. Nu a fost introdus in vanzari."]}

def model_settings():
    names = ("LOIAL_AI_OPENAI_API_KEY", "LOIAL_AI_INPUT_USD_PER_M",
             "LOIAL_AI_OUTPUT_USD_PER_M", "LOIAL_AI_USD_TO_EUR")
    values = [os.getenv(x, "").strip() for x in names]
    if not all(values):
        return None
    try:
        rates = [float(v) for v in values[1:]]
        if min(rates) <= 0:
            return None
        return values[0], rates
    except ValueError:
        return None

async def ask_model(system, question, usage, db, picture=None, advanced=False):
    settings = model_settings()
    budget = min(15.0, max(0.0, float(os.getenv("LOIAL_AI_MONTHLY_BUDGET_EUR", "5"))))
    if not settings or usage.cost_eur >= budget:
        return None
    key, rates = settings
    selected_model = os.getenv("LOIAL_AI_ECONOMY_MODEL", "gpt-4.1-nano")
    if advanced:
        strong = os.getenv("LOIAL_AI_ADVANCED_MODEL", "").strip()
        advanced_in = os.getenv("LOIAL_AI_ADVANCED_INPUT_USD_PER_M", "").strip()
        advanced_out = os.getenv("LOIAL_AI_ADVANCED_OUTPUT_USD_PER_M", "").strip()
        if strong and advanced_in and advanced_out:
            try:
                strong_rates = [float(advanced_in), float(advanced_out)]
                if min(strong_rates) > 0:
                    selected_model = strong
                    rates = [strong_rates[0], strong_rates[1], rates[2]]
            except ValueError:
                pass
    parts = [{"type": "text", "text": question[:12000]}]
    if picture:
        mime, raw = picture
        parts.append({"type": "image_url", "image_url": {"url":
                      "data:" + mime + ";base64," + base64.b64encode(raw).decode()}})
    payload = {"model": selected_model,
               "max_tokens": 750, "messages": [
                  {"role": "system", "content": system},
                  {"role": "user", "content": parts}]}
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions",
                                     json=payload, headers={"Authorization": "Bearer " + key})
        resp.raise_for_status()
        data = resp.json()
        response = data["choices"][0]["message"]["content"]
        spent = data.get("usage") or {}
        inp, out = int(spent.get("prompt_tokens") or 0), int(spent.get("completion_tokens") or 0)
        usage.input_tokens += inp
        usage.output_tokens += out
        usage.cost_eur += (inp * rates[0] + out * rates[1]) * rates[2] / 1000000
        db.commit()
        return response
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return None

def install_loial_ai(app, engine, session_factory, BusinessAccount, Customer,
                     Consent, secret_key, algorithm):
    BaseAI.metadata.create_all(bind=engine)
    r = APIRouter(prefix="/api/loial-ai", tags=["Loial AI Business"])
    def db_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()
    def owner(request: Request, db: Session = Depends(db_session)):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Autentificare obligatorie")
        try:
            payload = jwt.decode(auth[7:], secret_key, algorithms=[algorithm])
        except JWTError:
            raise HTTPException(status_code=401, detail="Token invalid")
        if payload.get("role") != "business" or not payload.get("sub"):
            raise HTTPException(status_code=403, detail="Doar administratorul firmei")
        biz = db.query(BusinessAccount).filter(BusinessAccount.email == payload["sub"]).first()
        if not biz or (payload.get("business_id") and payload["business_id"] != biz.id):
            raise HTTPException(status_code=403, detail="Acces interzis")
        if (biz.plan or "").lower() not in ("business", "probusiness", "pro", "premium", "enterprise"):
            raise HTTPException(status_code=403, detail="Disponibil in Loial Business")
        return biz
    def account_profile(db, biz):
        p = db.query(AIProfile).filter(AIProfile.business_id == biz.id).first()
        if not p:
            p = AIProfile(business_id=biz.id, sector=canonical(biz.business_type),
                          description="", currency="RON")
            db.add(p)
            db.commit()
        return p
    def usage_now(db, biz):
        month = date.today().strftime("%Y-%m")
        record = db.query(AIUsage).filter(AIUsage.business_id == biz.id, AIUsage.month == month).first()
        if not record:
            record = AIUsage(business_id=biz.id, month=month, input_tokens=0,
                             output_tokens=0, cost_eur=0)
            db.add(record)
            db.commit()
        return record
    def rows(db, biz):
        records = db.query(AISale).filter(AISale.business_id == biz.id).order_by(AISale.id.desc()).limit(10000).all()
        return [dict(product=x.product, quantity=x.quantity, unit_price=x.unit_price,
                     unit_variable_cost=x.unit_variable_cost, sold_at=x.sold_at,
                     transaction_id=x.transaction_id) for x in records]
    @r.get("/context")
    def context(biz=Depends(owner), db: Session = Depends(db_session)):
        p, u = account_profile(db, biz), usage_now(db, biz)
        return {"business": biz.name, "plan": biz.plan, "industry": profile(p.sector),
                "description": p.description, "currency": p.currency,
                "sectors": [{"key": k, "label": v["label"]} for k, v in PROFILES.items()],
                "topics": [{"key": k, "label": v} for k, v in TOPICS],
                "ai_connected": bool(model_settings()), "email_connected": bool(email_enabled()), "cost_eur": round(u.cost_eur, 4),
                "budget_eur": min(15, max(0, float(os.getenv("LOIAL_AI_MONTHLY_BUDGET_EUR", "5"))))}
    @r.put("/profile")
    def update_profile(req: ProfileRequest, biz=Depends(owner), db: Session = Depends(db_session)):
        p = account_profile(db, biz)
        p.sector, p.description, p.currency = canonical(req.sector), req.description.strip(), req.currency.upper()
        db.commit()
        return {"status": "saved", "industry": profile(p.sector)}
    @r.get("/history")
    def history(biz=Depends(owner), db: Session = Depends(db_session)):
        items = db.query(AIMessage).filter(AIMessage.business_id == biz.id).order_by(AIMessage.id.desc()).limit(80).all()
        return [{"role": x.role, "topic": x.topic, "text": x.content, "at": x.created_at}
                for x in reversed(items)]
    @r.get("/weekly")
    def weekly(biz=Depends(owner), db: Session = Depends(db_session)):
        p = account_profile(db, biz)
        recent = db.query(AIDocument).filter(AIDocument.business_id == biz.id).order_by(AIDocument.id.desc()).first()
        return {"message": weekly_request(p.sector), "last_document": recent.created_at if recent else None,
                "automated_delivery": False}
    @r.get("/report")
    def report(biz=Depends(owner), db: Session = Depends(db_session)):
        p = account_profile(db, biz)
        customers = db.query(Customer).filter(Customer.business_id == biz.id).all()
        manual = db.query(AIMetric).filter(AIMetric.business_id == biz.id).order_by(AIMetric.id.desc()).limit(60).all()
        operational = {}
        for x in reversed(manual):
            operational[x.name] = x.value
        calculated = sector_summary(p.sector, rows(db, biz), operational)
        return {"industry": profile(p.sector)["label"], "currency": p.currency,
                "sales": calculated, "abc": abc_products(calculated["products"]),
                "findings": manager_findings(calculated, p.sector),
                "customers": customer_segments(customers),
                "manual_metrics": [{"name": x.name, "value": x.value, "period": x.period} for x in manual],
                "limitations": calculated["missing"] + [
                    "Rapoartele contin doar date confirmate si nu substituie contabilitatea oficiala.",
                    "Profitul net nu poate fi calculat fara toate costurile relevante."]}
    @r.post("/metrics")
    def save_metric(req: MetricRequest, biz=Depends(owner), db: Session = Depends(db_session)):
        if not (-1e12 < req.value < 1e12):
            raise HTTPException(status_code=422, detail="Valoare invalida")
        m = AIMetric(business_id=biz.id, period=req.period, name=req.name,
                     value=req.value, source=req.source)
        db.add(m)
        db.commit()
        return {"status": "saved", "id": m.id}
    @r.post("/documents")
    async def upload(file: UploadFile = File(...), biz=Depends(owner),
                     db: Session = Depends(db_session)):
        name = (file.filename or "document")[:200]
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in (".csv", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(status_code=415, detail="Acceptam CSV, XLSX, PDF si imagini")
        raw = await file.read(4 * 1024 * 1024 + 1)
        if not raw or len(raw) > 4 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Dimensiune maxima: 4 MB")
        digest = hashlib.sha256(raw).hexdigest()
        previous = db.query(AIDocument).filter(AIDocument.business_id == biz.id,
                    AIDocument.sha256 == digest).first()
        if previous:
            return {"id": previous.id, "duplicate": True, "kind": previous.kind}
        try:
            if ext == ".csv":
                data = parse_sales_csv(raw)
            elif ext == ".xlsx":
                data = parse_xlsx(raw)
            elif ext == ".pdf":
                data = parse_pdf(raw)
            else:
                mime = "image/jpeg" if ext in (".jpg", ".jpeg") else (
                       "image/webp" if ext == ".webp" else "image/png")
                result = await ask_model(
                    "Extrage din fotografia documentului doar date vizibile. Returneaza JSON valid: kind, "
                    "merchant, date, rows (product, quantity, unit_price, unit_variable_cost daca este prezent), "
                    "uncertain_fields. Nu inventa nimic; nu extrage date personale nenecesare.",
                    "Interpreteaza documentul si semnaleaza valorile neclare.",
                    usage_now(db, biz), db, picture=(mime, raw))
                if not result:
                    raise HTTPException(status_code=503, detail="Extragerea din fotografii necesita activarea modelului AI; nu am pastrat imaginea")
                try:
                    data = json.loads(result.strip().replace(chr(96)*3 + "json", "").replace(chr(96)*3, ""))
                except ValueError:
                    raise HTTPException(status_code=422, detail="Date extrase neclare; reincarca o fotografie mai clara")
                if not isinstance(data, dict):
                    raise HTTPException(status_code=422, detail="Raspunsul extragerii nu este valid")
                data["kind"] = "photo_preview"
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        payload = json.dumps(data, ensure_ascii=False)
        if len(payload) > 220000:
            raise HTTPException(status_code=413, detail="Prea multe date in document")
        doc = AIDocument(business_id=biz.id, filename=name, sha256=digest, kind=data["kind"],
                         data_json=payload, confirmed=0, created_at=now())
        db.add(doc)
        db.commit()
        return {"id": doc.id, "kind": doc.kind, "confirmed": False,
                "preview": {"rows": data.get("rows", [])[:6], "notes": data.get("notes", []),
                            "uncertain_fields": data.get("uncertain_fields", [])},
                "message": "Verifica informatiile extrase. Nimic nu este adaugat automat in vanzari."}
    @r.get("/documents")
    def documents(biz=Depends(owner), db: Session = Depends(db_session)):
        data = db.query(AIDocument).filter(AIDocument.business_id == biz.id).order_by(AIDocument.id.desc()).limit(100).all()
        return [{"id": x.id, "name": x.filename, "type": x.kind,
                 "confirmed": bool(x.confirmed), "at": x.created_at} for x in data]
    @r.post("/documents/{doc_id}/confirm")
    def confirm(doc_id: int, biz=Depends(owner), db: Session = Depends(db_session)):
        doc = db.query(AIDocument).filter(AIDocument.business_id == biz.id, AIDocument.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document negasit")
        if doc.confirmed:
            return {"status": "already_confirmed"}
        if doc.kind != "sales":
            raise HTTPException(status_code=422, detail="Confirmarea automata este disponibila doar pentru exporturi de vanzari")
        content = json.loads(doc.data_json)
        for idx, item in enumerate(content["rows"]):
            db.add(AISale(business_id=biz.id, document_id=doc.id, row_number=idx,
                          sold_at=item["sold_at"], transaction_id=item.get("transaction_id"),
                          product=item["product"][:200], quantity=item["quantity"],
                          unit_price=item["unit_price"],
                          unit_variable_cost=item.get("unit_variable_cost"),
                          customer_uuid=item.get("customer_uuid")))
        doc.confirmed = 1
        db.commit()
        return {"status": "confirmed", "sales_lines": len(content["rows"])}
    @r.post("/chat")
    async def chat(req: ChatRequest, biz=Depends(owner), db: Session = Depends(db_session)):
        if req.topic not in {x[0] for x in TOPICS} | {"general"}:
            raise HTTPException(status_code=422, detail="Tema necunoscuta")
        day_count = db.query(AIMessage).filter(AIMessage.business_id == biz.id, AIMessage.role == "user",
                         AIMessage.created_at.like(date.today().isoformat() + "%")).count()
        if day_count >= 100:
            raise HTTPException(status_code=429, detail="Limita de 100 de mesaje zilnice")
        p = account_profile(db, biz)
        db.add(AIMessage(business_id=biz.id, role="user", topic=req.topic,
                         content=req.text.strip(), created_at=now()))
        db.commit()
        sales = sector_summary(p.sector, rows(db, biz))
        clients = db.query(Customer).filter(Customer.business_id == biz.id).all()
        data = {"sector": profile(p.sector), "description": p.description, "currency": p.currency,
                "summary": {k: sales[k] for k in ("total_revenue", "total_contribution", "missing", "sector_metrics")},
                "products": sales["products"][:15], "customers": customer_segments(clients)}
        recent_document = db.query(AIDocument).filter(AIDocument.business_id == biz.id).order_by(AIDocument.id.desc()).first()
        if recent_document:
            extracted = json.loads(recent_document.data_json or "{}")
            data["latest_document"] = {
                "kind": recent_document.kind,
                "confirmed": bool(recent_document.confirmed),
                "document_extract_unverified": json.dumps(extracted, ensure_ascii=False)[:5000]
            }
        recent_messages = db.query(AIMessage).filter(AIMessage.business_id == biz.id).order_by(AIMessage.id.desc()).limit(12).all()
        conversation = "\n".join(x.role + ": " + x.content[:1000] for x in reversed(recent_messages))
        system = ("Esti Loial, consultantul managerial al acestei afaceri. Vorbesti romaneste natural, "
                  "pe intelesul unui antreprenor fara pregatire contabila. "
                  "Te adaptezi activitatii. Explica decizii si cifre in termeni practici, nu formule, "
                  "prompturi sau rationament intern. Nu inventa date, nu echivala cifra de afaceri "
                  "cu profitul net, nu promite rezultate. Daca datele lipsesc cere screenshot, foto, "
                  "raport CSV sau PDF. Nicio campanie nu se trimite fara aprobare. "
                  "Context agregat verificabil: " + json.dumps(data, ensure_ascii=False) + "\n" + guidance(p.sector))
        answer = await ask_model(system, conversation, usage_now(db, biz), db,
                                 advanced=req.topic in ("products", "margin", "performance", "invoices"))
        active = answer is not None
        if not active:
            answer = ("Pot analiza activitatea ta de tip " + profile(p.sector)["label"] + ". " +
                      weekly_request(p.sector) + " " +
                      ("In acest moment nu am vanzari confirmate." if not sales["sales_lines"]
                       else "Incarcarile confirmate arata venituri de " + str(sales["total_revenue"]) + " " + p.currency + ".") +
                      " Chatul generativ va fi activ dupa configurarea furnizorului AI si a bugetului.")
        db.add(AIMessage(business_id=biz.id, role="assistant", topic=req.topic,
                         content=answer[:12000], created_at=now()))
        db.commit()
        return {"answer": answer, "mode": "ai" if active else "guided",
                "source": "profilul firmei si date agregate confirmate"}
    @r.post("/campaigns")
    async def draft_campaign(req: CampaignRequest, biz=Depends(owner), db: Session = Depends(db_session)):
        allowed = {"all", "active_0_7", "inactive_8_30", "inactive_31_90", "inactive_91_365"}
        if req.audience not in allowed:
            raise HTTPException(status_code=422, detail="Segment invalid")
        p = account_profile(db, biz)
        subject = "Noutati de la " + biz.name[:100]
        message = ("Buna! " + req.offer if req.offer else
                   "Buna! Te asteptam sa descoperi noutatile noastre.")
        summary = sector_summary(p.sector, rows(db, biz))
        structured = {"business": biz.name, "sector": profile(p.sector)["label"],
                      "objective": req.objective, "audience": req.audience,
                      "offer_explicit": req.offer, "products": summary["products"][:5]}
        prompt = ("Esti redactorul campaniilor Loial. Propune un email scurt, clar si natural pentru "
                  "afacerea descrisa. Returneaza NUMAI JSON valid cu cheile subject si text. "
                  "Nu inventa reduceri, preturi, promisiuni, stocuri, termene ori performante. "
                  "Nu mentiona public ca destinatarul a fost profilat dupa cumparaturi. "
                  "Nu comunica produse sensibile. Include doar oferte aprobate explicit de administrator.")
        result = await ask_model(prompt, json.dumps(structured, ensure_ascii=False),
                                 usage_now(db, biz), db)
        generated = False
        if result:
            try:
                candidate = json.loads(result.strip().replace(chr(96)*3 + "json", "").replace(chr(96)*3, ""))
                if (isinstance(candidate, dict) and isinstance(candidate.get("subject"), str)
                    and isinstance(candidate.get("text"), str) and
                        candidate["subject"].strip() and candidate["text"].strip()):
                    subject = candidate["subject"].strip()[:180]
                    message = candidate["text"].strip()[:2000]
                    generated = True
            except ValueError:
                pass
        draft = AICampaign(business_id=biz.id, audience=req.audience, objective=req.objective,
                           subject=subject, content=message, status="draft")
        db.add(draft)
        db.commit()
        return {"id": draft.id, "status": "draft", "subject": draft.subject,
                "text": draft.content, "generated_by_ai": generated, "sent": 0,
                "notice": "Previzualizare neexpediata. Administratorul verifica oferta si publicul."}
    @r.get("/campaigns")
    def campaigns(biz=Depends(owner), db: Session = Depends(db_session)):
        data = db.query(AICampaign).filter(AICampaign.business_id == biz.id).order_by(AICampaign.id.desc()).limit(60).all()
        return [{"id": x.id, "audience": x.audience, "objective": x.objective,
                 "subject": x.subject, "text": x.content, "status": x.status} for x in data]
    @r.post("/campaigns/{campaign_id}/approve")
    def approve(campaign_id: int, biz=Depends(owner), db: Session = Depends(db_session)):
        draft = db.query(AICampaign).filter(AICampaign.business_id == biz.id, AICampaign.id == campaign_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="Campanie inexistenta")
        draft.status = "approved_not_sent"
        db.commit()
        return {"status": draft.status, "sent": 0,
                "notice": "Trimiterea este dezactivata pana la configurarea emailului si verificarea consimtamantului."}
    @r.post("/campaigns/{campaign_id}/send")
    async def send_approved_campaign(campaign_id: int, req: SendCampaignRequest,
                                     biz=Depends(owner), db: Session = Depends(db_session)):
        if req.confirmation != "TRIMITE":
            raise HTTPException(status_code=422, detail="Confirmarea TRIMITE este obligatorie")
        campaign = db.query(AICampaign).filter(AICampaign.id == campaign_id,
                              AICampaign.business_id == biz.id).first()
        if not campaign or campaign.status not in ("approved_not_sent", "partially_sent"):
            raise HTTPException(status_code=409, detail="Campania trebuie aprobata inainte de trimitere")
        if not email_enabled():
            raise HTTPException(status_code=503, detail="Furnizorul email nu este activat")
        month_prefix = date.today().strftime("%Y-%m")
        month_count = db.query(AIEmailDispatch).filter(
            AIEmailDispatch.business_id == biz.id, AIEmailDispatch.status == "sent",
            AIEmailDispatch.sent_at.like(month_prefix + "%")).count()
        monthly_limit = max(0, min(5000, int(os.getenv("LOIAL_EMAIL_MONTHLY_LIMIT", "300"))))
        remaining_quota = max(0, monthly_limit - month_count)
        if remaining_quota == 0:
            raise HTTPException(status_code=429, detail="Cota lunara de email a fost atinsa")
        clients = db.query(Customer).filter(Customer.business_id == biz.id).all()
        allowed_ids = {x.customer_id for x in db.query(Consent).filter(
            Consent.purpose == "marketing_email", Consent.granted == 1).all()}
        eligible = eligible_segment(clients, campaign.audience, allowed_ids)
        sent = 0
        failed = 0
        for client in eligible:
            if sent >= min(25, remaining_quota):
                break
            existing = db.query(AIEmailDispatch).filter(
                AIEmailDispatch.campaign_id == campaign.id,
                AIEmailDispatch.customer_id == client.id).first()
            if existing:
                continue
            try:
                link = unsubscribe_url(biz.id, client.id, secret_key)
                succeeded = await send_text_email(client.email, campaign.subject,
                                                 campaign.content, link)
            except (httpx.HTTPError, RuntimeError, ValueError):
                succeeded = False
            if succeeded:
                db.add(AIEmailDispatch(business_id=biz.id, campaign_id=campaign.id,
                         customer_id=client.id, status="sent", sent_at=now()))
                db.commit()
                sent += 1
            else:
                failed += 1
        campaign.status = "partially_sent" if sent or failed else campaign.status
        db.commit()
        return {"sent_in_this_batch": sent, "failed_in_this_batch": failed,
                "monthly_quota_remaining": remaining_quota - sent,
                "status": campaign.status,
                "notice": "Trimitere partiala in loturi de maxim 25; reapeleaza doar cu aprobarea administratorului."}

    @r.post("/email/unsubscribe")
    def unsubscribe(req: UnsubscribeRequest, db: Session = Depends(db_session)):
        parsed = parse_unsubscribe_token(req.token, secret_key)
        if not parsed:
            raise HTTPException(status_code=400, detail="Link de dezabonare invalid")
        business_id, customer_id = parsed
        customer = db.query(Customer).filter(Customer.business_id == business_id,
                                              Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Client inexistent")
        consents = db.query(Consent).filter(Consent.customer_id == customer_id,
                                            Consent.purpose == "marketing_email").all()
        for c in consents:
            c.granted = 0
        if not consents:
            db.add(Consent(customer_id=customer_id, purpose="marketing_email",
                           granted=0, date=now(), ip="unsubscribe_link"))
        db.commit()
        return {"status": "unsubscribed", "message": "Nu vei mai primi mesaje comerciale prin email de la aceasta firma."}

    def export_csv(columns, records, filename):
        stream = io.StringIO()
        stream.write("\ufeff")
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(records)
        return StreamingResponse(iter([stream.getvalue().encode("utf-8")]),
                  media_type="text/csv; charset=utf-8",
                  headers={"Cache-Control": "no-store",
                           "Content-Disposition": 'attachment; filename="' + filename + '"'})
    @r.get("/exports/customers.csv")
    def customers_csv(biz=Depends(owner), db: Session = Depends(db_session)):
        customers = db.query(Customer).filter(Customer.business_id == biz.id).all()
        return export_csv(["id", "name", "email", "last_visit", "stamps"],
                          [[x.id, x.name, x.email or "", x.last_visit or "", x.stamps or 0]
                           for x in customers], "loial_clienti.csv")
    @r.get("/exports/sales.csv")
    def sales_csv(biz=Depends(owner), db: Session = Depends(db_session)):
        sales = db.query(AISale).filter(AISale.business_id == biz.id).limit(100000).all()
        return export_csv(["date", "transaction_id", "product", "quantity", "unit_price", "unit_variable_cost"],
                          [[x.sold_at, x.transaction_id or "", x.product, x.quantity, x.unit_price,
                            x.unit_variable_cost if x.unit_variable_cost is not None else ""] for x in sales],
                          "loial_vanzari.csv")
    @r.get("/exports/ads-consented.csv")
    def ads_csv(biz=Depends(owner), db: Session = Depends(db_session)):
        customers = db.query(Customer).filter(Customer.business_id == biz.id,
                                               Customer.email.isnot(None)).all()
        records = []
        for x in customers:
            if db.query(Consent).filter(Consent.customer_id == x.id,
                    Consent.purpose == "personalized_ads", Consent.granted == 1).first():
                records.append([x.email])
        return export_csv(["email"], records, "loial_ads_consimtamant.csv")
    @r.get("/message-templates")
    def message_templates(biz=Depends(owner), db: Session = Depends(db_session)):
        return [{"key": key, "label": tpl["label"],
                 "requires_marketing_permission": tpl["commercial"]}
                for key, tpl in TEMPLATES.items()]

    @r.get("/message-templates/{template_key}/preview")
    def preview_template(template_key: str, biz=Depends(owner),
                         db: Session = Depends(db_session)):
        if template_key not in TEMPLATES:
            raise HTTPException(status_code=404, detail="Sablon inexistent")
        return render_template(template_key, {"business": biz.name, "name": "Client",
                 "stamps": 2, "target": getattr(biz, "stamps_required", None) or 6,
                 "remaining": 4, "reward": biz.reward_text or "Premiu fidelitate",
                 "product": "produsul preferat", "offer": "Detalii la locatie."})

    @r.get("/customers")
    def customer_directory(page: int = 1, biz=Depends(owner),
                           db: Session = Depends(db_session)):
        page = max(1, page)
        records = db.query(Customer).filter(Customer.business_id == biz.id)
        count = records.count()
        clients = records.order_by(Customer.id.desc()).offset((page-1)*100).limit(100).all()
        return {"page": page, "total": count,
                "items": [{"id": c.id, "name": c.name, "email": c.email or "",
                           "last_visit": c.last_visit, "stamps": c.stamps or 0} for c in clients]}

    @r.get("/customers/{customer_id}/purchases")
    def purchase_history(customer_id: int, biz=Depends(owner),
                         db: Session = Depends(db_session)):
        customer = db.query(Customer).filter(Customer.business_id == biz.id,
                                              Customer.id == customer_id).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Client inexistent in firma ta")
        wallet = getattr(customer, "wallet_uuid", None) or customer.uuid
        ids = {wallet, customer.uuid}
        ids.discard(None)
        if not ids:
            return {"name": customer.name, "purchases": [], "note": "Nu exista identificator pentru legarea bonurilor"}
        lines = db.query(AISale).filter(AISale.business_id == biz.id,
                                        AISale.customer_uuid.in_(ids)).order_by(AISale.sold_at.desc()).limit(500).all()
        return {"name": customer.name,
                "purchases": [{"date": s.sold_at, "product": s.product, "quantity": s.quantity,
                               "total": round(s.quantity * s.unit_price, 2)} for s in lines],
                "note": "Produsele sunt asociate numai daca importul contine ID-ul clientului"}

    @r.get("/campaigns/{campaign_id}/audience")
    def campaign_audience(campaign_id: int, biz=Depends(owner),
                          db: Session = Depends(db_session)):
        draft = db.query(AICampaign).filter(AICampaign.business_id == biz.id,
                                             AICampaign.id == campaign_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="Campanie inexistenta")
        customers = db.query(Customer).filter(Customer.business_id == biz.id).all()
        consented = {c.customer_id for c in db.query(Consent).filter(
            Consent.purpose == "marketing_email", Consent.granted == 1).all()}
        eligible = eligible_segment(customers, draft.audience, consented)
        return {"campaign_id": draft.id, "segment": draft.audience,
                "eligible_email_recipients": len(eligible), "sent": 0,
                "note": "Verifica dreptul de marketing si preferintele inainte de a trimite. Mesajul nu a fost expediat."}

    app.include_router(r)
