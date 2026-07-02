from io import BytesIO

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate
from openpyxl import Workbook

from lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_batch.tpa_revenue_batch import (
    import_revenue_events,
    process_revenue_batch,
    validate_revenue_file,
)
from lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_recognition_run.tpa_revenue_recognition_run import (
    post_recognition_run,
    preview_recognition_run,
)
from lifeline_tpa.services.revenue_import import ENDORSEMENT_SHEET_REQUIRED_COLUMNS
from lifeline_tpa.setup.accounting import apply as apply_accounting_setup


class TestTPARevenueBatch(FrappeTestCase):
    def test_revenue_batch_processes_credit_note_schedule_and_recognition(self):
        apply_accounting_setup()
        settings = frappe.get_single("Lifeline TPA Settings")
        suffix = frappe.generate_hash(length=8)
        payer = _make_customer(f"Revenue Payer {suffix}")
        source_file = _make_source_file(
            f"revenue-{suffix}.xlsx",
            payer.customer_name,
        )

        batch = frappe.get_doc(
            {
                "doctype": "TPA Revenue Batch",
                "company": settings.company,
                "posting_date": nowdate(),
                "source_file": source_file.file_url,
            }
        ).insert(ignore_permissions=True)
        _attach_file_to_batch(source_file, batch)

        preview = validate_revenue_file(batch.name)
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["total_events"], 2)
        self.assertEqual(preview["total_deletion_events"], 1)
        self.assertEqual(preview["net_tpa_fee"], 0.99)

        result = import_revenue_events(batch.name)
        self.assertEqual(result["imported_events"], 2)

        batch.reload()
        batch.submit()
        batch.db_set("status", "Processing")
        processing = process_revenue_batch(batch.name, requested_by="Administrator")
        self.assertEqual(processing["status"], "Processed")
        self.assertEqual(processing["sales_invoice_count"], 1)
        self.assertEqual(processing["credit_note_count"], 1)

        events = frappe.get_all(
            "TPA Revenue Event",
            filters={"revenue_batch": batch.name},
            fields=[
                "name",
                "status",
                "sales_invoice",
                "sales_credit_note",
                "deferral_journal_entry",
                "tpa_fee",
            ],
            order_by="source_row_number asc",
        )
        self.assertEqual({event.status for event in events}, {"Processed"})
        self.assertTrue(events[0].sales_invoice)
        self.assertTrue(events[1].sales_credit_note)
        self.assertTrue(events[0].deferral_journal_entry)
        self.assertTrue(events[1].deferral_journal_entry)

        invoice = frappe.get_doc("Sales Invoice", events[0].sales_invoice)
        credit_note = frappe.get_doc("Sales Invoice", events[1].sales_credit_note)
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.is_return, 0)
        self.assertEqual(invoice.net_total, 15)
        if settings.revenue_sales_taxes_template:
            self.assertTrue(invoice.taxes)
            self.assertGreater(invoice.grand_total, invoice.net_total)
        self.assertEqual(credit_note.docstatus, 1)
        self.assertEqual(credit_note.is_return, 1)
        self.assertEqual(credit_note.net_total, -14.01)
        if settings.revenue_sales_taxes_template:
            self.assertTrue(credit_note.taxes)
            self.assertLess(credit_note.grand_total, credit_note.net_total)

        schedule_total = frappe.db.sql(
            """
            select sum(scheduled_amount)
            from `tabTPA Revenue Schedule`
            where revenue_batch = %s
            """,
            batch.name,
        )[0][0]
        self.assertEqual(round(schedule_total, 2), 0.99)

        run = frappe.get_doc(
            {
                "doctype": "TPA Revenue Recognition Run",
                "company": settings.company,
                "recognition_month": "2026-05-01",
                "posting_date": "2026-05-31",
            }
        ).insert(ignore_permissions=True)
        accrued = preview_recognition_run(run.name)
        self.assertGreater(accrued["total_schedule_rows"], 0)
        self.assertEqual(accrued["posted_amount"], 0.99)

        run.reload()
        run.submit()
        posted = post_recognition_run(run.name)
        self.assertEqual(posted["status"], "Posted")
        self.assertTrue(posted["journal_entry"])
        self.assertEqual(
            frappe.db.count(
                "TPA Revenue Schedule",
                {"recognition_run": run.name, "status": "Posted"},
            ),
            accrued["total_schedule_rows"],
        )


def _make_customer(customer_name):
    return frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": "Company",
            "customer_group": "Commercial",
            "territory": "United Arab Emirates",
        }
    ).insert(ignore_permissions=True)


def _make_source_file(file_name, payer_name):
    rows = [
        _make_row(payer_name, "Inception", "01-May-2026", 15),
        _make_row(payer_name, "Deletion", "25-May-2026", -14.01),
    ]
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "JBMT769532"
    worksheet.append([*ENDORSEMENT_SHEET_REQUIRED_COLUMNS, "EmployeeID", "MemberName"])
    for row in rows:
        worksheet.append(
            [
                row.get(column)
                for column in [*ENDORSEMENT_SHEET_REQUIRED_COLUMNS, "EmployeeID", "MemberName"]
            ]
        )
    output = BytesIO()
    workbook.save(output)
    return frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file_name,
            "is_private": 1,
            "content": output.getvalue(),
        }
    ).insert(ignore_permissions=True)


def _make_row(payer_name, endorsement_type, endorsement_date, tpa_fee):
    return {
        "EndorseYear": 2026,
        "EndorseMonth": "May",
        "payer": payer_name,
        "GroupName": "Group A",
        "PolicyNo": "POL-REVENUE-1",
        "PolicyStartDate": "01-May-2026",
        "PolicyStopDate": "30-Apr-2027",
        "EmployeeID": "EMP-1",
        "MemberName": "Member One",
        "CardNo": "REV-MEMBER-1",
        "MemberID": "REV-MEMBER-1",
        "EffDate_EndosDate": endorsement_date,
        "EndorsementType": endorsement_type,
        "TPA/Service Fees": tpa_fee,
    }


def _attach_file_to_batch(file_doc, batch):
    frappe.db.set_value(
        "File",
        file_doc.name,
        {
            "attached_to_doctype": batch.doctype,
            "attached_to_name": batch.name,
            "attached_to_field": "source_file",
        },
    )
