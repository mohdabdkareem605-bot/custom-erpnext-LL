# Lifeline TPA ERPNext Accounting Custom App

## Project

- App/package name: `lifeline_tpa`
- Target: Frappe and ERPNext version 15
- Repository root: this directory
- ERPNext is the accounting system; the external medical system remains the
  source for claim adjudication and PO generation.

## Approved core process

- Import the exact 34-column `Master Sheet` from the medical PO workbook.
- User selects the single payer before validation.
- `Unique Transaction ID` is the Claim Reference.
- `POID/Year` is the external PO reference.
- `Provider reference No` maps the claim to an ERPNext Supplier.
- `Payer Share CV` is the initial accounting amount.
- Bulk processing creates one Purchase Invoice (Process Payable) per provider
  group and one matching Sales Invoice for the payer/provider group.
- Claim-level payer settlement supports claim-wise and PO/process-payable modes.
- Provider settlement uses Supplier Payment Entries.
- Missing bank details create a settlement hold, not an accounting reversal.
- Claim withdrawal creates paired Purchase Debit Note and Sales Credit Note.

## Development status — 2026-06-18

- Workspace audited: Git is present; WSL, Docker and Bench are absent.
- Repository scaffolded as a Frappe v15 custom app.
- Added development requirements, WSL setup instructions and roadmap.
- Added initial DocTypes: Lifeline TPA Settings, Provider Facility Mapping,
  Claims PO Batch and Claim Record.
- Added the exact PO header schema and initial unit tests.
- Next prerequisite: install WSL 2/Ubuntu, then create the bench and install app.

## Working rules

- Keep accounting logic in Python services.
- Use standard ERPNext invoices, returns and Payment Entries.
- Never write GL Entry rows directly.
- Make imports and background processing idempotent.
- Update this file briefly whenever a process decision or development milestone
  is completed.
