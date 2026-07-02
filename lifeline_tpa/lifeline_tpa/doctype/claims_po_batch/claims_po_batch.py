import json
import re

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime

from lifeline_tpa.services.bulk_processing import (
    BulkClaim,
    group_claims_for_bulk_processing,
    summarize_bulk_groups,
)
from lifeline_tpa.services.po_import import parse_workbook, validate_parsed_workbook
from lifeline_tpa.services.processed_po_export import build_processed_po_workbook


BULK_PROCESSING_METHOD = (
    "lifeline_tpa.lifeline_tpa.doctype.claims_po_batch.claims_po_batch."
    "process_bulk_claims"
)


class ClaimsPOBatch(Document):
    def validate(self):
        self._validate_source_file()
        self._prevent_source_replacement()
        self._validate_dates()

    def _validate_source_file(self):
        if self.source_file and not self.source_file.lower().endswith(".xlsx"):
            frappe.throw("The PO source file must be an .xlsx workbook.")

    def _prevent_source_replacement(self):
        previous = self.get_doc_before_save()
        if (
            previous
            and previous.source_file
            and previous.source_file != self.source_file
            and previous.status != "Draft"
        ):
            frappe.throw("The source workbook cannot be replaced after validation has started.")

    def _validate_dates(self):
        if self.posting_date and self.expected_payment_date:
            if getdate(self.expected_payment_date) < getdate(self.posting_date):
                frappe.throw("Expected Payment Date cannot be before Posting Date.")


@frappe.whitelist()
def validate_po_file(batch_name):
    batch = frappe.get_doc("Claims PO Batch", batch_name)
    batch.check_permission("write")

    if batch.docstatus != 0:
        frappe.throw("Only a draft Claims PO Batch can be validated.")

    batch.db_set("status", "Validating", update_modified=False)
    try:
        result = _build_validation_result(batch)
        preview = result.as_dict()
        _store_validation_result(batch, preview)
        return preview
    except Exception:
        batch.db_set("status", "Validation Failed", update_modified=False)
        raise


