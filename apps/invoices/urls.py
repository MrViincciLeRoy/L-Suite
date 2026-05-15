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