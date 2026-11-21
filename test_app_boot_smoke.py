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

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
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

    def test_join_for_nonexistent_firm_fails_closed(self):
        response = self.client.get("/join/987654321")
        self.assertEqual(response.status_code,404,response.text)


if __name__ == "__main__":
    unittest.main()
