# LSuite — Phase 1: Reconciliation

---

## Overview

Phase 1 adds a reconciliation engine to LSuite. It pulls journal entries from ERPNext, matches them against imported `BankTransaction` records, flags discrepancies, and lets the accountant close off a month once everything is clean. A CSV export of the reconciliation report caps the workflow.

---

## Apps Involved

| App | Role in Phase 1 |
|---|---|
| `main` | `BankTransaction` model — adds `recon_status` field and `recon_match` FK |
| `erpnext` | ERPNext config + API client — extended to fetch Journal Entries |
| `bridge` | No changes — categorisation stays separate |
| `reconciliation` *(new)* | All reconciliation models, matching engine, period management, CSV export, views |

---

## New App: `reconciliation`

Create this app:

```bash
python manage.py startapp reconciliation
```

Register in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    'apps.reconciliation',
]
```

---

## Data Models

### 1. `ERPNextJournalEntry` — fetched from ERPNext

```python
# apps/reconciliation/models.py

from django.db import models
from django.contrib.auth.models import User


class ERPNextJournalEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    je_name = models.CharField(max_length=100)          # ERPNext doc name e.g. JV-2024-00123
    posting_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    account = models.CharField(max_length=255)
    reference_number = models.CharField(max_length=255, blank=True)
    remark = models.TextField(blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'je_name')

    def __str__(self):
        return self.je_name
