from django.db import models
from datetime import datetime
from django.contrib.auth.models import User 

# Create your models here.
class BankAccount(models.Model):

    """Bank account model"""
    #__tablename__ = 'bank_accounts'
    
    id = models.PositiveIntegerField(primary_key=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE,null=False)
    account_name = models.CharField(max_length=200, null=False)
    account_number = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=50)
    currency = models.CharField(max_length=3, default='ZAR')
    balance = models.IntegerField(default=0.00)
    is_active = models.BooleanField( default=True)
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(default=datetime.utcnow)
    
    # Relationships
    transactions = models.ManyToManyField('Transaction', related_name='bank_account')
    bank_transactions = models.ManyToManyField('BankTransaction', related_name='bank_account_2')
    
    def __str__(self):
        return f'<BankAccount {self.account_name}>'


# =============================================================================
# Invoice Models
# =============================================================================

class Invoice(models.Model):

    """Invoice model"""
    #__tablename__ = 'invoices'
    
    id = models.IntegerField(primary_key=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE,null=False)
    
    # Invoice details
    invoice_number = models.CharField(max_length=100, unique=True, null=False)
    invoice_date = models.DateField(null=False)
    due_date = models.DateField()
    
    # Customer/Supplier
    customer_name = models.CharField(max_length=200, null=False)
    customer_email = models.CharField(max_length=120)
    customer_address = models.CharField()
    
    # Financial details
    subtotal = models.IntegerField(null=False, default=0.00)
    tax_amount = models.IntegerField(default=0.00)
    tax_rate = models.IntegerField(default=0.00)
    discount_amount = models.IntegerField(default=0.00)
    total_amount = models.IntegerField(null=False, default=0.00)
    paid_amount = models.IntegerField(default=0.00)
    outstanding_amount = models.IntegerField(default=0.00)
    
    currency = models.CharField(max_length=3, default='ZAR')
    
    # Status
    status = models.CharField(max_length=50, default='draft')
    
    # ERPNext integration
    erpnext_id = models.CharField(max_length=100)
    erpnext_synced = models.BooleanField( default=False)
    erpnext_sync_date = models.DateTimeField()
    
    # Metadata
    notes = models.CharField()
    terms = models.CharField()
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(default=datetime.utcnow)
    
    # Relationships
    items = models.ManyToManyField('InvoiceItem', related_name='invoice')
    transactions = models.ManyToManyField('Transaction', related_name='invoice')
    bank_transactions = models.ManyToManyField('BankTransaction', related_name='invoice')
    
    @property
    def is_paid(self):
        """Check if invoice is fully paid"""
        return self.outstanding_amount <= 0
    
    @property
    def is_overdue(self):
        """Check if invoice is overdue"""
        if self.due_date and self.status not in ['paid', 'cancelled']:
            return datetime.now().date() > self.due_date
        return False
    
    def calculate_totals(self):
        """Recalculate invoice totals from items"""
        self.subtotal = sum(item.total for item in self.items)
        self.tax_amount = self.subtotal * (self.tax_rate / 100)
        self.total_amount = self.subtotal + self.tax_amount - self.discount_amount
        self.outstanding_amount = self.total_amount - self.paid_amount
    
    def __str__(self):
        return f'<Invoice {self.invoice_number}>'


class InvoiceItem(models.Model):

    """Invoice line item model"""
    #__tablename__ = 'invoice_items'
    
    id = models.IntegerField(primary_key=True)
    invoice_id = models.ForeignKey(Invoice,on_delete=models.CASCADE, null=False)
    
    item_code = models.CharField(max_length=100)
    description = models.CharField(max_length=500, null=False)
    quantity = models.IntegerField(null=False, default=1)
    unit_price = models.IntegerField(null=False)
    total = models.IntegerField(null=False)
    
    # Metadata
    notes = models.CharField(max_length=500)
    created_at = models.DateTimeField(default=datetime.utcnow)
    
    def calculate_total(self):
        """Calculate line item total"""
        self.total = self.quantity * self.unit_price
    
    def __str__(self):
        return f'<InvoiceItem {self.description[:30]}>'





