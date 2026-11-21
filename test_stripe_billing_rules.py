"""Execute Stripe billing decision functions without Stripe API or real records."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).with_name("loial_stripe_billing.py").read_text(encoding="utf-8")
FUNCTIONS = {
    "from_unix", "parse_utc", "invoice_period", "invoice_is_eligible",
    "entitlements", "lifecycle_event_is_stale", "checkout_binding_is_stale",
    "subscription_event_matches"
}
tree = ast.parse(SOURCE)
selected = [node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
assert len(selected) == len(FUNCTIONS)
namespace = {"datetime": datetime, "timedelta": timedelta, "timezone": timezone,
             "PRICE_CENTS": 6700}
exec(compile(ast.Module(body=selected, type_ignores=[]), "<billing-rules>", "exec"), namespace)


class StripeBillingRulesTests(unittest.TestCase):
    def paid_invoice(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=30)
        return {
            "status": "paid", "paid": True, "currency": "eur",
            "amount_paid": 6700, "paid_out_of_band": False,
            "lines": {"data": [{
                "quantity": 1, "price": {"id": "price_loial_verified"},
                "period": {"start": int(start.timestamp()), "end": int(end.timestamp())}
            }]}
        }

    def test_paid_verified_invoice_eligible(self):
        self.assertTrue(namespace["invoice_is_eligible"](
            self.paid_invoice(), "price_loial_verified"))

    def test_wrong_price_and_amount_never_unlock(self):
        for mutation in (
            {"amount_paid": 6701}, {"currency": "usd"}, {"paid": False},
            {"status": "open"}, {"paid_out_of_band": True}
        ):
            with self.subTest(mutation=mutation):
                invoice = self.paid_invoice()
                invoice.update(mutation)
                self.assertFalse(namespace["invoice_is_eligible"](
                    invoice, "price_loial_verified"))
        self.assertFalse(namespace["invoice_is_eligible"](
            self.paid_invoice(), "price_other_project"))

    def test_multiple_invoice_lines_or_quantity_rejected(self):
        invoice = self.paid_invoice()
        invoice["lines"]["data"].append(invoice["lines"]["data"][0].copy())
        self.assertFalse(namespace["invoice_is_eligible"](
            invoice, "price_loial_verified"))
        invoice = self.paid_invoice()
        invoice["lines"]["data"][0]["quantity"] = 2
        self.assertFalse(namespace["invoice_is_eligible"](
            invoice, "price_loial_verified"))

    def test_monthly_coverage_and_long_period_rejection(self):
        invoice = self.paid_invoice()
        period, end = namespace["invoice_period"](invoice)
        self.assertEqual(period, "2026-11")
        self.assertEqual(end, datetime(2026, 12, 1, tzinfo=timezone.utc))
        invoice["lines"]["data"][0]["period"]["end"] += 365 * 86400
        self.assertEqual(namespace["invoice_period"](invoice), (None, None))

    def test_active_paid_subscription_and_expiry(self):
        now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        state = SimpleNamespace(status="active",
                                paid_until=(now+timedelta(days=5)).isoformat(),
                                grace_until=None)
        self.assertTrue(namespace["entitlements"](state, now)["active"])
        self.assertFalse(namespace["entitlements"](state, now+timedelta(days=6))["active"])
        state.status = "canceled"
        self.assertFalse(namespace["entitlements"](state, now)["active"])

    def test_grace_period_applies_only_to_past_due(self):
        now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        state = SimpleNamespace(status="past_due",
                                paid_until=(now-timedelta(days=1)).isoformat(),
                                grace_until=(now+timedelta(days=2)).isoformat())
        self.assertEqual(namespace["entitlements"](state,now)["status"],"grace_period")
        self.assertFalse(namespace["entitlements"](state,now+timedelta(days=3))["active"])
        state.status = "unpaid"
        self.assertFalse(namespace["entitlements"](state,now)["active"])

    def test_stale_events_cannot_reverse_access(self):
        state = SimpleNamespace(last_event_at=100,subscription_id="sub_current")
        stale = namespace["lifecycle_event_is_stale"]
        self.assertTrue(stale(state, 100))
        self.assertTrue(stale(state, 99))
        self.assertFalse(stale(state, 101))
        checkout = namespace["checkout_binding_is_stale"]
        self.assertTrue(checkout(state,100,"sub_old"))
        self.assertFalse(checkout(state,101,"sub_new"))
        self.assertFalse(checkout(state,99,"sub_current"))

    def test_other_subscription_cannot_rebind(self):
        state = SimpleNamespace(customer_id="cus_one",subscription_id="sub_one")
        matches = namespace["subscription_event_matches"]
        self.assertTrue(matches(state,"cus_one","sub_one"))
        self.assertFalse(matches(state,"cus_two","sub_one"))
        self.assertFalse(matches(state,"cus_one","sub_two"))


if __name__ == "__main__":
    unittest.main()
