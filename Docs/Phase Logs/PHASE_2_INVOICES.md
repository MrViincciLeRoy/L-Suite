# LSuite — Phase 2: Invoice Integration

**Status:** Planning
**Depends on:** Phase 1 (Reconciliation) — Complete
**Stack:** Python 3.11 · Django 5.2 · ERPNext REST API

---

## Phase 1 Confirmation

Phase 1 is **complete**. The following is fully built and working:

- `reconciliation` app with all models (`ERPNextJournalEntry`, `ReconciliationMatch`, `ReconciliationPeriod`)
- `recon_status` field on `BankTransaction`
- Matching engine in `engine.py` (amount + date + reference scoring)
- Fetch JEs from ERPNext, auto-match, flag mismatches
- Manual match override
- Period open/close/reopen with guard logic
- CSV export
- All views and templates

---

## What Phase 2 Is (And Is Not)

**What it is NOT:**
LSuite will NOT create invoices. Invoices are created and managed in ERPNext where the tools already exist.

**What it IS:**
LSuite pulls Sales Invoices and Purchase Invoices from ERPNext, caches them locally, and lets users search, view, and link them to bank transactions. The goal is to give the accountant a single place to see: "this bank payment came in — which invoice does it belong to?"

---

## Overview

```
ERPNext (source of truth)
    ↓  REST API pull
LSuite (local cache + UI)
    ↓  user links invoice ↔ bank transaction
BankTransaction gets linked to an invoice
Invoice gets marked as paid in LSuite view
```

---

## Apps Involved

| App | Role in Phase 2 |
|---|---|
| `main` | `BankTransaction` model — adds `linked_invoice` FK |
| `erpnext` | `ERPNextService` — extended to fetch Sales + Purchase Invoices |
| `invoices` *(new)* | All invoice models, views, sync logic, linking UI |

---

## New App: `invoices`

```bash
python manage.py startapp invoices
```

Register in `settings.py`:

```python
INSTALLED_APPS = [
    ...
    'apps.invoices',
]
```

---

## ERPNext API Reference

### Authentication

All requests use the same token-based auth already in `ERPNextConfig`:

```
Authorization: token {api_key}:{api_secret}
```

This is already handled by the existing `ERPNextService` session setup — no changes needed to auth.

### Fetch Sales Invoices

```
GET {base_url}/api/resource/Sales Invoice
```

Params:

| Param | Value | Notes |
|---|---|---|
| `fields` | `["name","customer","customer_name","posting_date","due_date","grand_total","outstanding_amount","status","currency"]` | Fields to return |
| `filters` | `[["posting_date",">=","2024-01-01"],["posting_date","<=","2024-01-31"]]` | Date filter |
| `limit_page_length` | `500` | Max records per page |
| `limit_start` | `0` | Pagination offset |

Example response:
```json
{
  "data": [
    {
      "name": "ACC-SINV-2024-00123",
      "customer": "CUST-001",
      "customer_name": "Acme Corp",
      "posting_date": "2024-01-15",
      "due_date": "2024-02-14",
      "grand_total": 15000.00,
      "outstanding_amount": 15000.00,
      "status": "Unpaid",
      "currency": "ZAR"
    }
  ]
}
```

### Fetch a Single Sales Invoice (with line items)

```
GET {base_url}/api/resource/Sales Invoice/{name}
```

Returns full document including `items` child table.

### Fetch Purchase Invoices

```
GET {base_url}/api/resource/Purchase Invoice
```

Same params as Sales Invoice. Key fields: `supplier`, `supplier_name`, `bill_no`, `bill_date`, `grand_total`, `outstanding_amount`, `status`.

### Pagination Pattern

ERPNext paginates by default at 20 records. Use `limit_page_length` and `limit_start` to page through:

```python
def fetch_all_invoices(self, doctype, from_date, to_date):
    all_records = []
    start = 0
    page_size = 500

    while True:
        params = {
            'fields': json.dumps([
                'name', 'posting_date', 'due_date',
                'grand_total', 'outstanding_amount', 'status', 'currency',
                # Sales Invoice
                'customer', 'customer_name',
                # Purchase Invoice
                'supplier', 'supplier_name', 'bill_no',
            ]),
            'filters': json.dumps([
                ['posting_date', '>=', from_date],
                ['posting_date', '<=', to_date],
            ]),
            'limit_page_length': page_size,
            'limit_start': start,
            'order_by': 'posting_date asc',  # stable sort prevents duplicate pagination
        }
        resp = self.session.get(
            f"{self.base_url}/api/resource/{doctype}",
            params=params
        )
        resp.raise_for_status()
        data = resp.json().get('data', [])
        if not data:
            break
        all_records.extend(data)
        start += page_size

    return all_records
```

