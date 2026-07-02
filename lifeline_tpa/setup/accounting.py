import frappe


COMPANY = "Khat al haya management of health insurance claim"
CLEARING_ACCOUNT_NAME = "Claims Clearing Control"
CLEARING_PARENT = "Direct Expenses - LL"
RECEIVABLE_ACCOUNT = "Trade in Opening Fees - LL"
PAYABLE_ACCOUNT = "Trade Payable - LL"
MEDICAL_CLAIM_ITEM = "MEDICAL-CLAIM"
TPA_FEE_ITEM = "TPA-FEE"
DEFAULT_COST_CENTER = "Main - LL"
TPA_REVENUE_ACCOUNT_NAME = "TPA Revenue"
TPA_REVENUE_PARENT = "Direct Revenue - LL"
DEFERRED_TPA_REVENUE_ACCOUNT_NAME = "Deferred TPA Revenue"
DEFERRED_TPA_REVENUE_PARENT = "Current Liabilities - LL"
REVENUE_TAX_TEMPLATE = "UAE VAT 5% - LL"


def preview():
    clearing_account = _account_name(CLEARING_ACCOUNT_NAME)
    tpa_revenue_account = _account_name(TPA_REVENUE_ACCOUNT_NAME)
    deferred_tpa_revenue_account = _account_name(DEFERRED_TPA_REVENUE_ACCOUNT_NAME)
    return {
        "company": COMPANY,
        "writes": [
            {
                "doctype": "Account",
                "action": "reuse" if clearing_account else "create",
                "name": clearing_account or f"{CLEARING_ACCOUNT_NAME} - LL",
                "parent_account": CLEARING_PARENT,
            },
            {
                "doctype": "Item",
                "action": (
                    "reuse"
                    if frappe.db.exists("Item", MEDICAL_CLAIM_ITEM)
                    else "create"
                ),
                "name": MEDICAL_CLAIM_ITEM,
                "item_group": "Services",
                "is_stock_item": 0,
            },
            {
                "doctype": "Account",
                "action": "reuse" if tpa_revenue_account else "create",
                "name": tpa_revenue_account or f"{TPA_REVENUE_ACCOUNT_NAME} - LL",
                "parent_account": TPA_REVENUE_PARENT,
            },
            {
                "doctype": "Account",
                "action": "reuse" if deferred_tpa_revenue_account else "create",
                "name": (
                    deferred_tpa_revenue_account
                    or f"{DEFERRED_TPA_REVENUE_ACCOUNT_NAME} - LL"
                ),
                "parent_account": DEFERRED_TPA_REVENUE_PARENT,
            },
            {
                "doctype": "Item",
                "action": (
                    "reuse"
                    if frappe.db.exists("Item", TPA_FEE_ITEM)
                    else "create"
                ),
                "name": TPA_FEE_ITEM,
                "item_group": "Services",
                "is_stock_item": 0,
            },
            {
                "doctype": "Lifeline TPA Settings",
                "action": "update",
                "company": COMPANY,
                "claims_receivable_account": RECEIVABLE_ACCOUNT,
                "claims_payable_account": PAYABLE_ACCOUNT,
                "claims_clearing_account": (
                    clearing_account or f"{CLEARING_ACCOUNT_NAME} - LL"
                ),
                "medical_claim_item": MEDICAL_CLAIM_ITEM,
                "default_cost_center": DEFAULT_COST_CENTER,
                "tpa_fee_item": TPA_FEE_ITEM,
                "tpa_revenue_account": tpa_revenue_account or f"{TPA_REVENUE_ACCOUNT_NAME} - LL",
                "deferred_tpa_revenue_account": (
                    deferred_tpa_revenue_account
                    or f"{DEFERRED_TPA_REVENUE_ACCOUNT_NAME} - LL"
                ),
                "revenue_receivable_account": RECEIVABLE_ACCOUNT,
                "revenue_sales_taxes_template": REVENUE_TAX_TEMPLATE,
                "max_revenue_invoice_lines": 1000,
            },
        ],
        "posts_accounting_entries": False,
    }


