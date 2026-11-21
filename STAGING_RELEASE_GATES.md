# LOIAL – Release gates (staging only)

Current objective: validate customer and merchant experiences without touching production. **Stripe is the last stage**, only after product and mobile acceptance. Automated tests are necessary but insufficient for public launch.

## Automated acceptance

- Run GitHub Actions: `LOIAL security regressions`; require green for exact candidate SHA.
- Require Python unit/integration security tests, Node QR/PWA/language tests and inline JS checks to pass.
- Pin staging to the same reviewed Git SHA. Verify Railway deployment `SUCCESS`, `/health` 200, startup without errors.
- Verify production commit, environment and `/data` volume remain unchanged.

## Physical acceptance (user-owned iOS and Android devices)

1. Business: register a **test-only** business on staging; choose a non-default employee PIN. Open the enrollment QR and inspect company details.
2. iPhone Safari: scan enrollment QR, create a customer card, choose marketing consent explicitly, add wallet to Home Screen, launch from icon, switch EN -> RO -> EN.
3. Android Chrome: repeat enrollment with another test customer, install PWA using browser menu/prompt, relaunch from icon and switch EN -> DE -> HU.
4. Staff: use valid PIN to grant a stamp, verify the stamp is visible after wallet reload. Scan again with the same idempotency token and verify no double credit. Invalid PIN must not grant stamps.
5. Merchant isolation: a second test business must not access the first business's customers, campaigns or attribution metrics.
6. Marketing consent: opt out after preparing Win-Back draft. Approval must not deliver to the opted-out client. Re-enrollment is not a verified visit.
7. Win-Back: use only **synthetic staging data** with a confirmed stamp/receipt at least four days old and a configured three-day threshold. Prepare draft, approve, see inbox offer, scan customer again, and verify exactly one confirmed post-campaign attribution. A refund/redeem bookkeeping event must not count as a new visit.
8. Financial reporting: ensure simulated potential contribution is marked forecast, while confirmed visits do **not** claim verified revenue or proven incrementality.
9. Verify no personal business/customer data is in service-worker caches; test logout/reopen and wallet recovery on both devices.

## Last step: Stripe TEST

Only after all the above pass: configure **staging-only** `LOIAL_STRIPE_SECRET_KEY`, `LOIAL_STRIPE_WEBHOOK_SECRET`, `LOIAL_STRIPE_PRICE_ID` (and ProBusiness price only when approved). Use `/api/loial-stripe/webhook`. Turn off `LOIAL_PUBLIC_FREE_PILOT` only in staging for payments testing. Verify test-key checkout, signed paid-invoice activation, duplicate webhook idempotency, failed invoice and cancellation. Never paste live secrets into tickets or chat.

## Public release decision

**NO-GO** until all required physical checks and Stripe TEST pass, no unresolved critical issues remain, and the production deployment is explicitly authorized. Record tested commit, devices/browser versions, test results and final production rollback checkpoint.
