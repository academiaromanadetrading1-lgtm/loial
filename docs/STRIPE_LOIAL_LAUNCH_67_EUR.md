# LOIAL / Stripe Billing release checklist — 67 EUR/month
Last updated: 2026-11-17

## Approved architecture
- Merchant subscriptions collected via **dedicated LOIAL Stripe** account and hosted Checkout.
- Price: **EUR 67 monthly**, no VAT added at present (subject to the actual tax status and invoice setup).
- Payment access: provision only after a **signed** `invoice.paid` webhook with the configured LOIAL Price ID, EUR 67 amount and valid service period.
- Renewal success extends paid-through date. `invoice.payment_failed` starts a 3-day grace; after expiry the premium API is blocked. No automatic data deletion.
- `customer.subscription.deleted` or terminal subscription status denies premium access.
- Wise Business is **only** for manual payment of ambassador commissions; no Stripe Connect or automatic affiliate payouts.
- Commission: first genuine paid firm -> EUR 20 direct ambassador + EUR 10 their direct recruiter, once. Further paid periods -> only direct ambassador at EUR 5/10/15 for 1–25/26–50/51+ paid firms that month.
- Stripe invoice IDs and webhook event IDs are deduplicated. Stripe disputes/credit notes hold affected commissions for review.
- Neither Checkout redirect, registration, nor the Stripe subscription 'active' status alone gives access without paid-through evidence.

## Environment variables (secret manager, not Git)
`LOIAL_STRIPE_SECRET_KEY` -- Stripe secret API key for LOIAL, test on staging and live on production
`LOIAL_STRIPE_PRICE_ID` -- recurring monthly EUR 67 price created in the LOIAL Stripe account
`LOIAL_STRIPE_WEBHOOK_SECRET` -- endpoint signing secret
`LOIAL_PUBLIC_ORIGIN=https://loial.space`
Existing `JWT_SECRET_KEY`, `LOIAL_DATABASE_URL`, `ALLOWED_ORIGINS` must remain secure.

Webhook endpoint: `POST https://loial.space/api/loial-stripe/webhook`

Subscribe to these events:
- `checkout.session.completed`
- `invoice.paid`
- `invoice.payment_failed`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `credit_note.created`
- `charge.dispute.created`

## Acceptance checks to run before production merge
1. Create **LOIAL-specific** Stripe test account/products/price, never reuse another project's accounts.
2. Test checkout, redirect, signed webhook and event ordering, including `invoice.paid` before `checkout.session.completed`, duplicates and retries.
3. Confirm 67 EUR billed monthly with no VAT surcharge in intended tax configuration.
4. Verify access paid -> active; failed renewal -> 3-day grace -> deny premium; payment recovery -> restored; canceled -> denied.
5. Verify A/B/C ambassador hierarchy, 20 + 10 one-time, 5/10/15 recurring, refund/dispute holds, and no duplicate commissions.
6. Run full CI, backup+restore SQLite, rotate any historical credentials, test PWA on iPhone and Android.
7. Test with a real small live LOIAL subscription only after business owner explicitly approves and tax/payment details are set.
8. Deploy from tested branch with rollback plan. Do not mark live before these steps are completed.

## Current limitation
The GitHub code and isolated tests are not evidence that a LOIAL Stripe account has been created, that a genuine Stripe checkout has been executed, or that production has been deployed.
