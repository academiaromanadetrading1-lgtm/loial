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
