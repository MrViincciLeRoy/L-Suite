import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.main.models import ERPNextConfig, ERPNextSyncLog, BankTransaction
from .services import ERPNextService

logger = logging.getLogger(__name__)


def _active_config(user):
    return ERPNextConfig.objects.filter(user=user, is_active=True).first()


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


@login_required
def sync_logs(request):
    logs_qs = ERPNextSyncLog.objects.filter(
        config__user=request.user
    ).select_related('config').order_by('-sync_date')
    paginator = Paginator(logs_qs, 50)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'erpnext/sync_logs.html', {'logs': page})


@login_required
def sync_transaction(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    if not transaction.category_id:
        return JsonResponse(
            {'success': False, 'message': 'Transaction must be categorized first'}, status=400,
        )
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No active ERPNext configuration'}, status=400)
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
    config = _active_config(request.user)
    if not config:
        return JsonResponse({'success': False, 'message': 'No active ERPNext configuration'}, status=400)
    try:
        raw = ERPNextService(config).get_chart_of_accounts()
        if not raw:
            return JsonResponse(
                {'success': False, 'message': 'No accounts returned. Check company name and API permissions.'},
                status=502,
            )
        accounts = sorted(
            [{
                'name': a['name'],
                'account_name': a.get('account_name') or a['name'],
                'account_type': a.get('account_type', ''),
                'root_type': a.get('root_type', ''),
                'company': a.get('company', ''),
                'is_group': bool(a.get('is_group')),
            } for a in raw],
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

    config.default_company     = company
    config.bank_account        = bank
    config.default_cost_center = cost_center
    config.save(update_fields=['default_company', 'bank_account', 'default_cost_center'])

    logger.info(f"Config {config.id} defaults updated: company={company!r} bank={bank!r} cc={cost_center!r}")
    return JsonResponse({'success': True, 'message': 'Defaults saved.'})