"""Loial proactive weekly business reviews, entirely in-app.

An opt-in server thread checks due requests; a unique business+ISO-week index
guarantees at most one weekly prompt across repeated calls and workers.
No mail/SMS/WhatsApp, AI request, or external API is triggered by this job.
"""
import os
import threading
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Column, Integer, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base

from loial_industries import canonical, weekly_request, profile

WeeklyBase=declarative_base()
_ROMANIA=ZoneInfo("Europe/Bucharest")
_running=False
_runner_lock=threading.Lock()

class WeeklyCycle(WeeklyBase):
    __tablename__="loial_ai_weekly_cycles"
    id=Column(Integer,primary_key=True)
    business_id=Column(Integer,nullable=False,index=True)
    week=Column(String(8),nullable=False)
    created_at=Column(String(40),nullable=False)
    __table_args__=(UniqueConstraint("business_id","week",name="uq_loial_weekly_once"),)

def iso_week(local_time):
    d=local_time.isocalendar()
    return f"{d.year}-W{d.week:02d}"

def weekly_summary(db, business, p, docs, sales_model, as_of):
    """Only confirmed lines and explicit time ranges. No invented zero sales."""
    monday=as_of.date()-timedelta(days=as_of.weekday())
    beginning=monday-timedelta(days=7)
    previous_start=beginning-timedelta(days=7)
    sales=db.query(sales_model).filter(sales_model.business_id==business.id,
                                      sales_model.sold_at>=previous_start.isoformat(),
                                      sales_model.sold_at<monday.isoformat()).all()
    current=[x for x in sales if beginning.isoformat()<=x.sold_at[:10]<monday.isoformat()]
    before=[x for x in sales if previous_start.isoformat()<=x.sold_at[:10]<beginning.isoformat()]
    def total(rows):
        return round(sum(x.quantity*x.unit_price for x in rows),2)
    prefix="Raport saptamanal pentru "+business.name+" ("+profile(p.sector)["label"]+").\n"
    if current and before:
        old=total(before)
        new=total(current)
        delta=round(100*(new-old)/old,1) if old else None
        prefix+=("Din liniile de vanzari confirmate pentru "+beginning.isoformat()+" - "+
                 (monday-timedelta(days=1)).isoformat()+", incasari in baza exportata: "+
                 str(new)+" "+p.currency+". Saptamana anterioara: "+str(old)+" "+p.currency+". ")
        if delta is not None:
            prefix+="Variatie pe baza documentelor disponibile: "+str(delta)+"%. "
        else:
            prefix+="Comparatia procentuala nu este disponibila pentru o baza anterioara zero. "
        prefix+="Aceste cifre pot fi incomplete daca lipsesc vanzari din exporturi.\n"
    elif current:
        prefix+=("Exista "+str(len(current))+" linii confirmate in saptamana precedenta. "
                 "Pentru comparatie, lipseste istoricul aceleiasi perioade de referinta.\n")
    else:
        prefix+=("Nu exista vanzari confirmate importate pentru saptamana precedenta; "
                 "asta nu inseamna ca afacerea nu a avut incasari.\n")
    newest=docs[0] if docs else None
    if newest:
        prefix+="Ultimul document incarcat: "+newest.filename+" ("+newest.created_at[:10]+").\n"
    return prefix+weekly_request(p.sector)

def run_weekly_cycle(db, BusinessAccount, AIProfile, AIDocument,
                     AIMessage, AISale, as_of=None):
    """Idempotent unit of work. Safe to call from scheduled worker or tests."""
    as_of=as_of or datetime.now(_ROMANIA)
    if as_of.tzinfo is None:
        raise ValueError("as_of must include timezone")
    current=as_of.astimezone(_ROMANIA)
    week=iso_week(current)
    created=[]
    businesses=db.query(BusinessAccount).filter(
        BusinessAccount.plan.in_(("business","probusiness","pro","premium","enterprise"))
    ).all()
    for biz in businesses:
        old=db.query(WeeklyCycle).filter(
            WeeklyCycle.business_id==biz.id,WeeklyCycle.week==week).first()
        if old:
            continue
        p=db.query(AIProfile).filter(AIProfile.business_id==biz.id).first()
        if not p:
            p=AIProfile(business_id=biz.id,sector=canonical(biz.business_type or ""),
                        description="",currency="RON")
            db.add(p);db.flush()
        docs=db.query(AIDocument).filter(
            AIDocument.business_id==biz.id).order_by(AIDocument.id.desc()).limit(2).all()
        request=weekly_summary(db,biz,p,docs,AISale,current)
        try:
            db.add(WeeklyCycle(business_id=biz.id,week=week,
                               created_at=current.isoformat()))
            db.flush()
            db.add(AIMessage(business_id=biz.id,role="assistant",topic="weekly",
                             content=request[:12000],created_at=current.isoformat()))
            db.commit()
            created.append(biz.id)
        except IntegrityError:
            db.rollback() # another worker already created this week
    return {"week":week,"businesses_prompted":created,"count":len(created)}

def run_worker_loop(session_factory,models,stop_event):
    # First execution is on startup; subsequent cycles cannot duplicate prompts.
    while not stop_event.is_set():
        db=session_factory()
        try:
            run_weekly_cycle(db,*models)
        except Exception:
            db.rollback()
            import logging
            logging.getLogger("loial_weekly").exception("Weekly manager prompt failed")
        finally:
            db.close()
        stop_event.wait(3600)

def start_weekly_worker(engine,session_factory,models):
    """Enabled by default; set LOIAL_WEEKLY_JOBS_ENABLED=0 in isolated tests."""
    if os.getenv("LOIAL_WEEKLY_JOBS_ENABLED","1")!="1":
        return False
    global _running
    with _runner_lock:
        if _running:
            return False
        WeeklyBase.metadata.create_all(bind=engine)
        event=threading.Event()
        thread=threading.Thread(target=run_worker_loop,args=(session_factory,models,event),
                                name="loial-weekly-manager",daemon=True)
        thread.start()
        _running=True
        return True
