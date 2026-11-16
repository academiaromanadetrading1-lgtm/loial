from fastapi import Response
from fastapi.responses import JSONResponse, FileResponse
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
import secrets
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
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "https://loial.space").split(",") if origin.strip()]

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
DATABASE_URL = os.getenv("LOIAL_DATABASE_URL", "sqlite:////data/loial.db")
if not DATABASE_URL.startswith("sqlite:///"):
    raise RuntimeError("LOIAL_DATABASE_URL accepta doar conexiuni SQLite pentru acest deployment")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
    echo=False
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
if len(SECRET_KEY) < 32:
    raise RuntimeError("Configurare obligatorie: JWT_SECRET_KEY unic, minimum 32 caractere in secret manager")
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
    uuid = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, index=True)
    phone = Column(String, nullable=True)
    stamps = Column(Integer, default=0, index=True)
    lang = Column(String, default="en", index=True)
    email = Column(String, index=True, nullable=True)
    business_id = Column(Integer, index=True, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    last_visit = Column(String, index=True, nullable=True)
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
    business_type = Column(String, nullable=True)
    plan = Column(String, default="free")
    max_customers = Column(Integer, default=50)
    google_review_url = Column(String, nullable=True)
    reward_text = Column(String, default="A 6-a e din partea casei!")
    card_color = Column(String, default="#1e293b")
    staff_pin = Column(String, default=None)
    agent_id = Column(Integer, index=True, nullable=True)
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
    """Seeding explicit only. Never create admin/demo accounts with public passwords."""
    if os.getenv("LOIAL_DEV_SEED_DATA", "0") == "1" and db.query(User).count() == 0:
        demo_secret = os.getenv("LOIAL_DEV_DEMO_PASSWORD", "")
        if len(demo_secret) < 12:
            raise RuntimeError("Set LOIAL_DEV_DEMO_PASSWORD (minim 12 caractere) for explicit dev seed")
        db.add(User(email="demo@loial.app", password=pwd_context.hash(demo_secret),
                    name="Cont demo", plan="starter", role="owner"))
    admin_email = os.getenv("LOIAL_ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
    admin_secret = os.getenv("LOIAL_ADMIN_BOOTSTRAP_PASSWORD", "")
    if admin_email:
        if len(admin_secret) < 12:
            raise RuntimeError("LOIAL_ADMIN_BOOTSTRAP_PASSWORD trebuie sa aiba minimum 12 caractere")
        existing = db.query(User).filter(User.email == admin_email).first()
        if not existing:
            db.add(User(email=admin_email, password=pwd_context.hash(admin_secret),
                        name="Administrator Loial", plan="pro", role="admin"))
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
    pro_plan = db.query(Pricing).filter(Pricing.plan == "pro").first()
    if not pro_plan:
        db.add(Pricing(plan="starter", base_price=0, updated_at=datetime.now().isoformat()))
        db.add(Pricing(plan="pro", base_price=65, updated_at=datetime.now().isoformat()))
        db.add(Pricing(plan="network", base_price=199, updated_at=datetime.now().isoformat()))
    else:
        pro_plan.base_price = 65
        pro_plan.updated_at = datetime.now().isoformat()
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
    try:
        seed_data(db)
        seed_pricing(db)
        cleanup_old_data(db)
    finally:
        db.close()
    # Cerere saptamanala fara email/SMS/AI: mesaj intern in chatul administratorului.
    from loial_weekly_jobs import start_weekly_worker
    from loial_business_ai import AIProfile, AIDocument, AIMessage, AISale
    start_weekly_worker(engine, SessionLocal,
                        (BusinessAccount, AIProfile, AIDocument, AIMessage, AISale))
    # Sincronizarea externa Google Wallet este optionala si dezactivata fara emitent.
    from loial_wallet_sync import start_google_sync_worker
    start_google_sync_worker(engine, SessionLocal, (BusinessAccount, Customer))

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

@app.get("/register.html")
def register_page():
    return FileResponse("register.html")

@app.get("/join.html")
def join_html_page():
    return FileResponse("join.html")

@app.get("/scan.html")
def scan_html_page():
    return FileResponse("scan.html")

@app.get("/review.html")
def review_html_page():
    return FileResponse("review.html")


@app.get("/platform.html")
def platform_page():
    return FileResponse("platform.html")

@app.get("/index.html")
def index_page():
    return FileResponse("index.html")

@app.get("/")
def root(request: Request):
    token = request.cookies.get("loial_token")
    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return FileResponse("platform.html")
        except:
            pass
    return FileResponse("index.html")

@app.post("/auth/login")
@limiter.limit("20/minute")
def login(request: Request, response: Response, req: LoginRequest, db: Session = Depends(get_db)):
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
    biz_id_val = business.id if business else None
    response.set_cookie(key="loial_token", value=token, httponly=True, max_age=86400, samesite="lax")
    return {
        "access_token": token,
        "token_type": "bearer",
        "business_id": biz_id_val,
        "user": {"email": email, "name": name, "role": role}
    }


@app.post("/auth/logout")
@app.get("/auth/logout")
def logout_endpoint():
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie(key="loial_token")
    return response


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

# ==========================================
# LOIAL GROWTH, QR, REVIEW GATE & SEO ROUTES
# ==========================================
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text

class PublicReviewFeedback(Base):
    __tablename__ = "public_review_feedback"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    rating = Column(Integer)
    message = Column(String)
    created_at = Column(String)

Base.metadata.create_all(bind=engine)

def run_loial_migrations():
    with engine.connect() as conn:
        biz_cols = [
            ("max_customers", "INTEGER DEFAULT 50"),
            ("google_review_url", "VARCHAR"),
            ("reward_text", "VARCHAR DEFAULT 'A 6-a e din partea casei!'"),
            ("card_color", "VARCHAR DEFAULT '#1e293b'"),
            ("staff_pin", "VARCHAR DEFAULT '1234'")
        ]
        for col, typ in biz_cols:
            try:
                conn.execute(text(f"ALTER TABLE business_accounts ADD COLUMN {col} {typ}"))
            except Exception:
                pass
        cust_cols = [
            ("uuid", "VARCHAR"),
            ("phone", "VARCHAR"),
            ("business_id", "INTEGER")
        ]
        for col, typ in cust_cols:
            try:
                conn.execute(text(f"ALTER TABLE customers ADD COLUMN {col} {typ}"))
            except Exception:
                pass
        conn.commit()

run_loial_migrations()

class QuickRegisterRequest(BaseModel):
    email: str
    password: str
    business_name: str
    reward: str = "A 6-a e din partea casei!"
    color: str = "#1e293b"
    ref_code: Optional[str] = ""


@app.post("/api/register")
def quick_register(req: QuickRegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(BusinessAccount).filter(BusinessAccount.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email deja înregistrat")

    clean_ref = sanitize_input(req.ref_code or "", 60)
    agent = db.query(SalesAgent).filter(SalesAgent.qr_code == clean_ref).first() if clean_ref else None

    business = BusinessAccount(
        name=req.business_name,
        email=req.email,
        password=pwd_context.hash(req.password),
        plan="free",
        max_customers=50,
        reward_text=req.reward,
        card_color=req.color,
        staff_pin=str(1000 + secrets.randbelow(9000)),
        agent_id=agent.id if agent else None,
        ref_code=clean_ref,
        created_at=datetime.now().isoformat()
    )

    db.add(business)
    db.commit()
    db.refresh(business)
    token = create_access_token({"sub": req.email, "role": "business", "business_id": business.id})
    return {"token": token, "business_id": business.id, "plan": "free"}

@app.get("/api/business-public/{business_id}")
def get_business_public(business_id: int, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    return {
        "name": biz.name,
        "google_review_url": biz.google_review_url,
        "reward_text": biz.reward_text or "Colectează ștampile și primești premii!",
        "card_color": biz.card_color or "#1e293b"
    }

@app.get("/join/{business_id}")
def join_qr_page(business_id: int):
    return FileResponse("join.html")

class QREnrollRequest(BaseModel):
    business_id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None

@app.post("/api/enroll")
def qr_enroll(req: QREnrollRequest, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == req.business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    count = db.query(Customer).filter(Customer.business_id == req.business_id).count()
    if biz.plan == "free" and count >= (biz.max_customers or 50):
        raise HTTPException(status_code=403, detail="LIMIT_REACHED")
    new_uuid = str(uuid.uuid4())[:8]
    customer = Customer(
        uuid=new_uuid,
        name=req.name,
        phone=req.phone,
        email=req.email,
        stamps=0,
        business_id=req.business_id,
        last_visit=datetime.now().isoformat()
    )
    db.add(customer)
    db.commit()
    return {"uuid": new_uuid, "name": customer.name}

@app.get("/scan/{business_id}")
def staff_scan_page(business_id: int):
    return FileResponse("scan.html")

class QRScanRequest(BaseModel):
    pin: str
    business_id: int
    customer_uuid: str
    idempotency_key: Optional[str] = None

@app.post("/api/scan")
@limiter.limit("30/minute")
def qr_scan_stamp(request: Request, req: QRScanRequest, db: Session = Depends(get_db)):
    """Compatibility endpoint; all stamp grants use the audited universal path."""
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == req.business_id).first()
    if not biz or not biz.staff_pin or biz.staff_pin == "1234" or req.pin != biz.staff_pin:
        raise HTTPException(status_code=401, detail="PIN principal invalid sau schimbarea lui este necesara")
    scanned = scan_universal_card(request, UniversalScanRequest(
        pin=req.pin,business_id=req.business_id,
        customer_uuid=req.customer_uuid,idempotency_key=req.idempotency_key),db)
    return {"stamps":scanned["stamps"],"name":scanned["name"],
            "business_id":req.business_id,
            "duplicate_ignored":scanned.get("duplicate_ignored",False)}

@app.get("/review/{business_id}")
def review_gate_page(business_id: int):
    return FileResponse("review.html")

class PublicFeedbackRequest(BaseModel):
    business_id: int
    rating: int
    message: str

@app.post("/api/private-feedback")
def save_public_review_feedback(req: PublicFeedbackRequest, db: Session = Depends(get_db)):
    fb = PublicReviewFeedback(
        business_id=req.business_id,
        rating=req.rating,
        message=req.message,
        created_at=datetime.now().isoformat()
    )
    db.add(fb)
    db.commit()
    return {"status": "saved"}

INDUSTRIES = {
    "cafenele": {"title": "Carduri de loialitate pentru cafenele", "reward": "A 6-a cafea e din partea casei!", "h1": "Fidelizează clienții cafenelei tale"},
    "restaurante": {"title": "Carduri de loialitate pentru restaurante", "reward": "A 10-a masă e gratuită!", "h1": "Clienți fideli pentru restaurantul tău"},
    "pizzerii": {"title": "Carduri de loialitate pentru pizzerii", "reward": "A 5-a pizza e gratuită!", "h1": "Pizzerie cu clienți recurenți"},
    "florarii": {"title": "Carduri de loialitate pentru florării", "reward": "10% reducere la următoarea comandă", "h1": "Clienți fideli pentru florăria ta"},
    "saloane": {"title": "Carduri de loialitate pentru saloane", "reward": "A 6-a vizită e gratuită!", "h1": "Salon cu programări recurente"},
    "frizerii": {"title": "Carduri de loialitate pentru frizerii", "reward": "A 5-a tunsoare e gratuită!", "h1": "Frizerie cu clienți fideli"},
    "spalatorii-auto": {"title": "Carduri de loialitate pentru spălătorii auto", "reward": "A 5-a spălare e gratuită!", "h1": "Clienți recurenți pentru spălătorie"},
    "service-auto": {"title": "Carduri de loialitate pentru service auto", "reward": "10% reducere la următoarea revizie", "h1": "Service auto cu clienți fideli"},
    "clinici-stomatologice": {"title": "Carduri de loialitate pentru clinici", "reward": "Consultație gratuită la a 5-a vizită", "h1": "Pacienți fideli pentru clinica ta"},
    "pet-shop": {"title": "Carduri de loialitate pentru pet shop", "reward": "A 5-a achiziție cu 20% reducere", "h1": "Clienți fideli pentru pet shop"}
}

@app.get("/solutii/{industrie}")
def industry_seo_page(industrie: str):
    if industrie not in INDUSTRIES:
        raise HTTPException(status_code=404, detail="Industrie negăsită")
    data = INDUSTRIES[industrie]
    html = f'''<!DOCTYPE html>
<html lang="ro"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{data["title"]} - Loial.space</title>
<meta name="description" content="{data["title"]}. Creează carduri digitale de fidelitate cu cod QR gratuit în 3 minute.">
<link href="https://googleapis.com" rel="stylesheet">
<style>
  body {{ font-family: 'Inter', system-ui, sans-serif; background: #f6f9f7; color: #111f18; margin: 0; line-height: 1.6; }}
  header {{ background: #ffffff; border-bottom: 1px solid #dce6e0; padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; }}
  .logo {{ display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 20px; color: #111f18; text-decoration: none; }}
  .logo-icon {{ width: 32px; height: 32px; background: linear-gradient(135deg, #2d6a4f, #52b788); color: #fff; border-radius: 8px; display: flex; align-items: center; justify-content: center; }}
  .container {{ max-width: 760px; margin: 60px auto; padding: 0 24px; }}
  .badge {{ display: inline-block; padding: 6px 14px; background: #e8f3ed; border: 1px solid #b7d7c5; color: #2d6a4f; border-radius: 20px; font-size: 12.5px; font-weight: 700; margin-bottom: 16px; }}
  h1 {{ font-size: 40px; line-height: 1.15; font-weight: 800; margin-bottom: 16px; color: #111f18; }}
  p {{ color: #475d52; font-size: 17px; margin-bottom: 24px; }}
  .offer-card {{ background: #ffffff; padding: 24px; border-radius: 18px; border: 1px solid #dce6e0; box-shadow: 0 10px 25px rgba(17, 31, 24, 0.05); margin: 28px 0; }}
  .offer-label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #475d52; font-weight: 700; }}
  .offer-value {{ font-size: 20px; font-weight: 800; color: #2d6a4f; margin-top: 6px; }}
  .btn {{ display: inline-block; padding: 16px 32px; background: linear-gradient(135deg, #2d6a4f, #40916c); color: #ffffff; text-decoration: none; border-radius: 12px; font-weight: 700; font-size: 16px; box-shadow: 0 6px 18px rgba(45, 106, 79, 0.25); }}
</style>
</head><body>
<header>
  <a href="/" class="logo"><div class="logo-icon">L</div> LOIAL</a>
  <a href="/" style="color:#2d6a4f;text-decoration:none;font-weight:600;font-size:14px;">← Înapoi la toate industriile</a>
</header>
<div class="container">
  <span class="badge">SOLUȚII DE LOIALITATE • LOIAL.SPACE</span>
  <h1>{data["h1"]}</h1>
  <p>Renunță la cartonașele de carton care se pierd. Oferă clienților tăi un card digital pe care îl salvează în telefon printr-o simplă scanare QR, fără aplicații de descărcat.</p>
  <div class="offer-card">
    <div class="offer-label">🎁 Exemplu ofertă recomandată pentru afacerea ta</div>
    <div class="offer-value">{data["reward"]}</div>
  </div>
  <a href="/register.html" class="btn">Creează-ți primul card gratuit →</a>
  <p style="font-size:13px;margin-top:12px;">Gratuit până la primii 50 de clienți • Fără card bancar</p>
</div>
</body></html>'''
    return HTMLResponse(content=html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# ==========================================
# SERVICE WORKER & REAL-TIME SYNC ROUTES
# ==========================================
@app.get("/sw.js")
def service_worker():
    return FileResponse("sw.js", media_type="application/javascript")

ACTIVE_PRESENCE = {}

@app.post("/api/presence/{business_id}/{customer_uuid}")
def ping_customer_presence(business_id: int, customer_uuid: str, db: Session = Depends(get_db)):
    cust = db.query(Customer).filter(Customer.uuid == customer_uuid, Customer.business_id == business_id).first()
    if cust:
        ACTIVE_PRESENCE[business_id] = {
            "name": cust.name,
            "uuid": cust.uuid,
            "stamps": cust.stamps or 0,
            "ts": datetime.now().timestamp()
        }
    return {"ok": True}

@app.get("/api/presence/{business_id}")
def check_business_presence(business_id: int):
    info = ACTIVE_PRESENCE.get(business_id)
    if info and (datetime.now().timestamp() - info["ts"]) < 25:
        return {"active": True, "customer": info}
    return {"active": False}

@app.get("/api/customer-status/{customer_uuid}")
def get_customer_status(
    customer_uuid: str,
    business_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    # business_id este opțional pentru compatibilitatea cu apelurile vechi.
    # Clientul poate avea un portofel universal cu mai multe carduri per afacere.
    if business_id is not None:
        cust = db.query(Customer).filter(
            Customer.business_id == business_id,
            (Customer.uuid == customer_uuid) | (Customer.wallet_uuid == customer_uuid),
        ).first()
        if cust:
            return {"stamps": cust.stamps or 0, "name": cust.name}
        existing = db.query(Customer).filter(
            (Customer.uuid == customer_uuid) | (Customer.wallet_uuid == customer_uuid)
        ).first()
        if existing:
            return {"stamps": 0, "name": existing.name}
        raise HTTPException(status_code=404, detail="Cardul nu a fost găsit")

    cust = db.query(Customer).filter(
        (Customer.uuid == customer_uuid) | (Customer.wallet_uuid == customer_uuid)
    ).first()
    if not cust:
        raise HTTPException(status_code=404, detail="Cardul nu a fost găsit")
    return {"stamps": cust.stamps or 0, "name": cust.name}

# ==========================================
# BUSINESS DASHBOARD ENDPOINTS
# ==========================================
class BusinessSettingsUpdate(BaseModel):
    google_review_url: Optional[str] = None
    staff_pin: Optional[str] = None
    reward_text: Optional[str] = None

@app.get("/api/my-business")
def get_my_business(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Neautentificat")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalid")
    
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == email).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    
    customers = db.query(Customer).filter(Customer.business_id == biz.id).order_by(Customer.id.desc()).all()
    feedbacks = db.query(PublicReviewFeedback).filter(PublicReviewFeedback.business_id == biz.id).order_by(PublicReviewFeedback.id.desc()).all()
    
    return {
        "id": biz.id,
        "name": biz.name,
        "email": biz.email,
        "plan": biz.plan or "free",
        "max_customers": biz.max_customers or 50,
        "reward_text": biz.reward_text,
        "card_color": biz.card_color,
        "staff_pin": biz.staff_pin or "",
        "google_review_url": biz.google_review_url or "",
        "customers_count": len(customers),
        "customers": [{"name": c.name, "stamps": c.stamps or 0, "last_visit": c.last_visit} for c in customers[:20]],
        "feedbacks": [{"rating": f.rating, "message": f.message, "date": f.created_at} for f in feedbacks[:10]]
    }

@app.post("/api/my-business/rotate-pin")
def rotate_business_staff_pin(credentials: HTTPAuthorizationCredentials = Depends(security),
                              db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401,detail="Autentificare obligatorie")
    try:
        claims=jwt.decode(credentials.credentials,SECRET_KEY,algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401,detail="Sesiune invalida")
    if claims.get("role")!="business":
        raise HTTPException(status_code=403,detail="Doar administratorul firmei poate schimba PIN-ul")
    biz=db.query(BusinessAccount).filter(
        BusinessAccount.email==claims.get("sub")).first()
    if not biz:
        raise HTTPException(status_code=403,detail="Firma nu a fost gasita")
    staff_pins={p.pin for p in db.query(StaffMember).filter(
        StaffMember.business_id==biz.id,StaffMember.active==1).all()}
    for _ in range(100):
        new_pin=str(1000+secrets.randbelow(9000))
        if new_pin not in staff_pins and new_pin!=biz.staff_pin and new_pin!="1234":
            biz.staff_pin=new_pin
            db.commit()
            return {"status":"rotated","staff_pin":new_pin,
                    "notice":"Comunica PIN-ul doar persoanelor autorizate. PIN-ul vechi nu mai functioneaza."}
    raise HTTPException(status_code=503,detail="Nu a putut fi generat un PIN disponibil")

@app.post("/api/my-business/settings")
def update_my_business_settings(req: BusinessSettingsUpdate, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Neautentificat")
    payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == payload.get("sub")).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    if req.google_review_url is not None:
        biz.google_review_url = req.google_review_url.strip()
    if req.staff_pin is not None:
        pin=req.staff_pin.strip()
        if not re.fullmatch(r"\d{4}",pin) or pin=="1234":
            raise HTTPException(status_code=422,detail="Alege un PIN diferit de 1234, format din 4 cifre")
        biz.staff_pin=pin
    if req.reward_text:
        biz.reward_text = req.reward_text.strip()
    db.commit()
    return {"status": "updated"}

# ==========================================
# STAFF MANAGEMENT, CUSTOM OFFERS & SERVER QR
# ==========================================
class StaffMember(Base):
    __tablename__ = "staff_members"
    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    name = Column(String)
    pin = Column(String)
    scans_count = Column(Integer, default=0)
    active = Column(Integer, default=1)
    created_at = Column(String)

Base.metadata.create_all(bind=engine)

def migrate_custom_offers():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE business_accounts ADD COLUMN stamps_required INTEGER DEFAULT 6"))
        except Exception:
            pass
        conn.commit()

migrate_custom_offers()

from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
from PIL import Image, ImageDraw, ImageFont

def _hex_to_rgb(hex_color: str) -> tuple:
    h = (hex_color or "#2d6a4f").lstrip("#")
    if len(h) != 6:
        return (45, 106, 79)
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return (45, 106, 79)

def create_premium_qr_bytes(data: str, color: str = "#2d6a4f", initial: str = "L") -> bytes:
    rgb = _hex_to_rgb(color)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=14,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    qr_img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(back_color=(255, 255, 255), front_color=rgb)
    ).convert("RGBA")

    w, h = qr_img.size
    badge_size = int(w * 0.24)
    badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.ellipse((0, 0, badge_size, badge_size), fill=(255, 255, 255, 255))

    margin = int(badge_size * 0.12)
    draw.ellipse((margin, margin, badge_size - margin, badge_size - margin), fill=rgb)

    letter = (initial or "L")[0].upper()
    font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((badge_size - tw) / 2, (badge_size - th) / 2 - 1), letter, fill=(255, 255, 255, 255), font=font)

    qr_img.paste(badge, ((w - badge_size) // 2, (h - badge_size) // 2), badge)

    buf = io.BytesIO()
    qr_img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

@app.get("/api/qr-image/{business_id}")
def get_business_qr_image(business_id: int, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    color = biz.card_color if (biz and biz.card_color) else "#2d6a4f"
    initial = biz.name if (biz and biz.name) else "L"
    join_url = "https://" + "loial.space" + "/join/" + str(business_id)
    png_bytes = create_premium_qr_bytes(join_url, color=color, initial=initial)
    b64 = base64.b64encode(png_bytes).decode()
    return {"qr_base64": f"data:image/png;base64,{b64}", "url": join_url}


class StaffCreateRequest(BaseModel):
    name: str
    pin: str

@app.get("/api/my-business/staff")
def list_staff(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Neautentificat")
    payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == payload.get("sub")).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    staff = db.query(StaffMember).filter(StaffMember.business_id == biz.id, StaffMember.active == 1).all()
    return [{"id": s.id, "name": s.name, "pin": s.pin, "scans_count": s.scans_count or 0} for s in staff]

@app.post("/api/my-business/staff")
def add_staff_member(req: StaffCreateRequest, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Neautentificat")
    payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == payload.get("sub")).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    if not re.fullmatch(r"\d{4}",req.pin) or req.pin=="1234" or req.pin==biz.staff_pin:
        raise HTTPException(status_code=422,detail="PIN de 4 cifre, diferit de 1234 si de PIN-ul administratorului")
    existing_pin = db.query(StaffMember).filter(StaffMember.business_id == biz.id, StaffMember.pin == req.pin, StaffMember.active == 1).first()
    if existing_pin:
        raise HTTPException(status_code=400, detail="Acest PIN este deja folosit de alt angajat")
    member = StaffMember(
        business_id=biz.id,
        name=sanitize_input(req.name, 60),
        pin=req.pin,
        scans_count=0,
        active=1,
        created_at=datetime.now().isoformat()
    )
    db.add(member)
    db.commit()
    return {"status": "added", "id": member.id}

@app.delete("/api/my-business/staff/{staff_id}")
def remove_staff_member(staff_id: int, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Neautentificat")
    payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == payload.get("sub")).first()
    member = db.query(StaffMember).filter(StaffMember.id == staff_id, StaffMember.business_id == biz.id).first()
    if member:
        member.active = 0
        db.commit()
    return {"status": "removed"}

class FullBusinessSettings(BaseModel):
    reward_text: Optional[str] = None
    stamps_required: Optional[int] = 6
    google_review_url: Optional[str] = None

@app.post("/api/my-business/offer")
def update_business_offer(req: FullBusinessSettings, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Neautentificat")
    payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    biz = db.query(BusinessAccount).filter(BusinessAccount.email == payload.get("sub")).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    if req.reward_text:
        biz.reward_text = req.reward_text.strip()
    if req.stamps_required and 2 <= req.stamps_required <= 20:
        biz.stamps_required = req.stamps_required
    if req.google_review_url is not None:
        biz.google_review_url = req.google_review_url.strip()
    db.commit()
    return {"status": "updated"}

@app.post("/api/scan-v2")
@limiter.limit("30/minute")
def qr_scan_with_staff(request: Request, req: QRScanRequest, db: Session = Depends(get_db)):
    """Compatibility endpoint with shared idempotency, reward and inbox handling."""
    scanned = scan_universal_card(request, UniversalScanRequest(
        pin=req.pin,business_id=req.business_id,
        customer_uuid=req.customer_uuid,idempotency_key=req.idempotency_key),db)
    return {**scanned, "business_id":req.business_id}

# Autorizare stricta pentru citirea/modificarea informatiilor private ale firmei.
def require_business_owner_or_admin(business_id: int, credentials, db: Session):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Autentificare obligatorie")
    try:
        claims = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Sesiune invalida")
    email = claims.get("sub")
    if not email:
        raise HTTPException(status_code=403, detail="Acces interzis")
    if claims.get("role") == "business":
        account = db.query(BusinessAccount).filter(BusinessAccount.id == business_id,
                          BusinessAccount.email == email).first()
        if account:
            return account
    elif claims.get("role") in ("admin", "owner"):
        operator = db.query(User).filter(User.email == email).first()
        if operator and operator.role in ("admin", "owner"):
            return operator
    raise HTTPException(status_code=403, detail="Nu ai acces la aceasta firma")

def require_platform_admin(credentials, db: Session):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Autentificare obligatorie")
    try:
        claims = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Sesiune invalida")
    admin = db.query(User).filter(User.email == claims.get("sub")).first()
    if not admin or admin.role not in ("admin", "owner") or claims.get("role") not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Doar administratorul platformei")
    return admin

@app.get("/api/loial-public/{business_id}")
def get_loial_public_business(business_id: int, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negasita")
    return {"name": biz.name, "reward_text": biz.reward_text or "Premiu fidelitate",
            "stamps_required": getattr(biz, "stamps_required", None) or 6,
            "card_color": biz.card_color or "#2d6a4f"}

# ==========================================
# DIRECT BUSINESS ID ROUTES (NO TOKEN ISSUES)
# ==========================================
@app.get("/api/biz-full/{business_id}")
def get_biz_full_data(business_id: int, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_business_owner_or_admin(business_id, credentials, db)
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    customers = db.query(Customer).filter(Customer.business_id == biz.id).order_by(Customer.id.desc()).all()
    staff = db.query(StaffMember).filter(StaffMember.business_id == biz.id, StaffMember.active == 1).all()
    
    color = biz.card_color or "#2d6a4f"
    initial = biz.name if biz.name else "L"
    join_url = "https://" + "loial.space" + "/join/" + str(biz.id)
    png_bytes = create_premium_qr_bytes(join_url, color=color, initial=initial)
    qr_b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    
    return {
        "id": biz.id,
        "name": biz.name,
        "email": biz.email,
        "plan": biz.plan or "free",
        "max_customers": biz.max_customers or 50,
        "reward_text": biz.reward_text or "Oferta ta aici",
        "stamps_required": getattr(biz, "stamps_required", None) or 6,
        "card_color": color,
        "google_review_url": biz.google_review_url or "",
        "qr_base64": qr_b64,
        "customers_count": len(customers),
        "customers": [{"name": c.name, "stamps": c.stamps or 0, "last_visit": c.last_visit} for c in customers[:20]],
        "staff": [{"id": s.id, "name": s.name, "pin": s.pin, "scans_count": s.scans_count or 0} for s in staff]
    }

@app.post("/api/biz-full/{business_id}/offer")
def save_biz_offer_direct(business_id: int, req: FullBusinessSettings, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_business_owner_or_admin(business_id, credentials, db)
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    if req.reward_text:
        biz.reward_text = req.reward_text.strip()
    if req.stamps_required and 1 <= req.stamps_required <= 200:
        biz.stamps_required = req.stamps_required
    if req.google_review_url is not None:
        biz.google_review_url = req.google_review_url.strip()
    db.commit()
    return {"status": "ok"}

@app.post("/api/biz-full/{business_id}/staff")
def add_biz_staff_direct(business_id: int, req: StaffCreateRequest, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_business_owner_or_admin(business_id, credentials, db)
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    if not re.fullmatch(r"\d{4}",req.pin) or req.pin=="1234" or req.pin==biz.staff_pin:
        raise HTTPException(status_code=422,detail="PIN de 4 cifre, diferit de 1234 si de PIN-ul administratorului")
    existing = db.query(StaffMember).filter(StaffMember.business_id == business_id, StaffMember.pin == req.pin, StaffMember.active == 1).first()
    if existing:
        raise HTTPException(status_code=400, detail="Acest PIN este deja folosit de alt angajat")
    member = StaffMember(
        business_id=business_id,
        name=sanitize_input(req.name, 60),
        pin=req.pin,
        scans_count=0,
        active=1,
        created_at=datetime.now().isoformat()
    )
    db.add(member)
    db.commit()
    return {"status": "added"}

@app.delete("/api/biz-full/{business_id}/staff/{staff_id}")
def delete_biz_staff_direct(business_id: int, staff_id: int, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_business_owner_or_admin(business_id, credentials, db)
    member = db.query(StaffMember).filter(StaffMember.id == staff_id, StaffMember.business_id == business_id).first()
    if member:
        member.active = 0
        db.commit()
    return {"status": "deleted"}

# ==========================================
# INSTANT CLIENT CARD & QR PNG ENDPOINTS
# ==========================================
@app.get("/manifest.json")
def get_manifest():
    return FileResponse("manifest.json", media_type="application/manifest+json")

@app.get("/api/qr-raw/{code_text}")
def generate_raw_qr_png(code_text: str, color: str = "#2d6a4f", initial: str = "L"):
    png_bytes = create_premium_qr_bytes(code_text, color=color, initial=initial)
    return Response(content=png_bytes, media_type="image/png")
    
class RedeemRequest(BaseModel):
    pin: str
    business_id: int
    customer_uuid: str

@app.post("/api/redeem-reward")
@limiter.limit("10/minute")
def redeem_customer_reward(request: Request, req: RedeemRequest, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == req.business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    staff = db.query(StaffMember).filter(StaffMember.business_id == biz.id, StaffMember.pin == req.pin, StaffMember.active == 1).first()
    if not staff and (not biz.staff_pin or biz.staff_pin=="1234" or req.pin != biz.staff_pin):
        raise HTTPException(status_code=401, detail="PIN incorect")
    customer = db.query(Customer).filter(
        Customer.business_id == biz.id,
        (Customer.uuid == req.customer_uuid) | (Customer.wallet_uuid == req.customer_uuid)
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cardul clientului nu există la această afacere")
    target = getattr(biz, "stamps_required", None) or 6
    if (customer.stamps or 0) < target:
        raise HTTPException(status_code=409, detail="Recompensa nu este inca disponibila")
    customer.stamps = 0
    customer.last_visit = datetime.now().isoformat()
    from loial_inbox import queue_service_event
    from loial_scans import record_award
    redeem_key=uuid.uuid4().hex
    record_award(db,biz.id,customer.id,"redeem:"+redeem_key,"redeem",0)
    queue_service_event(db, biz, customer, kind="redeem", event_key=redeem_key)
    from loial_wallet_sync import queue_google_refresh
    queue_google_refresh(db,biz.id,customer.wallet_uuid or customer.uuid)
    from loial_apple_updates import mark_customer_pass_changed
    mark_customer_pass_changed(db,biz.id,customer.wallet_uuid or customer.uuid)
    db.commit()
    return {"status": "redeemed", "name": customer.name, "stamps": 0}
class InstantEnrollRequest(BaseModel):
    business_id: int
    name: str
    uuid: str
    email: Optional[str] = None
    consent_marketing_email: bool = False
    consent_personalized_ads: bool = False
    consent_loial_offers: bool = False
    wallet_claim_token: Optional[str] = None

@app.post("/api/enroll-sync")
def enroll_customer_sync(req: InstantEnrollRequest, db: Session = Depends(get_db)):
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == req.business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")

    email_clean = sanitize_input(req.email or "", 160).lower()
    if email_clean and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email_clean):
        raise HTTPException(status_code=422, detail="Adresa de email nu este valida")
    if (req.consent_marketing_email or req.consent_personalized_ads) and not email_clean:
        raise HTTPException(status_code=422, detail="Pentru comunicari este necesara o adresa de email")
    wallet_id = req.uuid.strip()
    if not wallet_id:
        raise HTTPException(status_code=400, detail="Codul portofelului lipsește")

    existing = db.query(Customer).filter(
        (Customer.uuid == wallet_id) | (Customer.wallet_uuid == wallet_id)
    ).first()
    card_at_business = db.query(Customer).filter(
        Customer.business_id == req.business_id,
        (Customer.uuid == wallet_id) | (Customer.wallet_uuid == wallet_id),
    ).first()
    if card_at_business:
        from loial_inbox import issue_wallet_access
        try:
            verified_token = issue_wallet_access(db, wallet_id, False, req.wallet_claim_token)
        except ValueError as exc:
            raise HTTPException(status_code=422,detail=str(exc))
        return {"status": "exists", "inbox_access": verified_token}

    if existing:
        # Un portofel universal, mai multe carduri cu progres independent.
        customer = Customer(
            uuid=str(uuid.uuid4()),
            wallet_uuid=existing.wallet_uuid or existing.uuid,
            name=existing.name,
            email=email_clean or None,
            phone=existing.phone,
            stamps=0,
            business_id=req.business_id,
            last_visit=datetime.now().isoformat()
        )
    else:
        customer = Customer(
            uuid=wallet_id,
            wallet_uuid=wallet_id,
            name=sanitize_input(req.name, 80),
            email=email_clean or None,
            stamps=0,
            business_id=req.business_id,
            last_visit=datetime.now().isoformat()
        )
    db.add(customer)
    db.flush()
    consent_time = datetime.now().isoformat()
    if req.consent_marketing_email:
        db.add(Consent(customer_id=customer.id, purpose="marketing_email",
                       granted=1, date=consent_time, ip="join_form"))
    if req.consent_personalized_ads:
        db.add(Consent(customer_id=customer.id, purpose="personalized_ads",
                       granted=1, date=consent_time, ip="join_form"))
    from loial_inbox import issue_wallet_access, record_offer_choice, queue_service_event
    try:
        inbox_token = issue_wallet_access(db, wallet_id, is_new_wallet=(existing is None),
                                         proposed_token=req.wallet_claim_token)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422,detail=str(exc))
    if req.consent_loial_offers:
        record_offer_choice(db, Consent, customer.id, True, "join_form")
    queue_service_event(db, biz, customer, kind="welcome")
    db.commit()
    return {"status": "saved", "inbox_access": inbox_token}
class ChangePasswordRequest(BaseModel):
    email: str
    old_password: str
    new_password: str

@app.post("/api/change-password")
def change_any_password(req: ChangePasswordRequest, db: Session = Depends(get_db)):
    email = sanitize_input(req.email, 100)
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Parola nouă trebuie să aibă minim 6 caractere")
    new_hash = pwd_context.hash(req.new_password)
    updated = False
    for model in [User, BusinessAccount, SalesAgent]:
        acc = db.query(model).filter(model.email == email).first()
        if acc and pwd_context.verify(req.old_password, acc.password):
            acc.password = new_hash
            updated = True
    if not updated:
        raise HTTPException(status_code=401, detail="Email sau parolă actuală incorectă")
    db.commit()
    return {"status": "password_updated", "message": "Parola a fost schimbată cu succes!"}

from sqlalchemy import text
from sales import get_ambassador_tier

def _ensure_ecosystem_columns():
    alter_statements = [
        "ALTER TABLE customers ADD COLUMN wallet_uuid TEXT",
        "ALTER TABLE customers ADD COLUMN phone TEXT",
        "ALTER TABLE customers ADD COLUMN network_bonus_text TEXT",
        "ALTER TABLE business_accounts ADD COLUMN ref_code TEXT",
        "ALTER TABLE business_accounts ADD COLUMN stamps_required INTEGER DEFAULT 6",
        "ALTER TABLE sales_agents ADD COLUMN rank TEXT DEFAULT 'Ambasador'",
        "ALTER TABLE sales ADD COLUMN business_id INTEGER",
        "ALTER TABLE sales ADD COLUMN activated_month TEXT",
    ]
    with engine.begin() as conn:
        for stmt in alter_statements:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass

_ensure_ecosystem_columns()
Customer.wallet_uuid = Column(String, nullable=True)
Customer.network_bonus_text = Column(String, nullable=True)
BusinessAccount.ref_code = Column(String, nullable=True)
BusinessAccount.stamps_required = Column(Integer, default=6)

class NetworkRule(Base):
    __tablename__ = "network_rules"
    id = Column(Integer, primary_key=True, index=True)
    min_businesses = Column(Integer, default=10)
    min_visits_per_business = Column(Integer, default=3)
    bonus_title = Column(String, default="Bonus VIP Rețeaua Loial")
    bonus_message = Column(String, default="Felicitări! Ai vizitat peste 10 afaceri partenere Loial. Ai câștigat un voucher cadou!")
    auto_enabled = Column(Integer, default=1)

Base.metadata.create_all(bind=engine)


class UniversalScanRequest(BaseModel):
    pin: str
    business_id: int
    customer_uuid: str
    idempotency_key: Optional[str] = None


@app.post("/api/scan-universal")
@limiter.limit("30/minute")
def scan_universal_card(request: Request, req: UniversalScanRequest, db: Session = Depends(get_db)):
    if req.pin=="1234":
        raise HTTPException(status_code=401,detail="PIN vechi nesigur. Schimba-l din panoul firmei.")
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == req.business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")

    staff = db.query(StaffMember).filter(
        StaffMember.business_id == biz.id,
        StaffMember.pin == req.pin,
        StaffMember.active == 1
    ).first()
    if not staff and (not biz.staff_pin or biz.staff_pin=="1234" or req.pin!=biz.staff_pin):
        raise HTTPException(status_code=401, detail="PIN angajat incorect")

    code = req.customer_uuid.strip()
    customer = db.query(Customer).filter(
        Customer.business_id == biz.id,
        (Customer.uuid == code) | (Customer.wallet_uuid == code)
    ).first()

    if not customer:
        existing_profile = db.query(Customer).filter(
            (Customer.uuid == code) | (Customer.wallet_uuid == code)
        ).first()
        if not existing_profile:
            raise HTTPException(status_code=404, detail="Cardul nu a fost găsit")

        wallet_id = existing_profile.wallet_uuid or existing_profile.uuid
        customer = Customer(
            uuid=str(uuid.uuid4()),  # Identificator UNIC per card de afacere
            wallet_uuid=wallet_id,   # Același portofel pentru toate afacerile
            name=existing_profile.name,
            email=existing_profile.email,
            phone=existing_profile.phone,
            business_id=biz.id,
            stamps=0,
            last_visit=datetime.now().isoformat()
        )
        db.add(customer)
        db.flush()

    target = getattr(biz, "stamps_required", None) or 6
    from loial_scans import existing_operation, recent_duplicate, record_award
    operation = req.idempotency_key or uuid.uuid4().hex
    if len(operation)<8 or len(operation)>120:
        raise HTTPException(status_code=422,detail="Identificatorul scanarii nu este valid")
    prior = existing_operation(db,biz.id,operation)
    if prior:
        if prior.customer_id!=customer.id:
            raise HTTPException(status_code=409,detail="Aceasta operatiune apartine altui card")
        return {"name":customer.name,"stamps":prior.stamps_after,
                "target":target,"staff_name":staff.name if staff else "Administrator",
                "reward_unlocked":prior.stamps_after>=target,
                "duplicate_ignored":True}
    if recent_duplicate(db,biz.id,customer.id):
        raise HTTPException(status_code=409,
            detail="Acest card a fost scanat recent. Verifica daca e o cumparatura noua.")
    if (customer.stamps or 0)>=target:
        raise HTTPException(status_code=409,
            detail="Recompensa este deja disponibila; acord-o inaintea unei noi stampile.")
    previous_visit = customer.last_visit
    customer.stamps = (customer.stamps or 0) + 1
    customer.last_visit = datetime.now().isoformat()
    if staff:
        staff.scans_count = (staff.scans_count or 0) + 1

    # Verificăm regula automată de bonus de rețea
    wallet_id = customer.wallet_uuid or customer.uuid
    all_cards = db.query(Customer).filter(
        (Customer.wallet_uuid == wallet_id) | (Customer.uuid == wallet_id)
    ).all()
    rule = db.query(NetworkRule).first()
    if rule and rule.auto_enabled:
        qualified_biz = [c for c in all_cards if (c.stamps or 0) >= rule.min_visits_per_business]
        if len(qualified_biz) >= rule.min_businesses and not customer.network_bonus_text:
            for c in all_cards:
                c.network_bonus_text = f"{rule.bonus_title}: {rule.bonus_message}"

    from loial_inbox import queue_service_event
    was_away = False
    if previous_visit:
        try:
            was_away = (datetime.now() - datetime.fromisoformat(previous_visit)).days >= 30
        except (ValueError, TypeError):
            pass
    queue_service_event(db, biz, customer, kind="stamp", returning=was_away,
                        event_key=operation)
    record_award(db,biz.id,customer.id,operation,"manual",customer.stamps)
    from loial_wallet_sync import queue_google_refresh
    queue_google_refresh(db,biz.id,customer.wallet_uuid or customer.uuid)
    from loial_apple_updates import mark_customer_pass_changed
    mark_customer_pass_changed(db,biz.id,customer.wallet_uuid or customer.uuid)
    db.commit()
    return {
        "name": customer.name,
        "stamps": customer.stamps,
        "target": target,
        "staff_name": staff.name if staff else "Administrator",
        "reward_unlocked": customer.stamps >= target
    }


@app.get("/api/wallet-profile/{wallet_uuid}")
def get_universal_wallet_profile(wallet_uuid: str, request: Request, db: Session = Depends(get_db)):
    # QR-ul vizibil angajatului identifica doar cardul pentru scanare.
    # Profilul, afacerile vizitate si stampilele sunt private titularului.
    from loial_inbox import WalletInboxAccess, access_hash
    private_token=(request.headers.get("X-Loial-Wallet-Token") or "").strip()
    if len(wallet_uuid)>120 or len(private_token)<40 or len(private_token)>180:
        raise HTTPException(status_code=401,detail="Verificarea portofelului este necesara")
    verified=db.query(WalletInboxAccess).filter(
        WalletInboxAccess.wallet_uuid==wallet_uuid,
        WalletInboxAccess.token_hash==access_hash(private_token)).first()
    if not verified:
        raise HTTPException(status_code=401,detail="Acces privat invalid sau neactivat")
    cards = db.query(Customer).filter(
        (Customer.wallet_uuid == wallet_uuid) | (Customer.uuid == wallet_uuid)
    ).all()
    if not cards:
        raise HTTPException(status_code=404, detail="Portofel negăsit")

    primary = cards[0]
    card_items = []
    bonus_text = None
    for c in cards:
        if c.network_bonus_text:
            bonus_text = c.network_bonus_text
        biz = db.query(BusinessAccount).filter(BusinessAccount.id == c.business_id).first()
        if biz:
            target = getattr(biz, "stamps_required", None) or 6
            card_items.append({
                "business_id": biz.id,
                "business_name": biz.name,
                "reward_text": biz.reward_text or "Premiu fidelitate",
                "card_color": biz.card_color or "#2d6a4f",
                "stamps": c.stamps or 0,
                "target": target,
                "unlocked": (c.stamps or 0) >= target
            })

    # Datele ambasadorului sunt disponibile numai dupa autentificare;
    # simpla posesie a QR-ului universal nu dovedeste identitatea titularului.
    ambassador_data = None

    return {
        "wallet_uuid": primary.wallet_uuid or primary.uuid,
        "name": primary.name,
        # Emailul si telefonul nu se expun prin simpla posesie a QR-ului.
        "businesses_count": len(card_items),
        "total_stamps": sum(item["stamps"] for item in card_items),
        "cards": card_items,
        "network_bonus": bonus_text,
        "ambassador": ambassador_data
    }


class AmbassadorEnrollRequest(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    password: str
    payout_method: str = "wise"
    payout_details: str = ""


@app.post("/api/ambassador/join")
def enroll_ambassador(req: AmbassadorEnrollRequest, db: Session = Depends(get_db)):
    email = sanitize_input(req.email, 100).lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email obligatoriu pentru contul de Ambasador")
    if len(req.password) < 10:
        raise HTTPException(status_code=422, detail="Parola necesita minimum 10 caractere")
    agent = db.query(SalesAgent).filter(SalesAgent.email == email).first()
    if agent:
        raise HTTPException(status_code=409, detail="Acest email are deja un cont de ambasador. Foloseste autentificarea contului.")
    if not agent:
        ref_code = f"LOIAL-{uuid.uuid4().hex[:6].upper()}"
        agent = SalesAgent(
            name=sanitize_input(req.name, 100) or "Ambasador Loial",
            email=email,
            phone=sanitize_input(req.phone or "", 40),
            password=pwd_context.hash(req.password),
            role="ambassador",
            rank="Ambasador",
            qr_code=ref_code,
            status="active",
            active=True,
            payout_method=req.payout_method,
            payout_details=sanitize_input(req.payout_details, 150),
            created_at=datetime.now().isoformat()
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
    qr_info = generate_agent_qr(agent.id, agent.name, agent.qr_code)
    sales_list = db.query(Sale).filter(Sale.agent_id == agent.id, Sale.status == "completed").all()
    tier = get_ambassador_tier(len(sales_list))
    return {
        "id": agent.id,
        "name": agent.name,
        "email": agent.email,
        "ref_code": agent.qr_code,
        "referral_url": qr_info["referral_url"],
        "qr_image": qr_info["qr_image"],
        "rank": tier["rank"],
        "active_businesses": len(sales_list),
        "monthly_rate": tier["monthly_rate"],
        "message": "Contul a fost creat. Pastreaza parola in siguranta."
    }


@app.get("/api/admin/overview")
def admin_super_overview(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_platform_admin(credentials, db)
    current_month = datetime.now().strftime("%Y-%m")
    ambassador_stats = calculate_commissions(db, Sale, Commission, SalesAgent, current_month)

    businesses = db.query(BusinessAccount).order_by(BusinessAccount.id.desc()).all()
    biz_list = []
    for b in businesses:
        c_count = db.query(Customer).filter(Customer.business_id == b.id).count()
        agent = db.query(SalesAgent).filter(SalesAgent.id == b.agent_id).first() if b.agent_id else None
        biz_list.append({
            "id": b.id,
            "name": b.name,
            "email": b.email,
            "plan": b.plan or "free",
            "customers_count": c_count,
            "ref_code": getattr(b, "ref_code", "") or "",
            "ambassador_name": agent.name if agent else "Direct",
            "created_at": (b.created_at or "")[:10]
        })

    # Top clienți din rețeaua Loial
    all_cust = db.query(Customer).all()
    grouped = {}
    for c in all_cust:
        wid = c.wallet_uuid or c.uuid or f"id-{c.id}"
        if wid not in grouped:
            grouped[wid] = {
                "wallet_uuid": wid,
                "name": c.name,
                "email": c.email or "",
                "businesses": set(),
                "total_stamps": 0,
                "bonus": c.network_bonus_text or ""
            }
        if c.business_id:
            grouped[wid]["businesses"].add(c.business_id)
        grouped[wid]["total_stamps"] += (c.stamps or 0)
        if c.network_bonus_text:
            grouped[wid]["bonus"] = c.network_bonus_text


    top_customers = sorted(
        [
            {
                "wallet_uuid": v["wallet_uuid"],
                "name": v["name"],
                "email": v["email"],
                "businesses_count": len(v["businesses"]),
                "total_stamps": v["total_stamps"],
                "bonus": v["bonus"]
            }
            for v in grouped.values()
        ],
        key=lambda x: (x["businesses_count"], x["total_stamps"]),
        reverse=True
    )[:30]

    rule = db.query(NetworkRule).first()
    if not rule:
        rule = NetworkRule()
        db.add(rule)
        db.commit()
        db.refresh(rule)

    return {
        "month": current_month,
        "businesses": biz_list,
        "ambassadors": ambassador_stats,
        "top_customers": top_customers,
        "network_rule": {
            "min_businesses": rule.min_businesses,
            "min_visits_per_business": rule.min_visits_per_business,
            "bonus_title": rule.bonus_title,
            "bonus_message": rule.bonus_message,
            "auto_enabled": bool(rule.auto_enabled)
        }
    }


@app.post("/api/admin/business/{biz_id}/toggle-pro")
def admin_toggle_business_pro(biz_id: int, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_platform_admin(credentials, db)
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == biz_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")

    current_month = datetime.now().strftime("%Y-%m")
    if biz.plan == "probusiness":
        biz.plan = "free"
        biz.max_customers = 50
        sale = db.query(Sale).filter(Sale.business_id == biz.id).first()
        if sale:
            sale.status = "cancelled"
    else:
        biz.plan = "probusiness"
        biz.max_customers = 999999
        if biz.agent_id:
            sale = db.query(Sale).filter(Sale.business_id == biz.id).first()
            if not sale:
                db.add(Sale(
                    agent_id=biz.agent_id,
                    business_id=biz.id,
                    business_name=biz.name,
                    business_email=biz.email,
                    plan="probusiness",
                    amount=65.0,
                    commission=20.0,
                    status="completed",
                    activated_month=current_month,
                    completed_at=datetime.now().isoformat(),
                    month=current_month
                ))
            else:
                sale.status = "completed"
                if not sale.activated_month:
                    sale.activated_month = current_month

    db.commit()
    return {"status": "updated", "plan": biz.plan}


class NetworkBonusManualRequest(BaseModel):
    wallet_uuid: str
    bonus_text: str


@app.post("/api/admin/network-bonus/manual")
def admin_send_manual_bonus(req: NetworkBonusManualRequest, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_platform_admin(credentials, db)
    cards = db.query(Customer).filter(
        (Customer.wallet_uuid == req.wallet_uuid) | (Customer.uuid == req.wallet_uuid)
    ).all()
    if not cards:
        raise HTTPException(status_code=404, detail="Client negăsit")
    for c in cards:
        c.network_bonus_text = sanitize_input(req.bonus_text, 250)
    db.commit()
    return {"status": "sent"}


class NetworkRuleUpdateRequest(BaseModel):
    min_businesses: int
    min_visits_per_business: int
    bonus_title: str
    bonus_message: str
    auto_enabled: bool


@app.post("/api/admin/network-rule")
def admin_update_network_rule(req: NetworkRuleUpdateRequest, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_platform_admin(credentials, db)
    rule = db.query(NetworkRule).first()
    if not rule:
        rule = NetworkRule()
        db.add(rule)
    rule.min_businesses = max(1, req.min_businesses)
    rule.min_visits_per_business = max(1, req.min_visits_per_business)
    rule.bonus_title = sanitize_input(req.bonus_title, 100)
    rule.bonus_message = sanitize_input(req.bonus_message, 250)
    rule.auto_enabled = 1 if req.auto_enabled else 0
    db.commit()
    return {"status": "updated"}
@app.get("/ambasador.html")
@app.get("/ambasador")
def serve_ambasador_page():
    return FileResponse("ambasador.html")
@app.delete("/api/admin/business/{biz_id}")
def admin_delete_business(biz_id: int, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_platform_admin(credentials, db)
    biz = db.query(BusinessAccount).filter(BusinessAccount.id == biz_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Afacere negăsită")
    db.query(StaffMember).filter(StaffMember.business_id == biz_id).delete()
    db.query(Customer).filter(Customer.business_id == biz_id).delete()
    db.query(Sale).filter(Sale.business_id == biz_id).delete()
    db.delete(biz)
    db.commit()
    return {"status": "deleted"}


@app.delete("/api/admin/ambassador/{agent_id}")
def admin_delete_ambassador(agent_id: int, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_platform_admin(credentials, db)
    agent = db.query(SalesAgent).filter(SalesAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Ambasador negăsit")
    db.query(BusinessAccount).filter(BusinessAccount.agent_id == agent_id).update({"agent_id": None, "ref_code": ""})
    db.query(Sale).filter(Sale.agent_id == agent_id).delete()
    db.query(Commission).filter(Commission.agent_id == agent_id).delete()
    db.delete(agent)
    db.commit()
    return {"status": "deleted"}

@app.delete("/api/admin/customer/{wallet_uuid}")
def admin_delete_customer(wallet_uuid: str, credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    require_platform_admin(credentials, db)
    db.query(Customer).filter(
        (Customer.wallet_uuid == wallet_uuid) | (Customer.uuid == wallet_uuid)
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "deleted"}

@app.get("/api/qr-link")
def generate_qr_from_query(url: str, color: str = "#2d6a4f", initial: str = "L"):
    png_bytes = create_premium_qr_bytes(url, color=color, initial=initial)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


# Loial AI Business - module independent from existing QR and loyalty routes.
from loial_business_ai import install_loial_ai
install_loial_ai(app, engine, SessionLocal, BusinessAccount, Customer, Consent, SECRET_KEY, ALGORITHM)

# Mesagerie Loial in-app, fara email, SMS sau servicii externe.
from loial_business_ai import AISale
from loial_inbox import install_loial_inbox
install_loial_inbox(app, engine, SessionLocal, BusinessAccount, Customer, Consent,
                    AISale, SECRET_KEY, ALGORITHM)

# Roluri independente: administratorul firmei poate fi si ambasador si client Loial.
from loial_inbox import WalletInboxAccess, access_hash
from loial_identity import install_loial_identity, BusinessAmbassadorLink
from loial_premium_wallet import install_premium_wallet
install_loial_identity(app, engine, SessionLocal, BusinessAccount, SalesAgent,
                       Sale, pwd_context, SECRET_KEY, ALGORITHM, WalletInboxAccess,
                       access_hash, get_ambassador_tier)
install_premium_wallet(app, engine, SessionLocal, BusinessAccount, Customer,
                       SalesAgent, Sale, SECRET_KEY, ALGORITHM,
                       get_ambassador_tier, BusinessAmbassadorLink)

# Serviciul standard Apple PassKit permite re-descarcarea cardurilor modificate.
from loial_premium_wallet import premium_card, signed_apple_pkpass, apple_pass_json
from loial_apple_updates import install_apple_pass_updates
install_apple_pass_updates(app, engine, SessionLocal, BusinessAccount, Customer,
                           SalesAgent, Sale, apple_pass_json, signed_apple_pkpass,
                           premium_card, get_ambassador_tier)


# Bon QR unic, verificare la nivel de tranzactie si asociere cu cumparaturile clientului.
from loial_business_ai import AIDocument
from loial_scans import ScanBase
ScanBase.metadata.create_all(bind=engine)
from loial_receipts import install_receipts
install_receipts(app, engine, SessionLocal, BusinessAccount, Customer,
                 AIDocument, AISale, SECRET_KEY, ALGORITHM)

@app.get("/api/loial-scans/history")
def business_stamp_audit(limit: int = 40, credentials: HTTPAuthorizationCredentials = Depends(security),
                         db: Session = Depends(get_db)):
    """Owner-only loyalty ledger: manual scans, receipts, rewards and reversals."""
    if not credentials:
        raise HTTPException(status_code=401,detail="Autentificare obligatorie")
    try:
        claims=jwt.decode(credentials.credentials,SECRET_KEY,algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401,detail="Sesiune invalida")
    if claims.get("role")!="business":
        raise HTTPException(status_code=403,detail="Doar administratorul firmei")
    biz=db.query(BusinessAccount).filter(BusinessAccount.email==claims.get("sub")).first()
    if not biz or (claims.get("business_id") and biz.id!=claims.get("business_id")):
        raise HTTPException(status_code=403,detail="Firma nu este disponibila")
    from loial_scans import StampAward
    safe_limit=max(1,min(int(limit),100))
    entries=db.query(StampAward).filter(
        StampAward.business_id==biz.id).order_by(StampAward.id.desc()).limit(safe_limit).all()
    customer_ids={x.customer_id for x in entries}
    customers=db.query(Customer).filter(
        Customer.business_id==biz.id,Customer.id.in_(customer_ids)).all() if customer_ids else []
    names={x.id:x.name for x in customers}
    return {"business_id":biz.id,"items":[{
        "id":x.id,"source":x.source,"customer_id":x.customer_id,
        "customer":names.get(x.customer_id,"Client indisponibil"),
        "stamps_after":x.stamps_after,"at":x.created_at
    } for x in entries],"limit":safe_limit}

@app.get("/loial-receipt.html")
def loial_receipt_page():
    return FileResponse("loial-receipt.html")



@app.get("/loial-ai.html")
@app.get("/loial-ai")
def loial_ai_page():
    return FileResponse("loial-ai.html")
