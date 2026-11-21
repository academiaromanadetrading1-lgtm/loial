# LOIAL release evidence — 2026-11-21

## Verified on development branch
- Branch: `chatgpt/loial-premium-ui-20261119`
- CI commit: `12b374f5cc554d980d7b12f46850a4272a441cac`
- GitHub Actions: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44892214255
- Isolated pytest: **256 passed**, 2 warnings
- FastAPI isolated database integration: **1 passed**, 6 warnings
- Python compilation, inline JavaScript syntax, PWA helper / manifest checks: success.
- Legacy public customer-presence / customer-status and email-only preferences endpoints: retired (HTTP 410).
- Join card refresh: reads scoped `/api/wallet-profile/{uuid}` with private wallet token; no public UUID-based polling.
- QR image generator: payload length, color and initial validation; request throttling.
- Public QR enrollment: request throttling, bounded field lengths and full UUID.

## Platform state checked on 2026-11-21
- Railway production service `web`: **online**, previously deployed 2026-11-19, with 1 running replica and no reported warnings or recent failures.
- Railway staging `loial-staging`: **sleeping**, prior deployment 2026-11-20.
- These CI commits are **not deployed to production**. Passing CI does not validate the deployed version.

## Release blockers — evidence still missing
1. Deploy reviewed development changes to an isolated staging environment and run API/QR/wallet smoke tests against its actual URL.
2. Confirm a full backup of the real persistent production SQLite data, integrity check and successful restore to an isolated destination; keep a secure off-site copy.
3. Test QR scan, repeated scan, stamping, redemption, wallet recovery and PWA installation on real Android and iOS devices; check offline behavior without promising offline transactions.
4. Validate business access isolation using two live staging accounts and verify token expiration, staff PIN rotation and customer privacy.
5. Validate Stripe test subscriptions end to end, including signed webhook, paid/failed/cancelled/recovered invoices, duplicate events and entitlements. Confirm merchant account, price IDs and tax requirements before charging users.
6. Verify legal operator identity, public legal pages, data retention, GDPR and customer communications. Never invent operator contact or tax identifiers.
7. Review and approve PR, finalize domain/TLS/recovery and perform a controlled production deploy and postdeploy smoke tests.

**Release decision: NO-GO.** Do not present the service as public-launch ready until the blocking evidence is recorded. Free-only pilot still requires checks 1–4, 6–7 and a separate decision to keep checkout disabled.


## 2026-11-21 authentication hardening update
- Verified commit: `40632bce5ec1675a38f4403e5eb422cd822ad980`.
- GitHub Actions: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44894438759
- Isolated tests: **272 passed**; assembled FastAPI integration: **1 passed**.
- Both password-change endpoints enforce 10–72 UTF-8 bytes for new passwords, avoiding bcrypt's silent truncation beyond 72 bytes.
- Login password-change form enforces minimum 10 and maximum 72 characters, with backend byte-length validation authoritative.
- When multiple account models share an email and the supplied old password matches more than one account, the public change-password endpoint now refuses a multi-account password reset (409) instead of mutating all matching accounts.
- CI branch concurrency cancels superseded workflows, limiting redundant runner consumption.

This evidence covers CI only; it **does not** certify the currently deployed production commit or close real-device, billing, storage, legal or recovery testing gates.


## 2026-11-21 customer-data and merchant-messaging gate

- CI-tested commit: `780ea4c1eceec194e0defa0906c0ee96856ff890`.
- Verified run: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44894812288
- Isolated Python suite: **272 passed**; assembled FastAPI integration: **1 passed**.
- The anonymous `/health` probe now uses `SELECT 1` and returns `{"status":"healthy"}` without the count of customers or the SQLite backend identifier.
- The deployed LOIAL inbox installation now requires active billing entitlements before permitting merchant messaging, rather than trusting the mutable `business.plan` label. The global subscription gate can return HTTP 402 before the inbox's own HTTP 403.
- A regression test simulates an unpaid merchant whose display plan is erroneously marked `probusiness`; access remains denied.
- This is source and CI validation **only**: the live Railway production service still runs its previously deployed image. Do not claim the fix is live before a separately approved staged rollout.

**Release remains NO-GO** pending a persistent isolated staging datastore, full device testing, Stripe validation, production backup/restore verification and legal review.


## 2026-11-21 recovery-wallet hardening

- GitHub Actions verified commit `cde3d9f4a8e87b0ceb78cb529e7fe05af7b55de1`.
- Run: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44895098346
- **278** isolated tests passed; **1** assembled FastAPI integration passed.
- Recovery claim destination wallet IDs now require the bounded `W-` identifier format, rejecting URL punctuation and whitespace before consuming a single-use ticket.
- Regression tests confirm malformed destination values cannot migrate a customer or consume the outstanding recovery ticket.
- Recovery page removes its one-use code from the browser address using `history.replaceState` immediately after reading it; no-referrer is retained.
- All changes remain **source-only** on the development branch; production Railway deployment is unchanged.

**NO-GO remains in force** pending isolated persistent staging, real-device verification, live-system backup/restore proof, Stripe validation and legal/operator sign-off.
