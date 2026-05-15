from django.core.management.base import BaseCommand
from apps.main.models import TransactionCategory


class Command(BaseCommand):
    help = "Delete categories that have zero transactions attached."

    def handle(self, *args, **options):
        empty_ids = [
            c.pk for c in TransactionCategory.objects.prefetch_related('transactions').all()
            if c.transactions.count() == 0
        ]
        if empty_ids:
            deleted, _ = TransactionCategory.objects.filter(pk__in=empty_ids).delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} empty category/categories."))
        else:
            self.stdout.write(self.style.SUCCESS("No empty categories to clean up."))