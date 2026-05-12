import os
import requests as http_requests

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from apps.main.models import TransactionCategory, BankTransaction, ERPNextConfig
from .services import (
    CategorizationService, BulkSyncService, classify_transaction,
    JUNK_CATEGORY_NAMES, _get_junk_category_ids, _needs_categorization_qs,
)

ITEMS_PER_PAGE = 20


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
    return render(request, 'bridge/categories.html', {
        'categories_with_stats': categories_with_stats,
    })


@login_required
def new_category(request):
    if request.method == 'POST':
        TransactionCategory.objects.create(
            name=request.POST['name'],
            erpnext_account=request.POST['erpnext_account'],
            transaction_type=request.POST['transaction_type'],
            keywords=request.POST.get('keywords', ''),
            tags=request.POST.get('tags', ''),
            active=request.POST.get('active', 'true') == 'true',
            color=request.POST.get('color') or None,
        )
        messages.success(request, 'Category created.')
        return redirect(reverse('bridge:categories'))
    return render(request, 'bridge/category_form.html')


@login_required
def edit_category(request, pk):
    category = get_object_or_404(TransactionCategory, pk=pk)
    if request.method == 'POST':
        category.name = request.POST['name']
        category.erpnext_account = request.POST['erpnext_account']
        category.transaction_type = request.POST['transaction_type']
        category.keywords = request.POST.get('keywords', '')
        category.tags = request.POST.get('tags', '')
        category.active = request.POST.get('active', 'true') == 'true'
        category.color = request.POST.get('color') or None
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
    txns_qs = category.transactions.order_by('-date')
    paginator = Paginator(txns_qs, ITEMS_PER_PAGE)
    page_number = request.GET.get('page', 1)
    try:
        page = paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        page = paginator.page(1)
    return render(request, 'bridge/category_transactions.html', {
        'category': category,
        'transactions': page,
        'is_junk': category.name.strip().lower() in JUNK_CATEGORY_NAMES,
    })


@login_required
def auto_categorize(request):
    if request.method == 'POST':
        service = CategorizationService()
        try:
            categorized, total = service.auto_categorize_all()
            if categorized > 0:
                messages.success(request, f'Categorized {categorized} of {total} transactions.')
            else:
                messages.info(request, 'No transactions could be auto-categorized. Add keywords to categories.')
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
            messages.success(request, 'AI categorization job dispatched to GitHub Actions. Check back in ~2 minutes.')
        else:
            messages.error(request, f'GitHub API error {resp.status_code}: {resp.text[:300]}')
    except Exception as e:
        messages.error(request, f'Failed to dispatch job: {e}')

    return redirect(reverse('bridge:bulk_operations'))


@login_required
def preview_categorization(request):
    if request.method == 'POST':
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
    return JsonResponse({'error': 'POST required'}, status=405)


@login_required
def classify_single(request):
    if request.method == 'POST':
        import json
        try:
            body = json.loads(request.body)
        except Exception:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        raw = body.get('transaction', '').strip()
        if not raw:
            return JsonResponse({'error': 'transaction field required'}, status=400)
        result = classify_transaction(raw)
        return JsonResponse(result)
    return JsonResponse({'error': 'POST required'}, status=405)


@login_required
def categorize_transaction(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    if request.method == 'POST':
        category_id = request.POST.get('category_id')
        if not category_id:
            messages.warning(request, 'Please select a category.')
            return redirect(request.META.get('HTTP_REFERER', reverse('gmail:transactions')))
        category = get_object_or_404(TransactionCategory, pk=category_id)
        transaction.category = category
        transaction.save()
        if transaction.description and hasattr(category, 'add_tag'):
            first_word = transaction.description.split()[0].lower().strip('*').strip()
            if len(first_word) > 2:
                category.add_tag(first_word)
        messages.success(request, f'Categorized as "{category.name}".')
    return redirect(request.META.get('HTTP_REFERER', reverse('gmail:transactions')))


@login_required
def uncategorize_transaction(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    if request.method == 'POST':
        if transaction.erpnext_synced:
            messages.warning(request, 'Cannot uncategorize a synced transaction.')
            return redirect(request.META.get('HTTP_REFERER', reverse('gmail:transactions')))
        transaction.category = None
        transaction.save()
        messages.info(request, 'Transaction uncategorized.')
    return redirect(request.META.get('HTTP_REFERER', reverse('gmail:transactions')))


@login_required
def bulk_operations(request):
    junk_ids = _get_junk_category_ids()
    junk_ids_set = set(junk_ids)

    needs_cat_count = _needs_categorization_qs().count()

    categorized_count = BankTransaction.objects.filter(
        category__isnull=False,
    ).exclude(category_id__in=junk_ids).count()

    ready_to_sync_count = BankTransaction.objects.filter(
        category__isnull=False,
        erpnext_synced=False,
    ).exclude(category_id__in=junk_ids).count()

    stats = {
        'total': BankTransaction.objects.count(),
        'uncategorized': needs_cat_count,
        'categorized': categorized_count,
        'synced': BankTransaction.objects.filter(erpnext_synced=True).count(),
        'ready_to_sync': ready_to_sync_count,
        'junk_categorized': BankTransaction.objects.filter(
            category_id__in=junk_ids,
            erpnext_synced=False,
        ).count() if junk_ids else 0,
        'truly_null': BankTransaction.objects.filter(
            category__isnull=True,
            erpnext_synced=False,
        ).count(),
    }

    erpnext_config = ERPNextConfig.objects.filter(is_active=True).first()

    raw_recent = BankTransaction.objects.order_by('-date')[:10]
    recent_transactions = [
        {
            'obj': t,
            'is_junk': bool(t.category_id and t.category_id in junk_ids_set),
        }
        for t in raw_recent
    ]

    raw_needs_cat = list(_needs_categorization_qs().order_by('-date'))
    needs_categorizing = [
        {
            'obj': t,
            'is_junk': bool(t.category_id and t.category_id in junk_ids_set),
        }
        for t in raw_needs_cat
    ]

    return render(request, 'bridge/bulk_operations.html', {
        'stats': stats,
        'erpnext_config': erpnext_config,
        'recent_transactions': recent_transactions,
        'needs_categorizing': needs_categorizing,
    })


@login_required
def bulk_sync(request):
    if request.method == 'POST':
        config = ERPNextConfig.objects.filter(is_active=True).first()
        if not config:
            messages.error(request, 'No active ERPNext configuration found.')
            return redirect(reverse('bridge:bulk_operations'))
        service = BulkSyncService(config)
        try:
            success, failed, total = service.sync_all_ready()
            if success > 0 and failed == 0:
                messages.success(request, f'Synced all {success} transactions!')
            elif success > 0:
                messages.warning(request, f'Synced {success}, {failed} failed.')
            elif total == 0:
                messages.info(request, 'No transactions ready to sync.')
            else:
                messages.error(request, f'Failed to sync {failed} transactions.')
        except Exception as e:
            messages.error(request, f'Sync error: {e}')
    return redirect(reverse('bridge:bulk_operations'))