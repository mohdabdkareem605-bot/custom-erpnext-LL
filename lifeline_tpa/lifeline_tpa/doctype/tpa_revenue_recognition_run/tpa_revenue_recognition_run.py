import json

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

from lifeline_tpa.lifeline_tpa.doctype.tpa_revenue_batch.tpa_revenue_batch import (
    _get_revenue_settings,
)
from lifeline_tpa.services.revenue_processing import (
    create_recognition_journal_entry,
    get_unposted_schedule_summary,
)
from lifeline_tpa.services.revenue_schedule import first_day_of_month


class TPARevenueRecognitionRun(Document):
    def validate(self):
        if self.recognition_month:
            self.recognition_month = first_day_of_month(getdate(self.recognition_month))

    def before_submit(self):
        if self.status != "Previewed":
            frappe.throw("Preview this recognition run before submitting it.")
        if frappe.db.exists(
            "TPA Revenue Recognition Run",
            {
                "company": self.company,
                "recognition_month": self.recognition_month,
                "status": "Posted",
                "name": ["!=", self.name],
            },
        ):
            frappe.throw("TPA revenue recognition is already posted for this company and month.")

    def on_cancel(self):
        if self.status == "Posted":
            frappe.throw(
                "A posted revenue recognition run cannot be cancelled automatically. "
                "Reverse the Journal Entry through an approved adjustment."
            )
        self.db_set("status", "Cancelled", update_modified=False)


@frappe.whitelist()
def preview_recognition_run(run_name):
    run = frappe.get_doc("TPA Revenue Recognition Run", run_name)
    run.check_permission("write")
    if run.docstatus != 0:
        frappe.throw("Only a draft recognition run can be previewed.")

    summary = get_unposted_schedule_summary(run.company, run.recognition_month)
    result = {
        "valid": bool(summary["schedule_rows"]),
        "company": run.company,
        "recognition_month": str(run.recognition_month),
        "total_schedule_rows": summary["total_rows"],
        "total_amount": float(summary["total_amount"]),
        "posted_amount": float(summary["posted_amount"]),
        "payer_count": summary["payer_count"],
        "currencies": summary["currencies"],
    }
    run.total_schedule_rows = result["total_schedule_rows"]
    run.total_amount = result["total_amount"]
    run.posted_amount = result["posted_amount"]
    run.currency = summary["currencies"][0] if len(summary["currencies"]) == 1 else "AED"
    run.preview_log = json.dumps(result, indent=2, ensure_ascii=False)
    run.status = "Previewed" if result["valid"] else "Draft"
    run.save(ignore_permissions=True)
    return result


@frappe.whitelist()
def post_recognition_run(run_name):
    run = frappe.get_doc("TPA Revenue Recognition Run", run_name)
    run.check_permission("write")
    if run.docstatus != 1:
        frappe.throw("Submit the recognition run before posting.")
    if run.status == "Posted":
        frappe.throw("This recognition run is already posted.")
    if run.status != "Previewed":
        frappe.throw("Preview this recognition run before posting.")

    settings = _get_revenue_settings(run.company)
    try:
        result = create_recognition_journal_entry(run, settings)
        result["status"] = "Posted"
        frappe.db.set_value(
            "TPA Revenue Recognition Run",
            run.name,
            {
                "status": "Posted",
                "journal_entry": result["journal_entry"],
                "total_schedule_rows": result["total_rows"],
                "total_amount": result["total_amount"],
                "posted_amount": result["posted_amount"],
                "processed_by": frappe.session.user,
                "processed_date": now_datetime(),
                "processing_log": json.dumps(result, indent=2, ensure_ascii=False),
            },
        )
        if not frappe.flags.in_test:
            frappe.db.commit()
        return result
    except Exception as exc:
        result = {"status": "Failed", "error": str(exc)}
        frappe.db.set_value(
            "TPA Revenue Recognition Run",
            run.name,
            {
                "status": "Failed",
                "processing_log": json.dumps(result, indent=2, ensure_ascii=False),
            },
        )
        frappe.log_error(
            title=f"TPA revenue recognition failed for {run.name}",
            message=frappe.get_traceback(),
        )
        if not frappe.flags.in_test:
            frappe.db.commit()
        raise