class Transaction(models.Model):

    """Bank transaction model (legacy)"""
    #__tablename__ = 'transactions'
    
    id = models.PositiveIntegerField( primary_key=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE,null=False)
    bank_account_id = models.ForeignKey(BankAccount, on_delete=models.CASCADE,null=False, related_name='Transactions')
    
    transaction_date = models.DateField(null=False)
    posting_date = models.DateField()
    description = models.CharField(max_length=500, null=False)
    reference_number = models.CharField(max_length=100)
    
    # Amount fields
    debit = models.IntegerField(default=0.00)
    credit = models.IntegerField( default=0.00)
    balance = models.IntegerField()
    
    # Categorization
    category = models.CharField(max_length=100)
    tags = models.CharField(max_length=500)
    notes = models.CharField()
    
    # Reconciliation
    is_reconciled = models.BooleanField(default=False)
    reconciled_date = models.DateTimeField()
    invoice_id = models.ForeignKey(Invoice, on_delete=models.CASCADE,related_name='transaction')
    
    # Metadata
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(default=datetime.utcnow)

    @property
    def amount(self):
        """Get transaction amount (credit - debit)"""
        return float(self.credit or 0) - float(self.debit or 0)
    
    @property
    def transaction_type(self):
        """Get transaction type"""
        if self.credit and self.credit > 0:
            return 'credit'
        elif self.debit and self.debit > 0:
            return 'debit'
        return 'unknown'
    
    def __str__(self):
        return f'<Transaction {self.reference_number or self.id}>'


class TransactionCategory(models.Model):

    """Transaction categorization for ERPNext mapping"""
    #__tablename__ = 'transaction_categories'
    
    id = models.IntegerField( primary_key=True)
    name = models.CharField(max_length=100, null=False, unique=True)
    erpnext_account = models.CharField(max_length=200, null=False)
    transaction_type = models.CharField(max_length=20, null=False)
    keywords = models.CharField()
    active = models.BooleanField(default=True)
    color = models.IntegerField()
    created_at = models.DateTimeField(default=datetime.utcnow)
    
    # Relationship
    transactions = models.ManyToManyField('BankTransaction')# back_populates='category'
    
    def get_keywords_list(self):
        """Return keywords as a list"""
        if not self.keywords:
            return []
        return [k.strip().lower() for k in self.keywords.split(',')]
    
    def matches_description(self, description):
        """Check if any keyword matches the description"""
        if not description:
            return False
        description_lower = description.lower()
        return any(keyword in description_lower for keyword in self.get_keywords_list())
    
    def __str__(self):
        return f'<TransactionCategory {self.name}>'

# =============================================================================
# Email Statement Models - FIXED VERSION
# =============================================================================

class EmailStatement(models.Model):

    """Email statement model for Gmail integration - FIXED"""
    #__tablename__ = 'email_statements'
    
    id = models.IntegerField(primary_key=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE,null=False)
    
    # Email details - FIXED: using gmail_id and received_date
    gmail_id = models.CharField(max_length=255, unique=True, null=False)
    thread_id = models.CharField(max_length=255)
    subject = models.CharField(max_length=500)
    sender = models.CharField(max_length=255)
    received_date = models.DateTimeField()
    
    # Statement details
    statement_date = models.DateField()
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=100)
    
    # PDF details
    has_pdf = models.BooleanField(default=False)
    pdf_password = models.CharField(max_length=100)
    
    # Processing status
    state = models.CharField(max_length=50, default='new')
    is_processed = models.BooleanField(default=False)
    processed_date = models.DateTimeField()
    transaction_count = models.IntegerField(default=0)
    
    # Content
    body_text = models.CharField()
    body_html = models.CharField()
    
    # Errors
    error_message = models.CharField()
    
    # Metadata
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(default=datetime.utcnow)
    
    # Relationships
    transactions = models.ManyToManyField('BankTransaction', related_name='statement')
    
    def __str__(self):
        return f'<EmailStatement {self.gmail_id}>'


