# LSuite — Full Technical Documentation
**Date:** 2026-05-15  
**Version:** MVP (Django 5.2)  
**Stack:** Python 3.11 · Django 5.2 · PostgreSQL · WhiteNoise · GitHub Actions

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [App Reference](#3-app-reference)
   - [main](#31-main)
   - [authusers](#32-authusers)
   - [gmail](#33-gmail)
   - [bank_parsers](#34-bank_parsers)
   - [bridge](#35-bridge)
   - [erpnext](#36-erpnext)
   - [reconciliation](#37-reconciliation)
   - [api](#38-api)
4. [Data Models](#4-data-models)
5. [Management Commands](#5-management-commands)
6. [GitHub Actions Workflows](#6-github-actions-workflows)
7. [Settings & Environment Variables](#7-settings--environment-variables)
8. [URL Structure](#8-url-structure)
9. [Core Flow](#9-core-flow)
10. [Categorization System](#10-categorization-system)
11. [ERPNext Integration](#11-erpnext-integration)
12. [Reconciliation Engine](#12-reconciliation-engine)
13. [PDF & CSV Parsing](#13-pdf--csv-parsing)
14. [Authentication & Social Auth](#14-authentication--social-auth)
15. [Local Development Setup](#15-local-development-setup)
16. [Deployment (Render)](#16-deployment-render)
17. [Supported Banks](#17-supported-banks)
18. [Known Patterns & Conventions](#18-known-patterns--conventions)

---

## 1. Project Overview

LSuite is a Django-based financial management system for South African small businesses. It bridges bank accounts (Capitec, TymeBank, GoTyme) with ERPNext, automating:

- Bank statement ingestion (Gmail OAuth, PDF upload, CSV upload)
- Transaction parsing from multiple bank formats
- AI-powered and keyword-based transaction categorisation
- ERPNext journal entry creation and sync
- Bank-to-ERPNext reconciliation

The target user is an accountant or bookkeeper who wants a single place to ingest, categorise, reconcile, and export financial data without manual data entry.

---

## 2. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                          LSuite Django App                      │
│                                                                │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌────────────┐  │
│  │  gmail   │  │  bridge  │  │  erpnext   │  │reconciliat.│  │
│  │  OAuth   │  │ categor. │  │  sync      │  │  engine    │  │
│  │  import  │  │ bulk ops │  │  preflight │  │  matching  │  │
│  └────┬─────┘  └────┬─────┘  └─────┬──────┘  └─────┬──────┘  │
│       │             │              │                │          │
│  ┌────▼─────────────▼──────────────▼────────────────▼──────┐  │
│  │                    apps/main/models.py                   │  │
│  │  BankTransaction · TransactionCategory · ERPNextConfig   │  │
│  │  EmailStatement · BankAccount · PDFImportJob · Invoice   │  │
│  └──────────────────────────────┬───────────────────────────┘  │
│                                 │                              │
│  ┌──────────────────────────────▼───────────────────────────┐  │
│  │                   bank_parsers                           │  │
│  │     CapitecParser · TymeBankParser · GoTymeParser        │  │
│  │     GenericParser · CSVParser · PDFParser (router)       │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
         │                                      │
    Gmail API                            ERPNext REST API
    HuggingFace                          (Journal Entries,
    Inference API                         Accounts, Companies)
```

**Request lifecycle:**
1. User uploads PDF / imports Gmail / uploads CSV
2. `bank_parsers` parses raw bytes → list of transaction dicts
3. `BankTransaction` records are created in DB
4. `auto_categorize` management command (or `CategorizationService`) runs keyword + zero-shot AI matching
5. Categorised transactions are synced to ERPNext via `ERPNextService.create_journal_entry()`
6. Reconciliation engine fetches ERPNext Journal Entries and matches them to bank transactions

---

## 3. App Reference

### 3.1 `main`

**Role:** Dashboard, shared models, global stats.

**Views:**
| View | URL | Description |
|------|-----|-------------|
| `about` | `/` | Public landing page |
| `index` | `/index/` | Auth-required dashboard with stats and recent items |

**Key models defined here:** `BankAccount`, `TransactionCategory`, `GoogleCredential`, `EmailStatement`, `BankTransaction`, `ERPNextConfig`, `ERPNextSyncLog`, `PDFImportJob`, `Invoice`, `InvoiceItem`

---

### 3.2 `authusers`

**Role:** User registration, login, logout, profile, password management, social auth completion.

**Views:**
| View | URL | Description |
|------|-----|-------------|
| `register_view` | `/authusers/register/` | Full registration with profile fields |
| `login_view` | `/authusers/login/` | Standard username/password login |
| `logout_view` | `/authusers/logout/` | Session logout |
| `profile` | `/authusers/profile/` | View profile + social links |
| `change_password` | `/authusers/change-password/` | Password change form |
| `password_reset_request` | `/authusers/reset/` | Send reset email |
| `password_reset_confirm` | `/authusers/reset/<uid>/<token>/` | Set new password |
| `social_complete` | `/authusers/social/complete/` | Post-OAuth profile completion |
| `social_link_save` | `/authusers/links/add/` or `.../edit/` | AJAX add/edit social link |
| `social_link_delete` | `/authusers/links/<pk>/delete/` | AJAX delete social link |

**Models:**
- `UserProfile` — One-to-one extension of Django's `User`. Fields: phone, DOB, ID number, city, province, country, occupation, years experience, industry, LinkedIn/GitHub/portfolio URLs.
- `SocialLink` — Per-user social media links with auto-detected emoji icons.

**Social auth pipeline** (`SOCIAL_AUTH_PIPELINE`): standard pipeline + `apps.authusers.pipeline.save_social_profile` to persist provider data into `UserProfile`.

---

### 3.3 `gmail`

**Role:** Gmail OAuth credential management, statement import, PDF/CSV upload, transaction listing.

**Views:**
| View | URL | Description |
|------|-----|-------------|
| `credentials` | `/gmail/credentials/` | List OAuth credentials |
| `new_credential` | `/gmail/credentials/new/` | Create credential |
| `authorize` | `/gmail/credentials/<pk>/authorize/` | Start OAuth flow |
| `oauth_callback` | `/gmail/oauth/callback/` | OAuth redirect handler |
| `statements` | `/gmail/statements/` | List imported statements |
| `import_statements` | `/gmail/statements/import/` | Trigger Gmail fetch |
| `statement_detail` | `/gmail/statements/<pk>/` | Statement + transactions |
| `parse_statement` | `/gmail/statements/<pk>/parse/` | Download + parse PDF from Gmail |
| `transactions` | `/gmail/transactions/` | Transaction list with filters |
| `transaction_detail` | `/gmail/transactions/<pk>/` | Single transaction |
| `upload_csv` | `/gmail/upload-csv/` | Single CSV upload |
| `bulk_csv_import` | `/gmail/bulk-csv-import/` | Multi-file CSV upload |
| `upload_pdf` | `/gmail/upload-pdf/` | Multi-file PDF upload (async) |
| `pdf_import_progress` | `/gmail/pdf-jobs/<pk>/` | Progress page |
| `pdf_import_status` | `/gmail/pdf-jobs/<pk>/status/` | JSON status poll endpoint |
| `pdf_import_history` | `/gmail/pdf-jobs/` | All import jobs |

**`GmailService`** (`apps/gmail/services.py`):
- `get_auth_url()` — builds Google OAuth2 URL for gmail.readonly scope
- `exchange_code_for_tokens()` — exchanges auth code, stores tokens in `GoogleCredential`
- `fetch_statements()` — searches Gmail for bank statement emails, creates `EmailStatement` records
- `download_and_parse_pdf()` — downloads PDF attachment, routes through `PDFParser`, saves `BankTransaction` records

**PDF import is asynchronous:** `upload_pdf` view spawns a `threading.Thread` running `run_pdf_job()`. The frontend polls `/gmail/pdf-jobs/<pk>/status/` for progress.

---

### 3.4 `bank_parsers`

**Role:** Parse bank statement PDFs and CSVs into normalised transaction dicts.

#### PDFParser (router) — `apps/bank_parsers/parsers/base.py`

`PDFParser.parse_pdf(pdf_data, bank_name, password)` routes to the correct parser:
- `bank_name='capitec'` → `CapitecParser`
- `bank_name='tymebank'` → auto-detects GoTyme signals, falls back to `TymeBankLegacyParser`
- `bank_name='gotyme'` → `GoTymeParser`
- Any bank → runs `is_gotyme()` auto-detection on extracted text first

All parsers return a list of dicts:
```python
{
  'date': date,
  'description': str,
  'amount': float,
  'type': 'credit' | 'debit',
  'reference': str,
  'balance': float,      # optional
  'fee': float,          # optional (Capitec only)
  'category': str,       # optional (Capitec only)
}
```

#### CapitecParser — `apps/bank_parsers/parsers/capitec.py`

Parses text extracted via PyPDF2. Handles:
- 3-column rows (amount, fee, balance) and 2-column rows (amount, balance)
- Multi-line rows where amounts appear on the next line
- Category keyword extraction from description suffix
- Credit/debit classification via keyword lists (`CREDIT_KW`, `DEBIT_KW`)

#### TymeBankLegacyParser — `apps/bank_parsers/parsers/tymebank.py`

Regex-based parser for legacy TymeBank statement format. Handles:
- `dd MMM YYYY` date format
- 4-column inline rows (fees | money out | money in | balance)
- Multi-line descriptions spread across subsequent lines

#### GoTymeParser — `apps/bank_parsers/parsers/gotyme.py`

Character-level PDF parser using `pdfplumber`. Uses x-coordinate column buckets to reconstruct tabular data from raw character positions. Auto-detected via `is_gotyme()` signal strings.

Column boundaries:
```
COL_DATE_X1   = 72
COL_DETAIL_X1 = 326
COL_CREDIT_X1 = 368
COL_DEBIT_X1  = 411
```

#### GenericParser — `apps/bank_parsers/parsers/generic.py`

Fallback regex parser. Tries four date format patterns. Used when bank is unrecognised.

#### CSVParser — `apps/bank_parsers/uploads/csv_upload.py`

Parses CSV exports with headers: `Transaction Date, Posting Date, Description, Debits, Credits, Balance, Bank account`. Returns list of dicts suitable for direct `BankTransaction` creation.

---

### 3.5 `bridge`

**Role:** Transaction categorisation, category CRUD, bulk operations, ERPNext preflight (legacy).

**Views:**
| View | URL | Description |
|------|-----|-------------|
| `categories` | `/bridge/categories/` | List all categories with stats |
| `new_category` | `/bridge/categories/new/` | Create category |
| `edit_category` | `/bridge/categories/<pk>/edit/` | Edit category |
| `delete_category` | `/bridge/categories/<pk>/delete/` | Delete (if no transactions) |
| `category_transactions` | `/bridge/categories/<pk>/transactions/` | Transactions in category |
| `bulk_operations` | `/bridge/bulk-operations/` | Bulk ops dashboard |
| `auto_categorize` | `/bridge/bulk-operations/auto-categorize/` | Run keyword categorisation |
| `auto_categorize_ai` | `/bridge/bulk-operations/auto-categorize-ai/` | Dispatch GH Actions AI job |
| `preview_categorization` | `/bridge/bulk-operations/preview-categorization/` | JSON preview |
| `classify_single` | `/bridge/classify/` | AJAX single-transaction classifier |
| `categorize_transaction` | `/bridge/transactions/<pk>/categorize/` | Manually assign category |
| `uncategorize_transaction` | `/bridge/transactions/<pk>/uncategorize/` | Remove category |

**`CategorizationService`** (`apps/bridge/services.py`):
- `auto_categorize_all()` — three-pass pipeline:
  1. DB keyword/tag matching via `TransactionCategory.matches_description()`
  2. `BUILTIN_CLUES` dict matching (hardcoded merchant → category map)
  3. HuggingFace zero-shot classification (if `_hf_client` available)
- `preview_categorization()` — same logic, dry-run, returns JSON-serialisable preview
- `suggest_category(description)` — returns best category or classification result for a description

**`BulkSyncService`** (`apps/bridge/services.py`):
- `sync_all_ready()` — syncs all categorised, unsynced, non-junk transactions to ERPNext
- `sync_by_category(category_id)` — sync by category
- `sync_by_date_range(start_date, end_date)` — sync by date range

**Junk category filtering:** A set of `JUNK_CATEGORY_NAMES` is defined to exclude low-quality auto-generated categories (e.g., `'uncategorised'`, `'sweep transfer'`) from sync and re-categorisation pipelines.

---

### 3.6 `erpnext`

**Role:** ERPNext configuration management, journal entry sync, sync preflight, sync logs.

**Views:**
| View | URL | Description |
|------|-----|-------------|
| `configs` | `/erpnext/configs/` | List ERPNext configs |
| `new_config` | `/erpnext/configs/new/` | Create + test connection |
| `edit_config` | `/erpnext/configs/<pk>/edit/` | Edit + re-test |
| `delete_config` | `/erpnext/configs/<pk>/delete/` | Delete config |
| `test_config` | `/erpnext/configs/<pk>/test/` | JSON connection test |
| `activate_config` | `/erpnext/configs/<pk>/activate/` | Set as active config |
| `sync_logs` | `/erpnext/sync-logs/` | Paginated sync audit log |
| `sync_transaction` | `/erpnext/sync/<pk>/` | Sync single transaction (JSON) |
| `fetch_accounts` | `/erpnext/fetch-accounts/` | Return ERPNext chart of accounts (JSON) |
| `fetch_cost_centers` | `/erpnext/fetch-cost-centers/` | Return cost centers (JSON) |
| `fetch_companies` | `/erpnext/fetch-companies/` | Return company list (JSON) |
| `update_config_defaults` | `/erpnext/update-config-defaults/` | AJAX save company/bank/cost-center |
| `sync_preflight` | `/erpnext/sync-preflight/` | Preflight form + GH Actions dispatch |
| `sync_job_status` | `/erpnext/sync-job-status/` | GH Actions job status page |
| `sync_job_status_api` | `/erpnext/sync-job-status-api/` | JSON poll for GH Actions run status |
| `bulk_sync_post` | `/erpnext/bulk-sync/` | Execute bulk sync directly |

**`ERPNextService`** (`apps/erpnext/services.py`):

Key methods:
- `test_connection()` — GET `/api/method/frappe.auth.get_logged_user`
- `create_journal_entry(transaction)` — builds and POSTs a `Journal Entry` doctype. Handles debit/credit row construction, bank account resolution, company name resolution (by name, abbreviation, or partial match).
- `get_chart_of_accounts()` — paginated fetch of all `Account` records, filtered by company
- `fetch_journal_entries(from_date, to_date)` — used by reconciliation to pull JEs for a period
- `_resolve_account(search_term)` — resolves a partial account name to its fully-qualified ERPNext name (`Name - Abbreviation`)
- `_resolve_company_name()` — resolves `default_company` against live ERPNext company list

**Journal entry structure:**
```python
{
  "doctype": "Journal Entry",
  "voucher_type": "Journal Entry",
  "company": "<resolved company>",
  "posting_date": "YYYY-MM-DD",
  "accounts": [
    # bank row: debit for credit txn, credit for debit txn
    {"account": "<bank_account>", "debit_in_account_currency": X, "credit_in_account_currency": Y},
    # expense/income row: inverse
    {"account": "<category.erpnext_account>", "debit_in_account_currency": Y, "credit_in_account_currency": X},
  ],
  "user_remark": "<transaction.description>",
  "cheque_no": "<reference_number>",
}
```

---

### 3.7 `reconciliation`

**Role:** Match bank transactions against ERPNext journal entries for a given month.

**Views:**
| View | URL | Description |
|------|-----|-------------|
| `dashboard` | `/reconciliation/` | Period list + transaction month picker |
| `period_detail` | `/reconciliation/<year>/<month>/` | Full period view with match status |
| `fetch_journal_entries` | `/reconciliation/<year>/<month>/fetch/` | Pull JEs from ERPNext for period |
| `run_match` | `/reconciliation/<year>/<month>/match/` | Execute auto-matching |
| `close_period` | `/reconciliation/<year>/<month>/close/` | Close period (if fully reconciled) |
| `reopen_period` | `/reconciliation/<year>/<month>/reopen/` | Reopen closed period |
| `export_csv` | `/reconciliation/<year>/<month>/export/` | Download reconciliation CSV |
| `manual_match` | `/reconciliation/match/manual/<txn_id>/` | Manually assign JE to transaction |
| `unmatch_transaction` | `/reconciliation/match/unmatch/<txn_id>/` | Remove match |

**Models:**
- `ERPNextJournalEntry` — local cache of ERPNext JEs fetched for a period
- `ReconciliationMatch` — links a `BankTransaction` to an `ERPNextJournalEntry` with status: `matched`, `flagged`, `manual`
- `ReconciliationPeriod` — tracks state (open/closed) and counts for a year/month pair per user

**Matching engine** (`apps/reconciliation/engine.py`):

`run_matching(user, year, month)` scores each bank transaction against available JEs:
- +3 points: amounts match within R0.05 tolerance
- +2 points: dates within 2 days
- +5 points: reference numbers match exactly

Score ≥ 3 → `matched`. Below threshold → `flagged` with a reason string.

A period can only be closed when `unreconciled_count == 0` and `flagged_count == 0`.

---

### 3.8 `api`

Scaffold app — models and views are empty stubs. Reserved for future internal API endpoints.

---

## 4. Data Models

### `BankAccount`
| Field | Type | Notes |
|-------|------|-------|
| `user` | FK User | Owner |
| `account_name` | CharField(200) | Display name |
| `account_number` | CharField(100) | Optional |
| `bank_name` | CharField(100) | e.g. "Capitec" |
| `erpnext_account` | CharField(200) | Fully-qualified ERPNext account for journal entries |
| `balance` | Decimal | Current balance |
| `is_active` | Boolean | |

### `TransactionCategory`
| Field | Type | Notes |
|-------|------|-------|
| `name` | CharField(100) unique | e.g. "Groceries" |
| `erpnext_account` | CharField(200) | ERPNext income/expense account |
| `transaction_type` | CharField(20) | `'credit'` or `'debit'` |
| `keywords` | TextField | Comma-separated match keywords |
| `tags` | TextField | Comma-separated AI-learned merchant names |
| `active` | Boolean | Excluded from matching if False |
| `color` | Integer | UI colour index |

Key methods:
- `get_keywords_list()` / `get_tags_list()` — split and lower-case
- `matches_description(description)` — returns True if any keyword or tag appears in the description
- `add_tag(tag)` — appends a new tag if not already present

### `BankTransaction`
| Field | Type | Notes |
|-------|------|-------|
| `user` | FK User | |
| `bank_account` | FK BankAccount nullable | |
| `statement` | FK EmailStatement nullable | |
| `invoice` | FK Invoice nullable | |
| `date` | DateField | Transaction date |
| `transaction_type` | CharField | `'credit'` or `'debit'` |
| `amount` | Decimal nullable | Unified amount field |
| `deposit` | Decimal nullable | Credit amount (CSV import) |
| `withdrawal` | Decimal nullable | Debit amount (CSV import) |
| `balance` | Decimal nullable | Running balance |
| `fee` | Decimal nullable | Bank fee (Capitec) |
| `description` | CharField(500) | Raw transaction description |
| `reference_number` | CharField(100) | Bank reference |
| `category` | FK TransactionCategory nullable | |
| `recon_status` | CharField | `unreconciled`, `matched`, `flagged` |
| `erpnext_synced` | Boolean | |
| `erpnext_journal_entry` | CharField | JE name after sync |
| `erpnext_error` | TextField | Last sync error |

**Note:** `amount`, `deposit`, and `withdrawal` partially overlap. `ERPNextService._extract_amount()` checks all three, preferring `withdrawal`/`deposit` over `amount`.

### `ERPNextConfig`
| Field | Type | Notes |
|-------|------|-------|
| `user` | FK User | |
| `name` | CharField(100) | Friendly label |
| `base_url` | CharField(255) | ERPNext instance URL |
| `api_key` | CharField(255) | |
| `api_secret` | CharField(255) | |
| `default_company` | CharField(200) | Company name or abbreviation |
| `bank_account` | CharField(200) | Fallback bank-side ERPNext account |
| `default_cost_center` | CharField(200) | Optional cost center |
| `is_active` | Boolean | Only one active config per user expected |

### `ERPNextSyncLog`
| Field | Type | Notes |
|-------|------|-------|
| `config` | FK ERPNextConfig | |
| `record_type` | CharField | e.g. `'bank_transaction'` |
| `record_id` | Integer | PK of the synced record |
| `erpnext_doctype` | CharField | e.g. `'Journal Entry'` |
| `erpnext_doc_name` | CharField | ERPNext document name |
| `status` | CharField | `'success'` or `'failed'` |
| `error_message` | TextField | |

### `PDFImportJob`
| Field | Type | Notes |
|-------|------|-------|
| `user` | FK User | |
| `filename` | CharField | Comma-joined filenames |
| `bank_name` | CharField | Selected bank |
| `pdf_password` | CharField | Optional |
| `status` | CharField | `pending`, `processing`, `done`, `failed` |
| `progress` | Integer | 0–100 |
| `total_files` / `processed_files` | Integer | |
| `transactions_found` / `transactions_saved` / `transactions_skipped` | Integer | |
| `statement` | FK EmailStatement | First statement created |

### `EmailStatement`
Represents one imported bank statement (from Gmail or upload). Links to `BankTransaction` via `related_name='bank_transactions'`.

### `ReconciliationMatch`
One-to-one with `BankTransaction`. Links to `ERPNextJournalEntry` (nullable for flagged). Status: `matched`, `flagged`, `manual`.

---

## 5. Management Commands

### `seed_categories`
```
python manage.py seed_categories [--overwrite]
```
Seeds 17 default `TransactionCategory` records with keyword and tag lists. Use `--overwrite` to reset keywords/tags on existing categories. Safe to re-run; uses `get_or_create`.

**Seeded categories:** Groceries, Fuel, Transport, Food & Dining, Entertainment, Healthcare, Telecommunications, Banking & Finance, Bank Charges, Utilities, Shopping, Income, Interest Income, Savings & Transfers, Digital Payments, Savings Round-up, Transfer Out.

---

### `auto_categorize`
```
python manage.py auto_categorize [--all] [--force-all] [--user USER_ID] [--dry-run] [--min-score 0.2]
```
Three-pass categorisation:
1. **Keyword match** — `TransactionCategory.matches_description()` with type filtering (credit/debit)
2. **CLUE_MAP match** — hardcoded merchant→category dict; creates category if missing
3. **Zero-shot AI** — `mDeBERTa-v3-base-mnli-xnli` via `transformers.pipeline`. Skips if score < `--min-score`. Boosts score by +0.5 when a clue is detected in description.

`--force-all`: clears `category=None` on all unsynced transactions before re-running.  
`--dry-run`: prints decisions without saving.

---

### `cleanup_categories`
```
python manage.py cleanup_categories
```
Deletes any `TransactionCategory` that has zero associated transactions.

---

### `recategorize`
```
python manage.py recategorize [--all] [--user USER_ID]
```
Lightweight keyword-only re-categorisation pass. No AI. Respects transaction type (credit/debit).

---

### `erpnext_sync`
```
python manage.py erpnext_sync [--dry-run] [--limit N] [--transaction-id ID]
```
Syncs categorised, unsynced transactions to ERPNext as Journal Entries.

Pre-checks before sync loop:
1. Active `ERPNextConfig` exists and connection succeeds
2. Transactions with no `bank_account` FK: validates/resolves `config.bank_account`
3. `BankAccount` records: auto-resolves `erpnext_account` if not fully qualified
4. Categories: auto-resolves `erpnext_account` if not fully qualified

Skips transactions with zero amount. Logs per-transaction success/failure.

---

## 6. GitHub Actions Workflows

### `Seed Categories` — `Seed Categories.yml`
**Trigger:** Manual (`workflow_dispatch`)  
Runs `python manage.py seed_categories --overwrite`. Useful for resetting category keywords after definition changes.

---

### `AI Categorize` — `ai_categorize.yml` and `auto_categorize.yml`

> **Note:** Two near-identical workflows exist (`ai_categorize.yml` and `auto_categorize.yml`). `ai_categorize.yml` includes an additional "Diagnose DB state" step. Both dispatch `auto_categorize` management command.

**Trigger:** Manual + daily cron at 02:00 UTC  
**Inputs:**
| Input | Default | Description |
|-------|---------|-------------|
| `user_id` | empty | Limit to one user |
| `dry_run` | `false` | Print-only mode |
| `min_score` | `0.2` | Zero-shot confidence threshold |
| `force_all` | `false` | Wipe and re-categorise all |

**Steps:**
1. Checkout + setup Python 3.11
2. Cache HuggingFace model (`mDeBERTa-v3-base-mnli-xnli`) in `/tmp/hf_cache`
3. `seed_categories` (creates missing defaults)
4. *(ai_categorize.yml only)* Diagnose DB state — prints category/transaction counts to logs
5. Pre-warm model via inline Python
6. `auto_categorize` with constructed args
7. `cleanup_categories`

**Required secrets:** `DATABASE_URL`, `SECRET_KEY`, `HF_TOKEN`  
**Optional:** `GH_TOKEN`, `GH_REPO` (for status dispatch)

---

### `ERPNext Sync` — `erpnext_sync.yml`
**Trigger:** Manual (`workflow_dispatch`)  
Runs `python manage.py erpnext_sync` against the production database.

**Required secrets:** `DATABASE_URL`, `DJANGO_SECRET_KEY`, `HUGGINGFACE_API_KEY`, `GH_TOKEN`, `GH_REPO`

---

### `Migrate on Push` — `migrate_on_push.yml`
**Trigger:** Push to any branch  
Runs `makemigrations` then `migrate`. Keeps the production DB schema current on every push.

**Required secrets:** `DATABASE_URL`, `DJANGO_SECRET_KEY`

---

## 7. Settings & Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Django secret key |
| `DATABASE_URL` | Yes (prod) | Full DB connection string (postgres/mysql/sqlite) |
| `DEBUG` | No | `'True'` or `'False'` (default False) |
| `ALLOWED_HOSTS` | No | Comma-separated hosts |
| `RENDER_EXTERNAL_HOSTNAME` | No | Auto-detected on Render |
| `GOOGLE_REDIRECT_URI` | Yes (Gmail) | OAuth callback URL |
| `GOOGLE_CLIENT_ID` | No | Social login Google client ID |
| `GOOGLE_CLIENT_SECRET` | No | Social login Google client secret |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | No | GitHub social login |
| `FACEBOOK_APP_ID` / `FACEBOOK_APP_SECRET` | No | Facebook social login |
| `HUGGINGFACE_API_KEY` | No | HuggingFace Inference API token |
| `HF_TOKEN` | No | Alternative HF token env var |
| `GH_TOKEN` | No | GitHub PAT for Actions dispatch |
| `GH_REPO` | No | `owner/repo` for Actions dispatch |
| `EMAIL_BACKEND` | No | Django email backend |
| `EMAIL_HOST` / `EMAIL_PORT` | No | SMTP settings |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | No | SMTP credentials |
| `DEFAULT_FROM_EMAIL` | No | From address for password resets |

**Database URL detection:** `settings.py` validates the `DATABASE_URL` scheme (`postgres`, `postgresql`, `mysql`, `sqlite`). Falls back to SQLite in `DEBUG=True`. Raises `RuntimeError` in production if missing.

---

## 8. URL Structure

```
/                           → main:about (public)
/index/                     → main:index (dashboard)

/authusers/register/
/authusers/login/
/authusers/logout/
/authusers/profile/
/authusers/change-password/
/authusers/reset/...
/authusers/links/...
/authusers/social/complete/

/gmail/credentials/...
/gmail/statements/...
/gmail/transactions/...
/gmail/upload-csv/
/gmail/bulk-csv-import/
/gmail/upload-pdf/
/gmail/pdf-jobs/...

/bridge/categories/...
/bridge/bulk-operations/...
/bridge/classify/
/bridge/transactions/<pk>/categorize/
/bridge/transactions/<pk>/uncategorize/

/erpnext/configs/...
/erpnext/sync-logs/
/erpnext/sync/<pk>/
/erpnext/fetch-accounts/
/erpnext/fetch-cost-centers/
/erpnext/fetch-companies/
/erpnext/sync-preflight/
/erpnext/sync-job-status/
/erpnext/sync-job-status-api/
/erpnext/bulk-sync/

/reconciliation/
/reconciliation/<year>/<month>/...

/admin/
/social/...                 → social_django
```

---

## 9. Core Flow

### Import via Gmail
```
1. User connects Gmail OAuth credential (/gmail/credentials/new/)
2. User clicks "Import Statements"
   → GmailService.fetch_statements() searches Gmail for bank statement emails
   → Creates EmailStatement records (state='new')
3. User clicks "Parse PDF" on a statement
   → GmailService.download_and_parse_pdf() fetches the attachment
   → PDFParser routes to correct bank parser
   → BankTransaction records created (no category yet)
4. auto_categorize runs (via bulk-ops button or GH Actions daily cron)
   → Keyword pass → BUILTIN_CLUES pass → zero-shot AI pass
5. User reviews categories in /bridge/bulk-operations/
6. User opens Sync Preflight (/erpnext/sync-preflight/)
   → Assigns ERPNext accounts to categories and bank accounts
   → Dispatches erpnext_sync.yml GH Actions workflow
7. ERPNext sync workflow creates Journal Entries
8. User reconciles via /reconciliation/
```

### Import via PDF Upload
```
1. User goes to /gmail/upload-pdf/, selects bank + PDF files
2. PDFImportJob created, threading.Thread spawned
3. run_pdf_job() parses files, saves BankTransaction records
4. auto_categorize management command runs after job completes
5. User continues at step 5 above
```

### Import via CSV Upload
```
1. User goes to /gmail/upload-csv/ or /gmail/bulk-csv-import/
2. CSVParser parses file(s)
3. BankTransaction records created
4. User runs auto-categorise from /bridge/bulk-operations/
```

---

## 10. Categorization System

### Three-pass pipeline

**Pass 1 — DB keyword/tag matching:**
- Iterates `TransactionCategory.objects.filter(active=True)` (junk excluded)
- For each category: calls `matches_description()` which checks keywords and tags as substrings
- Type-filtered: credit transactions only match `transaction_type='credit'` categories

**Pass 2 — BUILTIN_CLUES:**
- Large hardcoded dict mapping merchant substrings to category names
- Example: `"checkers" → "Groceries"`, `"netflix" → "Entertainment"`
- Creates new `TransactionCategory` if the target name doesn't exist
- Appends the matched clue to the category's keywords for future DB matching

**Pass 3 — Zero-shot AI (HuggingFace):**
- Model: `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`
- Candidate labels: all active non-junk category names from DB
- Score boosted +0.5 when a CLUE_MAP match is found in description
- Skips if score < `min_score` (default 0.2)
- For very low confidence + no clue: creates a new category named from the first word of the description

### Single-transaction classifier
`classify_transaction(description)` in `bridge/services.py` exposes the same pipeline for AJAX use at `/bridge/classify/`. Returns:
```json
{
  "raw": "CHECKERS EASTGATE",
  "category": "Groceries",
  "score": 0.94,
  "confidence": "High",
  "clue_detected": "checkers",
  "method": "hf+clue",
  "top3": [["Groceries", "94.0%"], ["Shopping", "3.1%"], ["Food & Dining", "2.9%"]]
}
```

### Junk category exclusion
These names are always excluded from matching, sync, and display logic:
`uncategorised`, `uncategorized`, `other`, `other income`, `other expense`, `other expenses`, `fee fees`, `terminal) fees`, `***0) fees`, `sweep transfer`, `deposit investments`, `applied transfer`, `fnb cellphone`, `digital payments`, `4th transfer`, `received interest`

---

## 11. ERPNext Integration

### Authentication
Uses ERPNext token-based API auth: `Authorization: token {api_key}:{api_secret}`.

### Company resolution
`_resolve_company_name()` tries in order:
1. Exact name match against `/api/resource/Company`
2. Abbreviation match (case-insensitive)
3. Partial name match (substring)
4. Returns stored value as-is if no match found

### Account resolution
`_resolve_account(search_term)` queries `/api/resource/Account?filters=[["name","like","%term%"]]`. If the returned name differs from input, logs the resolution and returns the qualified name.

### Bank account priority
Per transaction: `BankAccount.erpnext_account` → `ERPNextConfig.bank_account`

### Sync preflight flow
1. User opens `/erpnext/sync-preflight/`
2. Categories with missing/unqualified `erpnext_account` are listed
3. BankAccount records with missing/unqualified `erpnext_account` are listed
4. User fills in accounts using a live account picker (fetched from `/erpnext/fetch-accounts/`)
5. POST saves updated accounts + dispatches `erpnext_sync.yml` via GitHub API
6. User is redirected to sync job status page which polls GitHub Actions for run status

---

## 12. Reconciliation Engine

### Period lifecycle
```
open → (fetch JEs) → (run match) → review → close
                                          ↓
                                      reopen (if needed)
```

### Matching algorithm
See `apps/reconciliation/engine.py`:
- Score-based greedy matching
- Each JE can only be used once (`used_je_ids` set)
- Best-scoring JE above threshold (≥3) wins

### Flag reasons (auto-generated)
- "No journal entries found for this period."
- "No journal entry found with matching amount (R X)."
- "Amount found but date or reference mismatch — review manually."

### Manual override
Users can manually link any transaction to any JE in the same period via the period detail page. Manual matches set `matched_by='manual'`.

### Period close guard
`ReconciliationPeriod.can_close()` returns `True` only when `unreconciled_count == 0` and `flagged_count == 0`.

---

## 13. PDF & CSV Parsing

### Parser selection logic

```
parse_pdf(pdf_data, bank_name, password)
├── bank_name == 'tymebank'
│   ├── extract text
│   ├── is_gotyme(text) → GoTymeParser
│   └── else → TymeBankLegacyParser
├── extract text
├── is_gotyme(text) → GoTymeParser (auto-detected regardless of bank_name)
├── bank_name == 'capitec' → CapitecParser
├── bank_name == 'gotyme' → GoTymeParser
└── else → GenericParser
```

### PDF text extraction
Falls back gracefully: tries `PyPDF2` first, then `pdfplumber`. Password-protected PDFs are decrypted before extraction.

### CSV format expected
```
Transaction Date,Posting Date,Description,Debits,Credits,Balance,Bank account
2025/09/23,2025/09/23,CHECKERS EASTGATE,,1500.00,8250.00,Capitec Savings
```
Amount parsing strips `R`, commas, spaces. Returns `None` for blank/dash values.

### Deduplication
All import paths check for existing transactions matching `(user, date, description, amount/withdrawal/deposit)` before creating. Duplicate rows are counted as `skipped`.

---

## 14. Authentication & Social Auth

**Backends configured:**
1. `social_core.backends.google.GoogleOAuth2`
2. `social_core.backends.github.GithubOAuth2`
3. `social_core.backends.facebook.FacebookOAuth2`
4. `django.contrib.auth.backends.ModelBackend`

**Post-registration:** New social auth users are redirected to `/authusers/social/complete/` to fill in missing profile fields (occupation, city, etc.).

**Note on `login()` call after `create_user()`:** Since multiple AUTHENTICATION_BACKENDS are configured, `login()` is called with `backend='django.contrib.auth.backends.ModelBackend'` explicitly to avoid Django's backend inference ambiguity.

**Session config:** `SESSION_ENGINE = 'django.contrib.sessions.backends.db'`, cookie age 2 weeks.

**Gmail OAuth** (for statement import) is separate from social login. It uses Google's OAuth2 flow scoped to `gmail.readonly` and stores tokens in `GoogleCredential` model. This is not `social_django` — it's a custom flow in `gmail/services.py`.

---

## 15. Local Development Setup

```bash
git clone <repo>
cd LSuite
pip install -r requirements.txt
cp .env.example .env
# Edit .env:
#   SECRET_KEY=any-secret-key
#   DEBUG=True
#   DATABASE_URL=   (leave empty for SQLite)
#   GOOGLE_REDIRECT_URI=http://localhost:8000/gmail/oauth/callback/

python manage.py migrate
python manage.py createsuperuser
python manage.py seed_categories
python manage.py runserver
```

**Optional for AI categorisation locally:**
```bash
# Requires ~1GB download on first run
python manage.py auto_categorize --dry-run
```

**HuggingFace token** is only required if using the Inference API path (`bridge/services.py`). The management command (`auto_categorize.py`) loads the model locally via `transformers.pipeline` — no token needed if the model is cached.

---

## 16. Deployment (Render)

1. Push to GitHub
2. Render → New → Blueprint (auto-detects `render.yaml` if present)
3. Set environment variables:
   - `SECRET_KEY`
   - `DEBUG=False`
   - `DATABASE_URL` (Render Postgres connection string)
   - `GOOGLE_REDIRECT_URI=https://<your-domain>/gmail/oauth/callback/`
   - `HF_TOKEN` (for AI categorisation GitHub Actions)
   - `GH_TOKEN` + `GH_REPO` (for Actions dispatch from UI)
4. Post-deploy:
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py seed_categories
   ```

**Static files:** WhiteNoise serves static files with `CompressedManifestStaticFilesStorage`. `collectstatic` should run as part of the build command.

---

## 17. Supported Banks

| Bank | Parser | Detection | Format |
|------|--------|-----------|--------|
| Capitec | `CapitecParser` | Selected by user | PDF (email / upload) + CSV |
| TymeBank (legacy) | `TymeBankLegacyParser` | Selected by user | PDF (email / upload) |
| GoTyme | `GoTymeParser` | Auto-detected via signal strings | PDF only |
| Generic | `GenericParser` | Fallback | PDF with date + amount pattern |
| Any | `CSVParser` | N/A | CSV with standard headers |

GoTyme auto-detection signals: `'GoTyme'`, `'GoalSave'`, `'Credits (+)'`, `'Running Balance'`, `'Debits (-)'`

---

## 18. Known Patterns & Conventions

### Complete file preference
The codebase favours complete, self-contained files over partial diffs. Views, services, and management commands are fully contained per module.

### Zero-build frontend
No npm/webpack pipeline. Templates use CDN-loaded libraries. Static files served by WhiteNoise.

### Junk category handling
Junk categories accumulate when the Capitec parser extracts category names from transaction descriptions (e.g. "Fees", "Uncategorised"). The system identifies and excludes them using `JUNK_CATEGORY_NAMES` sets defined in both `bridge/services.py` and `auto_categorize.py`. The `cleanup_categories` command removes empty ones.

### Amount field duality
`BankTransaction` has both `amount` (unified field, used by PDF upload path) and `deposit`/`withdrawal` (used by Gmail import and CSV path). `ERPNextService._extract_amount()` normalises across all three. Future refactoring should unify these.

### ERPNext account qualification
ERPNext accounts must be fully qualified as `"Account Name - Company Abbreviation"` (e.g. `"Cash - V"`). The system auto-resolves partial names where possible, but the preflight step is the user-facing entry point for fixing missing qualifications.

### GitHub Actions as async worker
Because Render's free tier has no background worker, long-running tasks (AI categorisation, ERPNext sync) are dispatched as GitHub Actions workflows via the GitHub REST API. The UI provides a status polling page after dispatch.

### Per-user data isolation
All querysets are filtered by `user=request.user`. `ERPNextConfig`, `BankTransaction`, `EmailStatement`, `GoogleCredential`, `PDFImportJob`, and reconciliation models all carry a `user` FK.
