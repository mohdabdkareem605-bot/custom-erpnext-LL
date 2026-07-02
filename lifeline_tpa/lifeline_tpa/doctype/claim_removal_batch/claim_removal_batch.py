import json
from collections import defaultdict

import frappe
from erpnext.controllers.sales_and_purchase_return import make_return_doc
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime

from lifeline_tpa.services.claim_removal import parse_claim_removal_file


PROCESSING_METHOD = (
    "lifeline_tpa.lifeline_tpa.doctype.claim_removal_batch."
    "claim_removal_batch.process_claim_removals"
)


class ClaimRemovalBatch(Document):
    def validate(self):
        if self.source_file and not self.source_file.lower().endswith((".xlsx", ".csv")):
            frappe.throw("The claim removal file must be an .xlsx or .csv file.")

        previous = self.get_doc_before_save()
        if (
            previous
            and previous.source_file
            and previous.source_file != self.source_file
            and previous.status != "Draft"
        ):
            frappe.throw("The removal file cannot be replaced after validation starts.")

    def before_submit(self):
        if self.status != "Validated":
            frappe.throw("Validate the claim removal file before submitting this batch.")

    def on_cancel(self):
        if self.status == "Processed":
            frappe.throw(
                "A processed removal batch cannot be cancelled automatically. "
                "Its debit and credit notes must be reversed through an approved adjustment."
            )
        self.db_set("status", "Cancelled", update_modified=False)


@frappe.whitelist()
def validate_removal_file(batch_name):
    batch = frappe.get_doc("Claim Removal Batch", batch_name)
    batch.check_permission("write")

    if batch.docstatus != 0:
        frappe.throw("Only a draft Claim Removal Batch can be validated.")

    batch.db_set("status", "Validating", update_modified=False)
    parsed = _parse_source_file(batch)
    errors = list(parsed.errors)
    claims_by_reference = _get_claims_by_reference(
        request.claim_reference for request in parsed.requests
    )

    rows = []
    for request in parsed.requests:
        claim = claims_by_reference.get(request.claim_reference)
        row_errors = _validate_claim_for_removal(batch, request, claim)
        errors.extend(row_errors)
        rows.append(_removal_row(request, claim, row_errors))

    duplicate_file = frappe.db.exists(
        "Claim Removal Batch",
        {
            "source_file_hash": parsed.file_hash,
            "name": ["!=", batch.name],
            "docstatus": ["!=", 2],
        },
    )
    if duplicate_file:
        errors.append(
            {
                "row_number": 1,
                "code": "duplicate_file",
                "message": "This claim removal file was already used in another batch.",
            }
        )

    batch.set("claims", [])
    for row in rows:
        batch.append("claims", row)

    valid_rows = [row for row in rows if row["status"] == "Ready"]
    status = "Validated" if not errors and valid_rows else "Validation Failed"
    result = {
        "valid": status == "Validated",
        "file_hash": parsed.file_hash,
        "total_claims": len(valid_rows),
        "total_amount": round(sum(row["claim_amount"] for row in valid_rows), 2),
        "unprocessed_claims": sum(
            row["processing_mode"] == "Unprocessed Removal" for row in valid_rows
        ),
        "accounting_reversals": sum(
            row["processing_mode"] in (
                "Accounting Reversal",
                "Legacy Accounting Reversal",
            )
            for row in valid_rows
        ),
        "errors": errors,
    }
    batch.source_file_hash = parsed.file_hash
    batch.total_claims = result["total_claims"]
    batch.total_amount = result["total_amount"]
    batch.validation_log = json.dumps(result, indent=2, ensure_ascii=False)
    batch.status = status
    batch.save(ignore_permissions=True)
    return result