```

### 2. `ReconciliationMatch` — the link between a `BankTransaction` and a `ERPNextJournalEntry`

```python
class ReconciliationMatch(models.Model):
    MATCH_STATUS = [
        ('matched', 'Matched'),
        ('flagged', 'Flagged'),
        ('manual', 'Manual Override'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    transaction = models.OneToOneField(
        'main.BankTransaction',
        on_delete=models.CASCADE,
        related_name='recon_match'
    )
    journal_entry = models.ForeignKey(
        ERPNextJournalEntry,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='matches'
    )
    status = models.CharField(max_length=20, choices=MATCH_STATUS, default='matched')
    flag_reason = models.TextField(blank=True)          # populated when status=flagged
    matched_at = models.DateTimeField(auto_now_add=True)
    matched_by = models.CharField(max_length=20, default='auto')  # auto / manual

    def __str__(self):
        return f"{self.transaction} → {self.journal_entry}"
```

### 3. `ReconciliationPeriod` — monthly close

```python
class ReconciliationPeriod(models.Model):
    PERIOD_STATUS = [
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    year = models.IntegerField()
    month = models.IntegerField()                       # 1–12
    status = models.CharField(max_length=10, choices=PERIOD_STATUS, default='open')
    closed_at = models.DateTimeField(null=True, blank=True)
    total_transactions = models.IntegerField(default=0)
    matched_count = models.IntegerField(default=0)
    flagged_count = models.IntegerField(default=0)
    unreconciled_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ('user', 'year', 'month')

    def __str__(self):
        return f"{self.year}-{self.month:02d} ({self.status})"

    def label(self):
        from calendar import month_name
        return f"{month_name[self.month]} {self.year}"

    def can_close(self):
        return self.unreconciled_count == 0 and self.flagged_count == 0
```

### 4. `BankTransaction` update — add status field

In `apps/main/models.py`, add to `BankTransaction`:

```python
RECON_STATUS = [
    ('unreconciled', 'Unreconciled'),
    ('matched', 'Matched'),
    ('flagged', 'Flagged'),
]

recon_status = models.CharField(
    max_length=20,
    choices=RECON_STATUS,
    default='unreconciled'
)
```

Migration:

```bash
python manage.py makemigrations main reconciliation
python manage.py migrate
```

---

## ERPNext — Fetch Journal Entries

Extend the existing ERPNext API client in `apps/erpnext/`.

```python
# apps/erpnext/client.py  (add this method to your existing ERPNextClient class)

def fetch_journal_entries(self, from_date, to_date):
    params = {
        'doctype': 'Journal Entry',
        'fields': '["name","posting_date","total_debit","accounts","remark","cheque_no"]',
        'filters': f'[["posting_date",">=","{from_date}"],["posting_date","<=","{to_date}"]]',
        'limit_page_length': 500,
    }
    resp = self.session.get(f"{self.base_url}/api/resource/Journal Entry", params=params)
    resp.raise_for_status()
    return resp.json().get('data', [])
```

---

## Matching Engine

```python
# apps/reconciliation/engine.py

from decimal import Decimal
from datetime import timedelta
from .models import ERPNextJournalEntry, ReconciliationMatch
from apps.main.models import BankTransaction


DATE_TOLERANCE = timedelta(days=2)
AMOUNT_TOLERANCE = Decimal('0.01')


def _amounts_match(a, b):
    return abs(a - b) <= AMOUNT_TOLERANCE


def _dates_close(d1, d2):
    return abs((d1 - d2).days) <= DATE_TOLERANCE.days


def run_matching(user, year, month):
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    transactions = BankTransaction.objects.filter(
        user=user,
        date__year=year,
        date__month=month,
        recon_status='unreconciled',
    )
    journal_entries = ERPNextJournalEntry.objects.filter(
        user=user,
        posting_date__year=year,
        posting_date__month=month,
    )

    je_pool = list(journal_entries)
    used_je_ids = set()
    results = {'matched': 0, 'flagged': 0, 'skipped': 0}

    for txn in transactions:
        best = None
        score = 0

        for je in je_pool:
            if je.id in used_je_ids:
                continue

            s = 0
            if _amounts_match(txn.amount, je.amount):
                s += 3
            if _dates_close(txn.date, je.posting_date):
                s += 2
            if txn.reference_number and txn.reference_number == je.reference_number:
                s += 5

            if s > score:
                score = s
                best = je

        if best and score >= 3:
            ReconciliationMatch.objects.update_or_create(
                transaction=txn,
                defaults={
                    'user': user,
                    'journal_entry': best,
                    'status': 'matched',
                    'matched_by': 'auto',
                }
            )
            txn.recon_status = 'matched'
            txn.save(update_fields=['recon_status'])
            used_je_ids.add(best.id)
            results['matched'] += 1
        else:
            flag_reason = _determine_flag_reason(txn, je_pool, used_je_ids)
            ReconciliationMatch.objects.update_or_create(
                transaction=txn,
                defaults={
                    'user': user,
                    'journal_entry': None,
                    'status': 'flagged',
                    'flag_reason': flag_reason,
                    'matched_by': 'auto',
                }
            )
            txn.recon_status = 'flagged'
            txn.save(update_fields=['recon_status'])
            results['flagged'] += 1

    return results


def _determine_flag_reason(txn, je_pool, used_je_ids):
    amount_match = [
        je for je in je_pool
        if je.id not in used_je_ids and _amounts_match(txn.amount, je.amount)
    ]
    if not je_pool:
        return "No journal entries found for this period."
    if not amount_match:
        return f"No journal entry found with matching amount ({txn.amount})."
    return "Amount found but date or reference mismatch — review manually."
```

---

## Views

```python
# apps/reconciliation/views.py

import csv
from calendar import month_name
from datetime import date
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone

from apps.main.models import BankTransaction
from apps.erpnext.models import ERPNextConfig
from apps.erpnext.client import ERPNextClient
from .models import ERPNextJournalEntry, ReconciliationMatch, ReconciliationPeriod
from .engine import run_matching


@login_required
def dashboard(request):
    periods = ReconciliationPeriod.objects.filter(user=request.user).order_by('-year', '-month')
    return render(request, 'reconciliation/dashboard.html', {'periods': periods})


@login_required
def fetch_journal_entries(request, year, month):
    config = get_object_or_404(ERPNextConfig, user=request.user, is_active=True)
    client = ERPNextClient(config)
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    from_date = date(year, month, 1).isoformat()
    to_date = date(year, month, last_day).isoformat()

    try:
        entries = client.fetch_journal_entries(from_date, to_date)
        created = 0
        for e in entries:
            _, c = ERPNextJournalEntry.objects.get_or_create(
                user=request.user,
                je_name=e['name'],
                defaults={
                    'posting_date': e['posting_date'],
                    'amount': e.get('total_debit', 0),
                    'account': '',
                    'reference_number': e.get('cheque_no', ''),
                    'remark': e.get('remark', ''),
                }
            )
            if c:
                created += 1
        messages.success(request, f"Fetched {len(entries)} journal entries ({created} new).")
    except Exception as ex:
        messages.error(request, f"ERPNext fetch failed: {ex}")

    return redirect('reconciliation:period_detail', year=year, month=month)


@login_required
def run_match(request, year, month):
    results = run_matching(request.user, year, month)
    period, _ = ReconciliationPeriod.objects.get_or_create(
        user=request.user, year=year, month=month
    )
    _refresh_period_counts(period)
    messages.success(
        request,
        f"Matching complete — {results['matched']} matched, {results['flagged']} flagged."
    )
    return redirect('reconciliation:period_detail', year=year, month=month)


@login_required
def period_detail(request, year, month):
    period, _ = ReconciliationPeriod.objects.get_or_create(
        user=request.user, year=year, month=month,
        defaults={'status': 'open'}
    )
    _refresh_period_counts(period)

    transactions = BankTransaction.objects.filter(
        user=request.user,
        date__year=year,
        date__month=month,
    ).select_related('recon_match__journal_entry').order_by('date')

    status_filter = request.GET.get('status', '')
    if status_filter:
        transactions = transactions.filter(recon_status=status_filter)

    return render(request, 'reconciliation/period_detail.html', {
        'period': period,
        'transactions': transactions,
        'status_filter': status_filter,
        'month_label': f"{month_name[month]} {year}",
    })


@login_required
def close_period(request, year, month):
    period = get_object_or_404(ReconciliationPeriod, user=request.user, year=year, month=month)
    _refresh_period_counts(period)
    if not period.can_close():
        messages.error(request, "Cannot close period — unreconciled or flagged transactions remain.")
        return redirect('reconciliation:period_detail', year=year, month=month)
    period.status = 'closed'
    period.closed_at = timezone.now()
    period.save()
    messages.success(request, f"{period.label()} closed.")
    return redirect('reconciliation:dashboard')


@login_required
def manual_match(request, txn_id):
    txn = get_object_or_404(BankTransaction, id=txn_id, user=request.user)
    je_id = request.POST.get('journal_entry_id')
    je = get_object_or_404(ERPNextJournalEntry, id=je_id, user=request.user)
    ReconciliationMatch.objects.update_or_create(
        transaction=txn,
        defaults={
            'user': request.user,
            'journal_entry': je,
            'status': 'manual',
            'flag_reason': '',
            'matched_by': 'manual',
        }
    )
    txn.recon_status = 'matched'
    txn.save(update_fields=['recon_status'])
    messages.success(request, "Transaction manually matched.")
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def export_csv(request, year, month):
    transactions = BankTransaction.objects.filter(
        user=request.user,
        date__year=year,
        date__month=month,
    ).select_related('recon_match__journal_entry').order_by('date')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="recon_{year}_{month:02d}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Date', 'Description', 'Amount', 'Type',
        'Recon Status', 'Matched JE', 'Flag Reason'
    ])
    for txn in transactions:
        match = getattr(txn, 'recon_match', None)
        writer.writerow([
            txn.date,
            txn.description,
            txn.amount,
            txn.transaction_type,
            txn.recon_status,
            match.journal_entry.je_name if match and match.journal_entry else '',
            match.flag_reason if match else '',
        ])
    return response


def _refresh_period_counts(period):
    qs = BankTransaction.objects.filter(
        user=period.user,
        date__year=period.year,
        date__month=period.month,
    )
    period.total_transactions = qs.count()
    period.matched_count = qs.filter(recon_status='matched').count()
    period.flagged_count = qs.filter(recon_status='flagged').count()
    period.unreconciled_count = qs.filter(recon_status='unreconciled').count()
    period.save(update_fields=[
        'total_transactions', 'matched_count', 'flagged_count', 'unreconciled_count'
    ])
```

---

## URLs

```python
# apps/reconciliation/urls.py

from django.urls import path
from . import views

app_name = 'reconciliation'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('<int:year>/<int:month>/', views.period_detail, name='period_detail'),
    path('<int:year>/<int:month>/fetch/', views.fetch_journal_entries, name='fetch_je'),
    path('<int:year>/<int:month>/match/', views.run_match, name='run_match'),
    path('<int:year>/<int:month>/close/', views.close_period, name='close_period'),
    path('<int:year>/<int:month>/export/', views.export_csv, name='export_csv'),
    path('match/manual/<int:txn_id>/', views.manual_match, name='manual_match'),
]
```

Register in `LSuite/urls.py`:

```python
path('reconciliation/', include('apps.reconciliation.urls', namespace='reconciliation')),
```

---

## Templates

### `reconciliation/dashboard.html`

```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
  <h2>Reconciliation</h2>
  <a href="{% url 'reconciliation:period_detail' year=today.year month=today.month %}"
     class="btn btn-primary">Current Month</a>
