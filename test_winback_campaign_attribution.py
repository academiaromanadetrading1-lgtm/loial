"""Real SQLite integration for 14-day campaign attribution and merchant isolation."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from loial_winback_campaigns import (
    CampaignBase, WinbackCampaign, WinbackRecipient, WinbackAttribution,
    at_risk_ids, attribute_confirmed_visit
)

NOW=datetime(2026,11,22,12,0,tzinfo=timezone.utc)

class CampaignAttributionTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite+pysqlite:///:memory:")
        CampaignBase.metadata.create_all(self.engine)
        self.db=Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def campaign(self,biz,customer,days_ago=1,status="sent"):
        date_str=(NOW-timedelta(days=days_ago)).isoformat()
        row=WinbackCampaign(business_id=biz,title="Come back",message="Hello",
                            status=status,created_at=date_str,
                            approved_at=date_str,sent_count=1)
        self.db.add(row);self.db.flush()
        self.db.add(WinbackRecipient(campaign_id=row.id,business_id=biz,
            customer_id=customer,delivered_at=date_str if status=="sent" else None))
        self.db.commit()
        return row.id

    def test_confirmed_scan_in_attribution_window(self):
        cid=self.campaign(2,42)
        self.assertTrue(attribute_confirmed_visit(self.db,2,42,"scan-first",NOW))
        self.db.commit()
        row=self.db.query(WinbackAttribution).one()
        self.assertEqual((row.business_id,row.campaign_id,row.customer_id),(2,cid,42))

    def test_duplicate_operation_cannot_be_attributed_twice(self):
        self.campaign(2,42)
        self.assertTrue(attribute_confirmed_visit(self.db,2,42,"scan-replay",NOW))
        self.db.commit()
        self.assertFalse(attribute_confirmed_visit(self.db,2,42,"scan-replay",NOW))
        self.db.commit()
        self.assertEqual(self.db.query(WinbackAttribution).count(),1)

    def test_other_firm_or_customer_cannot_claim_attribution(self):
        self.campaign(2,42)
        self.assertFalse(attribute_confirmed_visit(self.db,3,42,"scan-third-firm",NOW))
        self.assertFalse(attribute_confirmed_visit(self.db,2,43,"scan-other-customer",NOW))
        self.assertEqual(self.db.query(WinbackAttribution).count(),0)

    def test_old_or_unapproved_campaigns_do_not_attribute(self):
        self.campaign(2,42,days_ago=15)
        self.campaign(2,43,days_ago=1,status="draft")
        self.assertFalse(attribute_confirmed_visit(self.db,2,42,"scan-old",NOW))
        self.assertFalse(attribute_confirmed_visit(self.db,2,43,"scan-draft",NOW))

    def test_fourteen_day_boundary(self):
        self.campaign(2,42,days_ago=14)
        self.assertTrue(attribute_confirmed_visit(self.db,2,42,"scan-14days",NOW))

    def test_database_unique_constraint_guards_racing_retries(self):
        self.campaign(2,42)
        for customer in (42,42):
            self.db.add(WinbackAttribution(business_id=2,campaign_id=1,
                customer_id=customer,operation_key="same-op",confirmed_at=NOW.isoformat()))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_at_risk_selection_requires_audited_visits(self):
        rows=[SimpleNamespace(customer_id=42,created_at="2026-10-01T12:00:00+00:00",source="manual"),
              SimpleNamespace(customer_id=43,created_at="2026-10-02T12:00:00+00:00",source="receipt")]
        self.assertEqual(at_risk_ids(rows,[42],30,date(2026,11,22)),{42})

    def test_non_visit_ledger_rows_never_make_winback_eligible(self):
        rows=[
            SimpleNamespace(customer_id=42,source="manual",
                created_at="2026-10-01T12:00:00+00:00"),
            SimpleNamespace(customer_id=42,source="redeem",
                created_at="2026-11-21T12:00:00+00:00"),
            SimpleNamespace(customer_id=43,source="refund",
                created_at="2026-10-01T12:00:00+00:00"),
            SimpleNamespace(customer_id=44,source="receipt",
                created_at="2026-10-02T12:00:00+00:00")
        ]
        self.assertEqual(at_risk_ids(rows,[42,43,44],30,date(2026,11,22)),
                         {42,44})

if __name__=="__main__":
    unittest.main()
