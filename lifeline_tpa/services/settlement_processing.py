import json
from collections import defaultdict
from decimal import Decimal

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from frappe.utils import flt, now_datetime

from lifeline_tpa.services.settlement_upload import (
    parse_payer_receipt_file,
    parse_provider_payment_file,
)


PAYMENT_TOLERANCE = 0.005


def validate_payer_receipt(batch):
    parsed = _parse_source_file(batch, parse_payer_receipt_file)
    errors = list(parsed.errors)
    claims_by_reference = _get_claims_by_reference(
        row.claim_reference for row in parsed.rows
    )

    rows = []
    for request in parsed.rows:
        claim = claims_by_reference.get(request.claim_reference)
        row_errors = _validate_payer_receipt_row(batch, request, claim)
        errors.extend(row_errors)
        rows.append(_payer_receipt_item(request, claim, row_errors))

    errors.extend(_duplicate_file_errors(batch, parsed.file_hash))
    _store_payer_receipt_validation(batch, parsed.file_hash, rows, errors)
    return _validation_result(parsed.file_hash, rows, errors)


def validate_provider_payment(batch):
    parsed = _parse_source_file(batch, parse_provider_payment_file)
    errors = list(parsed.errors)
    claims_by_reference = _get_claims_by_reference(
        row.claim_reference for row in parsed.rows
    )

    rows = []
    for request in parsed.rows:
        claim = claims_by_reference.get(request.claim_reference)
        row_errors = _validate_provider_payment_row(batch, request, claim)
        errors.extend(row_errors)
        rows.append(_provider_payment_item(request, claim, row_errors))

    errors.extend(_duplicate_file_errors(batch, parsed.file_hash))
    _store_provider_payment_validation(batch, parsed.file_hash, rows, errors)
    return _validation_result(parsed.file_hash, rows, errors)


def process_payer_receipt(batch, requested_by=None):
    if batch.docstatus != 1:
        frappe.throw("Submit the Payer Receipt Settlement before processing.")
    if batch.status not in ("Validated", "Failed"):
        frappe.throw(f"Payer receipt cannot be processed while status is {batch.status}.")

    ready_rows = [row for row in batch.claims if row.status == "Ready"]
    if not ready_rows:
        frappe.throw("This Payer Receipt Settlement has no validated claim rows.")

    _revalidate_payer_rows_for_processing(batch, ready_rows)
    report = {
        "status": "Processing",
        "settlement": batch.name,
        "payment_entries": [],
        "failed_groups": [],
    }
    frappe.db.set_value(
        batch.doctype,
        batch.name,
        {
            "status": "Processing",
            "processing_log": json.dumps(report, indent=2, ensure_ascii=False),
        },
    )

    for index, rows in enumerate(_group_by(ready_rows, "lifeline_bank_account").values(), start=1):
        savepoint = f"payer_receipt_{index}"
        frappe.db.savepoint(savepoint)
        try:
            payment_entry = _make_customer_payment_entry(batch, rows, index)
            _submit_payment_entry(payment_entry)
            _mark_payer_rows_processed(batch, rows, payment_entry.name)
            report["payment_entries"].append(
                {
                    "payment_entry": payment_entry.name,
                    "lifeline_bank_account": rows[0].lifeline_bank_account,
                    "claim_count": len(rows),
                    "total_amount": _sum_amount(rows),
                }
            )
            _store_processing_log(batch, report)
            _commit()
        except Exception as exc:
            frappe.db.rollback(save_point=savepoint)
            _mark_rows_failed("Payer Receipt Settlement Item", rows, str(exc))
            report["failed_groups"].append(
                {
                    "lifeline_bank_account": rows[0].lifeline_bank_account,
                    "claim_count": len(rows),
                    "error": str(exc),
                }
            )
            frappe.log_error(
                title=f"Payer receipt settlement failed for {batch.name}",
                message=frappe.get_traceback(),
            )
            _store_processing_log(batch, report)
            _commit()

    _finish_settlement(batch, report, requested_by)
    return report


