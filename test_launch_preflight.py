"""Pure preflight tests: no deployment, secrets, network, or production database."""
import unittest
from unittest.mock import patch
from loial_preflight import validated_public_origin, assert_staging_storage, preflight


class OriginValidationTests(unittest.TestCase):
    def test_staging_cannot_generate_production_qr(self):
        for url in ("https://loial.space", "https://www.loial.space"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validated_public_origin(url, "staging")

    def test_exact_staging_origin_is_accepted(self):
        self.assertEqual(
            validated_public_origin("https://staging.loial.example", "staging"),
            "https://staging.loial.example"
        )

    def test_invalid_origins_are_rejected_not_trimmed(self):
        candidates = (
            "https://staging.loial.example/",
            " https://staging.loial.example",
            "https://staging.loial.example ",
            "http://staging.loial.example",
            "https://evil.example/path",
            "https://user:password@staging.loial.example",
            "https://staging.loial.example?x=1",
        )
        for url in candidates:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validated_public_origin(url, "staging")

    def test_staging_requires_real_volume(self):
        with self.assertRaises(RuntimeError):
            assert_staging_storage("sqlite:////data/loial.db", "staging",
                                   mount_checker=lambda path: False)
        assert_staging_storage("sqlite:////data/loial.db", "staging",
                               mount_checker=lambda path: path == "/data")

    def test_staging_rejects_unmounted_or_wrong_path(self):
        for url in ("sqlite:////tmp/loial.db", "sqlite:////data/../tmp/loial.db",
                    "sqlite:///:memory:"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                assert_staging_storage(url, "staging", mount_checker=lambda _: True)


class LaunchGateTests(unittest.TestCase):
    def base_env(self):
        return {
            "LOIAL_DATABASE_URL": "sqlite:////data/loial.db",
            "JWT_SECRET_KEY": "A7eB9fC2gD3hJ4kL5mN6pQ8rS9tU0vW1xY2zAaBbCcDdEeFf",
            "LOIAL_PUBLIC_ORIGIN": "https://staging.loial.example",
            "ALLOWED_ORIGINS": "https://staging.loial.example",
            "LOIAL_PUBLIC_FREE_PILOT": "1",
            "LOIAL_APPLE_PILOT_ENABLED": "0",
        }

    def test_live_stripe_secret_is_blocked_in_staging(self):
        env = self.base_env()
        env["LOIAL_STRIPE_SECRET_KEY"] = "sk_live_" + "X" * 30
        with patch("loial_preflight.os.path.ismount", return_value=True):
            result = preflight(env, stage="staging")
        self.assertIn("staging_no_live_stripe", result["blockers"])
        self.assertFalse(result["automatic_checks_passed"])

    def test_staging_public_origin_must_not_be_production(self):
        env = self.base_env()
        env["LOIAL_PUBLIC_ORIGIN"] = "https://loial.space"
        env["ALLOWED_ORIGINS"] = "https://loial.space"
        with patch("loial_preflight.os.path.ismount", return_value=True):
            result = preflight(env, stage="staging")
        self.assertIn("staging_origin_isolated", result["blockers"])

    def test_trailing_slash_is_configuration_failure(self):
        env = self.base_env()
        env["LOIAL_PUBLIC_ORIGIN"] += "/"
        with patch("loial_preflight.os.path.ismount", return_value=True):
            result = preflight(env, stage="staging")
        self.assertIn("public_origin_https", result["blockers"])
        self.assertIn("staging_origin_isolated", result["blockers"])

    def test_live_release_never_claims_automatic_approval(self):
        result = preflight(self.base_env(), stage="production")
        self.assertFalse(result["safe_to_deploy_automatically"])
        self.assertIn("device_validation_manual", result["manual_approvals_required"])
        self.assertIn("legal_operator_manual", result["manual_approvals_required"])


if __name__ == "__main__":
    unittest.main()
