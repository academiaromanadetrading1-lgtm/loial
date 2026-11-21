"""LOIAL SQLite backup + restore smoke tests; disposable local database only."""
import os
import sqlite3

import pytest

from loial_backup import backup_database, verify_restorable


def test_backup_is_consistent_and_restorable(tmp_path):
    source=tmp_path/"loial-source.db"
    destination=tmp_path/"loial-backup.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE members (id INTEGER PRIMARY KEY, nickname TEXT)")
        db.execute("INSERT INTO members(nickname) VALUES (?)",("Test Member",))
        db.commit()
    outcome=backup_database(source,destination)
    assert outcome["integrity"]=="ok"
    assert outcome["restore_verified"] is True
    assert destination.exists()
    if os.name=="posix":
        assert os.stat(destination).st_mode & 0o777==0o600
    with sqlite3.connect(destination) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert restored.execute("SELECT nickname FROM members").fetchone()[0]=="Test Member"


def test_backup_does_not_overwrite_or_touch_source(tmp_path):
    source=tmp_path/"source.db"
    target=tmp_path/"existing.db"
    sqlite3.connect(source).close()
    target.write_bytes(b"leave unchanged")
    with pytest.raises(ValueError,match="new file"):
        backup_database(source,target)
    assert target.read_bytes()==b"leave unchanged"
    with pytest.raises(ValueError,match="new file"):
        backup_database(source,source)


def test_restore_checker_does_not_modify_source_snapshot(tmp_path):
    snapshot=tmp_path/"snapshot.sqlite"
    with sqlite3.connect(snapshot) as db:
        db.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO evidence(value) VALUES ('kept')")
        db.commit()
    before=snapshot.read_bytes()
    result=verify_restorable(snapshot)
    assert result=={"restored":True,"integrity":"ok","tables":1}
    assert snapshot.read_bytes()==before
    assert not list(tmp_path.glob("loial-restore-check-*"))


def test_restore_checker_rejects_corrupt_file(tmp_path):
    damaged=tmp_path/"damaged.sqlite"
    damaged.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        verify_restorable(damaged)


@pytest.mark.parametrize("basename", [
    "source #archive.sqlite",
    "source ?v=1.sqlite",
    "source % 2026.sqlite",
])
def test_backup_handles_reserved_file_uri_characters(tmp_path, basename):
    source=tmp_path/basename
    destination=tmp_path/"verified-backup.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE members (id INTEGER, label TEXT)")
        db.execute("INSERT INTO members VALUES (1, 'existing data')")
        db.commit()
    outcome=backup_database(source,destination)
    assert outcome["restore_verified"] is True
    with sqlite3.connect(destination) as snapshot:
        assert snapshot.execute("SELECT label FROM members").fetchone()[0]=="existing data"


def test_backup_includes_committed_wal_data(tmp_path):
    source=tmp_path/"wal-source.sqlite"
    destination=tmp_path/"wal-backup.sqlite"
    with sqlite3.connect(source) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower()=="wal"
        db.execute("CREATE TABLE receipts (id INTEGER PRIMARY KEY, amount INTEGER)")
        db.commit()
        db.execute("INSERT INTO receipts(amount) VALUES (12345)")
        db.commit()
        outcome=backup_database(source,destination)
        assert outcome["restore_verified"] is True
        with sqlite3.connect(destination) as copy:
            assert copy.execute("SELECT amount FROM receipts").fetchone()[0]==12345


def test_restore_checker_rejects_valid_but_empty_sqlite(tmp_path):
    empty=tmp_path/"empty.sqlite"
    sqlite3.connect(empty).close()
    with pytest.raises(RuntimeError,match="no application tables"):
        verify_restorable(empty)
    with pytest.raises(ValueError,match="empty"):
        backup_database(empty,tmp_path/"not-valid-backup.sqlite")
    assert not (tmp_path/"not-valid-backup.sqlite").exists()


def test_restore_checker_rejects_foreign_key_violations(tmp_path):
    snapshot=tmp_path/"broken-relations.sqlite"
    with sqlite3.connect(snapshot) as db:
        db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))")
        db.execute("INSERT INTO child (id,parent_id) VALUES (1,999)")
        db.commit()
    with pytest.raises(RuntimeError,match="foreign key violations"):
        verify_restorable(snapshot)
    with pytest.raises(RuntimeError,match="foreign key violations"):
        backup_database(snapshot,tmp_path/"unusable-backup.sqlite")
    assert not (tmp_path/"unusable-backup.sqlite").exists()


def test_operational_backup_rejects_unrelated_sqlite_schema(tmp_path):
    source=tmp_path/"foreign.sqlite"
    dest=tmp_path/"not-loial-backup.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        db.commit()
    with pytest.raises(RuntimeError,match="missing required LOIAL tables"):
        backup_database(source,dest,require_loial_schema=True)
    assert not dest.exists()
    # The original source is still valid and unchanged.
    with sqlite3.connect(source) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"


def test_operational_backup_accepts_loial_core_schema(tmp_path):
    from loial_backup import LOIAL_REQUIRED_COLUMNS
    source=tmp_path/"loial.sqlite"
    dest=tmp_path/"verified-loial.sqlite"
    with sqlite3.connect(source) as db:
        for name,columns in sorted(LOIAL_REQUIRED_COLUMNS.items()):
            ddl=", ".join(
                f'"{col}" '+("INTEGER PRIMARY KEY" if col=="id" else "TEXT")
                for col in sorted(columns)
            )
            db.execute(f'CREATE TABLE "{name}" ({ddl})')
        db.execute("INSERT INTO business_accounts(id) VALUES (3)")
        db.execute("INSERT INTO customers(id) VALUES (7)")
        db.commit()
    result=backup_database(source,dest,require_loial_schema=True)
    assert result["restore_verified"] is True
    assert verify_restorable(dest,require_loial_schema=True)["restored"] is True
    with sqlite3.connect(dest) as db:
        assert db.execute("SELECT id FROM customers").fetchone()[0]==7
        assert db.execute("SELECT id FROM business_accounts").fetchone()[0]==3


def test_backup_cli_requires_loial_schema_by_default(tmp_path,monkeypatch):
    import sys
    from loial_backup import main
    source=tmp_path/"generic.sqlite"
    destination=tmp_path/"cli-backup.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE generic_test (id INTEGER)")
    monkeypatch.setattr(sys,"argv",[
        "loial_backup.py","--source",str(source),"--output",str(destination)
    ])
    with pytest.raises(RuntimeError,match="missing required LOIAL tables"):
        main()
    assert not destination.exists()
    monkeypatch.setattr(sys,"argv",[
        "loial_backup.py","--source",str(source),"--output",str(destination),
        "--allow-generic-sqlite"
    ])
    main()
    assert destination.exists()


def test_operational_backup_rejects_misleading_table_names(tmp_path):
    from loial_backup import LOIAL_REQUIRED_TABLES
    source=tmp_path/"incomplete-loial.sqlite"
    dest=tmp_path/"not-complete.sqlite"
    with sqlite3.connect(source) as db:
        for name in sorted(LOIAL_REQUIRED_TABLES):
            db.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
        db.commit()
    with pytest.raises(RuntimeError,match="lacks required columns"):
        backup_database(source,dest,require_loial_schema=True)
    assert not dest.exists()
