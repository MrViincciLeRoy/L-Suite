import json
import logging
import os

import requests as http_requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.main.models import (
    BankTransaction,
    ERPNextConfig,
    ERPNextSyncLog,
    TransactionCategory,
)
from apps.erpnext.services import ERPNextService
from .services import (
    BulkSyncService,
    CategorizationService,
    classify_transaction,
    JUNK_CATEGORY_NAMES,
    _get_junk_category_ids,
    _needs_categorization_qs,
)

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 20


def _get_active_config(user=None):
    qs = ERPNextConfig.objects.filter(is_active=True)
    if user:
        qs = qs.filter(user=user)
    return qs.first()


def _active_config_or_error(user=None):
    config = _get_active_config(user)
    if not config:
        return None, JsonResponse(
            {'success': False, 'message': 'No active ERPNext configuration'},
            status=400,
        )
    return config, None


def _paginate(queryset, request, per_page=ITEMS_PER_PAGE):
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get('page', 1)
    try:
        return paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        return paginator.page(1)


def _junk_annotate(transactions, junk_ids_set):
    return [
        {'obj': t, 'is_junk': bool(t.category_id and t.category_id in junk_ids_set)}
        for t in transactions
    ]


def _redirect_back(request, fallback_name):
    return redirect(request.META.get('HTTP_REFERER', reverse(fallback_name)))


def _apply_bulk_sync(config):
    service = BulkSyncService(config)
    return service.sync_all_ready()


def _handle_bulk_sync_result(request, success, failed, total):
    if total == 0:
        messages.info(request, 'No transactions ready to sync.')
    elif failed == 0:
        messages.success(request, f'Synced {success} of {total} transactions!')
    else:
        messages.warning(request, f'Synced {success}, failed {failed} out of {total}.')


# ---------------------------------------------------------------------------
# ERPNext Config views
# ---------------------------------------------------------------------------

@login_required
def configs(request):
    configs = ERPNextConfig.objects.filter(user=request.user)
    return render(request, 'erpnext/configs.html', {'configs': configs})


def _config_from_post(request, instance=None):
    is_active = 'is_active' in request.POST
    fields = dict(
        name=request.POST['name'],
        base_url=request.POST['base_url'],
        api_key=request.POST['api_key'],
        api_secret=request.POST['api_secret'],
        default_company=request.POST.get('default_company', ''),
        bank_account=request.POST.get('bank_account', ''),
        default_cost_center=request.POST.get('default_cost_center', ''),
        is_active=is_active,
    )
    if instance is None:
        return ERPNextConfig(**fields), is_active
    for k, v in fields.items():
        setattr(instance, k, v)
    return instance, is_active


@login_required
def new_config(request):
    if request.method == 'POST':
        config, is_active = _config_from_post(request)
        config.user = request.user
        service = ERPNextService(config)
        success, message = service.test_connection()
        if not success:
            messages.error(request, f'Connection test failed: {message}')
            return render(request, 'erpnext/config_form.html', {'config': config})
        if is_active:
            ERPNextConfig.objects.filter(user=request.user).update(is_active=False)
        config.save()
        messages.success(request, f'Configuration created! {message}')
        return redirect(reverse('erpnext:configs'))
    return render(request, 'erpnext/config_form.html')


@login_required
def edit_config(request, pk):
    config = get_object_or_404(ERPNextConfig, pk=pk, user=request.user)
    if request.method == 'POST':
        config, is_active = _config_from_post(request, instance=config)
        service = ERPNextService(config)
        success, message = service.test_connection()
        if not success:
            messages.warning(request, f'Connection test failed: {message}')
        if is_active:
            ERPNextConfig.objects.filter(user=request.user).exclude(pk=pk).update(is_active=False)
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
        config.save(update_fields=['is_active'])
        messages.success(request, f'"{config.name}" is now active.')
    return redirect(reverse('erpnext:configs'))


# ---------------------------------------------------------------------------
# Sync views
# ---------------------------------------------------------------------------

