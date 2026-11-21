"""Loial deployment preflight: checks only, does not deploy or transmit secrets.

Example:
 LOIAL_DEPLOY_STAGE=staging python loial_preflight.py
 LOIAL_DEPLOY_STAGE=production python loial_preflight.py

The process returns nonzero for blockers. Google publishing approval still
requires verification in Google Wallet Console; it cannot be inferred from keys.
"""
import json
import os
import re
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Check:
    key: str
    passed: bool
    severity: str
    message: str

def validated_public_origin(value, environment_name=""):
    """Return an exact HTTPS origin, with staging never pointing to production."""
    from urllib.parse import urlsplit
    raw=(value or "").strip()
    if not raw or raw!=raw.rstrip("/") or any(c.isspace() or c in "*\\\\?#" for c in raw):
        raise ValueError("LOIAL_PUBLIC_ORIGIN must be an exact HTTPS origin")
    try:
        parts=urlsplit(raw)
        valid=(parts.scheme=="https" and bool(parts.hostname)
               and parts.username is None and parts.password is None
               and not parts.path and not parts.query and not parts.fragment
               and (parts.port is None or 1<=parts.port<=65535))
    except ValueError:
        valid=False
    if not valid:
        raise ValueError("LOIAL_PUBLIC_ORIGIN must be an exact HTTPS origin")
    if (environment_name or "").lower()=="staging" and parts.hostname.lower() in (
        "loial.space","www.loial.space"):
        raise ValueError("Railway staging cannot issue production QR links")
    return raw


def assert_staging_storage(database_url, environment_name, mount_checker=None):
    """Fail closed only on Railway staging; never probe or touch production data.

    Staging SQLite must live below a real /data mount, not on a disposable
    container filesystem. The Railway environment name is supplied by Railway,
    not by user requests or HTTP headers.
    """
    if (environment_name or "").lower() != "staging":
        return
    checker = mount_checker or os.path.ismount
    path = (database_url or "")[len("sqlite:///"):] if (
        database_url or "").startswith("sqlite:///") else ""
    normalized = os.path.normpath(path) if path else ""
    if not normalized.startswith("/data/") or not checker("/data"):
        raise RuntimeError("LOIAL staging requires persistent isolated SQLite storage mounted at /data")


