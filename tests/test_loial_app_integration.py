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
    monkeypatch.setenv("LOIAL_PUBLIC_FREE_PILOT","1")
    sys.modules.pop("main", None)
    main = importlib.import_module("main")
    try:
        with TestClient(main.app) as client:
            # Railway health check is public, stable and contains no customer
            # counts, credentials, schema information or operational internals.
            health=client.get("/health")
            assert health.status_code==200,health.text
            assert health.json()=={"status":"healthy"}
            assert "customers" not in health.text
            assert "sqlite" not in health.text
            # Installable universal wallet, public icons, and cache-safe PWA shell.
            manifest=client.get("/manifest.json")
            assert manifest.status_code==200
            assert manifest.json()["start_url"].startswith("/wallet")
            assert manifest.json()["display"]=="standalone"
            assert len(manifest.json()["icons"])>=2
            app_page=client.get("/wallet")
            assert app_page.status_code==200,app_page.text
            assert app_page.headers["cache-control"] == "no-store"
            assert app_page.headers["x-content-type-options"] == "nosniff"
            assert app_page.headers["x-frame-options"] == "DENY"
            assert "id=\"walletQr\"" in app_page.text
            assert "loial-pwa-install.js" in app_page.text
            for size in (192,512):
                icon=client.get(f"/pwa-icon-{size}.png")
                assert icon.status_code==200
                assert icon.headers["content-type"]=="image/png"
                assert icon.content.startswith(b"\x89PNG\r\n\x1a\n")
            assert client.get("/sw.js").status_code==200
            # Verify public commercial policy in the actual assembled app.
            catalog=client.get("/api/loial-plans")
            assert catalog.status_code==200
            assert [(p["code"],p["price_eur"],p["customer_cap"],p["location_cap"])
                    for p in catalog.json()]==[
                ("start",0,50,1),("business",67,None,1),("probusiness",270,None,5)]
            simulation=client.get("/api/loial-plans/simulate",params={
                "new_business":10,"renewed_business":30,"new_pro":5,
                "renewed_pro":10,"recruited_business":5})
            assert simulation.status_code==200
            assert simulation.json()["total_commission_cents"]==150000
            assert simulation.json()["illustrative_subscription_revenue_cents"]==706500
            assert simulation.json()["scenario_only"] is True
            assert client.get("/api/loial-plans/simulate?new_business=-1").status_code==422
            for path in ("/demo","/ambasadori","/robots.txt","/sitemap.xml",
                         "/en/","/de/","/fr/","/it/","/es/","/nl/","/pl/","/hu/"):
                assert client.get(path).status_code==200,path
            for path in ("/api/loial-friends/me","/api/admin/pilot-metrics"):
                assert client.get(path).status_code==401,path
            program=client.get("/api/loial-friends/program").json()
            assert program["cash_withdrawal"] is False
            assert program["merchant_redemption_enabled"] is False
            assert program["requires_ambassador_role"] is False
            # Nothing in the repository root (DB, source, secret manager files)
            # may be disclosed over the former /static mount.
            for sensitive in ("/static/main.py","/static/.env",
                              "/static/loial.db","/static/.git/config",
                              "/static/requirements.txt"):
                assert client.get(sensitive).status_code==404,sensitive

            assert client.get("/loial-pwa-install.js").status_code==200
            assert client.get("/loial-offline.html").status_code==200
            available = client.get("/api/premium-wallet/availability")
            assert available.status_code == 200
            assert available.json()["apple_ready"] is False
            assert available.json()["google_customer_ready"] is False

            unauthorized = client.get("/api/loial-identity/me")
            assert unauthorized.status_code == 401
            assert unauthorized.headers["cache-control"] == "no-store"

            # UTF-8 byte length, not character count, must be bounded
            # before bcrypt hashes merchant credentials.
            for invalid in ("x"*73, "é"*37, "short"):
                rejected=client.post("/api/register",json={
                    "email":"invalid-password@example.invalid",
                    "password":invalid,"business_name":"Never Created"})
                assert rejected.status_code==422,rejected.text
            with main.SessionLocal() as db:
                assert db.query(main.BusinessAccount).filter_by(
                    email="invalid-password@example.invalid").count()==0
            # The isolated test exercised three extra rejected signup requests.
            # Reset only its in-process rate-limit backend so that the existing
            # five legitimate registration tests still verify their own flows.
            main.limiter._storage.reset()

            sign_up = client.post("/api/register", json={
                "email": "owner.smoke@example.invalid",
                "password": "strong-test-password-only",
                "business_name": "Service Auto Test",
                "reward": "A sasea vizita gratuita"
            })
            assert sign_up.status_code == 200, sign_up.text
            business_id = sign_up.json()["business_id"]
            bearer = {"Authorization": "Bearer " + sign_up.json()["token"]}
            from jose import jwt as scoped_jwt

            # A legacy User row sharing the email cannot impersonate the
            # separately authenticated BusinessAccount, even with role business.
            with main.SessionLocal() as db:
                colliding_user=main.User(
                    email="owner.smoke@example.invalid",
                    password=main.pwd_context.hash("legacy-only-password"),
                    name="Legacy Collision",role="business",plan="starter")
                db.add(colliding_user)
                db.commit()
            impersonated=client.post("/auth/login",json={
                "email":"owner.smoke@example.invalid",
                "password":"legacy-only-password"})
            assert impersonated.status_code==401,impersonated.text
            merchant_login=client.post("/auth/login",json={
                "email":"owner.smoke@example.invalid",
                "password":"strong-test-password-only"})
            assert merchant_login.status_code==200,merchant_login.text
            merchant_claims=scoped_jwt.decode(
                merchant_login.json()["access_token"],
                main.SECRET_KEY,algorithms=[main.ALGORITHM])
            assert merchant_claims["role"]=="business"
            assert merchant_claims["business_id"]==business_id
            with main.SessionLocal() as db:
                db.query(main.User).filter(
                    main.User.email=="owner.smoke@example.invalid").delete()
                db.commit()


            # A valid non-Business JWT with the same email must never be
            # accepted as merchant authentication on staff or settings APIs.
            other_role_token=scoped_jwt.encode({
                "sub":"owner.smoke@example.invalid","role":"customer"
            },main.SECRET_KEY,algorithm=main.ALGORITHM)
            wrong_scope_token=scoped_jwt.encode({
                "sub":"owner.smoke@example.invalid","role":"business",
                "business_id":999999
            },main.SECRET_KEY,algorithm=main.ALGORITHM)
            missing_scope_token=scoped_jwt.encode({
                "sub":"owner.smoke@example.invalid","role":"business"
            },main.SECRET_KEY,algorithm=main.ALGORITHM)
            string_scope_token=scoped_jwt.encode({
                "sub":"owner.smoke@example.invalid","role":"business",
                "business_id":str(business_id)
            },main.SECRET_KEY,algorithm=main.ALGORITHM)
            for token in (other_role_token,wrong_scope_token,missing_scope_token,
                          string_scope_token):
                headers={"Authorization":"Bearer "+token}
                assert client.get("/api/loial-crm/customers",headers=headers).status_code==403
                assert client.get("/api/loial-scans/history",headers=headers).status_code==403
                assert client.get("/api/my-business",headers=headers).status_code==403
                assert client.get("/api/my-business/staff",headers=headers).status_code==403
                assert client.post("/api/my-business/staff",headers=headers,json={
                    "name":"Unauthorized","pin":"8527"}).status_code==403
                assert client.post("/api/my-business/settings",headers=headers,json={
                    "reward_text":"Forged change"}).status_code==403
                assert client.post("/api/my-business/rotate-pin",headers=headers).status_code==403
            assert client.get("/api/my-business",headers=bearer).status_code==200

            # Legacy web login must issue the same scoped JWT needed by billing.
            login=client.post("/auth/login",json={
                "email":"owner.smoke@example.invalid",
                "password":"strong-test-password-only"})
            assert login.status_code==200,login.text
            assert login.headers["cache-control"] == "no-store"
            login_headers={"Authorization":"Bearer "+login.json()["access_token"]}

            # Changing a password must enforce the same minimum length as
            # creating an account, without locking out a valid merchant.
            weak_password=client.post("/api/change-password",json={
                "email":"owner.smoke@example.invalid",
                "old_password":"strong-test-password-only",
                "new_password":"short"
            })
            assert weak_password.status_code==422,weak_password.text
            overlong_password=client.post("/api/change-password",json={
                "email":"owner.smoke@example.invalid",
                "old_password":"strong-test-password-only",
                "new_password":"X"*73
            })
            assert overlong_password.status_code==422,overlong_password.text

            changed_password=client.post("/api/change-password",json={
                "email":"owner.smoke@example.invalid",
                "old_password":"strong-test-password-only",
                "new_password":"fresh-secure-password-only"
            })
            assert changed_password.status_code==200,changed_password.text
            assert client.post("/auth/login",json={
                "email":"owner.smoke@example.invalid",
                "password":"strong-test-password-only"
            }).status_code==401
            assert client.post("/auth/login",json={
                "email":"owner.smoke@example.invalid",
                "password":"fresh-secure-password-only"
            }).status_code==200
            restored_password=client.post("/api/change-password",json={
                "email":"owner.smoke@example.invalid",
                "old_password":"fresh-secure-password-only",
                "new_password":"strong-test-password-only"
            })
            assert restored_password.status_code==200,restored_password.text

            # The same email can exist in multiple account models. A public
            # password change must not rotate both roles with one request.
            with main.SessionLocal() as db:
                conflicting=main.User(
                    email="owner.smoke@example.invalid",
                    name="Second account role",
                    role="owner",
                    password=main.pwd_context.hash("strong-test-password-only")
                )
                db.add(conflicting)
                db.commit()
                conflicting_id=conflicting.id
            ambiguous=client.post("/api/change-password",json={
                "email":"owner.smoke@example.invalid",
                "old_password":"strong-test-password-only",
                "new_password":"fresh-secure-password-only"
            })
            assert ambiguous.status_code==409,ambiguous.text
            with main.SessionLocal() as db:
                business=db.query(main.BusinessAccount).filter(
                    main.BusinessAccount.email=="owner.smoke@example.invalid").one()
                operator=db.get(main.User,conflicting_id)
                assert main.pwd_context.verify("strong-test-password-only",business.password)
                assert main.pwd_context.verify("strong-test-password-only",operator.password)
                db.delete(operator)
                db.commit()


            assert client.get("/api/loial-stripe/me",headers=login_headers).status_code==200
            from jose import jwt as jose_jwt
            payload=jose_jwt.decode(login.json()["access_token"],
                main.SECRET_KEY,algorithms=[main.ALGORITHM])
            assert payload["role"]=="business"
            assert payload["business_id"]==business_id
            # A QR must resolve to a real business and must be a valid PNG.
            unknown_business_qr=client.get("/api/qr-image/999999999")
            assert unknown_business_qr.status_code==404
            assert client.get("/api/qr-image/0").status_code==404
            merchant_qr=client.get(f"/api/qr-image/{business_id}")
            assert merchant_qr.status_code==200,merchant_qr.text
            merchant_payload=merchant_qr.json()
            assert merchant_payload["url"]==f"https://loial.space/join/{business_id}"
            assert merchant_payload["qr_base64"].startswith("data:image/png;base64,")

            # Staging QR must stay on staging; never route to production.
            with monkeypatch.context() as scope:
                scope.setenv("LOIAL_PUBLIC_ORIGIN",
                             "https://loial-staging-staging.up.railway.app")
                staging_qr=client.get(f"/api/qr-image/{business_id}")
                assert staging_qr.status_code==200,staging_qr.text
                assert staging_qr.json()["url"]==(
                    f"https://loial-staging-staging.up.railway.app/join/{business_id}"
                )
            for invalid_origin in (
                "http://loial.space", "https://evil.example/path",
                "https://user@evil.example", "https://*.example",
                "https://loial.space?bad=1", "https://loial.space:99999",
            ):
                with monkeypatch.context() as scope:
                    scope.setenv("LOIAL_PUBLIC_ORIGIN",invalid_origin)
                    denied_qr=client.get(f"/api/qr-image/{business_id}")
                    assert denied_qr.status_code==503,(invalid_origin,denied_qr.text)

            public = client.get("/api/business-public/" + str(business_id))
            assert public.status_code == 200
            assert public.json()["name"] == "Service Auto Test"

            # Stripe remains unconfigured in this test: free firm has no
            # premium entitlement, and a fake plan flag cannot grant access.
            stripe_state=client.get("/api/loial-stripe/me",headers=bearer)
            assert stripe_state.status_code==200,stripe_state.text
            assert stripe_state.json()["plan_price_eur"]==67
            assert stripe_state.json()["free_pilot_only"] is True
            assert stripe_state.json()["checkout_configured"] is False
            checkout_disabled=client.post("/api/loial-stripe/checkout",headers=bearer)
            assert checkout_disabled.status_code==503

            assert stripe_state.json()["subscription"]["active"] is False

            # A stale display plan must never bypass expired Stripe access.
            with main.SessionLocal() as db:
                business=db.get(main.BusinessAccount,business_id)
                business.plan="probusiness"
                db.commit()
            stale_inbox=client.get("/api/loial-inbox/sent",headers=bearer)
            # The global subscription guard returns 402 before the inbox's
            # additional active-entitlement check returns 403.
            assert stale_inbox.status_code in (402,403),stale_inbox.text
            with main.SessionLocal() as db:
                business=db.get(main.BusinessAccount,business_id)
                business.plan="free"
                db.commit()

            assert client.get("/api/loial-stripe/me").status_code==401
            assert client.get("/api/loial-ai/context",headers=bearer).status_code==402
            identity = client.get("/api/loial-identity/me", headers=bearer)
            assert identity.status_code == 200, identity.text
            assert identity.headers["cache-control"] == "no-store"
            assert identity.json()["roles"] == ["business"]
            # Identity overview and role linking must not accept a Business
            # JWT without an exact account ID even when the email matches.
            for claims in (
                {"sub":"owner.smoke@example.invalid","role":"business"},
                {"sub":"owner.smoke@example.invalid","role":"business","business_id":"1"},
                {"sub":"owner.smoke@example.invalid","role":"business","business_id":999999}
            ):
                forged=scoped_jwt.encode(claims,main.SECRET_KEY,algorithm=main.ALGORITHM)
                headers={"Authorization":"Bearer "+forged}
                assert client.get("/api/loial-identity/me",headers=headers).status_code==403
                assert client.post("/api/loial-identity/ambassador/activate",
                    headers=headers,json={"display_name":"Unauthorized"}).status_code==403

            # Reject oversized or malformed public identifiers before
            # touching a merchant's customer records.
            for invalid_uuid in ("short", "W-"+"X"*130, "W-name?query", " W-invalid! "):
                rejected=client.post("/api/enroll-sync",json={
                    "business_id":business_id,"uuid":invalid_uuid,"name":"Test",
                    "wallet_claim_token":"T"*48})
                assert rejected.status_code==422,(invalid_uuid,rejected.text)
            for invalid_name in ("", " ", "X"*81):
                rejected=client.post("/api/enroll-sync",json={
                    "business_id":business_id,"uuid":"W-BOUNDARY-TEST-001",
                    "name":invalid_name,"wallet_claim_token":"T"*48})
                assert rejected.status_code==422,(invalid_name,rejected.text)
            invalid_email=client.post("/api/enroll-sync",json={
                "business_id":business_id,"uuid":"W-BOUNDARY-TEST-001",
                "name":"Client Test","email":"X"*161,
                "wallet_claim_token":"T"*48})
            assert invalid_email.status_code==422,invalid_email.text

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

            # A public wallet UUID must not be sufficient to disclose an
            # existing card, its identity, or a private inbox access token.
            for unauthorized_claim in (None, "P"*48):
                payload={
                    "business_id":business_id,
                    "uuid":"W-INTEGRATION-TEST-001",
                    "name":"Client Test",
                }
                if unauthorized_claim is not None:
                    payload["wallet_claim_token"]=unauthorized_claim
                denied_retry=client.post("/api/enroll-sync",json=payload)
                assert denied_retry.status_code==401,denied_retry.text
                assert "inbox_access" not in denied_retry.text


            inbox = client.get("/api/loial-inbox/me",
                headers={"X-Loial-Wallet-Token": "T" * 48})
            assert inbox.status_code == 200
            assert inbox.headers["cache-control"] == "no-store"
            assert any(message["kind"] == "service"
                       for message in inbox.json()["messages"])
            assert client.get("/api/premium-wallet/customer/cards",
                headers={"X-Loial-Wallet-Token": "T" * 48}).status_code == 200
            profile_url="/api/wallet-profile/W-INTEGRATION-TEST-001"
            assert client.get(profile_url).status_code==401
            assert client.get(profile_url,headers={
                "X-Loial-Wallet-Token":"P"*48}).status_code==401
            own_profile=client.get(profile_url,headers={
                "X-Loial-Wallet-Token":"T"*48})
            assert own_profile.status_code==200,own_profile.text
            assert own_profile.json()["name"]=="Client Test"
            assert own_profile.json()["cards"][0]["business_name"]=="Service Auto Test"
            # Retired endpoints must not expose loyalty data by public UUID
            # or let strangers change settings by supplying somebody's email.
            for legacy_get in (
                "/preferences?email=owner.smoke@example.invalid",
                f"/api/presence/{business_id}",
                "/api/customer-status/W-INTEGRATION-TEST-001",
            ):
                retired=client.get(legacy_get)
                assert retired.status_code==410,(legacy_get,retired.text)
                assert "Client Test" not in retired.text
            assert client.put("/preferences",params={
                "email":"owner.smoke@example.invalid","language":"es"
            }).status_code==410
            assert client.post(
                f"/api/presence/{business_id}/W-INTEGRATION-TEST-001"
            ).status_code==410
            # Even with a known valid customer ID, a private card is available
            # only through its wallet-specific proof token.
            assert client.get(profile_url,headers={
                "X-Loial-Wallet-Token":"wrong-token"
            }).status_code==401
            assert client.get("/api/qr-raw/abc",params={
                "color":"not-a-color"
            }).status_code==422
            assert client.get("/api/qr-raw/"+("A"*513)).status_code==422
            qr_image=client.get("/api/qr-raw/valid-short-code")
            assert qr_image.status_code==200,qr_image.text
            assert qr_image.headers["content-type"]=="image/png"
            assert qr_image.content.startswith(b"\x89PNG\r\n\x1a\n")
            # New firms no longer inherit a publicly predictable primary PIN.
            account=client.get("/api/my-business",headers=bearer)
            assert account.status_code==200,account.text
            staff_pin=account.json()["staff_pin"]
            assert staff_pin.isdigit() and len(staff_pin)==4 and staff_pin!="1234"

            # A manual primary PIN cannot equal an active employee PIN.
            employee_pin="8527" if staff_pin!="8527" else "9462"
            employee=client.post("/api/my-business/staff",headers=bearer,json={
                "name":"Employee Collision Test","pin":employee_pin})
            assert employee.status_code==200,employee.text
            duplicate_primary=client.post("/api/my-business/settings",
                headers=bearer,json={"staff_pin":employee_pin})
            assert duplicate_primary.status_code==409,duplicate_primary.text
            unchanged=client.get("/api/my-business",headers=bearer)
            assert unchanged.json()["staff_pin"]==staff_pin
            removed=client.delete(
                "/api/my-business/staff/"+str(employee.json()["id"]),headers=bearer)
            assert removed.status_code==200,removed.text

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
            # Historical API aliases must not bypass the idempotent stamp ledger.
            for name, route in (("legacy", "/api/scan"),
                                ("v2", "/api/scan-v2")):
                unique="W-INTEGRATION-"+name.upper()
                enrolled=client.post("/api/enroll-sync",json={
                    "business_id":business_id,"uuid":unique,"name":"Client "+name,
                    "wallet_claim_token":("Q" if name=="legacy" else "R")*48
                })
                assert enrolled.status_code==200,enrolled.text
                original={"pin":new_pin,"business_id":business_id,
                          "customer_uuid":unique,"idempotency_key":"test-"+name+"-purchase"}
                once=client.post(route,json=original)
                assert once.status_code==200,once.text
                assert once.json()["stamps"]==1
                again=client.post(route,json=original)
                assert again.status_code==200,again.text
                assert again.json()["duplicate_ignored"] is True
                different={**original,"idempotency_key":"test-"+name+"-immediate"}
                assert client.post(route,json=different).status_code==409
            from loial_scans import StampAward
            with main.SessionLocal() as db:
                all_awards=db.query(StampAward).all()
                assert len(all_awards)==5 # 2 universal, 1 verified receipt, 2 legacy/v2 aliases
            history=client.get("/api/loial-scans/history?limit=100",headers=bearer)
            assert history.status_code==200,history.text
            assert len(history.json()["items"])==5
            assert history.json()["items"][0]["source"] in ("manual","receipt")
            assert client.get("/api/loial-scans/history").status_code==401
            second_business=client.post("/api/register",json={
                "email":"another.smoke@example.invalid",
                "password":"another-strong-test-password",
                "business_name":"Salon Test",
            })
            assert second_business.status_code==200,second_business.text
            other_bearer={"Authorization":"Bearer "+second_business.json()["token"]}

            # A universal wallet can hold a merchant-specific card ID. Its
            # private credential must still resolve to the canonical wallet.
            alias_card=client.post("/api/enroll-sync",json={
                "business_id":second_business.json()["business_id"],
                "uuid":"W-INTEGRATION-TEST-001","name":"Client Test",
                "wallet_claim_token":"T"*48
            })
            assert alias_card.status_code==200,alias_card.text
            assert alias_card.json()["inbox_access"]=="T"*48
            with main.SessionLocal() as db:
                alias=db.query(main.Customer).filter(
                    main.Customer.business_id==second_business.json()["business_id"],
                    main.Customer.wallet_uuid=="W-INTEGRATION-TEST-001").one()
                alias_uuid=alias.uuid
                assert alias_uuid!="W-INTEGRATION-TEST-001"
            alias_retry=client.post("/api/enroll-sync",json={
                "business_id":second_business.json()["business_id"],
                "uuid":alias_uuid,"name":"Client Test",
                "wallet_claim_token":"T"*48
            })
            assert alias_retry.status_code==200,alias_retry.text
            assert alias_retry.json()["status"]=="exists"
            assert alias_retry.json()["inbox_access"]=="T"*48
            without_proof=client.post("/api/enroll-sync",json={
                "business_id":second_business.json()["business_id"],
                "uuid":alias_uuid,"name":"Client Test"
            })
            assert without_proof.status_code==401,without_proof.text
            third_business=client.post("/api/register",json={
                "email":"third.smoke@example.invalid",
                "password":"another-strong-test-password",
                "business_name":"Floraria Test",
            })
            assert third_business.status_code==200,third_business.text
            via_alias=client.post("/api/enroll-sync",json={
                "business_id":third_business.json()["business_id"],
                "uuid":alias_uuid,"name":"Client Test",
                "wallet_claim_token":"T"*48
            })
            assert via_alias.status_code==200,via_alias.text
            assert via_alias.json()["inbox_access"]=="T"*48
            with main.SessionLocal() as db:
                third_card=db.query(main.Customer).filter(
                    main.Customer.business_id==third_business.json()["business_id"]).one()
                assert third_card.wallet_uuid=="W-INTEGRATION-TEST-001"

            # Cross-tenant access to merchant-private data must be denied in both directions.
            other_business_id = second_business.json()["business_id"]
            # One merchant cannot delete another merchant's employee by ID.
            staff_to_protect=client.post("/api/my-business/staff",headers=bearer,json={
                "name":"Protected Employee","pin":"8527" if staff_pin!="8527" else "9462"
            })
            assert staff_to_protect.status_code==200,staff_to_protect.text
            protected_id=staff_to_protect.json()["id"]
            foreign_delete=client.delete(
                "/api/my-business/staff/"+str(protected_id),headers=other_bearer)
            assert foreign_delete.status_code==200,foreign_delete.text
            foreign_direct=client.delete(
                f"/api/biz-full/{business_id}/staff/{protected_id}",
                headers=other_bearer)
            assert foreign_direct.status_code==403,foreign_direct.text
            with main.SessionLocal() as db:
                assert db.get(main.StaffMember,protected_id).active==1
            own_delete=client.delete(
                "/api/my-business/staff/"+str(protected_id),headers=bearer)
            assert own_delete.status_code==200,own_delete.text
            with main.SessionLocal() as db:
                assert db.get(main.StaffMember,protected_id).active==0
            for owner_headers, foreign_id in ((bearer, other_business_id), (other_bearer, business_id)):
                assert client.get("/api/biz-full/" + str(foreign_id), headers=owner_headers).status_code == 403
            assert client.get("/api/biz-full/" + str(business_id), headers=bearer).status_code == 200
            assert client.get("/setup-admin").status_code == 410
            assert client.get("/setup-admin", params={"email":"unauthorized@example.invalid"}).status_code == 410
            with main.SessionLocal() as db:
                assert db.query(main.User).filter(main.User.email == "unauthorized@example.invalid").first() is None
            other_history=client.get("/api/loial-scans/history",headers=other_bearer)
            assert other_history.status_code==200
            assert other_history.json()["items"]==[]

            # Only the platform administrator can monitor the first-100 Google pilot.
            assert client.get("/api/admin/google-wallet-pilot").status_code==401
            assert client.get("/api/admin/google-wallet-pilot",headers=bearer).status_code in (401,403)
            with main.SessionLocal() as db:
                db.add(main.User(email="supervisor@loial.test",
                    password=main.pwd_context.hash("test-admin-password-not-used"),
                    name="Administrator Test",role="admin",plan="pro"))
                db.commit()
            admin_token=main.create_access_token({"sub":"supervisor@loial.test","role":"admin"})
            # Administrator-only receipts and monthly export are read-only.
            assert client.get("/api/loial-revenue/admin/summary",headers=bearer).status_code in (401,403)
            from io import BytesIO
            from openpyxl import load_workbook
            revenue_export=client.get("/api/loial-revenue/admin/export/2026-11.xlsx",
                headers={"Authorization":"Bearer "+admin_token})
            assert revenue_export.status_code==200,revenue_export.text[:80] if revenue_export.status_code!=200 else ""
            workbook=load_workbook(BytesIO(revenue_export.content),read_only=True)
            assert "De platit" in workbook.sheetnames
            assert "Registru comisioane" in workbook.sheetnames
            pilot=client.get("/api/admin/google-wallet-pilot",
                headers={"Authorization":"Bearer "+admin_token})
            assert pilot.status_code==200,pilot.text
            state=pilot.json()
            assert state["goal_active_businesses"]==100
            assert state["businesses_with_recorded_stamp_awards"]==1
            assert state["businesses_registered"]==3  # Includes the wallet-alias merchant fixture
            assert state["google_wallet"]["publishing_approved"]=="not_verified"
            assert state["apple_wallet"]["in_pilot"] is False
            # Legacy wallet demo links must not impersonate official signed Google passes.
            assert client.get("/wallet/google/1").status_code==410
            assert client.get("/wallet/1").status_code==410
            # The old User-token API has no mapped customer ownership. Reject
            # export, delete and consent mutations from ordinary accounts.
            with main.SessionLocal() as db:
                db.add(main.User(email="other-user@loial.test",
                    password=main.pwd_context.hash("test-client-password-unused"),
                    name="Other User",role="owner",plan="starter"))
                db.commit()
            ordinary=main.create_access_token({"sub":"other-user@loial.test","role":"owner"})
            user_headers={"Authorization":"Bearer "+ordinary}
            with main.SessionLocal() as db:
                sensitive_customer=db.query(main.Customer).first()
                target=sensitive_customer.id
            assert client.get("/gdpr/export/"+str(target),headers=user_headers).status_code==403
            assert client.delete("/gdpr/delete/"+str(target),headers=user_headers).status_code==403
            assert client.post("/gdpr/consent",headers=user_headers,
                params={"customer_id":target,"purpose":"marketing","granted":True}).status_code==403
            # A normal client can invite a friend without becoming ambassador.
            client_headers={"X-Loial-Wallet-Token":"T"*48}
            referral=client.get("/api/loial-friends/me",headers=client_headers)
            assert referral.status_code==200,referral.text
            personal_code=referral.json()["code"]
            friend=client.post("/api/enroll-sync",json={
                "business_id":business_id,"name":"Prieten Loial",
                "uuid":"W-NEW-FRIEND-INTEGRATION",
                "wallet_claim_token":"F"*48,
                "friend_referral_code":personal_code
            })
            assert friend.status_code==200,friend.text
            assert friend.json()["friend_invitation_status"]=="pending_first_verified_visit"
            assert client.get("/api/loial-friends/me",headers=client_headers).json()["points"]==0
            first_visit=client.post("/api/scan-universal",json={
                "business_id":business_id,"customer_uuid":"W-NEW-FRIEND-INTEGRATION",
                "pin":new_pin,"idempotency_key":"first-verified-friend-visit"
            })
            assert first_visit.status_code==200,first_visit.text
            assert client.get("/api/loial-friends/me",headers=client_headers).json()["points"]==10
            assert client.get("/api/loial-friends/me",headers={
                "X-Loial-Wallet-Token":"F"*48}).json()["points"]==10
            # Ambassadors recruit via /ambasador.html, not a customer wallet page.
            def create_ambassador(email, sponsor_code=None):
                result=client.post("/api/ambassador/join",json={
                    "email":email,"name":email.split("@")[0],
                    "password":"test-ambassador-password-2026",
                    "sponsor_code":sponsor_code,"payout_method":"wise",
                    "payout_details":"ambassador@example.invalid"})
                assert result.status_code==200,result.text
                return result.json()
            ambassador_a=create_ambassador("ambassador-a@example.invalid")
            invalid_sponsor=client.post("/api/ambassador/join",json={
                "email":"no-sponsor@example.invalid","name":"Invalid Sponsor",
                "password":"secure-test-ambassador-2026",
                "sponsor_code":"LOIAL-UNKNOWN999",
                "payout_method":"wise","payout_details":"wise@example.invalid"})
            assert invalid_sponsor.status_code==422,invalid_sponsor.text
            with main.SessionLocal() as db:
                assert db.query(main.SalesAgent).filter(
                    main.SalesAgent.email=="no-sponsor@example.invalid").first() is None
            ambassador_b=create_ambassador("ambassador-b@example.invalid",
                ambassador_a["ref_code"])
            assert ambassador_b["sponsored_by_another_ambassador"] is True
            assert ambassador_b["ambassador_invite_url"].startswith(
                "https://loial.space/ambasador.html?ambref=")
            from loial_revenue_commissions import SponsorRelationship
            with main.SessionLocal() as db:
                link=db.query(SponsorRelationship).filter(
                    SponsorRelationship.ambassador_id==ambassador_b["id"]).one()
                assert link.sponsor_id==ambassador_a["id"]
            session_a={"Authorization":"Bearer "+ambassador_a["access_token"]}
            ambassador_status=client.get("/api/loial-revenue/ambassador/me",
                headers=session_a)
            assert ambassador_status.status_code==200
            assert ambassador_status.json()["sponsored_ambassadors"]==1
            assert ambassador_status.json()["pending_eur"]==0
            # A mistyped merchant referral must not silently drop ambassador pay.
            wrong_ref=client.post("/api/register",json={
                "email":"invalid-merchant-ref@example.invalid",
                "password":"merchant-password-strong",
                "business_name":"Referral must be valid",
                "ref_code":"LOIAL-INVALID999"})
            assert wrong_ref.status_code==422,wrong_ref.text
            with main.SessionLocal() as db:
                assert db.query(main.BusinessAccount).filter(
                    main.BusinessAccount.email=="invalid-merchant-ref@example.invalid").first() is None
            firm_b=client.post("/api/register",json={
                "email":"firm-recruited-by-b@example.invalid",
                "password":"secure-firm-test-password",
                "business_name":"Firma adusă de B",
                "ref_code":ambassador_b["ref_code"]})
            assert firm_b.status_code==200,firm_b.text
            with main.SessionLocal() as db:
                firm=db.query(main.BusinessAccount).filter(
                    main.BusinessAccount.id==firm_b.json()["business_id"]).one()
                assert firm.agent_id==ambassador_b["id"]
            status_a=client.get("/api/loial-revenue/ambassador/me",
                headers=session_a).json()
            assert status_a["pending_eur"]==0
            assert status_a["sponsored_ambassadors"]==1
            # Legacy payout destination may not be edited by an unrelated
            # authenticated account. The new endpoint re-verifies password.
            attacker=client.put(
                f"/sales/agent/{ambassador_b['id']}/payout",
                params={"method":"wise","details":"attacker@invalid.test"},
                headers=user_headers)
            assert attacker.status_code==410,attacker.text
            bad_update=client.put(
                "/api/loial-revenue/ambassador/wise-details",
                json={"password":"wrong password","account_details":"merchant@wise.test"},
                headers=session_a)
            assert bad_update.status_code==403,bad_update.text
            updated=client.put(
                "/api/loial-revenue/ambassador/wise-details",
                json={"password":"test-ambassador-password-2026",
                    "account_details":"ambassador-a@wise.test"},
                headers=session_a)
            assert updated.status_code==200,updated.text
            assert "ambassador-a@wise.test" not in updated.text
            refreshed=client.get("/api/loial-revenue/ambassador/me",
                headers=session_a)
            assert refreshed.status_code==200
            assert refreshed.json()["wise_details_saved"] is True
            assert "ambassador-a@wise.test" not in refreshed.text
            pricing=client.get("/pricing").json()
            assert any(x["plan"]=="pro" and x["base_price"]==67
                       and x["total"]==67 and x["vat_amount"]==0
                       for x in pricing)
            assert client.post("/email",params={"to":"victim@example.invalid",
                "subject":"spam","body":"spam"},headers=user_headers).status_code==410
            assert client.put("/pricing/pro",params={"base_price":1},
                headers=user_headers).status_code==410
            # Obsolete global CRM routes may not disclose or modify cross-firm
            # customer records, fabricate stamp awards or send arbitrary messages.
            for legacy in ("/customers","/stats","/locations"):
                assert client.get(legacy,headers=user_headers).status_code==410
            assert client.post("/customers",json={"name":"Forged"},
                headers=user_headers).status_code in (410,422)
            assert client.post("/stamp",json={"customer_id":target},
                headers=user_headers).status_code in (410,422)
            assert client.post("/notify",json={"customer_id":target,"message":"spam"},
                headers=user_headers).status_code in (410,422)
            # Legacy analytics routes must not leak merchant data or permit
            # unauthenticated fabricated purchases and cancellations.
            assert client.get("/analytics/business/"+str(business_id)).status_code==410
            assert client.post("/analytics/purchase",params={
                "customer_id":target,"business_id":business_id,
                "product":"fake","amount":999}).status_code==410
            assert client.post("/analytics/cancel",params={
                "business_id":business_id,"reason":"forged"},headers=user_headers).status_code==410
            assert client.get("/sales/live",headers=user_headers).status_code==410
            assert client.get("/analytics/agent/"+str(ambassador_a["id"]),
                headers=user_headers).status_code==410
            # Paid state must never be inferred solely from registration.
            # The public wallet route cannot bypass the free-tier 50-card limit.
            with main.SessionLocal() as db:
                for i in range(50):
                    db.add(main.Customer(
                        uuid=f"SMOKE-LIMIT-{i:03d}",
                        wallet_uuid=f"SMOKE-LIMIT-{i:03d}",
                        name=f"Customer {i}",stamps=0,
                        business_id=firm_b.json()["business_id"]))
                db.commit()
            denied=client.post("/api/enroll-sync",json={
                "business_id":firm_b.json()["business_id"],
                "uuid":"SMOKE-LIMIT-NEW-CUSTOMER",
                "name":"Client 51",
                "wallet_claim_token":"S"*48})
            assert denied.status_code==403,denied.text
            assert denied.json()["detail"]=="LIMIT_REACHED"
            also_denied=client.post("/api/enroll",json={
                "business_id":firm_b.json()["business_id"],"name":"Client 51"})
            assert also_denied.status_code==403,also_denied.text
            # Universal scan must also refuse to add an existing customer's
            # wallet to the capped-out second merchant.
            second_auth={"Authorization":"Bearer "+firm_b.json()["token"]}
            second_account=client.get("/api/my-business",headers=second_auth)
            assert second_account.status_code==200,second_account.text
            capped_scan=client.post("/api/scan-universal",json={
                "business_id":firm_b.json()["business_id"],
                "customer_uuid":"W-INTEGRATION-TEST-001",
                "pin":second_account.json()["staff_pin"],
                "idempotency_key":"capped-out-merchant-scan"})
            assert capped_scan.status_code==403,capped_scan.text
            assert capped_scan.json()["detail"]=="LIMIT_REACHED"
            # Admin-granted ProBusiness has no financial side effects.
            admin_headers={"Authorization":"Bearer "+admin_token}
            recruited_id=firm_b.json()["business_id"]
            manual_url=f"/api/admin/business/{recruited_id}/manual-plan"
            from loial_revenue_commissions import PaidMerchantInvoice, AmbassadorCommission
            with main.SessionLocal() as db:
                before=(db.query(PaidMerchantInvoice).count(),db.query(AmbassadorCommission).count())
            assert client.put(manual_url,json={"active":True},headers=second_auth).status_code==403
            grant=client.put(manual_url,json={"active":True},headers=admin_headers)
            assert grant.status_code==200,grant.text
            assert grant.json()["access_status"]=="manual_grant"
            assert client.get("/api/loial-stripe/me",headers=second_auth).json()["subscription"]["active"] is True
            with main.SessionLocal() as db:
                assert main.business_can_enroll_new_customers(db,recruited_id)
                assert db.get(main.BusinessAccount,recruited_id).max_customers==999999
            # Store the confirmed business profile, then read it in a new request.
            profile_payload={"sector":"patiserie","description":"Patiserie cu 4 angajati si 120 clienti zilnic.","currency":"EUR"}
            saved=client.put("/api/loial-ai/profile",json=profile_payload,headers=second_auth)
            assert saved.status_code==200,saved.text
            assert saved.json()["status"]=="saved"
            assert saved.json()["industry"]["key"]=="patiserie"
            assert saved.json()["currency"]=="EUR"
            assert saved.json()["description"]==profile_payload["description"]
            persisted=client.get("/api/loial-ai/context",headers=second_auth).json()
            assert persisted["industry"]["key"]=="patiserie"
            assert persisted["description"]==profile_payload["description"]
            assert persisted["currency"]=="EUR"
            assert client.put("/api/loial-ai/profile",json=profile_payload,headers=bearer).status_code==402
            assert client.get("/loial-i18n.js").status_code==200
            assert client.put(manual_url,json={"active":False},headers=admin_headers).status_code==200
            assert client.get("/api/loial-stripe/me",headers=second_auth).json()["subscription"]["active"] is False
            with main.SessionLocal() as db:
                assert not main.business_can_enroll_new_customers(db,recruited_id)
            invite_url="/api/admin/ambassador/invite"
            member_email="firm-recruited-by-b@example.invalid"
            assert client.post(invite_url,json={"email":member_email},headers=second_auth).status_code==403
            assert client.post(invite_url,json={"email":"no-member@example.invalid"},headers=admin_headers).status_code==404
            invite=client.post(invite_url,json={"email":member_email},headers=admin_headers)
            assert invite.status_code==200,invite.text
            token=invite.json()["activation_url"].split("#activate=")[1]
            claim=client.post("/api/ambassador/activate-invite",
                json={"activation_token":token,"password":"new-ambassador-test-password"})
            assert claim.status_code==200,claim.text
            assert client.post("/api/ambassador/activate-invite",
                json={"activation_token":token,"password":"new-ambassador-test-password"}).status_code==400
            invited_headers={"Authorization":"Bearer "+claim.json()["access_token"]}
            invited_claims=scoped_jwt.decode(claim.json()["access_token"],
                main.SECRET_KEY,algorithms=[main.ALGORITHM])
            assert client.get("/api/loial-identity/me",headers=invited_headers).status_code==200
            for missing_agent_id in (None,999999,"invalid"):
                forged_claims=dict(invited_claims)
                if missing_agent_id is None:
                    forged_claims.pop("agent_id",None)
                else:
                    forged_claims["agent_id"]=missing_agent_id
                forged=scoped_jwt.encode(forged_claims,main.SECRET_KEY,algorithm=main.ALGORITHM)
                assert client.get("/api/loial-identity/me",headers={
                    "Authorization":"Bearer "+forged}).status_code==403
            assert client.get("/api/loial-revenue/ambassador/me",headers=invited_headers).status_code==200
            assert client.get("/api/my-business",headers=second_auth).status_code==200
            with main.SessionLocal() as db:
                assert db.query(PaidMerchantInvoice).count()==before[0]
                assert db.query(AmbassadorCommission).count()==before[1]
                assert db.get(main.BusinessAccount,recruited_id).agent_id==ambassador_b["id"]
            # Manual stamps use an atomic bounded update rather than a
            # read-modify-write of a potentially stale customer object.
            from loial_scans import StampAward
            from datetime import datetime, timedelta, timezone
            with main.SessionLocal() as db:
                biz=db.get(main.BusinessAccount,business_id)
                biz.stamps_required=4
                card=db.query(main.Customer).filter(
                    main.Customer.business_id==business_id,
                    main.Customer.wallet_uuid=="W-INTEGRATION-TEST-001").one()
                card.stamps=3
                for award in db.query(StampAward).filter(
                    StampAward.business_id==business_id,
                    StampAward.customer_id==card.id).all():
                    award.created_at=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
                db.commit()
            final_stamp=client.post("/api/scan-universal",json={
                "business_id":business_id,"customer_uuid":"W-INTEGRATION-TEST-001",
                "pin":new_pin,"idempotency_key":"atomic-target-last-stamp"
            })
            assert final_stamp.status_code==200,final_stamp.text
            assert final_stamp.json()["stamps"]==4
            assert final_stamp.json()["reward_unlocked"] is True
            excess=client.post("/api/scan-universal",json={
                "business_id":business_id,"customer_uuid":"W-INTEGRATION-TEST-001",
                "pin":new_pin,"idempotency_key":"atomic-target-over-cap"
            })
            assert excess.status_code==409,excess.text
            with main.SessionLocal() as db:
                card=db.query(main.Customer).filter(
                    main.Customer.business_id==business_id,
                    main.Customer.wallet_uuid=="W-INTEGRATION-TEST-001").one()
                assert card.stamps==4
            # A reward is consumed once even when two staff terminals try to
            # redeem the same unlocked loyalty card.
            reward_payload={
                "business_id": business_id,
                "customer_uuid": "W-INTEGRATION-TEST-001",
                "pin": new_pin
            }
            redeemed=client.post("/api/redeem-reward",json=reward_payload)
            assert redeemed.status_code==200,redeemed.text
            assert redeemed.json()["stamps"]==0
            already_used=client.post("/api/redeem-reward",json=reward_payload)
            assert already_used.status_code==409,already_used.text
            with main.SessionLocal() as db:
                from loial_scans import StampAward
                card=db.query(main.Customer).filter(
                    main.Customer.business_id==business_id,
                    main.Customer.wallet_uuid=="W-INTEGRATION-TEST-001").one()
                assert card.stamps==0
                assert db.query(StampAward).filter(
                    StampAward.business_id==business_id,
                    StampAward.customer_id==card.id,
                    StampAward.source=="redeem").count()==1
            # No external provider or recipient data is needed for this scenario.
    finally:
        main.engine.dispose()
        sys.modules.pop("main", None)
