# Lifeline TPA ERPNext Custom App

`lifeline_tpa` is a private Frappe/ERPNext application for accounting approved
medical claims received from Lifeline TPA's external medical system.

The medical system remains the source for claim adjudication and PO generation.
This app starts from the approved PO Excel export and manages:

- PO validation and claim import
- Claim-level accounting records
- Process Payable generation per provider
- Matching payer Sales Invoices
- Claim-wise and PO/process-payable payer settlement
- Provider settlement
- Claim removal and settlement holds
- Audit and reconciliation reports

## Target platform

- Frappe Framework: version 15
- ERPNext: version 15
- Development OS: Ubuntu under WSL 2
- Source repository: this directory
- Bench runtime: WSL Linux filesystem, with this app soft-linked into the bench

See:

- [Development requirements](docs/DEVELOPMENT_REQUIREMENTS.md)
- [Windows/WSL setup](docs/SETUP_WINDOWS_WSL.md)
- [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md)

## Current status

The app is installed on the local ERPNext v15 development site. Phase 1 now
includes:

- Exact `Master Sheet` schema validation
- File-hash and duplicate-claim protection
- PO, currency, provider, claim-count, and amount validation preview
- Provider Facility Mapping checks
- Claim Record import without accounting entries
- Unit and ERPNext integration tests

The full sample workbook is confirmed as 3,516 claims, 340 provider facilities,
and AED 401,060.87. The current pilot uses five providers and 708 claims before
the remaining provider masters are loaded.

## Where to find the module

Open ERPNext at `http://lifeline.localhost:8000`, then select **Lifeline TPA**
from the left sidebar. The workspace contains:

- **Claims PO Batch** — upload, validate, and import a PO workbook.
- **Claim Record** — review the imported claim-level records.
- **Payer Receipt Settlement** — upload payer receipt claim allocations.
- **Provider Payment Settlement** — upload provider payment claim allocations.
- **Claim Removal Batch** — validate and process approved claim removals.
- **Provider Facility Mapping** — connect external facility IDs to Suppliers.
- **Lifeline TPA Settings** — configure accounting defaults for later phases.

The direct workspace URL is:

`http://lifeline.localhost:8000/app/lifeline-tpa`

For each custom sheet upload form, use **Actions → Download Upload Template**
before filling and attaching the file.

The current pilot is batch `CPO-2026-00001`, imported for payer `DNIRC` with
708 claims across five providers for AED 38,104.57.

After submitting this batch:

- Use **Actions → Preview Bulk Processing** to validate the provider groups
  without saving or posting accounting documents.
- Use **Actions → Run Bulk Processing** to confirm and queue the accounting
  job. Each provider group creates one submitted Purchase Invoice and one
  matching submitted Sales Invoice.

The job links every claim to both invoices, commits each provider group
independently, records failures in the Processing Log, supports safe retries,
and only marks the batch Processed when the batch clearing difference is zero.
All app-generated invoices use **Disable Rounded Total**, so AED fils are
posted exactly to payer and provider ledgers.

After processing, use **Actions → Download Processed PO** to download an Excel
workbook containing the original 34 source columns plus the payer, invoice,
payment amount, payment reference, payment date, and settlement-status fields.
Claims remain in their original source-row order.

## Settling claims

Payer receipts and provider payments are separate because they happen at
different times.

For money received from a payer, open **Payer Receipt Settlement** and upload a
`.xlsx` or `.csv` file with exactly:

```text
claim_unique_number | amount_paid | lifeline_bank_account
```

The Lifeline bank account is the ERPNext Bank/Cash account where the payer
transferred money into Lifeline. Processing creates standard **Payment Entry
Receive** records and updates the claim payer paid/outstanding fields.

For money paid to providers, open **Provider Payment Settlement** and upload a
`.xlsx` or `.csv` file with exactly:

```text
claim_unique_number | amount_paid | lifeline_bank_account | payment_reference
```

The Lifeline bank account is the ERPNext Bank/Cash account where Lifeline money
is debited from. You may select one Provider on the settlement form to restrict
the upload to that provider; if Provider is left blank, the file may contain
multiple providers. Processing groups rows by provider, bank account, and
payment reference, creates standard **Payment Entry Pay** records, and updates
the claim provider paid/outstanding fields.

## Removing approved claims

Open **Lifeline TPA → Claim Removal Batch**:

1. Create a new removal batch.
2. Use **Actions → Download Upload Template**.
3. Enter the claim's `Unique Transaction ID`, removal reason, approval
   reference, and removal date.
4. Attach the completed `.xlsx` or `.csv` file.
5. Run **Validate Removal File**, review the claim rows, and submit the batch.
6. Run **Process Claim Removals**.

Unprocessed claims are marked Removed without accounting entries. Processed
claims create submitted Purchase Debit Notes and matching Sales Credit Notes.
Claims with settlement activity are rejected. Original claims and invoices are
never deleted.
