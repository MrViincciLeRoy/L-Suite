from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.main.models import BankTransaction
from .models import ERPNextInvoice
from .services import InvoiceSyncService


@login_required
def dashboard(request):
    invoices = ERPNextInvoice.objects.filter(user=request.user)

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

    # Counts for tab badges
    counts = {
        'all': ERPNextInvoice.objects.filter(user=request.user).count(),
        'sales': ERPNextInvoice.objects.filter(user=request.user, invoice_type='sales').count(),
        'purchase': ERPNextInvoice.objects.filter(user=request.user, invoice_type='purchase').count(),
        'unpaid': ERPNextInvoice.objects.filter(user=request.user, erp_status='Unpaid').count(),
        'overdue': ERPNextInvoice.objects.filter(user=request.user, erp_status='Overdue').count(),
    }

    from datetime import date
    today = date.today()

    return render(request, 'invoices/dashboard.html', {
        'invoices': invoices,
        'invoice_type': invoice_type,
        'status': status,
        'search': search,
        'counts': counts,
        'current_year': today.year,
        'current_month': today.month,
    })


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(ERPNextInvoice, pk=pk, user=request.user)
    linked_txns = invoice.linked_transactions.all()

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
    if request.method != 'POST':
        return redirect('invoices:dashboard')

    try:
        service = InvoiceSyncService(request.user)
        results = service.sync_period(year, month)
        messages.success(
            request,
            f"Sync complete — "
            f"{results['sales_created']} sales created, {results['sales_updated']} updated; "
            f"{results['purchase_created']} purchase created, {results['purchase_updated']} updated."
        )
    except Exception as ex:
        messages.error(request, f"Sync failed: {ex}")

    return redirect('invoices:dashboard')


@login_required
def link_transaction(request, invoice_pk):
    invoice = get_object_or_404(ERPNextInvoice, pk=invoice_pk, user=request.user)
    txn_id = request.POST.get('transaction_id')
    txn = get_object_or_404(BankTransaction, id=txn_id, user=request.user)

    txn.linked_invoice = invoice
    txn.save(update_fields=['linked_invoice'])

    messages.success(request, f"Transaction linked to {invoice.erp_name}.")
    return redirect('invoices:detail', pk=invoice_pk)


@login_required
def unlink_transaction(request, txn_id):
    txn = get_object_or_404(BankTransaction, id=txn_id, user=request.user)
    txn.linked_invoice = None
    txn.save(update_fields=['linked_invoice'])
    messages.success(request, "Invoice link removed.")
    return redirect(request.META.get('HTTP_REFERER', '/invoices/'))


@login_required
def invoice_search_json(request):
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