> **Note:** Always use `order_by` when paginating. Without it, ERPNext's default ordering can shift between pages, causing duplicates or missed records.

---

## Data Models

### `apps/invoices/models.py`

```python
from django.db import models
from django.contrib.auth.models import User


class ERPNextInvoice(models.Model):
    INVOICE_TYPE = [
        ('sales', 'Sales Invoice'),
        ('purchase', 'Purchase Invoice'),
    ]

    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Submitted', 'Submitted'),
        ('Unpaid', 'Unpaid'),
        ('Partly Paid', 'Partly Paid'),
        ('Paid', 'Paid'),
        ('Overdue', 'Overdue'),
        ('Cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPE)

    # ERPNext identifiers
    erp_name = models.CharField(max_length=100)          # e.g. ACC-SINV-2024-00123
    erp_status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Unpaid')

    # Party (customer for sales, supplier for purchase)
    party_id = models.CharField(max_length=200, blank=True)       # ERPNext customer/supplier ID
    party_name = models.CharField(max_length=255, blank=True)     # Display name

    # Amounts
    currency = models.CharField(max_length=10, default='ZAR')
    grand_total = models.DecimalField(max_digits=14, decimal_places=2)
    outstanding_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Dates
    posting_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    # Purchase invoice only
    bill_no = models.CharField(max_length=100, blank=True)     # Supplier's own invoice number
    bill_date = models.DateField(null=True, blank=True)

    # Sync metadata
    fetched_at = models.DateTimeField(auto_now=True)
    raw_data = models.JSONField(default=dict, blank=True)      # Full ERPNext response cached

    class Meta:
        unique_together = ('user', 'erp_name')
        ordering = ['-posting_date']
        indexes = [
            models.Index(fields=['user', 'invoice_type', 'erp_status']),
            models.Index(fields=['user', 'posting_date']),
            models.Index(fields=['user', 'party_name']),
        ]

    def __str__(self):
        return f"{self.erp_name} — {self.party_name} ({self.erp_status})"

    @property
    def is_paid(self):
        return self.erp_status in ('Paid',)

    @property
    def is_overdue(self):
        from django.utils import timezone
        return (
            self.erp_status in ('Unpaid', 'Partly Paid')
            and self.due_date
            and self.due_date < timezone.now().date()
        )

    @property
    def amount_paid(self):
        return self.grand_total - self.outstanding_amount
```

### Update `BankTransaction` — add invoice link

In `apps/main/models.py`, add to `BankTransaction`:

```python
linked_invoice = models.ForeignKey(
    'invoices.ERPNextInvoice',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='linked_transactions',
)
```

### Migration

```bash
python manage.py makemigrations invoices
python manage.py makemigrations main    # for the linked_invoice FK
python manage.py migrate
```

---

## ERPNext Service Extension

Add these methods to the existing `ERPNextService` in `apps/erpnext/services.py`:

