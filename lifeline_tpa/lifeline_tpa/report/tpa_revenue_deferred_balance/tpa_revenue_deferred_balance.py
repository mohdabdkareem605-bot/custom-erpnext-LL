import frappe


def execute(filters=None):
    columns = [
        {
            "label": "Payer",
            "fieldname": "payer",
            "fieldtype": "Link",
            "options": "Customer",
            "width": 220,
        },
        {"label": "Policy No", "fieldname": "policy_no", "fieldtype": "Data", "width": 160},
        {"label": "Member ID", "fieldname": "member_id", "fieldtype": "Data", "width": 140},
        {
            "label": "Total Scheduled",
            "fieldname": "total_scheduled",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": "Recognized",
            "fieldname": "recognized_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": "Deferred Balance",
            "fieldname": "deferred_balance",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
    ]
    data = frappe.db.sql(
        """
        select
            payer,
            policy_no,
            member_id,
            currency,
            sum(scheduled_amount) as total_scheduled,
            sum(case when status = 'Posted' then scheduled_amount else 0 end) as recognized_amount,
            sum(case when status = 'Pending' then scheduled_amount else 0 end) as deferred_balance
        from `tabTPA Revenue Schedule`
        group by payer, policy_no, member_id, currency
        order by payer asc, policy_no asc, member_id asc
        """,
        as_dict=True,
    )
    return columns, data
