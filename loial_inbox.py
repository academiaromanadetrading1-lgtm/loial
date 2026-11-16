"""Loial native messaging.

Messages are stored and shown in the client's Loial wallet: NO SMS, email provider
or per-message fee. A wallet-only bearer token protects private inbox delivery.
The QR code is NOT an authentication token.
"""
import hashlib
import secrets
from datetime import datetime, timezone, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Session, declarative_base

InboxBase = declarative_base()
BUSINESS_PLANS = {"business", "probusiness", "pro", "premium", "enterprise"}
AUDIENCES = {"all", "active_0_7", "inactive_8_30", "inactive_31_90",
             "inactive_91_365", "product_buyers"}
PURPOSE = "loial_inapp_marketing"

def now():
    return datetime.now(timezone.utc).isoformat()

class WalletInboxAccess(InboxBase):
    __tablename__ = "loial_wallet_inbox_access"
    id = Column(Integer, primary_key=True)
    wallet_uuid = Column(String(120), nullable=False, unique=True, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(String(40), nullable=False)

class InboxEntry(InboxBase):
    __tablename__ = "loial_inbox_entries"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False, index=True)
    title = Column(String(160), nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(30), nullable=False)
    source_event = Column(String(140), nullable=True)
    created_at = Column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("business_id", "source_event",
                                      name="uq_loial_inbox_event"),)

class InboxDelivery(InboxBase):
    __tablename__ = "loial_inbox_deliveries"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, nullable=False, index=True)
    business_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    created_at = Column(String(40), nullable=False)
    read_at = Column(String(40), nullable=True)
    __table_args__ = (UniqueConstraint("entry_id", "customer_id",
                                      name="uq_loial_delivery_customer"),)

class DirectMessage(BaseModel):
    subject: str = Field(min_length=2, max_length=120)
    text: str = Field(min_length=2, max_length=2000)
    audience: str = Field(default="all", max_length=40)
    product: str = Field(default="", max_length=200)
    customer_ids: Optional[List[int]] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=120)

class OfferChoice(BaseModel):
    business_id: int
    enabled: bool

def access_hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def issue_wallet_access(db, wallet_uuid, is_new_wallet, proposed_token=None):
    """Issue/verify a private wallet credential, never from public QR alone.

    A device may propose its own cryptographically random secret before enrollment.
    Retrying with that SAME secret returns access; presenting only wallet_uuid
    does not. Legacy wallets without a credential require verified recovery.
    """
    if proposed_token is not None and not (
        isinstance(proposed_token,str) and 40 <= len(proposed_token) <= 180
    ):
        raise ValueError("Secretul privat al dispozitivului nu este valid")
    existing = db.query(WalletInboxAccess).filter(
        WalletInboxAccess.wallet_uuid == wallet_uuid).first()
    if existing:
        if proposed_token and access_hash(proposed_token) == existing.token_hash:
            return proposed_token
        return None
    if not is_new_wallet:
        return None
    token = proposed_token or secrets.token_urlsafe(32)
    db.add(WalletInboxAccess(wallet_uuid=wallet_uuid, token_hash=access_hash(token),
                             created_at=now()))
    db.flush()
    return token

def record_offer_choice(db, Consent, customer_id, enabled, source="wallet"):
    db.add(Consent(customer_id=customer_id, purpose=PURPOSE, granted=int(bool(enabled)),
                   date=now(), ip=source))

def latest_offer_choice(db, Consent, customer_id):
    row = db.query(Consent).filter(Consent.customer_id == customer_id,
                                  Consent.purpose == PURPOSE).order_by(Consent.id.desc()).first()
    return bool(row and row.granted == 1)