def apply():
    setup_preview = preview()
    clearing_account = _get_or_create_clearing_account()
    item = _get_or_create_medical_claim_item(clearing_account)
    tpa_revenue_account = _get_or_create_account(
        TPA_REVENUE_ACCOUNT_NAME,
        TPA_REVENUE_PARENT,
    )
    deferred_tpa_revenue_account = _get_or_create_account(
        DEFERRED_TPA_REVENUE_ACCOUNT_NAME,
        DEFERRED_TPA_REVENUE_PARENT,
    )
    tpa_fee_item = _get_or_create_tpa_fee_item(tpa_revenue_account)

    settings = frappe.get_single("Lifeline TPA Settings")
    settings.update(
        {
            "company": COMPANY,
            "claims_receivable_account": RECEIVABLE_ACCOUNT,
            "claims_payable_account": PAYABLE_ACCOUNT,
            "claims_clearing_account": clearing_account,
            "medical_claim_item": item.name,
            "default_cost_center": DEFAULT_COST_CENTER,
            "tpa_fee_item": tpa_fee_item.name,
            "tpa_revenue_account": tpa_revenue_account,
            "deferred_tpa_revenue_account": deferred_tpa_revenue_account,
            "revenue_receivable_account": RECEIVABLE_ACCOUNT,
            "revenue_sales_taxes_template": (
                REVENUE_TAX_TEMPLATE
                if frappe.db.exists("Sales Taxes and Charges Template", REVENUE_TAX_TEMPLATE)
                else None
            ),
            "max_revenue_invoice_lines": 1000,
        }
    )
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "preview": setup_preview,
        "verified": verify(),
    }


def verify():
    settings = frappe.get_single("Lifeline TPA Settings")
    clearing_account = frappe.get_doc("Account", settings.claims_clearing_account)
    item = frappe.get_doc("Item", settings.medical_claim_item)
    item_default = next(
        (
            row
            for row in item.item_defaults
            if row.company == settings.company
        ),
        None,
    )
    return {
        "company": settings.company,
        "claims_receivable_account": settings.claims_receivable_account,
        "claims_payable_account": settings.claims_payable_account,
        "claims_clearing_account": settings.claims_clearing_account,
        "clearing_account_parent": clearing_account.parent_account,
        "medical_claim_item": settings.medical_claim_item,
        "item_is_stock_item": item.is_stock_item,
        "item_expense_account": item_default.expense_account if item_default else None,
        "item_income_account": item_default.income_account if item_default else None,
        "default_cost_center": settings.default_cost_center,
        "tpa_fee_item": settings.tpa_fee_item,
        "tpa_revenue_account": settings.tpa_revenue_account,
        "deferred_tpa_revenue_account": settings.deferred_tpa_revenue_account,
        "revenue_receivable_account": settings.revenue_receivable_account,
        "revenue_sales_taxes_template": settings.revenue_sales_taxes_template,
        "max_revenue_invoice_lines": settings.max_revenue_invoice_lines,
    }


def _account_name(account_name):
    return frappe.db.get_value(
        "Account",
        {"account_name": account_name, "company": COMPANY},
        "name",
    )


def _get_or_create_clearing_account():
    return _get_or_create_account(CLEARING_ACCOUNT_NAME, CLEARING_PARENT)


def _get_or_create_account(account_name, parent_account):
    existing = _account_name(account_name)
    if existing:
        return existing

    return frappe.get_doc(
        {
            "doctype": "Account",
            "account_name": account_name,
            "parent_account": parent_account,
            "company": COMPANY,
            "account_currency": "AED",
            "is_group": 0,
        }
    ).insert(ignore_permissions=True).name


def _get_or_create_medical_claim_item(clearing_account):
    if frappe.db.exists("Item", MEDICAL_CLAIM_ITEM):
        item = frappe.get_doc("Item", MEDICAL_CLAIM_ITEM)
    else:
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": MEDICAL_CLAIM_ITEM,
                "item_name": "Medical Claim",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "include_item_in_manufacturing": 0,
            }
        )

    item.item_defaults = [
        row
        for row in item.item_defaults
        if row.company != COMPANY
    ]
    item.append(
        "item_defaults",
        {
            "company": COMPANY,
            "expense_account": clearing_account,
            "income_account": clearing_account,
            "buying_cost_center": DEFAULT_COST_CENTER,
            "selling_cost_center": DEFAULT_COST_CENTER,
        },
    )
    if item.is_new():
        item.insert(ignore_permissions=True)
    else:
        item.save(ignore_permissions=True)
    return item


def _get_or_create_tpa_fee_item(tpa_revenue_account):
    if frappe.db.exists("Item", TPA_FEE_ITEM):
        item = frappe.get_doc("Item", TPA_FEE_ITEM)
    else:
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": TPA_FEE_ITEM,
                "item_name": "TPA Fee",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "include_item_in_manufacturing": 0,
            }
        )

    item.item_defaults = [
        row
        for row in item.item_defaults
        if row.company != COMPANY
    ]
    item.append(
        "item_defaults",
        {
            "company": COMPANY,
            "income_account": tpa_revenue_account,
            "selling_cost_center": DEFAULT_COST_CENTER,
        },
    )
    if item.is_new():
        item.insert(ignore_permissions=True)
    else:
        item.save(ignore_permissions=True)
    return item
