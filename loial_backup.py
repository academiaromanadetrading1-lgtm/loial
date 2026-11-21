"""Consistent SQLite backup for LOIAL (no production access by default).

Use the SQLite Online Backup API while LOIAL is running. A complete, verified
snapshot is written to a *new* path with owner-only permissions. The operator
must provide both paths explicitly; the script never sends backups to a server.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

# Presence of these tables distinguishes a LOIAL database from an arbitrary
# but valid SQLite file. Validate before certifying an operational backup.
LOIAL_REQUIRED_COLUMNS={
    "business_accounts":frozenset({"id","email","name"}),
    "customers":frozenset({"id","uuid","business_id","stamps"}),
    "users":frozenset({"id","email","role"}),
    "loial_stamp_awards":frozenset({
        "id","business_id","customer_id","operation_key","stamps_after"
    }),
}
LOIAL_REQUIRED_TABLES=frozenset(LOIAL_REQUIRED_COLUMNS)



def verify_restorable(snapshot: str | Path, *, require_loial_schema: bool = False) -> dict:
    """Prove the snapshot can be restored into a separate disposable SQLite DB.

    Never copies data to a network destination and never opens the production
    source for writing. Counts schema objects only; does not expose row data.
    """
    source=Path(snapshot).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("Snapshot must be a regular file")
    with tempfile.TemporaryDirectory(prefix="loial-restore-check-") as folder:
        restored=Path(folder)/"restored.sqlite"
        with sqlite3.connect(source.as_uri()+"?mode=ro",uri=True) as src:
            with sqlite3.connect(restored) as dst:
                src.backup(dst,pages=100,sleep=0.05)
                result=dst.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0]!="ok":
                    raise RuntimeError("Isolated restore integrity check failed")
                # A zero-byte or uninitialized SQLite file can report "ok".
                # It must never count as a valid customer database backup.
                tables=dst.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
                if tables<1:
                    raise RuntimeError("Restored SQLite snapshot has no application tables")
                if dst.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("Restored SQLite snapshot has foreign key violations")
                if require_loial_schema:
                    names={row[0] for row in dst.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )}
                    missing=LOIAL_REQUIRED_TABLES-names
                    if missing:
                        raise RuntimeError(
                            "Restored database is missing required LOIAL tables: "
                            + ", ".join(sorted(missing))
                        )
                    for table,required in LOIAL_REQUIRED_COLUMNS.items():
                        # Table names are code-defined constants, never user input.
                        present={row[1] for row in dst.execute(
                            f'PRAGMA table_info("{table}")'
                        )}
                        absent=required-present
                        if absent:
                            raise RuntimeError(
                                f"Restored LOIAL table {table} lacks required columns: "
                                + ", ".join(sorted(absent))
                            )
                return {"restored":True,"integrity":"ok","tables":tables}


def backup_database(source: str | Path, destination: str | Path, *, require_loial_schema: bool = False) -> dict:
    src=Path(source).expanduser().resolve(strict=True)
    dst=Path(destination).expanduser().resolve(strict=False)
    if not src.is_file():
        raise ValueError("Source must be an existing database file")
    if src==dst or dst.exists():
        raise ValueError("Destination must be a new file, different from source")
    if src.stat().st_size==0:
        raise ValueError("Source SQLite file is empty; refusing false backup assurance")
    if not dst.parent.is_dir():
        raise ValueError("Destination parent directory does not exist")
    tmp=dst.with_name("."+dst.name+"."+uuid.uuid4().hex+".tmp")
    # SQLite WAL/journal mode snapshot remains transaction-consistent.
    conn=None
    target=None
    try:
        # Restrict access before any customer data is written.
        handle=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        os.close(handle)
        conn=sqlite3.connect(src.as_uri()+"?mode=ro",uri=True,timeout=20)
        target=sqlite3.connect(str(tmp))
        conn.backup(target,pages=100,sleep=0.05)
        check=target.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0]!="ok":
            raise RuntimeError("Backup integrity_check failed")
        target.commit()
        target.close()
        target=None
        conn.close()
        conn=None
        restoration=verify_restorable(tmp,require_loial_schema=require_loial_schema)
        # Atomic hard-link creation refuses an existing destination. Unlike
        # os.replace this can never overwrite another operator's backup.
        os.link(tmp,dst)
        return {"backup_path":str(dst),"bytes":dst.stat().st_size,
                "integrity":"ok","permissions":"0600","restore_verified":restoration["restored"]}
    finally:
        if target is not None:target.close()
        if conn is not None:conn.close()
        if tmp.exists():tmp.unlink()


def main() -> None:
    parser=argparse.ArgumentParser(description="Back up an existing LOIAL SQLite file")
    parser.add_argument("--source",required=True,help="Existing LOIAL SQLite database path")
    parser.add_argument("--output",required=True,help="NEW output file; never overwrite")
    parser.add_argument("--allow-generic-sqlite",action="store_true",
                        help="For fixture/testing use only; skip LOIAL schema verification")
    args=parser.parse_args()
    result=backup_database(args.source,args.output,
                           require_loial_schema=not args.allow_generic_sqlite)
    print(f"Verified backup: {result['backup_path']} ({result['bytes']} bytes)")


if __name__=="__main__":
    main()
