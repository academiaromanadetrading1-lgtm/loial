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

@dataclass(frozen=True)
class Check:
    key: str
    passed: bool
    severity: str
    message: str

def preflight(env=None,stage="production"):
    env=dict(os.environ if env is None else env)
    strict=stage=="production"
    checks=[]
    def add(key,passed,message,severity="blocker"):
        checks.append(Check(key,bool(passed),severity,message))
    url=env.get("LOIAL_DATABASE_URL","sqlite:////data/loial.db")
    db_isolation=url.startswith("sqlite:///") and ":memory:" not in url
    add("persistent_database",db_isolation,"SQLite persistent database configured")
    secret=env.get("JWT_SECRET_KEY","")
    add("jwt_secret",len(secret)>=48 and len(set(secret))>=16
        and not any(x in secret.lower() for x in ("test","demo","example","1234")),
        "Use a fresh random JWT secret (48+ characters; do not reuse previously exposed keys)")
    origins=[x.strip() for x in env.get("ALLOWED_ORIGINS","").split(",") if x.strip()]
    add("allowed_origins",bool(origins) and all(
        x.startswith("https://") and "*" not in x for x in origins),
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
    price_id=env.get("LOIAL_STRIPE_PRICE_ID","")
    origin=env.get("LOIAL_PUBLIC_ORIGIN","https://loial.space").rstrip("/")
    public_free_pilot=env.get("LOIAL_PUBLIC_FREE_PILOT","0")=="1"
    # Free-only public launch can proceed before Stripe credentials exist.
    # Fail closed when credentials are partly set, or live charges requested.
    stripe_values=(stripe_key,webhook_key,price_id)
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
    add("loial_stripe_return_origin",origin=="https://loial.space",
        "Checkout return URLs restricted to https://loial.space",
        severity=stripe_severity)
    # This cannot prove that a previously exposed secret was rotated.
    add("credential_rotation_manual",False,
        "Manually verify historical exposed secrets were rotated before deployment",
        severity="manual")
    add("google_publishing_manual",True,
        "Google Wallet is deferred; independent PWA is launch target",severity="warning")
    add("backup_restore_manual",False,
        "Back up the existing SQLite database and verify an isolated restore",
        severity="manual")
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
