from django.core.management.base import BaseCommand
from apps.main.models import BankTransaction, TransactionCategory


class Command(BaseCommand):
    help = 'Re-run keyword categorization on uncategorized or all transactions'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Re-categorize all, not just uncategorized')
        parser.add_argument('--user', type=int, help='Limit to a specific user ID')

    def handle(self, *args, **options):
        categories = list(TransactionCategory.objects.filter(active=True))

        if options['all']:
            qs = BankTransaction.objects.all()
        else:
            qs = BankTransaction.objects.filter(category__isnull=True)

        if options.get('user'):
            qs = qs.filter(user_id=options['user'])

        total = qs.count()
        self.stdout.write(f'Processing {total} transactions...')

        updated = 0
        unmatched = 0

        for txn in qs.iterator():
            matched = False
            for cat in categories:
                if cat.transaction_type != ('credit' if txn.deposit else 'debit'):
                    continue
                if cat.matches_description(txn.description):
                    txn.category = cat
                    txn.save(update_fields=['category'])
                    updated += 1
                    matched = True
                    break
            if not matched:
                unmatched += 1

        self.stdout.write(self.style.SUCCESS(f'Categorized: {updated}'))
        self.stdout.write(self.style.WARNING(f'No match found: {unmatched}'))
