import json

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from lifeline_tpa.services.revenue_import import (
    parse_revenue_workbook,
    validate_revenue_workbook,
)
from lifeline_tpa.services.revenue_processing import (
    create_revenue_accounting_documents,
    create_revenue_schedules_for_events,
    group_revenue_events,
    summarize_revenue_groups,
)


PROCESSING_METHOD = (
    "lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_batch."
    "tpa_revenue_batch.process_revenue_batch"
)


class TPARevenueBatch(Document):
    def validate(self):
        if self.source_file and not self.source_file.lower().endswith(".xlsx"):
            frappe.throw("The endorsement report must be an .xlsx workbook.")

        previous = self.get_doc_before_save()
        if (
            previous
            and previous.source_file
            and previous.source_file != self.source_file
            and previous.status != "Draft"
        ):
            frappe.throw("The endorsement report cannot be replaced after validation starts.")

    def before_submit(self):
        if self.status != "Imported":
            frappe.throw("Import validated revenue events before submitting this batch.")

    def on_cancel(self):
        if self.status == "Processed":
            frappe.throw(
                "A processed revenue batch cannot be cancelled automatically. "
                "Reverse its invoices, credit notes, and journal entries through an approved adjustment."
            )
        self.db_set("status", "Cancelled", update_modified=False)


