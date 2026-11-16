"""Smoke test on the REAL assembled FastAPI app, isolated SQLite only.

Never connects to /data/loial.db or any production service.
"""
import importlib
import os
import sys

from fastapi.testclient import TestClient


def test_full_application_starts_and_registers_wallet(tmp_path, monkeypatch):
    filename = tmp_path / "loial-integration.sqlite"
    monkeypatch.setenv("LOIAL_DATABASE_URL", "sqlite:///" + str(filename))
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-only-this-process-must-not-go-to-production")
    monkeypatch.delenv("LOIAL_ADMIN_BOOTSTRAP_EMAIL", raising=False)
    monkeypatch.delenv("LOIAL_DEV_SEED_DATA", raising=False)
    monkeypatch.setenv("LOIAL_WEEKLY_JOBS_ENABLED","0")
    sys.modules.pop("main", None)
    main = importlib.import_module("main")
    try:
        with TestClient(main.app) as client:
            available = client.get("/api/premium-wallet/availability")
            assert available.status_code == 200
            assert available.json()["apple_ready"] is False
            assert available.json()["google_customer_ready"] is False

            unauthorized = client.get("/api/loial-identity/me")
            assert unauthorized.status_code == 401

            sign_up = client.post("/api/register", json={
                "email": "owner.smoke@example.invalid",
                "password": "strong-test-password-only",
                "business_name": "Service Auto Test",
                "reward": "A sasea vizita gratuita"
            })
            assert sign_up.status_code == 200, sign_up.text
            business_id = sign_up.json()["business_id"]
            bearer = {"Authorization": "Bearer " + sign_up.json()["token"]}
            public = client.get("/api/business-public/" + str(business_id))
            assert public.status_code == 200
            assert public.json()["name"] == "Service Auto Test"

            identity = client.get("/api/loial-identity/me", headers=bearer)
            assert identity.status_code == 200, identity.text
            assert identity.json()["roles"] == ["business"]

            new_card = client.post("/api/enroll-sync", json={
                "business_id": business_id,
                "uuid": "W-INTEGRATION-TEST-001",
                "name": "Client Test",
                "wallet_claim_token": "T" * 48,
                "consent_loial_offers": True
            })
            assert new_card.status_code == 200, new_card.text
            assert new_card.json()["inbox_access"] == "T" * 48
            retry = client.post("/api/enroll-sync", json={
                "business_id": business_id,
                "uuid": "W-INTEGRATION-TEST-001",
                "name": "Client Test",
                "wallet_claim_token": "T" * 48
            })
            assert retry.status_code == 200
            assert retry.json()["inbox_access"] == "T" * 48

            inbox = client.get("/api/loial-inbox/me",
                headers={"X-Loial-Wallet-Token": "T" * 48})
            assert inbox.status_code == 200
            assert any(message["kind"] == "service"
                       for message in inbox.json()["messages"])
            assert client.get("/api/premium-wallet/customer/cards",
                headers={"X-Loial-Wallet-Token": "T" * 48}).status_code == 200
            # New firms no longer inherit a publicly predictable primary PIN.
            account=client.get("/api/my-business",headers=bearer)
            assert account.status_code==200,account.text
            staff_pin=account.json()["staff_pin"]
            assert staff_pin.isdigit() and len(staff_pin)==4 and staff_pin!="1234"
            scan_payload={"business_id":business_id,"customer_uuid":"W-INTEGRATION-TEST-001",
                          "pin":"1234"}
            assert client.post("/api/scan-universal",json=scan_payload).status_code==401
            scan_payload["pin"]=staff_pin
            scan_payload["idempotency_key"]="integration-first-purchase"
            stamped=client.post("/api/scan-universal",json=scan_payload)
            assert stamped.status_code==200,stamped.text
            assert stamped.json()["stamps"]==1
            replay=client.post("/api/scan-universal",json=scan_payload)
            assert replay.status_code==200
            assert replay.json()["duplicate_ignored"] is True
            assert replay.json()["stamps"]==1
            # A fresh operation inside the cooldown is not another real purchase.
            scan_payload["idempotency_key"]="integration-too-soon"
            assert client.post("/api/scan-universal",json=scan_payload).status_code==409

            rotated=client.post("/api/my-business/rotate-pin",headers=bearer)
            assert rotated.status_code==200,rotated.text
            new_pin=rotated.json()["staff_pin"]
            assert new_pin!=staff_pin and new_pin!="1234"
            assert client.post("/api/scan-universal",json=scan_payload).status_code==401
            scan_payload["pin"]=new_pin
            # Simulate a later independent purchase rather than repeating the scan.
            from loial_scans import StampAward
            from datetime import datetime, timedelta, timezone
            with main.SessionLocal() as db:
                first=db.query(StampAward).first()
                first.created_at=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
                db.commit()
            scan_payload["idempotency_key"]="integration-second-purchase"
            assert client.post("/api/scan-universal",json=scan_payload).status_code==200

            # End-to-end: owner issues an itemized one-use Loial receipt; wallet claims
            # it once and sees a fresh stamp; no accounting or POS API is required.
            issued=client.post("/api/loial-receipts/issue",headers=bearer,json={
                "receipt_ref":"SMOKE-101",
                "lines":[{"product":"Revizie auto","quantity":1,"unit_price":200,
                          "unit_variable_cost":65}]
            })
            assert issued.status_code==200,issued.text
            receipt_token=issued.json()["claim_url"].split("token=")[1]
            claimed=client.post("/api/loial-receipts/claim",
                headers={"X-Loial-Wallet-Token":"T"*48},
                json={"receipt_token":receipt_token})
            assert claimed.status_code==200,claimed.text
            assert claimed.json()["stamps"]==3
            assert client.post("/api/loial-receipts/claim",
                headers={"X-Loial-Wallet-Token":"T"*48},
                json={"receipt_token":receipt_token}).status_code==409
            messages=client.get("/api/loial-inbox/me",
                headers={"X-Loial-Wallet-Token":"T"*48}).json()["messages"]
            assert sum(x["kind"]=="service" for x in messages)>=4
            # No external provider or recipient data is needed for this scenario.
    finally:
        main.engine.dispose()
        sys.modules.pop("main", None)
