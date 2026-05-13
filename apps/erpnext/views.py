import json
import logging
import os

import requests as http_requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.main.models import ERPNextConfig, ERPNextSyncLog, BankTransaction, TransactionCategory
from .services import ERPNextService

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _active_config(user):
    return ERPNextConfig.objects.filter(user=user, is_active=True).first()


def _apply_bulk_sync(config):
    from apps.bridge.services import BulkSyncService
    return BulkSyncService(config).sync_all_ready()


def _handle_bulk_sync_result(request, success, failed, total):
    if total == 0:
        messages.info(request, 'No transactions ready to sync.')
    elif failed == 0:
        messages.success(request, f'Synced {success} of {total} transactions!')
    else:
        messages.warning(request, f'Synced {success}, failed {failed} out of {total}.')


def _get_junk_category_ids():
    from apps.bridge.services import _get_junk_category_ids as _junk
    return _junk()


def _unaccounted_categories(junk_ids):
    base_filter = dict(transactions__erpnext_synced=False)

    def _pending_qs(**extra):
        return (
            TransactionCategory.objects
            .filter(**base_filter, **extra)
            .exclude(id__in=junk_ids)
            .annotate(pending_count=Count('transactions'))
            .filter(pending_count__gt=0)
            .distinct()
        )

    cat_map = {
        c.pk: c
        for c in list(_pending_qs(erpnext_account__isnull=True))
               + list(_pending_qs(erpnext_account=''))
    }
    return sorted(cat_map.values(), key=lambda c: c.name)


