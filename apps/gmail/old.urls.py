from django.urls import path
from . import views
app_name='gmail'
urlpatterns = [
    path('credentials/',views.credentials,name='credentials'),
    path('credentials/new/',views.new_credential,name='new_credential'),
    path('credentials/<int:id>/authorize/',views.authorize,name='authorize'),
    path('oauth/callback/',views.oauth_callback,name='oauth_callback'),
    path('credentials/<int:id>/delete/',views.delete_credential,name='delete_credential'),
    path('statements/',views.statements,name='statements'),
    path('statements/import/',views.import_statements,name='import_statements'),
    path('statements/<int:id>/',views.statement_detail,name='statement_detail'),
    path('statements/<int:id>/parse/',views.parse_statement,name='parse_statement'),
    path('transactions/',views.transactions,name='transactions'),
    path('transactions/<int:id>/',views.transaction_detail,name='transaction_detail'),
    path('upload-csv/',views.upload_csv,name='upload_csv'),
    path('download-csv-template/',views.download_csv_template,name='download_csv_template'),
    path('bulk-csv-import/',views.bulk_csv_import,name='bulk_csv_import'),

]