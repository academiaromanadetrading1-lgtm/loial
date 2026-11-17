"""No-credential preflight regression checks; never touches production."""
import json
from loial_preflight import preflight

def sample_env():
    return {
        "LOIAL_DATABASE_URL":"sqlite:////data/loial.db",
        "JWT_SECRET_KEY":"aBcDeFgHiJkLmNoPqRsTuVwXyZ9876543210!#$%*_+-abcdefghi",
        "ALLOWED_ORIGINS":"https://loial.space",
        "LOIAL_APPLE_PILOT_ENABLED":"0",
        "LOIAL_GOOGLE_LOYALTY_CLASS_ID":"123456789012.loial_pilot",
        "LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON":json.dumps({
            "client_email":"pilot@loial-project.iam.gserviceaccount.com",
            "private_key":"-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----"
        }),
        "LOIAL_GOOGLE_WALLET_SYNC_ENABLED":"0",
        "LOIAL_STRIPE_SECRET_KEY":"sk_live_CI_ONLY_PLACEHOLDER_NEVER_USE_AS_A_KEY",
        "LOIAL_STRIPE_WEBHOOK_SECRET":"whsec_CI_ONLY_PLACEHOLDER_NEVER_USE",
        "LOIAL_STRIPE_PRICE_ID":"price_LOIALCI2026",
        "LOIAL_PUBLIC_ORIGIN":"https://loial.space",
        "LOIAL_DEV_SEED_DATA":"0"
    }

def test_preflight_remains_manual_even_when_config_seems_ready():
    report=preflight(sample_env(),stage="production")
    assert report["automatic_checks_passed"] is True
    assert report["safe_to_deploy_automatically"] is False
    assert "credential_rotation_manual" in report["manual_approvals_required"]
    assert "backup_restore_manual" in report["manual_approvals_required"]

def test_missing_google_does_not_block_pwa_launch():
    env=sample_env()
    env.pop("LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON")
    env["LOIAL_GOOGLE_LOYALTY_CLASS_ID"]=""
    assert "google_issuer" not in preflight(env,"staging")["blockers"]
    assert "google_issuer" not in preflight(env,"production")["blockers"]
    assert "google_class_id" not in preflight(env,"production")["blockers"]

def test_missing_stripe_blocks_public_launch_but_not_staging():
    env=sample_env()
    for key in ("LOIAL_STRIPE_SECRET_KEY","LOIAL_STRIPE_WEBHOOK_SECRET",
                "LOIAL_STRIPE_PRICE_ID"):
        env.pop(key)
    checks=preflight(env,"production")
    assert {"loial_stripe_live_key","loial_stripe_webhook",
            "loial_stripe_price"}.issubset(checks["blockers"])
    assert "loial_stripe_live_key" not in preflight(env,"staging")["blockers"]

def test_apple_and_weak_secrets_cannot_pass_launch_checks():
    env=sample_env()
    env["LOIAL_APPLE_PILOT_ENABLED"]="1"
    env["JWT_SECRET_KEY"]="demo"
    env["ALLOWED_ORIGINS"]="*"
    env["LOIAL_DEV_SEED_DATA"]="1"
    result=preflight(env,"production")
    for key in ("apple_postponed","jwt_secret","allowed_origins","no_demo_bootstrap"):
        assert key in result["blockers"]

def test_preflight_does_not_return_private_keys():
    env=sample_env()
    private=env["LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON"]
    output=json.dumps(preflight(env,"production"))
    assert private not in output
    assert "FAKE" not in output

def test_free_only_public_pilot_can_prepare_without_stripe_but_not_with_partial_keys():
    env=sample_env()
    for key in ("LOIAL_STRIPE_SECRET_KEY","LOIAL_STRIPE_WEBHOOK_SECRET",
                "LOIAL_STRIPE_PRICE_ID"):
        env.pop(key)
    env["LOIAL_PUBLIC_FREE_PILOT"]="1"
    free=preflight(env,"production")
    assert free["automatic_checks_passed"]
    assert "loial_stripe_live_key" not in free["blockers"]
    assert free["safe_to_deploy_automatically"] is False
    env["LOIAL_STRIPE_PRICE_ID"]="price_accidental_partial"
    partial=preflight(env,"production")
    assert "free_pilot_stripe_disabled" in partial["blockers"]
