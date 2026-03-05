from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from main.models import EmailStatement, BankTransaction


@login_required
def index(request):
    stats = {
        'statements': EmailStatement.objects.filter(user=request.user).count(),
        'transactions': BankTransaction.objects.filter(user=request.user).count(),
        'categorized': BankTransaction.objects.filter(user=request.user, category__isnull=False).count(),
        'synced': BankTransaction.objects.filter(user=request.user, erpnext_synced=True).count(),
    }
    recent_statements = EmailStatement.objects.filter(user=request.user).order_by('-received_date')[:5]
    recent_transactions = BankTransaction.objects.filter(user=request.user).order_by('-date')[:10]

    return render(request, 'main/index.html', {
        'stats': stats,
        'recent_statements': recent_statements,
        'recent_transactions': recent_transactions,
    })


def about(request):
    return render(request, 'main/about.html')
