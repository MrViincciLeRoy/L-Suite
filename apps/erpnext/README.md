# ERPNext Sync — GH Actions Flow

## What changed

The preflight form now saves everything to the DB **and then dispatches** a GitHub Actions job instead of running the sync inline. This avoids Render free-tier timeouts on large batch syncs.

## Flow

```
Preflight form (GET)
  → user picks company / bank account / cost center
  → user assigns ERPNext accounts to categories missing one

Preflight form (POST)
  1. Save ERPNextConfig fields (company, bank_account, default_cost_center)
  2. Save erpnext_account on each TransactionCategory
  3. POST to GH Actions → dispatches erpnext_sync.yml
  4. Redirect to /erpnext/sync-job/ (status page)

Status page
  → polls /erpnext/sync-job/api/ every 5 s
  → proxies GitHub API (token stays server-side)
  → shows queued / in_progress / success / failure
```

## New files

| File | Purpose |
|---|---|
| `apps/main/management/commands/erpnext_sync.py` | Management command run by GH Actions |
| `.github/workflows/erpnext_sync.yml` | Workflow triggered by preflight |
| `templates/erpnext/sync_job_status.html` | Live-polling status page |

## Env vars required

```
GH_TOKEN   — fine-grained PAT with Actions: write on the repo
GH_REPO    — e.g. your-org/your-repo
```

Both must be set on Render **and** as GitHub Actions secrets (for the workflow itself).

## Manual sync (no GH Actions)

`/erpnext/sync-now/` still works — it calls `BulkSyncService.sync_all_ready()` directly.

```bash
# local / server shell
python manage.py erpnext_sync
python manage.py erpnext_sync --user 1 --dry-run
```
