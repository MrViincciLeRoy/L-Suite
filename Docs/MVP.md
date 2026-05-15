# LSuite — MVP

Django financial management system that connects South African small business bank accounts to ERPNext, automates transaction processing, and gives accountants the tools to reconcile, report, and manage financial documents without leaving one place.

---

## Problem

Small businesses in South Africa — using banks like Capitec and TymeBank — have no easy way to get their bank transactions into ERPNext. Accountants and bookkeepers spend hours manually downloading CSVs, reformatting data, cleaning weeks of backlogged transactions, chasing overdue invoices, and matching supplier payments to POs. LSuite removes that friction end to end.

---

## What It Does (Current)

| Area | What's Built |
|---|---|
| **Gmail Import** | OAuth 2.0 connection to Gmail, fetches bank statement emails automatically |
| **PDF Parsing** | Extracts transactions from Capitec and TymeBank PDF statements (password-protected supported) |
| **CSV Import** | Upload bank CSV exports directly, bulk import multiple files |
| **Categorisation** | Keyword-based auto-categorisation of transactions against user-defined categories |
| **ERPNext Sync** | Creates journal entries in ERPNext via REST API, one transaction at a time or bulk |
| **Bulk Operations** | Auto-categorise all, bulk sync to ERPNext, preview before committing |
| **Sync Logs** | Full audit trail of every ERPNext sync attempt with error detail |
| **Auth** | Register, login, profile, password change |

---

## Apps

| App | Role |
|---|---|
| `main` | Dashboard, all shared models, stats |
| `authusers` | Login / register / profile |
| `gmail` | OAuth, statement import, PDF + CSV parsing |
| `bridge` | Auto-categorisation, bulk ops, category management |
| `erpnext` | ERPNext config, journal entry sync, sync logs |
| `api` | Scaffold — internal API endpoints (in progress) |

---

## Stack

- Python 3.11+, Django 5.2
- PostgreSQL (prod) / SQLite (dev)
- WhiteNoise for static files
- Google Gmail API (OAuth2)
- ERPNext REST API
- PyPDF2 for PDF parsing

---

## Supported Banks

| Bank | Method | Status |
|---|---|---|
| Capitec | PDF (email attachment) + CSV | Supported |
| TymeBank | PDF (email attachment) | Supported |
| Generic | CSV upload | Partial |

---

## Local Setup

```bash
git clone <repo>
cd LSuite
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

**.env**
```
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=
GOOGLE_REDIRECT_URI=http://localhost:8000/gmail/oauth/callback/
```

---

## Deploy (Render)

1. Push to GitHub
2. Render → New → Blueprint (auto-detects `render.yaml`)
3. Set env vars: `SECRET_KEY`, `DEBUG=False`, `DATABASE_URL`, `GOOGLE_REDIRECT_URI`
4. After deploy: `python manage.py migrate && python manage.py createsuperuser`

---

## Core Flow (Current)

```
Gmail OAuth → Fetch Statement Emails → Parse PDF/CSV → Auto-Categorise → Sync to ERPNext
```

---

## Planned Features (Next Phases)

### Phase 1 — Live Bank Feed

The current flow requires manually downloading a CSV from the bank, reformatting it, uploading it to LSuite, and then spending days cleaning a week's worth of backlogged transactions. The goal is to eliminate that entirely.

- Direct API connection to Capitec and TymeBank (Open Banking / bank-specific APIs)
- Automatic transaction pull on a daily basis or every 2 hours
- Transactions available for processing on the same day they occur — no more week-long backlogs
- Fallback to Gmail PDF/CSV import for banks without API access
- Webhook or scheduled job to trigger pulls automatically (no manual intervention)

---

### Phase 2 — Reconciliation

- Match bank transactions against ERPNext journal entries
- Flag discrepancies: missing entries, amount mismatches, duplicates
- Reconciliation status per transaction and per statement period
- Mark transactions as reconciled, with date and user stamp

---

### Phase 3 — Invoices & Aged Debtor Management

#### Invoice Management
- Create and manage sales invoices inside LSuite
- Auto-match bank credit transactions to outstanding invoices
- Sync invoices to ERPNext (Sales Invoice doctype)
- Flag unmatched payments for manual review

#### Aged Debtor Tracking
- Track payment terms per client (e.g. 30-day payment terms)
- Automatically bucket outstanding invoices by how far past due they are:
  - **Current** — within payment terms
  - **30 days overdue** — past due date, under 60 days
  - **60 days overdue** — between 60 and 90 days
  - **90+ days overdue** — critical, escalate immediately
- Aged debtor dashboard showing all clients and their overdue status at a glance
- Automated payment reminders sent to clients at 30, 60, and 90-day thresholds
- Alerts and follow-up prompts for the accountant: *"Client X has not paid. It has been 45 days."*

#### Customer Concentration Analysis
- Revenue breakdown by client — which clients make up the largest share of income
- Flag over-reliance on a single client (concentration risk)
- Trend view: is a client's payment behaviour worsening over time?

---

### Phase 4 — Purchase Orders & Supplier Payment Matching

- Create POs inside LSuite and raise them on ERPNext (Purchase Invoice doctype)
- When a supplier payment leaves the bank account, automatically match it to the relevant PO
- Allocate bank debit transactions to outstanding POs based on amount, supplier, and date
- Flag unmatched supplier payments for manual review
- PO status tracking: raised → partially paid → fully settled

---

### Phase 5 — Monthly Reporting & Projections

- Monthly spending summary by category (actual vs prior month)
- Projected spend for current month based on recurring transaction patterns
- Variance commentary on categories that deviate significantly
- Exportable summary report (PDF or CSV) for the accountant
- Dashboard widget showing category breakdown for the month

---

### Phase 6 — Accountant Workflow Tools

- Month-end checklist: outstanding reconciliations, unsynced transactions, missing categories
- Accrual prompts based on recurring transactions that haven't appeared yet
- Client-ready summary pack: statement of transactions, category totals, reconciliation status
- Multi-user support: assign clients to accountants, accountant sees all client dashboards

---

## Data Model Summary

| Model | Purpose |
|---|---|
| `BankTransaction` | Raw transaction from PDF/CSV or live bank feed |
| `TransactionCategory` | User-defined categories with keywords and ERPNext account |
| `EmailStatement` | Imported Gmail statement record |
| `GoogleCredential` | Stored OAuth credentials per user |
| `ERPNextConfig` | ERPNext instance connection details |
| `ERPNextSyncLog` | Audit log of every sync |
| `PDFImportJob` | Background job tracker for PDF batch imports |
| `BankFeedJob` | Scheduled job tracker for live bank feed pulls |
| `Invoice` *(partial)* | Invoice header and line items |
| `InvoiceAgingBucket` | Aged debtor status per invoice (current / 30 / 60 / 90+) |
| `PaymentReminder` | Log of automated reminders sent to clients |
| `PurchaseOrder` | PO header linked to supplier and ERPNext |
| `POPaymentMatch` | Links bank debit transactions to settled POs |
| `BankAccount` | Named bank accounts per user |