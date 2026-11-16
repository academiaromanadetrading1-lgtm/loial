"""Loial friends: customer referrals without ambassador registration or cash payouts."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from loial_inbox import InboxBase, issue_wallet_access
from loial_friend_referrals import (
    ReferralBase, FriendInvitation, FriendPoints, create_code, attribute_new_wallet,
    credit_after_valid_stamp, reverse_referral_for_refunded_receipt,
    reward_balance, install_friend_referrals, POINTS_PER_PERSON
)

@pytest.fixture
def env():
    engine=create_engine("sqlite://",
        connect_args={"check_same_thread":False},poolclass=StaticPool)
    InboxBase.metadata.create_all(engine)
    ReferralBase.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    app=FastAPI()
    install_friend_referrals(app,engine,factory)
    with factory() as db:
        inviter=issue_wallet_access(db,"referrer-wallet",True)
        friend=issue_wallet_access(db,"brand-new-wallet",True)
        db.commit()
    return TestClient(app),factory,inviter,friend

def auth(token):
    return {"X-Loial-Wallet-Token":token}

def test_ordinary_customer_can_invite_without_ambassador_role(env):
    client,db_factory,inviter,friend=env
    public=client.get("/api/loial-friends/program")
    assert public.status_code==200
    assert public.json()["requires_ambassador_role"] is False
    assert public.json()["monetary_value_eur"] is None
    assert public.json()["cash_withdrawal"] is False
    assert public.json()["merchant_redemption_enabled"] is False
    assert client.get("/api/loial-friends/me").status_code==401
    inviter_account=client.get("/api/loial-friends/me",headers=auth(inviter))
    assert inviter_account.status_code==200,inviter_account.text
    data=inviter_account.json()
    assert data["is_ambassador"] is False
    assert data["code"].startswith("L-")
    assert data["share_url"].startswith("https://loial.space/wallet?invite=L-")
    assert client.get("/api/loial-friends/validate",params={"code":data["code"]}).json()["valid"]

def test_first_verified_stamp_qualifies_both_parties_once(env):
    client,db_factory,inviter,friend=env
    code=client.get("/api/loial-friends/me",headers=auth(inviter)).json()["code"]
    with db_factory() as db:
        assert attribute_new_wallet(db,"brand-new-wallet",code)=="pending_first_verified_visit"
        assert attribute_new_wallet(db,"brand-new-wallet",code)=="already_attributed"
        db.commit()
    assert client.get("/api/loial-friends/me",headers=auth(inviter)).json()["points"]==0
    with db_factory() as db:
        assert credit_after_valid_stamp(db,"brand-new-wallet",7,"scan:event-001")=="qualified"
        assert credit_after_valid_stamp(db,"brand-new-wallet",7,"scan:event-001")=="not_pending"
        db.commit()
        assert reward_balance(db,"referrer-wallet")==POINTS_PER_PERSON
        assert reward_balance(db,"brand-new-wallet")==POINTS_PER_PERSON
        assert db.query(FriendPoints).count()==2
    assert client.get("/api/loial-friends/me",headers=auth(inviter)).json()["qualified"]==1
    assert client.get("/api/loial-friends/me",headers=auth(friend)).json()["points"]==10

def test_refund_reverses_both_rewards_and_next_valid_visit_requalifies(env):
    client,db_factory,inviter,friend=env
    code=client.get("/api/loial-friends/me",headers=auth(inviter)).json()["code"]
    with db_factory() as db:
        attribute_new_wallet(db,"brand-new-wallet",code)
        assert credit_after_valid_stamp(db,"brand-new-wallet",5,"receipt:101")=="qualified"
        db.commit()
        assert reverse_referral_for_refunded_receipt(db,"brand-new-wallet","receipt:102") is False
        assert reverse_referral_for_refunded_receipt(db,"brand-new-wallet","receipt:101") is True
        assert reverse_referral_for_refunded_receipt(db,"brand-new-wallet","receipt:101") is False
        db.commit()
        assert reward_balance(db,"referrer-wallet")==0
        assert reward_balance(db,"brand-new-wallet")==0
        assert db.query(FriendInvitation).first().status=="pending"
        assert credit_after_valid_stamp(db,"brand-new-wallet",5,"scan:second-real-visit")=="qualified"
        db.commit()
        assert reward_balance(db,"referrer-wallet")==POINTS_PER_PERSON
        assert reward_balance(db,"brand-new-wallet")==POINTS_PER_PERSON
        assert db.query(FriendPoints).count()==6

def test_self_referral_invalid_code_and_existing_attribution_blocked(env):
    client,db_factory,inviter,friend=env
    code=client.get("/api/loial-friends/me",headers=auth(inviter)).json()["code"]
    with db_factory() as db:
        assert attribute_new_wallet(db,"referrer-wallet",code)=="self_referral"
        assert attribute_new_wallet(db,"another-wallet","invalid-code")=="invalid"
        assert attribute_new_wallet(db,"brand-new-wallet",code)=="pending_first_verified_visit"
        assert attribute_new_wallet(db,"brand-new-wallet",code)=="already_attributed"
        db.commit()
    assert client.get("/api/loial-friends/validate",params={"code":"x"}).json()["valid"] is False

def test_monthly_cap_holds_excess_for_review(env):
    client,db_factory,inviter,friend=env
    code=client.get("/api/loial-friends/me",headers=auth(inviter)).json()["code"]
    with db_factory() as db:
        for n in range(21):
            name="additional-friend-"+str(n)
            issue_wallet_access(db,name,True)
            assert attribute_new_wallet(db,name,code)=="pending_first_verified_visit"
            result=credit_after_valid_stamp(db,name,3,"scan:"+str(n))
            assert result==("qualified" if n<20 else "monthly_limit_review")
            db.commit()
        assert reward_balance(db,"referrer-wallet")==20*POINTS_PER_PERSON
        assert db.query(FriendInvitation).filter(FriendInvitation.status=="review").count()==1
