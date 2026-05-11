from django.urls import path
from . import views

app_name = 'erpnext'

urlpatterns = [
    path('configs/', views.configs, name='configs'),
    path('configs/new/', views.new_config, name='new_config'),
    path('configs/<int:pk>/edit/', views.edit_config, name='edit_config'),
    path('configs/<int:pk>/delete/', views.delete_config, name='delete_config'),
    path('configs/<int:pk>/test/', views.test_config, name='test_config'),
    path('configs/<int:pk>/activate/', views.activate_config, name='activate_config'),
    path('sync-logs/', views.sync_logs, name='sync_logs'),
    path('transactions/<int:pk>/sync/', views.sync_transaction, name='sync_transaction'),
    path('fetch-accounts/', views.fetch_accounts, name='fetch_accounts'),
    path('fetch-cost-centers/', views.fetch_cost_centers, name='fetch_cost_centers'),
]
