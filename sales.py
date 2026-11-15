"""
Loial Sales System
- QR-based onboarding
- Commission tracking
- Team management
"""
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
import uuid
import qrcode
import io
import base64

def create_sales_models(Base):
    class SalesAgent(Base):
        __tablename__ = "sales_agents"
        id = Column(Integer, primary_key=True, index=True)
        user_id = Column(Integer, index=True)
        name = Column(String)
        email = Column(String, unique=True, index=True)
        phone = Column(String)
        password = Column(String)
        role = Column(String, default="pending")
        commission_own = Column(Float, default=20.0)
        commission_team = Column(Float, default=5.0)
        bonus_team = Column(Float, default=5.0)
        is_manager = Column(Boolean, default=False)
        team_id = Column(Integer, nullable=True)
        qr_code = Column(String, unique=True)
        status = Column(String, default="pending")
        active = Column(Boolean, default=False)
        trial_start = Column(String, nullable=True)
        trial_sales = Column(Integer, default=0)
        created_at = Column(String)
        validated_at = Column(String, nullable=True)
        payout_method = Column(String, default="bank")
        payout_details = Column(String)

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
        business_name = Column(String)
        business_email = Column(String)
        business_type = Column(String)
        plan = Column(String, default="pro")
        amount = Column(Float, default=49.0)
        commission = Column(Float, default=0.0)
        status = Column(String, default="pending")
        qr_scanned_at = Column(String)
        completed_at = Column(String)
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

def generate_agent_qr(agent_id: int, agent_name: str, existing_code: str = None) -> dict:
    qr_data = existing_code or f"AETHER-SALES:{agent_id}:{uuid.uuid4().hex[:8]}"
    img = qrcode.make(qr_data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {
        "qr_code": qr_data,
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
        own_sales = db.query(Sale).filter(
            Sale.agent_id == agent.id,
            Sale.month == month,
            Sale.status == "completed"
        ).all()
        
        own_count = len(own_sales)
        own_commission = own_count * agent.commission_own
        
        team_commission = 0
        team_bonus = 0
        team_sales_count = 0
        
        if agent.is_manager and agent.team_id:
            team_agents = db.query(SalesAgent).filter(
                SalesAgent.team_id == agent.team_id,
                SalesAgent.id != agent.id,
                SalesAgent.active == True
            ).all()
            
            active_team_count = 0
            for ta in team_agents:
                ta_sales = db.query(Sale).filter(
                    Sale.agent_id == ta.id,
                    Sale.month == month,
                    Sale.status == "completed"
                ).count()
                if ta_sales >= 5:
                    active_team_count += 1
                team_sales_count += ta_sales
            
            eligible = own_count >= 5
            if eligible:
                team_commission = team_sales_count * agent.commission_team
                if active_team_count >= 10:
                    team_bonus = team_sales_count * agent.bonus_team
        
        total = own_commission + team_commission + team_bonus
        
        existing = db.query(Commission).filter(
            Commission.agent_id == agent.id,
            Commission.month == month,
            Commission.type == "monthly"
        ).first()
        
        if existing:
            existing.amount = total
        else:
            comm = Commission(
                agent_id=agent.id,
                type="monthly",
                amount=total,
                month=month,
                status="pending",
                created_at=datetime.now().isoformat()
            )
            db.add(comm)
        
        results.append({
            "agent_id": agent.id,
            "agent_name": agent.name,
            "own_sales": own_count,
            "own_commission": own_commission,
            "team_sales": team_sales_count,
            "team_commission": team_commission,
            "team_bonus": team_bonus,
            "total": total,
            "eligible_for_team": own_count >= 5 if agent.is_manager else None
        })
    
    db.commit()
    return results