def process_provider_payment(batch, requested_by=None):
    if batch.docstatus != 1:
        frappe.throw("Submit the Provider Payment Settlement before processing.")
    if batch.status not in ("Validated", "Failed"):
        frappe.throw(
            f"Provider payment cannot be processed while status is {batch.status}."
        )

    ready_rows = [row for row in batch.claims if row.status == "Ready"]
    if not ready_rows:
        frappe.throw("This Provider Payment Settlement has no validated claim rows.")

    _revalidate_provider_rows_for_processing(batch, ready_rows)
    report = {
        "status": "Processing",
        "settlement": batch.name,
        "payment_entries": [],
        "failed_groups": [],
    }
    frappe.db.set_value(
        batch.doctype,
        batch.name,
        {
            "status": "Processing",
            "processing_log": json.dumps(report, indent=2, ensure_ascii=False),
        },
    )

    groups = _group_by(ready_rows, "provider", "lifeline_bank_account", "payment_reference")
    for index, rows in enumerate(groups.values(), start=1):
        savepoint = f"provider_payment_{index}"
        frappe.db.savepoint(savepoint)
        try:
            payment_entry = _make_supplier_payment_entry(batch, rows)
            _submit_payment_entry(payment_entry)
            _mark_provider_rows_processed(batch, rows, payment_entry.name)
            report["payment_entries"].append(
                {
                    "payment_entry": payment_entry.name,
                    "provider": rows[0].provider,
                    "lifeline_bank_account": rows[0].lifeline_bank_account,
                    "payment_reference": rows[0].payment_reference,
                    "claim_count": len(rows),
                    "total_amount": _sum_amount(rows),
                }
            )
            _store_processing_log(batch, report)
            _commit()
        except Exception as exc:
            frappe.db.rollback(save_point=savepoint)
            _mark_rows_failed("Provider Payment Settlement Item", rows, str(exc))
            report["failed_groups"].append(
                {
                    "provider": rows[0].provider,
                    "lifeline_bank_account": rows[0].lifeline_bank_account,
                    "payment_reference": rows[0].payment_reference,
                    "claim_count": len(rows),
                    "error": str(exc),
                }
            )
            frappe.log_error(
                title=f"Provider payment settlement failed for {batch.name}",
                message=frappe.get_traceback(),
            )
            _store_processing_log(batch, report)
            _commit()

    _finish_settlement(batch, report, requested_by)
    return report


def _parse_source_file(batch, parser):
    file_name = frappe.db.get_value("File", {"file_url": batch.source_file}, "name")
    if not file_name:
        frappe.throw("The attached settlement file could not be found.")
    file_doc = frappe.get_doc("File", file_name)
    if file_doc.attached_to_doctype != batch.doctype or file_doc.attached_to_name != batch.name:
        frappe.throw("The settlement file must be attached directly to this document.")
    try:
        return parser(file_doc.get_content(), file_doc.file_name)
    except ValueError as exc:
        frappe.throw(str(exc))


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
            "purchase_invoice",
            "process_payable_number",
            "sales_invoice",
            "payer_allocated_amount",
            "payer_outstanding_amount",
            "payer_settlement_status",
            "provider_paid_amount",
            "provider_outstanding_amount",
            "provider_settlement_status",
        ],
        limit_page_length=0,
    )
    return {claim.claim_reference: claim for claim in claims}


def _validate_payer_receipt_row(batch, request, claim):
    errors = _validate_common_row(batch, request, claim, "payer")
    if not claim:
        return errors
    if claim.payer != batch.payer:
        errors.append(
            _error(
                request.row_number,
                "payer_mismatch",
                f"Claim {request.claim_reference} belongs to payer {claim.payer}.",
            )
        )
    if not claim.sales_invoice:
        errors.append(
            _error(
                request.row_number,
                "missing_sales_invoice",
                f"Claim {request.claim_reference} has no Sales Invoice.",
            )
        )
    if flt(request.amount_paid) - flt(claim.payer_outstanding_amount) > PAYMENT_TOLERANCE:
        errors.append(
            _error(
                request.row_number,
                "amount_exceeds_outstanding",
                f"Claim {request.claim_reference} has only {claim.payer_outstanding_amount} outstanding from payer.",
            )
        )
    _validate_invoice_for_payment(
        request,
        "Sales Invoice",
        claim.sales_invoice,
        batch.company,
        request.amount_paid,
        errors,
    )
    return errors


