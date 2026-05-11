from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.contrib.auth.models import User 

'''
class User(AbstractUser):
    is_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username

    class Meta:
        db_table = 'users'
'''

class BankAccount(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bank_accounts',default='user')
    account_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=100, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_type = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=3, default='ZAR')
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.account_name

    class Meta:
        db_table = 'bank_accounts'


class TransactionCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    erpnext_account = models.CharField(max_length=200,null=True, blank=True)
    transaction_type = models.CharField(max_length=20)
    keywords = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    color = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_keywords_list(self):
        if not self.keywords:
            return []
        return [k.strip().lower() for k in self.keywords.split(',')]

    def matches_description(self, description):
        if not description:
            return False
        return any(kw in description.lower() for kw in self.get_keywords_list())

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'transaction_categories'


class GoogleCredential(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='google_credentials')
    name = models.CharField(max_length=100)
    client_id = models.CharField(max_length=255)
    client_secret = models.CharField(max_length=255)
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    is_authenticated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'google_credentials'


class EmailStatement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_statements')
    gmail_id = models.CharField(max_length=255, unique=True, db_index=True)
    thread_id = models.CharField(max_length=255, blank=True, db_index=True)
    subject = models.CharField(max_length=500, blank=True)
    sender = models.CharField(max_length=255, blank=True)
    received_date = models.DateTimeField(null=True, blank=True, db_index=True)
    statement_date = models.DateField(null=True, blank=True, db_index=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=100, blank=True)
    has_pdf = models.BooleanField(default=False)
    pdf_password = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, default='new')
    is_processed = models.BooleanField(default=False)
    processed_date = models.DateTimeField(null=True, blank=True)
    transaction_count = models.IntegerField(default=0)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.subject or self.gmail_id

    class Meta:
        db_table = 'email_statements'


class Invoice(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'), ('sent', 'Sent'), ('paid', 'Paid'),
        ('overdue', 'Overdue'), ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=100, unique=True, db_index=True)
    invoice_date = models.DateField(db_index=True)
    due_date = models.DateField(null=True, blank=True)
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField(blank=True)
    customer_address = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    outstanding_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default='ZAR')
    status = models.CharField(max_length=50, default='draft', choices=STATUS_CHOICES, db_index=True)
    erpnext_id = models.CharField(max_length=100, blank=True, db_index=True)
    erpnext_synced = models.BooleanField(default=False)
    erpnext_sync_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_paid(self):
        return self.outstanding_amount <= 0

    @property
    def is_overdue(self):
        if self.due_date and self.status not in ['paid', 'cancelled']:
            return timezone.now().date() > self.due_date
        return False

    def calculate_totals(self):
        self.subtotal = sum(item.total for item in self.items.all())
        self.tax_amount = self.subtotal * (self.tax_rate / 100)
        self.total_amount = self.subtotal + self.tax_amount - self.discount_amount
        self.outstanding_amount = self.total_amount - self.paid_amount

    def __str__(self):
        return self.invoice_number

    class Meta:
        db_table = 'invoices'


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    item_code = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    total = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def calculate_total(self):
        self.total = self.quantity * self.unit_price

    def __str__(self):
        return self.description[:30]

    class Meta:
        db_table = 'invoice_items'


class BankTransaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bank_transactions',default='user')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_transactions')
    statement = models.ForeignKey(EmailStatement, on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_transactions')
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name='bank_transactions')
    date = models.DateField(db_index=True)
    transaction_type =  models.CharField(max_length=100, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    fee = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    posting_date = models.DateField(null=True, blank=True, db_index=True)
    description = models.CharField(max_length=500)
    reference_number = models.CharField(max_length=100, blank=True, db_index=True)
    deposit = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    withdrawal = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    balance = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default='ZAR')
    unallocated_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    category = models.ForeignKey(TransactionCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    tags = models.CharField(max_length=500, blank=True)
    notes = models.TextField(blank=True)
    is_categorized = models.TextField(blank=True)
    is_reconciled = models.BooleanField(default=False)
    reconciled_date = models.DateTimeField(null=True, blank=True)
    erpnext_id = models.CharField(max_length=100, blank=True, db_index=True)
    erpnext_synced = models.BooleanField(default=False)
    erpnext_sync_date = models.DateTimeField(null=True, blank=True)
    erpnext_journal_entry = models.CharField(max_length=100, blank=True)
    erpnext_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def to_erpnext_format(self):
        return {
            'date': self.date.strftime('%Y-%m-%d') if self.date else None,
            'posting_date': self.posting_date.strftime('%Y-%m-%d') if self.posting_date else None,
            'description': self.description,
            'deposit': float(self.deposit or 0),
            'withdrawal': float(self.withdrawal or 0),
            'currency': self.currency,
            'bank_account': self.bank_account.account_name if self.bank_account else None,
            'reference_number': self.reference_number,
            'unallocated_amount': float(self.unallocated_amount or 0),
        }

    def __str__(self):
        return self.reference_number or str(self.id)

    class Meta:
        db_table = 'bank_transactions'


class ERPNextConfig(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='erpnext_configs')
    name = models.CharField(max_length=100)
    base_url = models.CharField(max_length=255)
    api_key = models.CharField(max_length=255)
    api_secret = models.CharField(max_length=255)
    default_company = models.CharField(max_length=200, blank=True)
    bank_account = models.CharField(max_length=200, blank=True)
    default_cost_center = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    last_sync = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'erpnext_configs'


class ERPNextSyncLog(models.Model):
    config = models.ForeignKey(ERPNextConfig, on_delete=models.CASCADE, related_name='sync_logs')
    record_type = models.CharField(max_length=50)
    record_id = models.IntegerField()
    erpnext_doctype = models.CharField(max_length=100, blank=True)
    erpnext_doc_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20)
    error_message = models.TextField(blank=True)
    sync_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.record_type}:{self.record_id} [{self.status}]'

    class Meta:
        db_table = 'erpnext_sync_logs'
    

class PDFImportJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pdf_import_jobs')
    filename = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=100, default='capitec')
    pdf_password = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    progress = models.IntegerField(default=0)
    total_files = models.IntegerField(default=1)
    processed_files = models.IntegerField(default=0)
    transactions_found = models.IntegerField(default=0)
    transactions_saved = models.IntegerField(default=0)
    transactions_skipped = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    statement = models.ForeignKey(
        'EmailStatement', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='pdf_jobs'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.filename} [{self.status}]'

    class Meta:
        db_table = 'pdf_import_jobs'
        ordering = ['-created_at']
