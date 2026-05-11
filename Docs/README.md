# LSUITE — LEDGER SUITE
## Project Documentation

---

## WHAT IS LSUITE

LSuite is a Django-based financial management platform built for South African small businesses. It bridges the gap between local bank accounts (Capitec, TymeBank) and ERPNext by automatically pulling bank statements, parsing transactions, categorising them, and syncing journal entries — so accountants and bookkeepers spend less time on manual data capture and more time on actual accounting work.

The core idea: a small business owner should be able to connect their bank email, import their statements, and have their transactions flowing into ERPNext with minimal manual effort.

---

## THE PROBLEM WE SOLVE

Most small businesses in South Africa run on banks like Capitec and TymeBank. Those banks send monthly PDF statements to email. Getting those transactions into ERPNext currently means:

1. Downloading the PDF
2. Manually reading each transaction
3. Capturing it in ERPNext as a journal entry
4. Reconciling it against any invoices or purchase orders
5. Building a month-end summary for the accountant

LSuite automates steps 1–3 and makes 4–5 significantly easier. For accountants managing multiple clients, this compounds — one accountant can handle far more clients with the same effort.

---

## WHAT IS CURRENTLY BUILT

### Gmail Integration
- OAuth 2.0 connection to a Gmail account
- Automatic fetch of bank statement emails from Capitec and TymeBank senders
- Stores statement metadata (subject, sender, date, bank name)
- Detects PDF attachments

### PDF Parsing
- Extracts transactions from Capitec and TymeBank PDF bank statements
- Handles password-protected PDFs
- Background job processing with live progress tracking (no page refresh needed)
- Batch upload: multiple PDFs processed as one job
- Duplicate detection — same transaction skipped on re-import

### CSV Import
- Upload a bank CSV export directly
- Bulk import: multiple CSV files at once
- Downloadable CSV template so users know the expected format
- Duplicate detection on import

### Transaction Categorisation
- User-defined categories with keyword lists (comma-separated)
- Each category maps to a specific ERPNext account
- Auto-categorise: runs all uncategorised transactions against all active categories
- Preview before applying: see what will be categorised before committing
- Manual override: assign or remove category per transaction
- Category management: create, edit, delete, view all transactions per category

### ERPNext Sync
- Connects to any ERPNext instance via API key + secret
- Creates Journal Entry for each categorised transaction
- Handles debit/credit correctly based on transaction type
- Supports cost centre assignment
- Bulk sync: all ready transactions in one action
- Per-transaction sync from the transaction detail page
- Full sync log with status, ERPNext doc name, and error detail on failure

### Dashboard
- Statement count, transaction count, categorised count, synced count
- Recent statements list
- Recent transactions list
- Quick action buttons

### Auth
- Register, login, logout
- User profile
- Password change

---

## PROJECT STRUCTURE

```
LSuite/
  apps/
    api/          — internal API scaffold (in progress)
    authusers/    — login, register, profile, password change
    bridge/       — categorisation engine, bulk operations
    erpnext/      — ERPNext config, sync service, sync logs
    gmail/        — OAuth, statement import, PDF + CSV parsing
    main/         — dashboard, all shared models
  templates/
    auth/
    bridge/
    components/   — navbar, flash messages, pagination
    erpnext/
    errors/
    gmail/
    main/
  LSuite/
    settings.py
    urls.py
    wsgi.py
    asgi.py
  Docs/
    Todo/
      INTEGRATION_PLAN.md   — Claude AI agent integration plan
      REVERSE_ENGINEERING_PLAN.md  — Groq + Django agent alternative
    README.md               — this file
    MVP.md                  — MVP scope and planned features
  manage.py
  requirements.txt
  render.yaml
```

---

## DATA MODELS

### BankTransaction
The core record. One row per transaction extracted from a PDF or CSV.

| Field | Purpose |
|---|---|
| `user` | Owner |
| `statement` | Source EmailStatement |
| `date` | Transaction date |
| `description` | Raw description from bank |
| `amount` | Transaction amount |
| `transaction_type` | debit / credit |
| `deposit` / `withdrawal` | Raw CSV columns |
| `balance` | Running balance if available |
| `fee` | Bank fee if parsed |
| `category` | FK to TransactionCategory (nullable) |
| `reference_number` | Bank reference |
| `erpnext_synced` | Boolean |
| `erpnext_journal_entry` | ERPNext JE name after sync |
| `erpnext_error` | Last sync error message |

### TransactionCategory
User-defined category. Drives both auto-categorisation and ERPNext account mapping.

| Field | Purpose |
|---|---|
| `name` | Display name |
| `erpnext_account` | ERPNext Chart of Accounts entry |
| `transaction_type` | expense / income / transfer |
| `keywords` | Comma-separated match strings |
| `active` | Whether used in auto-categorise |

### EmailStatement
One record per Gmail message or PDF upload job.

