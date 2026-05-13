import logging
from django.core.management.base import BaseCommand
from apps.main.models import ERPNextConfig
from apps.bridge.services import BulkSyncService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync categorized transactions to ERPNext as journal entries."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=int, help="Limit to a specific user ID")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        user_id = options.get("user")

        configs = ERPNextConfig.objects.filter(is_active=True)
        if user_id:
            configs = configs.filter(user_id=user_id)

        if not configs.exists():
            self.stdout.write(self.style.ERROR("No active ERPNext config found."))
            return

        total_success = total_failed = total_processed = 0

        for config in configs:
            self.stdout.write(f"\nConfig: {config.name} (user={config.user_id})")
            if dry:
                self.stdout.write(self.style.WARNING("  DRY RUN — skipping actual sync."))
                continue
            service = BulkSyncService(config)
            success, failed, total = service.sync_all_ready()
            total_success += success
            total_failed += failed
            total_processed += total
            self.stdout.write(
                self.style.SUCCESS(f"  Synced {success} / {total}, failed {failed}")
            )

        self.stdout.write("\n" + "─" * 50)
        self.stdout.write(self.style.SUCCESS(f"Total synced : {total_success}"))
        self.stdout.write(self.style.ERROR(f"Total failed : {total_failed}"))
        self.stdout.write(f"Total processed: {total_processed}")
