# Implementation Roadmap

## Phase 0 — Development foundation

- Install WSL and Frappe/ERPNext v15 bench.
- Install this app by soft link.
- Enable developer mode.
- Configure Git and pre-commit.
- Create development and UAT sites.

Exit condition: the app installs and appears in ERPNext without migration errors.

## Phase 1 — Masters and PO validation

- Lifeline TPA Settings
- Provider Facility Mapping
- Claims PO Batch
- Claim Record
- Exact `Master Sheet` header validation
- File hash and duplicate protection
- Validation preview and error report
- Import of claim records without accounting

Exit condition: the sample imports as 3,516 claims, 340 providers and
AED 401,060.87.

## Phase 2 — Accounting prototype and bulk processing

- Confirm clearing-account behaviour on ERPNext v15.
- Create Purchase Invoice per provider.
- Create matching Sales Invoice per provider/payer group.
- Assign Process Payable and Sales Invoice numbers to claims.
- Add background processing, progress, retries and reconciliation.
- Add processed PO export.

Exit condition: submitted invoices reconcile and batch clearing difference is zero.

Status: complete, including the processed PO Excel export.

## Phase 3 — Payer settlement

- Claim-wise settlement import.
- Partial allocations.
- Payment Entry generation.
- Duplicate file/reference controls.
- Payer outstanding and reconciliation reports.

Status: claim-level payer receipt upload is implemented with a simple
three-column file and standard Payment Entry Receive posting.

## Phase 4 — Provider settlement

- Process Payable selection.
- Cheque/transfer tracking.
- Supplier Payment Entry generation.
- Partial payment allocation.
- Provider outstanding and hold reports.

Status: claim-level provider payment upload is implemented with a simple
four-column file, optional provider selection, and standard Payment Entry Pay
posting grouped by provider, bank account, and payment reference.

## Phase 5 — Adjustments and controls

- Settlement Hold.
- Claim Adjustment workflow.
- Purchase Debit Notes and Sales Credit Notes.
- Maker/checker permissions.
- Cancellation and amendment handling.

## Phase 6 — UAT and go-live

- Volume and concurrency testing.
- Opening-balance/historical migration design.
- Finance reconciliation.
- User training.
- Production deployment and monitored parallel run.