@frappe.whitelist()
def import_claims(batch_name):
    batch = frappe.get_doc("Claims PO Batch", batch_name)
    batch.check_permission("write")

    if batch.docstatus != 0:
        frappe.throw("Only a draft Claims PO Batch can import claims.")
    if batch.status != "Validated":
        frappe.throw("Validate the PO file successfully before importing claims.")
    if frappe.db.exists("Claim Record", {"po_batch": batch.name}):
        frappe.throw("Claims were already imported for this batch.")

    result = _build_validation_result(batch)
    if not result.is_valid:
        preview = result.as_dict()
        _store_validation_result(batch, preview)
        frappe.throw("The workbook is no longer valid. Review the Validation Log.")

    for claim in result.workbook.claims:
        frappe.get_doc(
            {
                "doctype": "Claim Record",
                "claim_reference": claim.claim_reference,
                "po_batch": batch.name,
                "external_po_ref": claim.external_po_ref,
                "source_row_number": claim.row_number,
                "payer": batch.payer,
                "provider": result.provider_by_facility[claim.facility_id],
                "facility_id": claim.facility_id,
                "provider_name_as_received": claim.provider_name,
                "provider_invoice_number": claim.provider_invoice_number,
                "claim_amount": claim.amount,
                "currency": claim.currency,
                "payer_outstanding_amount": claim.amount,
                "provider_outstanding_amount": claim.amount,
                "source_data_json": json.dumps(
                    claim.source_data,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        ).insert(ignore_permissions=True)

    batch.db_set("status", "Imported")
    return {
        "imported_claims": len(result.workbook.claims),
        "batch_name": batch.name,
    }


@frappe.whitelist()
def download_processed_po(batch_name):
    batch = frappe.get_doc("Claims PO Batch", batch_name)
    batch.check_permission("read")

    content = _build_processed_po_export(batch)
    safe_reference = re.sub(r"[^A-Za-z0-9._-]+", "-", batch.external_po_ref or batch.name)
    frappe.local.response.filename = f"{safe_reference}-processed.xlsx"
    frappe.local.response.filecontent = content
    frappe.local.response.type = "download"


def _build_processed_po_export(batch):
    if batch.docstatus != 1:
        frappe.throw("Submit the Claims PO Batch before exporting it.")
    if batch.status not in ("Processed", "Partially Settled", "Fully Settled"):
        frappe.throw(
            "The processed PO export is available only after bulk processing is complete."
        )

    claims = frappe.get_all(
        "Claim Record",
        filters={"po_batch": batch.name},
        fields=[
            "claim_reference",
            "source_row_number",
            "source_data_json",
            "payer",
            "process_payable_number",
            "sales_invoice",
            "payer_allocated_amount",
            "payer_payment_reference",
            "payer_payment_date",
            "payer_settlement_status",
            "provider_paid_amount",
            "provider_payment_reference",
            "provider_payment_date",
            "provider_settlement_status",
        ],
        order_by="source_row_number asc",
        limit_page_length=0,
    )
    if len(claims) != batch.total_claims:
        frappe.throw(
            f"The batch contains {len(claims)} Claim Records but expects "
            f"{batch.total_claims}. Export stopped."
        )

    try:
        return build_processed_po_workbook(claims)
    except ValueError as exc:
        frappe.throw(str(exc))


@frappe.whitelist()
def preview_bulk_processing(batch_name):
    batch = frappe.get_doc("Claims PO Batch", batch_name)
    batch.check_permission("read")

    claims, groups, summary, settings = _get_bulk_processing_input(
        batch,
        allowed_statuses=("Imported",),
    )
    if any(claim.purchase_invoice or claim.sales_invoice for claim in claims):
        frappe.throw("This batch already contains claims linked to accounting invoices.")

    rows = []
    for group in groups:
        purchase_invoice = _build_purchase_invoice_preview(batch, group, settings)
        sales_invoice = _build_sales_invoice_preview(batch, group, settings)
        rows.append(
            {
                "facility_id": group.facility_id,
                "provider": group.provider,
                "claim_count": group.claim_count,
                "total_amount": float(group.total_amount),
                "purchase_invoice": purchase_invoice,
                "sales_invoice": sales_invoice,
                "difference": round(
                    purchase_invoice["grand_total"] - sales_invoice["grand_total"],
                    2,
                ),
            }
        )

    return {
        "batch_name": batch.name,
        "payer": batch.payer,
        "external_po_ref": batch.external_po_ref,
        "currency": batch.currency,
        **summary,
        "rows": rows,
        "posts_accounting_entries": False,
    }


@frappe.whitelist()
def enqueue_bulk_processing(batch_name):
    batch = frappe.get_doc("Claims PO Batch", batch_name)
    batch.check_permission("write")

    _get_bulk_processing_input(batch, allowed_statuses=("Imported", "Failed"))
    job_id = f"lifeline-tpa-bulk-{batch.name}"
    frappe.db.set_value(
        "Claims PO Batch",
        batch.name,
        {
            "status": "Processing",
            "background_job_id": job_id,
            "processing_log": json.dumps(
                {
                    "status": "Queued",
                    "batch_name": batch.name,
                    "job_id": job_id,
                    "queued_by": frappe.session.user,
                    "completed_groups": [],
                    "skipped_groups": [],
                    "failed_groups": [],
                },
                indent=2,
            ),
        },
    )
    frappe.enqueue(
        BULK_PROCESSING_METHOD,
        queue="long",
        timeout=3600,
        job_id=job_id,
        deduplicate=True,
        enqueue_after_commit=True,
        batch_name=batch.name,
        requested_by=frappe.session.user,
    )
    return {
        "batch_name": batch.name,
        "job_id": job_id,
        "status": "Processing",
    }


def process_bulk_claims(batch_name, requested_by=None):
    batch = frappe.get_doc("Claims PO Batch", batch_name)
    report = {
        "status": "Processing",
        "batch_name": batch.name,
        "job_id": batch.background_job_id,
        "requested_by": requested_by,
        "provider_count": 0,
        "claim_count": 0,
        "purchase_total": 0,
        "sales_total": 0,
        "clearing_difference": None,
        "completed_groups": [],
        "skipped_groups": [],
        "failed_groups": [],
    }

    try:
        claims, groups, summary, settings = _get_bulk_processing_input(
            batch,
            allowed_statuses=("Processing", "Failed"),
        )
        report.update(summary)
        claim_by_reference = {claim.claim_reference: claim for claim in claims}

        for index, group in enumerate(groups, start=1):
            group_claims = [
                claim_by_reference[reference]
                for reference in group.claim_references
            ]
            savepoint = f"bulk_provider_{index}"
            frappe.db.savepoint(savepoint)
            try:
                existing_pair = _get_existing_invoice_pair(
                    batch,
                    group,
                    group_claims,
                    settings,
                )
                if existing_pair:
                    report["skipped_groups"].append(
                        _group_result(
                            group,
                            *existing_pair,
                            status="Already Processed",
                        )
                    )
                    _store_processing_report(batch.name, report)
                    _commit()
                    continue

                purchase_invoice = _make_purchase_invoice(batch, group, settings)
                purchase_invoice.insert(ignore_permissions=True)
                purchase_invoice.submit()

                sales_invoice = _make_sales_invoice(batch, group, settings)
                sales_invoice.insert(ignore_permissions=True)
                sales_invoice.submit()

                _validate_posted_invoice_pair(group, purchase_invoice, sales_invoice)
                _link_claims_to_invoices(
                    group_claims,
                    purchase_invoice,
                    sales_invoice,
                )
                _commit()
                report["completed_groups"].append(
                    _group_result(
                        group,
                        purchase_invoice.name,
                        sales_invoice.name,
                        status="Completed",
                    )
                )
            except Exception as exc:
                frappe.db.rollback(save_point=savepoint)
                report["failed_groups"].append(
                    {
                        "facility_id": group.facility_id,
                        "provider": group.provider,
                        "claim_count": group.claim_count,
                        "total_amount": float(group.total_amount),
                        "error": str(exc),
                    }
                )
                frappe.log_error(
                    title=f"Bulk processing failed for {batch.name} / {group.facility_id}",
                    message=frappe.get_traceback(),
                )

            _store_processing_report(batch.name, report)
            _commit()

        report["clearing_difference"] = _get_batch_clearing_difference(
            batch.name,
            settings.claims_clearing_account,
        )
        if abs(report["clearing_difference"]) > 0.005:
            report["failed_groups"].append(
                {
                    "facility_id": None,
                    "provider": None,
                    "error": (
                        "The posted Purchase and Sales Invoice entries do not clear to zero. "
                        f"Difference: {report['clearing_difference']}"
                    ),
                }
            )

        linked_claim_count = frappe.db.count(
            "Claim Record",
            filters={
                "po_batch": batch.name,
                "claim_status": "Active",
                "purchase_invoice": ["is", "set"],
                "sales_invoice": ["is", "set"],
            },
        )
        if linked_claim_count != summary["claim_count"]:
            report["failed_groups"].append(
                {
                    "facility_id": None,
                    "provider": None,
                    "error": (
                        f"Only {linked_claim_count} of {summary['claim_count']} active claims "
                        "are linked to both accounting invoices."
                    ),
                }
            )

        report["status"] = "Failed" if report["failed_groups"] else "Processed"
        values = {
            "status": report["status"],
            "clearing_difference": report["clearing_difference"],
            "processing_log": json.dumps(report, indent=2, ensure_ascii=False),
        }
        if report["status"] == "Processed":
            values.update(
                {
                    "processed_by": requested_by or frappe.session.user,
                    "processed_date": now_datetime(),
                }
            )
        frappe.db.set_value("Claims PO Batch", batch.name, values)
        _commit()
        return report
    except Exception as exc:
        frappe.db.rollback()
        report["status"] = "Failed"
        report["failed_groups"].append(
            {
                "facility_id": None,
                "provider": None,
                "error": str(exc),
            }
        )
        frappe.db.set_value(
            "Claims PO Batch",
            batch.name,
            {
                "status": "Failed",
                "processing_log": json.dumps(report, indent=2, ensure_ascii=False),
            },
        )
        _commit()
        frappe.log_error(
            title=f"Bulk processing failed for {batch.name}",
            message=frappe.get_traceback(),
        )
        raise


def _get_bulk_processing_input(batch, allowed_statuses):
    if batch.docstatus != 1:
        frappe.throw("Submit the Claims PO Batch before running bulk processing.")
    if batch.status not in allowed_statuses:
        frappe.throw(
            "Bulk processing is not available while the batch status is "
            f"{batch.status}."
        )

    settings = _get_accounting_settings(batch.company)
    claims = frappe.get_all(
        "Claim Record",
        filters={
            "po_batch": batch.name,
            "claim_status": "Active",
        },
        fields=[
            "name",
            "claim_reference",
            "facility_id",
            "provider",
            "claim_amount",
            "purchase_invoice",
            "purchase_invoice_item",
            "process_payable_number",
            "sales_invoice",
            "sales_invoice_item",
        ],
        order_by="source_row_number asc",
        limit_page_length=0,
    )
    if not claims:
        frappe.throw("This batch has no active Claim Records.")

    try:
        groups = group_claims_for_bulk_processing(
            [
                BulkClaim(
                    claim_reference=claim.claim_reference,
                    facility_id=claim.facility_id,
                    provider=claim.provider,
                    amount=claim.claim_amount,
                )
                for claim in claims
            ]
        )
    except ValueError as exc:
        frappe.throw(str(exc))

    summary = summarize_bulk_groups(groups)
    removed_totals = frappe.get_all(
        "Claim Record",
        filters={
            "po_batch": batch.name,
            "claim_status": "Removed",
        },
        fields=["count(name) as claim_count", "sum(claim_amount) as total_amount"],
        limit_page_length=1,
    )[0]
    removed_claim_count = int(removed_totals.claim_count or 0)
    removed_amount = flt(removed_totals.total_amount)
    if summary["claim_count"] + removed_claim_count != batch.total_claims:
        frappe.throw(
            "The active and removed Claim Record count does not match the batch total."
        )
    if abs(summary["purchase_total"] + removed_amount - batch.total_amount) > 0.005:
        frappe.throw(
            "The active and removed Claim Record amount does not match the batch total."
        )
    return claims, groups, summary, settings


def _get_accounting_settings(company):
    settings = frappe.get_single("Lifeline TPA Settings")
    required_fields = {
        "company": settings.company,
        "claims_receivable_account": settings.claims_receivable_account,
        "claims_payable_account": settings.claims_payable_account,
        "claims_clearing_account": settings.claims_clearing_account,
        "medical_claim_item": settings.medical_claim_item,
        "default_cost_center": settings.default_cost_center,
    }
    missing = [label for label, value in required_fields.items() if not value]
    if missing:
        frappe.throw(
            "Complete Lifeline TPA Settings before bulk processing: "
            + ", ".join(missing)
            + "."
        )
    if settings.company != company:
        frappe.throw("Lifeline TPA Settings belongs to a different Company.")
    return settings


def _build_purchase_invoice_preview(batch, group, settings):
    doc = _make_purchase_invoice(batch, group, settings, preview=True)
    _validate_invoice_preview(doc)
    return _invoice_summary(doc)


def _build_sales_invoice_preview(batch, group, settings):
    doc = _make_sales_invoice(batch, group, settings, preview=True)
    _validate_invoice_preview(doc)
    return _invoice_summary(doc)


def _make_purchase_invoice(batch, group, settings, preview=False):
    action = "preview" if preview else "bulk processing"
    return frappe.get_doc(
        {
            "doctype": "Purchase Invoice",
            "company": batch.company,
            "supplier": group.provider,
            "posting_date": batch.posting_date,
            "due_date": batch.expected_payment_date or batch.posting_date,
            "bill_no": f"{batch.external_po_ref}-{group.facility_id}",
            "bill_date": batch.posting_date,
            "currency": batch.currency,
            "disable_rounded_total": 1,
            "credit_to": settings.claims_payable_account,
            "cost_center": settings.default_cost_center,
            "remarks": (
                f"Lifeline TPA {action} for {batch.name}, "
                f"facility {group.facility_id}."
            ),
            "items": [
                {
                    "item_code": settings.medical_claim_item,
                    "qty": 1,
                    "rate": claim.amount,
                    "description": f"Medical claim {claim.claim_reference}",
                    "expense_account": settings.claims_clearing_account,
                    "cost_center": settings.default_cost_center,
                }
                for claim in group.claim_lines
            ],
        }
    )


def _make_sales_invoice(batch, group, settings, preview=False):
    action = "preview" if preview else "bulk processing"
    return frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "company": batch.company,
            "customer": batch.payer,
            "posting_date": batch.posting_date,
            "due_date": batch.expected_payment_date or batch.posting_date,
            "currency": batch.currency,
            "disable_rounded_total": 1,
            "debit_to": settings.claims_receivable_account,
            "cost_center": settings.default_cost_center,
            "remarks": (
                f"Lifeline TPA {action} for {batch.name}, "
                f"facility {group.facility_id}."
            ),
            "items": [
                {
                    "item_code": settings.medical_claim_item,
                    "qty": 1,
                    "rate": claim.amount,
                    "description": f"Medical claim {claim.claim_reference}",
                    "income_account": settings.claims_clearing_account,
                    "cost_center": settings.default_cost_center,
                }
                for claim in group.claim_lines
            ],
        }
    )


