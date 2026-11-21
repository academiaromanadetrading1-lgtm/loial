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


## 2026-11-21 refund concurrency and recovery throttling

- CI verified revision `1f3ee4b5831d55043a583c45e16eb43c60076103`: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44898136022
- **287** isolated tests passed; **1** assembled FastAPI integration passed.
- Refunding the latest loyalty receipt now uses a conditional SQL update that only reverses the expected current stamp balance. When the balance changes before the write, the receipt is refunded financially but the loyalty reversal is withheld for manual review; this avoids overwriting a newer customer balance.
- Tests cover exactly-once refund ledger recording, duplicate refund idempotence, and an injected concurrent customer balance change immediately before the conditional UPDATE.
- Legacy wallet recovery endpoints now have application-enforced SlowAPI rate limits: eligible 60/min, ticket requests 5/min, previews 30/min, claims 15/min. The isolated test verifies a sixth ticket request is rejected with HTTP 429.
- The Railway staging environment remains without any volume mounts; source-only improvements are not proof of a durable deployed service. Railway production remains online on the previous deployment.

**Public launch remains NO-GO**. Do not deploy staging without confirming durable isolated storage, and do not deploy production without a verified backup/restore, operational Stripe checks, device tests and legal sign-off.


## 2026-11-21 smart receipt race condition hardening

- Verified development commit: `69b79ded26e12819d518a715c30e2afef1d230d2`.
- GitHub Actions: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44898750153
- Isolated test suite: **289 passed**, FastAPI integration: **1 passed**.
- A staff's smart receipt payment approval is now consumed only by a conditional database UPDATE whose WHERE clause includes the approval's unexpired timestamp. The earlier in-memory expiry precheck remains as an early rejection.
- An awaiting-payment receipt is now reserved only if its expiration still holds during the conditional database UPDATE.
- Independent regression tests simulate expiration immediately before each atomic transition, verifying no unintended receipt claim, staff confirmation or loyalty stamp.
- Railway production was checked online on deployment `1bdeabfe-dc4b-473f-8b66-f3d19137feeb`, untouched by these commits. Staging remains sleeping, with no mounted volume. The isolated CI database is not a substitute for real staging verification.

**Release decision: NO-GO** until durable isolated staging storage, restore-tested backup, Stripe checkout/webhooks, real-device PWA/QR flows, and legal/operator approval are completed.


## 2026-11-21 receipt API throttling

- Verified source revision: `96866b05a1417aa8805799726ce0447356674490`.
- CI: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44899297357
- **290 isolated tests passed**; full FastAPI integration **1 passed**; Python compile, JavaScript and PWA validation passed.
- Receipt QR endpoints have enforced application rate limits when wired to the installed SlowAPI limiter: anonymous preview 30/min, private claim 20/min, reservation 20/min, payment status 60/min, merchant issue 30/min, merchant refund 20/min. The existing staff payment confirmation limit of 20/min and integration issuance of 120/min remain.
- An isolated FastAPI test makes 30 public receipt preview requests followed by the 31st and verifies HTTP 429. This is an application-layer abuse-control regression; real proxy and shared multi-instance behavior still requires operational testing.
- Railway production remains on the unchanged prior deployment. Staging has **no persistent volume** and should not be redeployed onto an ephemeral SQLite path.

**Public release remains NO-GO** pending real staging storage/rollout, verified backup restoration, Stripe payment/webhook tests, mobile QR/PWA checks and operator/legal sign-off.


## 2026-11-21 merchant JWT scope hardening

- CI tested revision: `be701706176a64517650b011e26260bc4fc098cc`; GitHub Actions: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44900256205
- **290** isolated tests passed and **1** assembled FastAPI integration passed, including JavaScript/PWA validation.
- Direct merchant settings and employee routes now share a business-only JWT validator. It checks `role=business`, account existence and the optional `business_id` claim; an identical email on a customer or other account role is insufficient authorization.
- The administrator's primary staff PIN rotation route was aligned with the same validator following an integration regression that exposed missing `business_id` scope enforcement.
- Regression coverage confirms forged alternate role or mismatched merchant scope cannot read merchant details, list/add staff, modify settings or rotate the business PIN.
- Production Railway remains online at the prior deployment, with no new code installed. Railway staging remains sleeping without persistent volume. No volume was created and no live database modified.

