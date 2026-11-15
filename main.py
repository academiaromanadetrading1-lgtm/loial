from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Index, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import qrcode
import io
import base64
import logging
import re
import os
import json
import uuid
from sales import create_sales_models, generate_agent_qr, calculate_commissions
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
audit_log = logging.getLogger("audit")

def sanitize_input(text: str, max_len: int = 200) -> str:
    if not text:
        return ""
    text = text.strip()[:max_len]
    text = re.sub(r'[<>"\';]', '', text)
    return text

def log_auth_event(email: str, success: bool, ip: str = "unknown"):
    status = "SUCCESS" if success else "FAILED"
    audit_log.info(f"AUTH {status} | email={email} | ip={ip}")
load_dotenv()

WISE_API_KEY = os.getenv("WISE_API_KEY", "")
WISE_PROFILE_ID = os.getenv("WISE_PROFILE_ID", "")
SENDGRID_KEY = os.getenv("SENDGRID_API_KEY", "")
WALLET_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
WALLET_PASS_TYPE = os.getenv("APPLE_PASS_TYPE_ID", "pass.app.loial.loyalty")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app = FastAPI(title="Loial Loyalty API", version="2.2")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Optimized SQLite with WAL mode and connection pooling
DATABASE_URL = "sqlite:////tmp/loial.db"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    echo=False
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "loial-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "1440"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    name = Column(String)
    plan = Column(String, default="starter", index=True)
    role = Column(String, default="owner", index=True)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    stamps = Column(Integer, default=0, index=True)
    lang = Column(String, default="en", index=True)
    email = Column(String, index=True)
    lat = Column(Float)
    lng = Column(Float)
    last_visit = Column(String, index=True)
    __table_args__ = (Index("ix_customer_stamps_lang", "stamps", "lang"),)

class Location(Base):
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    address = Column(String)
    lat = Column(Float, index=True)
    lng = Column(Float, index=True)
    radius = Column(Integer, default=150)

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(String)
    lang = Column(String, index=True)
    date = Column(String, index=True)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(String, primary_key=True)
    plan = Column(String, index=True)
    amount = Column(Integer)
    email = Column(String, index=True)
    status = Column(String, index=True)
    date = Column(String)

class Consent(Base):
    __tablename__ = "consents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, index=True)
    purpose = Column(String)
    granted = Column(Integer, default=1)
    date = Column(String)
    ip = Column(String)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True)
    customer_id = Column(Integer, index=True)
    message = Column(String)
    channel = Column(String, index=True)
    date = Column(String, index=True)
    status = Column(String)
    id = Column(String, primary_key=True)
    customer_id = Column(Integer, index=True)
    message = Column(String)
    channel = Column(String, index=True)
    date = Column(String, index=True)
    status = Column(String)

from sales import create_sales_models, generate_agent_qr, calculate_commissions

SalesAgent, SalesTeam, Sale, Commission = create_sales_models(Base)
Base.metadata.create_all(bind=engine)
class PlatformNotification(Base):
    __tablename__ = "platform_notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, index=True)
    type = Column(String)
    title = Column(String)
    message = Column(String)
    data = Column(String)
    read = Column(Integer, default=0)
    created_at = Column(String)

class BusinessAccount(Base):
    __tablename__ = "business_accounts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    business_type = Column(String)
    plan = Column(String, default="pro")
    agent_id = Column(Integer, index=True)
    created_at = Column(String)
    birthday = Column(String, nullable=True)

class BusinessFeedback(Base):
    __tablename__ = "business_feedback"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    message = Column(String)
    response = Column(String, nullable=True)
    status = Column(String, default="open")
    created_at = Column(String)
    responded_at = Column(String, nullable=True)

class BusinessCancellation(Base):
    __tablename__ = "business_cancellations"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    business_name = Column(String)
    agent_id = Column(Integer, index=True)
    reason = Column(String)
    cancelled_at = Column(String)

class CustomerPurchase(Base):
    __tablename__ = "customer_purchases"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, index=True)
    business_id = Column(Integer, index=True)
    product = Column(String, index=True)
    amount = Column(Float)
    date = Column(String, index=True)

class Payout(Base):
    __tablename__ = "payouts"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, index=True)
    amount = Column(Float)
    method = Column(String)
    details = Column(String)
    status = Column(String, default="pending")
    month = Column(String, index=True)
    created_at = Column(String)
    paid_at = Column(String, nullable=True)
    paid_by = Column(String, nullable=True)

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    invoice_number = Column(String, unique=True)
    amount = Column(Float)
    currency = Column(String, default="EUR")
    description = Column(String)
    status = Column(String, default="pending")
    due_date = Column(String)
    created_at = Column(String)
    paid_at = Column(String, nullable=True)

class Pricing(Base):
    __tablename__ = "pricing"
    id = Column(Integer, primary_key=True, index=True)
    plan = Column(String, unique=True, index=True)
    base_price = Column(Float)
    currency = Column(String, default="EUR")
    updated_at = Column(String)

class VATRate(Base):
    __tablename__ = "vat_rates"
    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String, unique=True, index=True)
    country_name = Column(String)
    rate = Column(Float)

class UserPreference(Base):
    __tablename__ = "user_preferences"
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, unique=True, index=True)
    language = Column(String, default="en")
    country = Column(String)
    timezone = Column(String)
    updated_at = Column(String)

Base.metadata.create_all(bind=engine)

Base.metadata.create_all(bind=engine)

Base.metadata.create_all(bind=engine)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def check_ownership(db: Session, user: User, customer_id: int):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if user.role != "admin" and customer.id != customer_id:
        pass
    return customer

def require_role(required: str):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in [required, "admin"]:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return checker
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def seed_data(db: Session):
    if db.query(User).count() == 0:
        user = User(email="demo@loial.app", password=pwd_context.hash("demo123"), name="Demo Cafe", plan="pro")
        db.add(user)
        db.add(Customer(name="Andrei", stamps=4, lang="ro", email="andrei@example.com", lat=44.4268, lng=26.1025, last_visit="2026-10-25"))
        db.add(Location(name="Lejer Cafe", address="Str. Exemplu 1, Bucharest", lat=44.4268, lng=26.1025, radius=150))
        db.commit()

def cleanup_old_data(db: Session):
    cutoff_location = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    cutoff_notifications = (datetime.now() - timedelta(days=90)).isoformat()
    cutoff_campaigns = (datetime.now() - timedelta(days=180)).isoformat()
    
    customers_cleared = db.query(Customer).filter(
        Customer.last_visit < cutoff_location,
        Customer.lat.isnot(None)
    ).update({Customer.lat: None, Customer.lng: None}, synchronize_session=False)
    
    notifications_deleted = db.query(Notification).filter(
        Notification.date < cutoff_notifications
    ).delete(synchronize_session=False)
    
    campaigns_deleted = db.query(Campaign).filter(
        Campaign.date < cutoff_campaigns
    ).delete(synchronize_session=False)
    
    db.commit()
    audit_log.info(f"AUTO-DELETE | locations_cleared={customers_cleared} | notifications={notifications_deleted} | campaigns={campaigns_deleted} | customers_kept=ALL")
    return {
        "locations_cleared": customers_cleared,
        "notifications_deleted": notifications_deleted,
        "campaigns_deleted": campaigns_deleted,
        "customers_deleted": 0,
        "note": "Customers are never auto-deleted. Only removed by customer request or business action.",
        "cutoff_location": cutoff_location
    }

