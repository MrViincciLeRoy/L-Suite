import csv
from calendar import month_name, monthrange
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.main.models import BankTransaction, ERPNextConfig
from apps.erpnext.services import ERPNextService
from .models import ERPNextJournalEntry, ReconciliationMatch, ReconciliationPeriod
from .engine import run_matching

@login_required
def dashboard(request):
    periods = ReconciliationPeriod.objects.filter(user=request.user).order_by('-year', '-month')

    # Find all months that have bank transactions for this user
    from django.db.models import Min, Max
    from apps.main.models import BankTransaction
    import calendar

    txn_months = (
        BankTransaction.objects
        .filter(user=request.user)
        .dates('date', 'month', order='DESC')  # returns first day of each month
    )

    today = date.today()
    return render(request, 'reconciliation/dashboard.html', {
        'periods': periods,
        'today': today,
        'txn_months': txn_months,
    })


@login_required
def fetch_journal_entries(request, year, month):
    config = ERPNextConfig.objects.filter(user=request.user, is_active=True).first()
    if not config:
        messages.error(request, 'No active ERPNext configuration.')
        return redirect('reconciliation:period_detail', year=year, month=month)

    _, last_day = monthrange(year, month)
    from_date = date(year, month, 1).isoformat()
    to_date = date(year, month, last_day).isoformat()

    try:
        service = ERPNextService(config)
        # Uses the existing fetch_journal_entries from erpnext/services.py
        # Returns list of JE dicts: name, posting_date, total_debit, remark, cheque_no
        entries = service.fetch_journal_entries(from_date, to_date)
        created = 0
        for e in entries:
            # total_debit is the amount on the JE — what we match against
            amount = e.get('total_debit') or e.get('total_credit') or 0
            _, new = ERPNextJournalEntry.objects.get_or_create(
                user=request.user,
                je_name=e['name'],
                defaults={
                    'posting_date': e.get('posting_date', from_date),
                    'amount': amount,
                    'account': '',
                    'reference_number': e.get('cheque_no', '') or e.get('user_remark', ''),
                    'remark': e.get('remark', '') or e.get('user_remark', ''),
                },
            )
            if new:
                created += 1
        messages.success(request, f"Fetched {len(entries)} journal entries ({created} new).")
    except Exception as ex:
        messages.error(request, f"ERPNext fetch failed: {ex}")

    return redirect('reconciliation:period_detail', year=year, month=month)


@login_required
def run_match(request, year, month):
    period = ReconciliationPeriod.objects.filter(
        user=request.user, year=year, month=month, status='closed'
    ).first()
    if period:
        messages.error(request, 'Period is closed — re-matching is not allowed.')
        return redirect('reconciliation:period_detail', year=year, month=month)

    results = run_matching(request.user, year, month)
    period, _ = ReconciliationPeriod.objects.get_or_create(
        user=request.user, year=year, month=month, defaults={'status': 'open'}
    )
    _refresh_period_counts(period)
    messages.success(
        request,
        f"Matching complete — {results['matched']} matched, {results['flagged']} flagged.",
    )
    return redirect('reconciliation:period_detail', year=year, month=month)