```python
def fetch_sales_invoices(self, from_date, to_date):
    """Fetch Sales Invoices from ERPNext for a date range."""
    return self._fetch_invoices_paginated(
        doctype='Sales Invoice',
        fields=[
            'name', 'customer', 'customer_name',
            'posting_date', 'due_date',
            'grand_total', 'outstanding_amount',
            'status', 'currency',
        ],
        from_date=from_date,
        to_date=to_date,
    )

def fetch_purchase_invoices(self, from_date, to_date):
    """Fetch Purchase Invoices from ERPNext for a date range."""
    return self._fetch_invoices_paginated(
        doctype='Purchase Invoice',
        fields=[
            'name', 'supplier', 'supplier_name',
            'posting_date', 'due_date', 'bill_no', 'bill_date',
            'grand_total', 'outstanding_amount',
            'status', 'currency',
        ],
        from_date=from_date,
        to_date=to_date,
    )

def fetch_invoice_detail(self, doctype, name):
    """Fetch a single invoice with full line items."""
    resp = self.session.get(f"{self.base_url}/api/resource/{doctype}/{name}")
    resp.raise_for_status()
    return resp.json().get('data', {})

def _fetch_invoices_paginated(self, doctype, fields, from_date, to_date):
    import json
    all_records = []
    start = 0
    page_size = 500

    while True:
        params = {
            'fields': json.dumps(fields),
            'filters': json.dumps([
                ['posting_date', '>=', from_date],
                ['posting_date', '<=', to_date],
            ]),
            'limit_page_length': page_size,
            'limit_start': start,
            'order_by': 'posting_date asc',
        }
        resp = self.session.get(
            f"{self.base_url}/api/resource/{doctype}",
            params=params
        )
        resp.raise_for_status()
        data = resp.json().get('data', [])
        if not data:
            break
        all_records.extend(data)
        if len(data) < page_size:
            break
        start += page_size

    return all_records
```

---

## Invoice Sync Service

```python
# apps/invoices/services.py

from django.utils import timezone
from apps.erpnext.models import ERPNextConfig
from apps.erpnext.services import ERPNextService
from .models import ERPNextInvoice


class InvoiceSyncService:

    def __init__(self, user):
        self.user = user
        self.config = ERPNextConfig.objects.filter(user=user, is_active=True).first()
        if not self.config:
            raise ValueError("No active ERPNext config found.")
        self.client = ERPNextService(self.config)

    def sync_period(self, year, month):
        """
        Pull Sales + Purchase Invoices from ERPNext for a given month.
        Returns a dict with counts.
        """
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        from_date = f"{year}-{month:02d}-01"
        to_date = f"{year}-{month:02d}-{last_day:02d}"

        results = {
            'sales_fetched': 0, 'sales_created': 0, 'sales_updated': 0,
            'purchase_fetched': 0, 'purchase_created': 0, 'purchase_updated': 0,
        }

        # Sync Sales Invoices
        sales_data = self.client.fetch_sales_invoices(from_date, to_date)
        results['sales_fetched'] = len(sales_data)
        for entry in sales_data:
            created = self._upsert_invoice(entry, 'sales')
            if created:
                results['sales_created'] += 1
            else:
                results['sales_updated'] += 1

        # Sync Purchase Invoices
        purchase_data = self.client.fetch_purchase_invoices(from_date, to_date)
        results['purchase_fetched'] = len(purchase_data)
        for entry in purchase_data:
            created = self._upsert_invoice(entry, 'purchase')
            if created:
                results['purchase_created'] += 1
            else:
                results['purchase_updated'] += 1

        return results

    def _upsert_invoice(self, data, invoice_type):
        """Create or update a local ERPNextInvoice from raw API data. Returns True if created."""
        if invoice_type == 'sales':
            party_id = data.get('customer', '')
            party_name = data.get('customer_name', '') or data.get('customer', '')
        else:
            party_id = data.get('supplier', '')
            party_name = data.get('supplier_name', '') or data.get('supplier', '')

        defaults = {
            'invoice_type': invoice_type,
            'erp_status': data.get('status', 'Unpaid'),
            'party_id': party_id,
            'party_name': party_name,
            'currency': data.get('currency', 'ZAR'),
            'grand_total': data.get('grand_total', 0),
            'outstanding_amount': data.get('outstanding_amount', 0),
            'posting_date': data['posting_date'],
            'due_date': data.get('due_date') or None,
            'bill_no': data.get('bill_no', ''),
            'bill_date': data.get('bill_date') or None,
            'raw_data': data,
        }

        obj, created = ERPNextInvoice.objects.update_or_create(
            user=self.user,
            erp_name=data['name'],
            defaults=defaults,
        )
        return created
```

---

## Views

