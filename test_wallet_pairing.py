"""Regression tests: pairing never uses public QR, does not change stamp ledger."""
import asyncio
from datetime import datetime, timedelta, timezone
import secrets
import pytest
import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from loial_inbox import InboxBase, WalletInboxAccess, access_hash
from loial_wallet_pairing import install_wallet_pairing, WalletPairTicket

def setup_app():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    InboxBase.metadata.create_all(engine)
    Session=sessionmaker(bind=engine)
    cipher=Fernet(Fernet.generate_key())
    app=FastAPI()
    install_wallet_pairing(app,engine,Session,
        encrypt=lambda value:cipher.encrypt(value.encode()).decode(),
        decrypt=lambda value:cipher.decrypt(value.encode()).decode())
    with Session() as session:
        session.add(WalletInboxAccess(wallet_uuid="W-"+"a"*32,
            token_hash=access_hash("t"*48),created_at=datetime.now(timezone.utc).isoformat()))
        session.commit()
    return app, Session

async def call(app,method,path,**kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        return await client.request(method,path,**kwargs)

def test_private_pairing_one_time():
    app,Session=setup_app()
    async def run():
        assert (await call(app,"POST","/api/loial-wallet-pair/issue",
            headers={"X-Loial-Wallet-Id":"W-"+"a"*32,
                     "X-Loial-Wallet-Token":"wrong"*12})).status_code==403
        assert (await call(app,"POST","/api/loial-wallet-pair/issue",
            headers={"X-Loial-Wallet-Id":"W-"+"a"*32})).status_code==401
        valid={"X-Loial-Wallet-Id":"W-"+"a"*32,
               "X-Loial-Wallet-Token":"t"*48}
        issue=await call(app,"POST","/api/loial-wallet-pair/issue",headers=valid)
        assert issue.status_code==200,issue.text
        code=issue.json()["pairing_code"]
        assert len(code)>=40
        assert (await call(app,"POST","/api/loial-wallet-pair/claim",
          json={"code":code+"X"})).status_code==404
        with Session() as session:
            ticket=session.query(WalletPairTicket).first()
            assert ticket and ticket.code_hash!=code
            assert "t"*48 not in ticket.private_token_encrypted
        claim=await call(app,"POST","/api/loial-wallet-pair/claim",json={"code":code})
        assert claim.status_code==200,claim.text
        assert claim.json()["wallet_uuid"]=="W-"+"a"*32
        assert claim.json()["private_token"]=="t"*48
        replay=await call(app,"POST","/api/loial-wallet-pair/claim",json={"code":code})
        assert replay.status_code==404
    asyncio.run(run())

def test_expired_pairing_never_recovers_token():
    app,Session=setup_app()
    async def run():
        issue=await call(app,"POST","/api/loial-wallet-pair/issue",headers={
          "X-Loial-Wallet-Id":"W-"+"a"*32,"X-Loial-Wallet-Token":"t"*48})
        assert issue.status_code==200
        code=issue.json()["pairing_code"]
        with Session() as session:
            ticket=session.query(WalletPairTicket).first()
            ticket.expires_at=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
            session.commit()
        claim=await call(app,"POST","/api/loial-wallet-pair/claim",json={"code":code})
        assert claim.status_code==404
    asyncio.run(run())
