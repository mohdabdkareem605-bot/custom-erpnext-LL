import unittest
from decimal import Decimal

from lifeline_tpa.services.bulk_processing import (
    BulkClaim,
    group_claims_for_bulk_processing,
    summarize_bulk_groups,
)


class TestBulkProcessing(unittest.TestCase):
    def test_groups_claims_by_facility_and_provider(self):
        groups = group_claims_for_bulk_processing(
            [
                _claim("CLAIM-1", "FAC-1", "Provider One", "10.25"),
                _claim("CLAIM-2", "FAC-1", "Provider One", "20.75"),
                _claim("CLAIM-3", "FAC-2", "Provider Two", "9"),
            ]
        )

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].facility_id, "FAC-1")
        self.assertEqual(groups[0].claim_count, 2)
        self.assertEqual(groups[0].total_amount, Decimal("31.00"))

        summary = summarize_bulk_groups(groups)
        self.assertEqual(summary["claim_count"], 3)
        self.assertEqual(summary["purchase_total"], 40.0)
        self.assertEqual(summary["sales_total"], 40.0)
        self.assertEqual(summary["clearing_difference"], 0.0)

    def test_rejects_zero_amount_claim(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            group_claims_for_bulk_processing(
                [_claim("CLAIM-1", "FAC-1", "Provider One", "0")]
            )

    def test_rejects_missing_provider_mapping(self):
        with self.assertRaisesRegex(ValueError, "missing its provider mapping"):
            group_claims_for_bulk_processing(
                [_claim("CLAIM-1", "FAC-1", "", "10")]
            )


def _claim(reference, facility_id, provider, amount):
    return BulkClaim(
        claim_reference=reference,
        facility_id=facility_id,
        provider=provider,
        amount=Decimal(amount),
    )
