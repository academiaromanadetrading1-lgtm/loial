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


def test_exact_https_origin_validation():
    for origin in ("https://", "https://loial.space/path", "https://loial.space?x=1",
                   "https://user@loial.space", "https://loial.space:99999",
                   "http://loial.space", "https://*.loial.space", "https://loial.space#fragment"):
        env=sample_env()
        env["ALLOWED_ORIGINS"]=origin
        assert "allowed_origins" in preflight(env,"production")["blockers"], origin
    env=sample_env()
    env["ALLOWED_ORIGINS"]="https://staging.loial.space"
    assert "public_origin_allowed" in preflight(env,"production")["blockers"]
    env["LOIAL_PUBLIC_ORIGIN"]="http://staging.loial.space"
    assert "public_origin_https" in preflight(env,"staging")["blockers"]


def test_unknown_deployment_stage_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        preflight(sample_env(),"prodution")


def test_staging_rejects_live_stripe_credentials():
    env=sample_env()
    result=preflight(env,"staging")
    assert "staging_no_live_stripe" in result["blockers"]
    assert result["automatic_checks_passed"] is False
    assert result["safe_to_deploy_automatically"] is False


def test_staging_allows_test_stripe_key_without_claiming_launch_approval():
    env=sample_env()
    env["LOIAL_STRIPE_SECRET_KEY"]="sk_test_CI_ONLY_PLACEHOLDER_NEVER_USE_AS_A_KEY"
    result=preflight(env,"staging")
    assert "staging_no_live_stripe" not in result["blockers"]
    assert result["safe_to_deploy_automatically"] is False


def test_public_free_pilot_must_not_use_live_stripe_in_staging():
    env=sample_env()
    env["LOIAL_PUBLIC_FREE_PILOT"]="1"
    result=preflight(env,"staging")
    assert "staging_no_live_stripe" in result["blockers"]
    assert "free_pilot_stripe_disabled" not in result["blockers"]  # warning in staging


def test_staging_fails_closed_without_a_real_data_mount(monkeypatch):
    monkeypatch.setattr("loial_preflight.os.path.ismount", lambda path: False)
    env=sample_env()
    env["LOIAL_STRIPE_SECRET_KEY"]="sk_test_CI_ONLY_PLACEHOLDER_NEVER_USE_AS_A_KEY"
    result=preflight(env,"staging")
    assert "staging_durable_volume" in result["blockers"]
    assert not result["automatic_checks_passed"]


def test_staging_requires_both_isolated_path_and_real_mount(monkeypatch):
    checked=[]
    def mounted(path):
        checked.append(path)
        return path=="/data"
    monkeypatch.setattr("loial_preflight.os.path.ismount", mounted)
    env=sample_env()
    env["LOIAL_STRIPE_SECRET_KEY"]="sk_test_CI_ONLY_PLACEHOLDER_NEVER_USE_AS_A_KEY"
    valid=preflight(env,"staging")
    assert "staging_durable_volume" not in valid["blockers"]
    assert checked==["/data"]
    env["LOIAL_DATABASE_URL"]="sqlite:////tmp/loial.db"
    invalid=preflight(env,"staging")
    assert "staging_durable_volume" in invalid["blockers"]
    env["LOIAL_DATABASE_URL"]="sqlite:////data/../tmp/loial.db"
    escaped=preflight(env,"staging")
    assert "staging_durable_volume" in escaped["blockers"]


def test_production_preflight_does_not_claim_staging_volume_verification(monkeypatch):
    monkeypatch.setattr("loial_preflight.os.path.ismount",
                        lambda _: (_ for _ in ()).throw(AssertionError("unexpected mount check")))
    report=preflight(sample_env(),"production")
    assert "staging_durable_volume" not in report["blockers"]
    assert not report["safe_to_deploy_automatically"]


def test_railway_staging_startup_rejects_ephemeral_sqlite():
    import pytest
    from loial_preflight import assert_staging_storage
    with pytest.raises(RuntimeError,match="persistent isolated SQLite"):
        assert_staging_storage("sqlite:////data/loial.db","staging",lambda _:False)
    with pytest.raises(RuntimeError,match="persistent isolated SQLite"):
        assert_staging_storage("sqlite:////tmp/loial.db","staging",lambda _:True)
    with pytest.raises(RuntimeError,match="persistent isolated SQLite"):
        assert_staging_storage("sqlite:////data/../tmp/loial.db","staging",lambda _:True)
    assert_staging_storage("sqlite:////data/loial.db","staging",lambda path:path=="/data")


def test_railway_production_startup_guard_does_not_probe_staging_mount():
    from loial_preflight import assert_staging_storage
    def forbidden(_):
        raise AssertionError("Production must not be checked as staging")
    assert_staging_storage("sqlite:////data/loial.db","production",forbidden)
    assert_staging_storage("sqlite:////data/loial.db","",forbidden)


def test_public_origin_requires_exact_https_and_isolates_staging():
    import pytest
    from loial_preflight import validated_public_origin
    assert validated_public_origin("https://loial.space","production")=="https://loial.space"
    assert validated_public_origin("https://staging-loial.example","staging")=="https://staging-loial.example"
    for origin in (
        "", "http://staging-loial.example", "https://staging-loial.example/path",
        "https://user@staging-loial.example", "https://*.example",
        "https://staging-loial.example?code=x", "https://staging-loial.example/",
        "https://staging-loial.example:99999", "https://loial.space",
        "https://www.loial.space"
    ):
        with pytest.raises(ValueError):
            validated_public_origin(origin,"staging")


def test_staging_preflight_accepts_its_own_origin_not_production(monkeypatch):
    monkeypatch.setattr("loial_preflight.os.path.ismount",lambda path:path=="/data")
    env=sample_env()
    env["LOIAL_STRIPE_SECRET_KEY"]="sk_test_CI_ONLY_PLACEHOLDER_NEVER_USE_AS_A_KEY"
    env["LOIAL_PUBLIC_ORIGIN"]="https://loial-staging-staging.up.railway.app"
    env["ALLOWED_ORIGINS"]="https://loial-staging-staging.up.railway.app"
    result=preflight(env,"staging")
    assert "staging_origin_isolated" not in result["blockers"]
    assert "loial_stripe_return_origin" not in result["blockers"]
    assert "staging_durable_volume" not in result["blockers"]
    env["LOIAL_PUBLIC_ORIGIN"]="https://loial.space"
    env["ALLOWED_ORIGINS"]="https://loial.space"
    wrong=preflight(env,"staging")
    assert "staging_origin_isolated" in wrong["blockers"]
    assert "staging_durable_volume" not in wrong["blockers"]
