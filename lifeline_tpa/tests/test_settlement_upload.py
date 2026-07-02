import unittest
from io import BytesIO

from openpyxl import Workbook

from lifeline_tpa.services.settlement_upload import (
    PAYER_RECEIPT_COLUMNS,
    PROVIDER_PAYMENT_COLUMNS,
    parse_payer_receipt_file,
    parse_provider_payment_file,
)


class TestSettlementUploadParser(unittest.TestCase):
    def test_parses_payer_receipt_three_column_workbook(self):
        parsed = parse_payer_receipt_file(
            _workbook(
                PAYER_RECEIPT_COLUMNS,
                [["CLAIM-1", 20, "ENBD Bank - LL"]],
            ),
            "payer-receipt.xlsx",
        )

        self.assertTrue(parsed.is_valid)
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.rows[0].claim_reference, "CLAIM-1")
        self.assertEqual(str(parsed.rows[0].amount_paid), "20")
        self.assertEqual(parsed.rows[0].lifeline_bank_account, "ENBD Bank - LL")
        self.assertIsNone(parsed.rows[0].payment_reference)

    def test_parses_provider_payment_four_column_workbook(self):
        parsed = parse_provider_payment_file(
            _workbook(
                PROVIDER_PAYMENT_COLUMNS,
                [["CLAIM-1", "20.50", "ENBD Bank - LL", "TT-123"]],
            ),
            "provider-payment.xlsx",
        )

        self.assertTrue(parsed.is_valid)
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.rows[0].claim_reference, "CLAIM-1")
        self.assertEqual(str(parsed.rows[0].amount_paid), "20.50")
        self.assertEqual(parsed.rows[0].payment_reference, "TT-123")

    def test_rejects_wrong_payer_receipt_headers(self):
        parsed = parse_payer_receipt_file(
            _workbook(
                ["claim_unique_number", "amount_paid", "payment_reference"],
                [["CLAIM-1", 20, "TT-123"]],
            ),
            "payer-receipt.xlsx",
        )

        self.assertFalse(parsed.is_valid)
        self.assertEqual(parsed.errors[0]["code"], "invalid_headers")

    def test_rejects_duplicates_and_bad_values(self):
        parsed = parse_provider_payment_file(
            _workbook(
                PROVIDER_PAYMENT_COLUMNS,
                [
                    ["CLAIM-1", "20", "ENBD Bank - LL", "TT-123"],
                    ["CLAIM-1", "-5", "", ""],
                ],
            ),
            "provider-payment.xlsx",
        )

        self.assertFalse(parsed.is_valid)
        codes = {error["code"] for error in parsed.errors}
        self.assertIn("duplicate_claim_reference", codes)
        self.assertIn("non_positive_amount_paid", codes)
        self.assertIn("missing_lifeline_bank_account", codes)
        self.assertIn("missing_payment_reference", codes)


def _workbook(headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
