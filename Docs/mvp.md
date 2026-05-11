# LSuite — MVP

Django financial management system that pulls bank statements from Gmail, parses PDF/CSV transactions, categorises them, and syncs journal entries to ERPNext.

---

## Apps

| App | Role |
|-----|------|
| `main` | Dashboard, models, shared data |
| `authusers` | Login / register / profile |
| `gmail` | OAuth, statement import, PDF/CSV parsing |
| `bridge` | Auto-categorisation, bulk ops |
| `erpnext` | ERPNext config, journal entry sync |

---

## Stack

- Python 3.11+, Django 5.2
- PostgreSQL (prod) / SQLite (dev)
- WhiteNoise for static files
- Google Gmail API (OAuth2)
- ERPNext REST API

---

## Local Setup

```bash
git clone <repo>
cd LSuite
pip install -r requirements.txt
cp .env.example .env   # fill in values
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

**.env**
```
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=            # leave blank to use SQLite
GOOGLE_REDIRECT_URI=http://localhost:8000/gmail/oauth/callback/
```

---

## Deploy (Render)

1. Push to GitHub
2. Render → New → Blueprint — auto-detects `render.yaml`
3. Set env vars:

| Key | Value |
|-----|-------|
| `SECRET_KEY` | long random string |
| `DEBUG` | `False` |
| `DATABASE_URL` | auto-set by Render Postgres |
| `GOOGLE_REDIRECT_URI` | `https://<app>.onrender.com/gmail/oauth/callback/` |

4. After deploy, run via Render Shell:
```bash
python manage.py migrate
python manage.py createsuperuser
```

> Free-tier Postgres expires after 90 days.

---

## Core Flow

```
Gmail OAuth → Fetch Statements → Parse PDF/CSV → Auto-Categorise → Sync to ERPNext
```

1. Add Google OAuth credential under `/gmail/credentials/`
2. Authorise Gmail access
3. Import statements → parse PDFs (password-protected supported) or upload CSV
4. Run auto-categorise in `/bridge/bulk-operations/`
5. Bulk sync to ERPNext or sync per transaction

---

## CSV Format

```
Transaction Date,Posting Date,Description,Debits,Credits,Balance,Bank account
2025/09/23,2025/09/23,Sample Deposit,,1000.00,5000.00,Capitec Savings
```

Download template at `/gmail/download-csv-template/`

---

## Supported Banks

- Capitec
- TymeBank
- Generic fallback (regex-based)
