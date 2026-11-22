"""Boot the real FastAPI application with an isolated disposable SQLite database.

Never connects to Railway, Stripe, or production; no credentials needed beyond
an ephemeral local JWT secret. Fail CI if a route installer or import is broken.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class ApplicationBootSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="loial-smoke-")
        env = {
            "LOIAL_DATABASE_URL": "sqlite:///" + str(Path(cls.tempdir.name) / "loial-test.db"),
            "JWT_SECRET_KEY": "ci-only-e9c5bd3d6a21f0b79cc4ae734df8aa91c0b6b7b97025",
            "RAILWAY_ENVIRONMENT_NAME": "",
            "LOIAL_DEV_SEED_DATA": "0",
            "LOIAL_WEEKLY_JOBS_ENABLED": "0",
            "LOIAL_GOOGLE_WALLET_SYNC_ENABLED": "0",
            "LOIAL_APPLE_PILOT_ENABLED": "0",
            "LOIAL_PUBLIC_FREE_PILOT": "1",
            "LOIAL_PUBLIC_ORIGIN": "https://ci.local.example",
            "ALLOWED_ORIGINS": "https://ci.local.example",
            "LOIAL_ADMIN_BOOTSTRAP_EMAIL": "",
            "LOIAL_ADMIN_BOOTSTRAP_PASSWORD": "",
        }
        cls.patch = patch.dict(os.environ,env)
        cls.patch.start()
        import main
        cls.application = main
        cls.client = TestClient(main.app)
        # Enter the ASGI lifespan so startup migrations/optional queue tables
        # exist exactly as they do in Railway (TestClient() alone skips startup).
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.patch.stop()
        cls.tempdir.cleanup()

    def test_public_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200,response.text)

    def test_winback_routes_registered(self):
        # FastAPI may nest included routes inside _IncludedRouter wrappers.
        # Request the real ASGI app to prove route dispatch works end to end.
        routes = (
            ("GET", "/api/loial-winback/insights"),
            ("GET", "/api/loial-winback/settings"),
            ("POST", "/api/loial-winback/campaigns/draft"),
            ("POST", "/api/loial-winback/campaigns/1/approve"),
            ("GET", "/api/loial-winback/campaigns/attributions"),
        )
        for method,path in routes:
            with self.subTest(path=path):
                response = self.client.request(method,path)
                self.assertIn(response.status_code,(401,403),response.text)

    def test_private_winback_api_denies_anonymous_requests(self):
        for path in ("/api/loial-winback/settings",
                     "/api/loial-winback/insights",
                     "/api/loial-winback/campaigns/attributions"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertIn(response.status_code,(401,403),response.text)
                self.assertEqual(response.headers.get("Cache-Control"),"no-store")

    def test_core_customer_and_merchant_pages_serve_successfully(self):
        for path in ("/", "/login.html", "/register.html", "/join.html",
                     "/scan.html", "/platform.html", "/loial-i18n.js"):
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200,response.text[:150])

    def test_pwa_assets_and_language_dictionary_are_accessible(self):
        manifest=self.client.get("/manifest.json")
        self.assertEqual(manifest.status_code,200,manifest.text)
        self.assertIn("name",manifest.json())
        worker=self.client.get("/sw.js")
        self.assertEqual(worker.status_code,200,worker.text[:150])
        self.assertIn("javascript",worker.headers.get("content-type",""))
        language=self.client.get("/loial-i18n.js")
        self.assertEqual(language.status_code,200,language.text[:150])
        self.assertIn("const langs=",language.text)

    def test_unauthenticated_merchant_data_is_not_public(self):
        for path in ("/api/biz-full/1",
                     "/api/loial-scans/history",
                     "/api/loial-winback/campaigns"):
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertIn(response.status_code,(401,403),response.text[:150])
                self.assertEqual(response.headers.get("Cache-Control"),"no-store")

    def test_new_customer_joins_require_existing_merchant(self):
        response=self.client.get("/join/987654321")
        self.assertEqual(response.status_code,404,response.text)

    def test_stripe_webhook_unconfigured_fails_closed(self):
        with patch.dict(os.environ,{"LOIAL_PUBLIC_FREE_PILOT":"0",
                                    "LOIAL_STRIPE_WEBHOOK_SECRET":""}):
            response=self.client.post("/api/loial-stripe/webhook",
                                      content=b"{}",headers={"Stripe-Signature":"invalid"})
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual(response.headers.get("Cache-Control"),"no-store")

    def test_stripe_webhook_rejects_invalid_signature(self):
        with patch.dict(os.environ,{"LOIAL_PUBLIC_FREE_PILOT":"0",
                                    "LOIAL_STRIPE_WEBHOOK_SECRET":"whsec_ci_only",
                                    "LOIAL_STRIPE_SECRET_KEY":"sk_test_ci_only"}):
            response=self.client.post("/api/loial-stripe/webhook",
                                      content=b"{}",headers={"Stripe-Signature":"invalid"})
        self.assertEqual(response.status_code,400,response.text)

    def test_stripe_webhook_records_unknown_event_once_without_real_stripe(self):
        # The mocked signature verifier simulates a VERIFIED Stripe event.
        # This test sends no network calls and cannot create real payments.
        import stripe
        event={"id":"evt_loial_ci_smoke_unique","livemode":False,
               "type":"test.loial_smoke","data":{"object":{}}}
        env={"LOIAL_PUBLIC_FREE_PILOT":"0",
             "LOIAL_STRIPE_WEBHOOK_SECRET":"whsec_ci_only",
             "LOIAL_STRIPE_SECRET_KEY":"sk_test_ci_only"}
        with patch.dict(os.environ,env):
            with patch.object(stripe.Webhook,"construct_event",return_value=event):
                first=self.client.post("/api/loial-stripe/webhook",content=b"{}")
                again=self.client.post("/api/loial-stripe/webhook",content=b"{}")
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()["status"],"recorded")
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(again.json()["status"],"duplicate")

    def test_stripe_webhook_ignores_live_event_with_test_key(self):
        import stripe
        event={"id":"evt_loial_ci_live_mismatch","livemode":True,
               "type":"test.loial_smoke","data":{"object":{}}}
        env={"LOIAL_PUBLIC_FREE_PILOT":"0",
             "LOIAL_STRIPE_WEBHOOK_SECRET":"whsec_ci_only",
             "LOIAL_STRIPE_SECRET_KEY":"sk_test_ci_only"}
        with patch.dict(os.environ,env):
            with patch.object(stripe.Webhook,"construct_event",return_value=event):
                response=self.client.post("/api/loial-stripe/webhook",content=b"{}")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["status"],"ignored_mode_mismatch")

    def test_synthetic_wallet_enrollment_scan_and_private_inbox_flow(self):
        """Full ASGI test: join QR, guarded enrollment, actual scan ledger, private inbox."""
        from loial_inbox import InboxDelivery
        from loial_scans import StampAward
        app=self.application
        with app.SessionLocal() as db:
            db.add_all([
                app.BusinessAccount(id=98701,name="Pilot Bakery A",
                    email="pilot-a@example.invalid",plan="free",staff_pin="864209"),
                app.BusinessAccount(id=98702,name="Pilot Bakery B",
                    email="pilot-b@example.invalid",plan="free",staff_pin="125498")
            ])
            db.commit()
        good_join=self.client.get("/join/98701")
        self.assertEqual(good_join.status_code,200,good_join.text[:150])
        missing=self.client.get("/join/98703")
        self.assertEqual(missing.status_code,404,missing.text[:150])
        secret="ci-only-device-private-token-98701-0123456789abcdefghijkl"
        payload={"business_id":98701,"name":"Test Wallet Holder",
                 "uuid":"ci-wallet-98701","consent_loial_offers":False,
                 "wallet_claim_token":secret}
        registered=self.client.post("/api/enroll-sync",json=payload)
        self.assertEqual(registered.status_code,200,registered.text)
        self.assertEqual(registered.json()["status"],"saved")
        self.assertEqual(registered.json()["inbox_access"],secret)

        unauthorized=self.client.post("/api/enroll-sync",
            json={**payload,"wallet_claim_token":None})
        self.assertEqual(unauthorized.status_code,401,unauthorized.text)
        repeat=self.client.post("/api/enroll-sync",json=payload)
        self.assertEqual(repeat.status_code,200,repeat.text)
        self.assertEqual(repeat.json()["status"],"exists")

        inbox=self.client.get("/api/loial-inbox/me",
            headers={"X-Loial-Wallet-Token":secret})
        self.assertEqual(inbox.status_code,200,inbox.text)
        self.assertEqual(inbox.json()["cards"],1)
        public=self.client.get("/api/loial-inbox/me")
        self.assertEqual(public.status_code,401,public.text)
        other=self.client.get("/api/loial-inbox/me",
            headers={"X-Loial-Wallet-Token":"ci-only-another-device-token-"+"z"*48})
        self.assertEqual(other.status_code,401,other.text)

        scan={"business_id":98701,"pin":"864209","customer_uuid":"ci-wallet-98701",
              "idempotency_key":"ci-purchase-98701-0001"}
        wrong=self.client.post("/api/scan-universal",json={**scan,"pin":"111111"})
        self.assertEqual(wrong.status_code,401,wrong.text)
        first=self.client.post("/api/scan-universal",json=scan)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()["stamps"],1)
        replay=self.client.post("/api/scan-universal",json=scan)
        self.assertEqual(replay.status_code,200,replay.text)
        self.assertTrue(replay.json()["duplicate_ignored"])
        another=self.client.post("/api/scan-universal",
            json={**scan,"idempotency_key":"ci-purchase-98701-0002"})
        self.assertEqual(another.status_code,409,another.text)
        with app.SessionLocal() as db:
            card=db.query(app.Customer).filter(
                app.Customer.business_id==98701,
                app.Customer.wallet_uuid=="ci-wallet-98701").one()
            self.assertEqual(card.stamps,1)
            self.assertEqual(db.query(StampAward).filter(
                StampAward.business_id==98701).count(),1)
            self.assertEqual(db.query(InboxDelivery).filter(
                InboxDelivery.business_id==98702).count(),0)

        # Same universal wallet can join a second merchant only after proving
        # possession of its private device credential.
        second={**payload,"business_id":98702}
        denied=self.client.post("/api/enroll-sync",
            json={**second,"wallet_claim_token":None})
        self.assertEqual(denied.status_code,401,denied.text)
        allowed=self.client.post("/api/enroll-sync",json=second)
        self.assertEqual(allowed.status_code,200,allowed.text)
        self.assertEqual(allowed.json()["inbox_access"],secret)
        after=self.client.get("/api/loial-inbox/me",
            headers={"X-Loial-Wallet-Token":secret})
        self.assertEqual(after.status_code,200,after.text)
        self.assertEqual(after.json()["cards"],2)
        with app.SessionLocal() as db:
            cards=db.query(app.Customer).filter(
                app.Customer.wallet_uuid=="ci-wallet-98701").all()
            self.assertEqual({c.business_id for c in cards},{98701,98702})
            self.assertEqual({c.business_id:c.stamps for c in cards},
                             {98701:1,98702:0})

    def test_paid_receipt_at_stamp_cap_is_claimed_once_without_extra_stamp(self):
        """A receipt documents a visit even after a loyalty reward is unlocked."""
        from urllib.parse import urlsplit, parse_qs
        from loial_receipts import Receipt
        from loial_scans import StampAward
        app=self.application
        merchant_id=98711
        wallet_uuid="ci-wallet-98711"
        secret="ci-only-receipt-private-device-98711-abcdefghijklmnopqrst"
        with app.SessionLocal() as db:
            db.add(app.BusinessAccount(id=merchant_id,name="Receipt Bakery",
                email="receipt-pilot@example.invalid",plan="free",staff_pin="864209"))
            db.commit()
        enrolled=self.client.post("/api/enroll-sync",json={
            "business_id":merchant_id,"name":"Receipt Tester",
            "uuid":wallet_uuid,"wallet_claim_token":secret})
        self.assertEqual(enrolled.status_code,200,enrolled.text)
        with app.SessionLocal() as db:
            customer=db.query(app.Customer).filter_by(
                business_id=merchant_id,wallet_uuid=wallet_uuid).one()
            customer.stamps=6
            db.commit()

        auth=app.create_access_token({
            "sub":"receipt-pilot@example.invalid","role":"business",
            "business_id":merchant_id})
        payload={"receipt_ref":"CI-RECEIPT-CAP-001","currency":"RON",
                 "lines":[{"product":"Synthetic bread","quantity":1,"unit_price":18.0}]}
        issued=self.client.post("/api/loial-receipts/issue",
            json=payload,headers={"Authorization":"Bearer "+auth})
        self.assertEqual(issued.status_code,200,issued.text)
        self.assertEqual(issued.json()["status"],"issued")
        receipt_token=parse_qs(urlsplit(issued.json()["claim_url"]).query)["token"][0]
        claim=self.client.post("/api/loial-receipts/claim",
            json={"receipt_token":receipt_token},
            headers={"X-Loial-Wallet-Token":secret})
        self.assertEqual(claim.status_code,200,claim.text)
        self.assertEqual(claim.json()["status"],"claimed")
        self.assertFalse(claim.json()["stamp_granted"])
        self.assertEqual(claim.json()["stamps"],6)

        duplicate=self.client.post("/api/loial-receipts/claim",
            json={"receipt_token":receipt_token},
            headers={"X-Loial-Wallet-Token":secret})
        self.assertEqual(duplicate.status_code,409,duplicate.text)
        with app.SessionLocal() as db:
            receipt=db.query(Receipt).filter_by(
                business_id=merchant_id,receipt_ref="CI-RECEIPT-CAP-001").one()
            customer=db.query(app.Customer).filter_by(
                business_id=merchant_id,wallet_uuid=wallet_uuid).one()
            self.assertEqual(receipt.status,"claimed")
            self.assertEqual(customer.stamps,6)
            stamps=db.query(StampAward).filter_by(
                business_id=merchant_id,operation_key="receipt:"+str(receipt.id)).all()
            self.assertEqual(len(stamps),1)
            self.assertEqual(stamps[0].source,"receipt_visit")

    def test_join_for_nonexistent_firm_fails_closed(self):
        response = self.client.get("/join/987654321")
        self.assertEqual(response.status_code,404,response.text)


if __name__ == "__main__":
    unittest.main()
