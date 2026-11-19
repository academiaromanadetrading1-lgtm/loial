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

## Owner confirmation and production preflight

Owner confirmed the demo account works on 2026-11-19; premium entitlement and commission status were not independently rechecked for that account. Production preflight: live web service, current commit `e35fc310a7c44a8d4a5970794ee9393aac10778c`, existing `/data` volume 500 MB, no staged changes; last three hours 102 HTTP requests, zero 5xx. No production changes performed. Physical checks, administrator credential rotation, fresh verified backup/restore and explicit deployment authorization remain open.

## Superseding account-navigation candidate

Candidate `197833a00532890cba2eaef4e5cd027250a1bab0`; staging deployment `71e3dcc5-d7fb-4e0f-8bc0-5998250e5cfe` SUCCESS. Regression at predecessor `e633fdbdf54cf71bedb83ce6df5065d6a955f4be`: [44490778502](https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44490778502) SUCCESS. Final navigation-only correction validated by [44494131853](https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44494131853): 12/12 synthetic browser role states on desktop and mobile emulation, language order, password tab navigation, client confirmation, credential removal and return to public root. Earlier mobile failures superseded by this pass. These checks do not prove server-side session revocation or real-device compatibility. Prior full regression was not rerun on the final navigation commit. Production backup/restore, credentials and physical devices remain open until evidenced; explicit production authorization required.
