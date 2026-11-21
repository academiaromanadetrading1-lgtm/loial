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


## 2026-11-21 canonical universal wallet alias regression
- Tested revision: `471d7bdb6eec7463f9fed7a62ab180dc7beb2e5c`.
- CI: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44895711773
- Isolated tests: **281 passed**; FastAPI integration: **1 passed**.
- Customer enrollment now resolves merchant-specific card identifiers to the canonical `wallet_uuid` before checking the private device token. This prevents rejecting legitimate re-enrollment or silently returning no token when a user presents a valid business-specific card ID.
- Regression exercises a universal wallet enrolled across three separate businesses, authorized alias retry, unauthorized alias retry and correct per-business wallet association.
- Railway production remains on its existing deployment; staging remains sleeping with **no persistent volume**. No production changes or real-customer data operations were performed.

**NO-GO** for public launch remains until staging storage, field device tests, real backup/restore, payment integration and legal checks have been verified.


## 2026-11-21 atomic stamp and receipt transitions

- Verified run: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44896387211
- Tested revision: `f4fd67a66fc8b8c63d5a2d78a5cfd29ab9494cf2`.
- Isolated tests: **282 passed**; full assembled FastAPI integration: **1 passed**.
- Universal manual scan now increments the current customer stamp counter using a bounded SQL conditional update; it no longer overwrites a potentially stale ORM counter under concurrent requests. A regression exercise reaches the reward limit exactly and refuses an excess scan.
- Receipt claiming now checks the original ticket expiration in the same conditional SQL update that switches its state to claimed. The test moves simulated time across the expiry between the preliminary check and atomic transition and confirms the receipt remains unclaimed and no stamp is recorded.
- Production Railway was verified online on its prior deployment; the latest source revision has NOT been deployed.
- Staging still lacks its required persistent volume; DO NOT bypass the staging boot guard or proceed with a pilot there until persistent isolated storage is confirmed.

**Release decision: NO-GO**; additional real-device, payment, backup/restore, staging isolation, and legal checks remain mandatory.


## 2026-11-21 atomic reward redemption and receipt URL privacy
- Verified source revision: `c4a741d6c068cc2a3cc02aaa5a4b6f5d50fbafc6`.
- CI: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44896790778
- Isolated tests: **283 passed**. Assembled FastAPI integration: **1 passed**. JavaScript and PWA syntax checks also passed.
- Reward redemption uses an atomic conditional UPDATE of the customer's stamp counter. A second attempt to consume the same unlocked reward receives HTTP 409; the first is audited exactly once.
- One-use receipt claim tokens are read on page load and removed from the visible browser URL and history with `history.replaceState`, maintaining the existing in-memory claim flow.
- Railway production remains on its earlier release and staging remains sleeping without a persistent volume. These changes were not deployed.

**Public release status: NO-GO.** Durable staging, real-data backup/restore, paid Stripe testing, real-device PWA/QR checks and legal/operator approval remain outstanding.


## 2026-11-21 QR origin and staging isolation

- CI-tested revision: `878f39dbd40f37f2e57c478e93c6edd08f19ef58`.
- GitHub Actions: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44897403616
- Python isolated tests: **285 passed**; assembled FastAPI integration: **1 passed**.
- `validated_public_origin` rejects missing, malformed, wildcard, userinfo, HTTP or non-root HTTPS origins. Railway staging is forbidden from silently pointing QR links to `loial.space`.
- Receipt QR issuance consumes the validated per-environment HTTPS origin rather than the raw environment variable.
- Staging startup refuses a missing or production origin; production launch checks still demand the exact official production origin.
- Preflight accepts a dedicated staging checkout-return origin instead of incorrectly requiring `https://loial.space` in every environment.
- Production Railway remains **online on the prior deployment**. Staging remains **sleeping without a persistent volume**. These changes were not deployed.

**Release status: NO-GO.** Dedicated durable staging storage, hands-on QR/PWA device tests, Stripe staging verification, verified production backup/restore and legal/operator sign-off remain outstanding.
