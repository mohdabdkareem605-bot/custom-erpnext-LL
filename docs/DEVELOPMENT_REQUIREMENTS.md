# Development Requirements

## 1. Platform requirements

The development and UAT environments must use the same major versions:

| Component | Requirement |
|---|---|
| Frappe Framework | Version 15 |
| ERPNext | Version 15 |
| Python | 3.10–3.13; use 3.12 for the local bench |
| Node.js | 18 or 20; use 20 |
| Database | MariaDB 10.6 or newer supported by Frappe v15 |
| Redis | Required for cache, queues, and realtime events |
| Yarn | Required for Frappe assets |
| wkhtmltopdf | Required for PDF printing |
| Operating system | Ubuntu under WSL 2 for Windows development |
| Source control | Git |

Do not run the Frappe stack directly in native Windows Python. Keep the bench
inside the WSL Linux filesystem. The app source remains in this repository and
is soft-linked into the bench.

## 2. ERPNext master-data requirements

Before end-to-end processing can be tested, Finance must provide:

- Company and default currency
- One Customer master per payer
- One Supplier master per provider
- Facility ID to Supplier mapping
- Supplier bank accounts and approved beneficiary details
- Company bank accounts
- Cost centre
- Medical Claim service item
- Claims Receivable account
- Claims Payable account
- Claims Clearing Control account
- Posting-date and fiscal-year rules

Provider matching must use `Provider reference No` as the external Facility ID.
Provider names from the spreadsheet are descriptive and must not be the unique
matching key.

## 3. PO import requirements

- Read only the worksheet named `Master Sheet`.
- Require the exact 34 source columns in the agreed order.
- Preserve the uploaded workbook as an immutable source attachment.
- Select one payer on the ERPNext batch before validation.
- Treat `POID/Year` as the external PO reference.
- Treat `Unique Transaction ID` as the claim reference.
- Treat `Provider reference No` as the provider/facility identifier.
- Treat `Invoice #` as the provider's source invoice reference.
- Use `Payer Share CV` as the initial accounting amount.
- Require one PO reference and one CV currency per uploaded file.
- Reject duplicate claim references and repeated file uploads.
- Record the uploaded file hash for idempotency.
- Display claim count, provider count, amount and validation errors before processing.

## 4. Bulk-processing requirements

For each provider/facility group in one PO:

1. Create one submitted Purchase Invoice.
2. Use the Purchase Invoice number as the Process Payable Number.
3. Create one matching submitted Sales Invoice for the selected payer.
4. Link every Claim Record in that group to both invoices.
5. Require matching Purchase and Sales Invoice totals.
6. Require the Claims Clearing Control balance for the batch to be zero.

The process must:

- Run as a background job.
- Be safe to retry without duplicate accounting documents.
- Record job progress and per-provider failures.
- Use standard ERPNext documents and never insert GL Entry rows directly.
- Roll back an individual provider group if its accounting pair fails.
- Prevent edits to accounting-critical imported values after processing.

## 5. Processed PO export requirements

The generated workbook must retain the original 34 columns and append:

- Payer
- Process Payable Number
- Sales Invoice Number
- Payer Paid Amount
- Payer Payment Reference
- Payer Payment Date
- Payer Payment Status
- Provider Paid Amount
- Provider Payment Reference
- Provider Payment Date
- Provider Payment Status

`Unique Transaction ID` remains the lookup key for claim-wise remittance.

## 6. Payer-settlement requirements

Support both modes:

### Claim-wise allocation

- Upload claim reference, paid amount, bank reference and value date.
- Validate every claim against the selected payer and PO.
- Prevent duplicate reference/allocation processing.
- Support partial claim payments.
- Reconcile settlement-line total to the bank receipt.

### PO/process-payable allocation

- Select payer and PO.
- Enter the bank receipt amount and reference.
- Display Process Payable Numbers and outstanding amounts.
- Permit manual allocation.
- Provide an explicit preview before optional auto-allocation.
- Map each Process Payable to its matching Sales Invoice.

Accounting is posted through standard Payment Entry:

```text
Bank                            Dr
    Payer Receivable               Cr
```

Claim-level allocation remains in the custom settlement subledger.

## 7. Provider-settlement requirements

- Select provider and outstanding Process Payables.
- Record cheque/transfer reference, release date and amount.
- Support full and partial settlement.
- Generate standard Supplier Payment Entries.
- Update claim-level provider settlement independently from payer settlement.

Accounting:

```text
Provider Payable                Dr
    Bank                           Cr
```

## 8. Claim-removal and hold requirements

Missing bank details produce a `Settlement Hold`; they do not reverse accounting.

A genuine medical-team withdrawal produces:

- Purchase Debit Note against the provider Purchase Invoice
- Sales Credit Note against the payer Sales Invoice
- Claim Adjustment audit record
- Recalculated claim and invoice outstanding values

Claims already collected or paid require Finance Manager approval and explicit
reallocation or recovery treatment.

## 9. Security and audit requirements

- Roles: Lifeline TPA Manager, Lifeline TPA User, Lifeline TPA Read Only.
- Restrict sensitive patient and national-identity information.
- Keep original source files immutable.
- Log validation, processing, settlement, removal and retry events.
- Use maker/checker approval for removals and settlement batches.
- Never store bank credentials or passwords in source control.
- Apply standard ERPNext document cancellation/amendment controls.

## 10. Performance and acceptance requirements

Initial volume test:

| Measure | Expected sample result |
|---|---:|
| Claims | 3,516 |
| Provider groups | 340 |
| PO reference | DNIRC-000150/2026 |
| Total | AED 401,060.87 |
| Clearing difference | AED 0.00 |

The import and processing design must also be tested at projected peak PO size.
Background jobs must expose progress and remain safely restartable.

## 11. Development quality requirements

- Business logic belongs in Python services, not Client Scripts.
- Client Scripts only control presentation and call whitelisted server methods.
- Add unit tests for schema validation, grouping and allocation rules.
- Add integration tests for invoices, returns and Payment Entries.
- Use migrations/patches for all production data changes.
- Require code review and UAT sign-off before production installation.