</div>

<table class="table table-hover">
  <thead>
    <tr>
      <th>Period</th><th>Status</th><th>Total</th>
      <th>Matched</th><th>Flagged</th><th>Unreconciled</th><th></th>
    </tr>
  </thead>
  <tbody>
    {% for p in periods %}
    <tr>
      <td>{{ p.label }}</td>
      <td>
        <span class="badge {% if p.status == 'closed' %}bg-success{% else %}bg-warning text-dark{% endif %}">
          {{ p.status }}
        </span>
      </td>
      <td>{{ p.total_transactions }}</td>
      <td>{{ p.matched_count }}</td>
      <td>{{ p.flagged_count }}</td>
      <td>{{ p.unreconciled_count }}</td>
      <td>
        <a href="{% url 'reconciliation:period_detail' year=p.year month=p.month %}"
           class="btn btn-sm btn-outline-secondary">View</a>
      </td>
    </tr>
    {% empty %}
    <tr><td colspan="7" class="text-center text-muted">No periods yet.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

### `reconciliation/period_detail.html`

```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h3>{{ month_label }}</h3>
  <div class="d-flex gap-2">
    <a href="{% url 'reconciliation:fetch_je' year=period.year month=period.month %}"
       class="btn btn-outline-primary btn-sm">Fetch JEs</a>
    <a href="{% url 'reconciliation:run_match' year=period.year month=period.month %}"
       class="btn btn-outline-success btn-sm">Run Matching</a>
    <a href="{% url 'reconciliation:export_csv' year=period.year month=period.month %}"
       class="btn btn-outline-secondary btn-sm">Export CSV</a>
    {% if period.status == 'open' and period.can_close %}
    <a href="{% url 'reconciliation:close_period' year=period.year month=period.month %}"
       class="btn btn-success btn-sm">Close Period</a>
    {% endif %}
  </div>
</div>

<div class="row mb-3">
  <div class="col-md-3">
    <div class="card text-center">
      <div class="card-body">
        <h4>{{ period.total_transactions }}</h4><small>Total</small>
      </div>
    </div>
  </div>
  <div class="col-md-3">
    <div class="card text-center border-success">
      <div class="card-body">
        <h4 class="text-success">{{ period.matched_count }}</h4><small>Matched</small>
      </div>
    </div>
  </div>
  <div class="col-md-3">
    <div class="card text-center border-danger">
      <div class="card-body">
        <h4 class="text-danger">{{ period.flagged_count }}</h4><small>Flagged</small>
      </div>
    </div>
  </div>
  <div class="col-md-3">
    <div class="card text-center border-warning">
      <div class="card-body">
        <h4 class="text-warning">{{ period.unreconciled_count }}</h4><small>Unreconciled</small>
      </div>
    </div>
  </div>
</div>

<!-- Filter -->
<div class="mb-3">
  <a href="?" class="btn btn-sm {% if not status_filter %}btn-secondary{% else %}btn-outline-secondary{% endif %}">All</a>
  <a href="?status=unreconciled" class="btn btn-sm {% if status_filter == 'unreconciled' %}btn-warning{% else %}btn-outline-warning{% endif %}">Unreconciled</a>
  <a href="?status=matched" class="btn btn-sm {% if status_filter == 'matched' %}btn-success{% else %}btn-outline-success{% endif %}">Matched</a>
  <a href="?status=flagged" class="btn btn-sm {% if status_filter == 'flagged' %}btn-danger{% else %}btn-outline-danger{% endif %}">Flagged</a>
</div>

<table class="table table-sm table-hover">
  <thead>
    <tr>
      <th>Date</th><th>Description</th><th>Amount</th>
      <th>Status</th><th>Matched JE</th><th>Flag Reason</th>
    </tr>
  </thead>
  <tbody>
    {% for txn in transactions %}
    <tr>
      <td>{{ txn.date }}</td>
      <td>{{ txn.description|truncatechars:50 }}</td>
      <td>R {{ txn.amount }}</td>
      <td>
        <span class="badge
          {% if txn.recon_status == 'matched' %}bg-success
          {% elif txn.recon_status == 'flagged' %}bg-danger
          {% else %}bg-warning text-dark{% endif %}">
          {{ txn.recon_status }}
        </span>
      </td>
      <td>
        {% if txn.recon_match.journal_entry %}
          {{ txn.recon_match.journal_entry.je_name }}
        {% else %}—{% endif %}
      </td>
      <td class="text-muted small">
        {% if txn.recon_match %}{{ txn.recon_match.flag_reason }}{% endif %}
      </td>
    </tr>
    {% empty %}
    <tr><td colspan="6" class="text-center text-muted">No transactions.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

---

## Matching Logic Summary

| Signal | Weight |
|---|---|
| Amount match (within R0.01) | +3 |
| Date within 2 days | +2 |
| Reference number exact match | +5 |
| **Minimum score to match** | **3** |

If no journal entry scores ≥ 3 against a transaction → flagged with a reason string.

---

## Flag Reasons

| Scenario | Flag Reason |
|---|---|
| No JEs in period at all | "No journal entries found for this period." |
| No JE with matching amount | "No journal entry found with matching amount (R X)." |
| Amount found but date/ref off | "Amount found but date or reference mismatch — review manually." |
| Duplicate JE already used | Treated as unmatched — falls to flagged |

---

## Period Close Rules

A period can only be closed when:

```
unreconciled_count == 0  AND  flagged_count == 0
```

Closed periods are read-only — re-matching is blocked on closed periods (add guard in `run_match` view).

---

## CSV Export Columns

| Column | Source |
|---|---|
| Date | `BankTransaction.date` |
| Description | `BankTransaction.description` |
| Amount | `BankTransaction.amount` |
| Type | `BankTransaction.transaction_type` |
| Recon Status | `BankTransaction.recon_status` |
| Matched JE | `ReconciliationMatch.journal_entry.je_name` |
| Flag Reason | `ReconciliationMatch.flag_reason` |

---

## Migrations Checklist

```bash
python manage.py makemigrations main          # adds recon_status to BankTransaction
python manage.py makemigrations reconciliation # new models
python manage.py migrate
```

---

## Nav Link

Add to your navbar:

```html
<a class="nav-link" href="{% url 'reconciliation:dashboard' %}">
  <i class="fa fa-balance-scale"></i> Reconciliation
</a>
```

---

## Summary of What Phase 1 Delivers

| Feature | How |
|---|---|
| Fetch ERPNext JEs | `ERPNextClient.fetch_journal_entries()` → stored as `ERPNextJournalEntry` |
| Auto-match | Scoring engine in `engine.py` — amount + date + reference |
| Flag mismatches | Score < 3 → `recon_status=flagged` with a reason |
| Per-transaction status | `BankTransaction.recon_status` field — unreconciled / matched / flagged |
| Manual override | `manual_match` view — accountant picks a JE manually |
| Period management | `ReconciliationPeriod` — tracks counts, enforces close rules |
| Period close | Blocked until 0 unreconciled + 0 flagged |
| CSV export | Full transaction list with match and flag detail |