def _dispatch_gh_actions(workflow_file='erpnext_sync.yml'):
    gh_token = os.environ.get('GH_TOKEN', '')
    gh_repo = os.environ.get('GH_REPO', '')
    if not gh_token or not gh_repo:
        return False, 'GH_TOKEN or GH_REPO not set.'
    try:
        resp = http_requests.post(
            f'https://api.github.com/repos/{gh_repo}/actions/workflows/{workflow_file}/dispatches',
            headers={
                'Authorization': f'Bearer {gh_token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            json={'ref': 'main'},
            timeout=10,
        )
        if resp.status_code == 204:
            return True, None
        return False, f'GitHub API {resp.status_code}: {resp.text[:300]}'
    except Exception as e:
        return False, str(e)


# ── Config CRUD ───────────────────────────────────────────────────────────────

@login_required
def configs(request):
    configs = ERPNextConfig.objects.filter(user=request.user)
    return render(request, 'erpnext/configs.html', {'configs': configs})


@login_required
def new_config(request):
    if request.method == 'POST':
        config = ERPNextConfig(
            user=request.user,
            name=request.POST['name'],
            base_url=request.POST['base_url'],
            api_key=request.POST['api_key'],
            api_secret=request.POST['api_secret'],
            default_company=request.POST.get('default_company', ''),
            bank_account=request.POST.get('bank_account', ''),
            default_cost_center=request.POST.get('default_cost_center', ''),
            is_active='is_active' in request.POST,
        )
        service = ERPNextService(config)
        success, message = service.test_connection()
        if not success:
            messages.error(request, f'Connection test failed: {message}')
            return render(request, 'erpnext/config_form.html', {'config': config})
        config.save()
        messages.success(request, f'Configuration created! {message}')
        return redirect(reverse('erpnext:configs'))
    return render(request, 'erpnext/config_form.html')


@login_required
def edit_config(request, pk):
    config = get_object_or_404(ERPNextConfig, pk=pk, user=request.user)
    if request.method == 'POST':
        config.name                = request.POST['name']
        config.base_url            = request.POST['base_url']
        config.api_key             = request.POST['api_key']
        config.api_secret          = request.POST['api_secret']
        config.default_company     = request.POST.get('default_company', '')
        config.bank_account        = request.POST.get('bank_account', '')
        config.default_cost_center = request.POST.get('default_cost_center', '')
        config.is_active           = 'is_active' in request.POST
        service = ERPNextService(config)
        success, message = service.test_connection()
        if not success:
            messages.warning(request, f'Connection test failed: {message}')
        config.save()
        messages.success(request, 'Configuration updated!')
        return redirect(reverse('erpnext:configs'))
    return render(request, 'erpnext/config_form.html', {'config': config})


@login_required
def delete_config(request, pk):
    config = get_object_or_404(ERPNextConfig, pk=pk, user=request.user)
    if request.method == 'POST':
        config.delete()
        messages.success(request, 'Configuration deleted.')
    return redirect(reverse('erpnext:configs'))


@login_required
def test_config(request, pk):
    config = get_object_or_404(ERPNextConfig, pk=pk, user=request.user)
    service = ERPNextService(config)
    success, message = service.test_connection()
    return JsonResponse({'success': success, 'message': message})


@login_required
def activate_config(request, pk):
    config = get_object_or_404(ERPNextConfig, pk=pk, user=request.user)
    if request.method == 'POST':
        ERPNextConfig.objects.filter(user=request.user).update(is_active=False)
        config.is_active = True
        config.save()
        messages.success(request, f'"{config.name}" is now active.')
    return redirect(reverse('erpnext:configs'))


# ── Sync logs ─────────────────────────────────────────────────────────────────

@login_required
def sync_logs(request):
    logs_qs = ERPNextSyncLog.objects.filter(
        config__user=request.user
    ).select_related('config').order_by('-sync_date')
    page = Paginator(logs_qs, 50).get_page(request.GET.get('page', 1))
    return render(request, 'erpnext/sync_logs.html', {'logs': page})


@login_required
def sync_transaction(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    if not transaction.category_id:
        return JsonResponse({'success': False, 'message': 'Transaction must be categorized first'}, status=400)
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No active ERPNext configuration'}, status=400)
    try:
        journal = ERPNextService(config).create_journal_entry(transaction)
        return JsonResponse({'success': True, 'message': f'Synced: {journal}', 'journal_entry': journal})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ── Data-fetch endpoints ──────────────────────────────────────────────────────

@login_required
def fetch_accounts(request):
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No active ERPNext configuration'}, status=400)
    try:
        raw = ERPNextService(config).get_chart_of_accounts()
        if not raw:
            return JsonResponse({'success': False, 'message': 'No accounts returned.'}, status=502)
        accounts = sorted(
            [{'name': a['name'], 'account_name': a.get('account_name') or a['name'],
              'account_type': a.get('account_type', ''), 'root_type': a.get('root_type', ''),
              'company': a.get('company', ''), 'is_group': bool(a.get('is_group'))} for a in raw],
            key=lambda x: (x['root_type'], x['name']),
        )
        return JsonResponse({'success': True, 'accounts': accounts, 'count': len(accounts)})
    except Exception as e:
        logger.error(f"fetch_accounts error: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def fetch_cost_centers(request):
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No active ERPNext configuration'}, status=400)
    try:
        cost_centers = ERPNextService(config).get_cost_centers()
        return JsonResponse({'success': True, 'cost_centers': cost_centers})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def fetch_companies(request):
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No active ERPNext configuration'}, status=400)
    try:
        companies = ERPNextService(config).get_companies()
        return JsonResponse({'success': True, 'companies': companies})
    except Exception as e:
        logger.error(f"fetch_companies error: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def update_config_defaults(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required'}, status=405)
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No active ERPNext configuration'}, status=400)
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    company     = body.get('company', '').strip()
    bank        = body.get('bank_account', '').strip()
    cost_center = body.get('cost_center', '').strip()

    if not company:
        return JsonResponse({'success': False, 'message': 'Company is required'}, status=400)
    if not bank:
        return JsonResponse({'success': False, 'message': 'Bank account is required'}, status=400)

    service = ERPNextService(config)
    companies = service.get_companies()
    resolved_company = company
    for c in companies:
        if c.get('name') == company:
            break
        if c.get('abbr', '').strip().upper() == company.upper():
            resolved_company = c['name']
            break

    config.default_company     = resolved_company
    config.bank_account        = bank
    config.default_cost_center = cost_center
    config.save(update_fields=['default_company', 'bank_account', 'default_cost_center'])

    note = f" (resolved from '{company}')" if resolved_company != company else ""
    return JsonResponse({
        'success': True,
        'message': f'Defaults saved. Company: {resolved_company}{note}',
        'resolved_company': resolved_company,
    })


# ── Preflight → save DB → dispatch GH Actions ────────────────────────────────

@login_required
def sync_preflight(request):
    config = _active_config(request.user)
    if not config:
        messages.error(request, 'No active ERPNext configuration found.')
        return redirect(reverse('bridge:bulk_operations'))

    junk_ids = _get_junk_category_ids()
    missing_cats = _unaccounted_categories(junk_ids)

    if request.method == 'POST':
        # 1. Save config overrides
        config_fields = []
        for field, post_key in [
            ('default_company', 'config_company'),
            ('bank_account', 'config_bank_account'),
            ('default_cost_center', 'config_cost_center'),
        ]:
            val = request.POST.get(post_key, '').strip()
            if val and val != getattr(config, field):
                setattr(config, field, val)
                config_fields.append(field)
        if config_fields:
            config.save(update_fields=config_fields)

        # 2. Save category account assignments
        updated_cats = 0
        for cat in missing_cats:
            account = request.POST.get(f'account_{cat.pk}', '').strip()
            if account:
                cat.erpnext_account = account
                cat.save(update_fields=['erpnext_account'])
                updated_cats += 1

        # 3. Warn about still-missing categories (unless user opted to skip)
        still_missing = [
            c for c in missing_cats
            if not request.POST.get(f'account_{c.pk}', '').strip()
        ]
        if still_missing and not request.POST.get('skip_missing'):
            messages.warning(
                request,
                f'{len(still_missing)} categor{"y" if len(still_missing) == 1 else "ies"} '
                f'still have no ERPNext account — their transactions will be skipped.',
            )

        # 4. Dispatch GH Actions workflow
        ok, err = _dispatch_gh_actions('erpnext_sync.yml')
        if ok:
            messages.success(
                request,
                f'DB saved ({updated_cats} categor{"y" if updated_cats == 1 else "ies"} updated). '
                'ERPNext sync job dispatched to GitHub Actions.',
            )
            return redirect(reverse('erpnext:sync_job_status'))
        else:
            messages.error(request, f'DB saved but GH dispatch failed: {err}')
            return redirect(reverse('bridge:bulk_operations'))

    # GET — render the form
    ready_count = (
        BankTransaction.objects
        .filter(category__isnull=False, erpnext_synced=False, category__erpnext_account__isnull=False)
        .exclude(category__erpnext_account='')
        .exclude(category_id__in=junk_ids)
        .count()
    )
    return render(request, 'erpnext/sync_preflight.html', {
        'config': config,
        'missing_cats': missing_cats,
        'ready_count': ready_count,
    })


@login_required
def sync_job_status(request):
    gh_token = os.environ.get('GH_TOKEN', '')
    gh_repo  = os.environ.get('GH_REPO', '')
    return render(request, 'erpnext/sync_job_status.html', {
        'gh_repo': gh_repo,
        'has_gh': bool(gh_token and gh_repo),
    })


@login_required
def sync_job_status_api(request):
    """Proxy the GH Actions run list so we don't expose the token to the browser."""
    gh_token = os.environ.get('GH_TOKEN', '')
    gh_repo  = os.environ.get('GH_REPO', '')
    if not gh_token or not gh_repo:
        return JsonResponse({'error': 'GH not configured'}, status=400)
    try:
        resp = http_requests.get(
            f'https://api.github.com/repos/{gh_repo}/actions/workflows/erpnext_sync.yml/runs',
            headers={
                'Authorization': f'Bearer {gh_token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            params={'per_page': 1},
            timeout=10,
        )
        resp.raise_for_status()
        runs = resp.json().get('workflow_runs', [])
        if not runs:
            return JsonResponse({'status': 'no_runs'})
        run = runs[0]
        return JsonResponse({
            'status':      run.get('status'),       # queued / in_progress / completed
            'conclusion':  run.get('conclusion'),   # success / failure / cancelled / None
            'run_id':      run.get('id'),
            'html_url':    run.get('html_url'),
            'created_at':  run.get('created_at'),
            'updated_at':  run.get('updated_at'),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def bulk_sync_post(request):
    """Direct (non-GH-Actions) sync — kept for backward compat / manual use."""
    config = _active_config(request.user)
    if not config:
        messages.error(request, 'No active ERPNext configuration.')
        return redirect(reverse('bridge:bulk_operations'))
    try:
        success, failed, total = _apply_bulk_sync(config)
        _handle_bulk_sync_result(request, success, failed, total)
    except Exception as e:
        messages.error(request, f'Sync error: {e}')
    return redirect(reverse('bridge:bulk_operations'))
