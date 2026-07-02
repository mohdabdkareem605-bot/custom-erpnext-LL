from io import BytesIO

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate
from openpyxl import Workbook

from lifeline_tpa.lifeline_tpa.doctype.claim_removal_batch.claim_removal_batch import (
    process_claim_removals,
    validate_removal_file,
)
from lifeline_tpa.services.claim_removal import REMOVAL_COLUMNS


class TestClaimRemovalBatch(FrappeTestCase):
    def test_removes_unprocessed_claim_without_accounting_documents(self):
        claim = _make_claim()
        removal_batch = _make_removal_batch(claim.claim_reference)

        result = validate_removal_file(removal_batch.name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["unprocessed_claims"], 1)

        removal_batch.reload()
        removal_batch.submit()
        removal_batch.db_set("status", "Processing")
        report = process_claim_removals(removal_batch.name, requested_by="Administrator")

        self.assertEqual(report["status"], "Processed")
        claim.reload()
        self.assertEqual(claim.claim_status, "Removed")
        self.assertEqual(claim.removal_batch, removal_batch.name)
        self.assertFalse(claim.purchase_debit_note)
        self.assertFalse(claim.sales_credit_note)

    def test_reverses_processed_claim_with_debit_and_credit_notes(self):
        claim = _make_processed_claim()
        removal_batch = _make_removal_batch(claim.claim_reference)

        result = validate_removal_file(removal_batch.name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["accounting_reversals"], 1)

        removal_batch.reload()
        removal_batch.submit()
        removal_batch.db_set("status", "Processing")
        report = process_claim_removals(removal_batch.name, requested_by="Administrator")

        self.assertEqual(report["status"], "Processed")
        self.assertEqual(report["clearing_difference"], 0)
        claim.reload()
        self.assertEqual(claim.claim_status, "Removed")
        self.assertTrue(claim.purchase_debit_note)
        self.assertTrue(claim.sales_credit_note)
        self.assertEqual(
            frappe.db.get_value(
                "Purchase Invoice",
                claim.purchase_debit_note,
                [
                    "docstatus",
                    "is_return",
                    "return_against",
                    "disable_rounded_total",
                    "grand_total",
                    "outstanding_amount",
                ],
            ),
            (
                1,
                1,
                claim.purchase_invoice,
                1,
                -claim.claim_amount,
                -claim.claim_amount,
            ),
        )
        self.assertEqual(
            frappe.db.get_value(
                "Sales Invoice",
                claim.sales_credit_note,
                [
                    "docstatus",
                    "is_return",
                    "return_against",
                    "disable_rounded_total",
                    "grand_total",
                    "outstanding_amount",
                ],
            ),
            (
                1,
                1,
                claim.sales_invoice,
                1,
                -claim.claim_amount,
                -claim.claim_amount,
            ),
        )

    def test_reverses_legacy_aggregated_invoice_by_claim_amount(self):
        claim = _make_processed_claim(legacy=True)
        removal_batch = _make_removal_batch(claim.claim_reference)

        result = validate_removal_file(removal_batch.name)
        self.assertTrue(result["valid"])
        removal_batch.reload()
        self.assertEqual(
            removal_batch.claims[0].processing_mode,
            "Legacy Accounting Reversal",
        )

        removal_batch.submit()
        removal_batch.db_set("status", "Processing")
        report = process_claim_removals(removal_batch.name, requested_by="Administrator")

        self.assertEqual(report["status"], "Processed")
        claim.reload()
        self.assertEqual(
            abs(
                frappe.db.get_value(
                    "Purchase Invoice",
                    claim.purchase_debit_note,
                    "grand_total",
                )
            ),
            claim.claim_amount,
        )
        self.assertEqual(
            frappe.db.get_value(
                "Purchase Invoice",
                claim.purchase_debit_note,
                ["disable_rounded_total", "rounding_adjustment"],
            ),
            (1, 0),
        )
        self.assertEqual(
            abs(
                frappe.db.get_value(
                    "Sales Invoice",
                    claim.sales_credit_note,
                    "grand_total",
                )
            ),
            claim.claim_amount,
        )
        self.assertEqual(
            frappe.db.get_value(
                "Sales Invoice",
                claim.sales_credit_note,
                ["disable_rounded_total", "rounding_adjustment"],
            ),
            (1, 0),
        )