def queue_service_event(db, business, customer, kind="stamp", returning=False, event_key=None):
    """Atomic with an enrollment or stamp transaction; no external delivery."""
    target = getattr(business, "stamps_required", None) or 6
    count = customer.stamps or 0
    name = (customer.name or "Bun venit").strip()[:60]
    remaining = max(0, target - count)
    if kind == "welcome":
        title = "Bun venit la " + business.name
        body = "Cardul tau Loial este activ. Te asteptam la urmatoarea vizita!"
        event = "welcome:" + str(customer.id)
    elif kind == "redeem":
        title = "Recompensa folosita la " + business.name
        body = "Ai folosit recompensa: " + (business.reward_text or "Premiul de fidelitate")
        body += ". Cardul tau a fost resetat la 0 stampile. Te asteptam din nou!"
        event = "redeem:" + str(customer.id) + ":" + str(event_key or count)
    elif kind == "reversal":
        title = "Corectie de stampile la " + business.name
        body = "Un bon a fost anulat. Stampila aferenta a fost retrasa; ai acum "
        body += str(count) + " din " + str(target) + " stampile."
        event = "reversal:" + str(customer.id) + ":" + str(event_key or count)
    else:
        title = "Ai primit o stampila la " + business.name
        body = ("Bine ai revenit! " if returning else "Multumim pentru vizita! ")
        body += "Ai acum " + str(count) + " din " + str(target) + " stampile."
        if remaining == 0:
            body += " Recompensa este disponibila: " + (business.reward_text or "Premiul de fidelitate")
        else:
            body += " Mai ai " + str(remaining) + " stampile pana la recompensa."
        event = "stamp:" + str(customer.id) + ":" + str(event_key or count)
    if db.query(InboxEntry).filter(InboxEntry.business_id == business.id,
                                    InboxEntry.source_event == event).first():
        return False
    entry = InboxEntry(business_id=business.id, title=title[:160], body=body[:2000],
                       category="service", source_event=event, created_at=now())
    db.add(entry)
    db.flush()
    db.add(InboxDelivery(entry_id=entry.id, business_id=business.id, customer_id=customer.id,
                         created_at=now()))
    return True

def read_customer_ids(db, business_id, Sale, product):
    if not product.strip():
        return set()
    matched = db.query(Sale.customer_uuid).filter(
        Sale.business_id == business_id,
        func.lower(Sale.product) == product.strip().lower(),
        Sale.customer_uuid.isnot(None)).distinct().all()
    return {x[0] for x in matched if x[0]}