def preflight(env=None,stage="production"):
    env=dict(os.environ if env is None else env)
    if stage not in ("production", "staging"):
        raise ValueError("Invalid deployment stage")
    strict=stage=="production"
    checks=[]
    def add(key,passed,message,severity="blocker"):
        checks.append(Check(key,bool(passed),severity,message))
    url=env.get("LOIAL_DATABASE_URL","sqlite:////data/loial.db")
    db_isolation=url.startswith("sqlite:///") and ":memory:" not in url
    add("persistent_database",db_isolation,"SQLite database URL configured (not proof of durable storage)")
    if stage=="staging":
        # A SQLite path by itself is not durable on Railway's ephemeral container
        # filesystem. Staging must use the isolated /data volume. ismount()
        # checks the runtime mount, rather than trusting configuration text.
        sqlite_path=url[len("sqlite:///"):] if db_isolation else ""
        isolated_path=(sqlite_path.startswith("/data/") and
                       os.path.normpath(sqlite_path).startswith("/data/"))
        add("staging_durable_volume",isolated_path and os.path.ismount("/data"),
            "Staging SQLite must reside on a mounted, isolated /data volume")
    secret=env.get("JWT_SECRET_KEY","")
    add("jwt_secret",len(secret)>=48 and len(set(secret))>=16
        and not any(x in secret.lower() for x in ("test","demo","example","1234")),
        "Use a fresh random JWT secret (48+ characters; do not reuse previously exposed keys)")
    origins=[x.strip() for x in env.get("ALLOWED_ORIGINS","").split(",") if x.strip()]
    def exact_https_origin(value):
        try:
            parts = urlsplit(value)
            port = parts.port
            return (parts.scheme == "https" and bool(parts.hostname)
                    and parts.username is None and parts.password is None
                    and not parts.path and not parts.query and not parts.fragment
                    and not any(c.isspace() or c in "*\\\\?#" for c in value)
                    and (port is None or 1 <= port <= 65535))
        except ValueError:
            return False
    add("allowed_origins",bool(origins) and all(exact_https_origin(x) for x in origins),
        "Only exact HTTPS allowed origins")
    add("apple_postponed",env.get("LOIAL_APPLE_PILOT_ENABLED","0")!="1",
        "Apple Wallet issuance must stay disabled before the first 100 firms")
    add("google_class_id",bool(re.fullmatch(r"[0-9]{6,}\.[A-Za-z0-9._-]+",
        env.get("LOIAL_GOOGLE_LOYALTY_CLASS_ID",""))),
        "Google Loyalty Class ID configured",severity="warning")
    account_raw=env.get("LOIAL_GOOGLE_WALLET_SERVICE_ACCOUNT_JSON","")
    configured=False
    try:
        acct=json.loads(account_raw)
        configured=(acct.get("client_email","").endswith(".gserviceaccount.com") and
                    "BEGIN PRIVATE KEY" in acct.get("private_key",""))
    except (ValueError,TypeError,AttributeError):
        pass
    add("google_issuer",configured,"Google Wallet issuer service account configured",
        severity="warning")
    add("google_wallet_sync",env.get("LOIAL_GOOGLE_WALLET_SYNC_ENABLED","0")!="1" or configured,
        "Automatic Google card updates require issuer credentials")
    add("no_demo_bootstrap",env.get("LOIAL_DEV_SEED_DATA","0")!="1",
        "Production must never seed demo accounts")
    add("no_plaintext_admin",not env.get("LOIAL_ADMIN_BOOTSTRAP_EMAIL") or
        len(env.get("LOIAL_ADMIN_BOOTSTRAP_PASSWORD",""))>=12,
        "Admin bootstrap credentials must be explicit and strong")
    # Stripe credentials belong to LOIAL, not to another connected project.
    stripe_key=env.get("LOIAL_STRIPE_SECRET_KEY","")
    webhook_key=env.get("LOIAL_STRIPE_WEBHOOK_SECRET","")
    add("staging_no_live_stripe",stage!="staging" or not stripe_key.startswith("sk_live_"),
        "Never configure live Stripe secret keys in staging")
    price_id=env.get("LOIAL_STRIPE_PRICE_ID","")
    origin=env.get("LOIAL_PUBLIC_ORIGIN","https://loial.space").rstrip("/")
    public_free_pilot=env.get("LOIAL_PUBLIC_FREE_PILOT","0")=="1"
    # Free-only public launch can proceed before Stripe credentials exist.
    # Fail closed when credentials are partly set, or live charges requested.
    pro_price_id=env.get("LOIAL_STRIPE_PROBUSINESS_PRICE_ID","")
    multilocation_ready=env.get("LOIAL_MULTILOCATION_READY","0")=="1"
    stripe_values=(stripe_key,webhook_key,price_id,pro_price_id)
    add("pilot_multilocation_disabled",not public_free_pilot or not multilocation_ready,
        "Free pilot must not activate ProBusiness before paid validation")
    add("probusiness_price_distinct",not multilocation_ready or (
        bool(re.fullmatch(r"price_[A-Za-z0-9]{8,}",pro_price_id)) and pro_price_id!=price_id),
        "ProBusiness requires a separate recurring EUR 270 price ID")
    no_stripe_config=not any(stripe_values)
    if public_free_pilot:
        add("free_pilot_stripe_disabled",no_stripe_config,
            "Free-only pilot must not carry partial or active Stripe credentials",
            severity="blocker" if strict else "warning")
    stripe_severity=("warning" if public_free_pilot and no_stripe_config else
                     "blocker" if strict else "warning")
    add("loial_stripe_live_key",stripe_key.startswith("sk_live_") and
        len(stripe_key)>=25,"Use the LOIAL live Stripe secret key only in production",
        severity=stripe_severity)
    add("loial_stripe_webhook",webhook_key.startswith("whsec_") and
        len(webhook_key)>=20,"Configure dedicated LOIAL signed webhook secret",
        severity=stripe_severity)
    add("loial_stripe_price",bool(re.fullmatch(r"price_[A-Za-z0-9]{8,}",price_id)),
        "Dedicated LOIAL recurring EUR 67 price ID required",
        severity=stripe_severity)
    try:
        configured_origin=validated_public_origin(origin,stage)
        isolated_origin=True
    except ValueError:
        configured_origin=""
        isolated_origin=False
    add("staging_origin_isolated",stage!="staging" or isolated_origin,
        "Staging QR links must use an explicit, isolated HTTPS origin")
    add("loial_stripe_return_origin",
        (configured_origin=="https://loial.space" if strict else isolated_origin),
        "Checkout return origin must match production in production and an isolated HTTPS origin in staging",
        severity=stripe_severity)
    add("public_origin_https",exact_https_origin(origin),
        "Public origin must be an exact HTTPS origin")
    add("public_origin_allowed",origin in origins,
        "Public origin must be included in allowed origins")
    # This cannot prove that a previously exposed secret was rotated.
    add("credential_rotation_manual",False,
        "Manually verify historical exposed secrets were rotated before deployment",
        severity="manual")
    add("google_publishing_manual",True,
        "Google Wallet is deferred; independent PWA is launch target",severity="warning")
    add("backup_restore_manual",False,
        "Back up the existing SQLite database and verify an isolated restore",
        severity="manual")
    add("legal_operator_manual",False,
        "Verify operator identity, terms, privacy notice and actual contact channel before commercial launch",severity="manual")
    add("device_validation_manual",False,
        "Validate PWA installation, scanning and independent business authorization on real devices",severity="manual")
    blockers=[c.key for c in checks if not c.passed and c.severity=="blocker"]
    manual=[c.key for c in checks if c.severity=="manual"]
    return {"stage":stage,"safe_to_deploy_automatically":False,
            "automatic_checks_passed":not blockers,
            "blockers":blockers,"manual_approvals_required":manual,
            "checks":[{"key":c.key,"passed":c.passed,"severity":c.severity,
                       "message":c.message} for c in checks]}

if __name__=="__main__":
    stage=os.environ.get("LOIAL_DEPLOY_STAGE","production")
    if stage not in ("production","staging"):
        raise SystemExit("LOIAL_DEPLOY_STAGE must be staging or production")
    report=preflight(stage=stage)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    sys.exit(2 if report["blockers"] else 0)