def _validate_provider_payment_row(batch, request, claim):
    errors = _validate_common_row(batch, request, claim, "provider")
    if not claim:
        return errors
    if batch.provider and claim.provider != batch.provider:
        errors.append(
            _error(
                request.row_number,
                "provider_mismatch",
                f"Claim {request.claim_reference} belongs to provider {claim.provider}.",
            )
        )
    if not claim.purchase_invoice or not claim.process_payable_number:
        errors.append(
            _error(
                request.row_number,
                "missing_purchase_invoice",
                f"Claim {request.claim_reference} has no Purchase Invoice / Process Payable Number.",
            )
        )
    if flt(request.amount_paid) - flt(claim.provider_outstanding_amount) > PAYMENT_TOLERANCE:
        errors.append(
            _error(
                request.row_number,
                "amount_exceeds_outstanding",
                f"Claim {request.claim_reference} has only {claim.provider_outstanding_amount} outstanding for provider payment.",
            )
        )
    if _provider_reference_already_used(request):
        errors.append(
            _error(
                request.row_number,
                "duplicate_payment_reference",
                f"Payment reference {request.payment_reference} was already used for claim {request.claim_reference}.",
            )
        )
    _validate_invoice_for_payment(
        request,
        "Purchase Invoice",
        claim.purchase_invoice,
        batch.company,
        request.amount_paid,
        errors,
    )
    return errors


def _validate_common_row(batch, request, claim, side):
    errors = []
    _validate_bank_account(request, batch.company, errors)
    if not claim:
        errors.append(
            _error(
                request.row_number,
                "claim_not_found",
                f"Claim {request.claim_reference} was not found.",
            )
        )
        return errors
    if batch.po_batch and claim.po_batch != batch.po_batch:
        errors.append(
            _error(
                request.row_number,
                "po_batch_mismatch",
                f"Claim {request.claim_reference} does not belong to PO Batch {batch.po_batch}.",
            )
        )
    if claim.claim_status != "Active":
        errors.append(
            _error(
                request.row_number,
                "claim_not_active",
                f"Claim {request.claim_reference} is {claim.claim_status}.",
            )
        )
    outstanding_field = (
        "payer_outstanding_amount"
        if side == "payer"
        else "provider_outstanding_amount"
    )
    if flt(claim.get(outstanding_field)) <= PAYMENT_TOLERANCE:
        errors.append(
            _error(
                request.row_number,
                "claim_already_settled",
                f"Claim {request.claim_reference} has no {side} outstanding amount.",
            )
        )
    return errors


def _validate_bank_account(request, company, errors):
    account = frappe.db.get_value(
        "Account",
        request.lifeline_bank_account,
        ["name", "company", "account_type", "is_group"],
        as_dict=True,
    )
    if not account:
        errors.append(
            _error(
                request.row_number,
                "invalid_bank_account",
                f"Bank account {request.lifeline_bank_account} was not found.",
            )
        )
        return
    if account.company != company:
        errors.append(
            _error(
                request.row_number,
                "bank_account_company_mismatch",
                f"Bank account {request.lifeline_bank_account} belongs to another Company.",
            )
        )
    if account.is_group:
        errors.append(
            _error(
                request.row_number,
                "bank_account_is_group",
                f"Bank account {request.lifeline_bank_account} is a group account.",
            )
        )
    if account.account_type not in ("Bank", "Cash"):
        errors.append(
            _error(
                request.row_number,
                "not_bank_or_cash_account",
                f"Account {request.lifeline_bank_account} must be a Bank or Cash account.",
            )
        )


def _validate_invoice_for_payment(request, doctype, invoice_name, company, amount, errors):
    if not invoice_name:
        return
    invoice = frappe.db.get_value(
        doctype,
        invoice_name,
        ["docstatus", "company", "grand_total", "outstanding_amount"],
        as_dict=True,
    )
    if not invoice or invoice.docstatus != 1:
        errors.append(
            _error(
                request.row_number,
                "invoice_not_submitted",
                f"{doctype} {invoice_name} is not submitted.",
            )
        )
        return
    if invoice.company != company:
        errors.append(
            _error(
                request.row_number,
                "invoice_company_mismatch",
                f"{doctype} {invoice_name} belongs to another Company.",
            )
        )
    if flt(amount) - flt(invoice.outstanding_amount) > PAYMENT_TOLERANCE:
        errors.append(
            _error(
                request.row_number,
                "invoice_outstanding_too_low",
                f"{doctype} {invoice_name} has only {invoice.outstanding_amount} outstanding.",
            )
        )