class BankTransaction(models.Model):

    """Bank transaction model for ERPNext integration"""
    #__tablename__ = 'bank_transactions'
    
    id = models.IntegerField(primary_key=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE,null=False)
    bank_account_id = models.ForeignKey(BankAccount,on_delete=models.CASCADE,related_name='bank_transaction')
    statement_id = models.ForeignKey(EmailStatement,on_delete=models.CASCADE,related_name='bank_transaction')
    
    # Transaction details
    date = models.DateField(null=False)
    posting_date = models.DateField()
    description = models.CharField(max_length=500, null=False)
    reference_number = models.CharField(max_length=100)
    
    # Amounts
    deposit = models.IntegerField(default=0.00)
    withdrawal = models.IntegerField(default=0.00)
    balance = models.IntegerField()
    
    # Additional fields
    currency = models.CharField(max_length=3, default='ZAR')
    unallocated_amount = models.IntegerField()
    
    # Categorization
    category_id = models.ForeignKey(TransactionCategory,on_delete=models.CASCADE,related_name='bank_transaction')
    tags = models.CharField(max_length=500)
    notes = models.IntegerField()
    
    # Reconciliation
    is_reconciled = models.IntegerField(default=False)
    reconciled_date = models.IntegerField()
    invoice_id = models.ForeignKey(Invoice,on_delete=models.CASCADE,related_name='bank_transaction')
    
    # ERPNext integration
    erpnext_id = models.CharField(max_length=100)
    erpnext_synced = models.BooleanField(default=False)
    erpnext_sync_date = models.DateTimeField()
    erpnext_journal_entry = models.CharField(max_length=100)
    erpnext_error = models.IntegerField()
    
    # Metadata
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(default=datetime.utcnow)
    
    # Relationship to category
    category = models.ManyToManyField('TransactionCategory')# back_populates='transactions'

    @property
    def amount(self):
        """Get transaction amount"""
        return float(self.deposit or 0) - float(self.withdrawal or 0)
    
    @property
    def transaction_type(self):
        """Get transaction type"""
        if self.deposit and self.deposit > 0:
            return 'deposit'
        elif self.withdrawal and self.withdrawal > 0:
            return 'withdrawal'
        return 'unknown'
    
    @property
    def is_categorized(self):
        """Check if transaction is categorized"""
        return self.category_id is not None
    
    def to_erpnext_format(self):
        """Convert to ERPNext format"""
        return {
            "date": self.date.strftime('%Y-%m-%d') if self.date else None,
            "posting_date": self.posting_date.strftime('%Y-%m-%d') if self.posting_date else None,
            "description": self.description,
            "deposit": float(self.deposit or 0),
            "withdrawal": float(self.withdrawal or 0),
            "currency": self.currency,
            "bank_account": self.bank_account.account_name if self.bank_account else None,
            "reference_number": self.reference_number,
            "unallocated_amount": float(self.unallocated_amount or 0)
        }
    
    def __str__(self):
        return f'<BankTransaction {self.reference_number or self.id}>'


# =============================================================================
# ERPNext Integration Models
# =============================================================================

class ERPNextConfig(models.Model):

    """ERPNext configuration model"""
    #__tablename__ = 'erpnext_configs'
    
    id = models.IntegerField(primary_key=True)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE,null=False)
    
    name = models.CharField(max_length=100, null=False)
    base_url = models.CharField(max_length=255, null=False)
    api_key = models.CharField(max_length=255, null=False)
    api_secret = models.CharField(max_length=255, null=False)
    
    default_company = models.CharField(max_length=200)
    bank_account = models.CharField(max_length=200)
    default_cost_center = models.CharField(max_length=200)
    
    is_active = models.BooleanField(default=True)
    last_sync = models.DateTimeField()
    
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(default=datetime.utcnow)
    
    def __str__(self):
        return f'<ERPNextConfig {self.name}>'


class ERPNextSyncLog(models.Model):

    """ERPNext synchronization log model"""
    #__tablename__ = 'erpnext_sync_logs'
    
    id = models.IntegerField(primary_key=True)
    config_id = models.ForeignKey(ERPNextConfig,on_delete=models.CASCADE, null=False)
    
    record_type = models.CharField(max_length=50, null=False)
    record_id = models.IntegerField(null=False)
    
    erpnext_doctype = models.CharField(max_length=100)
    erpnext_doc_name = models.CharField(max_length=200)
    
    status = models.CharField(max_length=20, null=False)
    error_message = models.CharField()
    
    sync_date = models.CharField(default=datetime.utcnow)
    
    def __str__(self):
        return f'<ERPNextSyncLog {self.record_type}:{self.record_id} {self.status}>'
# Alias for backwards compatibility
SyncLog = ERPNextSyncLog