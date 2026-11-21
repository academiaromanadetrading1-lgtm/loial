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
        # Some mounted routers expose an ASGI route wrapper without .path.
        paths = {r.path for r in self.application.app.routes
                 if isinstance(getattr(r,"path",None),str)}
        for path in ("/api/loial-winback/insights",
                     "/api/loial-winback/settings",
                     "/api/loial-winback/campaigns/draft",
                     "/api/loial-winback/campaigns/{campaign_id}/approve",
                     "/api/loial-winback/campaigns/attributions"):
            with self.subTest(path=path):
                self.assertIn(path,paths)

    def test_private_winback_api_denies_anonymous_requests(self):
        for path in ("/api/loial-winback/settings",
                     "/api/loial-winback/insights",
                     "/api/loial-winback/campaigns/attributions"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertIn(response.status_code,(401,403),response.text)
                self.assertEqual(response.headers.get("Cache-Control"),"no-store")

    def test_join_for_nonexistent_firm_fails_closed(self):
        response = self.client.get("/join/987654321")
        self.assertEqual(response.status_code,404,response.text)


if __name__ == "__main__":
    unittest.main()
