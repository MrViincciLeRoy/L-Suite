from django.db import models
from django.contrib.auth.models import User


class ERPNextInvoice(models.Model):
    INVOICE_TYPE = [
        ('sales', 'Sales Invoice'),
        ('purchase', 'Purchase Invoice'),
    ]

    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Submitted', 'Submitted'),
        ('Unpaid', 'Unpaid'),
        ('Partly Paid', 'Partly Paid'),
        ('Paid', 'Paid'),
        ('Overdue', 'Overdue'),
        ('Cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPE)

    # ERPNext identifiers
    erp_name = models.CharField(max_length=100)
    erp_status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Unpaid')

    # Party (customer for sales, supplier for purchase)
    party_id = models.CharField(max_length=200, blank=True)
    party_name = models.CharField(max_length=255, blank=True)

    # Amounts
    currency = models.CharField(max_length=10, default='ZAR')
    grand_total = models.DecimalField(max_digits=14, decimal_places=2)
    outstanding_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Dates
    posting_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    # Purchase invoice only
    bill_no = models.CharField(max_length=100, blank=True)
    bill_date = models.DateField(null=True, blank=True)

    # Sync metadata
    fetched_at = models.DateTimeField(auto_now=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('user', 'erp_name')
        ordering = ['-posting_date']
        indexes = [
            models.Index(fields=['user', 'invoice_type', 'erp_status']),
            models.Index(fields=['user', 'posting_date']),
            models.Index(fields=['user', 'party_name']),
        ]

    def __str__(self):
        return f"{self.erp_name} — {self.party_name} ({self.erp_status})"

    @property
    def is_paid(self):
        return self.erp_status in ('Paid',)

    @property
    def is_overdue(self):
        from django.utils import timezone
        return (
            self.erp_status in ('Unpaid', 'Partly Paid')
            and self.due_date
            and self.due_date < timezone.now().date()
        )

    @property
    def amount_paid(self):
        return self.grand_total - self.outstanding_amount