def _provider_reference_already_used(request):
    return bool(
        frappe.db.sql(
            """
            select item.name
            from `tabProvider Payment Settlement Item` item
            join `tabProvider Payment Settlement` parent on parent.name = item.parent
            where item.claim_reference = %s
              and item.payment_reference = %s
              and item.status = 'Processed'
              and parent.docstatus = 1
            limit 1
            """,
            (request.claim_reference, request.payment_reference),
        )
    )


def _duplicate_file_errors(batch, file_hash):
    duplicate = frappe.db.exists(
        batch.doctype,
        {
            "source_file_hash": file_hash,
            "name": ["!=", batch.name],
            "docstatus": ["!=", 2],
        },
    )
    if not duplicate:
        return []
    return [
        _error(
            1,
            "duplicate_file",
            "This settlement file was already used in another settlement document.",
        )
    ]


def _payer_receipt_item(request, claim, row_errors):
    already_paid = flt(claim.payer_allocated_amount) if claim else 0
    outstanding = flt(claim.payer_outstanding_amount) if claim else 0
    amount_paid = flt(request.amount_paid)
    return {
        "source_row_number": request.row_number,
        "claim_record": claim.name if claim else None,
        "claim_reference": request.claim_reference,
        "po_batch": claim.po_batch if claim else None,
        "payer": claim.payer if claim else None,
        "provider": claim.provider if claim else None,
        "sales_invoice": claim.sales_invoice if claim else None,
        "claim_amount": flt(claim.claim_amount) if claim else 0,
        "already_paid_amount": already_paid,
        "outstanding_amount": outstanding,
        "amount_paid": amount_paid,
        "new_outstanding_amount": max(round(outstanding - amount_paid, 2), 0),
        "lifeline_bank_account": request.lifeline_bank_account,
        "status": "Failed" if row_errors else "Ready",
        "error_message": "\n".join(error["message"] for error in row_errors),
    }


def _provider_payment_item(request, claim, row_errors):
    already_paid = flt(claim.provider_paid_amount) if claim else 0
    outstanding = flt(claim.provider_outstanding_amount) if claim else 0
    amount_paid = flt(request.amount_paid)
    return {
        "source_row_number": request.row_number,
        "claim_record": claim.name if claim else None,
        "claim_reference": request.claim_reference,
        "po_batch": claim.po_batch if claim else None,
        "payer": claim.payer if claim else None,
        "provider": claim.provider if claim else None,
        "purchase_invoice": claim.purchase_invoice if claim else None,
        "process_payable_number": claim.process_payable_number if claim else None,
        "claim_amount": flt(claim.claim_amount) if claim else 0,
        "already_paid_amount": already_paid,
        "outstanding_amount": outstanding,
        "amount_paid": amount_paid,
        "new_outstanding_amount": max(round(outstanding - amount_paid, 2), 0),
        "lifeline_bank_account": request.lifeline_bank_account,
        "payment_reference": request.payment_reference,
        "status": "Failed" if row_errors else "Ready",
        "error_message": "\n".join(error["message"] for error in row_errors),
    }


def _store_payer_receipt_validation(batch, file_hash, rows, errors):
    batch.set("claims", [])
    for row in rows:
        batch.append("claims", row)
    _store_validation(batch, file_hash, rows, errors)


def _store_provider_payment_validation(batch, file_hash, rows, errors):
    batch.set("claims", [])
    for row in rows:
        batch.append("claims", row)
    _store_validation(batch, file_hash, rows, errors)


def _store_validation(batch, file_hash, rows, errors):
    ready_rows = [row for row in rows if row["status"] == "Ready"]
    status = "Validated" if not errors and ready_rows else "Validation Failed"
    result = _validation_result(file_hash, rows, errors)
    batch.source_file_hash = file_hash
    batch.total_claims = result["total_claims"]
    batch.total_amount = result["total_amount"]
    batch.validation_log = json.dumps(result, indent=2, ensure_ascii=False)
    batch.status = status
    batch.save(ignore_permissions=True)


def _validation_result(file_hash, rows, errors):
    ready_rows = [row for row in rows if row["status"] == "Ready"]
    return {
        "valid": not errors and bool(ready_rows),
        "file_hash": file_hash,
        "total_claims": len(ready_rows),
        "total_amount": round(sum(flt(row["amount_paid"]) for row in ready_rows), 2),
        "errors": errors,
    }


def _revalidate_payer_rows_for_processing(batch, rows):
    claims = _get_claims_by_reference(row.claim_reference for row in rows)
    errors = []
    for row in rows:
        request = _row_request(row)
        errors.extend(
            _validate_payer_receipt_row(batch, request, claims.get(row.claim_reference))
        )
    if errors:
        frappe.throw("The payer receipt is no longer valid. Validate the file again.")


