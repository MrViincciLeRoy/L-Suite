from django.contrib import admin
from .models import (
    BankAccount, TransactionCategory, GoogleCredential,
    EmailStatement, Invoice, InvoiceItem,
    BankTransaction, ERPNextConfig, ERPNextSyncLog, PDFImportJob,
)


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display  = ('account_name', 'user', 'bank_name', 'account_type', 'currency', 'balance', 'is_active')
    search_fields = ('account_name', 'account_number', 'bank_name', 'user__username')
    list_filter   = ('bank_name', 'account_type', 'currency', 'is_active')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TransactionCategory)
class TransactionCategoryAdmin(admin.ModelAdmin):
    list_display  = ('name', 'transaction_type', 'erpnext_account', 'active', 'created_at')
    search_fields = ('name', 'keywords', 'tags', 'erpnext_account')
    list_filter   = ('transaction_type', 'active')
    readonly_fields = ('created_at',)


@admin.register(GoogleCredential)
class GoogleCredentialAdmin(admin.ModelAdmin):
    list_display  = ('name', 'user', 'is_authenticated', 'token_expiry', 'created_at')
    search_fields = ('name', 'user__username')
    list_filter   = ('is_authenticated',)
    readonly_fields = ('created_at', 'updated_at', 'access_token', 'refresh_token')


@admin.register(EmailStatement)
class EmailStatementAdmin(admin.ModelAdmin):
    list_display  = ('subject', 'user', 'bank_name', 'state', 'has_pdf', 'is_processed', 'transaction_count', 'received_date')
    search_fields = ('subject', 'sender', 'gmail_id', 'user__username', 'bank_name')
    list_filter   = ('bank_name', 'state', 'has_pdf', 'is_processed')
    readonly_fields = ('created_at', 'updated_at')


class InvoiceItemInline(admin.TabularInline):
    model  = InvoiceItem
    extra  = 0
    fields = ('description', 'item_code', 'quantity', 'unit_price', 'total')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display  = ('invoice_number', 'user', 'customer_name', 'total_amount', 'status', 'invoice_date', 'due_date', 'erpnext_synced')
    search_fields = ('invoice_number', 'customer_name', 'customer_email', 'user__username')
    list_filter   = ('status', 'currency', 'erpnext_synced')
    readonly_fields = ('created_at', 'updated_at')
    inlines       = [InvoiceItemInline]


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display  = ('description', 'user', 'date', 'transaction_type', 'amount', 'deposit', 'withdrawal', 'balance', 'category', 'erpnext_synced')
    search_fields = ('description', 'reference_number', 'user__username')
    list_filter   = ('transaction_type', 'category', 'is_reconciled', 'erpnext_synced', 'currency')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'date'


@admin.register(ERPNextConfig)
class ERPNextConfigAdmin(admin.ModelAdmin):
    list_display  = ('name', 'user', 'base_url', 'default_company', 'is_active', 'last_sync')
    search_fields = ('name', 'base_url', 'default_company', 'user__username')
    list_filter   = ('is_active',)
    readonly_fields = ('created_at', 'updated_at', 'api_key', 'api_secret')


@admin.register(ERPNextSyncLog)
class ERPNextSyncLogAdmin(admin.ModelAdmin):
    list_display  = ('config', 'record_type', 'record_id', 'erpnext_doctype', 'status', 'sync_date')
    search_fields = ('record_type', 'erpnext_doc_name', 'erpnext_doctype')
    list_filter   = ('status', 'record_type')
    readonly_fields = ('sync_date',)


@admin.register(PDFImportJob)
class PDFImportJobAdmin(admin.ModelAdmin):
    list_display  = ('filename', 'user', 'bank_name', 'status', 'progress', 'total_files', 'processed_files', 'transactions_saved', 'created_at')
    search_fields = ('filename', 'user__username', 'bank_name')
    list_filter   = ('status', 'bank_name')
    readonly_fields = ('created_at', 'updated_at')
