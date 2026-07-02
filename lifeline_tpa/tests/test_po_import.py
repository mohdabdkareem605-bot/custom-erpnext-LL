import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from lifeline_tpa.services.po_import import parse_workbook, validate_parsed_workbook
from lifeline_tpa.services.po_schema import MASTER_SHEET_COLUMNS


SAMPLE_FILE = Path(__file__).resolve().parents[2] / "doc" / "PO sample.xlsx"


class TestPOImport(unittest.TestCase):
    def test_sample_workbook_matches_expected_control_totals(self):
        parsed = parse_workbook(SAMPLE_FILE.read_bytes())

        self.assertEqual(parsed.issues, [])
        self.assertEqual(len(parsed.claims), 3516)
        self.assertEqual(len(parsed.facility_ids), 340)
        self.assertEqual(parsed.external_po_refs, {"DNIRC-000150/2026"})
        self.assertEqual(parsed.currencies, {"AED"})
        self.assertEqual(str(parsed.total_amount), "401060.87")

    def test_duplicate_claim_reference_is_rejected(self):
        content = make_workbook(
            [
                make_row(claim_reference="CLAIM-1"),
                make_row(claim_reference="CLAIM-1"),
            ]
        )

        parsed = parse_workbook(content)

        self.assertIn("duplicate_claim_reference", [issue.code for issue in parsed.issues])

    def test_multiple_po_references_and_currencies_are_rejected(self):
        content = make_workbook(
            [
                make_row(claim_reference="CLAIM-1"),
                make_row(
                    claim_reference="CLAIM-2",
                    external_po_ref="PO-2",
                    currency="USD",
                ),
            ]
        )

        parsed = parse_workbook(content)
        issue_codes = [issue.code for issue in parsed.issues]

        self.assertIn("multiple_po_references", issue_codes)
        self.assertIn("multiple_currencies", issue_codes)

    def test_database_and_provider_checks_are_added_to_preview(self):
        parsed = parse_workbook(make_workbook([make_row(claim_reference="CLAIM-1")]))

        result = validate_parsed_workbook(
            parsed,
            existing_claim_references={"CLAIM-1"},
            provider_by_facility={},
            duplicate_file=True,
        )
        issue_codes = [issue.code for issue in result.issues]

        self.assertFalse(result.is_valid)
        self.assertIn("existing_claim_reference", issue_codes)
        self.assertIn("missing_provider_mapping", issue_codes)
        self.assertIn("duplicate_file", issue_codes)

    def test_invalid_rows_remain_in_preview_counts(self):
        content = make_workbook(
            [
                make_row(claim_reference=""),
                make_row(
                    claim_reference="CLAIM-2",
                    external_po_ref="PO-2",
                    currency="USD",
                ),
            ]
        )

        parsed = parse_workbook(content)

        self.assertEqual(len(parsed.claims), 2)
        self.assertIn("missing_required_value", [issue.code for issue in parsed.issues])
        self.assertIn("multiple_po_references", [issue.code for issue in parsed.issues])
        self.assertIn("multiple_currencies", [issue.code for issue in parsed.issues])


def make_workbook(rows):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Master Sheet"
    worksheet.append(MASTER_SHEET_COLUMNS)
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def make_row(
    *,
    claim_reference,
    external_po_ref="PO-1",
    facility_id="FACILITY-1",
    amount=10,
    currency="AED",
):
    values = {column: f"Value for {column}" for column in MASTER_SHEET_COLUMNS}
    values.update(
        {
            "Provider Name": "Test Provider",
            "Invoice #": "INV-1",
            "Payer Share CV": amount,
            "CV Currency": currency,
            "POID/Year": external_po_ref,
            "Provider reference No": facility_id,
            "Unique Transaction ID": claim_reference,
        }
    )
    return [values[column] for column in MASTER_SHEET_COLUMNS]


if __name__ == "__main__":
    unittest.main()
