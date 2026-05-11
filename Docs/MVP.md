# LSuite — MVP

Django financial management system that connects South African small business bank accounts to ERPNext, automates transaction processing, and gives accountants the tools to reconcile, report, and manage financial documents without leaving one place.

---

## Problem

Small businesses in South Africa — using banks like Capitec and TymeBank — have no easy way to get their bank transactions into ERPNext. Accountants and bookkeepers spend hours manually capturing transactions, matching invoices, and building month-end reports. LSuite removes that friction.

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

### Phase 1 — Reconciliation
- Match bank transactions against ERPNext journal entries
- Flag discrepancies (missing entries, amount mismatches, duplicates)
- Reconciliation status per transaction and per statement period
- Mark transactions as reconciled, with date and user stamp

### Phase 2 — Invoices & Purchase Orders
- Create and manage invoices inside LSuite
- Create POs and match them against incoming bank payments
- Auto-match bank credit transactions to outstanding invoices
- Sync invoices and POs to ERPNext (Sales Invoice, Purchase Invoice doctype)
- Flag unmatched payments for manual review

### Phase 3 — Monthly Reporting & Projections
- Monthly spending summary by category (actual vs prior month)
- Projected spend for current month based on recurring transaction patterns
- Variance commentary on categories that deviate significantly
- Exportable summary report (PDF or CSV) for the accountant
- Dashboard widget showing category breakdown for the month

### Phase 4 — Accountant Workflow Tools
- Month-end checklist: outstanding reconciliations, unsynced transactions, missing categories
- Accrual prompts based on recurring transactions that haven't appeared yet
- Client-ready summary pack: statement of transactions, category totals, reconciliation status
- Multi-user support: assign clients to accountants, accountant sees all client dashboards

---

## Data Model Summary

| Model | Purpose |
|---|---|
| `BankTransaction` | Raw transaction from PDF/CSV |
| `TransactionCategory` | User-defined categories with keywords and ERPNext account |
| `EmailStatement` | Imported Gmail statement record |
| `GoogleCredential` | Stored OAuth credentials per user |
| `ERPNextConfig` | ERPNext instance connection details |
| `ERPNextSyncLog` | Audit log of every sync |
| `PDFImportJob` | Background job tracker for PDF batch imports |
| `Invoice` *(partial)* | Invoice header and line items |
| `BankAccount` | Named bank accounts per user |
