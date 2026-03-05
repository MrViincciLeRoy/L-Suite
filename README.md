# LSuite — Ledger Suite

Django-based financial management system that integrates Gmail bank statements with ERPNext.

## Deploy to Render (Free Tier)

### 1. Add these files to your project root
- `requirements.txt`
- `render.yaml`
- Replace `LSuite/settings.py` with the new `settings.py`

### 2. Push to GitHub

```bash
git add .
git commit -m "Add Render deployment config"
git push
```

### 3. Deploy on Render

- Go to [render.com](https://render.com) → New → Blueprint
- Connect your GitHub repo
- Render will auto-detect `render.yaml` and create the web service + PostgreSQL database

### 4. Set Environment Variables (if not using render.yaml)

| Key | Value |
|-----|-------|
| `SECRET_KEY` | Any long random string |
| `DEBUG` | `False` |
| `DATABASE_URL` | Auto-set from Render Postgres |
| `ALLOWED_HOSTS` | `.onrender.com` |
| `GOOGLE_REDIRECT_URI` | `https://your-app.onrender.com/gmail/oauth/callback/` |

### 5. After deploy

Run migrations manually if needed via Render Shell:
```bash
python manage.py migrate
python manage.py createsuperuser
```

## Local Development

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Set `DEBUG=True` in your local `.env` or environment.

## Notes

- **Free tier Postgres on Render** expires after 90 days — upgrade or re-create
- Static files are served via WhiteNoise (no S3 needed)
- Gmail OAuth redirect URI must match exactly what's set in Google Cloud Console