```python
# apps/invoices/views.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q

from apps.main.models import BankTransaction
from .models import ERPNextInvoice
from .services import InvoiceSyncService


@login_required
def dashboard(request):
    """Invoice list with search and filter."""
    invoices = ERPNextInvoice.objects.filter(user=request.user)

    # Filters
    invoice_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    search = request.GET.get('q', '')

    if invoice_type:
        invoices = invoices.filter(invoice_type=invoice_type)
    if status:
        invoices = invoices.filter(erp_status=status)
    if search:
        invoices = invoices.filter(
            Q(party_name__icontains=search) |
            Q(erp_name__icontains=search) |
            Q(bill_no__icontains=search)
        )

    invoices = invoices.order_by('-posting_date')

    return render(request, 'invoices/dashboard.html', {
        'invoices': invoices,
        'invoice_type': invoice_type,
        'status': status,
        'search': search,
    })


@login_required
def invoice_detail(request, pk):
    """Single invoice view with linked transactions."""
    invoice = get_object_or_404(ERPNextInvoice, pk=pk, user=request.user)
    linked_txns = invoice.linked_transactions.all()

    # Unlinked transactions that could match (by amount, within 30 days)
    from datetime import timedelta
    from decimal import Decimal
    amount = invoice.grand_total
    date_from = invoice.posting_date - timedelta(days=30)
    date_to = invoice.posting_date + timedelta(days=30)
    tolerance = Decimal('0.05')

    candidate_txns = BankTransaction.objects.filter(
        user=request.user,
        linked_invoice__isnull=True,
        date__gte=date_from,
        date__lte=date_to,
    ).filter(
        Q(amount__gte=amount - tolerance, amount__lte=amount + tolerance) |
        Q(deposit__gte=amount - tolerance, deposit__lte=amount + tolerance)
    )

    return render(request, 'invoices/detail.html', {
        'invoice': invoice,
        'linked_txns': linked_txns,
        'candidate_txns': candidate_txns,
    })


@login_required
def sync_invoices(request, year, month):
    """Pull invoices from ERPNext for a given period."""
    if request.method != 'POST':
        return redirect('invoices:dashboard')

    try:
        service = InvoiceSyncService(request.user)
        results = service.sync_period(year, month)
        messages.success(
            request,
            f"Sync complete — "
            f"{results['sales_created']} sales invoices added, "
            f"{results['purchase_created']} purchase invoices added."
        )
    except Exception as ex:
        messages.error(request, f"Sync failed: {ex}")

    return redirect('invoices:dashboard')


@login_required
def link_transaction(request, invoice_pk):
    """Link a bank transaction to an invoice."""
    invoice = get_object_or_404(ERPNextInvoice, pk=invoice_pk, user=request.user)
    txn_id = request.POST.get('transaction_id')
    txn = get_object_or_404(BankTransaction, id=txn_id, user=request.user)

    txn.linked_invoice = invoice
    txn.save(update_fields=['linked_invoice'])

    messages.success(request, f"Transaction linked to {invoice.erp_name}.")
    return redirect('invoices:detail', pk=invoice_pk)


@login_required
def unlink_transaction(request, txn_id):
    """Remove the invoice link from a bank transaction."""
    txn = get_object_or_404(BankTransaction, id=txn_id, user=request.user)
    txn.linked_invoice = None
    txn.save(update_fields=['linked_invoice'])
    messages.success(request, "Invoice link removed.")
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def invoice_search_json(request):
    """
    AJAX endpoint — search invoices by party name or amount.
    Used by the transaction detail page to find matching invoices.
    """
    q = request.GET.get('q', '')
    invoice_type = request.GET.get('type', '')

    invoices = ERPNextInvoice.objects.filter(
        user=request.user,
        erp_status__in=['Unpaid', 'Partly Paid', 'Overdue'],
    )
    if q:
        invoices = invoices.filter(
            Q(party_name__icontains=q) |
            Q(erp_name__icontains=q)
        )
    if invoice_type:
        invoices = invoices.filter(invoice_type=invoice_type)

    data = [
        {
            'id': inv.pk,
            'erp_name': inv.erp_name,
            'party_name': inv.party_name,
            'grand_total': str(inv.grand_total),
            'outstanding_amount': str(inv.outstanding_amount),
            'posting_date': str(inv.posting_date),
            'due_date': str(inv.due_date) if inv.due_date else None,
            'erp_status': inv.erp_status,
            'invoice_type': inv.invoice_type,
        }
        for inv in invoices[:20]
    ]
    return JsonResponse({'results': data})
```

---

## URLs

