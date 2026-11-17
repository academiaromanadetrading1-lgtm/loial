"""
Loial Ambassador & Partner System
- Universal QR & referral link onboarding
- Exact tiered recurring commission tracking:
  * Month 1 (new paid ProBusiness): 20 EUR activation bonus
  * Month 2+ (recurring per active paid business):
      - 1..25 active businesses: 5 EUR / month (Ambasador)
      - 26..50 active businesses: 10 EUR / month (Ambasador Manager)
      - 51+ active businesses: 15 EUR / month (Ambasador Senior 50+)
- Wise Business / IBAN payout tracking
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean
import uuid
import qrcode
import io
import base64


def create_sales_models(Base):
    class SalesAgent(Base):
        __tablename__ = "sales_agents"
        id = Column(Integer, primary_key=True, index=True)
        user_id = Column(Integer, index=True, nullable=True)
        name = Column(String)
        email = Column(String, unique=True, index=True)
        phone = Column(String, nullable=True)
        password = Column(String)
        role = Column(String, default="ambassador")
        rank = Column(String, default="Ambasador")
        commission_own = Column(Float, default=20.0)
        commission_team = Column(Float, default=5.0)
        bonus_team = Column(Float, default=0.0)
        is_manager = Column(Boolean, default=False)
        team_id = Column(Integer, nullable=True)
        qr_code = Column(String, unique=True, index=True)
        status = Column(String, default="active")
        active = Column(Boolean, default=True)
        trial_start = Column(String, nullable=True)
        trial_sales = Column(Integer, default=0)
        created_at = Column(String)
        validated_at = Column(String, nullable=True)
        payout_method = Column(String, default="wise")
        payout_details = Column(String, nullable=True)

    class SalesTeam(Base):
        __tablename__ = "sales_teams"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String)
        manager_id = Column(Integer, index=True)
        created_at = Column(String)

    class Sale(Base):
        __tablename__ = "sales"
        id = Column(Integer, primary_key=True, index=True)
        agent_id = Column(Integer, index=True)
        business_id = Column(Integer, index=True, nullable=True)
        business_name = Column(String)
        business_email = Column(String)
        business_type = Column(String, nullable=True)
        plan = Column(String, default="probusiness")
        amount = Column(Float, default=67.0)
        commission = Column(Float, default=20.0)
        status = Column(String, default="pending")
        activated_month = Column(String, index=True, nullable=True)
        qr_scanned_at = Column(String, nullable=True)
        completed_at = Column(String, nullable=True)
        month = Column(String, index=True)

    class Commission(Base):
        __tablename__ = "commissions"
        id = Column(Integer, primary_key=True, index=True)
        agent_id = Column(Integer, index=True)
        sale_id = Column(Integer, nullable=True)
        type = Column(String)
        amount = Column(Float)
        month = Column(String, index=True)
        status = Column(String, default="pending")
        paid_at = Column(String, nullable=True)
        created_at = Column(String)

    return SalesAgent, SalesTeam, Sale, Commission


def get_ambassador_tier(active_paid_count: int) -> dict:
    if active_paid_count >= 51:
        return {"rank": "Ambasador Senior 50+", "monthly_rate": 15.0, "activation_bonus": 20.0, "next_tier": None}
    elif active_paid_count >= 26:
        return {"rank": "Ambasador Manager", "monthly_rate": 10.0, "activation_bonus": 20.0, "next_tier": 51}
    else:
        return {"rank": "Ambasador", "monthly_rate": 5.0, "activation_bonus": 20.0, "next_tier": 26}


def generate_agent_qr(agent_id: int, agent_name: str, existing_code: str = None) -> dict:
    ref_code = existing_code or f"LOIAL-{agent_id}-{uuid.uuid4().hex[:6].upper()}"
    ref_url = "https://" + "loial.space" + "/register.html?ref=" + ref_code
    img = qrcode.make(ref_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {
        "qr_code": ref_code,
        "referral_url": ref_url,
        "qr_image": f"data:image/png;base64,{b64}",
        "agent_id": agent_id,
        "agent_name": agent_name
    }


def calculate_commissions(db, Sale, Commission, SalesAgent, month: str = None):
    if not month:
        month = datetime.now().strftime("%Y-%m")

    results = []
    agents = db.query(SalesAgent).filter(SalesAgent.active == True).all()

    for agent in agents:
        active_sales = db.query(Sale).filter(
            Sale.agent_id == agent.id,
            Sale.status == "completed"
        ).all()

        total_active = len(active_sales)
        tier = get_ambassador_tier(total_active)
        agent.rank = tier["rank"]
        agent.is_manager = total_active >= 26
        agent.commission_team = tier["monthly_rate"]

        month1_sales = [s for s in active_sales if (s.activated_month or s.month) == month]
        recurring_sales = [s for s in active_sales if (s.activated_month or s.month) != month]

        new_activations_count = len(month1_sales)
        recurring_count = len(recurring_sales)

        activation_total = new_activations_count * 20.0
        recurring_total = recurring_count * tier["monthly_rate"]
        total = round(activation_total + recurring_total, 2)

        existing = db.query(Commission).filter(
            Commission.agent_id == agent.id,
            Commission.month == month,
            Commission.type == "monthly"
        ).first()

        if existing:
            existing.amount = total
        else:
            db.add(Commission(
                agent_id=agent.id,
                type="monthly",
                amount=total,
                month=month,
                status="pending",
                created_at=datetime.now().isoformat()
            ))

        results.append({
            "agent_id": agent.id,
            "agent_name": agent.name,
            "email": agent.email,
            "payout_method": agent.payout_method or "wise",
            "payout_details": agent.payout_details or "",
            "rank": tier["rank"],
            "total_active_businesses": total_active,
            "new_this_month": new_activations_count,
            "activation_commission": activation_total,
            "recurring_businesses": recurring_count,
            "recurring_rate": tier["monthly_rate"],
            "recurring_commission": recurring_total,
            "total": total
        })

    db.commit()
    return results
