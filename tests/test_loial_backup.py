"""LOIAL SQLite backup + restore smoke tests; disposable local database only."""
import os
import sqlite3

import pytest

from loial_backup import backup_database


def test_backup_is_consistent_and_restorable(tmp_path):
    source=tmp_path/"loial-source.db"
    destination=tmp_path/"loial-backup.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE members (id INTEGER PRIMARY KEY, nickname TEXT)")
        db.execute("INSERT INTO members(nickname) VALUES (?)",("Test Member",))
        db.commit()
    outcome=backup_database(source,destination)
    assert outcome["integrity"]=="ok"
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


def test_verified_restore_required_tables_and_escaped_paths(tmp_path):
    from loial_backup import verify_restore
    source=tmp_path/"snapshot #1?.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE loial_management_snapshots (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO loial_management_snapshots VALUES (1)")
        db.commit()
    target=tmp_path/"isolated restore.db"
    result=verify_restore(source,target,("loial_management_snapshots",))
    assert result["row_counts_match"] and result["required_tables_present"]
    assert result["table_count"]==1
    bad=tmp_path/"failed.db"
    with pytest.raises(RuntimeError,match="schema or row count mismatch"):
        verify_restore(source,bad,("missing_table",))
    assert not bad.exists() and source.exists()
