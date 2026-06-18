MASTER_SHEET_NAME = "Master Sheet"

MASTER_SHEET_COLUMNS = (
    "Provider Name",
    "Contract Name",
    "Policy Number",
    "Inception Date",
    "Expiry Date",
    "Policy Jurisdiction",
    "FOB",
    "Authorization Num",
    "Invoice #",
    "Card Number",
    "Claimed amount",
    "Approved amount",
    "Currency",
    "Approved amount CV",
    "CV Currency",
    "Payer Share CV",
    "Beneficiary Share",
    "POID/Year",
    "PO Validation Date",
    "E-claims/Non e-claims",
    "Provider reference No",
    "Admission Date",
    "Unique Transaction ID",
    "Delivery Date",
    "Reference no",
    "Claim_Type",
    "DIAGNOSIS",
    "Reported to TPA/ submitted to Post office or to TPA",
    "Principal Card No",
    "First Name",
    "Middle Name",
    "Last Name",
    "Beneficiary FullName",
    "National IdentityNo",
)

CLAIM_REFERENCE_COLUMN = "Unique Transaction ID"
EXTERNAL_PO_COLUMN = "POID/Year"
PROVIDER_FACILITY_COLUMN = "Provider reference No"
PROVIDER_INVOICE_COLUMN = "Invoice #"
ACCOUNTING_AMOUNT_COLUMN = "Payer Share CV"
ACCOUNTING_CURRENCY_COLUMN = "CV Currency"


def compare_headers(headers):
    actual = tuple("" if value is None else str(value).strip() for value in headers)
    expected = MASTER_SHEET_COLUMNS

    missing = [column for column in expected if column not in actual]
    unexpected = [column for column in actual if column and column not in expected]
    wrong_order = not missing and not unexpected and actual != expected

    return {
        "valid": actual == expected,
        "missing": missing,
        "unexpected": unexpected,
        "wrong_order": wrong_order,
        "expected": expected,
        "actual": actual,
    }