| Field | Purpose |
|---|---|
| `gmail_id` | Unique Gmail message ID |
| `subject` / `sender` | Email metadata |
| `bank_name` | capitec / tymebank / other |
| `state` | new / imported / parsed / error |
| `has_pdf` | Whether PDF attachment found |
| `pdf_password` | Saved password for re-parse |
| `transaction_count` | Count after parsing |

### ERPNextConfig
One config per ERPNext instance per user.

| Field | Purpose |
|---|---|
| `base_url` | ERPNext instance URL |
| `api_key` / `api_secret` | API credentials |
| `default_company` | Company name in ERPNext |
| `bank_account` | Bank account in Chart of Accounts |
| `default_cost_center` | Optional cost centre |
| `is_active` | Only one active config used for sync |

### ERPNextSyncLog
Audit trail. One row per sync attempt.

### PDFImportJob
Background job tracker. Tracks progress across multiple PDF files in a single upload.

### GoogleCredential
OAuth tokens per user for Gmail access.

### Invoice / InvoiceItem
Partial implementation. Invoice header with line items. Planned for full use in Phase 2.

### BankAccount
Named bank account record per user. Links to transactions.

---

## SUPPORTED BANKS

| Bank | Import Method | Parser Status |
|---|---|---|
| Capitec | PDF email attachment / CSV upload | Full support |
| TymeBank | PDF email attachment | Full support |
| Generic | CSV upload | Partial — regex fallback |

---

## TECH STACK

| Layer | Technology |
|---|---|
| Framework | Django 5.2 |
| Language | Python 3.11+ |
| Database (prod) | PostgreSQL |
| Database (dev) | SQLite |
| Static files | WhiteNoise |
| PDF parsing | PyPDF2 |
| Gmail | Google OAuth 2.0 + Gmail API |
| ERP | ERPNext REST API |
| Hosting | Render (free tier) |
| Frontend | Bootstrap 5 + Font Awesome |

---

## ENVIRONMENT VARIABLES

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | True (dev) / False (prod) |
| `DATABASE_URL` | Postgres URL (blank = SQLite) |
| `GOOGLE_REDIRECT_URI` | Gmail OAuth callback URL |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts |

---

## LOCAL SETUP

```bash
git clone <repo>
cd LSuite
pip install -r requirements.txt
cp .env.example .env          # fill in values
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

---

## DEPLOYMENT (RENDER)

1. Push to GitHub
2. Render → New → Blueprint — auto-detects `render.yaml`
3. Set `SECRET_KEY`, `DEBUG=False`, `GOOGLE_REDIRECT_URI`
4. After first deploy, run via Render Shell:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Free-tier Postgres expires after 90 days — upgrade or recreate.

---

## PLANNED FEATURES

### PHASE 1 — RECONCILIATION
- Match bank transactions to ERPNext journal entries by amount, date, and reference
- Flag mismatches: missing entries, wrong amounts, duplicates
- Reconciliation status per transaction (unreconciled / matched / flagged)
- Period-level reconciliation: close a month once all transactions are matched
- Reconciliation report exportable to CSV

### PHASE 2 — INVOICES AND PURCHASE ORDERS
- Create invoices in LSuite and sync to ERPNext Sales Invoice
- Create POs and sync to ERPNext Purchase Invoice
- Auto-match incoming bank credits to outstanding invoices by amount + date
- Auto-match bank debits to outstanding POs
- Flag unmatched payments for manual review
- Invoice aging report (overdue, due soon, paid)

### PHASE 3 — MONTHLY REPORTING AND PROJECTIONS
- Category spending summary: actual vs prior month, variance by category
- Recurring transaction detection — flag regular debits (rent, insurance, subscriptions)
- Projected spend for current month based on patterns from prior 3 months
- Month-end summary pack exportable for accountant (PDF or CSV)
- Dashboard chart: category breakdown, credit vs debit by week

### PHASE 4 — ACCOUNTANT WORKFLOW TOOLS
- Month-end checklist: unreconciled items, unsynced transactions, uncategorised transactions, missing expected recurring entries
- Accrual prompts: flag expected transactions that haven't arrived yet based on history
- Multi-client support: accountant account type can see multiple business accounts on one dashboard
- Client-ready report pack: statement, category totals, reconciliation summary, invoice status
- Notes and flags per transaction for accountant-client communication

### PHASE 5 — AI AGENT LAYER (PLANNED, SEE DOCS/TODO)
- GL Reconciler agent: reviews uncategorised transactions, suggests categories + ERPNext accounts
- Statement Auditor agent: reviews a parsed statement for anomalies before sync
- Month-End Closer agent: generates variance commentary and flags missing accruals

Two implementation paths documented in `Docs/Todo/`:
- `INTEGRATION_PLAN.md` — using Anthropic Claude API directly
- `REVERSE_ENGINEERING_PLAN.md` — using Groq + self-hosted agents in a Django app

---

## WHAT LSuite IS NOT (YET)

- Not a full accounting system — it is a bridge layer into ERPNext
- Not a bank directly — it reads statements, it does not connect to bank APIs
- Not a payroll tool
- Not multi-currency (ZAR only for now)