def audience_matches(customer, audience, reference=None):
    if audience in ("all", "product_buyers"):
        return True
    ref = reference or date.today()
    try:
        seen = datetime.fromisoformat(str(customer.last_visit).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return False
    d = (ref - seen).days
    return {"active_0_7": d <= 7, "inactive_8_30": 8 <= d <= 30,
            "inactive_31_90": 31 <= d <= 90,
            "inactive_91_365": 91 <= d <= 365}.get(audience, False)

def install_loial_inbox(app, engine, factory, BusinessAccount, Customer, Consent,
                        Sale, jwt_key, jwt_algorithm):
    InboxBase.metadata.create_all(bind=engine)
    route = APIRouter(prefix="/api/loial-inbox", tags=["Loial native inbox"])

    def db_session():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    def owner(request: Request, db: Session = Depends(db_session)):
        authorization = request.headers.get("Authorization") or ""
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Autentificare obligatorie")
        try:
            claims = jwt.decode(authorization[7:], jwt_key, algorithms=[jwt_algorithm])
        except JWTError:
            raise HTTPException(status_code=401, detail="Sesiune expirata sau invalida")
        if claims.get("role") != "business":
            raise HTTPException(status_code=403, detail="Doar administratorul firmei")
        account = db.query(BusinessAccount).filter(
            BusinessAccount.email == claims.get("sub")).first()
        if not account or (claims.get("business_id") and claims["business_id"] != account.id):
            raise HTTPException(status_code=403, detail="Acces refuzat")
        if (account.plan or "").lower() not in BUSINESS_PLANS:
            raise HTTPException(status_code=403, detail="Disponibil in Loial Business")
        return account

    def client(request: Request, db: Session = Depends(db_session)):
        token = (request.headers.get("X-Loial-Wallet-Token") or "").strip()
        if not (40 <= len(token) <= 180):
            raise HTTPException(status_code=401, detail="Accesul privat la portofel lipseste")
        access = db.query(WalletInboxAccess).filter(
            WalletInboxAccess.token_hash == access_hash(token)).first()
        if not access:
            raise HTTPException(status_code=401, detail="Dispozitivul nu este autorizat")
        return access

    def cards_for(db, wallet_id):
        return db.query(Customer).filter(
            (Customer.wallet_uuid == wallet_id) | (Customer.uuid == wallet_id)).all()

    def business_audience(db, account, audience, product, selected_ids=None):
        if audience not in AUDIENCES:
            raise HTTPException(status_code=422, detail="Segment necunoscut")
        if audience == "product_buyers" and not product.strip():
            raise HTTPException(status_code=422, detail="Alege produsul sau serviciul")
        product_wallets = read_customer_ids(db, account.id, Sale, product) if product.strip() else None
        users = db.query(Customer).filter(Customer.business_id == account.id).all()
        selected = [c for c in users if selected_ids is None or c.id in selected_ids]
        # Citim acordurile intr-un numar constant de interogari pe lot, nu una per client.
        grants = {}
        for index in range(0, len(selected), 400):
            block_ids = [c.id for c in selected[index:index+400]]
            consents = db.query(Consent).filter(
                Consent.customer_id.in_(block_ids), Consent.purpose == PURPOSE
            ).order_by(Consent.id.asc()).all()
            for consent in consents:
                grants[consent.customer_id] = bool(consent.granted)
        result = []
        for c in selected:
            if not grants.get(c.id, False):
                continue
            if not audience_matches(c, audience):
                continue
            if product_wallets is not None and c.uuid not in product_wallets and (
                getattr(c, "wallet_uuid", None) not in product_wallets):
                continue
            result.append(c)
        return result

    @route.post("/send")
    def send_direct(req: DirectMessage, biz=Depends(owner), db: Session = Depends(db_session)):
        event = "direct:" + req.idempotency_key if req.idempotency_key else None
        if event:
            previous = db.query(InboxEntry).filter(
                InboxEntry.business_id == biz.id, InboxEntry.source_event == event).first()
            if previous:
                if previous.title != req.subject.strip() or previous.body != req.text.strip():
                    raise HTTPException(status_code=409, detail="Cheia mesajului a fost reutilizata pentru alt text")
                delivered = db.query(InboxDelivery).filter(InboxDelivery.entry_id == previous.id).count()
                return {"message_id": previous.id, "sent": delivered,
                        "status": "already_delivered", "channel": "loial", "external_messages": 0}
        if req.customer_ids is not None and len(req.customer_ids) > 10000:
            raise HTTPException(status_code=422, detail="Selectie prea mare; foloseste segmentul toti")
        ids = set(req.customer_ids) if req.customer_ids is not None else None
        eligible = business_audience(db, biz, req.audience, req.product, ids)
        if not eligible:
            return {"sent": 0, "visible_to_wallets": 0, "status": "no_eligible_clients",
                    "message": "Nu exista clienti din segment care sa fi permis oferte in Loial."}
        entry = InboxEntry(business_id=biz.id, title=req.subject.strip(), body=req.text.strip(),
                           category="marketing", source_event=event, created_at=now())
        db.add(entry)
        db.flush()
        sent = 0
        accessible = 0
        wallet_ids = {(getattr(c, "wallet_uuid", None) or c.uuid) for c in eligible}
        wallet_ids.discard(None)
        access_wallets = set()
        identifiers = list(wallet_ids)
        for index in range(0, len(identifiers), 400):
            for wallet_id, in db.query(WalletInboxAccess.wallet_uuid).filter(
                WalletInboxAccess.wallet_uuid.in_(identifiers[index:index+400])).all():
                access_wallets.add(wallet_id)
        for c in eligible:
            db.add(InboxDelivery(entry_id=entry.id, business_id=biz.id, customer_id=c.id,
                                 created_at=now()))
            sent += 1
            if (getattr(c, "wallet_uuid", None) or c.uuid) in access_wallets:
                accessible += 1
        db.commit()
        return {"message_id": entry.id, "sent": sent, "visible_to_wallets": accessible,
                "awaiting_wallet_activation": sent-accessible, "status": "delivered_in_loial",
                "channel": "loial", "external_messages": 0}

    @route.get("/audience")
    def preview_audience(audience: str = "all", product: str = "",
                         biz=Depends(owner), db: Session = Depends(db_session)):
        recipients = business_audience(db, biz, audience, product)
        return {"eligible": len(recipients), "audience": audience,
                "channel": "loial", "fee_per_message": 0,
                "note": "Numai clienti care au permis ofertele Loial. Nicio taxa de SMS sau email."}

    @route.get("/sent")
    def sent_history(biz=Depends(owner), db: Session = Depends(db_session)):
        data = db.query(InboxEntry).filter(
            InboxEntry.business_id == biz.id, InboxEntry.category == "marketing"
        ).order_by(InboxEntry.id.desc()).limit(80).all()
        return [{"id": m.id, "subject": m.title, "text": m.body, "at": m.created_at,
                 "delivered": db.query(InboxDelivery).filter(InboxDelivery.entry_id == m.id).count(),
                 "read": db.query(InboxDelivery).filter(InboxDelivery.entry_id == m.id,
                                                        InboxDelivery.read_at.isnot(None)).count()}
                for m in data]

    @route.get("/me")
    def my_inbox(wallet=Depends(client), db: Session = Depends(db_session)):
        cards = cards_for(db, wallet.wallet_uuid)
        ids = {c.id for c in cards}
        if not ids:
            return {"messages": [], "unread": 0, "cards": 0}
        deliveries = db.query(InboxDelivery).filter(
            InboxDelivery.customer_id.in_(ids)).order_by(
            InboxDelivery.id.desc()).limit(120).all()
        messages = []
        unread = 0
        for delivery in deliveries:
            entry = db.query(InboxEntry).filter(
                InboxEntry.id == delivery.entry_id,
                InboxEntry.business_id == delivery.business_id).first()
            biz = db.query(BusinessAccount).filter(
                BusinessAccount.id == delivery.business_id).first()
            if not entry or not biz:
                continue
            messages.append({"delivery_id": delivery.id, "business_id": biz.id,
                "business_name": biz.name, "subject": entry.title, "text": entry.body,
                "kind": entry.category, "created_at": delivery.created_at,
                "read": delivery.read_at is not None})
            if not delivery.read_at:
                unread += 1
        return {"messages": messages, "unread": unread, "cards": len(cards)}

    @route.post("/read/{delivery_id}")
    def mark_read(delivery_id: int, wallet=Depends(client), db: Session = Depends(db_session)):
        allowed = {c.id for c in cards_for(db, wallet.wallet_uuid)}
        delivery = db.query(InboxDelivery).filter(
            InboxDelivery.id == delivery_id,
            InboxDelivery.customer_id.in_(allowed)).first()
        if not delivery:
            raise HTTPException(status_code=404, detail="Mesaj negasit")
        if delivery.read_at is None:
            delivery.read_at = now()
            db.commit()
        return {"read": True}

    @route.get("/preferences")
    def preferences(wallet=Depends(client), db: Session = Depends(db_session)):
        cards = cards_for(db, wallet.wallet_uuid)
        result = []
        for c in cards:
            biz = db.query(BusinessAccount).filter(BusinessAccount.id == c.business_id).first()
            if biz:
                result.append({"business_id": biz.id, "business_name": biz.name,
                               "offers_enabled": latest_offer_choice(db, Consent, c.id)})
        return result

    @route.post("/preferences")
    def set_preferences(req: OfferChoice, wallet=Depends(client),
                        db: Session = Depends(db_session)):
        c = next((c for c in cards_for(db, wallet.wallet_uuid)
                  if c.business_id == req.business_id), None)
        if c is None:
            raise HTTPException(status_code=404, detail="Cardul pentru afacere nu exista")
        record_offer_choice(db, Consent, c.id, req.enabled, "wallet_preference")
        db.commit()
        return {"business_id": req.business_id, "offers_enabled": req.enabled}

    app.include_router(route)
