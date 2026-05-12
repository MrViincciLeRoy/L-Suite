from django.contrib import admin
from .models import *

admin.site.register(BankAccount)
admin.site.register(Invoice)
admin.site.register(InvoiceItem)
admin.site.register(Transaction)
admin.site.register(TransactionCategory)
admin.site.register(EmailStatement)
admin.site.register(BankTransaction)
admin.site.register(ERPNextConfig)
admin.site.register(ERPNextSyncLog)
