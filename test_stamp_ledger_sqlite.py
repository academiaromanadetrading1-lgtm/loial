"""SQLite integration tests for the real stamp-award ledger.

These tests create an isolated in-memory DB: no Railway credentials or customer
data are accessed. They execute actual SQLAlchemy queries and constraints.
"""
from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from loial_scans import (
    ScanBase, StampAward, existing_operation, recent_duplicate, record_award,
)


class StampLedgerSQLiteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        ScanBase.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_same_business_and_operation_cannot_be_written_twice(self):
        record_award(self.db, 7, 11, "scan-operation-A", "manual", 1)
        self.db.commit()
        record_award(self.db, 7, 11, "scan-operation-A", "manual", 2)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
        self.assertEqual(self.db.query(StampAward).count(), 1)

    def test_same_operation_key_in_other_business_is_independent(self):
        record_award(self.db, 7, 11, "scan-operation-A", "manual", 1)
        record_award(self.db, 8, 12, "scan-operation-A", "manual", 1)
        self.db.commit()
        self.assertEqual(self.db.query(StampAward).count(), 2)
        self.assertEqual(existing_operation(self.db, 7, "scan-operation-A").customer_id, 11)
        self.assertEqual(existing_operation(self.db, 8, "scan-operation-A").customer_id, 12)
        self.assertIsNone(existing_operation(self.db, 9, "scan-operation-A"))

    def test_cooldown_is_per_business_and_customer(self):
        now = datetime.now(timezone.utc)
        record_award(self.db, 7, 11, "operation-recent", "manual", 3, at=now)
        self.db.commit()
        self.assertIsNotNone(recent_duplicate(self.db, 7, 11, now=now))
        self.assertIsNone(recent_duplicate(self.db, 7, 12, now=now))
        self.assertIsNone(recent_duplicate(self.db, 8, 11, now=now))

    def test_old_operation_is_not_flagged_as_a_recent_scan(self):
        now = datetime.now(timezone.utc)
        record_award(self.db, 7, 11, "operation-old", "manual", 1,
                     at=now - timedelta(minutes=3))
        self.db.commit()
        self.assertIsNone(recent_duplicate(self.db, 7, 11, now=now))

    def test_operation_identifiers_must_be_nonempty_and_bounded(self):
        for invalid in ("", "a" * 121):
            with self.subTest(invalid_length=len(invalid)):
                with self.assertRaises(ValueError):
                    record_award(self.db, 7, 11, invalid, "manual", 1)
        self.assertEqual(self.db.query(StampAward).count(), 0)


if __name__ == "__main__":
    unittest.main()