def _get_existing_invoice_pair(batch, group, claims, settings):
    pairs = {
        (claim.purchase_invoice, claim.sales_invoice)
        for claim in claims
        if claim.purchase_invoice or claim.sales_invoice
    }
    if not pairs:
        return None
    if len(pairs) != 1 or any(not value for value in next(iter(pairs))):
        frappe.throw(
            f"Facility {group.facility_id} contains incomplete or inconsistent invoice links."
        )

    purchase_invoice, sales_invoice = next(iter(pairs))
    if any(
        claim.purchase_invoice != purchase_invoice
        or not claim.purchase_invoice_item
        or claim.process_payable_number != purchase_invoice
        or claim.sales_invoice != sales_invoice
        or not claim.sales_invoice_item
        for claim in claims
    ):
        frappe.throw(
            f"Facility {group.facility_id} contains incomplete or inconsistent invoice links."
        )
    purchase_doc = frappe.get_doc("Purchase Invoice", purchase_invoice)
    sales_doc = frappe.get_doc("Sales Invoice", sales_invoice)
    if purchase_doc.docstatus != 1:
        frappe.throw(f"Purchase Invoice {purchase_invoice} is not submitted.")
    if sales_doc.docstatus != 1:
        frappe.throw(f"Sales Invoice {sales_invoice} is not submitted.")
    if purchase_doc.company != batch.company or sales_doc.company != batch.company:
        frappe.throw(
            f"Facility {group.facility_id} is linked to invoices from another Company."
        )
    if purchase_doc.supplier != group.provider or sales_doc.customer != batch.payer:
        frappe.throw(
            f"Facility {group.facility_id} is linked to invoices for the wrong party."
        )
    if purchase_doc.currency != batch.currency or sales_doc.currency != batch.currency:
        frappe.throw(
            f"Facility {group.facility_id} is linked to invoices in the wrong currency."
        )
    if any(
        item.expense_account != settings.claims_clearing_account
        for item in purchase_doc.items
    ) or any(
        item.income_account != settings.claims_clearing_account
        for item in sales_doc.items
    ):
        frappe.throw(
            f"Facility {group.facility_id} is linked to invoices using the wrong clearing account."
        )
    _validate_posted_invoice_pair(group, purchase_doc, sales_doc)
    return purchase_invoice, sales_invoice