@login_required
def period_detail(request, year, month):
    period, _ = ReconciliationPeriod.objects.get_or_create(
        user=request.user, year=year, month=month, defaults={'status': 'open'}
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

    je_count = ERPNextJournalEntry.objects.filter(
        user=request.user,
        posting_date__year=year,
        posting_date__month=month,
    ).count()

    return render(request, 'reconciliation/period_detail.html', {
        'period': period,
        'transactions': transactions,
        'status_filter': status_filter,
        'month_label': f"{month_name[month]} {year}",
        'je_count': je_count,
    })


@login_required
def close_period(request, year, month):
    period = get_object_or_404(ReconciliationPeriod, user=request.user, year=year, month=month)
    _refresh_period_counts(period)
    if not period.can_close():
        messages.error(request, 'Cannot close — unreconciled or flagged transactions remain.')
        return redirect('reconciliation:period_detail', year=year, month=month)
    period.status = 'closed'
    period.closed_at = timezone.now()
    period.save()
    messages.success(request, f'{period.label()} closed.')
    return redirect('reconciliation:dashboard')


@login_required
def reopen_period(request, year, month):
    period = get_object_or_404(ReconciliationPeriod, user=request.user, year=year, month=month)
    if request.method == 'POST':
        period.status = 'open'
        period.closed_at = None
        period.save()
        messages.success(request, f'{period.label()} reopened.')
    return redirect('reconciliation:period_detail', year=year, month=month)


@login_required
def manual_match(request, txn_id):
    if request.method != 'POST':
        return redirect('reconciliation:dashboard')
    txn = get_object_or_404(BankTransaction, id=txn_id, user=request.user)
    je_id = request.POST.get('journal_entry_id')
    if not je_id:
        messages.error(request, 'Select a journal entry.')
        return redirect(request.META.get('HTTP_REFERER', '/'))
    je = get_object_or_404(ERPNextJournalEntry, id=je_id, user=request.user)
    ReconciliationMatch.objects.update_or_create(
        transaction=txn,
        defaults={
            'user': request.user,
            'journal_entry': je,
            'status': 'manual',
            'flag_reason': '',
            'matched_by': 'manual',
        },
    )
    txn.recon_status = 'matched'
    txn.save(update_fields=['recon_status'])
    messages.success(request, 'Transaction manually matched.')
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def unmatch_transaction(request, txn_id):
    if request.method != 'POST':
        return redirect('reconciliation:dashboard')
    txn = get_object_or_404(BankTransaction, id=txn_id, user=request.user)
    ReconciliationMatch.objects.filter(transaction=txn).delete()
    txn.recon_status = 'unreconciled'
    txn.save(update_fields=['recon_status'])
    messages.success(request, 'Match removed — transaction is unreconciled.')
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
    writer.writerow(['Date', 'Description', 'Amount', 'Type', 'Recon Status', 'Matched JE', 'Flag Reason'])
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
@login_required
def debug_journal_entries(request):
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'error': 'No active ERPNext config'}, status=400)

    year  = int(request.GET.get('year', 2025))
    month = int(request.GET.get('month', 12))

    from calendar import monthrange
    from datetime import date
    _, last_day = monthrange(year, month)
    from_date = date(year, month, 1).isoformat()
    to_date   = date(year, month, last_day).isoformat()

    service = ERPNextService(config)
    headers = service._get_headers()
    base_url = service.base_url

    # Try the raw request so we can see the full response
    import requests
    url = f"{base_url}/api/resource/Journal Entry"
    params = {
        'fields': '["name","posting_date","total_debit","total_credit","remark","cheque_no","user_remark","docstatus"]',
        'filters': f'[["posting_date",">=","{from_date}"],["posting_date","<=","{to_date}"]]',
        'limit_page_length': 20,
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        raw = resp.json()
    except Exception as e:
        raw = {'exception': str(e)}

    # Also try without docstatus filter (original has docstatus=1 which means submitted only)
    params2 = dict(params)
    params2['filters'] = f'[["posting_date",">=","{from_date}"],["posting_date","<=","{to_date}"],["docstatus","in","0,1,2"]]'
    try:
        resp2 = requests.get(url, headers=headers, params=params2, timeout=30)
        raw2 = resp2.json()
    except Exception as e:
        raw2 = {'exception': str(e)}

    return JsonResponse({
        'config': {
            'base_url': base_url,
            'company': config.default_company,
        },
        'date_range': {'from': from_date, 'to': to_date},
        'submitted_only_count': len(raw.get('data', [])),
        'submitted_only_sample': raw.get('data', [])[:3],
        'all_statuses_count': len(raw2.get('data', [])),
        'all_statuses_sample': raw2.get('data', [])[:3],
        'raw_error': raw.get('exc') or raw.get('exception'),
    }, json_dumps_params={'indent': 2})

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
    period.save(update_fields=['total_transactions', 'matched_count', 'flagged_count', 'unreconciled_count'])