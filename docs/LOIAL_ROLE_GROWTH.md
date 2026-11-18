# LOIAL — role-specific value and organic growth (approved direction)

Preserve the existing public simulators, including their interaction and visual design. Do not replace compensation rules with a new calculator formula. Use the existing authoritative revenue commission rules (first paid month 20 EUR direct where eligible; subsequent paid months 5/10/15 EUR by verified rank; existing sponsor rules separately). Simulations are hypothetical, not cash balances or guarantees.

## Merchant
FREE registration without payment; show available actions and clearly locked premium actions, explain the specific benefit when clicked. Server-side entitlement checks are authoritative; never substitute UI locks for authorization. Reuse the actual plan catalog. Contextual guidance: setup reward, print QR, train staff, first valid scan, near verified customer cap, inactive customers, campaign eligibility, multi-location needs. Recommend one useful next action rather than repeated upgrade banners. No ROI claim without input assumptions; distinguish simulated from verified sales and gross margin from revenue.

## Client
Show card progress, available rewards, inbox preferences and the next practical action. Invite the client to share a distinct merchant recruitment QR (not the public wallet identity QR and not the friend-referral QR). Explain compensation eligibility and show existing simulator. No spam, no automatic contacts upload. First attributed merchant registration promotes the client to ambassador status through an idempotent server transaction; preserve attribution and require secure identity verification/acceptance of terms before activating authenticated access. No automatic financial entitlement merely from signup. Pay only under existing verified revenue rules; payout setup separate.

## Ambassador
Display registered vs paying firms, verified commissions vs simulations, next rank criteria from actual commission rules, referral link/QR and practical actions for recruiting firms. Provide role-specific sales scripts by industry, demonstration walkthrough, follow-up guidance; no unsolicited bulk messaging. Existing commission engine remains the source of truth.

## Implementation and acceptance
1. Audit existing UI and backend plan gates and simulator; preserve functional behavior.
2. Deterministic role-based guidance from permissioned data; static fallback without paid AI. For AI chat, separate role context and data scopes, no cross-tenant or wallet leakage.
3. Add merchant recruitment attribution distinct from friend referrals. Test replay, self-referral, existing account collision, concurrent registration and no commission on free signup. Never create account credentials in URLs.
4. Add contextual CTA and accessible locked controls; mobile and desktop checks for each role. Verify FREE cannot call premium APIs directly.
5. Validate existing plan pricing, commission outputs and conversion paths against authoritative code. No additional CI or deployment without authorization.
6. Keep this work isolated from the previously accepted release until regression checks pass.
