# Context

## 2026-06-18

- Reviewed the sample PO workbook and confirmed `Master Sheet` is the upload source.
- Finalized the first-pass design for import, bulk processing, payer settlement, and provider settlement.
- Chose a custom Frappe/ERPNext v15 app named `lifeline_tpa`.
- Scaffolded the app with `Lifeline TPA Settings`, `Provider Facility Mapping`, `Claims PO Batch`, and `Claim Record`.
- Added exact PO header schema validation.
- Added setup and roadmap docs for the Windows to WSL development flow.
- Initialized git and pushed the initial scaffold to GitHub.
- Set up the native macOS development environment with isolated Python 3.11,
  Node.js 20, Yarn, MariaDB, Redis, Bench, and PDF generation support.
- Created `~/frappe-bench` with Frappe and ERPNext 15.112.0, linked this
  repository as the `lifeline_tpa` app, and created `lifeline.localhost`.
- Installed and migrated `lifeline_tpa` 0.1.0. Verified its four DocTypes and
  three Lifeline TPA roles were created.
- Enabled the scheduler and verified one worker is online. Browser checks
  confirmed the login and setup wizard load without console errors.
- The two PO schema unit tests pass and the repository remains clean.
- ERPNext initial setup is now complete enough to reach the Accounting
  workspace. Continue with the Phase 1 workbook parser, validation preview,
  duplicate protection, and claim import.

## 2026-06-19

- Implemented the Phase 1 PO import flow: `.xlsx` parsing from `Master Sheet`,
  exact schema and required-value checks, file hashing, duplicate claim/file
  detection, single-PO and single-currency enforcement, provider mapping
  validation, and preview totals/errors.
- Added `Validate PO File` and `Import Claims` actions to `Claims PO Batch`.
  Successful imports create read-only `Claim Record` entries, preserve each
  original row as restricted source JSON, initialize payer/provider outstanding
  amounts, and move the batch to `Imported`.
- Confirmed the sample workbook contains 3,516 unique claims across 340 facility
  IDs for `DNIRC-000150/2026`, totaling AED 401,060.87.
- Migrated the changes to `lifeline.localhost`; eight unit and ERPNext
  integration tests pass, and the Claims PO Batch list and new form load in the
  browser without application errors.
- The full 340-provider sample remains blocked on complete business master
  data. The agreed approach is to prove the workflow with five providers first,
  then expand the masters only after the pilot is accepted.
- Added a public `Lifeline TPA` ERPNext workspace with shortcuts to Claims PO
  Batch, Claim Record, Provider Facility Mapping, and Lifeline TPA Settings.
- Added an idempotent five-provider pilot setup routine in
  `lifeline_tpa.setup.pilot`. It selects the five highest-volume facilities,
  creates the required payer/provider masters and mappings, filters the source
  workbook, validates it, and imports the claims.
- Created payer `DNIRC`, five Healthcare Provider Suppliers, and five facility
  mappings on `lifeline.localhost`. Imported batch `CPO-2026-00001` for PO
  `DNIRC-000150/2026`: 708 claims, five providers, AED 38,104.57.
- Read-back verification matched the batch and database claim counts and
  amounts exactly. A second pilot run returned the existing batch without
  creating duplicate records.
- Seven parser/import unit tests pass. The Frappe site test runner remains
  blocked before test execution by an `ImplicitCommitError` in the local test
  environment. Continue with pilot review in the UI, then implement the
  provider-group Purchase Invoice and matching Sales Invoice preview workflow.
- Completed the Phase 2 accounting-preview foundation. Created
  `Claims Clearing Control - LL`, the non-stock `MEDICAL-CLAIM` item, and
  configured `Lifeline TPA Settings` with the company receivable/payable
  accounts and `Main - LL` cost center.
- Added **Actions → Preview Bulk Processing** for submitted, imported Claims PO
  Batches. It groups active claims by provider, builds and validates matching
  Purchase/Sales Invoice documents in memory, and displays provider totals
  without saving or posting accounting documents.
- Repaired the missing standard ERPNext `Contact-is_billing_contact` custom
  field discovered by live invoice validation.
- Verified `CPO-2026-00001` previews five Purchase Invoices and five matching
  Sales Invoices covering 708 claims. Both sides total AED 38,104.57 and the
  clearing difference is AED 0.00. Ten unit tests pass, the rendered preview
  dialog works without console errors, and no invoices or GL entries were
  created.
- The preview table's current **Purchase Invoice** and **Sales Invoice** columns
  display proposed invoice totals, not invoice numbers; rename them to
  **Purchase Invoice Total** and **Sales Invoice Total** in the next UI change.
  Actual invoice numbers will exist only after ERPNext saves the documents.
- Implemented **Actions → Run Bulk Processing** as a confirmed background job.
  It processes each provider group in its own transaction, submits one Purchase
  Invoice and one matching Sales Invoice, links every Claim Record to both
  documents, records provider-level progress and failures, and safely skips
  completed groups when a failed batch is retried.
