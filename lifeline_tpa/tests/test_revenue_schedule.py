import unittest
from datetime import date
from decimal import Decimal

from lifeline_tpa.services.revenue_schedule import build_revenue_schedule


class TestRevenueSchedule(unittest.TestCase):
    def test_schedule_uses_exclusive_policy_stop_date_and_balances_to_fee(self):
        lines = build_revenue_schedule(
            amount=Decimal("15.00"),
            service_start=date(2026, 5, 1),
            service_end=date(2027, 4, 30),
        )

        self.assertEqual(lines[0].eligible_days, 31)
        self.assertEqual(lines[0].service_days, 364)
        self.assertEqual(sum((line.scheduled_amount for line in lines), Decimal("0")), Decimal("15.00"))

    def test_deletion_schedule_is_negative_and_balances_to_credit_note(self):
        lines = build_revenue_schedule(
            amount=Decimal("-14.01"),
            service_start=date(2026, 5, 25),
            service_end=date(2027, 4, 30),
        )

        self.assertEqual(lines[0].eligible_days, 7)
        self.assertEqual(lines[0].service_days, 340)
        self.assertLess(lines[0].scheduled_amount, 0)
        self.assertEqual(sum((line.scheduled_amount for line in lines), Decimal("0")), Decimal("-14.01"))


if __name__ == "__main__":
    unittest.main()
