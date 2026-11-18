"""Consistent SQLite backup for LOIAL (no production access by default).

Use the SQLite Online Backup API while LOIAL is running. A complete, verified
snapshot is written to a *new* path with owner-only permissions. The operator
must provide both paths explicitly; the script never sends backups to a server.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import uuid
from pathlib import Path


def backup_database(source: str | Path, destination: str | Path) -> dict:
    src=Path(source).expanduser().resolve(strict=True)
    dst=Path(destination).expanduser().resolve(strict=False)
    if not src.is_file():
        raise ValueError("Source must be an existing database file")
    if src==dst or dst.exists():
        raise ValueError("Destination must be a new file, different from source")
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
        # Atomic hard-link creation refuses an existing destination. Unlike
        # os.replace this can never overwrite another operator's backup.
        os.link(tmp,dst)
        return {"backup_path":str(dst),"bytes":dst.stat().st_size,
                "integrity":"ok","permissions":"0600"}
    finally:
        if target is not None:target.close()
        if conn is not None:conn.close()
        if tmp.exists():tmp.unlink()


def verify_restore(snapshot: str | Path, destination: str | Path,
                   required_tables: tuple[str, ...] = ()) -> dict:
    """Restore into a new isolated file; verify schema and row counts without exposing rows."""
    src=Path(snapshot).expanduser().resolve(strict=True)
    dst=Path(destination).expanduser().resolve(strict=False)
    outcome=backup_database(src,dst)
    try:
        with sqlite3.connect(src.as_uri()+"?mode=ro",uri=True) as original, \
             sqlite3.connect(dst.as_uri()+"?mode=ro",uri=True) as restored:
            def inventory(db):
                names={r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                return {name:db.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]
                        for name in sorted(names)}
            expected=inventory(original)
            actual=inventory(restored)
            missing=set(required_tables)-set(actual)
            if expected!=actual or missing:
                raise RuntimeError("Restore verification failed: schema or row count mismatch")
            if restored.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise RuntimeError("Restored database failed integrity check")
        return {**outcome,"table_count":len(actual),"row_counts_match":True,
                "required_tables_present":True}
    except Exception:
        dst.unlink(missing_ok=True)
        raise


def main() -> None:
    parser=argparse.ArgumentParser(description="Back up an existing LOIAL SQLite file")
    parser.add_argument("--source",required=True,help="Existing LOIAL SQLite database path")
    parser.add_argument("--output",required=True,help="NEW output file; never overwrite")
    parser.add_argument("--verify-restore",action="store_true",help="Restore from an immutable snapshot into a new isolated file")
    parser.add_argument("--require-table",action="append",default=[],help="Required table for restore verification")
    args=parser.parse_args()
    if args.require_table and not args.verify_restore:
        parser.error("--require-table requires --verify-restore")
    result=(verify_restore(args.source,args.output,tuple(args.require_table)) if args.verify_restore
            else backup_database(args.source,args.output))
    print(f"Verified backup: {result['backup_path']} ({result['bytes']} bytes)")


if __name__=="__main__":
    main()
