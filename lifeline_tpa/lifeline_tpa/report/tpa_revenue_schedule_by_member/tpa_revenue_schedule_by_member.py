import frappe


def execute(filters=None):
    columns = [
        {
            "label": "Recognition Month",
            "fieldname": "recognition_month",
            "fieldtype": "Date",
            "width": 120,
        },
        {
            "label": "Payer",
            "fieldname": "payer",
            "fieldtype": "Link",
            "options": "Customer",
            "width": 220,
        },
        {"label": "Policy No", "fieldname": "policy_no", "fieldtype": "Data", "width": 160},
        {"label": "Member ID", "fieldname": "member_id", "fieldtype": "Data", "width": 140},
        {"label": "Eligible Days", "fieldname": "eligible_days", "fieldtype": "Int", "width": 100},
        {
            "label": "Scheduled Amount",
            "fieldname": "scheduled_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
        {
            "label": "Journal Entry",
            "fieldname": "recognition_journal_entry",
            "fieldtype": "Link",
            "options": "Journal Entry",
            "width": 180,
        },
    ]
    data = frappe.db.sql(
        """
        select
            recognition_month,
            payer,
            policy_no,
            member_id,
            eligible_days,
            scheduled_amount,
            currency,
            status,
            recognition_journal_entry
        from `tabTPA Revenue Schedule`
        order by recognition_month asc, payer asc, policy_no asc, member_id asc
        """,
        as_dict=True,
    )
    return columns, data