def _revalidate_provider_rows_for_processing(batch, rows):
    claims = _get_claims_by_reference(row.claim_reference for row in rows)
    errors = []
    for row in rows:
        request = _row_request(row)
        errors.extend(
            _validate_provider_payment_row(
                batch,
                request,
                claims.get(row.claim_reference),
            )
        )
    if errors:
        frappe.throw("The provider payment is no longer valid. Validate the file again.")


def _row_request(row):
    return frappe._dict(
        row_number=row.source_row_number,
        claim_reference=row.claim_reference,
        amount_paid=Decimal(str(row.amount_paid)),
        lifeline_bank_account=row.lifeline_bank_account,
        payment_reference=row.get("payment_reference"),
    )


def _make_customer_payment_entry(batch, rows, group_index):
    invoices = _invoice_allocations(rows, "sales_invoice", "Sales Invoice")
    first_invoice = next(iter(invoices))
    total = _sum_amount(rows)
    payment_entry = get_payment_entry(
        "Sales Invoice",
        first_invoice,
        party_amount=total,
        bank_account=rows[0].lifeline_bank_account,
        bank_amount=total,
        payment_type="Receive",
        reference_date=batch.posting_date,
        ignore_permissions=True,
    )
    payment_entry.posting_date = batch.posting_date
    payment_entry.reference_no = f"{batch.name}-{group_index}"
    payment_entry.reference_date = batch.posting_date
    payment_entry.remarks = f"Lifeline TPA payer receipt settlement {batch.name}."
    payment_entry.set("references", [])
    _append_references(payment_entry, invoices, "Sales Invoice")
    _prepare_payment_entry(payment_entry, total)
    return payment_entry


def _make_supplier_payment_entry(batch, rows):
    invoices = _invoice_allocations(rows, "purchase_invoice", "Purchase Invoice")
    first_invoice = next(iter(invoices))
    total = _sum_amount(rows)
    payment_entry = get_payment_entry(
        "Purchase Invoice",
        first_invoice,
        party_amount=total,
        bank_account=rows[0].lifeline_bank_account,
        bank_amount=total,
        payment_type="Pay",
        reference_date=batch.posting_date,
        ignore_permissions=True,
    )
    payment_entry.posting_date = batch.posting_date
    payment_entry.reference_no = rows[0].payment_reference
    payment_entry.reference_date = batch.posting_date
    payment_entry.remarks = f"Lifeline TPA provider payment settlement {batch.name}."
    payment_entry.set("references", [])
    _append_references(payment_entry, invoices, "Purchase Invoice")
    _prepare_payment_entry(payment_entry, total)
    return payment_entry


def _invoice_allocations(rows, invoice_field, doctype):
    grouped = defaultdict(float)
    for row in rows:
        grouped[row.get(invoice_field)] += flt(row.amount_paid)
    for invoice, amount in grouped.items():
        outstanding = flt(frappe.db.get_value(doctype, invoice, "outstanding_amount"))
        if amount - outstanding > PAYMENT_TOLERANCE:
            frappe.throw(f"{doctype} {invoice} has only {outstanding} outstanding.")
    return dict(grouped)


def _append_references(payment_entry, invoices, doctype):
    for invoice, amount in invoices.items():
        fields = ["grand_total", "outstanding_amount", "due_date"]
        if doctype == "Purchase Invoice":
            fields.append("bill_no")
        values = frappe.db.get_value(doctype, invoice, fields, as_dict=True)
        reference = {
            "reference_doctype": doctype,
            "reference_name": invoice,
            "due_date": values.due_date,
            "total_amount": values.grand_total,
            "outstanding_amount": values.outstanding_amount,
            "allocated_amount": amount,
        }
        if doctype == "Purchase Invoice":
            reference["bill_no"] = values.bill_no
        payment_entry.append("references", reference)


def _prepare_payment_entry(payment_entry, total):
    payment_entry.paid_amount = total
    payment_entry.received_amount = total
    payment_entry.set_exchange_rate()
    payment_entry.set_amounts()
    payment_entry.set_missing_ref_details()


def _submit_payment_entry(payment_entry):
    payment_entry.insert(ignore_permissions=True)
    payment_entry.submit()


