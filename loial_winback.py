"""Win-back insights from verified stamp records, isolated per business.

No messaging, no external AI requests, and no inferred transaction revenue.
A confirmed stamp is a visit; a new wallet enrollment is not a visit.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

WinbackBase = declarative_base()

class WinbackSettings(WinbackBase):
    __tablename__ = "loial_winback_settings"
    business_id = Column(Integer, primary_key=True)
    default_return_days = Column(Integer, nullable=False, default=30)
    average_ticket_minor = Column(Integer, nullable=False, default=0)
    estimated_margin_percent = Column(Integer, nullable=False, default=35)
    currency = Column(String(3), nullable=False, default="RON")

class SettingsInput(BaseModel):
    default_return_days: int = Field(ge=3, le=365)
    average_ticket_minor: int = Field(ge=0, le=100_000_000)
    estimated_margin_percent: int = Field(ge=0, le=100)
    currency: str = Field(default="RON", pattern="^(RON|EUR|USD|GBP)$")

def parse_visit_date(value):
    try:
        if isinstance(value, datetime):
            return value.date()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError, TypeError):
        return None

def summarize_inactive(award_rows, customer_ids, threshold=30, ticket_minor=0,
                       margin_percent=35, as_of=None):
    """Only verified stamps count; repeat grants on the same day count once."""
    if type(threshold) is not int or not 3 <= threshold <= 365:
        raise ValueError("Invalid return cycle threshold")
    as_of = as_of or datetime.now(timezone.utc).date()
    histories = defaultdict(set)
    eligible = set(customer_ids)
    for row in award_rows:
        cid = row.customer_id
        if cid not in eligible:
            continue
        day = parse_visit_date(row.created_at)
        if day and day <= as_of:
            histories[cid].add(day)
    at_risk = 0
    history_count = 0
    examples = []
    for customer_id, days in histories.items():
        ordered = sorted(days)
        personal = len(ordered) >= 3
        if personal:
            intervals = [(b-a).days for a, b in zip(ordered, ordered[1:])]
            expected = max(3, min(365, round(mean(intervals) * 1.3)))
            history_count += 1
        else:
            expected = threshold
        absence = (as_of - ordered[-1]).days
        if absence > expected:
            at_risk += 1
            examples.append({"days_absent": absence, "expected_cycle_days": expected})
    # This is a scenario only, NOT reported sales or attributable revenue.
    hypothetical_minor = round(at_risk * 0.25 * ticket_minor)
    return {
        "confirmed_visit_customers": len(histories),
        "with_personal_cycle": history_count,
        "at_risk_customers": at_risk,
        "default_return_days": threshold,
        "hypothetical_return_rate": 0.25,
        "potential_return_revenue_minor": hypothetical_minor,
        "potential_contribution_minor": round(hypothetical_minor * margin_percent / 100),
        "forecast_only": True,
        "customer_identifiers_exposed": False,
        "methodology": "Verified stamps grouped into distinct calendar days; 3+ visit days use mean interval × 1.3, otherwise merchant threshold. No messages sent; estimates are scenarios.",
    }

def install_winback(app, engine, get_db, BusinessAccount, Customer, StampAward,
                    merchant_auth, security):
    WinbackBase.metadata.create_all(bind=engine)
    router = APIRouter(prefix="/api/loial-winback", tags=["winback"])

    def authenticated_merchant(credentials=Depends(security), db=Depends(get_db)):
        return merchant_auth(credentials, db)

    @router.get("/settings")
    def settings(business=Depends(authenticated_merchant), db=Depends(get_db)):
        row = db.get(WinbackSettings, business.id)
        return {
            "default_return_days": row.default_return_days if row else 30,
            "average_ticket_minor": row.average_ticket_minor if row else 0,
            "estimated_margin_percent": row.estimated_margin_percent if row else 35,
            "currency": row.currency if row else "RON",
            "assumptions_only": True,
        }

    @router.put("/settings")
    def update_settings(payload: SettingsInput, business=Depends(authenticated_merchant),
                        db=Depends(get_db)):
        row = db.get(WinbackSettings, business.id)
        if row is None:
            row = WinbackSettings(business_id=business.id)
            db.add(row)
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        db.commit()
        return {"status": "updated", "business_id": business.id}

    @router.get("/insights")
    def insights(business=Depends(authenticated_merchant), db=Depends(get_db)):
        row = db.get(WinbackSettings, business.id)
        threshold = row.default_return_days if row else 30
        ticket_minor = row.average_ticket_minor if row else 0
        margin = row.estimated_margin_percent if row else 35
        currency = row.currency if row else "RON"
        ids = [r[0] for r in db.query(Customer.id).filter(
            Customer.business_id == business.id).all()]
        # Select only this merchant's audited stamps, never another firm's data.
        awards = db.query(StampAward).filter(
            StampAward.business_id == business.id).all()
        result = summarize_inactive(awards, ids, threshold, ticket_minor, margin)
        result["currency"] = currency
        result["message_dispatch_enabled"] = False
        result["needs_marketing_consent_before_campaign"] = True
        return result

    app.include_router(router)
