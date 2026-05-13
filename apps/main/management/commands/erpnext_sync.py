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


def _resolve_bank_from_accounts(service, raw):
    """
    _resolve_account() silently returns the raw string on failure — you can't
    tell "found" from "not found".  This does a definitive lookup against the
    full chart of accounts and returns (resolved_name | None, all_accounts).
    """
    all_accounts = service.get_chart_of_accounts()

    # Exact match
    for a in all_accounts:
        if a['name'] == raw:
            return a['name'], all_accounts

    # Case-insensitive partial match
    raw_lower = raw.lower()
    matches = [a for a in all_accounts if raw_lower in a['name'].lower() and not a.get('is_group')]
    if len(matches) == 1:
        return matches[0]['name'], all_accounts
    if len(matches) > 1:
        bank_matches = [a for a in matches if a.get('account_type') == 'Bank']
        return (bank_matches or matches)[0]['name'], all_accounts

    return None, all_accounts


class Command(BaseCommand):
    help = "Sync categorised bank transactions to ERPNext as Journal Entries"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Validate only, no writes")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--transaction-id", type=int, default=0)

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

        # ── Company ───────────────────────────────────────────────────────────
        try:
            company = service._resolve_company_name()
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f"Company: {company}")

        # ── Bank account ──────────────────────────────────────────────────────
        raw_bank = (config.bank_account or "").strip()
        if not raw_bank:
            raise CommandError(
                "bank_account is not set. Open the Sync Preflight page and select one."
            )

        if " - " in raw_bank:
            # Already fully qualified — trust it
            resolved_bank = raw_bank
            self.stdout.write(f"Bank account: {resolved_bank}")
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"'{raw_bank}' is not a fully qualified ERPNext account name. Searching…"
                )
            )
            resolved_bank, all_accounts = _resolve_bank_from_accounts(service, raw_bank)

            if not resolved_bank:
                candidates = sorted(
                    a['name'] for a in all_accounts
                    if not a.get('is_group') and a.get('account_type') in ('Bank', 'Cash')
                )
                if not candidates:
                    candidates = sorted(
                        a['name'] for a in all_accounts
                        if not a.get('is_group') and a.get('root_type') == 'Asset'
                    )[:20]
                self.stdout.write(
                    self.style.ERROR(f"No ERPNext account matches '{raw_bank}'.")
                )
                self.stdout.write("Available Bank/Cash accounts:")
                for c in candidates:
                    self.stdout.write(f"  {c}")
                raise CommandError(
                    f"Could not resolve bank account '{raw_bank}'. "
                    "Open Sync Preflight, pick the correct account from the dropdown, save, then retry."
                )

            self.stdout.write(
                self.style.SUCCESS(f"Bank account resolved: '{raw_bank}' → '{resolved_bank}'")
            )
            if not dry_run:
                config.bank_account = resolved_bank
                config.save(update_fields=["bank_account"])

        # Override on the in-memory config so create_journal_entry uses the right name
        # even before the DB save propagates (and in dry-run mode).
        config.bank_account = resolved_bank

        # ── Queryset ──────────────────────────────────────────────────────────
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

        # ── Pre-resolve category expense accounts ─────────────────────────────
        cat_ids   = list(qs.values_list("category_id", flat=True).distinct())
        cats      = TransactionCategory.objects.filter(pk__in=cat_ids)
        skip_cats = set()

        for cat in cats:
            raw = (cat.erpnext_account or "").strip()
            if " - " in raw:
                continue  # already qualified, trust it

            resolved = service._resolve_account(raw)
            if not resolved or resolved == raw:
                self.stdout.write(
                    self.style.ERROR(f"  SKIP category '{cat.name}': '{raw}' not resolvable")
                )
                skip_cats.add(cat.pk)
                continue

            self.stdout.write(f"  Category '{cat.name}': '{raw}' → '{resolved}'")
            if not dry_run:
                cat.erpnext_account = resolved
                cat.save(update_fields=["erpnext_account"])

        if skip_cats:
            qs    = qs.exclude(category_id__in=skip_cats)
            total = qs.count()
            self.stdout.write(
                self.style.WARNING(f"{len(skip_cats)} category/ies skipped (unresolvable account).")
            )
            if total == 0:
                self.stdout.write("Nothing left to sync.")
                return

        # ── Sync loop ─────────────────────────────────────────────────────────
        synced = failed = skipped = 0

        for txn in qs.iterator():
            desc   = f"#{txn.id} [{txn.date}] {str(txn.description or '')[:60]!r}"
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

        label = "Would sync" if dry_run else "Synced"
        self.stdout.write(f"\n{label} {synced}, failed {failed}, skipped {skipped} of {total}.")
        if failed:
            raise CommandError(f"{failed} transaction(s) failed.")