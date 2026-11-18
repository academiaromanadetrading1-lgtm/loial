# LOIAL pilot release gate — 2026-11-18

## Verified
- Production baseline: e35fc310a7c44a8d4a5970794ee9393aac10778c.
- Candidate: e6bc6d3c6536538d919d08ce5795e44df9968f0d, deployed successfully in isolated staging.
- Git comparison: 13 commits ahead, 0 behind, 14 changed files.
- Automated suite: 203 tests passed on predecessor 86e9bf5; https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44325777195.
- Live staging acceptance: https://github.com/academiaromanadetrading1-lgtm/loial/actions/runs/44341256957, SUCCESS: merchant/admin/ambassador authentication, manual Business grant/revoke, QR receipt and payment approval, reprint, duplicate rejection, tenant isolation, CRM segment, inbox offer, retry, reaction, opt-out, refund. Synthetic data only.

## Required before production change
- Verify production current source, persistence and backup/restore procedure. Take a consistent database backup; do not copy production secrets to staging or logs.
- Mobile acceptance: Android Chrome and iOS Safari where available; install card shortcut, scan printed claim URL, enroll, return to receipt, confirm payment with employee device, inspect wallet and Inbox. Reject duplicate/wrong employee/other business. Document actual devices and results.
- Printer acceptance: use a real merchant print-system integration or manual QR print, confirm readable size and same QR on reprint. Vendor-specific integrations remain unvalidated; don't claim universal compatibility.
- Confirm pilot commercial copy reflects actual module availability; no paid activation until billing separately validated. AI, OCR and physical printer integrations are not implicitly certified by these API tests.
- Obtain explicit production deployment approval. Do not merge acceptance runner or its trigger into production merely to deploy the candidate.

## Deployment and rollback
- Deploy only the tested candidate SHA after confirming environment ID, current source, and persistent mount /data. Keep private production variables intact.
- Health check, login and non-destructive public smoke checks; observe logs for migrations and HTTP errors.
- If checks fail, redeploy baseline SHA e35fc310a7c44a8d4a5970794ee9393aac10778c. Code rollback is not database rollback; inspect schema compatibility. Restore a verified backup only if necessary and with explicit approval, accounting for intervening writes.
- Remove temporary GitHub QA secret when staging automation no longer needs it and rotate test credentials. Never publish real passwords.
- No launch-ready declaration until release gates are evidenced.
