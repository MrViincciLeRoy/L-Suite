from django.urls import path
from . import views

app_name = 'gmail'

urlpatterns = [
    path('credentials/', views.credentials, name='credentials'),
    path('credentials/new/', views.new_credential, name='new_credential'),
    path('credentials/<int:pk>/authorize/', views.authorize, name='authorize'),
    path('credentials/<int:pk>/delete/', views.delete_credential, name='delete_credential'),
    path('oauth/callback/', views.oauth_callback, name='oauth_callback'),
    path('statements/', views.statements, name='statements'),
    path('statements/import/', views.import_statements, name='import_statements'),
    path('statements/<int:pk>/', views.statement_detail, name='statement_detail'),
    path('statements/<int:pk>/parse/', views.parse_statement, name='parse_statement'),
    path('transactions/', views.transactions, name='transactions'),
    path('transactions/<int:pk>/', views.transaction_detail, name='transaction_detail'),
    path('upload-csv/', views.upload_csv, name='upload_csv'),
    path('download-csv-template/', views.download_csv_template, name='download_csv_template'),
    path('bulk-csv-import/', views.bulk_csv_import, name='bulk_csv_import'),
]

# PDF upload & progress
from django.urls import path
urlpatterns += [
    path('upload-pdf/', views.upload_pdf, name='upload_pdf'),
    path('pdf-jobs/<int:pk>/', views.pdf_import_progress, name='pdf_import_progress'),
    path('pdf-jobs/<int:pk>/status/', views.pdf_import_status, name='pdf_import_status'),
    path('pdf-jobs/', views.pdf_import_history, name='pdf_import_history'),
]
