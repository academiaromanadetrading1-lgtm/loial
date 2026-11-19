# LOIAL pilot release gate — 2026-11-19

Candidate: `92acc280f2d7f6ac60563fc901ab7f96f69a82eb` (growth branch).
Staging deployment: `c0615e87-e0a4-413c-9af6-fae0005ca3d6` SUCCESS.
Production is not changed by this record.

## Evidence

- [Regression run 44482393402](https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44482393402): 211 isolated tests and one full app integration test passed; Python compilation, inline JS syntax, PWA manifest checks passed.
- [Founders acceptance 44485762837](https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44485762837): public landing, gallery, capacity, superadmin authorization, consent, public data minimization, stable slots and removal passed.
- [Browser acceptance 44487158943](https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44487158943): Chromium desktop and Pixel 7/iPhone 13 emulation, public landing, active simulator, gallery, responsive width, superadmin dashboard, logout, enrollment, card and inbox passed.
- Earlier staging acceptance covered QR receipt claim/settlement, refunds, consent and CRM; these are not a physical printer or external payment test.

## Remaining gates

1. Provision an isolated demonstration merchant with private password entry; grant premium manually, not through a fake paid invoice. Verify login, premium status and no commissions. Staging has ephemeral storage; do not use it for real customers or sensitive documents. Never commit passwords or place them in workflow logs. AI external calls remain disabled by budget policy.
2. Actual Android and iPhone install/open/scan and a real merchant printer workflow. Browser emulation does not establish physical camera and printer compatibility.
3. Before production, obtain explicit approval, rotate exposed administrator credentials, obtain a fresh database backup and verify restore in isolation. Preserve the /data production volume. Confirm only the production service source commit is changing; keep current image/source as rollback target.
4. After approved deploy, verify health, public landing, admin access and existing merchant data without synthetic mutations in production. Roll back if integrity or access fails. Stripe payment activation requires separate validation and authorization; initial release is a free pilot.

No live billing, real customer data, paid AI calls or production changes are authorized by this record. Founders are allocated by verified approval order; fictitious demonstration tiles are explicitly identified, never represented as genuine members.
