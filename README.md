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

The app repository and initial data-model scaffold are created. A runnable
ERPNext site still requires WSL 2 and the Frappe development dependencies.