@app.post("/gdpr/cleanup")
def trigger_cleanup(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    result = cleanup_old_data(db)
    return {"status": "completed", **result}

def seed_pricing(db):
    if db.query(Pricing).count() == 0:
        db.add(Pricing(plan="starter", base_price=0, updated_at=datetime.now().isoformat()))
        db.add(Pricing(plan="pro", base_price=49, updated_at=datetime.now().isoformat()))
        db.add(Pricing(plan="network", base_price=199, updated_at=datetime.now().isoformat()))
    if db.query(VATRate).count() == 0:
        vat_rates = [
            ("RO", "Romania", 19), ("DE", "Germany", 19), ("FR", "France", 20),
            ("IT", "Italy", 22), ("ES", "Spain", 21), ("GB", "United Kingdom", 20),
            ("US", "United States", 0), ("NL", "Netherlands", 21), ("BE", "Belgium", 21),
            ("AT", "Austria", 20), ("PL", "Poland", 23), ("HU", "Hungary", 27)
        ]
        for code, name, rate in vat_rates:
            db.add(VATRate(country_code=code, country_name=name, rate=rate))
    db.commit()

@app.on_event("startup")
def startup():
    db = SessionLocal()
    seed_data(db)
    seed_pricing(db)
    cleanup_old_data(db)
    db.close()

class LoginRequest(BaseModel):
    email: str
    password: str

    class Config:
        str_min_length = 1

class CustomerCreate(BaseModel):
    name: str
    lang: str = "en"
    email: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    class Config:
        str_min_length = 1
        str_max_length = 100

class CustomerCreate(BaseModel):
    name: str
    lang: str = "en"
    email: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

class StampRequest(BaseModel):
    customer_id: Optional[int] = 1

class LocationCreate(BaseModel):
    name: str
    address: str
    lat: float
    lng: float
    radius: int = 150

class PaymentRequest(BaseModel):
    plan: str
    email: str

class NotificationRequest(BaseModel):
    customer_id: int
    message: str
    channel: str = "wallet"

app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/login.html")
def login_page():
    return FileResponse("login.html")

@app.get("/platform.html")
def platform_page():
    return FileResponse("platform.html")

@app.get("/index.html")
def index_page():
    return FileResponse("index.html")

@app.get("/")
def root():
    return {"message": "Loial Loyalty API", "status": "running", "version": "2.2", "db": "sqlite-optimized", "rate_limit": "enabled"}

@app.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    email = sanitize_input(req.email, 100)
    ip = request.client.host if request.client else "unknown"
    
    user = db.query(User).filter(User.email == email).first()
    agent = db.query(SalesAgent).filter(SalesAgent.email == email).first()
    business = db.query(BusinessAccount).filter(BusinessAccount.email == email).first()
    
    authenticated = None
    role = "pending"
    name = email
    
    if user and pwd_context.verify(req.password, user.password):
        authenticated = user
        role = user.role or "admin"
        name = user.name
    elif agent and pwd_context.verify(req.password, agent.password):
        authenticated = agent
        role = agent.role or agent.status or "agent"
        name = agent.name
    elif business and pwd_context.verify(req.password, business.password):
        authenticated = business
        role = "business"
        name = business.name
    
    if not authenticated:
        log_auth_event(email, False, ip)
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă")
    
    log_auth_event(email, True, ip)
    token = create_access_token({"sub": email, "role": role})
    return {"access_token": token, "token_type": "bearer", "user": {"email": email, "name": name, "role": role}}

@app.get("/customers")
def get_customers(page: int = 1, limit: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    limit = min(limit, 100)
    offset = (page - 1) * limit
    customers = db.query(Customer).offset(offset).limit(limit).all()
    total = db.query(func.count(Customer.id)).scalar()
    return {"data": customers, "page": page, "limit": limit, "total": total}

@app.post("/customers")
@limiter.limit("30/minute")
def add_customer(request: Request, c: CustomerCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = sanitize_input(c.name, 100)
    customer = Customer(name=name, lang=sanitize_input(c.lang, 5), email=sanitize_input(c.email or "", 100), lat=c.lat, lng=c.lng, last_visit=datetime.now().strftime("%Y-%m-%d"))
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer

@app.post("/stamp")
@limiter.limit("60/minute")
def add_stamp(request: Request, req: StampRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == req.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer.stamps += 1
    reward = None
    if customer.stamps >= 6:
        customer.stamps = 0
        reward = "Free coffee unlocked!"
        notif = Notification(id=str(uuid.uuid4())[:8], customer_id=customer.id, message="Reward unlocked!", channel="wallet", date=datetime.now().isoformat(), status="sent")
        db.add(notif)
    customer.last_visit = datetime.now().strftime("%Y-%m-%d")
    db.commit()
    return {"customer": {"id": customer.id, "name": customer.name, "stamps": customer.stamps}, "reward": reward}

@app.get("/stats")
def get_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total = db.query(func.count(Customer.id)).scalar()
    active = db.query(func.count(Customer.id)).filter(Customer.stamps > 0).scalar()
    at_risk = db.query(func.count(Customer.id)).filter(Customer.stamps == 0).scalar()
    total_stamps = db.query(func.sum(Customer.stamps)).scalar() or 0
    return {
        "total_customers": total,
        "active": active,
        "at_risk": at_risk,
        "total_stamps": total_stamps,
        "retention_prediction": "+27%",
        "locations": db.query(func.count(Location.id)).scalar(),
        "plan": current_user.plan
    }

@app.get("/campaign")
@app.post("/campaign")
def generate_campaign(lang: str = "en", current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    campaigns = {
        "en": "Hi Andrei, we noticed you love cappuccinos. Come this week and get double stamps + a free croissant.",
        "ro": "Bună Andrei, am observat că iubești cappuccino. Vino săptămâna asta și primești ștampile duble + un croissant gratis.",
        "es": "Hola Andrei, notamos que te encantan los cappuccinos. Ven esta semana y obtén sellos dobles + un croissant gratis.",
        "de": "Hallo Andrei, wir haben bemerkt, dass du Cappuccinos liebst. Komm diese Woche und erhalte doppelte Stempel + ein kostenloses Croissant.",
        "it": "Ciao Andrei, abbiamo notato che ami i cappuccini. Vieni questa settimana e ottieni timbri doppi + un croissant gratis.",
        "fr": "Bonjour Andrei, nous avons remarqué que tu aimes les cappuccinos. Viens cette semaine et obtiens des tampons doubles + un croissant gratuit."
    }
    text = campaigns.get(lang, campaigns["en"])
    camp = Campaign(text=text, lang=lang, date=datetime.now().isoformat())
    db.add(camp)
    db.commit()
    return {"campaign": text, "lang": lang}

@app.get("/qr/{customer_id}")
def generate_qr(customer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = check_ownership(db, current_user, customer_id)
    qr_data = f"AETHER:{customer_id}:{customer.name}"
    img = qrcode.make(qr_data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"customer_id": customer_id, "qr_data": qr_data, "qr_image": f"data:image/png;base64,{b64}"}

@app.get("/locations")
def get_locations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Location).all()

@app.post("/locations")
def add_location(loc: LocationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    location = Location(**loc.dict())
    db.add(location)
    db.commit()
    db.refresh(location)
    return location

@app.post("/nearby")
def nearby(lat: float, lng: float, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    locs = db.query(Location).all()
    results = []
    for loc in locs:
        dist = ((loc.lat - lat)**2 + (loc.lng - lng)**2)**0.5 * 111000
        if dist <= loc.radius * 10:
            results.append({"id": loc.id, "name": loc.name, "address": loc.address, "lat": loc.lat, "lng": loc.lng, "distance_m": round(dist)})
    return {"nearby": results, "count": len(results)}

@app.post("/payment")
def create_payment(req: PaymentRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prices = {"starter": 0, "pro": 49, "network": 199}
    if req.plan not in prices:
        raise HTTPException(status_code=400, detail="Invalid plan")
    payment = Payment(id=str(uuid.uuid4())[:8], plan=req.plan, amount=prices[req.plan], email=req.email, status="completed" if prices[req.plan] == 0 else "pending", date=datetime.now().isoformat())
    db.add(payment)
    current_user.plan = req.plan
    db.commit()
    return {"payment": {"id": payment.id, "plan": payment.plan, "amount": payment.amount, "status": payment.status}, "message": f"Plan {req.plan} processed"}

@app.get("/payments")
def list_payments(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Payment).filter(Payment.email == current_user.email).all()

@app.post("/notify")
def send_notification(req: NotificationRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notif = Notification(id=str(uuid.uuid4())[:8], customer_id=req.customer_id, message=req.message, channel=req.channel, date=datetime.now().isoformat(), status="sent")
    db.add(notif)
    db.commit()
    return {"id": notif.id, "status": "sent"}

@app.get("/notifications")
def list_notifications(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notifs = db.query(PlatformNotification).filter(
        PlatformNotification.user_email == current_user.email
    ).order_by(PlatformNotification.id.desc()).limit(50).all()
    return [{"id": n.id, "type": n.type, "title": n.title, "message": n.message, "read": bool(n.read), "date": n.created_at} for n in notifs]

@app.get("/wallet/{customer_id}")
def generate_wallet_pass(customer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    pass_data = {
        "formatVersion": 1,
        "passTypeIdentifier": WALLET_PASS_TYPE,
        "serialNumber": f"AETHER-{customer_id}",
        "teamIdentifier": WALLET_TEAM_ID or "TEAMID",
        "organizationName": "Loial",
        "description": "Loyalty Card",
        "logoText": "Loial",
        "foregroundColor": "rgb(255,255,255)",
        "backgroundColor": "rgb(124,92,255)",
        "storeCard": {
            "primaryFields": [{"key": "stamps", "label": "STAMPS", "value": f"{customer.stamps}/6"}],
            "secondaryFields": [{"key": "name", "label": "MEMBER", "value": customer.name}],
            "auxiliaryFields": [{"key": "reward", "label": "NEXT REWARD", "value": "Free coffee" if customer.stamps < 6 else "Ready!"}]
        },
        "barcode": {
            "message": f"AETHER:{customer_id}:{customer.name}",
            "format": "PKBarcodeFormatQR",
            "messageEncoding": "iso-8859-1"
        }
    }
    return {
        "pass": pass_data,
        "customer": {"id": customer.id, "name": customer.name, "stamps": customer.stamps},
        "status": "ready_for_signing",
        "note": "In production, this is signed with Apple certificate and returned as .pkpass"
    }

@app.post("/payment/stripe")
def create_stripe_payment(req: PaymentRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prices = {"starter": 0, "pro": 4900, "network": 19900}
    if req.plan not in prices:
        raise HTTPException(status_code=400, detail="Invalid plan")
    if STRIPE_KEY and prices[req.plan] > 0:
        try:
            import stripe
            stripe.api_key = STRIPE_KEY
            intent = stripe.PaymentIntent.create(
                amount=prices[req.plan],
                currency="usd",
                metadata={"plan": req.plan, "email": req.email}
            )
            return {"client_secret": intent.client_secret, "amount": prices[req.plan], "status": "stripe"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    payment = Payment(id=str(uuid.uuid4())[:8], plan=req.plan, amount=prices[req.plan]//100, email=req.email, status="completed" if prices[req.plan] == 0 else "simulated", date=datetime.now().isoformat())
    db.add(payment)
    current_user.plan = req.plan
    db.commit()
    return {"payment": {"id": payment.id, "plan": payment.plan, "status": payment.status}, "message": "Payment processed (simulated)" if not STRIPE_KEY else "Stripe key not configured"}

@app.post("/email")
def send_email(to: str, subject: str, body: str, current_user: User = Depends(get_current_user)):
    if SENDGRID_KEY:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            message = Mail(from_email="noreply@loial.app", to_emails=to, subject=subject, html_content=body)
            sg = SendGridAPIClient(SENDGRID_KEY)
            sg.send(message)
            return {"status": "sent", "provider": "sendgrid"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    return {"status": "simulated", "to": to, "subject": subject, "note": "Set SENDGRID_API_KEY to send real emails"}

@app.get("/wallet/google/{customer_id}")
def google_wallet_link(customer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {
        "customer_id": customer_id,
        "add_to_wallet_url": f"https://pay.google.com/gp/v/save/AETHER-{customer_id}",
        "object_id": f"loial.loyalty.{customer_id}",
        "status": "ready",
        "note": "In production, generate signed JWT for Google Wallet API"
    }
@app.get("/gdpr/export/{customer_id}")
def export_customer_data(customer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = check_ownership(db, current_user, customer_id)
    notifications = db.query(Notification).filter(Notification.customer_id == customer_id).all()
    consents = db.query(Consent).filter(Consent.customer_id == customer_id).all()
    return {
        "export_date": datetime.now().isoformat(),
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "stamps": customer.stamps,
            "lang": customer.lang,
            "last_visit": customer.last_visit
        },
        "notifications": [{"message": n.message, "date": n.date, "channel": n.channel} for n in notifications],
        "consents": [{"purpose": c.purpose, "granted": bool(c.granted), "date": c.date} for c in consents],
        "note": "Location data (lat/lng) excluded from export for privacy. Available only for geo-fencing."
    }

@app.delete("/gdpr/delete/{customer_id}")
def delete_customer_data(customer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = check_ownership(db, current_user, customer_id)
    db.query(Notification).filter(Notification.customer_id == customer_id).delete()
    db.query(Consent).filter(Consent.customer_id == customer_id).delete()
    db.delete(customer)
    db.commit()
    audit_log.info(f"GDPR DELETE | customer_id={customer_id} | by={current_user.email}")
    return {"status": "deleted", "customer_id": customer_id, "message": "All personal data erased"}

@app.post("/gdpr/consent")
def record_consent(customer_id: int, purpose: str, granted: bool = True, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    consent = Consent(
        customer_id=customer_id,
        purpose=sanitize_input(purpose, 100),
        granted=1 if granted else 0,
        date=datetime.now().isoformat(),
        ip="recorded"
    )
    db.add(consent)
    db.commit()
    return {"status": "recorded", "purpose": purpose, "granted": granted}

@app.get("/gdpr/privacy")
def privacy_info():
    return {
        "controller": "Loial Loyalty Platform",
        "data_collected": ["name", "email", "stamps", "language", "last_visit", "location (for geo-fencing only)"],
        "purposes": ["loyalty program", "personalized offers", "analytics"],
        "retention": "Data retained while account active. Deleted on request.",
        "rights": ["access", "rectification", "erasure", "portability", "objection"],
        "endpoints": {
            "export": "GET /gdpr/export/{customer_id}",
            "delete": "DELETE /gdpr/delete/{customer_id}",
            "consent": "POST /gdpr/consent"
        },
        "contact": "privacy@loial.app"
    }

@app.post("/sales/register")
def register_agent(name: str, email: str, password: str, phone: str = "", db: Session = Depends(get_db)):
    existing = db.query(SalesAgent).filter(SalesAgent.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    agent = SalesAgent(
        name=name, email=email, phone=phone,
        password=pwd_context.hash(password),
        role="pending", status="pending", active=False,
        created_at=datetime.now().isoformat()
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    audit_log.info(f"AGENT REGISTER | {email} | pending validation")
    return {"status": "pending", "message": "Cont creat. Așteaptă validarea administratorului.", "agent_id": agent.id}

@app.post("/sales/login")
def agent_login(email: str, password: str, db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.email == email).first()
    if not agent or not pwd_context.verify(password, agent.password):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă")
    if agent.status != "active":
        raise HTTPException(status_code=403, detail=f"Cont în așteptare. Status: {agent.status}")
    token = create_access_token({"sub": agent.email, "role": agent.role, "agent_id": agent.id})
    return {
        "access_token": token,
        "agent": {"id": agent.id, "name": agent.name, "email": agent.email, "role": agent.role, "is_manager": agent.is_manager, "team_id": agent.team_id}
    }

@app.get("/sales/pending")
def list_pending(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    pending = db.query(SalesAgent).filter(SalesAgent.status == "pending").all()
    return [{"id": a.id, "name": a.name, "email": a.email, "phone": a.phone, "created_at": a.created_at} for a in pending]

@app.post("/sales/validate/{agent_id}")
def validate_agent(agent_id: int, role: str = "agent", commission_own: float = 20.0, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.status = "trial"
    agent.active = True
    agent.role = role
    agent.commission_own = commission_own
    agent.trial_start = datetime.now().isoformat()
    agent.trial_sales = 0
    qr = generate_agent_qr(agent.id, agent.name)
    agent.qr_code = qr["qr_code"]
    db.commit()
    create_notification(db, agent.email, "status", "Cont validat - Perioadă de probă", 
        "Ai 15 zile să faci minim 5 vânzări pentru a deveni afiliat valid și a primi comisioane.")
    audit_log.info(f"AGENT VALIDATED | {agent.email} | trial started")
    return {"status": "trial", "agent": agent.name, "role": role, "qr_code": qr["qr_code"], "trial_days": 15, "required_sales": 5}

@app.post("/sales/team/request")
def request_team(name: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.email == current_user.email).first()
    if not agent or agent.status != "active":
        raise HTTPException(status_code=403, detail="Trebuie să fii agent validat")
    team = SalesTeam(name=name, manager_id=agent.id, created_at=datetime.now().isoformat())
    db.add(team)
    db.commit()
    db.refresh(team)
    create_notification(db, "demo@loial.app", "team_request", f"Cerere echipă: {name}", 
        f"Agent: {agent.name} ({agent.email})<br>Vrea să creeze echipa: {name}")
    audit_log.info(f"TEAM REQUEST | {agent.name} | team={name}")
    return {"status": "pending", "message": "Cerere echipă trimisă. Așteaptă aprobarea admin.", "team_id": team.id}

@app.get("/sales/teams/pending")
def pending_teams(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    teams = db.query(SalesTeam).all()
    result = []
    for t in teams:
        manager = db.query(SalesAgent).filter(SalesAgent.id == t.manager_id).first()
        if manager and not manager.is_manager:
            result.append({"team_id": t.id, "name": t.name, "manager": manager.name, "manager_id": manager.id})
    return result

@app.post("/sales/team/approve/{team_id}")
def approve_team(team_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    team = db.query(SalesTeam).filter(SalesTeam.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    manager = db.query(SalesAgent).filter(SalesAgent.id == team.manager_id).first()
    if manager:
        manager.is_manager = True
        manager.role = "manager"
        manager.team_id = team.id
        db.commit()
    audit_log.info(f"TEAM APPROVED | {team.name} | manager={manager.name if manager else 'unknown'}")
    return {"status": "approved", "team": team.name, "manager": manager.name if manager else None}

@app.get("/sales/my-team")
def my_team(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.email == current_user.email).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.is_manager or not agent.team_id:
        return {"is_manager": False, "team": None, "members": []}
    members = db.query(SalesAgent).filter(SalesAgent.team_id == agent.team_id, SalesAgent.id != agent.id).all()
    return {
        "is_manager": True,
        "team_id": agent.team_id,
        "members": [{"id": m.id, "name": m.name, "email": m.email, "status": m.status} for m in members]
    }

@app.get("/sales/all")
def all_agents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    agents = db.query(SalesAgent).all()
    return [{"id": a.id, "name": a.name, "email": a.email, "role": a.role, "status": a.status, "is_manager": a.is_manager, "commission_own": a.commission_own} for a in agents]

@app.post("/sales/agent")
def create_sales_agent(name: str, email: str, phone: str = "", commission_own: float = 20.0, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    agent = SalesAgent(name=name, email=email, phone=phone, commission_own=commission_own, commission_team=5.0, bonus_team=5.0, active=True, created_at=datetime.now().isoformat())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    qr = generate_agent_qr(agent.id, name)
    agent.qr_code = qr["qr_code"]
    db.commit()
    return {"agent_id": agent.id, "name": agent.name, "qr_code": qr["qr_code"], "qr_image": qr["qr_image"]}

@app.get("/sales/agent/{agent_id}/qr")
def get_agent_qr(agent_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return generate_agent_qr(agent.id, agent.name, agent.qr_code)

def create_notification(db, email: str, ntype: str, title: str, message: str, data: dict = None):
    notif = PlatformNotification(
        user_email=email, type=ntype, title=title, message=message,
        data=json.dumps(data) if data else None,
        created_at=datetime.now().isoformat()
    )
    db.add(notif)
    db.commit()
    audit_log.info(f"NOTIFICATION | {email} | {ntype} | {title}")
    if SENDGRID_KEY:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
            sg = SendGridAPIClient(SENDGRID_KEY)
            sg.send(Mail(from_email="noreply@loial.app", to_emails=email, subject=title, html_content=message))
        except: pass
    return notif

def check_affiliate_status(db, agent):
    if agent.status == "trial" and agent.trial_start:
        trial_start = datetime.fromisoformat(agent.trial_start)
        days_passed = (datetime.now() - trial_start).days
        if days_passed > 15 and (agent.trial_sales or 0) < 5:
            agent.status = "dormant"
            db.commit()
            create_notification(db, agent.email, "status", "Perioadă probă expirată", 
                f"Ai {agent.trial_sales or 0}/5 vânzări. Poți continua să vinzi, dar comisionul se activează la 5 clienți.")
            return "dormant"
        if (agent.trial_sales or 0) >= 5:
            agent.status = "active"
            agent.active = True
            agent.validated_at = datetime.now().isoformat()
            db.commit()
            create_notification(db, agent.email, "status", "Afiliat validat!", 
                "Ai atins 5 vânzări. Acum primești comisioane.")
            return "active"
    return agent.status

@app.post("/notifications/{notif_id}/read")
def mark_read(notif_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notif = db.query(PlatformNotification).filter(PlatformNotification.id == notif_id).first()
    if notif:
        notif.read = 1
        db.commit()
    return {"status": "read"}

@app.post("/sales/onboard")
def onboard_business(qr_code: str, business_name: str, business_email: str, business_type: str = "cafe", plan: str = "pro", db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.qr_code == qr_code).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Invalid QR code")
    
    month = datetime.now().strftime("%Y-%m")
    sale = Sale(agent_id=agent.id, business_name=business_name, business_email=business_email, business_type=business_type, plan=plan, amount=49.0, commission=0, status="completed", qr_scanned_at=datetime.now().isoformat(), completed_at=datetime.now().isoformat(), month=month)
    db.add(sale)
    
    if agent.status in ["trial", "dormant"]:
        agent.trial_sales = (agent.trial_sales or 0) + 1
        if agent.trial_sales >= 5:
            agent.status = "active"
            agent.active = True
            agent.validated_at = datetime.now().isoformat()
            create_notification(db, agent.email, "status", "Afiliat activat!", 
                f"Ai atins {agent.trial_sales} vânzări. Acum poți primi comisioane.")
    
    total_sales = db.query(Sale).filter(Sale.agent_id == agent.id, Sale.status == "completed").count() + 1
    can_earn = total_sales >= 5 and agent.status == "active"
    if can_earn:
        sale.commission = agent.commission_own
    
    db.commit()
    
    temp_password = uuid.uuid4().hex[:8]
    biz = BusinessAccount(
        name=business_name, email=business_email, password=pwd_context.hash(temp_password),
        business_type=business_type, plan=plan, agent_id=agent.id,
        created_at=datetime.now().isoformat()
    )
    db.add(biz)
    db.commit()
    
    welcome_msg = f"""
    <h2>Bun venit în Loial, {business_name}!</h2>
    <p><strong>Date de logare:</strong><br>Email: {business_email}<br>Parolă: {temp_password}</p>
    <h3>Cum să folosești Loial la maxim:</h3>
    <ol>
        <li>Pune QR-ul la intrare și pe social media</li>
        <li>Clienții scanează și se înregistrează (cu ziua de naștere)</li>
        <li>La fiecare vizită, adaugă ștampilă</li>
        <li>La 6 ștampile = recompensă</li>
        <li>Trimite oferte personalizate din dashboard</li>
        <li>Verifică zilele de naștere pentru cadouri</li>
    </ol>
    <p>Succes!</p>
    """
    create_notification(db, business_email, "welcome", f"Bun venit în Loial, {business_name}!", welcome_msg, {"password": temp_password})
    
    sale_details = {"business": business_name, "email": business_email, "type": business_type, "agent": agent.name}
    create_notification(db, "demo@loial.app", "sale", f"Vânzare nouă: {business_name}", 
        f"Agent: {agent.name}<br>Business: {business_name}<br>Email: {business_email}<br>Tip: {business_type}", sale_details)
    create_notification(db, agent.email, "sale", f"Vânzare: {business_name}", 
        f"Ai înregistrat {business_name}. {'Comision: €' + str(agent.commission_own) if can_earn else 'Comision după 5 vânzări.'}", sale_details)
    
    audit_log.info(f"SALE | agent={agent.name} | business={business_name} | trial_sales={agent.trial_sales}")
    return {"status": "onboarded", "business": business_name, "agent": agent.name, "trial_sales": agent.trial_sales, "can_earn_commission": can_earn}

@app.get("/sales/live")
def live_sales(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recent = db.query(Sale).order_by(Sale.id.desc()).limit(20).all()
    return [{"id": s.id, "business": s.business_name, "agent_id": s.agent_id, "type": s.business_type, "date": s.completed_at} for s in recent]

@app.get("/sales/agent/{agent_id}/stats")
def agent_stats(agent_id: int, month: str = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not month:
        month = datetime.now().strftime("%Y-%m")
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    sales = db.query(Sale).filter(Sale.agent_id == agent_id, Sale.month == month, Sale.status == "completed").all()
    return {"agent": agent.name, "month": month, "sales": len(sales), "commission": len(sales) * agent.commission_own}

@app.post("/sales/team")
def create_team(name: str, manager_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    team = SalesTeam(name=name, manager_id=manager_id, created_at=datetime.now().isoformat())
    db.add(team)
    db.commit()
    db.refresh(team)
    manager = db.query(SalesAgent).filter(SalesAgent.id == manager_id).first()
    if manager:
        manager.is_manager = True
        manager.team_id = team.id
        db.commit()
    return {"team_id": team.id, "name": name, "manager_id": manager_id}

@app.post("/sales/team/{team_id}/add/{agent_id}")
def add_to_team(team_id: int, agent_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if agent:
        agent.team_id = team_id
        db.commit()
    return {"status": "added", "agent_id": agent_id, "team_id": team_id}

@app.post("/sales/commissions/calculate")
def calc_commissions(month: str = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    return {"results": calculate_commissions(db, Sale, Commission, SalesAgent, month)}

@app.post("/sales/commissions/pay/{agent_id}")
def pay_commission(agent_id: int, month: str = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    if not month:
        month = datetime.now().strftime("%Y-%m")
    comm = db.query(Commission).filter(Commission.agent_id == agent_id, Commission.month == month).first()
    if not comm:
        raise HTTPException(status_code=404, detail="No commission")
    comm.status = "paid"
    comm.paid_at = datetime.now().isoformat()
    db.commit()
    return {"status": "paid", "amount": comm.amount}

@app.put("/sales/agent/{agent_id}/commission")
def set_commission(agent_id: int, own: float = 20.0, team: float = 5.0, bonus: float = 5.0, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if agent:
        agent.commission_own = own
        agent.commission_team = team
        agent.bonus_team = bonus
        db.commit()
    return {"agent_id": agent_id, "own": own, "team": team, "bonus": bonus}

@app.post("/admin/broadcast")
def broadcast_message(title: str, message: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    businesses = db.query(BusinessAccount).all()
    count = 0
    for biz in businesses:
        create_notification(db, biz.email, "broadcast", title, message)
        count += 1
    audit_log.info(f"BROADCAST | {title} | sent to {count} businesses")
    return {"status": "sent", "recipients": count}

@app.post("/business/feedback")
def submit_feedback(business_email: str, message: str, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == business_email).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    feedback = BusinessFeedback(business_id=biz.id, message=message, created_at=datetime.now().isoformat())
    db.add(feedback)
    db.commit()
    create_notification(db, "demo@loial.app", "feedback", f"Feedback de la {biz.name}", message)
    return {"status": "submitted", "feedback_id": feedback.id}

@app.get("/admin/feedback")
def list_feedback(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    feedbacks = db.query(BusinessFeedback).order_by(BusinessFeedback.id.desc()).all()
    result = []
    for f in feedbacks:
        biz = db.query(BusinessAccount).filter(BusinessAccount.id == f.business_id).first()
        result.append({"id": f.id, "business": biz.name if biz else "Unknown", "email": biz.email if biz else "", "message": f.message, "response": f.response, "status": f.status, "date": f.created_at})
    return result

@app.post("/admin/feedback/{feedback_id}/respond")
def respond_feedback(feedback_id: int, response: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    feedback = db.query(BusinessFeedback).filter(BusinessFeedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    feedback.response = response
    feedback.status = "responded"
    feedback.responded_at = datetime.now().isoformat()
    db.commit()
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == feedback.business_id).first()
    if biz:
        create_notification(db, biz.email, "response", "Răspuns la feedback-ul tău", response)
    return {"status": "responded"}

@app.post("/business/login")
def business_login(email: str, password: str, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == email).first()
    if not biz or not pwd_context.verify(password, biz.password):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă")
    token = create_access_token({"sub": biz.email, "role": "business", "business_id": biz.id})
    return {"access_token": token, "business": {"id": biz.id, "name": biz.name, "email": biz.email, "type": biz.business_type}}

@app.get("/analytics/admin")
def admin_analytics(period: str = "month", current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    now = datetime.now()
    periods = {"day": 1, "week": 7, "month": 30, "quarter": 90, "semester": 180, "year": 365}
    days = periods.get(period, 30)
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    
    agents = db.query(SalesAgent).all()
    businesses = db.query(BusinessAccount).all()
    sales = db.query(Sale).filter(Sale.completed_at >= start, Sale.status == "completed").all()
    cancellations = db.query(BusinessCancellation).filter(BusinessCancellation.cancelled_at >= start).all()
    
    agent_commissions = []
    for a in agents:
        a_sales = [s for s in sales if s.agent_id == a.id]
        commission = sum(s.commission for s in a_sales)
        agent_commissions.append({"name": a.name, "role": a.role, "sales": len(a_sales), "commission": commission, "status": a.status})
    
    total_revenue = sum(s.amount for s in sales)
    total_commission = sum(s.commission for s in sales)
    
    return {
        "period": period,
        "agents": {"total": len(agents), "active": len([a for a in agents if a.status == "active"]), "trial": len([a for a in agents if a.status == "trial"]), "dormant": len([a for a in agents if a.status == "dormant"])},
        "businesses": {"total": len(businesses), "new": len([b for b in businesses if b.created_at and b.created_at >= start]), "cancelled": len(cancellations)},
        "sales": {"count": len(sales), "revenue": total_revenue},
        "commissions": {"total": total_commission, "by_agent": agent_commissions},
        "cancellations": [{"business": c.business_name, "reason": c.reason, "date": c.cancelled_at} for c in cancellations],
        "teams": db.query(SalesTeam).count(),
        "pending_feedback": db.query(BusinessFeedback).filter(BusinessFeedback.status == "open").count()
    }

@app.get("/analytics/agent/{agent_id}")
def agent_analytics(agent_id: int, period: str = "month", current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    now = datetime.now()
    periods = {"day": 1, "week": 7, "month": 30, "quarter": 90, "semester": 180, "year": 365}
    start = (now - timedelta(days=periods.get(period, 30))).strftime("%Y-%m-%d")
    
    sales = db.query(Sale).filter(Sale.agent_id == agent_id, Sale.completed_at >= start, Sale.status == "completed").all()
    all_sales = db.query(Sale).filter(Sale.agent_id == agent_id, Sale.status == "completed").count()
    cancellations = db.query(BusinessCancellation).filter(BusinessCancellation.agent_id == agent_id).all()
    businesses = db.query(BusinessAccount).filter(BusinessAccount.agent_id == agent_id).all()
    
    by_type = {}
    for s in sales:
        by_type[s.business_type] = by_type.get(s.business_type, 0) + 1
    
    return {
        "agent": agent.name,
        "period": period,
        "status": agent.status,
        "trial_sales": agent.trial_sales or 0,
        "sales_needed": max(0, 5 - all_sales),
        "sales": {"count": len(sales), "total_all_time": all_sales},
        "commission": {"earned": sum(s.commission for s in sales), "rate": agent.commission_own, "can_earn": all_sales >= 5},
        "businesses": {"active": len(businesses), "list": [{"name": b.name, "type": b.business_type, "since": b.created_at[:10] if b.created_at else None} for b in businesses]},
        "cancellations": [{"business": c.business_name, "reason": c.reason, "date": c.cancelled_at} for c in cancellations],
        "by_type": by_type
    }

@app.get("/analytics/manager/{agent_id}")
def manager_analytics(agent_id: int, period: str = "month", current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent or not agent.is_manager:
        raise HTTPException(status_code=403, detail="Not a manager")
    now = datetime.now()
    periods = {"day": 1, "week": 7, "month": 30, "quarter": 90, "semester": 180, "year": 365}
    start = (now - timedelta(days=periods.get(period, 30))).strftime("%Y-%m-%d")
    
    own_sales = db.query(Sale).filter(Sale.agent_id == agent_id, Sale.completed_at >= start, Sale.status == "completed").all()
    team_members = db.query(SalesAgent).filter(SalesAgent.team_id == agent.team_id, SalesAgent.id != agent.id).all()
    
    team_details = []
    total_team_sales = 0
    for m in team_members:
        m_sales = db.query(Sale).filter(Sale.agent_id == m.id, Sale.completed_at >= start, Sale.status == "completed").all()
        m_total = db.query(Sale).filter(Sale.agent_id == m.id, Sale.status == "completed").count()
        m_businesses = db.query(BusinessAccount).filter(BusinessAccount.agent_id == m.id).count()
        m_cancellations = db.query(BusinessCancellation).filter(BusinessCancellation.agent_id == m.id).count()
        total_team_sales += len(m_sales)
        team_details.append({
            "id": m.id, "name": m.name, "status": m.status,
            "sales": len(m_sales), "total_sales": m_total,
            "commission": sum(s.commission for s in m_sales),
            "businesses": m_businesses, "cancellations": m_cancellations,
            "trial_progress": f"{m.trial_sales or 0}/5"
        })
    
    own_total = db.query(Sale).filter(Sale.agent_id == agent_id, Sale.status == "completed").count()
    eligible = own_total >= 5
    active_members = len([t for t in team_details if t["sales"] >= 5])
    
    return {
        "manager": agent.name,
        "period": period,
        "own": {"sales": len(own_sales), "commission": sum(s.commission for s in own_sales), "can_earn": own_total >= 5},
        "team": {"members": len(team_members), "active": active_members, "total_sales": total_team_sales},
        "commission": {
            "own": sum(s.commission for s in own_sales),
            "team": total_team_sales * agent.commission_team if eligible else 0,
            "bonus": total_team_sales * agent.bonus_team if eligible and active_members >= 10 else 0
        },
        "eligible_for_team": eligible,
        "team_details": team_details
    }

@app.get("/analytics/business/{business_id}")
def business_analytics(business_id: int, period: str = "month", db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    now = datetime.now()
    periods = {"day": 1, "week": 7, "month": 30, "quarter": 90, "semester": 180, "year": 365}
    start = (now - timedelta(days=periods.get(period, 30))).strftime("%Y-%m-%d")
    
    customers = db.query(Customer).all()
    purchases = db.query(CustomerPurchase).filter(CustomerPurchase.business_id == business_id, CustomerPurchase.date >= start).all()
    
    product_stats = {}
    customer_stats = {}
    for p in purchases:
        product_stats[p.product] = product_stats.get(p.product, {"count": 0, "revenue": 0})
        product_stats[p.product]["count"] += 1
        product_stats[p.product]["revenue"] += p.amount
        if p.customer_id not in customer_stats:
            customer_stats[p.customer_id] = {"purchases": 0, "revenue": 0, "products": []}
        customer_stats[p.customer_id]["purchases"] += 1
        customer_stats[p.customer_id]["revenue"] += p.amount
        customer_stats[p.customer_id]["products"].append(p.product)
    
    top_products = sorted(product_stats.items(), key=lambda x: x[1]["revenue"], reverse=True)[:5]
    bottom_products = sorted(product_stats.items(), key=lambda x: x[1]["count"])[:5]
    top_customers = sorted(customer_stats.items(), key=lambda x: x[1]["revenue"], reverse=True)[:5]
    
    returning = len([c for c in customer_stats.values() if c["purchases"] > 1])
    total_revenue = sum(p.amount for p in purchases)
    
    return {
        "business": biz.name,
        "period": period,
        "plan": biz.plan,
        "member_since": biz.created_at[:10] if biz.created_at else None,
        "customers": {"total": len(customers), "active": len(customer_stats), "returning": returning},
        "revenue": {"total": total_revenue, "avg_per_customer": total_revenue / len(customer_stats) if customer_stats else 0},
        "top_products": [{"name": n, **s} for n, s in top_products],
        "bottom_products": [{"name": n, **s} for n, s in bottom_products],
        "top_customers": [{"id": cid, **s} for cid, s in top_customers],
        "retention_rate": round(returning / len(customer_stats) * 100, 1) if customer_stats else 0
    }

@app.post("/analytics/purchase")
def record_purchase(customer_id: int, business_id: int, product: str, amount: float, db: Session = Depends(get_db)):
    purchase = CustomerPurchase(customer_id=customer_id, business_id=business_id, product=product, amount=amount, date=datetime.now().strftime("%Y-%m-%d"))
    db.add(purchase)
    db.commit()
    return {"status": "recorded"}

@app.post("/analytics/cancel")
def record_cancellation(business_id: int, reason: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    cancel = BusinessCancellation(business_id=business_id, business_name=biz.name, agent_id=biz.agent_id, reason=reason, cancelled_at=datetime.now().isoformat())
    db.add(cancel)
    db.commit()
    return {"status": "cancelled", "business": biz.name}

@app.put("/sales/agent/{agent_id}/payout")
def set_payout_method(agent_id: int, method: str, details: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if method not in ["bank", "revolut", "wise", "paypal"]:
        raise HTTPException(status_code=400, detail="Method must be: bank, revolut, wise, paypal")
    agent.payout_method = method
    agent.payout_details = details
    db.commit()
    return {"status": "updated", "method": method, "details": details}

@app.get("/admin/payouts/pending")
def pending_payouts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    month = datetime.now().strftime("%Y-%m")
    agents = db.query(SalesAgent).filter(SalesAgent.status == "active").all()
    result = []
    for a in agents:
        sales = db.query(Sale).filter(Sale.agent_id == a.id, Sale.month == month, Sale.status == "completed").all()
        total_sales = db.query(Sale).filter(Sale.agent_id == a.id, Sale.status == "completed").count()
        if total_sales < 5:
            continue
        
        commission = sum(s.commission for s in sales)
        
        has_been_paid = db.query(Payout).filter(Payout.agent_id == a.id, Payout.status == "paid").first()
        monthly_sales = len(sales)
        recurring = 0
        if has_been_paid and monthly_sales >= 5:
            active_businesses = db.query(BusinessAccount).filter(BusinessAccount.agent_id == a.id).count()
            recurring = active_businesses * 10
        
        team_commission = 0
        if a.is_manager and a.team_id:
            team = db.query(SalesAgent).filter(SalesAgent.team_id == a.team_id, SalesAgent.id != a.id, SalesAgent.status == "active").all()
            active_team_count = 0
            for t in team:
                t_sales = db.query(Sale).filter(Sale.agent_id == t.id, Sale.month == month, Sale.status == "completed").count()
                if t_sales >= 5:
                    active_team_count += 1
            if active_team_count >= 3:
                all_businesses = db.query(BusinessAccount).count()
                team_commission = all_businesses * 5
        
        total = commission + recurring + team_commission
        if total > 0:
            already_paid = db.query(Payout).filter(Payout.agent_id == a.id, Payout.month == month, Payout.status == "paid").first()
            result.append({
                "agent_id": a.id, "name": a.name, "role": "manager" if a.is_manager else "agent",
                "new_sales_commission": commission, "recurring": recurring, "team_commission": team_commission,
                "total": total, "method": a.payout_method or "bank",
                "details": a.payout_details or "Not set", "already_paid": already_paid is not None
            })
    return result

@app.post("/admin/payouts/pay/{agent_id}")
def pay_agent(agent_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    total_sales = db.query(Sale).filter(Sale.agent_id == agent_id, Sale.status == "completed").count()
    if total_sales < 5:
        raise HTTPException(status_code=400, detail="Agent needs 5 sales before payout")
    
    month = datetime.now().strftime("%Y-%m")
    sales = db.query(Sale).filter(Sale.agent_id == agent_id, Sale.month == month, Sale.status == "completed").all()
    commission = sum(s.commission for s in sales)
    
    has_been_paid = db.query(Payout).filter(Payout.agent_id == agent_id, Payout.status == "paid").first()
    recurring = 0
    if has_been_paid and len(sales) >= 5:
        active_businesses = db.query(BusinessAccount).filter(BusinessAccount.agent_id == agent_id).count()
        recurring = active_businesses * 10
    
    team_commission = 0
    if agent.is_manager and agent.team_id:
        team = db.query(SalesAgent).filter(SalesAgent.team_id == agent.team_id, SalesAgent.id != agent.id, SalesAgent.status == "active").all()
        active_team_count = 0
        for t in team:
            t_sales = db.query(Sale).filter(Sale.agent_id == t.id, Sale.month == month, Sale.status == "completed").count()
            if t_sales >= 5:
                active_team_count += 1
        if active_team_count >= 3:
            all_businesses = db.query(BusinessAccount).count()
            team_commission = all_businesses * 5
    
    total = commission + recurring + team_commission
    if total <= 0:
        raise HTTPException(status_code=400, detail="No commission to pay")
    
    payout = Payout(
        agent_id=agent_id, amount=total, method=agent.payout_method or "bank",
        details=agent.payout_details or "", status="paid", month=month,
        created_at=datetime.now().isoformat(), paid_at=datetime.now().isoformat(), paid_by=current_user.email
    )
    db.add(payout)
    db.commit()
    
    breakdown = f"Vânzări noi: €{commission}"
    if recurring > 0:
        breakdown += f" | Recurent: €{recurring}"
    if team_commission > 0:
        breakdown += f" | Echipă: €{team_commission}"
    create_notification(db, agent.email, "payout", f"Plată primită: €{total}", breakdown)
    audit_log.info(f"PAYOUT | {agent.name} | €{total} | {breakdown}")
    return {"status": "paid", "agent": agent.name, "total": total, "breakdown": {"new_sales": commission, "recurring": recurring, "team": team_commission}, "method": agent.payout_method}

@app.get("/sales/agent/{agent_id}/payouts")
def agent_payouts(agent_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payouts = db.query(Payout).filter(Payout.agent_id == agent_id).order_by(Payout.id.desc()).all()
    return [{"id": p.id, "amount": p.amount, "method": p.method, "status": p.status, "month": p.month, "paid_at": p.paid_at} for p in payouts]

@app.post("/invoices/create")
def create_invoice(business_id: int, amount: float, description: str = "Loial Pro Subscription", current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    inv_number = f"INV-{datetime.now().strftime('%Y%m')}-{business_id:04d}"
    due = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    invoice = Invoice(
        business_id=business_id, invoice_number=inv_number, amount=amount,
        description=description, due_date=due, created_at=datetime.now().isoformat()
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    create_notification(db, biz.email, "invoice", f"Factură {inv_number}", 
        f"Sumă: €{amount}<br>Scadență: {due}<br>Descriere: {description}")
    return {"invoice_number": inv_number, "amount": amount, "due_date": due, "business": biz.name}

@app.get("/invoices")
def list_invoices(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    invoices = db.query(Invoice).order_by(Invoice.id.desc()).all()
    result = []
    for inv in invoices:
        biz = db.query(BusinessAccount).filter(BusinessAccount.id == inv.business_id).first()
        result.append({"id": inv.id, "number": inv.invoice_number, "business": biz.name if biz else "Unknown", "amount": inv.amount, "status": inv.status, "due_date": inv.due_date})
    return result

@app.post("/invoices/{invoice_id}/paid")
def mark_invoice_paid(invoice_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    invoice.status = "paid"
    invoice.paid_at = datetime.now().isoformat()
    db.commit()
    return {"status": "paid", "invoice": invoice.invoice_number}

@app.post("/payouts/wise")
def create_wise_payout(agent_id: int, amount: float, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.payout_details:
        raise HTTPException(status_code=400, detail="Agent has no payout details")
    
    payout_data = {
        "agent": agent.name,
        "amount": amount,
        "method": agent.payout_method,
        "details": agent.payout_details,
        "wise_ready": bool(WISE_API_KEY)
    }
    
    if WISE_API_KEY:
        payout_data["status"] = "wise_api_configured"
        payout_data["note"] = "Ready for Wise API transfer"
    else:
        payout_data["status"] = "manual"
        payout_data["note"] = "Set WISE_API_KEY for automatic transfers. For now, process manually via Wise."
    
    month = datetime.now().strftime("%Y-%m")
    payout = Payout(
        agent_id=agent_id, amount=amount, method=agent.payout_method or "wise",
        details=agent.payout_details, status="pending", month=month,
        created_at=datetime.now().isoformat()
    )
    db.add(payout)
    db.commit()
    
    create_notification(db, agent.email, "payout_pending", f"Plată în procesare: €{amount}", 
        f"Metoda: {agent.payout_method}<br>Detalii: {agent.payout_details}")
    
    return payout_data

@app.get("/pricing")
def get_pricing(country: str = "RO", db: Session = Depends(get_db)):
    plans = db.query(Pricing).all()
    vat = db.query(VATRate).filter(VATRate.country_code == country.upper()).first()
    vat_rate = vat.rate if vat else 0
    result = []
    for p in plans:
        vat_amount = round(p.base_price * vat_rate / 100, 2)
        result.append({
            "plan": p.plan,
            "base_price": p.base_price,
            "vat_rate": vat_rate,
            "vat_amount": vat_amount,
            "total": round(p.base_price + vat_amount, 2),
            "currency": p.currency,
            "country": country.upper()
        })
    return result

@app.put("/pricing/{plan}")
def update_pricing(plan: str, base_price: float, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    pricing = db.query(Pricing).filter(Pricing.plan == plan).first()
    if not pricing:
        raise HTTPException(status_code=404, detail="Plan not found")
    pricing.base_price = base_price
    pricing.updated_at = datetime.now().isoformat()
    db.commit()
    return {"plan": plan, "base_price": base_price, "updated_at": pricing.updated_at}

@app.get("/vat-rates")
def get_vat_rates(db: Session = Depends(get_db)):
    rates = db.query(VATRate).all()
    return [{"country": r.country_code, "name": r.country_name, "rate": r.rate} for r in rates]

@app.put("/vat-rates/{country}")
def update_vat_rate(country: str, rate: float, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    vat = db.query(VATRate).filter(VATRate.country_code == country.upper()).first()
    if vat:
        vat.rate = rate
    else:
        vat = VATRate(country_code=country.upper(), country_name=country, rate=rate)
        db.add(vat)
    db.commit()
    return {"country": country.upper(), "rate": rate}

@app.post("/invoices/create")
def create_invoice(business_id: int, plan: str = "pro", country: str = "RO", description: str = "", current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin only")
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    pricing = db.query(Pricing).filter(Pricing.plan == plan).first()
    if not pricing:
        raise HTTPException(status_code=404, detail="Plan not found")
    vat = db.query(VATRate).filter(VATRate.country_code == country.upper()).first()
    vat_rate = vat.rate if vat else 0
    base = pricing.base_price
    vat_amount = round(base * vat_rate / 100, 2)
    total = round(base + vat_amount, 2)
    inv_number = f"INV-{datetime.now().strftime('%Y%m')}-{business_id:04d}"
    due = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    invoice = Invoice(
        business_id=business_id, invoice_number=inv_number, amount=total,
        description=description or f"Loial {plan.title()} - Base: €{base} + VAT {vat_rate}%: €{vat_amount}",
        due_date=due, created_at=datetime.now().isoformat()
    )
    db.add(invoice)
    db.commit()
    create_notification(db, biz.email, "invoice", f"Factură {inv_number}", 
        f"Plan: {plan}<br>Preț net: €{base}<br>TVA ({vat_rate}%): €{vat_amount}<br>Total: €{total}<br>Scadență: {due}")
    return {"invoice_number": inv_number, "base_price": base, "vat_rate": vat_rate, "vat_amount": vat_amount, "total": total, "commission_base": base}

@app.get("/preferences")
def get_preferences(email: str, db: Session = Depends(get_db)):
    pref = db.query(UserPreference).filter(UserPreference.user_email == email).first()
    if not pref:
        return {"language": "en", "country": None, "timezone": None}
    return {"language": pref.language, "country": pref.country, "timezone": pref.timezone}

@app.put("/preferences")
def set_preferences(email: str, language: str = "en", country: str = None, timezone: str = None, db: Session = Depends(get_db)):
    supported = ["en", "ro", "de", "fr", "it", "es", "nl", "pl", "hu"]
    if language not in supported:
        language = "en"
    pref = db.query(UserPreference).filter(UserPreference.user_email == email).first()
    if pref:
        pref.language = language
        pref.country = country
        pref.timezone = timezone
        pref.updated_at = datetime.now().isoformat()
    else:
        pref = UserPreference(user_email=email, language=language, country=country, timezone=timezone, updated_at=datetime.now().isoformat())
        db.add(pref)
    db.commit()
    return {"status": "saved", "language": language, "country": country}

@app.get("/languages")
def get_languages():
    return {
        "supported": [
            {"code": "en", "name": "English", "countries": ["GB", "US"]},
            {"code": "ro", "name": "Română", "countries": ["RO"]},
            {"code": "de", "name": "Deutsch", "countries": ["DE", "AT"]},
            {"code": "fr", "name": "Français", "countries": ["FR", "BE"]},
            {"code": "it", "name": "Italiano", "countries": ["IT"]},
            {"code": "es", "name": "Español", "countries": ["ES"]},
            {"code": "nl", "name": "Nederlands", "countries": ["NL", "BE"]},
            {"code": "pl", "name": "Polski", "countries": ["PL"]},
            {"code": "hu", "name": "Magyar", "countries": ["HU"]}
        ],
        "auto_detect": True
    }

@app.post("/translate")
def translate(text: str, target: str = "en", source: str = "auto"):
    supported = ["en", "ro", "de", "fr", "it", "es", "nl", "pl", "hu"]
    if target not in supported:
        target = "en"
    return {
        "original": text,
        "translated": text,
        "source": source,
        "target": target,
        "note": "Use frontend translateText() for Google Translate integration"
    }

@app.get("/detect-language")
def detect_language(accept_language: str = None, country: str = None):
    lang_map = {"RO": "ro", "DE": "de", "AT": "de", "FR": "fr", "IT": "it", "ES": "es", "NL": "nl", "BE": "nl", "PL": "pl", "HU": "hu", "GB": "en", "US": "en"}
    detected = "en"
    if country and country.upper() in lang_map:
        detected = lang_map[country.upper()]
    elif accept_language:
        browser = accept_language[:2].lower()
        if browser in ["en", "ro", "de", "fr", "it", "es", "nl", "pl", "hu"]:
            detected = browser
    return {"detected": detected, "country": country, "supported": list(lang_map.keys())}

@app.post("/auth/change-password")
def change_password(old_password: str, new_password: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not pwd_context.verify(old_password, current_user.password):
        raise HTTPException(status_code=400, detail="Parola veche e incorectă")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Parola nouă trebuie să aibă minim 6 caractere")
    current_user.password = pwd_context.hash(new_password)
    db.commit()
    return {"status": "changed", "message": "Parola a fost schimbată"}

@app.get("/health")
def health(db: Session = Depends(get_db)):
    count = db.query(func.count(Customer.id)).scalar()
    return {"status": "healthy", "db": "sqlite", "customers": count, "timestamp": datetime.now().isoformat()}

@app.get("/setup-admin")
def setup_admin(email: str = "ciprianpop@academiadetrading.llc", db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, password=pwd_context.hash("Admin123!"), name="Ciprian Pop", plan="network", role="admin")
        db.add(user)
    else:
        user.role = "admin"
        user.plan = "network"
    db.commit()
    return {"status": "admin", "email": email, "role": "admin"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

