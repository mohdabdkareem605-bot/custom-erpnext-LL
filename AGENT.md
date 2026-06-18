# Lifeline TPA ERPNext

- App: `lifeline_tpa`
- Stack: Frappe/ERPNext v15
- Goal: import medical PO files and post payer/provider accounting in ERPNext

## Core context

- Upload source is the exact `Master Sheet` template.
- `Unique Transaction ID` is the claim reference.
- `POID/Year` is the external PO number.
- `Provider reference No` maps to ERPNext Supplier.
- `Payer Share CV` is the posting amount.

## Current design

- Bulk process creates provider-group purchase invoices and matching sales invoices.
- Payer settlement supports claim-wise upload and PO/process-payable allocation.
- Provider settlement is posted when bank payment is released.
- Claim removals use accounting returns, not direct deletion.

## Status

- Repo scaffold is ready.
- WSL/bench setup is pending.
- See `context.md` for dated implementation notes.