def _make_claim():
    suffix = frappe.generate_hash(length=8)
    po_batch = frappe.get_all("Claims PO Batch", pluck="name", limit=1)[0]
    batch = frappe.get_doc("Claims PO Batch", po_batch)
    provider = frappe.get_all("Supplier", pluck="name", limit=1)[0]
    return frappe.get_doc(
        {
            "doctype": "Claim Record",
            "claim_reference": f"REMOVE-{suffix}",
            "po_batch": batch.name,
            "external_po_ref": batch.external_po_ref,
            "source_row_number": 999999,
            "payer": batch.payer,
            "provider": provider,
            "facility_id": f"REMOVE-{suffix}",
            "claim_amount": 25.5,
            "currency": batch.currency,
            "payer_outstanding_amount": 25.5,
            "provider_outstanding_amount": 25.5,
            "source_data_json": "{}",
        }
    ).insert(ignore_permissions=True)


def _make_processed_claim(legacy=False):
    claim = _make_claim()
    settings = frappe.get_single("Lifeline TPA Settings")
    suffix = frappe.generate_hash(length=8)
    invoice_amount = 40 if legacy else claim.claim_amount
    purchase_invoice = frappe.get_doc(
        {
            "doctype": "Purchase Invoice",
            "company": settings.company,
            "supplier": claim.provider,
            "posting_date": nowdate(),
            "due_date": nowdate(),
            "bill_no": f"TEST-REMOVE-{suffix}",
            "bill_date": nowdate(),
            "currency": claim.currency,
            "credit_to": settings.claims_payable_account,
            "cost_center": settings.default_cost_center,
            "items": [
                {
                    "item_code": settings.medical_claim_item,
                    "qty": 1,
                    "rate": invoice_amount,
                    "description": f"Medical claim {claim.claim_reference}",
                    "expense_account": settings.claims_clearing_account,
                    "cost_center": settings.default_cost_center,
                }
            ],
        }
    ).insert(ignore_permissions=True)
    purchase_invoice.submit()

    sales_invoice = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "company": settings.company,
            "customer": claim.payer,
            "posting_date": nowdate(),
            "due_date": nowdate(),
            "currency": claim.currency,
            "debit_to": settings.claims_receivable_account,
            "cost_center": settings.default_cost_center,
            "items": [
                {
                    "item_code": settings.medical_claim_item,
                    "qty": 1,
                    "rate": invoice_amount,
                    "description": f"Medical claim {claim.claim_reference}",
                    "income_account": settings.claims_clearing_account,
                    "cost_center": settings.default_cost_center,
                }
            ],
        }
    ).insert(ignore_permissions=True)
    sales_invoice.submit()

    frappe.db.set_value(
        "Claim Record",
        claim.name,
        {
            "purchase_invoice": purchase_invoice.name,
            "purchase_invoice_item": (
                None if legacy else purchase_invoice.items[0].name
            ),
            "process_payable_number": purchase_invoice.name,
            "sales_invoice": sales_invoice.name,
            "sales_invoice_item": None if legacy else sales_invoice.items[0].name,
        },
    )
    claim.reload()
    return claim


def _make_removal_batch(claim_reference):
    company = frappe.get_single("Lifeline TPA Settings").company
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": f"claim-removal-{frappe.generate_hash(length=8)}.xlsx",
            "is_private": 1,
            "content": _removal_workbook(claim_reference),
        }
    ).insert(ignore_permissions=True)
    batch = frappe.get_doc(
        {
            "doctype": "Claim Removal Batch",
            "company": company,
            "posting_date": nowdate(),
            "source_file": file_doc.file_url,
        }
    ).insert(ignore_permissions=True)
    file_doc.db_set(
        {
            "attached_to_doctype": batch.doctype,
            "attached_to_name": batch.name,
            "attached_to_field": "source_file",
        }
    )
    return batch


def _removal_workbook(claim_reference):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Claim Removals"
    sheet.append(REMOVAL_COLUMNS)
    sheet.append(
        [
            claim_reference,
            "Approved test removal",
            "TEST-APPROVAL",
            nowdate(),
        ]
    )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
