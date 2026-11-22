# LOIAL — product and go-to-market operating rules (22 Nov 2026)

Internal product direction approved by the owner. These guidelines are decision constraints, **not independently verified market research**, valuation certification, or a guarantee of future revenue.

## Positioning and ideal customer

- Sell **repeat visits, measurable win-back and merchant retention**, not a consumer discount/coupon app.
- Initial target: independently operated businesses with **1–5 locations**. Avoid enterprise integrations and bespoke SAP/legacy POS projects during the initial pilot.
- Priority verticals: beauty/barber salons, automotive services/detailing, dental/veterinary clinics. Consider HoReCa when ticket size, repeat purchase frequency and contribution margin support the subscription.
- Sales framing: show merchant how much contribution a *confirmed* returning customer may generate. Label forecasts as assumptions; avoid presenting attributed visits as proven causal uplift.

## Rollout sequence

1. **Romania**: begin with controlled pilots in Timișoara/Giroc; expand only after paying merchant retention is demonstrated. Potential second cities: București, Cluj, Iași, Brașov.
2. **CEE**: consider Hungary and Poland after Romanian unit economics and translations have been validated with real users.
3. **DACH**: Germany and Austria only after legal/compliance, localization and support capacity are assessed.

Nine supported UI languages (RO, EN, DE, FR, IT, ES, NL, PL, HU) do not by themselves establish market fit or production-readiness.

## Acquisition channels

- Test direct merchant acquisition against partners who already serve the ideal customer: independent sales agents, accountants, salon/auto suppliers, and local marketing freelancers.
- Ambassador recruitment should be based on traceable referred **paying** merchants, not signup counts. Verify all referral accounting and consent rules before public activation.
- Focus metrics: qualified demos, activation to verified first purchase, paid conversion, acquisition cost, monthly recurring revenue (MRR), net new MRR, paid merchant retention/churn, verified reactivation rate, contribution margin and support burden.

## Product and launch constraints

- Keep customer access simple: browser/PWA, no mandatory App Store or Google Wallet installation.
- Default UI language: **English**; allow change before and after authentication. A setting should persist correctly and not expose another merchant's data.
- Privacy: private device credentials required for private wallet access; marketing consent remains explicit, merchant-specific, reversible; all tenant data isolated.
- Merchant plans assumed in current product model: Business **€67/month**, ProBusiness **€270/month**; do not advertise or accept payments until billing is fully verified.
- Product scope remains repeat purchase ledger, unique receipt QR, staff stamp/reward, CRM/Win-Back, private inbox, clear merchant metrics and controlled ambassador program.
- **Stripe is the final technical integration/acceptance step** after core product and real iOS/Android pilot tests. Never deploy to production without explicit owner authorization, backed-up data, rollback and go/no-go sign-off.

## Valuation scenarios — not established transaction prices

Treat the following as **owner-supplied planning hypotheses only**; they are not independently substantiated values or accepted SaaS valuation multiples:

| Scenario | Merchants and target MRR | Owner-supplied hypothetical value |
|---|---|---|
| Pre-revenue | No verified recurring revenue | €25,000–€60,000 |
| Early validation | 30 paying × €67 = €2,010 MRR | €80,000–€120,000 |
| Local traction | 250 mixed-price merchants; circa €20,000 MRR | €700,000–€1,100,000 |
| Regional scale | 1,500+ mixed-price merchants; circa €120,000 MRR | €4,500,000–€7,000,000 |

No forecast should be described as ARR/MRR achieved, a purchase offer, verified market value, or incremental causal revenue. Revise projections when paid cohorts, CAC, gross margin, churn and actual cohort retention exist.

## Pilot launch decision

Block launch on failed automated tests, mobile QR/PWA behavior, merchant data separation, consent, staff fraud controls, unavailable rollback, missing legal/privacy disclosures or Stripe TEST failures at the final stage. Require owner review of actual iPhone and Android operation and production go/no-go sign-off.
