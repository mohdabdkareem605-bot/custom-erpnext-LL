from io import BytesIO

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate
from openpyxl import Workbook

from lifeline_tpa.lifeline_tpa.doctype.payer_receipt_settlement.payer_receipt_settlement import (
    process_receipt_settlement,
    validate_receipt_file,
)
from lifeline_tpa.lifeline_tpa.doctype.provider_payment_settlement.provider_payment_settlement import (
    process_payment_settlement,
    validate_payment_file,
)
from lifeline_tpa.services.settlement_upload import (
    PAYER_RECEIPT_COLUMNS,
    PROVIDER_PAYMENT_COLUMNS,
)


class TestSettlementUploads(FrappeTestCase):
    def test_payer_receipt_creates_payment_entry_and_updates_claim(self):
        claim = _make_processed_claim()
        bank_account = _get_bank_account()
        settlement = _make_payer_receipt_settlement(
            claim,
            bank_account,
            amount=10,
        )

        result = validate_receipt_file(settlement.name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["total_claims"], 1)
        self.assertEqual(result["total_amount"], 10)

        settlement.reload()
        settlement.submit()
        report = process_receipt_settlement(settlement.name)

        self.assertEqual(report["status"], "Processed")
        claim.reload()
        self.assertEqual(claim.payer_allocated_amount, 10)
        self.assertEqual(claim.payer_outstanding_amount, 15.5)
        self.assertEqual(claim.payer_settlement_status, "Partially Paid")
        self.assertTrue(claim.payer_payment_reference)
        self.assertEqual(claim.payer_payment_date, settlement.posting_date)
        self.assertEqual(
            frappe.db.get_value(
                "Payment Entry",
                claim.payer_payment_reference,
                ["docstatus", "payment_type", "party", "paid_to", "paid_amount"],
            ),
            (1, "Receive", claim.payer, bank_account, 10),
        )
        self.assertEqual(
            frappe.db.get_value(
                "Payment Entry Reference",
                {
                    "parent": claim.payer_payment_reference,
                    "reference_doctype": "Sales Invoice",
                    "reference_name": claim.sales_invoice,
                },
                "allocated_amount",
            ),
            10,
        )

    def test_provider_payment_groups_and_updates_claims(self):
        first_claim = _make_processed_claim()
        second_claim = _make_processed_claim(
            po_batch=first_claim.po_batch,
            payer=first_claim.payer,
            provider=first_claim.provider,
        )
        bank_account = _get_bank_account()
        settlement = _make_provider_payment_settlement(
            [
                (first_claim.claim_reference, 5, bank_account, "TT-GROUP-1"),
                (second_claim.claim_reference, 7, bank_account, "TT-GROUP-1"),
            ]
        )

        result = validate_payment_file(settlement.name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["total_claims"], 2)
        self.assertEqual(result["total_amount"], 12)

        settlement.reload()
        settlement.submit()
        report = process_payment_settlement(settlement.name)

        self.assertEqual(report["status"], "Processed")
        self.assertEqual(len(report["payment_entries"]), 1)
        payment_entry = report["payment_entries"][0]["payment_entry"]
        self.assertEqual(
            frappe.db.get_value(
                "Payment Entry",
                payment_entry,
                ["docstatus", "payment_type", "party", "paid_from", "reference_no"],
            ),
            (1, "Pay", first_claim.provider, bank_account, "TT-GROUP-1"),
        )
        first_claim.reload()
        second_claim.reload()
        self.assertEqual(first_claim.provider_paid_amount, 5)
        self.assertEqual(first_claim.provider_outstanding_amount, 20.5)
        self.assertEqual(first_claim.provider_settlement_status, "Partially Paid")
        self.assertEqual(first_claim.provider_payment_reference, "TT-GROUP-1")
        self.assertEqual(second_claim.provider_paid_amount, 7)
        self.assertEqual(second_claim.provider_outstanding_amount, 18.5)
        self.assertEqual(first_claim.payer_allocated_amount, 0)
        self.assertEqual(first_claim.payer_settlement_status, "Unpaid")

    def test_provider_payment_can_fully_settle_claim(self):
        claim = _make_processed_claim()
        bank_account = _get_bank_account()
        settlement = _make_provider_payment_settlement(
            [
                (
                    claim.claim_reference,
                    claim.provider_outstanding_amount,
                    bank_account,
                    "TT-FULL-PROVIDER",
                )
            ],
            provider=claim.provider,
        )

        result = validate_payment_file(settlement.name)
        self.assertTrue(result["valid"])

        settlement.reload()
        settlement.submit()
        report = process_payment_settlement(settlement.name)

        self.assertEqual(report["status"], "Processed")
        claim.reload()
        self.assertEqual(claim.provider_paid_amount, claim.claim_amount)
        self.assertEqual(claim.provider_outstanding_amount, 0)
        self.assertEqual(claim.provider_settlement_status, "Paid")
        self.assertEqual(claim.provider_payment_reference, "TT-FULL-PROVIDER")
        self.assertEqual(claim.payer_allocated_amount, 0)
        self.assertEqual(claim.payer_settlement_status, "Unpaid")
        self.assertEqual(
            frappe.db.get_value(
                "Payment Entry Reference",
                {
                    "parent": report["payment_entries"][0]["payment_entry"],
                    "reference_doctype": "Purchase Invoice",
                    "reference_name": claim.purchase_invoice,
                },
                "allocated_amount",
            ),
            claim.claim_amount,
        )

    def test_provider_payment_validates_selected_provider(self):
        claim = _make_processed_claim()
        other_provider = _make_supplier(
            f"Other Provider {frappe.generate_hash(length=8)}"
        )
        bank_account = _get_bank_account()
        settlement = _make_provider_payment_settlement(
            [(claim.claim_reference, 5, bank_account, "TT-WRONG-PROVIDER")],
            provider=other_provider.name,
        )

        result = validate_payment_file(settlement.name)

        self.assertFalse(result["valid"])
        self.assertIn(
            "provider_mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_provider_payment_accepts_matching_selected_provider(self):
        claim = _make_processed_claim()
        bank_account = _get_bank_account()
        settlement = _make_provider_payment_settlement(
            [(claim.claim_reference, 5, bank_account, "TT-MATCHED-PROVIDER")],
            provider=claim.provider,
        )

        result = validate_payment_file(settlement.name)

        self.assertTrue(result["valid"])
        self.assertEqual(settlement.reload().claims[0].provider, claim.provider)

    def test_validation_rejects_invalid_bank_and_overpayment(self):
        claim = _make_processed_claim()
        settlement = _make_payer_receipt_settlement(
            claim,
            "Not A Bank - LL",
            amount=999,
        )

        result = validate_receipt_file(settlement.name)

        self.assertFalse(result["valid"])
        codes = {error["code"] for error in result["errors"]}
        self.assertIn("invalid_bank_account", codes)
        self.assertIn("amount_exceeds_outstanding", codes)


def _make_processed_claim(po_batch=None, payer=None, provider=None):
    settings = frappe.get_single("Lifeline TPA Settings")
    suffix = frappe.generate_hash(length=8)
    payer = payer or _make_customer(f"Settlement Payer {suffix}").name
    provider = provider or _make_supplier(f"Settlement Provider {suffix}").name
    po_batch = po_batch or _make_po_batch(settings.company, payer).name

    claim = frappe.get_doc(
        {
            "doctype": "Claim Record",
            "claim_reference": f"SETTLE-{suffix}",
            "po_batch": po_batch,
            "external_po_ref": f"PO-SETTLE-{suffix}",
            "source_row_number": 900000,
            "payer": payer,
            "provider": provider,
            "facility_id": f"SETTLE-FAC-{suffix}",
            "provider_name_as_received": provider,
            "provider_invoice_number": f"PINV-SRC-{suffix}",
            "claim_amount": 25.5,
            "currency": "AED",
            "payer_outstanding_amount": 25.5,
            "provider_outstanding_amount": 25.5,
            "source_data_json": "{}",
        }
    ).insert(ignore_permissions=True)

    purchase_invoice = frappe.get_doc(
        {
            "doctype": "Purchase Invoice",
            "company": settings.company,
            "supplier": provider,
            "posting_date": nowdate(),
            "due_date": nowdate(),
            "bill_no": f"TEST-SETTLE-{suffix}",
            "bill_date": nowdate(),
            "currency": claim.currency,
            "disable_rounded_total": 1,
            "credit_to": settings.claims_payable_account,
            "cost_center": settings.default_cost_center,
            "items": [
                {
                    "item_code": settings.medical_claim_item,
                    "qty": 1,
                    "rate": claim.claim_amount,
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
            "customer": payer,
            "posting_date": nowdate(),
            "due_date": nowdate(),
            "currency": claim.currency,
            "disable_rounded_total": 1,
            "debit_to": settings.claims_receivable_account,
            "cost_center": settings.default_cost_center,
            "items": [
                {
                    "item_code": settings.medical_claim_item,
                    "qty": 1,
                    "rate": claim.claim_amount,
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
            "purchase_invoice_item": purchase_invoice.items[0].name,
            "process_payable_number": purchase_invoice.name,
            "sales_invoice": sales_invoice.name,
            "sales_invoice_item": sales_invoice.items[0].name,
        },
    )
    claim.reload()
    return claim


def _make_payer_receipt_settlement(claim, bank_account, amount):
    file_doc = _make_file(
        f"payer-receipt-{frappe.generate_hash(length=8)}.xlsx",
        PAYER_RECEIPT_COLUMNS,
        [[claim.claim_reference, amount, bank_account]],
    )
    settlement = frappe.get_doc(
        {
            "doctype": "Payer Receipt Settlement",
            "company": frappe.get_single("Lifeline TPA Settings").company,
            "payer": claim.payer,
            "po_batch": claim.po_batch,
            "posting_date": nowdate(),
            "source_file": file_doc.file_url,
        }
    ).insert(ignore_permissions=True)
    _attach_file(file_doc, settlement)
    return settlement


def _make_provider_payment_settlement(rows, provider=None):
    file_doc = _make_file(
        f"provider-payment-{frappe.generate_hash(length=8)}.xlsx",
        PROVIDER_PAYMENT_COLUMNS,
        rows,
    )
    settlement = frappe.get_doc(
        {
            "doctype": "Provider Payment Settlement",
            "company": frappe.get_single("Lifeline TPA Settings").company,
            "provider": provider,
            "posting_date": nowdate(),
            "source_file": file_doc.file_url,
        }
    ).insert(ignore_permissions=True)
    _attach_file(file_doc, settlement)
    return settlement


def _make_po_batch(company, payer):
    file_doc = _make_file(
        f"settlement-po-{frappe.generate_hash(length=8)}.xlsx",
        ["placeholder"],
        [["placeholder"]],
    )
    batch = frappe.get_doc(
        {
            "doctype": "Claims PO Batch",
            "company": company,
            "payer": payer,
            "posting_date": nowdate(),
            "source_file": file_doc.file_url,
        }
    ).insert(ignore_permissions=True)
    _attach_file(file_doc, batch)
    batch.db_set(
        {
            "external_po_ref": f"PO-SETTLE-{frappe.generate_hash(length=8)}",
            "currency": "AED",
            "status": "Processed",
            "total_claims": 1,
            "total_providers": 1,
            "total_amount": 25.5,
        }
    )
    batch.submit()
    return batch


def _make_file(file_name, headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
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


def _attach_file(file_doc, doc):
    file_doc.db_set(
        {
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
            "attached_to_field": "source_file",
        }
    )


def _get_bank_account():
    company = frappe.get_single("Lifeline TPA Settings").company
    return frappe.get_all(
        "Account",
        filters={
            "company": company,
            "account_type": ["in", ["Bank", "Cash"]],
            "is_group": 0,
        },
        pluck="name",
        limit=1,
    )[0]


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


def _make_supplier(supplier_name):
    return frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": supplier_name,
            "supplier_group": "Services",
            "supplier_type": "Company",
        }
    ).insert(ignore_permissions=True)