**Release status: NO-GO.** Staging durable storage creation/attachment remains an explicit approval-required infrastructure change due to possible cost and redeployment; backup/restore, Stripe, device and legal/operator checks remain pending.


## 2026-11-21 PIN collision and cross-merchant staff isolation

- Verified source revision `fe87618e13372fd66b5f89ac6ba7ca553fe8d520`.
- CI: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44901290883
- Isolated Python tests **290 passed** and assembled FastAPI integration **1 passed**; Python compilation, inline JavaScript and PWA checks passed.
- Manually setting a merchant's primary staff PIN now refuses any PIN assigned to an active employee of the same merchant (HTTP 409). The primary PIN remains unchanged after the rejected attempt.
- Cross-merchant regression tests exercise employee deactivation attempts by another Business JWT, including the direct business-ID route. The foreign request leaves the protected employee active; only the real business owner can deactivate it.
- Railway production remained online at `1bdeabfe-dc4b-473f-8b66-f3d19137feeb`; staging remains sleeping without persistent volume. No deployment or volume mutation was performed.

**Release decision: NO-GO** until persistent isolated staging, backup and restore, paid billing validation, on-device PWA/QR trials and legal/operator review are completed.


## 2026-11-21 staging storage deployed; backup validation strengthened

- Staging received its own 500 MB persistent SQLite volume, loial-staging-sqlite (ID 8a041c39-3f75-42d5-b1be-a21e9e0eeb36), mounted at /data only in the staging environment. Database URL: sqlite:////data/loial.db. Dedicated public and allowed origin: https://loial-staging-staging.up.railway.app.
- Staging deployment 8479fe18-8589-461b-a004-17e0ad09002b completed SUCCESS with /health HTTP 200, on source e04648a8cd8daf043fae1587e7b1accff57da999. Railway later reports sleeping due to idle policy, volume still attached, no warnings/criticals.
- Production remains on deployment 1bdeabfe-dc4b-473f-8b66-f3d19137feeb, not redeployed or reconfigured.
- Backup helper now rejects empty SQLite source databases and isolated restores with no application tables or broken foreign-key relationships; retains overwrite prevention.
- CI revision e349ce80965d1082349219f37f572cca5bc3886c passed 292 isolated tests and 1 full FastAPI integration. https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44902572553
- CI fixtures do not prove a real staging/production backup or persistence across restart; no legacy ephemeral data migration was verified.

Public release NO-GO until isolated real backup/restore, billing verification, mobile QR/PWA tests and legal/operator acceptance are completed.

## 2026-11-21 operational LOIAL backup schema validation

- CI tested revision d3d03d8516fe1c1ee644edcc43cc6f3cb8764334; https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44903302657
- All **296 isolated Python tests** passed and **1 assembled FastAPI integration** passed.
- The operational backup CLI requires genuine core LOIAL tables AND minimum key columns (business_accounts, customers, users, loial_stamp_awards). An unrelated or structurally incomplete but otherwise valid SQLite file now fails. The generic SQLite option is explicit and only for test fixtures.
- The disposable test suite checks strict acceptance, absence of output on failure, and CLI fail-closed behavior. This does NOT certify any real staging/production backup.
- A separate staged maintenance runbook was created: docs/LOIAL_STAGING_BACKUP_RESTORE_RUNBOOK.md. Real backup, encrypted off-volume copy and independent restoration are NOT yet verified.
- Staging Railway volume remains attached (service idle-sleeping); production has not been modified.

Public launch remains NO-GO while real restore, Stripe billing, device testing and legal/operator sign-off remain open.

## 2026-11-21 cross-model merchant login isolation

- Verified commit 3e5633dd7bac1096a18f32addf1f115c34062af7, CI: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44903733608
- The shared /auth/login endpoint can no longer emit a Business token through a legacy User row with the same email and business role. Business tokens are minted only after actual BusinessAccount authentication. A matching SalesAgent row likewise cannot provide a BusinessAccount identity.
- Integration regression creates a separate User row with an identical merchant email, proves the legacy password cannot log in as a merchant, and proves that the actual merchant password still yields a scoped Business JWT.
- CI: 296 isolated tests PASS, 1 complete FastAPI integration PASS; JavaScript/PWA checks PASS.
- Production unchanged. Staging has a persistent volume but is in sleep state and remains on the earlier deployed commit; no live deployment was attempted.
- Public launch NO-GO until real operational backup/restore, payment/Stripe verification, real mobile PWA/QR testing and legal/operator sign-off.