@frappe.whitelist()
def enqueue_claim_removals(batch_name):
    batch = frappe.get_doc("Claim Removal Batch", batch_name)
    batch.check_permission("write")

    if batch.docstatus != 1:
        frappe.throw("Submit the Claim Removal Batch before processing.")
    if batch.status not in ("Validated", "Failed"):
        frappe.throw(f"Claim removals cannot run while the status is {batch.status}.")
    if not batch.claims:
        frappe.throw("This removal batch contains no validated claims.")

    job_id = f"lifeline-tpa-removal-{batch.name}"
    report = {
        "status": "Queued",
        "batch_name": batch.name,
        "job_id": job_id,
        "queued_by": frappe.session.user,
        "completed_groups": [],
        "failed_groups": [],
    }
    frappe.db.set_value(
        "Claim Removal Batch",
        batch.name,
        {
            "status": "Processing",
            "background_job_id": job_id,
            "processing_log": json.dumps(report, indent=2),
        },
    )
    frappe.enqueue(
        PROCESSING_METHOD,
        queue="long",
        timeout=3600,
        job_id=job_id,
        deduplicate=True,
        enqueue_after_commit=True,
        batch_name=batch.name,
        requested_by=frappe.session.user,
    )
    return {"batch_name": batch.name, "job_id": job_id, "status": "Processing"}


