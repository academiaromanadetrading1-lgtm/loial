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
            # No external provider or recipient data is needed for this scenario.
    finally:
        main.engine.dispose()
        sys.modules.pop("main", None)