```python
# apps/invoices/urls.py

from django.urls import path
from . import views

app_name = 'invoices'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('<int:pk>/', views.invoice_detail, name='detail'),
    path('sync/<int:year>/<int:month>/', views.sync_invoices, name='sync'),
    path('<int:invoice_pk>/link/', views.link_transaction, name='link_transaction'),
    path('transactions/<int:txn_id>/unlink/', views.unlink_transaction, name='unlink_transaction'),
    path('search.json', views.invoice_search_json, name='search_json'),
]
```

Register in `LSuite/urls.py`:

```python
path('invoices/', include('apps.invoices.urls', namespace='invoices')),
```

---

## Templates

### `invoices/dashboard.html` (structure)

Key elements:
- Month/period picker to trigger a sync (POST to `invoices:sync`)
- Search bar (filters by party name, invoice number)
- Filter tabs: All / Sales / Purchase / Unpaid / Overdue
- Table columns: Invoice #, Party, Date, Due Date, Total, Outstanding, Status, Actions
- Status badges: Paid (green), Unpaid (yellow), Overdue (red), Partly Paid (blue)
- "View" link per row → `invoices:detail`

### `invoices/detail.html` (structure)

Key elements:
- Invoice header: ERPNext name, party, posting date, due date, total, outstanding, status
- Linked Transactions section: table of bank transactions already linked to this invoice
- Suggested Matches section: transactions with similar amount/date, "Link" button per row
- Manual link form: text input to search all transactions by description or amount

---

## Transaction Detail Integration

On the existing transaction detail page (`/gmail/transactions/<pk>/`), add an Invoice section:

- If `transaction.linked_invoice` exists: show the linked invoice name, party, amount, status + "Unlink" button
- If not linked: show a search box (AJAX to `invoices:search_json`) to find and link an invoice

Template snippet:

```html
<div class="card mt-3">
  <div class="card-header">Invoice</div>
  <div class="card-body">
    {% if transaction.linked_invoice %}
      <p>
        <strong>{{ transaction.linked_invoice.erp_name }}</strong>
        — {{ transaction.linked_invoice.party_name }}
        — R {{ transaction.linked_invoice.grand_total }}
        <span class="badge bg-secondary">{{ transaction.linked_invoice.erp_status }}</span>
      </p>
      <form method="post" action="{% url 'invoices:unlink_transaction' transaction.pk %}">
        {% csrf_token %}
        <button class="btn btn-sm btn-outline-danger">Unlink</button>
      </form>
    {% else %}
      <input type="text" id="invoice-search" class="form-control mb-2"
             placeholder="Search invoices by customer or invoice number...">
      <div id="invoice-results"></div>
    {% endif %}
  </div>
</div>

<script>
const input = document.getElementById('invoice-search');
if (input) {
  input.addEventListener('input', async () => {
    const q = input.value;
    if (q.length < 2) return;
    const resp = await fetch(`/invoices/search.json?q=${encodeURIComponent(q)}`);
    const data = await resp.json();
    const container = document.getElementById('invoice-results');
    container.innerHTML = data.results.map(inv => `
      <div class="d-flex justify-content-between align-items-center border-bottom py-2">
        <div>
          <strong>${inv.erp_name}</strong> — ${inv.party_name}<br>
          <small class="text-muted">R ${inv.grand_total} | ${inv.erp_status} | ${inv.posting_date}</small>
        </div>
        <form method="post" action="/invoices/${inv.id}/link/">
          <input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf_token }}">
          <input type="hidden" name="transaction_id" value="{{ transaction.pk }}">
          <button class="btn btn-sm btn-success">Link</button>
        </form>
      </div>
    `).join('');
  });
}
</script>
```

---

## Management Command: `sync_invoices`

For automated syncing via GitHub Actions (same pattern as `erpnext_sync`):

```python
# apps/invoices/management/commands/sync_invoices.py

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.invoices.services import InvoiceSyncService
from datetime import date


class Command(BaseCommand):
    help = 'Sync invoices from ERPNext for a given period'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=date.today().year)
        parser.add_argument('--month', type=int, default=date.today().month)
        parser.add_argument('--user', type=int, help='Limit to user ID')

    def handle(self, *args, **options):
        year = options['year']
        month = options['month']

        users = User.objects.all()
        if options.get('user'):
            users = users.filter(pk=options['user'])

        for user in users:
            try:
                service = InvoiceSyncService(user)
                results = service.sync_period(year, month)
                self.stdout.write(
                    f"User {user.username}: "
                    f"{results['sales_created']} sales, "
                    f"{results['purchase_created']} purchase invoices added."
                )
            except Exception as ex:
                self.stderr.write(f"User {user.username} failed: {ex}")
```

