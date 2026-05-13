from django.urls import path
from . import views

app_name = 'erpnext'

urlpatterns = [
    path('configs/', views.configs, name='configs'),
    path('configs/new/', views.new_config, name='new_config'),
    path('configs/<int:pk>/edit/', views.edit_config, name='edit_config'),
    path('configs/<int:pk>/delete/', views.delete_config, name='delete_config'),
    path('configs/<int:pk>/test/', views.test_config, name='test_connection'),
    path('configs/<int:pk>/activate/', views.activate_config, name='activate_config'),
    path('sync-logs/', views.sync_logs, name='sync_logs'),
    path('transactions/<int:pk>/sync/', views.sync_transaction, name='sync_transaction'),
    path('fetch-accounts/', views.fetch_accounts, name='fetch_accounts'),
    path('fetch-cost-centers/', views.fetch_cost_centers, name='fetch_cost_centers'),
    path('fetch-companies/', views.fetch_companies, name='fetch_companies'),
    path('update-config-defaults/', views.update_config_defaults, name='update_config_defaults'),
    path('sync-preflight/', views.sync_preflight, name='sync_preflight'),
    path('sync-now/', views.bulk_sync_post, name='bulk_sync_post'),
    path('sync-job/', views.sync_job_status, name='sync_job_status'),
    path('sync-job/api/', views.sync_job_status_api, name='sync_job_status_api'),
]
