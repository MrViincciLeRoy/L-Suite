from django.core.management.base import BaseCommand
from django.core.management import call_command
from apps.main.models import TransactionCategory, BankTransaction


class Command(BaseCommand):
    help = "Delete categories with no transactions, then seed if the system has no categories."

    def add_arguments(self, parser):
        parser.add_argument("--seed-overwrite", action="store_true",
                            help="Pass --overwrite to seed_categories if seeding runs")

    def handle(self, *args, **options):
        # 1. Delete categories that have zero transactions attached
        empty_ids = [
            c.pk for c in TransactionCategory.objects.all()
            if c.transactions.count() == 0
        ]
        if empty_ids:
            deleted, _ = TransactionCategory.objects.filter(pk__in=empty_ids).delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} empty category/categories."))
        else:
            self.stdout.write("No empty categories found.")

        # 2. If no categories remain, auto-seed
        remaining = TransactionCategory.objects.count()
        if remaining == 0:
            self.stdout.write(self.style.WARNING(
                "No categories in system — running seed_categories..."
            ))
            seed_kwargs = {}
            if options["seed_overwrite"]:
                seed_kwargs["overwrite"] = True
            call_command("seed_categories", **seed_kwargs)
        else:
            self.stdout.write(self.style.SUCCESS(
                f"{remaining} categories remain after cleanup. Skipping seed."
            ))
