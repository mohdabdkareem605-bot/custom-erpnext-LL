import frappe


def execute(filters=None):
    columns = [
        {
            "label": "Revenue Batch",
            "fieldname": "revenue_batch",
            "fieldtype": "Link",
            "options": "TPA Revenue Batch",
            "width": 180,
        },
        {
            "label": "Payer",
            "fieldname": "payer",
            "fieldtype": "Link",
            "options": "Customer",
            "width": 220,
        },
        {"label": "Events", "fieldname": "event_count", "fieldtype": "Int", "width": 90},
        {
            "label": "Invoice Amount",
            "fieldname": "invoice_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {
            "label": "Credit Note Amount",
            "fieldname": "credit_note_amount",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
        {
            "label": "Net TPA Fee",
            "fieldname": "net_tpa_fee",
            "fieldtype": "Currency",
            "options": "currency",
            "width": 140,
        },
        {"label": "Sales Invoices", "fieldname": "sales_invoice_count", "fieldtype": "Int", "width": 120},
        {"label": "Credit Notes", "fieldname": "credit_note_count", "fieldtype": "Int", "width": 120},
        {"label": "Deferral JEs", "fieldname": "deferral_je_count", "fieldtype": "Int", "width": 120},
    ]
    data = frappe.db.sql(
        """
        select
            revenue_batch,
            payer,
            currency,
            count(*) as event_count,
            sum(case when tpa_fee > 0 then tpa_fee else 0 end) as invoice_amount,
            sum(case when tpa_fee < 0 then tpa_fee else 0 end) as credit_note_amount,
            sum(tpa_fee) as net_tpa_fee,
            count(distinct sales_invoice) as sales_invoice_count,
            count(distinct sales_credit_note) as credit_note_count,
            count(distinct deferral_journal_entry) as deferral_je_count
        from `tabTPA Revenue Event`
        group by revenue_batch, payer, currency
        order by revenue_batch desc, payer asc
        """,
        as_dict=True,
    )
    return columns, data
