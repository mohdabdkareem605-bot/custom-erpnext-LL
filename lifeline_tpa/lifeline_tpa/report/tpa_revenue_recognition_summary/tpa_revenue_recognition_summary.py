import frappe


def execute(filters=None):
    columns = [
        {
            "label": "Run",
            "fieldname": "name",
            "fieldtype": "Link",
            "options": "TPA Revenue Recognition Run",
            "width": 180,
        },
        {"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 220},
        {"label": "Recognition Month", "fieldname": "recognition_month", "fieldtype": "Date", "width": 130},
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": "Schedule Rows", "fieldname": "total_schedule_rows", "fieldtype": "Int", "width": 120},
        {
            "label": "Schedule Amount",
            "fieldname": "total_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": "Posted Amount",
            "fieldname": "posted_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": "Journal Entry",
            "fieldname": "journal_entry",
            "fieldtype": "Link",
            "options": "Journal Entry",
            "width": 180,
        },
    ]
    data = frappe.db.sql(
        """
        select
            name,
            company,
            recognition_month,
            currency,
            status,
            total_schedule_rows,
            total_amount,
            posted_amount,
            journal_entry
        from `tabTPA Revenue Recognition Run`
        order by recognition_month desc, modified desc
        """,
        as_dict=True,
    )
    return columns, data