@login_required
def sync_logs(request):
    logs_qs = (
        ERPNextSyncLog.objects
        .filter(config__user=request.user)
        .select_related('config')
        .order_by('-sync_date')
    )
    page = _paginate(logs_qs, request, per_page=50)
    return render(request, 'erpnext/sync_logs.html', {'logs': page})


@login_required
def sync_transaction(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    if not transaction.category_id:
        return JsonResponse(
            {'success': False, 'message': 'Transaction must be categorized first'}, status=400,
        )
    config, err = _active_config_or_error(user=request.user)
    if err:
        return err
    try:
        service = ERPNextService(config)
        journal_entry_name = service.create_journal_entry(transaction)
        return JsonResponse({
            'success': True,
            'message': f'Synced: {journal_entry_name}',
            'journal_entry': journal_entry_name,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def fetch_accounts(request):
    config, err = _active_config_or_error(user=request.user)
    if err:
        return err
    try:
        raw = ERPNextService(config).get_chart_of_accounts()
        if not raw:
            return JsonResponse(
                {'success': False, 'message': 'No accounts returned from ERPNext. Check company name and API permissions.'},
                status=502,
            )
        accounts = sorted(
            [
                {
                    'name': a['name'],
                    'account_name': a.get('account_name') or a['name'],
                    'account_type': a.get('account_type', ''),
                    'root_type': a.get('root_type', ''),
                    'company': a.get('company', ''),
                    'is_group': bool(a.get('is_group')),
                }
                for a in raw
            ],
            key=lambda x: (x['root_type'], x['name']),
        )
        return JsonResponse({'success': True, 'accounts': accounts, 'count': len(accounts)})
    except Exception as e:
        logger.error(f"fetch_accounts error: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def fetch_cost_centers(request):
    config, err = _active_config_or_error(user=request.user)
    if err:
        return err
    try:
        cost_centers = ERPNextService(config).get_cost_centers()
        return JsonResponse({'success': True, 'cost_centers': cost_centers})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ---------------------------------------------------------------------------
# Category views
# ---------------------------------------------------------------------------

@login_required
def categories(request):
    cats = TransactionCategory.objects.order_by('name')
    categories_with_stats = [
        (c, {
            'total': c.transactions.count(),
            'synced': c.transactions.filter(erpnext_synced=True).count(),
            'pending': c.transactions.filter(erpnext_synced=False).count(),
            'is_junk': c.name.strip().lower() in JUNK_CATEGORY_NAMES,
        })
        for c in cats
    ]
    active_config = ERPNextConfig.objects.filter(user=request.user, is_active=True).first()
    any_config = active_config or ERPNextConfig.objects.filter(
        user=request.user
    ).order_by('-created_at').first()
    return render(request, 'bridge/categories.html', {
        'categories_with_stats': categories_with_stats,
        'erpnext_config': active_config,
        'any_erpnext_config': any_config,
    })


def _category_fields_from_post(request):
    return dict(
        name=request.POST['name'],
        erpnext_account=request.POST['erpnext_account'],
        transaction_type=request.POST['transaction_type'],
        keywords=request.POST.get('keywords', ''),
        tags=request.POST.get('tags', ''),
        active=request.POST.get('active', 'true') == 'true',
        color=request.POST.get('color') or None,
    )


@login_required
def new_category(request):
    if request.method == 'POST':
        TransactionCategory.objects.create(**_category_fields_from_post(request))
        messages.success(request, 'Category created.')
        return redirect(reverse('bridge:categories'))
    return render(request, 'bridge/category_form.html')


@login_required
def edit_category(request, pk):
    category = get_object_or_404(TransactionCategory, pk=pk)
    if request.method == 'POST':
        for k, v in _category_fields_from_post(request).items():
            setattr(category, k, v)
        category.save()
        messages.success(request, 'Category updated.')
        return redirect(reverse('bridge:categories'))
    return render(request, 'bridge/category_form.html', {'category': category})


@login_required
def delete_category(request, pk):
    category = get_object_or_404(TransactionCategory, pk=pk)
    if request.method == 'POST':
        count = category.transactions.count()
        if count > 0:
            messages.warning(request, f'Cannot delete: {count} transactions use this category.')
            return redirect(reverse('bridge:categories'))
        category.delete()
        messages.success(request, 'Category deleted.')
    return redirect(reverse('bridge:categories'))


@login_required
def category_transactions(request, pk):
    category = get_object_or_404(TransactionCategory, pk=pk)
    page = _paginate(category.transactions.order_by('-date'), request)
    return render(request, 'bridge/category_transactions.html', {
        'category': category,
        'transactions': page,
        'is_junk': category.name.strip().lower() in JUNK_CATEGORY_NAMES,
    })


# ---------------------------------------------------------------------------
# Categorization views
# ---------------------------------------------------------------------------

@login_required
def auto_categorize(request):
    if request.method == 'POST':
        service = CategorizationService()
        try:
            categorized, total = service.auto_categorize_all()
            if categorized > 0:
                messages.success(request, f'Categorized {categorized} of {total} transactions.')
            else:
                messages.info(request, 'No transactions could be auto-categorized.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
    return redirect(reverse('bridge:bulk_operations'))


@login_required
def auto_categorize_ai(request):
    if request.method != 'POST':
        return redirect(reverse('bridge:bulk_operations'))
    gh_token = os.environ.get('GH_TOKEN', '')
    gh_repo = os.environ.get('GH_REPO', '')
    if not gh_token or not gh_repo:
        messages.error(request, 'GH_TOKEN or GH_REPO not configured on this server.')
        return redirect(reverse('bridge:bulk_operations'))
    try:
        resp = http_requests.post(
            f'https://api.github.com/repos/{gh_repo}/actions/workflows/ai_categorize.yml/dispatches',
            headers={
                'Authorization': f'Bearer {gh_token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            json={'ref': 'main'},
            timeout=10,
        )
        if resp.status_code == 204:
            messages.success(request, 'AI categorization job dispatched to GitHub Actions.')
        else:
            messages.error(request, f'GitHub API error {resp.status_code}: {resp.text[:300]}')
    except Exception as e:
        messages.error(request, f'Failed to dispatch job: {e}')
    return redirect(reverse('bridge:bulk_operations'))


@login_required
def preview_categorization(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    service = CategorizationService()
    preview = service.preview_categorization()
    return JsonResponse({
        'total_uncategorized': len(preview['uncategorized']),
        'will_be_categorized': len(preview['matches']),
        'no_match': len(preview['no_match']),
        'matches': [
            {
                'transaction_id': m['transaction'].id,
                'description': m['transaction'].description[:50],
                'category': m['category'].name,
                'keyword': m['keyword'],
            }
            for m in preview['matches'][:20]
        ],
    })


@login_required
def classify_single(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    raw = body.get('transaction', '').strip()
    if not raw:
        return JsonResponse({'error': 'transaction field required'}, status=400)
    return JsonResponse(classify_transaction(raw))


@login_required
def categorize_transaction(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    if request.method == 'POST':
        category_id = request.POST.get('category_id')
        if not category_id:
            messages.warning(request, 'Please select a category.')
            return _redirect_back(request, 'gmail:transactions')
        category = get_object_or_404(TransactionCategory, pk=category_id)
        transaction.category = category
        transaction.save()
        if transaction.description and hasattr(category, 'add_tag'):
            first_word = transaction.description.split()[0].lower().strip('*').strip()
            if len(first_word) > 2:
                category.add_tag(first_word)
        messages.success(request, f'Categorized as "{category.name}".')
    return _redirect_back(request, 'gmail:transactions')


@login_required
def uncategorize_transaction(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    if request.method == 'POST':
        if transaction.erpnext_synced:
            messages.warning(request, 'Cannot uncategorize a synced transaction.')
            return _redirect_back(request, 'gmail:transactions')
        transaction.category = None
        transaction.save()
        messages.info(request, 'Transaction uncategorized.')
    return _redirect_back(request, 'gmail:transactions')


# ---------------------------------------------------------------------------
# Bulk operation views
# ---------------------------------------------------------------------------

@login_required
def bulk_operations(request):
    junk_ids = _get_junk_category_ids()
    junk_ids_set = set(junk_ids)
    needs_cat_count = _needs_categorization_qs().count()
    stats = {
        'total': BankTransaction.objects.count(),
        'uncategorized': needs_cat_count,
        'categorized': (
            BankTransaction.objects
            .filter(category__isnull=False)
            .exclude(category_id__in=junk_ids)
            .count()
        ),
        'synced': BankTransaction.objects.filter(erpnext_synced=True).count(),
        'ready_to_sync': (
            BankTransaction.objects
            .filter(category__isnull=False, erpnext_synced=False)
            .exclude(category_id__in=junk_ids)
            .count()
        ),
        'junk_categorized': (
            BankTransaction.objects
            .filter(category_id__in=junk_ids, erpnext_synced=False)
            .count()
            if junk_ids else 0
        ),
        'truly_null': (
            BankTransaction.objects
            .filter(category__isnull=True, erpnext_synced=False)
            .count()
        ),
    }
    return render(request, 'bridge/bulk_operations.html', {
        'stats': stats,
        'erpnext_config': _get_active_config(),
        'recent_transactions': _junk_annotate(
            BankTransaction.objects.order_by('-date')[:10], junk_ids_set,
        ),
        'needs_categorizing': _junk_annotate(
            list(_needs_categorization_qs().order_by('-date')), junk_ids_set,
        ),
    })


@login_required
def bulk_sync(request):
    if request.method == 'POST':
        config = _get_active_config()
        if not config:
            messages.error(request, 'No active ERPNext configuration found.')
            return redirect(reverse('bridge:bulk_operations'))
        try:
            success, failed, total = _apply_bulk_sync(config)
            _handle_bulk_sync_result(request, success, failed, total)
        except Exception as e:
            messages.error(request, f'Sync error: {e}')
    return redirect(reverse('bridge:bulk_operations'))


def _unaccounted_categories(junk_ids):
    base_filter = dict(transactions__erpnext_synced=False)

    def _pending_qs(**extra_filter):
        return (
            TransactionCategory.objects
            .filter(**base_filter, **extra_filter)
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


@login_required
def sync_preflight(request):
    config = _get_active_config()
    if not config:
        messages.error(request, 'No active ERPNext configuration found.')
        return redirect(reverse('bridge:bulk_operations'))

    junk_ids = _get_junk_category_ids()
    missing_cats = _unaccounted_categories(junk_ids)

    if request.method == 'POST':
        updated = 0
        for cat in missing_cats:
            account = request.POST.get(f'account_{cat.pk}', '').strip()
            if account:
                cat.erpnext_account = account
                cat.save(update_fields=['erpnext_account'])
                updated += 1

        if updated:
            messages.success(
                request,
                f'Saved ERPNext accounts for {updated} categor{"y" if updated == 1 else "ies"}.',
            )

        still_missing = [
            c for c in missing_cats
            if not request.POST.get(f'account_{c.pk}', '').strip()
        ]
        if still_missing and not request.POST.get('skip_missing'):
            messages.warning(
                request,
                f'{len(still_missing)} categories still have no account ? their transactions will be skipped.',
            )
        return redirect(reverse('bridge:bulk_sync_post'))

    ready_count = (
        BankTransaction.objects
        .filter(
            category__isnull=False,
            erpnext_synced=False,
            category__erpnext_account__isnull=False,
        )
        .exclude(category__erpnext_account='')
        .exclude(category_id__in=junk_ids)
        .count()
    )

    return render(request, 'bridge/sync_preflight.html', {
        'config': config,
        'missing_cats': missing_cats,
        'ready_count': ready_count,
    })


@login_required
def bulk_sync_post(request):
    config = _get_active_config()
    if not config:
        messages.error(request, 'No active ERPNext configuration.')
        return redirect(reverse('bridge:bulk_operations'))
    try:
        success, failed, total = _apply_bulk_sync(config)
        _handle_bulk_sync_result(request, success, failed, total)
    except Exception as e:
        messages.error(request, f'Sync error: {e}')
    return redirect(reverse('bridge:bulk_operations'))