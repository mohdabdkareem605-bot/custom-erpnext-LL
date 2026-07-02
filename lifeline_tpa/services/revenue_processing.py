from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe.utils import flt, getdate

from lifeline_tpa.services.revenue_schedule import (
    build_revenue_schedule,
    rounded_posting_amount,
)


@dataclass(frozen=True)
class RevenueDocumentGroup:
    payer: str
    document_type: str
    chunk_index: int
    events: tuple

    @property
    def total_amount(self):
        return sum((Decimal(str(event.tpa_fee)) for event in self.events), Decimal("0"))

    def as_dict(self):
        return {
            "payer": self.payer,
            "document_type": self.document_type,
            "chunk_index": self.chunk_index,
            "event_count": len(self.events),
            "total_amount": float(self.total_amount),
        }


def group_revenue_events(events, max_lines):
    max_lines = int(max_lines or 1000)
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1.")

    grouped = {}
    for event in events:
        amount = Decimal(str(event.tpa_fee))
        document_type = "Credit Note" if amount < 0 else "Sales Invoice"
        grouped.setdefault((event.payer, document_type), []).append(event)

    result = []
    for (payer, document_type), group_events in sorted(grouped.items()):
        group_events = sorted(group_events, key=lambda event: event.source_row_number)
        for index in range(0, len(group_events), max_lines):
            result.append(
                RevenueDocumentGroup(
                    payer=payer,
                    document_type=document_type,
                    chunk_index=(index // max_lines) + 1,
                    events=tuple(group_events[index : index + max_lines]),
                )
            )
    return result


def summarize_revenue_groups(groups):
    invoice_total = sum(
        (group.total_amount for group in groups if group.document_type == "Sales Invoice"),
        Decimal("0"),
    )
    credit_note_total = sum(
        (group.total_amount for group in groups if group.document_type == "Credit Note"),
        Decimal("0"),
    )
    return {
        "document_count": len(groups),
        "sales_invoice_count": sum(group.document_type == "Sales Invoice" for group in groups),
        "credit_note_count": sum(group.document_type == "Credit Note" for group in groups),
        "event_count": sum(len(group.events) for group in groups),
        "invoice_total": float(invoice_total),
        "credit_note_total": float(credit_note_total),
        "net_total": float(invoice_total + credit_note_total),
    }


def create_revenue_accounting_documents(batch, events, settings):
    groups = group_revenue_events(events, settings.max_revenue_invoice_lines or 1000)
    results = []
    for group in groups:
        sales_doc = _make_sales_document(batch, group, settings)
        sales_doc.insert(ignore_permissions=True)
        sales_doc.submit()

        deferral_journal_entry = _make_deferral_journal_entry(batch, group, settings)
        deferral_journal_entry.insert(ignore_permissions=True)
        deferral_journal_entry.submit()

        _link_group_events(group, sales_doc, deferral_journal_entry)
        results.append(
            {
                **group.as_dict(),
                "sales_invoice": sales_doc.name if group.document_type == "Sales Invoice" else None,
                "sales_credit_note": sales_doc.name if group.document_type == "Credit Note" else None,
                "deferral_journal_entry": deferral_journal_entry.name,
                "grand_total": flt(sales_doc.grand_total),
                "net_total": flt(sales_doc.net_total),
            }
        )
    return {
        "groups": results,
        **summarize_revenue_groups(groups),
    }


def create_revenue_schedules_for_events(events):
    created = 0
    total_amount = Decimal("0")
    for event in events:
        if frappe.db.exists("TPA Revenue Schedule", {"revenue_event": event.name}):
            continue

        lines = build_revenue_schedule(
            amount=event.tpa_fee,
            service_start=getdate(event.endorsement_date),
            service_end=getdate(event.policy_stop_date),
        )
        for line in lines:
            frappe.get_doc(
                {
                    "doctype": "TPA Revenue Schedule",
                    "revenue_event": event.name,
                    "revenue_batch": event.revenue_batch,
                    "company": event.company,
                    "payer": event.payer,
                    "member_id": event.member_id,
                    "card_no": event.card_no,
                    "policy_no": event.policy_no,
                    "recognition_month": line.recognition_month,
                    "month_start": line.month_start,
                    "month_end": line.month_end,
                    "service_days": line.service_days,
                    "eligible_days": line.eligible_days,
                    "scheduled_amount": line.scheduled_amount,
                    "currency": event.currency,
                    "status": "Pending",
                }
            ).insert(ignore_permissions=True)
            total_amount += line.scheduled_amount
            created += 1
    return {
        "created_schedule_rows": created,
        "total_schedule_amount": float(total_amount),
    }


def get_unposted_schedule_summary(company, recognition_month):
    rows = frappe.get_all(
        "TPA Revenue Schedule",
        filters={
            "company": company,
            "recognition_month": recognition_month,
            "status": "Pending",
        },
        fields=["name", "scheduled_amount", "payer", "currency"],
        order_by="payer asc, name asc",
        limit_page_length=0,
    )
    total = sum((Decimal(str(row.scheduled_amount)) for row in rows), Decimal("0"))
    return {
        "schedule_rows": rows,
        "total_rows": len(rows),
        "total_amount": total,
        "posted_amount": rounded_posting_amount(total),
        "payer_count": len({row.payer for row in rows}),
        "currencies": sorted({row.currency for row in rows if row.currency}),
    }


def create_recognition_journal_entry(run, settings):
    summary = get_unposted_schedule_summary(run.company, run.recognition_month)
    amount = summary["posted_amount"]
    if not summary["schedule_rows"]:
        frappe.throw("There are no pending TPA revenue schedule rows for this month.")
    if amount == Decimal("0.00"):
        frappe.throw("The pending TPA revenue amount is zero; no Journal Entry is needed.")

    absolute_amount = abs(amount)
    if amount > 0:
        accounts = [
            {
                "account": settings.deferred_tpa_revenue_account,
                "debit_in_account_currency": absolute_amount,
                "credit_in_account_currency": 0,
            },
            {
                "account": settings.tpa_revenue_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": absolute_amount,
            },
        ]
    else:
        accounts = [
            {
                "account": settings.tpa_revenue_account,
                "debit_in_account_currency": absolute_amount,
                "credit_in_account_currency": 0,
            },
            {
                "account": settings.deferred_tpa_revenue_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": absolute_amount,
            },
        ]

    journal_entry = frappe.get_doc(
        {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": run.company,
            "posting_date": run.posting_date,
            "user_remark": (
                f"TPA revenue recognition for {run.recognition_month} "
                f"from run {run.name}."
            ),
            "accounts": accounts,
        }
    )
    journal_entry.insert(ignore_permissions=True)
    journal_entry.submit()

    schedule_names = [row.name for row in summary["schedule_rows"]]
    for schedule_name in schedule_names:
        frappe.db.set_value(
            "TPA Revenue Schedule",
            schedule_name,
            {
                "status": "Posted",
                "recognition_run": run.name,
                "recognition_journal_entry": journal_entry.name,
            },
            update_modified=False,
        )
    return {
        "journal_entry": journal_entry.name,
        "total_rows": summary["total_rows"],
        "total_amount": float(summary["total_amount"]),
        "posted_amount": float(amount),
    }


def _make_sales_document(batch, group, settings):
    is_credit_note = group.document_type == "Credit Note"
    doc = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "company": batch.company,
            "customer": group.payer,
            "posting_date": batch.posting_date,
            "due_date": batch.posting_date,
            "currency": batch.currency,
            "is_return": 1 if is_credit_note else 0,
            "disable_rounded_total": 1,
            "debit_to": settings.revenue_receivable_account,
            "cost_center": settings.default_cost_center,
            "taxes_and_charges": settings.revenue_sales_taxes_template,
            "remarks": (
                f"Lifeline TPA revenue {group.document_type.lower()} for "
                f"{batch.name}, endorsement {batch.endorsement_year}-"
                f"{int(batch.endorsement_month):02d}, group {group.chunk_index}."
            ),
            "items": [_sales_item(event, settings, is_credit_note) for event in group.events],
        }
    )
    if doc.taxes_and_charges:
        _append_sales_taxes_from_template(doc, doc.taxes_and_charges)
    doc.run_method("calculate_taxes_and_totals")
    return doc


