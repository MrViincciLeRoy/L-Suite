from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = 'bridge'

urlpatterns = [
    path('categories/', views.categories, name='categories'),
    path('categories/new/', views.new_category, name='new_category'),
    path('categories/<int:pk>/edit/', views.edit_category, name='edit_category'),
    path('categories/<int:pk>/delete/', views.delete_category, name='delete_category'),
    path('categories/<int:pk>/transactions/', views.category_transactions, name='category_transactions'),

    path('bulk-operations/', views.bulk_operations, name='bulk_operations'),
    path('bulk-operations/auto-categorize/', views.auto_categorize, name='auto_categorize'),
    path('bulk-operations/auto-categorize-ai/', views.auto_categorize_ai, name='auto_categorize_ai'),
    path('bulk-operations/preview-categorization/', views.preview_categorization, name='preview_categorization'),
    path('bulk-operations/sync-to-erpnext/', views.bulk_sync, name='bulk_sync'),

    # Redirects ? these moved to erpnext app
    path('bulk-operations/sync-preflight/', RedirectView.as_view(pattern_name='erpnext:sync_preflight', permanent=True), name='sync_logs'),
    path('bulk-operations/sync-now/', RedirectView.as_view(pattern_name='erpnext:bulk_sync_post', permanent=True), name='bulk_sync_post'),

    # AJAX single-transaction classifier
    path('classify/', views.classify_single, name='classify_single'),

    path('transactions/<int:pk>/categorize/', views.categorize_transaction, name='categorize_transaction'),
    path('transactions/<int:pk>/uncategorize/', views.uncategorize_transaction, name='uncategorize_transaction'),
]