"""Audit stamp cooldown: redemption/refund bookkeeping is not a purchase scan."""
from datetime import datetime, timedelta, timezone
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from loial_scans import ScanBase, StampAward, recent_duplicate, existing_operation, record_award

NOW=datetime(2026,11,22,12,0,tzinfo=timezone.utc)

class ScanCooldownTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite+pysqlite:///:memory:")
        ScanBase.metadata.create_all(self.engine)
        self.db=Session(self.engine)
    def tearDown(self):
        self.db.close()
        self.engine.dispose()
    def add(self,operation,source,age=0,customer=5,merchant=1):
        record_award(self.db,merchant,customer,operation,source,1,
                     at=NOW-timedelta(seconds=age))
        self.db.commit()
    def test_recent_staff_scan_blocks_repeated_stamp(self):
        self.add("scan:staff:001","manual",age=3)
        self.assertIsNotNone(recent_duplicate(self.db,1,5,now=NOW))
        self.assertIsNone(recent_duplicate(self.db,1,6,now=NOW))
        self.assertIsNone(recent_duplicate(self.db,2,5,now=NOW))
    def test_recent_receipt_claim_blocks_duplicate_stamp(self):
        self.add("receipt:001","receipt",age=3)
        self.assertIsNotNone(recent_duplicate(self.db,1,5,now=NOW))
    def test_refund_and_redeem_do_not_block_new_stamp(self):
        self.add("redeem:001","redeem",age=2)
        self.add("refund:001","refund",age=1)
        self.assertIsNone(recent_duplicate(self.db,1,5,now=NOW))
    def test_cooldown_boundary_and_operation_idempotency(self):
        self.add("scan:staff:old","manual",age=13)
        self.assertIsNone(recent_duplicate(self.db,1,5,now=NOW))
        self.assertIsNotNone(existing_operation(self.db,1,"scan:staff:old"))

if __name__=="__main__":
    unittest.main()
