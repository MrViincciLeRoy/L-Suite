from django.db import models
from django.contrib.auth.models import User
from calendar import month_name as _month_name


class ERPNextJournalEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    je_name = models.CharField(max_length=100)
    posting_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    account = models.CharField(max_length=255, blank=True)
    reference_number = models.CharField(max_length=255, blank=True)
    remark = models.TextField(blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'je_name')

    def __str__(self):
        return self.je_name


class ReconciliationMatch(models.Model):
    MATCH_STATUS = [
        ('matched', 'Matched'),
        ('flagged', 'Flagged'),
        ('manual', 'Manual Override'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    transaction = models.OneToOneField(
        'main.BankTransaction',
        on_delete=models.CASCADE,
        related_name='recon_match',
    )
    journal_entry = models.ForeignKey(
        ERPNextJournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='matches',
    )
    status = models.CharField(max_length=20, choices=MATCH_STATUS, default='matched')
    flag_reason = models.TextField(blank=True)
    matched_at = models.DateTimeField(auto_now_add=True)
    matched_by = models.CharField(max_length=20, default='auto')

    def __str__(self):
        return f"{self.transaction} → {self.journal_entry}"


class ReconciliationPeriod(models.Model):
    PERIOD_STATUS = [
        ('open', 'Open'),
        ('closed', 'Closed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    year = models.IntegerField()
    month = models.IntegerField()
    status = models.CharField(max_length=10, choices=PERIOD_STATUS, default='open')
    closed_at = models.DateTimeField(null=True, blank=True)
    total_transactions = models.IntegerField(default=0)
    matched_count = models.IntegerField(default=0)
    flagged_count = models.IntegerField(default=0)
    unreconciled_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ('user', 'year', 'month')

    def __str__(self):
        return f"{self.year}-{self.month:02d} ({self.status})"

    def label(self):
        return f"{_month_name[self.month]} {self.year}"

    def can_close(self):
        return self.unreconciled_count == 0 and self.flagged_count == 0