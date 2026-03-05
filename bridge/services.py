import logging
from main.models import TransactionCategory, BankTransaction
from erpnext.services import ERPNextService

logger = logging.getLogger(__name__)


class CategorizationService:
    def auto_categorize_all(self):
        uncategorized = list(BankTransaction.objects.filter(category__isnull=True, erpnext_synced=False))
        if not uncategorized:
            return 0, 0

        categories = list(TransactionCategory.objects.filter(active=True))
        categorized_count = 0

        for transaction in uncategorized:
            category = self._find_matching_category(transaction, categories)
            if category:
                transaction.category = category
                transaction.save()
                categorized_count += 1
                logger.info(f"Auto-categorized transaction {transaction.id} as {category.name}")

        return categorized_count, len(uncategorized)

    def _find_matching_category(self, transaction, categories):
        if not transaction.description:
            return None
        description_lower = transaction.description.lower()
        for category in categories:
            if category.matches_description(description_lower):
                return category
        return None

    def preview_categorization(self):
        uncategorized = list(BankTransaction.objects.filter(category__isnull=True, erpnext_synced=False))
        categories = list(TransactionCategory.objects.filter(active=True))

        matches, no_match = [], []

        for transaction in uncategorized:
            category = self._find_matching_category(transaction, categories)
            if category:
                matched_keyword = next(
                    (kw for kw in category.get_keywords_list() if kw in transaction.description.lower()),
                    None,
                )
                matches.append({'transaction': transaction, 'category': category, 'keyword': matched_keyword})
            else:
                no_match.append(transaction)

        return {'uncategorized': uncategorized, 'matches': matches, 'no_match': no_match}

    def suggest_category(self, description):
        if not description:
            return None
        categories = list(TransactionCategory.objects.filter(active=True))

        class _FakeTxn:
            pass

        t = _FakeTxn()
        t.description = description
        return self._find_matching_category(t, categories)


class BulkSyncService:
    def __init__(self, erpnext_config):
        self.config = erpnext_config
        self.service = ERPNextService(erpnext_config)

    def sync_all_ready(self):
        ready = list(BankTransaction.objects.filter(category__isnull=False, erpnext_synced=False))
        if not ready:
            return 0, 0, 0

        success_count, failed_count = 0, 0
        for transaction in ready:
            try:
                self.service.create_journal_entry(transaction)
                success_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to sync transaction {transaction.id}: {e}")

        return success_count, failed_count, len(ready)

    def sync_by_category(self, category_id):
        transactions = list(BankTransaction.objects.filter(category_id=category_id, erpnext_synced=False))
        success_count, failed_count = 0, 0
        for transaction in transactions:
            try:
                self.service.create_journal_entry(transaction)
                success_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to sync transaction {transaction.id}: {e}")
        return success_count, failed_count, len(transactions)

    def sync_by_date_range(self, start_date, end_date):
        transactions = list(BankTransaction.objects.filter(
            category__isnull=False,
            erpnext_synced=False,
            date__gte=start_date,
            date__lte=end_date,
        ))
        success_count, failed_count = 0, 0
        for transaction in transactions:
            try:
                self.service.create_journal_entry(transaction)
                success_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to sync transaction {transaction.id}: {e}")
        return success_count, failed_count, len(transactions)