---

## GitHub Actions Workflow

```yaml
# .github/workflows/sync_invoices.yml

name: Sync Invoices

on:
  workflow_dispatch:
    inputs:
      year:
        description: 'Year (default: current)'
        required: false
      month:
        description: 'Month (default: current)'
        required: false
      user_id:
        description: 'Limit to user ID (optional)'
        required: false

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: |
          ARGS=""
          if [ -n "${{ github.event.inputs.year }}" ]; then
            ARGS="$ARGS --year ${{ github.event.inputs.year }}"
          fi
          if [ -n "${{ github.event.inputs.month }}" ]; then
            ARGS="$ARGS --month ${{ github.event.inputs.month }}"
          fi
          if [ -n "${{ github.event.inputs.user_id }}" ]; then
            ARGS="$ARGS --user ${{ github.event.inputs.user_id }}"
          fi
          python manage.py sync_invoices $ARGS
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          SECRET_KEY: ${{ secrets.SECRET_KEY }}
```

---

## Data Model Summary

| Model | Purpose |
|---|---|
| `ERPNextInvoice` | Local cache of Sales + Purchase invoices pulled from ERPNext |
| `BankTransaction.linked_invoice` | FK linking a payment to the invoice it settles |

---

## URL Structure

```
/invoices/                              → invoice dashboard (list + search)
/invoices/<pk>/                         → invoice detail + linked transactions
/invoices/sync/<year>/<month>/          → trigger ERPNext sync (POST)
/invoices/<invoice_pk>/link/            → link a transaction to this invoice (POST)
/invoices/transactions/<txn_id>/unlink/ → remove invoice link (POST)
/invoices/search.json                   → AJAX search for linking from transaction page
```

---

## Core User Flow

```
1. User goes to /invoices/
2. Picks a month, clicks "Sync from ERPNext"
   → InvoiceSyncService.sync_period() fetches Sales + Purchase invoices
   → Stored locally in ERPNextInvoice

3. User browses invoice list, filters by status/type/party
4. User clicks into an invoice → sees linked transactions + suggested matches

5a. FROM INVOICE:
    User sees suggested bank transactions with similar amount
    → clicks "Link" → transaction.linked_invoice = this invoice

5b. FROM TRANSACTION:
    User is on a bank transaction, searches for the invoice by customer name
    → selects invoice → transaction.linked_invoice = that invoice

6. Invoice shows as linked, transaction shows linked invoice
7. User can unlink at any time from either side
```

---

## Migrations Checklist

```bash
python manage.py makemigrations invoices          # new ERPNextInvoice model
python manage.py makemigrations main              # adds linked_invoice FK to BankTransaction
python manage.py migrate
```

---

## Summary of What Phase 2 Delivers

| Feature | How |
|---|---|
| Pull Sales Invoices from ERPNext | `ERPNextService.fetch_sales_invoices()` → stored as `ERPNextInvoice` |
| Pull Purchase Invoices from ERPNext | `ERPNextService.fetch_purchase_invoices()` → same model, `invoice_type='purchase'` |
| Local invoice cache | `ERPNextInvoice` — upserted on every sync, keeps `raw_data` for full detail |
| Invoice list + search | `/invoices/` — filter by type, status, party name |
| Invoice detail view | `/invoices/<pk>/` — shows line items, linked transactions, suggested matches |
| Link bank transaction → invoice | From invoice detail or from transaction detail page |
| AJAX invoice search | `/invoices/search.json` — used inline on transaction pages |
| Sync management command | `python manage.py sync_invoices --year --month` |
| GitHub Actions sync | Manual trigger + can add cron for nightly sync |

---

## What Phase 2 Does NOT Do

- Does not create invoices in ERPNext
- Does not edit invoice data in ERPNext
- Does not submit or cancel invoices in ERPNext
- Does not automatically mark invoices as paid in ERPNext (that stays in ERPNext)

LSuite is a read + link layer on top of ERPNext's invoice system.