def _mark_payer_rows_processed(batch, rows, payment_entry):
    for row in rows:
        claim = frappe.get_doc("Claim Record", row.claim_record)
        paid = flt(claim.payer_allocated_amount) + flt(row.amount_paid)
        outstanding = max(round(flt(claim.payer_outstanding_amount) - flt(row.amount_paid), 2), 0)
        frappe.db.set_value(
            "Claim Record",
            claim.name,
            {
                "payer_allocated_amount": paid,
                "payer_outstanding_amount": outstanding,
                "payer_settlement_status": _settlement_status(outstanding),
                "payer_payment_reference": payment_entry,
                "payer_payment_date": batch.posting_date,
            },
            update_modified=False,
        )
        frappe.db.set_value(
            "Payer Receipt Settlement Item",
            row.name,
            {
                "payment_entry": payment_entry,
                "status": "Processed",
                "error_message": None,
            },
            update_modified=False,
        )


def _mark_provider_rows_processed(batch, rows, payment_entry):
    for row in rows:
        claim = frappe.get_doc("Claim Record", row.claim_record)
        paid = flt(claim.provider_paid_amount) + flt(row.amount_paid)
        outstanding = max(round(flt(claim.provider_outstanding_amount) - flt(row.amount_paid), 2), 0)
        frappe.db.set_value(
            "Claim Record",
            claim.name,
            {
                "provider_paid_amount": paid,
                "provider_outstanding_amount": outstanding,
                "provider_settlement_status": _settlement_status(outstanding),
                "provider_payment_reference": row.payment_reference,
                "provider_payment_date": batch.posting_date,
            },
            update_modified=False,
        )
        frappe.db.set_value(
            "Provider Payment Settlement Item",
            row.name,
            {
                "payment_entry": payment_entry,
                "status": "Processed",
                "error_message": None,
            },
            update_modified=False,
        )


def _mark_rows_failed(doctype, rows, error):
    for row in rows:
        frappe.db.set_value(
            doctype,
            row.name,
            {"status": "Failed", "error_message": error},
            update_modified=False,
        )


def _finish_settlement(batch, report, requested_by):
    failed = bool(report["failed_groups"])
    report["status"] = "Failed" if failed else "Processed"
    payment_entries = [row["payment_entry"] for row in report["payment_entries"]]
    values = {
        "status": report["status"],
        "payment_entries": json.dumps(payment_entries, indent=2),
        "processing_log": json.dumps(report, indent=2, ensure_ascii=False),
    }
    if not failed:
        values.update(
            {
                "processed_by": requested_by or frappe.session.user,
                "processed_date": now_datetime(),
            }
        )
    frappe.db.set_value(batch.doctype, batch.name, values)
    _update_po_batch_status_for_rows(batch.claims)
    _commit()


def _update_po_batch_status_for_rows(rows):
    batch_names = {row.po_batch for row in rows if row.po_batch}
    for batch_name in batch_names:
        totals = frappe.get_all(
            "Claim Record",
            filters={"po_batch": batch_name, "claim_status": "Active"},
            fields=[
                "sum(payer_outstanding_amount) as payer_outstanding",
                "sum(provider_outstanding_amount) as provider_outstanding",
            ],
            limit_page_length=1,
        )[0]
        payer_outstanding = flt(totals.payer_outstanding)
        provider_outstanding = flt(totals.provider_outstanding)
        status = (
            "Fully Settled"
            if payer_outstanding <= PAYMENT_TOLERANCE and provider_outstanding <= PAYMENT_TOLERANCE
            else "Partially Settled"
        )
        frappe.db.set_value(
            "Claims PO Batch",
            batch_name,
            "status",
            status,
            update_modified=False,
        )


def _settlement_status(outstanding):
    return "Paid" if flt(outstanding) <= PAYMENT_TOLERANCE else "Partially Paid"


def _group_by(rows, *fields):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(field) for field in fields)].append(row)
    return groups


def _sum_amount(rows):
    return round(sum(flt(row.amount_paid) for row in rows), 2)


def _store_processing_log(batch, report):
    frappe.db.set_value(
        batch.doctype,
        batch.name,
        "processing_log",
        json.dumps(report, indent=2, ensure_ascii=False),
        update_modified=False,
    )


def _error(row_number, code, message):
    return {"row_number": row_number, "code": code, "message": message}


def _commit():
    if not frappe.flags.in_test:
        frappe.db.commit()
