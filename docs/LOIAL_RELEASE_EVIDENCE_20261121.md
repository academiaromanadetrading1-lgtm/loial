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
