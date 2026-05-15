from django.urls import path
from . import views

app_name = 'reconciliation'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('<int:year>/<int:month>/', views.period_detail, name='period_detail'),
    path('<int:year>/<int:month>/fetch/', views.fetch_journal_entries, name='fetch_je'),
    path('<int:year>/<int:month>/match/', views.run_match, name='run_match'),
    path('<int:year>/<int:month>/close/', views.close_period, name='close_period'),
    path('<int:year>/<int:month>/reopen/', views.reopen_period, name='reopen_period'),
    path('<int:year>/<int:month>/export/', views.export_csv, name='export_csv'),
    path('match/manual/<int:txn_id>/', views.manual_match, name='manual_match'),
    path('match/unmatch/<int:txn_id>/', views.unmatch_transaction, name='unmatch_transaction'),
    path('debug-je/', 
]