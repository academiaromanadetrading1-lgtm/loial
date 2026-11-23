# LOIAL – pilot acceptance and onboarding playbook

Status: **INTERNAL DRAFT – NOT A PUBLIC OFFER**. The pilot may start only after mobile acceptance, privacy/QR checks, verified operational backups and Stripe TEST (last stage, if required for paid pilot).

## First 3 pilot merchants – controlled enrollment

Use invited merchants only. Keep production and staging data separate. Never reuse staging QR cards or passwords in production.

1. Record merchant legal name, store name, industry, contact email, responsible owner, location(s), accepted pilot terms, privacy notice version and consent to be contacted.
2. Owner creates the business account; chooses a unique, non-default staff PIN, reward name and stamp target. Staff receive only the minimum required instructions.
3. Generate merchant enrollment QR and display it at cashier; explain that customers can save a LOIAL PWA card on their phone, with no external Wallet dependency.
4. Customer joins voluntarily, sees the appropriate privacy information and chooses marketing opt-in separately (default should not silently subscribe). A customer who opts out must still receive ordinary loyalty stamps.
5. Staff scan customer QR and issue a stamp only after an eligible purchase. A duplicate scan must not award another stamp. A refunded receipt must follow receipt reversal rules.
6. Owner checks daily totals: enrolled customers, confirmed purchase scans, redeemed rewards, marketing opt-ins and service errors. Never treat projections as actual sales.
7. Owner drafts and explicitly approves any Win-Back campaign. Target only consented customers with **verified visits** and a minimum three-day threshold. A returning customer or opt-out must be removed at approval.
8. After the campaign, show confirmed attributed visits separately from estimated ROI. Do not claim causal incremental revenue without an appropriate comparison group.

## 15-minute cashier training

- **At enrollment:** show the business QR; customer registers their own card and optionally installs the PWA.
- **At purchase:** verify the customer QR is visible and scan using the authorized employee PIN.
- **If scan repeats:** check whether it is a retry of the same purchase; do not force another stamp.
- **If reward unlocked:** redeem it before new stamps when required by the offer.
- **If receipt was canceled:** follow the approved reversal flow; do not manually alter database rows.
- **If phone is replaced:** use the authorized wallet recovery path; public QR is not a private credential.
- **If customer wants no offers:** update consent without removing ordinary loyalty benefits.

## Daily pilot control sheet

| Field | Source | Never report as |
|---|---|---|
| Unique enrolled customers | Actual registration events | Confirmed visits |
| Issued/claimed receipt scans | Verified receipt ledger | Duplicated purchase revenue |
| Stamps | Confirmed staff/receipt operations | Independent financial sales |
| Win-Back recipients | Approved consent-gated deliveries | All clients in campaign draft |
| Attributed returning visits | One confirmed return within 14 days | Proven incremental sales |
| Potential contribution | Ticket and margin assumptions | Accounting profit |
| Incident count | Support log | Marketing conversion |

## Launch blockers and escalation

- **Critical:** merchant-crossed data, unauthorized stamp, broken consent withdrawal, leaked wallet token, double receipt claim, payment access incorrectly granted/revoked.
- **High:** cannot open PWA from home screen, QR incorrectly points to another merchant, approved offer never appears, language change breaks onboarding.
- **Moderate:** alignment, minor translation omissions, visual styling on specific devices.

If a critical issue appears, stop onboarding, record reproducible steps, environment, tested commit, device/browser, timestamps, screenshots with personal data redacted, and rollback reference.

## Acceptance sign-off

| Gate | Evidence |
|---|---|
| Automated regressions | CI green on exact commit |
| Railway staging | SUCCESS, health 200, isolated volume |
| iOS Safari | QR enrollment, PWA install/relaunch, language, stamp |
| Android Chrome | QR enrollment, PWA install/relaunch, language, stamp |
| Privacy | Opt-out, tenant isolation, private wallet access |
| Win-Back | Draft → approval → inbox → verified attribution |
| Financial clarity | Forecast clearly separate from actual transactions |
| Last: Stripe TEST | Test-only payments, lifecycle webhook, access controls |
| Production go/no-go | Explicit owner authorization and rollback plan |

Do not present a pilot signup form as publicly available until acceptance is complete.