- Added final General Ledger reconciliation for the batch clearing account.
  The batch is marked Processed only when all active claims have both invoice
  links and the clearing difference is zero. Added Processed By, Processed
  Date, and Processing Log fields to the batch.
- Migrated the local site and reverified the 708-claim pilot preview: five
  provider groups, AED 38,104.57 on both sides, and AED 0.00 difference.
  Browser QA confirmed the Run action and warning confirmation with no console
  errors. The confirmation was dismissed, so the pilot remains Imported with
  zero Purchase Invoices, Sales Invoices, and GL Entries.
- Added **Claim Removal Batch** with an `.xlsx`/`.csv` upload workflow using
  `Unique Transaction ID`, Removal Reason, Approval Reference, and Removal
  Date. Validation rejects missing, duplicate, already removed, settled, or
  incorrectly linked claims before any accounting action.
- Unprocessed claims are marked Removed without accounting entries. Processed
  claims are grouped by their original Purchase/Sales invoice pair and reversed
  using submitted Purchase Debit Notes and Sales Credit Notes. Every removal
  keeps the original claim and invoice history and records the approval details.
- Updated future bulk processing to create one invoice item per claim, allowing
  exact claim-level returns. Added a controlled legacy partial-return path for
  batches already processed with one aggregated invoice item per provider.
- Added a formatted removal upload template and a download action in ERPNext.
  Added the Claim Removal Batch shortcut to the Lifeline TPA workspace.
- Unit and ERPNext integration tests cover file validation, unprocessed removal,
  claim-level accounting reversal, legacy aggregated reversal, and future bulk
  claim-item links. Browser QA confirmed the workspace and new form. No live
  claim was removed; the site still has zero removal batches and zero return
  invoices.
- During final verification, pilot `CPO-2026-00001` was already Processed with
  five Purchase Invoices, five Sales Invoices, and a zero clearing difference.
  Those documents were preserved unchanged.

## 2026-06-21

- Set `Disable Rounded Total` on all future app-generated Purchase Invoices,
  Sales Invoices, Purchase Debit Notes, and Sales Credit Notes so claim amounts
  are posted using their exact fils instead of being rounded to whole dirhams.
- Accounting integration tests verify exact invoice and outstanding amounts
  with zero rounding adjustment; all four relevant integration tests pass.
- Existing submitted pilot invoices and removal notes remain unchanged because
  ERPNext does not allow their accounting totals to be edited after submission.
  Correcting those records would require a separately approved cancellation,
  amendment, or accounting adjustment.

## 2026-06-22

- Completed the remaining Phase 2 Processed PO Export.
- Added **Actions → Download Processed PO** for submitted batches in Processed,
  Partially Settled, or Fully Settled status.
- The generated workbook keeps all original 34 `Master Sheet` columns and
  appends payer, Process Payable, Sales Invoice, payer/provider payment amounts,
  references, dates, and settlement statuses.
- The export includes all batch claims for audit history, preserves original
  source-row order, checks the exported claim count against the batch total, and
  rejects missing or damaged source JSON.
- Verified the 708-claim pilot action in the browser. The download started
  successfully and the page produced no console warnings or errors.
- Added **Payer Receipt Settlement** for money received from payers. It accepts
  `.xlsx`/`.csv` files with exactly `claim_unique_number`, `amount_paid`, and
  `lifeline_bank_account`; validates claims, payer, PO batch, active status,
  Sales Invoice links, outstanding amount, and Bank/Cash account; then creates
  standard ERPNext Payment Entry Receive records and updates payer claim
  settlement fields.
- Added **Provider Payment Settlement** for money paid to providers. It accepts
  `.xlsx`/`.csv` files with exactly `claim_unique_number`, `amount_paid`,
  `lifeline_bank_account`, and `payment_reference`; validates Purchase Invoice
  / Process Payable links, optional selected-provider matching, and duplicate
  claim/reference use; then groups by provider, Lifeline bank account, and
  payment reference before creating standard ERPNext Payment Entry Pay records
  and updating provider settlement fields.
- Settlement upload preview rows intentionally store the bank account as text
  so invalid uploaded account names can be shown with validation errors instead
  of failing link validation.
- Verification: 17 service tests pass, compile and JS syntax checks pass,
  `git diff --check` passes, the Claims PO Batch ERPNext integration test
  passes, and the new settlement ERPNext integration module passes three tests
  covering payer receipt posting, provider grouped payment posting, and
  validation errors.
- Hardened provider settlement with an optional selected Provider field on
  `Provider Payment Settlement`. If set, uploaded claim rows must belong to that
  Supplier; if left blank, the existing multi-provider grouped upload remains
  supported.
- Provider settlement integration coverage now verifies grouped partial
  provider payments, full provider claim payment to `Paid`, selected-provider
  acceptance/rejection, Supplier Payment Entry allocation against Purchase
  Invoices, and that provider payment updates do not alter payer settlement
  fields.
- Continue with browser QA for the two new settlement forms, then add
  settlement reports/ageing views if Finance accepts the upload workflow.
