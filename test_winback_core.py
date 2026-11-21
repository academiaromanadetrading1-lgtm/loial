"""Win-back behavior from audited visits, never enrollments or fabricated sales."""
from datetime import date
from types import SimpleNamespace
import unittest

from loial_winback import summarize_inactive, SettingsInput


def scan(customer, day, source="manual"):
    return SimpleNamespace(customer_id=customer, created_at=day, source=source)


class WinbackCoreTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 22)

    def test_three_confirmed_visits_use_personal_cycle(self):
        # 10-day interval => expected 13 days. Customer absent 22 days.
        rows = [scan(2, day) for day in (
            "2026-10-11T10:00:00+00:00",
            "2026-10-21T10:00:00+00:00",
            "2026-10-31T10:00:00+00:00")]
        result = summarize_inactive(rows, [2], 30, 9000, 35, self.today)
        self.assertEqual(result["with_personal_cycle"], 1)
        self.assertEqual(result["at_risk_customers"], 1)
        self.assertEqual(result["potential_return_revenue_minor"], 2250)
        self.assertEqual(result["potential_contribution_minor"], 788)
        self.assertTrue(result["forecast_only"])

    def test_ineligible_customers_from_other_merchants_excluded(self):
        rows = [scan(2, "2026-10-01"), scan(9, "2026-10-01")]
        result = summarize_inactive(rows, [2], 30, as_of=self.today)
        self.assertEqual(result["at_risk_customers"], 1)
        self.assertEqual(result["confirmed_visit_customers"], 1)

    def test_enrollment_without_scan_does_not_count_as_visit(self):
        result = summarize_inactive([], [2,3,4], as_of=self.today)
        self.assertEqual(result["confirmed_visit_customers"], 0)
        self.assertEqual(result["at_risk_customers"], 0)
        self.assertEqual(result["potential_return_revenue_minor"], 0)

    def test_same_day_scan_duplicates_do_not_fake_personal_cycle(self):
        rows = [scan(2, "2026-11-01T09:00:00"),
                scan(2, "2026-11-01T13:00:00"),
                scan(2, "2026-11-02T13:00:00")]
        result = summarize_inactive(rows, [2], 30, as_of=self.today)
        self.assertEqual(result["with_personal_cycle"], 0)
        self.assertEqual(result["at_risk_customers"], 0)

    def test_invalid_date_and_future_visit_ignored(self):
        rows = [scan(2, "bad"), scan(2, "2026-12-31T09:00:00")]
        result = summarize_inactive(rows, [2], 30, as_of=self.today)
        self.assertEqual(result["confirmed_visit_customers"], 0)

    def test_exact_threshold_is_not_at_risk(self):
        result = summarize_inactive([scan(2, "2026-10-23")], [2], 30,
                                    as_of=self.today)
        self.assertEqual(result["at_risk_customers"], 0)

    def test_reward_redemption_and_refund_are_not_customer_visits(self):
        rows=[scan(2,"2026-10-01","manual"),
              scan(2,"2026-11-21","redeem"),
              scan(3,"2026-10-02","refund"),
              scan(4,"2026-10-01","receipt")]
        result=summarize_inactive(rows,[2,3,4],30,as_of=self.today)
        self.assertEqual(result["confirmed_visit_customers"],2)
        self.assertEqual(result["at_risk_customers"],2)

    def test_only_bookkeeping_events_do_not_create_retention_candidates(self):
        rows=[scan(2,"2026-10-01","redeem"),
              scan(2,"2026-10-02","refund")]
        result=summarize_inactive(rows,[2],3,as_of=self.today)
        self.assertEqual(result["confirmed_visit_customers"],0)
        self.assertEqual(result["at_risk_customers"],0)

    def test_settings_reject_unsafe_financial_assumptions(self):
        from pydantic import ValidationError
        for values in (
            {"default_return_days": 0, "average_ticket_minor": 5000,
             "estimated_margin_percent": 35, "currency": "RON"},
            {"default_return_days": 30, "average_ticket_minor": -1,
             "estimated_margin_percent": 35, "currency": "RON"},
            {"default_return_days": 30, "average_ticket_minor": 5000,
             "estimated_margin_percent": 101, "currency": "RON"},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                SettingsInput(**values)


if __name__ == "__main__":
    unittest.main()
