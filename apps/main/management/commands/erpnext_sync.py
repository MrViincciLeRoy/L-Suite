import logging
from django.core.management.base import BaseCommand, CommandError
from apps.main.models import ERPNextConfig, BankTransaction, TransactionCategory
from apps.erpnext.services import ERPNextService

logger = logging.getLogger(__name__)


def _get_junk_ids():
    try:
        from apps.bridge.services import _get_junk_category_ids
        return _get_junk_category_ids()
    except Exception:
        return []


class Command(BaseCommand):
    help = "Sync categorised bank transactions to ERPNext as Journal Entries"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Validate only, no writes")
        parser.add_argument("--limit", type=int, default=0, help="Max transactions (0 = all)")
        parser.add_argument("--transaction-id", type=int, default=0, help="Sync a single transaction by ID")

    def handle(self, *args, **options):
        dry_run   = options["dry_run"]
        limit     = options["limit"]
        single_id = options["transaction_id"]

        config = ERPNextConfig.objects.filter(is_active=True).first()
        if not config:
            raise CommandError("No active ERPNext configuration found.")

        service = ERPNextService(config)

        ok, msg = service.test_connection()
        if not ok:
            raise CommandError(f"ERPNext connection failed: {msg}")
        self.stdout.write(self.style.SUCCESS(f"Connected: {msg}"))

        # ── Validate bank account ────────────────────────────────────────────
        # The preflight form saves the fully qualified ERPNext name (e.g. "Capitec - V")
        # directly to config.bank_account. _resolve_account short-circuits on " - "
        # so no extra API call is needed.
        bank = (config.bank_account or "").strip()
        if not bank:
            raise CommandError(
                "bank_account is not set. Open the Sync Preflight page, select "
                "your bank account from the dropdown, and save."
            )

        resolved_bank = service._resolve_account(bank)
        if not resolved_bank:
            raise CommandError(f"Could not resolve bank account '{bank}'.")

        if resolved_bank != bank:
            self.stdout.write(f"Bank account: '{bank}' → '{resolved_bank}'")
            if not dry_run:
                config.bank_account = resolved_bank
                config.save(update_fields=["bank_account"])
        else:
            self.stdout.write(f"Bank account: {resolved_bank}")

        # ── Validate company ─────────────────────────────────────────────────
        try:
            company = service._resolve_company_name()
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"Company: {company}")

        # ── Build queryset ───────────────────────────────────────────────────
        if single_id:
            qs = BankTransaction.objects.filter(pk=single_id)
        else:
            junk_ids = _get_junk_ids()
            qs = (
                BankTransaction.objects
                .filter(
                    category__isnull=False,
                    erpnext_synced=False,
                    category__erpnext_account__isnull=False,
                )
                .exclude(category__erpnext_account="")
                .exclude(category_id__in=junk_ids)
                .select_related("category")
                .order_by("date", "id")
            )
            if limit:
                qs = qs[:limit]

        total = qs.count()
        if total == 0:
            self.stdout.write("No transactions ready to sync.")
            return

        self.stdout.write(f"Syncing {total} transaction(s)…")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be written."))

        # ── Pre-validate category accounts ───────────────────────────────────
        # Each category's erpnext_account should already be a fully qualified
        # name from the preflight form. We resolve anyway to catch any legacy
        # short names and persist the corrected value.
        cat_ids   = list(qs.values_list("category_id", flat=True).distinct())
        cats      = TransactionCategory.objects.filter(pk__in=cat_ids)
        skip_cats = set()

        for cat in cats:
            raw      = (cat.erpnext_account or "").strip()
            resolved = service._resolve_account(raw)

            if not resolved:
                self.stdout.write(
                    self.style.ERROR(f"  SKIP category '{cat.name}': account '{raw}' unresolvable")
                )
                skip_cats.add(cat.pk)
                continue

            if resolved != raw:
                self.stdout.write(f"  Category '{cat.name}': '{raw}' → '{resolved}'")
                if not dry_run:
                    cat.erpnext_account = resolved
                    cat.save(update_fields=["erpnext_account"])

        if skip_cats:
            qs    = qs.exclude(category_id__in=skip_cats)
            total = qs.count()
            self.stdout.write(
                self.style.WARNING(
                    f"{len(skip_cats)} category/ies skipped. "
                    "Use the preflight page to assign valid ERPNext accounts."
                )
            )
            if total == 0:
                self.stdout.write("Nothing left to sync.")
                return

        # ── Sync loop ────────────────────────────────────────────────────────
        synced = failed = skipped = 0

        for txn in qs.iterator():
            desc = f"#{txn.id} [{txn.date}] {str(txn.description or '')[:60]!r}"

            amount = service._extract_amount(txn)
            if amount == 0.0:
                self.stdout.write(f"  SKIP  {desc}: zero amount")
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  DRY   {desc}: would sync {amount:.2f}")
                synced += 1
                continue

            try:
                journal = service.create_journal_entry(txn)
                self.stdout.write(self.style.SUCCESS(f"  OK    {desc}: {journal}"))
                synced += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  FAIL  {desc}: {exc}"))
                failed += 1

        # ── Summary ──────────────────────────────────────────────────────────
        label = "Would sync" if dry_run else "Synced"
        self.stdout.write(
            f"\n{label} {synced}, failed {failed}, skipped {skipped} of {total}."
        )
        if failed:
            raise CommandError(f"{failed} transaction(s) failed.")