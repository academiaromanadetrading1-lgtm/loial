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
    try:
        conn=sqlite3.connect(f"file:{src.as_posix()}?mode=ro",uri=True,timeout=20)
        with sqlite3.connect(str(tmp)) as target:
            conn.backup(target,pages=100,sleep=0.05)
            check=target.execute("PRAGMA integrity_check").fetchone()
            if not check or check[0]!="ok":
                raise RuntimeError("Backup integrity_check failed")
        os.chmod(tmp,0o600)
        if dst.exists():
            raise ValueError("Destination appeared during backup")
        os.replace(tmp,dst)
        return {"backup_path":str(dst),"bytes":dst.stat().st_size,
                "integrity":"ok","permissions":"0600"}
    finally:
        if conn is not None:conn.close()
        if tmp.exists():tmp.unlink()


def main() -> None:
    parser=argparse.ArgumentParser(description="Back up an existing LOIAL SQLite file")
    parser.add_argument("--source",required=True,help="Existing LOIAL SQLite database path")
    parser.add_argument("--output",required=True,help="NEW output file; never overwrite")
    args=parser.parse_args()
    result=backup_database(args.source,args.output)
    print(f"Verified backup: {result['backup_path']} ({result['bytes']} bytes)")


if __name__=="__main__":
    main()
