import unittest
from io import BytesIO

from openpyxl import Workbook

from lifeline_tpa.services.revenue_import import (
    ENDORSEMENT_SHEET_REQUIRED_COLUMNS,
    parse_revenue_workbook,
    validate_revenue_workbook,
)


class TestRevenueImport(unittest.TestCase):
    def test_validates_inception_addition_deletion_and_allowed_duplicate(self):
        content = make_revenue_workbook(
            [
                make_row(member_id="M-1", endorsement_type="Inception", tpa_fee=15),
                make_row(
                    member_id="M-1",
                    endorsement_type="Deletion",
                    endorsement_date="25-May-2026",
                    tpa_fee=-14.01,
                ),
                make_row(
                    member_id="M-2",
                    endorsement_type="Addition",
                    endorsement_date="05-May-2026",
                    policy_start="16-Oct-2025",
                    policy_stop="15-Oct-2026",
                    tpa_fee=24.71,
                ),
            ]
        )

        parsed = parse_revenue_workbook(content)
        result = validate_revenue_workbook(
            parsed,
            customer_by_payer_name={"Al Sagr National Insurance Co. (PSC)": "Al Sagr"},
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(
            result.workbook.net_fee,
            parsed.events[0].tpa_fee
            + parsed.events[1].tpa_fee
            + parsed.events[2].tpa_fee,
        )
        self.assertEqual(result.as_dict()["total_events"], 3)
        self.assertEqual(result.as_dict()["total_deletion_events"], 1)

    def test_rejects_duplicate_member_without_deletion(self):
        content = make_revenue_workbook(
            [
                make_row(member_id="M-1", endorsement_type="Inception", tpa_fee=15),
                make_row(member_id="M-1", endorsement_type="Addition", tpa_fee=10),
            ]
        )

        parsed = parse_revenue_workbook(content)

        self.assertIn("invalid_duplicate_member", [issue.code for issue in parsed.issues])

    def test_rejects_invalid_fee_sign_and_unknown_payer(self):
        content = make_revenue_workbook(
            [make_row(endorsement_type="Deletion", tpa_fee=10)]
        )

        parsed = parse_revenue_workbook(content)
        result = validate_revenue_workbook(parsed, customer_by_payer_name={})
        issue_codes = [issue.code for issue in result.issues]

        self.assertIn("invalid_tpa_fee_sign", issue_codes)
        self.assertIn("unknown_payer", issue_codes)

    def test_rejects_missing_required_columns(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["MemberID"])
        worksheet.append(["M-1"])
        output = BytesIO()
        workbook.save(output)

        parsed = parse_revenue_workbook(output.getvalue())

        self.assertIn("missing_required_columns", [issue.code for issue in parsed.issues])


def make_revenue_workbook(rows):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "JBMT769532"
    worksheet.append([*ENDORSEMENT_SHEET_REQUIRED_COLUMNS, "EmployeeID", "MemberName"])
    for row in rows:
        worksheet.append(
            [
                row.get(column)
                for column in [
                    *ENDORSEMENT_SHEET_REQUIRED_COLUMNS,
                    "EmployeeID",
                    "MemberName",
                ]
            ]
        )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def make_row(
    *,
    member_id="M-1",
    card_no=None,
    payer="Al Sagr National Insurance Co. (PSC)",
    endorsement_type="Inception",
    endorsement_date="01-May-2026",
    policy_start="01-May-2026",
    policy_stop="30-Apr-2027",
    tpa_fee=15,
):
    return {
        "EndorseYear": 2026,
        "EndorseMonth": "May",
        "payer": payer,
        "GroupName": "Group A",
        "PolicyNo": "POL-1",
        "PolicyStartDate": policy_start,
        "PolicyStopDate": policy_stop,
        "EmployeeID": "EMP-1",
        "MemberName": "Member One",
        "CardNo": card_no or member_id,
        "MemberID": member_id,
        "EffDate_EndosDate": endorsement_date,
        "EndorsementType": endorsement_type,
        "TPA/Service Fees": tpa_fee,
    }


if __name__ == "__main__":
    unittest.main()
