import unittest
from datetime import date
from io import BytesIO

from openpyxl import Workbook

from lifeline_tpa.services.claim_removal import (
    REMOVAL_COLUMNS,
    parse_claim_removal_file,
)


class TestClaimRemovalParser(unittest.TestCase):
    def test_parses_valid_workbook(self):
        parsed = parse_claim_removal_file(
            _workbook(
                [
                    ["CLAIM-1", "Duplicate approval", "MED-123", "2026-06-19"],
                    ["CLAIM-2", "Medical rejection", "MED-124", date(2026, 6, 20)],
                ]
            ),
            "removals.xlsx",
        )

        self.assertTrue(parsed.is_valid)
        self.assertEqual(len(parsed.requests), 2)
        self.assertEqual(parsed.requests[0].claim_reference, "CLAIM-1")
        self.assertEqual(parsed.requests[0].removal_date, date(2026, 6, 19))

    def test_rejects_duplicate_and_missing_values(self):
        parsed = parse_claim_removal_file(
            _workbook(
                [
                    ["CLAIM-1", "Duplicate", "MED-123", "2026-06-19"],
                    ["CLAIM-1", "", "", "not-a-date"],
                ]
            ),
            "removals.xlsx",
        )

        self.assertFalse(parsed.is_valid)
        codes = {error["code"] for error in parsed.errors}
        self.assertIn("duplicate_claim_reference", codes)
        self.assertIn("missing_reason", codes)
        self.assertIn("missing_approval_reference", codes)
        self.assertIn("invalid_removal_date", codes)

    def test_requires_exact_headers(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Claim", "Reason"])
        output = BytesIO()
        workbook.save(output)

        parsed = parse_claim_removal_file(output.getvalue(), "removals.xlsx")

        self.assertEqual(parsed.errors[0]["code"], "invalid_headers")


def _workbook(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Claim Removals"
    sheet.append(REMOVAL_COLUMNS)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
