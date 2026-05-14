import logging

from django.core.management.base import BaseCommand, CommandError

from apps.main.models import ERPNextConfig, BankTransaction, BankAccount, TransactionCategory
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
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--transaction-id", type=int, default=0)

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = options["limit"]
        single_id = options["transaction_id"]

        config = ERPNextConfig.objects.filter(is_active=True).first()
        if not config:
            raise CommandError("No active ERPNext configuration found.")

        service = ERPNextService(config)
        ok, msg = service.test_connection()
        if not ok:
            raise CommandError(f"ERPNext connection failed: {msg}")
        self.stdout.write(self.style.SUCCESS(f"Connected: {msg}"))

        # ── Company ──────────────────────────────────────────────────────────
        try:
            company = service._resolve_company_name()
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"Company: {company}")

        # ── Validate BankAccount.erpnext_account for all pending transactions ─
        # The bank side of journal entries now comes from BankAccount.erpnext_account,
        # not from ERPNextConfig.bank_account.
        junk_ids = _get_junk_ids()

        if single_id:
            qs = BankTransaction.objects.filter(pk=single_id).select_related(
                "bank_account", "category"
            )
        else:
            qs = (
                BankTransaction.objects
                .filter(
                    category__isnull=False,
                    erpnext_synced=False,
                    category__erpnext_account__isnull=False,
                )
                .exclude(category__erpnext_account="")
                .exclude(category_id__in=junk_ids)
                .select_related("bank_account", "category")
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
            self.stdout.write(self.style.WARNING("DRY RUN — no changes written."))

        # ── Pre-check: every linked BankAccount must have a valid erpnext_account
        bank_account_ids = list(
            qs.filter(bank_account__isnull=False)
            .values_list("bank_account_id", flat=True)
            .distinct()
        )

        bad_bank_ids = set()
        for ba in BankAccount.objects.filter(pk__in=bank_account_ids):
            acct = (ba.erpnext_account or "").strip()
            if not acct or " - " not in acct:
                self.stdout.write(
                    self.style.ERROR(
                        f"  BankAccount '{ba.account_name}' has no valid ERPNext account "
                        f"(current: '{acct or 'not set'}'). "
                        "Open Sync Preflight to assign one."
                    )
                )
                bad_bank_ids.add(ba.pk)

        if bad_bank_ids:
            # Transactions without a linked bank account use config fallback — allow those.
            # Exclude transactions linked to bad bank accounts.
            qs = qs.exclude(bank_account_id__in=bad_bank_ids)
            total = qs.count()
            self.stdout.write(
                self.style.WARNING(
                    f"{len(bad_bank_ids)} bank account(s) skipped. "
                    f"{total} transaction(s) remaining."
                )
            )
            if total == 0:
                raise CommandError(
                    "No transactions left to sync. Open Sync Preflight and assign "
                    "ERPNext accounts to your bank accounts."
                )

        # ── Pre-check: category expense accounts ──────────────────────────────
        cat_ids = list(qs.values_list("category_id", flat=True).distinct())
        skip_cats = set()

        for cat in TransactionCategory.objects.filter(pk__in=cat_ids):
            raw = (cat.erpnext_account or "").strip()
            if " - " in raw:
                continue
            resolved = service._resolve_account(raw)
            if not resolved or resolved == raw:
                self.stdout.write(
                    self.style.ERROR(f"  SKIP category '{cat.name}': '{raw}' not resolvable")
                )
                skip_cats.add(cat.pk)
            else:
                self.stdout.write(f"  Category '{cat.name}': '{raw}' → '{resolved}'")
                if not dry_run:
                    cat.erpnext_account = resolved
                    cat.save(update_fields=["erpnext_account"])

        if skip_cats:
            qs = qs.exclude(category_id__in=skip_cats)
            total = qs.count()
            if total == 0:
                self.stdout.write("Nothing left to sync.")
                return

        # ── Sync loop ─────────────────────────────────────────────────────────
        synced = failed = skipped = 0

        for txn in qs.iterator():
            desc = f"#{txn.id} [{txn.date}] {str(txn.description or '')[:60]!r}"
            amount = service._extract_amount(txn)

            if amount == 0.0:
                self.stdout.write(f"  SKIP {desc}: zero amount")
                skipped += 1
                continue

            if dry_run:
                bank_label = (
                    txn.bank_account.erpnext_account
                    if txn.bank_account_id
                    else config.bank_account or "config fallback"
                )
                self.stdout.write(f"  DRY  {desc}: {amount:.2f} | bank → {bank_label}")
                synced += 1
                continue

            try:
                journal = service.create_journal_entry(txn)
                self.stdout.write(self.style.SUCCESS(f"  OK   {desc}: {journal}"))
                synced += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  FAIL {desc}: {exc}"))
                failed += 1

        label = "Would sync" if dry_run else "Synced"
        self.stdout.write(f"\n{label} {synced}, failed {failed}, skipped {skipped} of {total}.")

        if failed:
            raise CommandError(f"{failed} transaction(s) failed.")