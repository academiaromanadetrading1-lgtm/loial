"""Weekly reports: distinct industries, confirmed sales, no duplicate prompts."""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from loial_business_ai import BaseAI, AIProfile, AIDocument, AIMessage, AISale
from loial_weekly_jobs import WeeklyBase, WeeklyCycle, run_weekly_cycle, iso_week


def setup_weekly_fixture():
    DB=declarative_base()
    class Business(DB):
        __tablename__="business_accounts"
        id=Column(Integer,primary_key=True)
        name=Column(String(120))
        business_type=Column(String(90))
        plan=Column(String(40))
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},
                         poolclass=StaticPool)
    DB.metadata.create_all(engine)
    BaseAI.metadata.create_all(engine)
    WeeklyBase.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([
            Business(id=1,name="Taxi Test",business_type="Uber/Bolt",plan="probusiness"),
            Business(id=2,name="Auto Wash",business_type="self wash",plan="probusiness"),
            Business(id=3,name="Free Shop",business_type="retail",plan="free")])
        db.add(AISale(business_id=1,document_id=1,row_number=1,
                     sold_at="2026-11-10",transaction_id="t100",
                     product="Cursa",quantity=1,unit_price=80))
        db.add(AISale(business_id=1,document_id=1,row_number=2,
                     sold_at="2026-11-03",transaction_id="t101",
                     product="Cursa",quantity=1,unit_price=100))
        db.commit()
    return factory,Business


def test_weekly_idempotent_and_tenant_scoped():
    factory,Business=setup_weekly_fixture()
    local=datetime(2026,11,16,9,0,tzinfo=ZoneInfo("Europe/Bucharest"))
    with factory() as db:
        models=(Business,AIProfile,AIDocument,AIMessage,AISale)
        result=run_weekly_cycle(db,*models,as_of=local)
        assert result["count"]==2
        second=run_weekly_cycle(db,*models,as_of=local)
        assert second["count"]==0
        assert db.query(WeeklyCycle).count()==2
        messages=db.query(AIMessage).all()
        assert len(messages)==2
        by_business={m.business_id:m.content for m in messages}
        assert "Taxi Test" in by_business[1]
        assert "80.0" in by_business[1]
        assert "100.0" in by_business[1]
        assert "km" in by_business[1].lower() or "kilometri" in by_business[1].lower()
        assert "box" in by_business[2].lower()
        assert 3 not in by_business


def test_second_week_generates_one_more_per_business():
    factory,Business=setup_weekly_fixture()
    models=(Business,AIProfile,AIDocument,AIMessage,AISale)
    with factory() as db:
        monday=datetime(2026,11,16,10,0,tzinfo=ZoneInfo("Europe/Bucharest"))
        next_monday=datetime(2026,11,23,10,0,tzinfo=ZoneInfo("Europe/Bucharest"))
        assert run_weekly_cycle(db,*models,as_of=monday)["count"]==2
        assert run_weekly_cycle(db,*models,as_of=next_monday)["count"]==2
        assert run_weekly_cycle(db,*models,as_of=next_monday)["count"]==0
        assert db.query(WeeklyCycle).count()==4


def test_week_rollover_and_partial_data_marked_as_unverified():
    assert iso_week(datetime(2027,1,1,tzinfo=ZoneInfo("Europe/Bucharest")))=="2026-W53"
    factory,Business=setup_weekly_fixture()
    models=(Business,AIProfile,AIDocument,AIMessage,AISale)
    with factory() as db:
        at=datetime(2026,11,30,9,0,tzinfo=ZoneInfo("Europe/Bucharest"))
        result=run_weekly_cycle(db,*models,as_of=at)
        assert result["count"]==2
        for m in db.query(AIMessage).all():
            assert "nu inseamna ca afacerea nu a avut incasari" in m.content.lower()
