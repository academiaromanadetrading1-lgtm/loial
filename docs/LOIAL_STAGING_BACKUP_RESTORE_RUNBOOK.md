# LOIAL staging: backup and independent restore

Scope: Railway staging only. Never run on production without a separate change review.

## Preconditions
- Confirm Railway environment is staging and volume is mounted at /data.
- Confirm SQLite URL is sqlite:////data/loial.db.
- Use an authenticated maintenance terminal with access to the mounted volume.
- Select a private directory **outside** /data for the backup, sufficient space and encrypted offsite retention. A second file on the same volume does not protect against volume loss.
- Do not transmit private customer records, credentials or database bytes to logs, GitHub or CI.

## Create and test a snapshot

```bash
umask 077
python loial_backup.py --source /data/loial.db --output /secure-backups/loial-staging-YYYYMMDD-HHMMSS.sqlite
```

Output must be a new filename. The CLI rejects overwrites, corrupt/empty files and databases missing essential LOIAL tables or columns. It verifies the snapshot by restoring into a temporary isolated database and checking integrity and foreign keys. On POSIX the created backup is private (0600). Do not use --allow-generic-sqlite for real LOIAL backups.

Transfer the verified backup through an approved encrypted channel to an independently secured off-volume location. Verify the transfer independently, and establish an appropriate retention policy.

## Independent recovery drill

In an isolated machine with a copy of the encrypted artifact:

```bash
python -c "from loial_backup import verify_restorable; print(verify_restorable('/secure-backups/loial-staging-YYYYMMDD-HHMMSS.sqlite', require_loial_schema=True))"
```

For release sign-off, also restore a copy into an entirely separate instance, test business login and QR processes using test credentials, then securely dispose of the clone. Do not overwrite staging or production data during the drill.

## Evidence / NO-GO

Record environment and deployment ID, timestamp, file size, off-volume storage reference, restoration result, separate-instance smoke tests and operator approval, without sharing customer content.

As of 2026-11-21: staging has an attached persistent volume and previously passed /health, but **a backup of the real staging data and an independent restoration have not been verified**. CI tests with disposable SQLite fixtures do not satisfy this release gate.