@frappe.whitelist()
def validate_revenue_file(batch_name):
    batch = frappe.get_doc("TPA Revenue Batch", batch_name)
    batch.check_permission("write")

    if batch.docstatus != 0:
        frappe.throw("Only a draft TPA Revenue Batch can be validated.")

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
def import_revenue_events(batch_name):
    batch = frappe.get_doc("TPA Revenue Batch", batch_name)
    batch.check_permission("write")

    if batch.docstatus != 0:
        frappe.throw("Only a draft TPA Revenue Batch can import revenue events.")
    if batch.status != "Validated":
        frappe.throw("Validate the endorsement report successfully before importing events.")
    if frappe.db.exists("TPA Revenue Event", {"revenue_batch": batch.name}):
        frappe.throw("Revenue events were already imported for this batch.")

    result = _build_validation_result(batch)
    if not result.is_valid:
        preview = result.as_dict()
        _store_validation_result(batch, preview)
        frappe.throw("The endorsement report is no longer valid. Review the Validation Log.")

    for event in result.workbook.events:
        frappe.get_doc(
            {
                "doctype": "TPA Revenue Event",
                "revenue_batch": batch.name,
                "company": batch.company,
                "source_row_number": event.row_number,
                "endorsement_year": event.endorsement_year,
                "endorsement_month": event.endorsement_month,
                "endorsement_date": event.endorsement_date,
                "endorsement_type": event.endorsement_type,
                "payer": result.customer_by_payer_name[event.payer_name],
                "payer_name_as_received": event.payer_name,
                "group_name": event.group_name,
                "policy_no": event.policy_no,
                "policy_start_date": event.policy_start_date,
                "policy_stop_date": event.policy_stop_date,
                "policy_category": event.policy_category,
                "employee_id": event.employee_id,
                "member_name": event.member_name,
                "member_second_name": event.member_second_name,
                "card_no": event.card_no,
                "member_id": event.member_id,
                "tpa_fee": event.tpa_fee,
                "currency": event.currency,
                "gross_premium": event.gross_premium,
                "prorata_gross_premium": event.prorata_gross_premium,
                "source_data_json": json.dumps(
                    event.source_data,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        ).insert(ignore_permissions=True)

    batch.db_set("status", "Imported")
    return {
        "batch_name": batch.name,
        "imported_events": len(result.workbook.events),
    }


@frappe.whitelist()
def preview_revenue_documents(batch_name):
    batch = frappe.get_doc("TPA Revenue Batch", batch_name)
    batch.check_permission("read")

    events = _get_batch_events(batch.name)
    settings = _get_revenue_settings(batch.company)
    groups = group_revenue_events(events, settings.max_revenue_invoice_lines or 1000)
    return {
        "batch_name": batch.name,
        "posts_accounting_entries": False,
        "rows": [group.as_dict() for group in groups],
        **summarize_revenue_groups(groups),
    }


@frappe.whitelist()
def enqueue_revenue_processing(batch_name):
    batch = frappe.get_doc("TPA Revenue Batch", batch_name)
    batch.check_permission("write")

    _validate_batch_ready_for_processing(batch)
    job_id = f"lifeline-tpa-revenue-{batch.name}"
    report = {
        "status": "Queued",
        "batch_name": batch.name,
        "job_id": job_id,
        "queued_by": frappe.session.user,
        "completed_groups": [],
        "failed_groups": [],
    }
    frappe.db.set_value(
        "TPA Revenue Batch",
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


def process_revenue_batch(batch_name, requested_by=None):
    batch = frappe.get_doc("TPA Revenue Batch", batch_name)
    _validate_batch_ready_for_processing(batch, allowed_statuses=("Processing", "Failed"))

    report = {
        "status": "Processing",
        "batch_name": batch.name,
        "job_id": batch.background_job_id,
        "requested_by": requested_by,
        "completed_groups": [],
        "failed_groups": [],
    }
    try:
        events = _get_batch_events(batch.name, only_ready=True)
        settings = _get_revenue_settings(batch.company)
        accounting_result = create_revenue_accounting_documents(batch, events, settings)
        schedule_result = create_revenue_schedules_for_events(
            frappe.get_all(
                "TPA Revenue Event",
                filters={"revenue_batch": batch.name},
                fields=["*"],
                order_by="source_row_number asc",
                limit_page_length=0,
            )
        )
        report.update(accounting_result)
        report.update(schedule_result)
        report["completed_groups"] = accounting_result["groups"]
        report["status"] = "Processed"
        frappe.db.set_value(
            "TPA Revenue Batch",
            batch.name,
            {
                "status": "Processed",
                "processed_by": requested_by,
                "processed_date": now_datetime(),
                "total_schedule_amount": schedule_result["total_schedule_amount"],
                "processing_log": json.dumps(report, indent=2, ensure_ascii=False),
            },
        )
        _commit()
        return report
    except Exception as exc:
        report["status"] = "Failed"
        report["failed_groups"].append({"error": str(exc)})
        frappe.db.set_value(
            "TPA Revenue Batch",
            batch.name,
            {
                "status": "Failed",
                "processing_log": json.dumps(report, indent=2, ensure_ascii=False),
            },
        )
        frappe.log_error(
            title=f"TPA revenue processing failed for {batch.name}",
            message=frappe.get_traceback(),
        )
        _commit()
        raise


def _validate_batch_ready_for_processing(batch, allowed_statuses=("Imported", "Failed")):
    if batch.docstatus != 1:
        frappe.throw("Submit the TPA Revenue Batch before processing.")
    if batch.status not in allowed_statuses:
        frappe.throw(f"TPA revenue processing cannot run while the status is {batch.status}.")
    if not frappe.db.exists("TPA Revenue Event", {"revenue_batch": batch.name}):
        frappe.throw("This TPA Revenue Batch contains no imported events.")


def _build_validation_result(batch):
    content = _get_source_file_content(batch)
    parsed = parse_revenue_workbook(content)
    customer_by_payer_name = _get_customer_by_payer_name(parsed.payer_names)
    duplicate_file = bool(
        frappe.db.exists(
            "TPA Revenue Batch",
            {
                "source_file_hash": parsed.file_hash,
                "name": ["!=", batch.name],
            },
        )
    )
    return validate_revenue_workbook(
        parsed,
        customer_by_payer_name=customer_by_payer_name,
        duplicate_file=duplicate_file,
    )


def _get_source_file_content(batch):
    file_name = frappe.db.get_value("File", {"file_url": batch.source_file}, "name")
    if not file_name:
        frappe.throw("The attached endorsement report could not be found.")
    file_doc = frappe.get_doc("File", file_name)
    if file_doc.attached_to_doctype != batch.doctype or file_doc.attached_to_name != batch.name:
        frappe.throw("The endorsement report must be attached directly to this TPA Revenue Batch.")
    return file_doc.get_content()


def _store_validation_result(batch, preview):
    status = "Validated" if preview["valid"] else "Validation Failed"
    is_duplicate_file = any(error["code"] == "duplicate_file" for error in preview["errors"])
    frappe.db.set_value(
        "TPA Revenue Batch",
        batch.name,
        {
            "source_file_hash": None if is_duplicate_file else preview["file_hash"],
            "endorsement_year": preview["endorsement_year"],
            "endorsement_month": preview["endorsement_month"],
            "currency": preview["currency"],
            "total_events": preview["total_events"],
            "total_positive_events": preview["total_positive_events"],
            "total_deletion_events": preview["total_deletion_events"],
            "total_payers": preview["total_payers"],
            "total_invoice_amount": preview["total_invoice_amount"],
            "total_credit_note_amount": preview["total_credit_note_amount"],
            "net_tpa_fee": preview["net_tpa_fee"],
            "validation_summary": _build_validation_summary(preview),
            "validation_log": json.dumps(preview, indent=2, ensure_ascii=False),
            "status": status,
        },
    )


def _build_validation_summary(preview):
    errors = preview.get("errors") or []
    if not errors:
        return "Validation passed. The endorsement report is ready to import."

    messages = [error["message"] for error in errors[:10]]
    if len(errors) > 10:
        messages.append(f"... and {len(errors) - 10} more validation issue(s).")
    return "\n".join(messages)


def _get_customer_by_payer_name(payer_names):
    payer_names = {name for name in payer_names if name}
    if not payer_names:
        return {}

    customer_by_payer_name = {}
    for row in frappe.get_all(
        "Customer",
        filters={"name": ["in", sorted(payer_names)]},
        fields=["name", "customer_name"],
        limit_page_length=0,
    ):
        customer_by_payer_name[row.name] = row.name
        if row.customer_name in payer_names:
            customer_by_payer_name[row.customer_name] = row.name

    missing_after_name_lookup = payer_names - set(customer_by_payer_name)
    if missing_after_name_lookup:
        for row in frappe.get_all(
            "Customer",
            filters={"customer_name": ["in", sorted(missing_after_name_lookup)]},
            fields=["name", "customer_name"],
            limit_page_length=0,
        ):
            customer_by_payer_name[row.customer_name] = row.name
    return customer_by_payer_name


def _get_batch_events(batch_name, only_ready=False):
    filters = {"revenue_batch": batch_name}
    if only_ready:
        filters["status"] = "Ready"
    return frappe.get_all(
        "TPA Revenue Event",
        filters=filters,
        fields=["*"],
        order_by="source_row_number asc",
        limit_page_length=0,
    )


def _get_revenue_settings(company):
    settings = frappe.get_single("Lifeline TPA Settings")
    if settings.company != company:
        frappe.throw("Lifeline TPA Settings belongs to a different Company.")

    missing = [
        label
        for fieldname, label in (
            ("tpa_fee_item", "TPA Fee Item"),
            ("tpa_revenue_account", "TPA Revenue Account"),
            ("deferred_tpa_revenue_account", "Deferred TPA Revenue Account"),
            ("revenue_receivable_account", "Revenue Receivable Account"),
            ("default_cost_center", "Default Cost Center"),
        )
        if not settings.get(fieldname)
    ]
    if missing:
        frappe.throw("Complete Lifeline TPA Settings before revenue processing: " + ", ".join(missing))
    return settings


def _commit():
    if not frappe.flags.in_test:
        frappe.db.commit()
