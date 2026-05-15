from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from apps.invoices.services import InvoiceSyncService


class Command(BaseCommand):
    help = 'Sync invoices from ERPNext for a given period'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=date.today().year)
        parser.add_argument('--month', type=int, default=date.today().month)
        parser.add_argument('--user', type=int, help='Limit to user ID')

    def handle(self, *args, **options):
        year = options['year']
        month = options['month']

        users = User.objects.all()
        if options.get('user'):
            users = users.filter(pk=options['user'])

        self.stdout.write(f"Syncing invoices for {year}-{month:02d} ...")

        for user in users:
            try:
                service = InvoiceSyncService(user)
                results = service.sync_period(year, month)
                self.stdout.write(self.style.SUCCESS(
                    f"  {user.username}: "
                    f"sales +{results['sales_created']} upd {results['sales_updated']} | "
                    f"purchase +{results['purchase_created']} upd {results['purchase_updated']}"
                ))
            except ValueError as ex:
                # No ERPNext config — skip silently
                self.stdout.write(f"  {user.username}: skipped ({ex})")
            except Exception as ex:
                self.stderr.write(self.style.ERROR(f"  {user.username}: FAILED — {ex}"))