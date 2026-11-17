# Pilot validation — 17 November 2026

## Verified isolated local execution

- Module: loial_plans.py
- Verified Git blob SHA: 43ba013425cf19be55929952e4122727866aee1c
- Exact source reconstructed from connector, verified through git hash-object.
- Local pytest: 16 passed (0.06 seconds).
- Coverage: six tier boundaries, six invalid amounts, three invalid portfolio input sets, mixed paid portfolio.
- Mixed scenario: 55 direct paid accounts, 5 sponsored new accounts, hypothetical 7,065 EUR gross subscription revenue and 1,700 EUR commission.
- No network calls or paid runner used. This is isolated module validation, not integrated application acceptance.

## Outstanding release gates

- Full repository checkout prevented by DNS in local environment; jose dependency not installed.
- Full FastAPI, authorization, financial integration, browser and device tests outstanding.
- Confirm backup and restore, credential rotation, fiscal treatment and legal operator.
- Stripe live and ProBusiness rollout remain disabled pending validation.
- Pilot SEO routes and public UI require integrated smoke tests before deployment.
- No production change or paid service initiated.