def _validate_posted_invoice_pair(group, purchase_invoice, sales_invoice):
    expected = float(group.total_amount)
    if abs(flt(purchase_invoice.grand_total) - expected) > 0.005:
        frappe.throw(
            f"Purchase Invoice total for facility {group.facility_id} does not match its claims."
        )
    if abs(flt(sales_invoice.grand_total) - expected) > 0.005:
        frappe.throw(
            f"Sales Invoice total for facility {group.facility_id} does not match its claims."
        )
    if abs(flt(purchase_invoice.grand_total) - flt(sales_invoice.grand_total)) > 0.005:
        frappe.throw(
            f"Purchase and Sales Invoice totals differ for facility {group.facility_id}."
        )


def _link_claims_to_invoices(claims, purchase_invoice, sales_invoice):
    if len(claims) != len(purchase_invoice.items) or len(claims) != len(sales_invoice.items):
        frappe.throw("Invoice item count does not match the provider claim count.")

    for claim, purchase_item, sales_item in zip(
        claims,
        purchase_invoice.items,
        sales_invoice.items,
        strict=True,
    ):
        frappe.db.set_value(
            "Claim Record",
            claim.name,
            {
                "purchase_invoice": purchase_invoice.name,
                "purchase_invoice_item": purchase_item.name,
                "process_payable_number": purchase_invoice.name,
                "sales_invoice": sales_invoice.name,
                "sales_invoice_item": sales_item.name,
            },
            update_modified=False,
        )


