# LOIAL staging deployment safety gate (2026-11-21)

## Observed Railway state
- Project `outstanding-stillness`, environment `staging`, service `loial-staging`.
- Source: `academiaromanadetrading1-lgtm/loial`, branch `chatgpt/loial-premium-ui-20261119`.
- Current staging source commit is older than verified development commits.
- Service is configured with `sleepApplication: true`.
- **No Railway volume is mounted** on staging, as confirmed through the Railway environment and service inventory.
- The application uses SQLite; its default database URL is `sqlite:////data/loial.db`. A path alone is not evidence of durable mounted storage.
- Service has a generated Railway domain, but public HTTP accessibility was not established in this inspection.

## Safety consequence
Staging must **not** be used for durable pilot customers or live financial records until the database path is confirmed to be on persistent storage. Redeploying or sleeping a container must not be assumed to preserve its filesystem.

## Deployment checklist
1. Confirm staging contains no data that must be retained. Export any existing data before changes.
2. Provision and attach a dedicated **staging-only** persistent volume, mounted at `/data`, or use a separately provisioned durable database. Never attach the production volume.
3. Verify `LOIAL_DATABASE_URL` points to this staging location without publishing its secret value.
4. Confirm independent staging JWT secret, no production Stripe keys, no production webhook, demo seed off, and valid staging origin allowlist.
5. Ensure app startup can create/write the SQLite file. Deploy latest CI-passing development commit and confirm `/health`.
6. Create two isolated test merchants, exercise QR enrollment, wallet token validation, scans, PIN rotation, reward redemption, receipt replay, and delete/recover.
7. Verify data survives a controlled staging restart/redeploy after a safe backup. Record results.
8. Keep production unchanged until an approved review, backup/restore proof and rollout plan exist.

**Status: staging redeploy NOT YET AUTHORIZED by evidence.** This runbook is documentation only; it did not provision resources, mutate any Railway environment or copy production data.
