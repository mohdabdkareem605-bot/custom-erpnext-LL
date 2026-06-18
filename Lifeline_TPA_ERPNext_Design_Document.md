# ERPNext Implementation Design Document
## Lifeline TPA — Accounting System

| | |
|---|---|
| **Organisation** | Lifeline TPA (Khat Al Haya Management of Health Insurance Claims L.L.C.) |
| **Document Type** | System Design Document |
| **Version** | 1.1 |
| **Date** | June 2026 |
| **Status** | Draft — For Team Discussion |
| **Prepared By** | Finance Team |
| **Changes in v1.1** | Added Remittance Advice (RA) process; expanded Data Migration to cover 2-year historical claim migration |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Scope](#2-scope)
3. [System Architecture](#3-system-architecture)
4. [ERPNext Module Usage](#4-erpnext-module-usage)
5. [Chart of Accounts Design](#5-chart-of-accounts-design)
6. [Master Data Design](#6-master-data-design)
7. [Custom DocType: Claims Batch](#7-custom-doctype-claims-batch)
8. [Process 1 — Bulk Claims Processing](#8-process-1--bulk-claims-processing)
9. [Process 2 — Claim Removal](#9-process-2--claim-removal)
10. [Process 3 — Settlement](#10-process-3--settlement)
11. [Process 4 — Remittance Advice (RA)](#11-process-4--remittance-advice-ra) ← NEW
12. [Process 5 — TPA Revenue & Deferred Revenue](#12-process-5--tpa-revenue--deferred-revenue)
13. [Custom Development Specification](#13-custom-development-specification)
14. [Data Migration — 2-Year Historical Claims](#14-data-migration--2-year-historical-claims) ← UPDATED
15. [Roles & Permissions](#15-roles--permissions)
16. [Implementation Phases](#16-implementation-phases)
17. [Risks & Mitigations](#17-risks--mitigations)
18. [Open Questions for Team Discussion](#18-open-questions-for-team-discussion)

---

## 1. Executive Summary

Lifeline TPA requires a structured accounting system to manage the financial side of its Third Party Administrator (TPA) operations. The current system (JBM) has limitations in handling bulk claims processing, automated settlement reconciliation, and deferred revenue management at scale.

**Proposed solution:** Implement **ERPNext** (Frappe Framework) as the primary accounting platform for Lifeline TPA.

ERPNext will handle:
- General Ledger and Chart of Accounts
- Accounts Payable (Providers)
- Accounts Receivable (Payers)
- Bulk claims processing with automated journal entry generation
- Payment reconciliation and settlement
- Deferred TPA revenue recognition across lakhs of policies
- Financial statements (P&L, Balance Sheet, Cash Flow)
- UAE VAT compliance

ERPNext will **not** replace the medical/claims system. It receives the output of claims decisions and handles accounting from the point of approval onwards.

---

## 2. Scope

### In Scope

- Chart of Accounts setup for TPA operations
- All 7 payer (debtor) ledgers
- All provider (creditor) ledgers
- Claims Batch — custom document to manage bulk claim uploads
- Bulk processing — auto-generate Process Payables (Purchase Invoices per provider)
- Payer (Sales Invoice) generation on bulk processing
- Claim removal via Debit/Credit Notes
- Provider settlement — pay to bank
- Payer settlement — receive from bank
- Bulk settlement upload (custom feature)
- Endorsement report upload → Deferred Revenue posting
- Monthly deferred revenue recognition (scheduler)
- UAE VAT on TPA fees
- Financial reporting — P&L, Balance Sheet, Ageing, Ledger Statements

### Out of Scope

- Claims adjudication (approve/reject decisions) — remains in medical system
- Policy administration — remains in existing systems
- HR/Payroll — separate consideration
- Inventory management — not applicable
- E-commerce / CRM — not applicable

---

## 3. System Architecture

### 3.1 Two-System Design

```
┌──────────────────────────────────────┐
│        Medical / Claims System       │
│           (External System)          │
│                                      │
│  ● Claims adjudication               │
│  ● Claims approval / rejection       │
│  ● Purchase Order (PO) creation      │
│  ● PO reference stamping on claims   │
│  ● Exports: Claims Data File         │
│  ● Exports: Endorsement Report       │
└──────────────┬───────────────────────┘
               │
               │  CSV / Excel Files
               │  (Manual upload by Finance Team)
               ▼
┌──────────────────────────────────────┐
│         ERPNext (Frappe)             │
│         Accounting System            │
│                                      │
│  ● General Ledger                    │
│  ● Accounts Payable (Providers)      │
│  ● Accounts Receivable (Payers)      │
│  ● Claims Batch (Custom DocType)     │
│  ● Bulk Processing (Custom Script)   │
│  ● Payment Reconciliation            │
│  ● Deferred Revenue (Scheduler)      │
│  ● Financial Statements              │
│  ● UAE VAT Reports                   │
└──────────────────────────────────────┘
```

### 3.2 Integration Method

There is **no real-time API integration** between the medical system and ERPNext in Phase 1. Data flows via file-based upload:

| Data | Source | Destination | Method | Frequency |
|---|---|---|---|---|
| Claims data | Medical system | ERPNext Claims Batch | CSV upload | Per batch (daily/weekly) |
| Endorsement report | Medical system | ERPNext Sales Invoice | CSV import | Per endorsement cycle |
| Bank transfer confirmation | Bank / Finance team | ERPNext Payment Entry | CSV upload | Per settlement run |

> **Decision point for team:** Should Phase 2 include an API integration between the medical system and ERPNext to automate file transfer? Or is manual upload acceptable long-term?

### 3.3 PO Reference Handling

The Purchase Order (PO) is created in the **medical system**. ERPNext does not hold a PO document. The PO reference number is stored as a **plain text field** on ERPNext documents for traceability:

```
Medical System PO: PO-2025-001
    ↓ (stored as text on)
ERPNext Claims Batch → External PO Ref: PO-2025-001
ERPNext Purchase Invoice → External PO Ref: PO-2025-001
ERPNext Sales Invoice → External PO Ref: PO-2025-001
ERPNext Payment Entry → External PO Ref: PO-2025-001
```

This means any auditor can search `External PO Ref = PO-2025-001` across all ERPNext documents to get a complete picture of that batch.

---

## 4. ERPNext Module Usage

| ERPNext Module | Used For | Standard or Custom |
|---|---|---|
| Accounting → Chart of Accounts | GL structure | Standard |
| Accounting → Sales Invoice | Payer (debtor) invoicing | Standard + custom fields |
| Accounting → Purchase Invoice | Provider (creditor) Process Payable | Standard + custom fields |
| Accounting → Payment Entry | Settlement receipts and payments | Standard + custom fields |
| Accounting → Payment Reconciliation | Matching payments to invoices | Standard |
| Accounting → Process Deferred Revenue | Monthly revenue recognition | Standard |
| Accounting → Journal Entry | Manual adjustments | Standard |
| Accounting → Financial Reports | P&L, Balance Sheet, Ageing | Standard |
| Data Import Tool | Bulk CSV/Excel upload | Standard |
| Claims Batch | Batch management and processing trigger | **Custom DocType** |
| Bulk Settlement Upload | Bank file upload → auto-reconcile | **Custom Page** |

---

## 5. Chart of Accounts Design

### 5.1 Full Structure

```
ASSETS
├── Current Assets
│   ├── Cash & Bank
│   │   └── Lifeline TPA — Main Bank (AED)
│   │   └── Lifeline TPA — USD Account (if needed)
│   └── Accounts Receivable
│       ├── Claims Receivable Control A/C    ← CONTROL ACCOUNT
│       ├── Al Sagr — Receivable
│       ├── Dubai Insurance (DIC) — Receivable
│       ├── Alliance Insurance — Receivable
│       ├── National General Insurance (NGI) — Receivable
│       ├── Dubai National Insurance (DNI) — Receivable
│       ├── Sukoon Insurance — Receivable
│       └── Al Buhaira Insurance — Receivable
└── Non-Current Assets
    └── [as required]

LIABILITIES
├── Current Liabilities
│   ├── Accounts Payable
│   │   ├── Claims Payable Control A/C       ← CONTROL ACCOUNT
│   │   ├── Mediclinic — Payable
│   │   ├── NMC — Payable
│   │   ├── Aster — Payable
│   │   └── [all other providers...]
│   └── Deferred Revenue
│       └── Deferred TPA Revenue A/C
└── Non-Current Liabilities
    └── [as required]

EQUITY
└── [as required]

INCOME
├── TPA Revenue A/C
└── Other Income (if needed)

EXPENSES
└── [as required]
```

### 5.2 Control Accounts — Purpose & Behaviour

| Account | Type | Purpose |
|---|---|---|
| Claims Receivable Control A/C | Receivable | Credited on payer SINV; bridges payer and provider entries |
| Claims Payable Control A/C | Payable | Debited on provider PINV; bridges provider and payer entries |

**Both control accounts must net to zero after every bulk processing run.** If they don't, it means claims on one side were posted without a corresponding entry on the other side.

### 5.3 Account Type Settings (Critical)

ERPNext uses Account Type to drive AR/AP functionality:

| Account | ERPNext Account Type | Why |
|---|---|---|
| All Payer accounts | Receivable | Enables outstanding invoice tracking, ageing, ledger statements |
| All Provider accounts | Payable | Enables outstanding payable tracking, ageing, payment matching |
| Deferred TPA Revenue | Current Liability | Enables deferred revenue scheduler to process it |
| TPA Revenue | Income | Revenue recognition target |

---

## 6. Master Data Design

### 6.1 Payers → Customers

| Customer Name | Customer Group | Default Receivable A/C | VAT Reg No |
|---|---|---|---|
| Al Sagr Insurance (PSC) | Insurance Payers | Al Sagr — Receivable | [to be filled] |
| Dubai Insurance Company (DIC) | Insurance Payers | DIC — Receivable | [to be filled] |
| Alliance Insurance | Insurance Payers | Alliance — Receivable | [to be filled] |
| National General Insurance | Insurance Payers | NGI — Receivable | [to be filled] |
| Dubai National Insurance | Insurance Payers | DNI — Receivable | [to be filled] |
| Sukoon Insurance | Insurance Payers | Sukoon — Receivable | [to be filled] |
| Al Buhaira Insurance | Insurance Payers | Al Buhaira — Receivable | [to be filled] |

### 6.2 Providers → Suppliers

Each healthcare provider to be set up as a Supplier with:
- Supplier Name
- Supplier Group: Healthcare Providers
- Default Payable Account: [Provider] — Payable
- VAT Registration Number
- Bank account details (for payment processing)

> **Action item:** Finance team to provide complete list of all active providers with their bank details.

### 6.3 Item Master

| Item Code | Item Name | Item Group | Income Account | Is Stock Item |
|---|---|---|---|---|
| MEDICAL-CLAIM | Medical Claim | Insurance Claims | TPA Revenue A/C | No |
| TPA-FEE | TPA Fee | TPA Revenue | TPA Revenue A/C | No |

---

## 7. Custom DocType: Claims Batch

The Claims Batch is a new document type built specifically for Lifeline TPA. It is the **central document** for bulk claims processing.

### 7.1 Parent Document Fields

| Field Label | Field Type | Required | Description |
|---|---|---|---|
| Batch ID | Auto (naming series) | Auto | CB-YYYY-NNNN |
| External PO Ref | Data | Yes | PO number from medical system |
| Payer | Link → Customer | Yes | Insurance payer for this batch |
| Upload Date | Date | Yes | Date claims file received |
| Claim Period From | Date | No | Service date range start |
| Claim Period To | Date | No | Service date range end |
| Status | Select | Auto | Draft / Uploaded / Processed / Settled |
| Total Claims | Int | Auto | Count of rows in child table |
| Total Amount (AED) | Currency | Auto | Sum of all claim amounts |
| Processed By | Link → User | Auto | Set on bulk processing run |
| Processed Date | Date | Auto | Set on bulk processing run |
| Process Payables Created | Text | Auto | List of PINV numbers generated |
| Sales Invoices Created | Text | Auto | List of SINV numbers generated |
| Notes | Small Text | No | Remarks |

### 7.2 Child Table: Claims Batch Item

| Field Label | Field Type | Required | Description |
|---|---|---|---|
| Claim No | Data | Yes | Unique claim ID from medical system |
| Provider | Link → Supplier | Yes | Healthcare provider |
| Payer | Link → Customer | Yes | Insurance company |
| Amount (AED) | Currency | Yes | Claim amount |
| Service Date | Date | Yes | Date service was rendered |
| Member ID | Data | No | Patient/member identifier |
| Diagnosis Code | Data | No | ICD code |
| Policy No | Data | No | Insurance policy number |
| External PO Ref | Data | Auto | Inherited from parent |
| Status | Select | Auto | Pending / Processed / Removed |
| Process Payable No | Data | Auto | PINV number after processing |

### 7.3 Workflow States

```
DRAFT
  ↓  Finance team creates Claims Batch, uploads claims via Data Import
UPLOADED
  ↓  Finance team clicks "Run Bulk Processing"
PROCESSED
  ↓  Payer remits + all providers paid
SETTLED
```

### 7.4 Custom Buttons on Claims Batch Form

| Button | Trigger | Action |
|---|---|---|
| Run Bulk Processing | Manual click | Groups claims, creates PINV per provider + SINV per payer |
| View Process Payables | Manual click | Opens list of all PINVs for this batch |
| View Sales Invoices | Manual click | Opens list of all SINVs for this batch |
| Mark as Settled | Manual click | Updates status after all payments confirmed |

---

## 8. Process 1 — Bulk Claims Processing

### 8.1 Process Flow

```
Finance team receives claims data file from medical team
                    ↓
        Create new Claims Batch document
        (enter External PO Ref, Payer, dates)
                    ↓
        Upload claims CSV via Data Import Tool
        (1,000 or 2,000 rows → child table)
                    ↓
        Review: check total count and total amount
                    ↓
        Click: "Run Bulk Processing"
                    ↓
        System groups claims by Provider
                    ↓
        Creates Purchase Invoice per Provider
        (= Process Payable, unique PINV number)
                    ↓
        Creates Sales Invoice per Payer
                    ↓
        GL entries posted automatically
                    ↓
        Claims Batch status → "Processed"
        PINV and SINV numbers recorded on Batch
```

### 8.2 Grouping Logic

```
Claims Batch CB-2025-001 (1,000 claims)
│
├── Group by Provider:
│     Mediclinic  → 400 claims → PINV-LT-2025-0001
│     NMC         → 350 claims → PINV-LT-2025-0002
│     Aster       → 250 claims → PINV-LT-2025-0003
│
└── Group by Payer:
      Al Sagr  → 560 claims (mixed providers) → SINV-LT-2025-0001
      DIC      → 440 claims (mixed providers) → SINV-LT-2025-0002
```

> **Decision point:** Should one SINV be created per payer, or per payer-per-provider combination? Current design: one SINV per payer (simpler reconciliation). Team to confirm.

### 8.3 Accounting Entries Generated

**Purchase Invoices — Provider side:**

```
Claims Payable Control A/C       Dr    293,000
    To Mediclinic — Payable           Cr    120,000    ← PINV-LT-2025-0001
    To NMC — Payable                  Cr     98,000    ← PINV-LT-2025-0002
    To Aster — Payable                Cr     75,000    ← PINV-LT-2025-0003
```

**Sales Invoices — Payer side:**

```
Al Sagr — Receivable             Dr    150,000         ← SINV-LT-2025-0001
DIC — Receivable                 Dr    143,000         ← SINV-LT-2025-0002
    To Claims Receivable Control      Cr    293,000
```

**Control Account Validation (auto-check):**

```
Claims Payable Control  Dr  293,000  ─┐
Claims Receivable Control Cr 293,000  ─┘  Net = 0 ✅
```

If this check fails, the system must halt and alert the user.

### 8.4 Process Payable Numbering

Current proposal: `PINV-LT-YYYY-NNNN`

> **Decision point:** What naming format does the finance team require for Process Payables and Sales Invoices? Does it need to match any existing format used in current system?

### 8.5 Data Validation Before Processing

The system must validate before running:

| Check | Rule |
|---|---|
| Status | Batch must be in "Uploaded" status |
| Minimum rows | Must have at least 1 claim row |
| Provider | All claim rows must have a valid provider (linked Supplier) |
| Payer | All claim rows must have a valid payer (linked Customer) |
| Amount | All amounts must be > 0 |
| Duplicate claims | Warn if any Claim No already exists in another processed batch |

---

## 9. Process 2 — Claim Removal

When approved claims are subsequently removed from a processed batch (e.g. duplicates found, rejection after processing, incorrect amounts).

### 9.1 Accounting Entry

```
Provider A/C (e.g. Mediclinic — Payable)    Dr    [claim amount]
    To Payer A/C (e.g. Al Sagr — Receivable)    Cr    [claim amount]
```

### 9.2 ERPNext Documents Used

| Side | Document | Type |
|---|---|---|
| Provider (reversal) | Purchase Debit Note | Return against original PINV |
| Payer (reversal) | Sales Credit Note | Return against original SINV |

Both documents carry:
- Reference to original PINV / SINV
- Claim numbers being removed
- External PO Ref
- Claims Batch number

### 9.3 Questions for Team

> **Q1:** Who has authority to initiate a claim removal — only finance manager, or any finance user?

> **Q2:** Is there a form/approval from the medical team that must be attached before removal is allowed?

> **Q3:** Should claim removals be tracked on the original Claims Batch document (updating the claim row status to "Removed")?

---

## 10. Process 3 — Settlement

### 10.1 Money Received from Payer

**Trigger:** Insurance company remits payment to Lifeline TPA's bank account.

**Accounting Entry:**
```
Bank A/C                         Dr    [amount received]
    To Payer A/C                     Cr    [amount received]
```

**ERPNext Document:** Payment Entry (Type: Receive)

**Reconciliation:** Finance team uses Payment Reconciliation Tool to match the receipt against outstanding Sales Invoices for that payer. Payer ledger clears to zero.

### 10.2 Money Paid to Provider

**Trigger:** Lifeline TPA transfers payment to healthcare provider.

**Accounting Entry:**
```
Provider A/C                     Dr    [amount paid]
    To Bank A/C                      Cr    [amount paid]
```

**ERPNext Document:** Payment Entry (Type: Pay)

**Reconciliation:** Payment matched against outstanding Purchase Invoices for that provider. Provider ledger clears to zero.

### 10.3 Bulk Settlement Upload (Custom Feature)

For settlement runs where many providers are paid in one bank transfer file.

**Flow:**
```
Finance team downloads bank transfer confirmation file
                    ↓
Go to: Lifeline TPA → Bulk Settlement Upload
                    ↓
Upload CSV file
Columns: Provider Name | Transfer Ref | Amount | Value Date
                    ↓
System matches each row to open Purchase Invoices
(matched by: Provider + Amount)
                    ↓
Creates Payment Entries in bulk for all matched rows
                    ↓
Submits all Payment Entries
                    ↓
Exceptions report: any unmatched rows flagged for manual review
                    ↓
All matched provider ledgers clear to zero
```

### 10.4 Bulk Settlement Upload — CSV Format

```
provider_name    | transfer_ref  | amount    | value_date
Mediclinic       | TT-2025-11001 | 120000.00 | 2025-11-20
NMC              | TT-2025-11002 |  98000.00 | 2025-11-20
Aster            | TT-2025-11003 |  75000.00 | 2025-11-20
```

> **Decision point:** Will the bank provide a structured export file? Or will the finance team manually prepare this CSV? What is the exact column format available from the bank?

---

## 11. Process 4 — Remittance Advice (RA)

### 11.1 What is a Remittance Advice?

A Remittance Advice (RA) is a document sent by the payer (insurance company) when they make a payment transfer. It lists exactly **which claims** they are paying against that transfer, the amount paid per claim, any deductions made, and the reason for deductions.

Without an RA, the finance team only knows that money arrived in the bank — they cannot link the payment to specific claims. The RA is what enables claim-level reconciliation.

**RA is triggered by:** Payer sharing transfer/payment details (bank transfer confirmation + RA document).

```
Payer sends:
  ├── Bank Transfer Confirmation (total amount, reference)
  └── Remittance Advice (claim-by-claim breakdown)

Finance team:
  └── Uploads RA into ERPNext → system matches claims → marks as Paid
```

### 11.2 Remittance Advice — Custom DocType

Since ERPNext has no native RA document, a custom DocType **Remittance Advice** is built:

**Parent Document Fields:**

| Field Label | Field Type | Required | Description |
|---|---|---|---|
| RA Number | Auto (RA-YYYY-NNNN) | Auto | ERPNext-generated RA ID |
| Payer | Link → Customer | Yes | Insurance company sending the payment |
| Transfer Reference | Data | Yes | Bank transfer / TT reference number |
| Transfer Date | Date | Yes | Date funds transferred by payer |
| Total Transfer Amount | Currency (AED) | Yes | Total amount remitted |
| Bank Account | Link → Bank Account | Yes | Lifeline TPA bank account credited |
| RA Document | Attach | No | Uploaded RA file (PDF / Excel from payer) |
| Status | Select | Auto | Draft / Uploaded / Reconciled / Partially Reconciled |
| Total Claims in RA | Int | Auto | Count of claim rows |
| Total Paid Amount | Currency | Auto | Sum of paid amounts in child table |
| Total Deducted Amount | Currency | Auto | Sum of deductions |
| Payment Entry No | Link → Payment Entry | Auto | Created on reconciliation |
| Reconciled By | Link → User | Auto | |
| Reconciled Date | Date | Auto | |

**Child Table: RA Line Items**

| Field Label | Field Type | Required | Description |
|---|---|---|---|
| Claim No | Data | Yes | Claim identifier (must exist in ERPNext) |
| Original Claim Amount | Currency | Yes | Amount originally billed to payer |
| Paid Amount | Currency | Yes | Amount payer is paying for this claim |
| Deduction Amount | Currency | Auto | Original − Paid |
| Deduction Reason | Select | No | Short Payment / Rejected / Duplicate / Pending / Policy Excess |
| Deduction Notes | Data | No | Free text from payer |
| Provider | Link → Supplier | Auto | Pulled from original claim record |
| Claims Batch No | Data | Auto | Original batch this claim belongs to |
| Status | Select | Auto | Paid / Partial / Deducted / Pending |

### 11.3 RA Workflow States

```
DRAFT
  ↓  Finance team creates RA, enters transfer details
UPLOADED
  ↓  Finance team uploads claim lines from RA document
  ↓  System validates each claim number against ERPNext records
RECONCILED  (all claims matched and paid in full)
  or
PARTIALLY RECONCILED  (some claims deducted / short-paid)
```

### 11.4 Process Flow

```
Payer sends transfer + RA document
              ↓
Finance team creates Remittance Advice in ERPNext
  → Enter payer, transfer ref, transfer date, total amount
              ↓
Upload RA claim lines (CSV or manual entry)
  → Each row: Claim No | Paid Amount | Deduction Reason
              ↓
System validates:
  → Does each Claim No exist in ERPNext? ✅ / ❌
  → Is each claim currently outstanding (unpaid)? ✅ / ❌
  → Does sum of paid amounts = total transfer amount? ✅ / ❌
              ↓
Finance team clicks: "Process Remittance Advice"
              ↓
System creates Payment Entry (Bank → Payer A/C)
System reconciles Payment Entry against open Sales Invoices
  → Matched by Claim No on invoice lines
              ↓
Each claim line in RA → Status updated to "Paid"
Each matched Sales Invoice → Status updated to "Paid"
              ↓
RA Status → "Reconciled" (or "Partially Reconciled" if deductions exist)
```

### 11.5 Accounting Entries Generated

**Payment Entry (always created on RA processing):**
```
Bank A/C                         Dr    [Total Transfer Amount]
    To Payer A/C (Al Sagr, etc.)     Cr    [Total Transfer Amount]
```

**For deducted/short-paid claims:** The difference between the original claim amount and the paid amount remains as an outstanding balance on the payer's ledger. The finance team then decides:

| Scenario | Action in ERPNext |
|---|---|
| Claim re-submitted to payer | Claim remains open — awaiting next RA |
| Claim written off (irrecoverable) | Journal Entry: Write-off A/C Dr / Payer A/C Cr |
| Payer will pay in next cycle | Claim remains open outstanding |
| Dispute raised | Claim flagged as "Disputed" on RA line — no write-off yet |

### 11.6 Handling Resubmissions via RA

When a claim was previously processed, partially paid or deducted, and then **resubmitted** to the payer:

```
Original claim: CLM-0001 (AED 500) → Payer deducted → AED 200 outstanding
        ↓
Medical team resubmits CLM-0001 to payer
        ↓
Payer pays AED 200 on next RA
        ↓
Finance team uploads new RA → references CLM-0001
        ↓
System finds CLM-0001 in ERPNext (from original batch)
Matches AED 200 payment to outstanding AED 200 on payer ledger
Marks CLM-0001 as fully settled ✅
```

This is why **2-year historical claim data must exist in ERPNext** — so that old claim numbers can be found and matched when resubmission payments arrive.

### 11.7 RA Upload CSV Format

```
claim_no  | original_amount | paid_amount | deduction_reason      | notes
CLM-0001  | 500.00          | 500.00      |                       |
CLM-0002  | 300.00          | 300.00      |                       |
CLM-0003  | 750.00          | 500.00      | Short Payment         | Policy excess deducted
CLM-0004  | 400.00          | 0.00        | Rejected              | Duplicate claim
CLM-0005  | 600.00          | 0.00        | Pending               | Awaiting additional docs
```

### 11.8 Key Validations on RA Processing

| Validation | Rule | Action if Failed |
|---|---|---|
| Claim exists | Claim No must exist in ERPNext | Error — halt, show missing claims |
| Claim is open | Claim must not already be fully paid | Warning — flag for review |
| Total check | Sum of paid amounts must equal transfer amount | Warning — allow override with finance manager approval |
| Payer match | All claims in RA must belong to the same payer | Error — halt |

### 11.9 RA Summary on Payer Ledger

After RA is reconciled, the payer ledger statement shows:

```
Al Sagr — Receivable Ledger
────────────────────────────────────────────────────────────
Date        Document        Debit      Credit     Balance
────────────────────────────────────────────────────────────
01-Nov-25   SINV-0001       150,000               150,000
20-Nov-25   RA-2025-0001               148,750      1,250  ← short-paid claims remain
────────────────────────────────────────────────────────────
Outstanding: AED 1,250 (3 deducted/pending claims)
```

---

## 12. Process 5 — TPA Revenue & Deferred Revenue

### 11.1 Revenue Recognition Principle

TPA fee revenue is recognised on a **time-proportionate (straight-line) basis** over the policy period. The portion of TPA fee relating to the unexpired period at any reporting date is classified as **Deferred Revenue** (liability).

```
Daily Rate  = Total TPA Fee ÷ Total Policy Days
Earned      = Daily Rate × Days elapsed in reporting period
Deferred    = Total TPA Fee − Earned
```

### 11.2 Worked Example — 31 December 2025

| Policy | Start Date | End Date | TPA Fee | Total Days | Days Earned by 31-Dec | Earned | Deferred |
|---|---|---|---|---|---|---|---|
| 1 | 01-Mar-2025 | 01-Mar-2026 | AED 100 | 365 | 306 | AED 83.84 | AED 16.16 |
| 2 | 31-May-2025 | 31-May-2026 | AED 200 | 365 | 215 | AED 117.81 | AED 82.19 |
| 3 | 15-Nov-2025 | 15-Nov-2026 | AED 300 | 365 | 47 | AED 38.63 | AED 261.37 |
| **Total** | | | **AED 600** | | | **AED 240.28** | **AED 359.72** |

### 11.3 Entry on Endorsement Report Upload

When the endorsement report is uploaded, all policies are imported as Sales Invoice line items with ERPNext's built-in **Deferred Revenue** flag enabled.

**Journal Entry (auto-posted on Sales Invoice submission):**
```
Debtor / Payer A/C               Dr    [Full TPA Fee]
    To Deferred TPA Revenue A/C      Cr    [Full TPA Fee]
```

The full TPA fee goes to Deferred Revenue at inception. Revenue is recognised monthly via the scheduler.

**Key fields set on each Sales Invoice line:**

| Field | Value |
|---|---|
| Item | TPA-FEE |
| Amount | Policy TPA Fee |
| Enable Deferred Revenue | ✅ Yes |
| Deferred Revenue Account | Deferred TPA Revenue A/C |
| Service Start Date | Policy Start Date |
| Service End Date | Policy End Date |

### 11.4 Monthly Revenue Recognition

**Path:** Accounting → Tools → Process Deferred Revenue

Finance team runs this once at month-end. ERPNext calculates the earned portion for every active policy and posts one journal entry:

**Monthly Journal Entry:**
```
Deferred TPA Revenue A/C         Dr    [Earned in the month]
    To TPA Revenue A/C               Cr    [Earned in the month]
```

For December 2025 example:
```
Deferred TPA Revenue A/C         Dr    240.28
    To TPA Revenue A/C               Cr    240.28
```

Remaining deferred liability = **AED 359.72** ✅

### 11.5 Handling Scale — Lakhs of Policies

ERPNext's scheduler runs as a **background queue job**:
- Processes all active policies automatically — no manual entry per policy
- Runs overnight for large volumes — finance team does not wait
- Single journal entry per month covers all policies
- **Deferred Revenue Report** shows: balance per payer, monthly schedule, remaining per policy

### 11.6 Endorsement Upload CSV Format

```
customer     | service_start | service_end | tpa_fee | policy_no
Al Sagr      | 2025-03-01    | 2026-03-01  | 100.00  | POL-001
Al Sagr      | 2025-05-31    | 2026-05-31  | 200.00  | POL-002
DIC          | 2025-11-15    | 2026-11-15  | 300.00  | POL-003
```

> **Decision point:** Does the endorsement report need to be split by payer before uploading, or can all payers be in one file? ERPNext can handle all payers in a single import.

---

## 13. Custom Development Specification

### 12.1 Summary of Custom Items

| # | Item | Type | Priority | Effort |
|---|---|---|---|---|
| 1 | Claims Batch DocType | New DocType (Python + JSON) | Critical | 3 days |
| 2 | Claims Batch Item child table | Child Table | Critical | 1 day |
| 3 | Bulk Processing Script | Python API + JS button | Critical | 5 days |
| 4 | Control Account net-zero validation | Python hook | Critical | 1 day |
| 5 | Remittance Advice DocType | New DocType (Python + JSON) | Critical | 3 days |
| 6 | RA Line Items child table | Child Table | Critical | 1 day |
| 7 | RA Processing Script | Python API + JS button | Critical | 5 days |
| 8 | RA claim-number validation | Python hook | Critical | 1 day |
| 9 | Custom fields on PINV/SINV/Payment Entry | Customise Form | High | 1 day |
| 10 | Naming series (PINV-LT, SINV-LT, CB, RA) | Settings | High | 0.5 days |
| 11 | Data Import CSV templates | Template files | High | 1 day |
| 12 | Deferred Revenue import script | Python | High | 2 days |
| 13 | Bulk Settlement Upload page | Custom Page (Python + JS) | High | 10 days |
| 14 | Historical claims migration script | Python data migration | High | 10 days |
| 15 | Claims Batch status report | Report | Medium | 2 days |
| 16 | RA reconciliation report | Report | Medium | 2 days |
| 17 | Provider outstanding ageing report | Custom Report | Medium | 2 days |
| 18 | Payer outstanding ageing report | Custom Report | Medium | 2 days |

**Total estimated effort: 10–12 weeks (one Frappe developer)**

### 12.2 Custom App Structure

All customisations will live in a dedicated Frappe app: `lifeline_tpa`

```
lifeline_tpa/
├── lifeline_tpa/
│   ├── api.py                        ← All whitelisted Python functions
│   ├── hooks.py                      ← Scheduler + event hooks
│   ├── doctype/
│   │   ├── claims_batch/
│   │   │   ├── claims_batch.json     ← Field definitions
│   │   │   ├── claims_batch.py       ← Validation + logic
│   │   │   └── claims_batch.js       ← Custom buttons (client side)
│   │   └── claims_batch_item/
│   │       ├── claims_batch_item.json
│   │       └── claims_batch_item.py
│   ├── page/
│   │   └── bulk_settlement_upload/
│   │       ├── bulk_settlement_upload.js
│   │       └── bulk_settlement_upload.py
│   └── templates/
│       ├── claims_import_template.csv
│       └── endorsement_import_template.csv
└── setup.py
```

### 12.3 Custom Button Technical Approach

Buttons are added via **Client Scripts** (JavaScript) which call **whitelisted Python functions** on the server:

```
User clicks button (browser)
       ↓
JavaScript calls: frappe.call({ method: 'lifeline_tpa.api.bulk_process' })
       ↓
ERPNext server receives the call
       ↓
Python @frappe.whitelist() function executes
       ↓
ERPNext database updated (invoices created, GL posted)
       ↓
Response returned to browser
       ↓
User sees success message, document refreshes
```

This is the **standard Frappe architecture** — not a workaround. It is the same mechanism ERPNext itself uses for all its built-in action buttons.

---

## 14. Data Migration — 2-Year Historical Claims

### 14.1 Why 2-Year Historical Migration is Required

This is **not optional**. Historical claim data must exist in ERPNext for two critical business reasons:

**Reason 1 — Resubmissions:**
When a claim was originally processed in 2024 or 2025, rejected or deducted by the payer, and then **resubmitted**, the payer's eventual payment will reference the original claim number. ERPNext must be able to find that original claim to reconcile the payment correctly. Without historical data, old claim payments cannot be matched — they float as unidentified receipts.

**Reason 2 — Old Claim Payments via RA:**
Payers sometimes settle claims months after original processing. An RA arriving in 2026 may contain claim numbers from batches processed in 2024. ERPNext must hold those claim records to process the RA correctly.

```
Without historical migration:
    RA received with CLM-2024-0045 → ERPNext cannot find it → manual workaround needed

With historical migration:
    RA received with CLM-2024-0045 → ERPNext finds original record → auto-reconciles ✅
```

### 14.2 Scope of Historical Migration

| Data | Period | Volume Estimate | Priority |
|---|---|---|---|
| Claims data (all claims) | Last 2 years | [To be confirmed by team] | Critical |
| Outstanding (unpaid) claims | Last 2 years | [Subset of above] | Critical |
| Partially paid claims | Last 2 years | [Subset of above] | Critical |
| Fully paid/settled claims | Last 2 years | [Subset of above] | High |
| Historical Remittance Advices | Last 2 years | Optional | Low |
| Deferred Revenue — policy level | Active policies only | All active policies | Critical |
| Opening GL balances | As at go-live date | One journal entry | Critical |

### 14.3 Migration Strategy — Two-Layer Approach

Historical migration is done in **two distinct layers**:

```
LAYER 1 — FINANCIAL LAYER (affects current balances)
─────────────────────────────────────────────────────
Outstanding claims (unpaid/partially paid)
  → Imported as OPEN Purchase Invoices (provider side)
  → Imported as OPEN Sales Invoices (payer side)
  → These affect current AR/AP balances
  → These appear in ageing reports
  → These are what future RAs will reconcile against

LAYER 2 — REFERENCE LAYER (for lookup only)
─────────────────────────────────────────────
Fully paid/settled historical claims
  → Imported as CLOSED/PAID documents (or as reference records)
  → Do NOT affect current balances
  → Exist purely so claim numbers can be found when:
      a) Resubmission payment arrives
      b) RA references an old claim number
```

### 14.4 Layer 1 — Outstanding Claims Migration

**Source:** Extract from JBM (or medical system) all claims where:
- Status = Unpaid OR Partially Paid
- Service date within last 2 years

**Target in ERPNext:**

Each outstanding claim → one row in a **Historical Claims Batch** (special batch type flagged as "Historical Import"):

```
Historical Batch: HB-2024-001
External PO Ref: [original PO ref from medical system]
Status: Historical Import
Claims: [all outstanding claims from this PO]
```

After import, bulk processing creates:
- Open Purchase Invoices per provider (outstanding payables)
- Open Sales Invoices per payer (outstanding receivables)

These open invoices then appear correctly in:
- AR Ageing Report
- AP Ageing Report
- Payer ledger statements
- Provider ledger statements

And future RA uploads will reconcile against them.

**For partially paid claims:**
- Import at the **remaining outstanding balance** (not original amount)
- Or import at full original amount with a corresponding historical payment against it

> **Decision point for team:** For partially paid historical claims, should we import (a) just the remaining balance, or (b) the full original amount plus a historical payment record? Option (b) gives more complete history but is more migration work.

### 14.5 Layer 2 — Paid Historical Claims Migration (Reference Records)

**Source:** All claims settled/paid in last 2 years from JBM.

**Target in ERPNext:** Two options —

**Option A — Full document migration (heavier):**
Import as submitted + paid Purchase Invoices and Sales Invoices. Complete GL history exists in ERPNext. Higher migration effort.

**Option B — Reference-only table (lighter, recommended):**
Create a custom table **Historical Claim Reference** — stores claim number, original amount, paid amount, payer, provider, PO ref, payment date — but does NOT post any GL entries. Used purely for lookup when RA references an old claim.

| | Option A | Option B |
|---|---|---|
| GL history in ERPNext | Yes — complete | No |
| Migration effort | Very high | Low-Medium |
| RA lookup capability | Yes | Yes |
| Affects current balances | No (already paid) | No |
| Recommended | Only if audit requires full GL history | ✅ For most scenarios |

> **Decision point for team:** Option A or Option B for paid historical claims?

### 14.6 Migration Data Requirements from Medical System / JBM

The migration team needs to extract the following fields for every claim in the last 2 years:

| Field | Source | Required for Layer 1 | Required for Layer 2 |
|---|---|---|---|
| Claim Number | Medical system | ✅ | ✅ |
| Provider Name | Medical system | ✅ | ✅ |
| Payer Name | Medical system | ✅ | ✅ |
| Original Claim Amount | JBM | ✅ | ✅ |
| Amount Paid | JBM | ✅ | ✅ |
| Outstanding Balance | JBM | ✅ | — |
| Service Date | Medical system | ✅ | ✅ |
| PO Reference | Medical system | ✅ | ✅ |
| Batch Reference | JBM | ✅ | ✅ |
| Payment Date (if paid) | JBM | — | ✅ |
| RA Reference (if paid) | JBM | — | ✅ |
| Claim Status | JBM | ✅ | ✅ |
| Member ID | Medical system | Optional | Optional |

### 14.7 Migration Execution Plan

```
Step 1 — Data Extraction
  Finance team extracts data from JBM / medical system
  Target: CSV files per year per payer
  Owner: Finance team + JBM vendor
  Estimated time: 2–3 weeks

Step 2 — Data Cleaning
  Remove duplicates
  Standardise provider/payer names to match ERPNext masters
  Validate amounts (outstanding = original − paid)
  Owner: Finance team with Frappe developer support
  Estimated time: 1–2 weeks

Step 3 — Test Migration (UAT environment)
  Run migration script on sample data (1 payer, 3 months)
  Verify: balances match JBM trial balance
  Verify: RA lookup works for a test old claim
  Owner: Frappe developer + finance team
  Estimated time: 1 week

Step 4 — Full Historical Migration
  Run migration script for all 2 years of data
  Verify totals by payer match JBM ageing report
  Owner: Frappe developer
  Estimated time: 1–2 days (script runs automatically)

Step 5 — Opening Balance Journal Entry
  Pass one Journal Entry in ERPNext for remaining GL balances
  (Any items not captured in claim-level import)
  Owner: Finance team
  Estimated time: 1 day

Step 6 — Reconciliation Sign-off
  ERPNext payer balances compared to JBM trial balance per payer
  ERPNext provider balances compared to JBM trial balance per provider
  Differences investigated and cleared
  Owner: Finance manager
  Estimated time: 1 week
```

### 14.8 Migration Risk — Data Volume

2 years of claims data can be very large. The migration script must:
- Run in batches (e.g. 5,000 claims per run) to avoid server timeout
- Be re-runnable safely (idempotent — no duplicate records if run twice)
- Log every record processed with success/failure status
- Produce a reconciliation report at the end

### 14.9 Go-Live Cutover Sequence

```
T-4 weeks : Complete historical migration in UAT environment
T-2 weeks : Finance team reconciliation sign-off on UAT data
T-1 week  : Final data extract from JBM (delta — last 2 weeks of transactions)
T-1 day   : Close books in JBM for go-live period
T-0       : Run final migration script (delta records)
T-0       : Enter opening GL balance journal entry
T-0       : ERPNext go-live — all new transactions in ERPNext
T+1 month : Parallel run — verify ERPNext vs JBM for 1 month
T+5 weeks : Full cutover — JBM read-only (reference only)
```

---

## 15. Roles & Permissions

### 14.1 Proposed ERPNext Roles

| Role | Access Level | Users |
|---|---|---|
| Finance Manager | Full access — all documents, submit, cancel, amend | Senior finance staff |
| Finance User | Create, edit, submit Claims Batch, SINV, PINV, Payment Entry | Finance team |
| Finance Read Only | View all documents, run reports | Management, auditors |
| System Administrator | Full ERPNext access | IT / ERPNext implementer |

### 14.2 Permission Matrix

| Document | Finance Manager | Finance User | Finance Read Only |
|---|---|---|---|
| Claims Batch | Create, Edit, Submit, Cancel | Create, Edit, Submit | View |
| Purchase Invoice | Create, Edit, Submit, Cancel | Create, Edit, Submit | View |
| Sales Invoice | Create, Edit, Submit, Cancel | Create, Edit, Submit | View |
| Payment Entry | Create, Edit, Submit, Cancel | Create, Edit, Submit | View |
| Journal Entry | Create, Edit, Submit, Cancel | Create, Edit | View |
| Chart of Accounts | Edit | View | View |
| Reports | All | All | All |
| Bulk Processing button | ✅ | ✅ | ❌ |
| Cancel submitted documents | ✅ | ❌ | ❌ |

---

## 15. Implementation Phases

### Phase 1 — Foundation (Weeks 1–4)

| Week | Deliverable |
|---|---|
| 1 | ERPNext server setup (Frappe Cloud / VPS), initial install, company setup |
| 2 | Chart of Accounts, Customer masters (payers), Supplier masters (providers) |
| 3 | Item masters, naming series, UAE VAT configuration |
| 4 | Claims Batch DocType + child table — build and test |

**Phase 1 sign-off:** Finance team can create a Claims Batch, upload claims rows, and view the document.

### Phase 2 — Core Processing (Weeks 5–7)

| Week | Deliverable |
|---|---|
| 5 | Bulk Processing script — build, unit test with sample data |
| 6 | Data Import CSV templates for claims + endorsement report |
| 7 | Deferred Revenue import script + scheduler configuration |

**Phase 2 sign-off:** End-to-end test — upload claims batch, run bulk processing, verify GL entries, run month-end deferred revenue, verify balances.

### Phase 3 — Settlement & Reporting (Weeks 8–10)

| Week | Deliverable |
|---|---|
| 8 | Bulk Settlement Upload custom page — build and test |
| 9 | Custom reports: Claims Batch status, Provider ageing, Payer ageing |
| 10 | UAT — full end-to-end test with real data from current system |

**Phase 3 sign-off:** Complete UAT sign-off from finance team.

### Phase 4 — Go-Live (Week 11–12)

| Week | Deliverable |
|---|---|
| 11 | Data migration — opening balances, outstanding invoices |
| 12 | Go-live, parallel run begins |
| 12+ | Parallel run for 1 month, then full cutover |

---

## 16. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Performance issues with very high claim volumes | Medium | High | Provision properly sized server; test with full data volume before go-live |
| 2 | Data quality issues in claims file from medical system | High | Medium | Build validation in import script; provide clear error messages |
| 3 | Frappe developer availability / cost in UAE | Medium | Medium | Identify 2 qualified developers; get fixed-price quote for Phase 1–3 |
| 4 | Medical system unable to export in required CSV format | Low | High | Confirm export capabilities with medical system vendor early |
| 5 | Deferred revenue scheduler fails silently for large volumes | Low | High | Add monitoring + email alerts on scheduler job status |
| 6 | Provider/payer master data incomplete at go-live | High | Medium | Start master data collection immediately; assign owner |
| 7 | Users unfamiliar with ERPNext | High | Medium | Plan 2-day training for finance team before go-live |
| 8 | Parallel run reveals discrepancies | Medium | High | Allocate 1 month parallel run; assign reconciliation owner |

---

## 17. Open Questions for Team Discussion

The following items require team decisions before development begins:

### Architecture

- [ ] **Q1.** Phase 2 integration: Should we build an API link between the medical system and ERPNext in future, or is CSV upload sufficient permanently?
- [ ] **Q2.** Hosting: Frappe Cloud (managed, subscription cost) vs self-hosted VPS (one-time setup, ongoing IT maintenance)? Who maintains the server?

### Business Logic

- [ ] **Q3.** Sales Invoice grouping: One SINV per payer, or one SINV per payer-per-provider combination? Impact on reconciliation complexity.
- [ ] **Q4.** Process Payable naming series: What format should PINV numbers follow? Should it include payer code, year, sequence?
- [ ] **Q5.** Claim removal authority: Who can initiate a claim removal? Is there a formal approval required from medical team?
- [ ] **Q6.** Settlement: Does the bank provide a structured export file for bulk payments, or does the team prepare it manually?

### Data

- [ ] **Q7.** Go-live date: What is the target go-live month/quarter?
- [ ] **Q8.** Historical data: Do we need historical transactions in ERPNext, or only from go-live date?
- [ ] **Q9.** Provider master data: Who is responsible for collecting all provider details (name, bank account, VAT number)?
- [ ] **Q10.** Deferred revenue: Should policies be imported at individual level in ERPNext, or grouped by payer per month?

### Reporting

- [ ] **Q11.** What reports does management require monthly? (ageing, outstanding, revenue summary, deferred schedule?)
- [ ] **Q12.** Are there any regulatory reports required by the UAE Insurance Authority from the accounting system?

---

*This document is a working draft for internal team discussion.*
*All figures used are illustrative examples only.*
*Decisions recorded in Section 17 must be confirmed before development commences.*

---

**Document Control**

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | June 2026 | Finance Team | Initial draft |