def _group_result(group, purchase_invoice, sales_invoice, status):
    return {
        "facility_id": group.facility_id,
        "provider": group.provider,
        "claim_count": group.claim_count,
        "total_amount": float(group.total_amount),
        "purchase_invoice": purchase_invoice,
        "sales_invoice": sales_invoice,
        "status": status,
    }


def _store_processing_report(batch_name, report):
    frappe.db.set_value(
        "Claims PO Batch",
        batch_name,
        "processing_log",
        json.dumps(report, indent=2, ensure_ascii=False),
        update_modified=False,
    )


def _commit():
    if not frappe.flags.in_test:
        frappe.db.commit()


def _get_batch_clearing_difference(batch_name, clearing_account):
    invoice_names = set(
        frappe.get_all(
            "Claim Record",
            filters={
                "po_batch": batch_name,
                "claim_status": "Active",
            },
            pluck="purchase_invoice",
            limit_page_length=0,
        )
    )
    invoice_names.update(
        frappe.get_all(
            "Claim Record",
            filters={
                "po_batch": batch_name,
                "claim_status": "Active",
            },
            pluck="sales_invoice",
            limit_page_length=0,
        )
    )
    invoice_names.discard(None)
    invoice_names.discard("")
    if not invoice_names:
        return 0.0

    entries = frappe.get_all(
        "GL Entry",
        filters={
            "account": clearing_account,
            "voucher_no": ["in", sorted(invoice_names)],
            "is_cancelled": 0,
        },
        fields=["debit", "credit"],
        limit_page_length=0,
    )
    return round(
        sum(flt(entry.debit) - flt(entry.credit) for entry in entries),
        2,
    )