def process_claim_removals(batch_name, requested_by=None):
    batch = frappe.get_doc("Claim Removal Batch", batch_name)
    if batch.docstatus != 1 or batch.status not in ("Processing", "Failed"):
        frappe.throw("This Claim Removal Batch is not ready for processing.")

    report = {
        "status": "Processing",
        "batch_name": batch.name,
        "job_id": batch.background_job_id,
        "requested_by": requested_by,
        "completed_groups": [],
        "failed_groups": [],
        "clearing_difference": None,
    }

    groups = _group_ready_rows(batch)
    for index, (group_key, rows) in enumerate(groups.items(), start=1):
        savepoint = f"claim_removal_{index}"
        frappe.db.savepoint(savepoint)
        try:
            result = (
                _process_unprocessed_rows(batch, rows)
                if group_key[0] == "Unprocessed Removal"
                else _process_accounting_reversal(batch, rows)
            )
            report["completed_groups"].append(result)
            _store_report(batch.name, report)
            _commit()
        except Exception as exc:
            frappe.db.rollback(save_point=savepoint)
            for row in rows:
                frappe.db.set_value(
                    "Claim Removal Item",
                    row.name,
                    {"status": "Failed", "error_message": str(exc)},
                    update_modified=False,
                )
            report["failed_groups"].append(
                {
                    "group": " / ".join(str(value) for value in group_key if value),
                    "claim_count": len(rows),
                    "error": str(exc),
                }
            )
            frappe.log_error(
                title=f"Claim removal failed for {batch.name}",
                message=frappe.get_traceback(),
            )
            _store_report(batch.name, report)
            _commit()

    report["clearing_difference"] = _get_clearing_difference(batch.name)
    remaining = frappe.db.count(
        "Claim Removal Item",
        filters={"parent": batch.name, "status": ["!=", "Processed"]},
    )
    if remaining:
        report["failed_groups"].append(
            {"group": "Final validation", "error": f"{remaining} claim row(s) remain unprocessed."}
        )
    if abs(report["clearing_difference"]) > 0.005:
        report["failed_groups"].append(
            {
                "group": "Final validation",
                "error": (
                    "The removal debit and credit notes do not clear to zero. "
                    f"Difference: {report['clearing_difference']}"
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
    frappe.db.set_value("Claim Removal Batch", batch.name, values)
    _commit()
    return report


def _parse_source_file(batch):
    file_doc = _get_source_file(batch)
    try:
        return parse_claim_removal_file(file_doc.get_content(), file_doc.file_name)
    except ValueError as exc:
        frappe.throw(str(exc))


def _get_source_file(batch):
    file_name = frappe.db.get_value("File", {"file_url": batch.source_file}, "name")
    if not file_name:
        frappe.throw("The attached claim removal file could not be found.")
    file_doc = frappe.get_doc("File", file_name)
    if file_doc.attached_to_doctype != batch.doctype or file_doc.attached_to_name != batch.name:
        frappe.throw(
            "The claim removal file must be attached directly to this Claim Removal Batch."
        )
    return file_doc


def _get_claims_by_reference(claim_references):
    references = sorted(set(claim_references))
    if not references:
        return {}
    claims = frappe.get_all(
        "Claim Record",
        filters={"claim_reference": ["in", references]},
        fields=[
            "name",
            "claim_reference",
            "po_batch",
            "payer",
            "provider",
            "claim_amount",
            "currency",
            "claim_status",
            "payer_allocated_amount",
            "provider_paid_amount",
            "payer_settlement_status",
            "provider_settlement_status",
            "purchase_invoice",
            "purchase_invoice_item",
            "sales_invoice",
            "sales_invoice_item",
            "removal_batch",
            "purchase_debit_note",
            "sales_credit_note",
        ],
        limit_page_length=0,
    )
    return {claim.claim_reference: claim for claim in claims}


def _validate_claim_for_removal(batch, request, claim):
    errors = []
    if getdate(batch.posting_date) < getdate(request.removal_date):
        errors.append(
            {
                "row_number": request.row_number,
                "code": "posting_date_before_removal_date",
                "message": (
                    "Accounting Posting Date cannot be before the uploaded Removal Date."
                ),
            }
        )
    if not claim:
        errors.append(
            {
                "row_number": request.row_number,
                "code": "claim_not_found",
                "message": f"Claim {request.claim_reference} was not found.",
            }
        )
        return errors
    if claim.claim_status != "Active":
        errors.append(
            {
                "row_number": request.row_number,
                "code": "claim_not_active",
                "message": f"Claim {request.claim_reference} is already {claim.claim_status}.",
            }
        )
    if (
        flt(claim.payer_allocated_amount)
        or flt(claim.provider_paid_amount)
        or claim.payer_settlement_status != "Unpaid"
        or claim.provider_settlement_status not in ("Unpaid", "On Hold")
    ):
        errors.append(
            {
                "row_number": request.row_number,
                "code": "claim_has_settlement",
                "message": (
                    f"Claim {request.claim_reference} has payer or provider settlement activity "
                    "and cannot be removed automatically."
                ),
            }
        )

    invoice_links = (claim.purchase_invoice, claim.sales_invoice)
    if any(invoice_links) and not all(invoice_links):
        errors.append(
            {
                "row_number": request.row_number,
                "code": "incomplete_invoice_links",
                "message": f"Claim {request.claim_reference} has incomplete accounting links.",
            }
        )
    if all(invoice_links):
        if bool(claim.purchase_invoice_item) != bool(claim.sales_invoice_item):
            errors.append(
                {
                    "row_number": request.row_number,
                    "code": "missing_invoice_item_links",
                    "message": (
                        f"Claim {request.claim_reference} has inconsistent invoice item links."
                    ),
                }
            )
        _validate_original_invoice(
            batch,
            request,
            "Purchase Invoice",
            claim.purchase_invoice,
            claim.claim_amount,
            errors,
        )
        _validate_original_invoice(
            batch,
            request,
            "Sales Invoice",
            claim.sales_invoice,
            claim.claim_amount,
            errors,
        )
    return errors


def _validate_original_invoice(
    batch,
    request,
    doctype,
    invoice_name,
    claim_amount,
    errors,
):
    values = frappe.db.get_value(
        doctype,
        invoice_name,
        ["docstatus", "company", "posting_date", "outstanding_amount"],
        as_dict=True,
    )
    if not values or values.docstatus != 1:
        errors.append(
            {
                "row_number": request.row_number,
                "code": "invoice_not_submitted",
                "message": f"{doctype} {invoice_name} is not submitted.",
            }
        )
        return
    if values.company != batch.company:
        errors.append(
            {
                "row_number": request.row_number,
                "code": "company_mismatch",
                "message": f"{doctype} {invoice_name} belongs to another Company.",
            }
        )
    if getdate(batch.posting_date) < getdate(values.posting_date):
        errors.append(
            {
                "row_number": request.row_number,
                "code": "posting_date_before_invoice",
                "message": (
                    f"Accounting Posting Date cannot be before {doctype} "
                    f"{invoice_name}'s posting date."
                ),
            }
        )
    if flt(values.outstanding_amount) + 0.005 < flt(claim_amount):
        errors.append(
            {
                "row_number": request.row_number,
                "code": "insufficient_invoice_outstanding",
                "message": (
                    f"{doctype} {invoice_name} has insufficient outstanding amount "
                    f"for claim {request.claim_reference}."
                ),
            }
        )


def _removal_row(request, claim, row_errors):
    processed = bool(claim and claim.purchase_invoice and claim.sales_invoice)
    has_item_links = bool(
        claim and claim.purchase_invoice_item and claim.sales_invoice_item
    )
    if not processed:
        processing_mode = "Unprocessed Removal"
    elif has_item_links:
        processing_mode = "Accounting Reversal"
    else:
        processing_mode = "Legacy Accounting Reversal"
    return {
        "source_row_number": request.row_number,
        "claim_record": claim.name if claim else None,
        "claim_reference": request.claim_reference,
        "po_batch": claim.po_batch if claim else None,
        "payer": claim.payer if claim else None,
        "provider": claim.provider if claim else None,
        "claim_amount": flt(claim.claim_amount) if claim else 0,
        "currency": claim.currency if claim else None,
        "processing_mode": processing_mode,
        "removal_reason": request.removal_reason,
        "approval_reference": request.approval_reference,
        "removal_date": request.removal_date,
        "original_purchase_invoice": claim.purchase_invoice if claim else None,
        "original_purchase_invoice_item": (
            claim.purchase_invoice_item if claim else None
        ),
        "original_sales_invoice": claim.sales_invoice if claim else None,
        "original_sales_invoice_item": claim.sales_invoice_item if claim else None,
        "status": "Failed" if row_errors else "Ready",
        "error_message": "\n".join(error["message"] for error in row_errors),
    }


def _group_ready_rows(batch):
    grouped = defaultdict(list)
    for row in batch.claims:
        if row.status == "Processed":
            continue
        if row.processing_mode == "Unprocessed Removal":
            key = ("Unprocessed Removal", row.name)
        else:
            key = (
                "Accounting Reversal",
                row.original_purchase_invoice,
                row.original_sales_invoice,
            )
        grouped[key].append(row)
    return grouped


def _process_unprocessed_rows(batch, rows):
    total = 0
    for row in rows:
        claim = frappe.get_doc("Claim Record", row.claim_record)
        _ensure_claim_is_removable(batch, claim)
        _mark_claim_removed(batch, row, claim)
        total += flt(claim.claim_amount)
    return {
        "mode": "Unprocessed Removal",
        "claim_count": len(rows),
        "total_amount": round(total, 2),
    }


def _process_accounting_reversal(batch, rows):
    claims = [frappe.get_doc("Claim Record", row.claim_record) for row in rows]
    for claim in claims:
        _ensure_claim_is_removable(batch, claim)

    purchase_invoice = rows[0].original_purchase_invoice
    sales_invoice = rows[0].original_sales_invoice
    expected_total = round(sum(flt(claim.claim_amount) for claim in claims), 2)
    _validate_group_outstanding("Purchase Invoice", purchase_invoice, expected_total)
    _validate_group_outstanding("Sales Invoice", sales_invoice, expected_total)
    has_item_links = all(
        row.original_purchase_invoice_item and row.original_sales_invoice_item
        for row in rows
    )
    if has_item_links:
        debit_note = _make_partial_return(
            "Purchase Invoice",
            purchase_invoice,
            "purchase_invoice_item",
            {row.original_purchase_invoice_item for row in rows},
            batch,
        )
        credit_note = _make_partial_return(
            "Sales Invoice",
            sales_invoice,
            "sales_invoice_item",
            {row.original_sales_invoice_item for row in rows},
            batch,
        )
    else:
        _validate_legacy_return_amount(
            "Purchase Invoice",
            purchase_invoice,
            expected_total,
        )
        _validate_legacy_return_amount(
            "Sales Invoice",
            sales_invoice,
            expected_total,
        )
        debit_note = _make_legacy_partial_return(
            "Purchase Invoice",
            purchase_invoice,
            expected_total,
            batch,
        )
        credit_note = _make_legacy_partial_return(
            "Sales Invoice",
            sales_invoice,
            expected_total,
            batch,
        )

    debit_note.insert(ignore_permissions=True)
    debit_note.submit()
    credit_note.insert(ignore_permissions=True)
    credit_note.submit()

    if abs(abs(flt(debit_note.grand_total)) - expected_total) > 0.005:
        frappe.throw("The Purchase Debit Note total does not match the selected claims.")
    if abs(abs(flt(credit_note.grand_total)) - expected_total) > 0.005:
        frappe.throw("The Sales Credit Note total does not match the selected claims.")

    for row, claim in zip(rows, claims, strict=True):
        _mark_claim_removed(
            batch,
            row,
            claim,
            purchase_debit_note=debit_note.name,
            sales_credit_note=credit_note.name,
        )
    return {
        "mode": (
            "Accounting Reversal"
            if has_item_links
            else "Legacy Accounting Reversal"
        ),
        "purchase_invoice": purchase_invoice,
        "sales_invoice": sales_invoice,
        "purchase_debit_note": debit_note.name,
        "sales_credit_note": credit_note.name,
        "claim_count": len(rows),
        "total_amount": expected_total,
    }


def _make_partial_return(
    doctype,
    source_name,
    source_item_field,
    selected_source_items,
    batch,
):
    return_doc = make_return_doc(doctype, source_name)
    selected_items = [
        item for item in return_doc.items
        if item.get(source_item_field) in selected_source_items
    ]
    if len(selected_items) != len(selected_source_items):
        frappe.throw(
            f"Some selected claim items are no longer returnable against {doctype} {source_name}."
        )
    return_doc.set("items", selected_items)
    return_doc.posting_date = batch.posting_date
    return_doc.disable_rounded_total = 1
    return_doc.remarks = (
        f"Lifeline TPA claim removal {batch.name}. "
        f"Return against {doctype} {source_name}."
    )
    if doctype == "Purchase Invoice":
        return_doc.bill_no = f"{batch.name}-{source_name}"
        return_doc.bill_date = batch.posting_date
    return_doc.run_method("calculate_taxes_and_totals")
    return return_doc


def _validate_legacy_return_amount(doctype, source_name, requested_total):
    original_total = abs(flt(frappe.db.get_value(doctype, source_name, "grand_total")))
    returned_total = sum(
        abs(flt(value))
        for value in frappe.get_all(
            doctype,
            filters={
                "return_against": source_name,
                "is_return": 1,
                "docstatus": 1,
            },
            pluck="grand_total",
            limit_page_length=0,
        )
    )
    available = round(original_total - returned_total, 2)
    if requested_total - available > 0.005:
        frappe.throw(
            f"Only {available} remains returnable against {doctype} {source_name}."
        )


def _validate_group_outstanding(doctype, invoice_name, requested_total):
    outstanding = flt(
        frappe.db.get_value(doctype, invoice_name, "outstanding_amount")
    )
    if requested_total - outstanding > 0.005:
        frappe.throw(
            f"{doctype} {invoice_name} has only {outstanding} outstanding, "
            f"but the selected claims total {requested_total}."
        )


def _make_legacy_partial_return(doctype, source_name, amount, batch):
    source = frappe.get_doc(doctype, source_name)
    source_item = source.items[0]
    values = {
        "doctype": doctype,
        "company": source.company,
        "posting_date": batch.posting_date,
        "due_date": batch.posting_date,
        "currency": source.currency,
        "conversion_rate": source.conversion_rate,
        "disable_rounded_total": 1,
        "is_return": 1,
        "return_against": source.name,
        "cost_center": source.cost_center,
        "remarks": (
            f"Lifeline TPA legacy claim removal {batch.name}. "
            f"Partial return against {doctype} {source.name}."
        ),
    }
    if doctype == "Purchase Invoice":
        values.update(
            {
                "supplier": source.supplier,
                "credit_to": source.credit_to,
                "bill_no": f"{batch.name}-{source.name}",
                "bill_date": batch.posting_date,
                "items": [
                    {
                        "item_code": source_item.item_code,
                        "qty": -1,
                        "rate": amount,
                        "description": f"Approved claim removals in {batch.name}",
                        "expense_account": source_item.expense_account,
                        "cost_center": source_item.cost_center,
                    }
                ],
            }
        )
    else:
        values.update(
            {
                "customer": source.customer,
                "debit_to": source.debit_to,
                "items": [
                    {
                        "item_code": source_item.item_code,
                        "qty": -1,
                        "rate": amount,
                        "description": f"Approved claim removals in {batch.name}",
                        "income_account": source_item.income_account,
                        "cost_center": source_item.cost_center,
                    }
                ],
            }
        )
    return_doc = frappe.get_doc(values)
    return_doc.run_method("set_missing_values", for_validate=True)
    return_doc.run_method("calculate_taxes_and_totals")
    return return_doc


def _ensure_claim_is_removable(batch, claim):
    if claim.claim_status == "Removed" and claim.removal_batch == batch.name:
        return
    if claim.claim_status != "Active":
        frappe.throw(
            f"Claim {claim.claim_reference} is no longer active and cannot be removed."
        )
    if flt(claim.payer_allocated_amount) or flt(claim.provider_paid_amount):
        frappe.throw(
            f"Claim {claim.claim_reference} now has settlement activity and cannot be removed."
        )


def _mark_claim_removed(
    batch,
    row,
    claim,
    purchase_debit_note=None,
    sales_credit_note=None,
):
    frappe.db.set_value(
        "Claim Record",
        claim.name,
        {
            "claim_status": "Removed",
            "removal_batch": batch.name,
            "purchase_debit_note": purchase_debit_note,
            "sales_credit_note": sales_credit_note,
            "removal_reason": row.removal_reason,
            "removal_approval_reference": row.approval_reference,
            "removed_date": row.removal_date,
            "payer_outstanding_amount": 0,
            "provider_outstanding_amount": 0,
        },
        update_modified=False,
    )
    frappe.db.set_value(
        "Claim Removal Item",
        row.name,
        {
            "purchase_debit_note": purchase_debit_note,
            "sales_credit_note": sales_credit_note,
            "status": "Processed",
            "error_message": None,
        },
        update_modified=False,
    )


def _get_clearing_difference(batch_name):
    settings = frappe.get_single("Lifeline TPA Settings")
    vouchers = set(
        frappe.get_all(
            "Claim Removal Item",
            filters={"parent": batch_name},
            pluck="purchase_debit_note",
            limit_page_length=0,
        )
    )
    vouchers.update(
        frappe.get_all(
            "Claim Removal Item",
            filters={"parent": batch_name},
            pluck="sales_credit_note",
            limit_page_length=0,
        )
    )
    vouchers.discard(None)
    vouchers.discard("")
    if not vouchers:
        return 0.0
    entries = frappe.get_all(
        "GL Entry",
        filters={
            "account": settings.claims_clearing_account,
            "voucher_no": ["in", sorted(vouchers)],
            "is_cancelled": 0,
        },
        fields=["debit", "credit"],
        limit_page_length=0,
    )
    return round(sum(flt(row.debit) - flt(row.credit) for row in entries), 2)


def _store_report(batch_name, report):
    frappe.db.set_value(
        "Claim Removal Batch",
        batch_name,
        "processing_log",
        json.dumps(report, indent=2, ensure_ascii=False),
        update_modified=False,
    )


def _commit():
    if not frappe.flags.in_test:
        frappe.db.commit()