def _append_sales_taxes_from_template(doc, template):
    tax_rows = frappe.get_all(
        "Sales Taxes and Charges",
        filters={"parent": template, "parenttype": "Sales Taxes and Charges Template"},
        fields=[
            "charge_type",
            "account_head",
            "description",
            "rate",
            "cost_center",
            "included_in_print_rate",
            "included_in_paid_amount",
        ],
        order_by="idx asc",
        limit_page_length=0,
    )
    for tax_row in tax_rows:
        doc.append(
            "taxes",
            {
                "charge_type": tax_row.charge_type,
                "account_head": tax_row.account_head,
                "description": tax_row.description,
                "rate": tax_row.rate,
                "cost_center": tax_row.cost_center,
                "included_in_print_rate": tax_row.included_in_print_rate,
                "included_in_paid_amount": tax_row.included_in_paid_amount,
            },
        )


def _sales_item(event, settings, is_credit_note):
    amount = abs(Decimal(str(event.tpa_fee)))
    return {
        "item_code": settings.tpa_fee_item,
        "qty": -1 if is_credit_note else 1,
        "rate": amount,
        "description": (
            f"TPA fee | Member: {event.member_id} | Card: {event.card_no} | "
            f"Policy: {event.policy_no} | Endorsement: {event.endorsement_type} "
            f"on {event.endorsement_date}"
        ),
        "income_account": settings.tpa_revenue_account,
        "cost_center": settings.default_cost_center,
    }


def _make_deferral_journal_entry(batch, group, settings):
    amount = abs(group.total_amount)
    is_credit_note = group.document_type == "Credit Note"
    if is_credit_note:
        accounts = [
            {
                "account": settings.deferred_tpa_revenue_account,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
            },
            {
                "account": settings.tpa_revenue_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
            },
        ]
    else:
        accounts = [
            {
                "account": settings.tpa_revenue_account,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
            },
            {
                "account": settings.deferred_tpa_revenue_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
            },
        ]

    return frappe.get_doc(
        {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": batch.company,
            "posting_date": batch.posting_date,
            "user_remark": (
                f"TPA revenue deferral for {batch.name}, "
                f"{group.document_type}, group {group.chunk_index}."
            ),
            "accounts": accounts,
        }
    )


def _link_group_events(group, sales_doc, deferral_journal_entry):
    if len(group.events) != len(sales_doc.items):
        frappe.throw("TPA revenue document item count does not match event count.")

    for event, item in zip(group.events, sales_doc.items, strict=True):
        values = {
            "sales_invoice_item": item.name,
            "deferral_journal_entry": deferral_journal_entry.name,
            "status": "Processed",
        }
        if group.document_type == "Credit Note":
            values["sales_credit_note"] = sales_doc.name
        else:
            values["sales_invoice"] = sales_doc.name
        frappe.db.set_value(
            "TPA Revenue Event",
            event.name,
            values,
            update_modified=False,
        )