def _validate_invoice_preview(doc):
    doc.run_method("set_missing_values", for_validate=True)
    doc.run_method("calculate_taxes_and_totals")
    doc.run_method("validate")


def _invoice_summary(doc):
    clearing_accounts = {
        item.expense_account
        if doc.doctype == "Purchase Invoice"
        else item.income_account
        for item in doc.items
    }
    return {
        "doctype": doc.doctype,
        "party": doc.supplier if doc.doctype == "Purchase Invoice" else doc.customer,
        "party_account": (
            doc.credit_to if doc.doctype == "Purchase Invoice" else doc.debit_to
        ),
        "clearing_account": next(iter(clearing_accounts)),
        "item_code": doc.items[0].item_code,
        "item_count": len(doc.items),
        "grand_total": float(doc.grand_total),
        "currency": doc.currency,
        "would_submit": True,
    }


def _build_validation_result(batch):
    content = _get_source_file_content(batch)
    parsed = parse_workbook(content)

    existing_claim_references = set()
    if parsed.claim_references:
        existing_claim_references = set(
            frappe.get_all(
                "Claim Record",
                filters={
                    "claim_reference": ["in", parsed.claim_references],
                    "po_batch": ["!=", batch.name],
                },
                pluck="claim_reference",
                limit_page_length=0,
            )
        )

    provider_by_facility = {}
    if parsed.facility_ids:
        mappings = frappe.get_all(
            "Provider Facility Mapping",
            filters={
                "facility_id": ["in", sorted(parsed.facility_ids)],
                "disabled": 0,
            },
            fields=["facility_id", "supplier"],
            limit_page_length=0,
        )
        provider_by_facility = {mapping.facility_id: mapping.supplier for mapping in mappings}

    duplicate_file = bool(
        frappe.db.exists(
            "Claims PO Batch",
            {
                "source_file_hash": parsed.file_hash,
                "name": ["!=", batch.name],
            },
        )
    )
    return validate_parsed_workbook(
        parsed,
        existing_claim_references=existing_claim_references,
        provider_by_facility=provider_by_facility,
        duplicate_file=duplicate_file,
    )


def _get_source_file_content(batch):
    file_name = frappe.db.get_value("File", {"file_url": batch.source_file}, "name")
    if not file_name:
        frappe.throw("The attached PO Excel file could not be found.")
    file_doc = frappe.get_doc("File", file_name)
    if file_doc.attached_to_doctype != batch.doctype or file_doc.attached_to_name != batch.name:
        frappe.throw("The PO Excel file must be attached directly to this Claims PO Batch.")
    return file_doc.get_content()


def _store_validation_result(batch, preview):
    status = "Validated" if preview["valid"] else "Validation Failed"
    is_duplicate_file = any(error["code"] == "duplicate_file" for error in preview["errors"])
    frappe.db.set_value(
        "Claims PO Batch",
        batch.name,
        {
            "source_file_hash": None if is_duplicate_file else preview["file_hash"],
            "external_po_ref": preview["external_po_ref"],
            "currency": preview["currency"],
            "total_claims": preview["total_claims"],
            "total_providers": preview["total_providers"],
            "total_amount": preview["total_amount"],
            "validation_log": json.dumps(preview, indent=2, ensure_ascii=False),
            "status": status,
        },
    )
