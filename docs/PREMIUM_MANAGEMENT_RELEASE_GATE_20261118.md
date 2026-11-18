# LOIAL premium management — release gate, 2026-11-18

## Verified evidence
- CI run 44220569540 (#526), SHA e35fc310a7c44a8d4a5970794ee9393aac10778c, job 134521095029: success. Logs: 193 isolated tests + one integration test passed; Python compile, inline JS and PWA validation passed.
- Railway production remains on 6e9f86fae8c420faf0f9ff7b1e66d5c0930b7175 (release/loial-specialists-6e9f86f), deployment 6fb968ac-9ba9-494c-aff8-e2dee8821a76 SUCCESS, one running replica, /data mounted, no recent failures or active warnings in 24h status. No staged changes.
- Stripe configuration names absent in current production inventory. AI model configuration names present, not proof of successful real chat. No secret values read.

## Required before paid launch
- Isolated restore of a current backup, verify schema additions and rollback procedure. Do not replace production DB during tests.
- Authenticated browser checks for each specialist, document upload, real AI answers, health snapshot ownership, decision journal, mobile PWA and messaging consent. Use approved bounded AI budget; do not infer live success from CI.
- Dedicated Stripe TEST configuration, checkout, webhook, refund, duplicate and entitlement checks; separate approval for live credentials and charges. Verify operator identity and privacy terms; verify historical credential rotation.
- Device installation and scanning on physical devices, measure realistic pilot load, complete untranslated UI copy. No paid deployment or additional CI without approval.

Status: NOT READY for public paid launch. Production untouched. Prior approval for CI #526 consumed.
