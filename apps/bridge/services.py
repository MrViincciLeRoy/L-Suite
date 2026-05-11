import logging
from apps.main.models import TransactionCategory, BankTransaction, ERPNextConfig
from apps.erpnext.services import ERPNextService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AI Classification (HuggingFace zero-shot + DB clue boosting)
# ---------------------------------------------------------------------------

try:
    from huggingface_hub import InferenceClient
    import os

    HF_TOKEN = os.environ.get("HF_TOKEN", "")
    HF_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    _hf_client = InferenceClient(token=HF_TOKEN) if HF_TOKEN else None
except ImportError:
    _hf_client = None

DEFAULT_CATEGORIES = [
    "Groceries", "Transport", "Entertainment", "Fuel",
    "Food & Dining", "Banking & Finance", "Utilities",
    "Shopping", "Healthcare", "Telecommunications",
]

# Category names treated as junk — transactions here get re-processed automatically
JUNK_CATEGORY_NAMES = {
    'uncategorised', 'uncategorized', 'other', 'other income',
    'fee fees', 'terminal) fees', '***0) fees', 'sweep transfer',
    'deposit investments', 'applied transfer', 'fnb cellphone',
    'digital payments', '4th transfer', 'received interest',
}

# Fallback built-in clues — DB clues always take priority over these
BUILTIN_CLUES = {
    "supermarket": "Groceries",
    "mart": "Groceries",
    "checkers": "Groceries",
    "woolworths": "Groceries",
    "tucksho": "Groceries",
    "tuck sho": "Groceries",
    "tuck shop": "Groceries",
    "spaza": "Groceries",
    "pick n pay": "Groceries",
    "spar": "Groceries",
    "s2s*": "Groceries",
    "ccn*": "Groceries",
    "alcohol": "Groceries",
    "caltex": "Fuel",
    "shell": "Fuel",
    "sasol": "Fuel",
    "engen": "Fuel",
    "total": "Fuel",
    "pharmacy": "Healthcare",
    "dischem": "Healthcare",
    "clicks": "Healthcare",
    "clinic": "Healthcare",
    "hospital": "Healthcare",
    "uber": "Transport",
    "bolt": "Transport",
    "taxi": "Transport",
    "netflix": "Entertainment",
    "showmax": "Entertainment",
    "dstv": "Entertainment",
    "spotify": "Entertainment",
    "nando": "Food & Dining",
    "kfc": "Food & Dining",
    "mcdonalds": "Food & Dining",
    "steers": "Food & Dining",
    "wimpy": "Food & Dining",
    "vodacom": "Telecommunications",
    "mtn": "Telecommunications",
    "telkom": "Telecommunications",
    "airtime": "Telecommunications",
    "monthly account admin": "Banking & Finance",
    "branch card replacement": "Banking & Finance",
    "print statement fee": "Banking & Finance",
    "external payment": "Banking & Finance",
    "banking app": "Banking & Finance",
    "fnb": "Banking & Finance",
    "absa": "Banking & Finance",
    "nedbank": "Banking & Finance",
    "standard bank": "Banking & Finance",
    "capitec": "Banking & Finance",
    "eskom": "Utilities",
    "city power": "Utilities",
    "municipality": "Utilities",
    "immediate payment": "Transfer",
}


def _get_junk_category_ids():
    try:
        return list(
            TransactionCategory.objects.filter(
                name__in=JUNK_CATEGORY_NAMES
            ).values_list('id', flat=True)
        )
    except Exception:
        return []


def _build_clue_map():
    clue_map = dict(BUILTIN_CLUES)
    try:
        for cat in TransactionCategory.objects.filter(active=True):
            if cat.name.lower() in JUNK_CATEGORY_NAMES:
                continue
            for kw in cat.get_keywords_list():
                if kw:
                    clue_map[kw.lower().strip()] = cat.name
            if hasattr(cat, 'get_tags_list'):
                for tag in cat.get_tags_list():
                    if tag:
                        clue_map[tag.lower().strip()] = cat.name
    except Exception as e:
        logger.warning(f"Could not load DB clues, using built-ins only: {e}")
    return clue_map


def _get_candidate_labels():
    try:
        names = list(
            TransactionCategory.objects.filter(active=True)
            .exclude(name__in=JUNK_CATEGORY_NAMES)
            .values_list('name', flat=True)
        )
        return names if names else DEFAULT_CATEGORIES
    except Exception:
        return DEFAULT_CATEGORIES


def classify_transaction(transaction: str) -> dict:
    tx_lower = transaction.lower()
    clue_map = _build_clue_map()
    candidate_labels = _get_candidate_labels()

    detected_clue = None
    clue_category = None
    for clue, category in clue_map.items():
        if clue in tx_lower:
            detected_clue = clue
            clue_category = category
            break

    if _hf_client:
        try:
            results = _hf_client.zero_shot_classification(
                text=transaction,
                candidate_labels=candidate_labels,
                model=HF_MODEL_ID,
            )
            score_dict = {r['label']: r['score'] for r in results}

            if clue_category and clue_category in score_dict:
                score_dict[clue_category] = min(score_dict[clue_category] + 0.5, 1.0)

            sorted_items = sorted(score_dict.items(), key=lambda x: x[1], reverse=True)
            top_label, top_score = sorted_items[0]
            confidence = "High" if top_score > 0.8 else "Medium" if top_score > 0.5 else "Low"

            return {
                "raw": transaction,
                "category": top_label,
                "confidence": confidence,
                "clue_detected": detected_clue,
                "method": "hf+clue" if detected_clue else "hf",
                "top3": [(label, f"{score * 100:.1f}%") for label, score in sorted_items[:3]],
            }
        except Exception as e:
            logger.warning(f"HF classification failed, falling back to clue-only: {e}")

    if clue_category:
        return {
            "raw": transaction,
            "category": clue_category,
            "confidence": "Medium",
            "clue_detected": detected_clue,
            "method": "clue_only",
            "top3": [(clue_category, "100.0%")],
        }

    return {
        "raw": transaction,
        "category": "Uncategorized",
        "confidence": "Low",
        "clue_detected": None,
        "method": "none",
        "top3": [],
    }


# ---------------------------------------------------------------------------
# Categorization Service
# ---------------------------------------------------------------------------

class CategorizationService:

    def _get_processable_transactions(self):
        """
        Returns transactions that need categorizing:
        - category is null, OR
        - category is a junk/placeholder category
        Only unsynced transactions are touched.
        """
        junk_ids = _get_junk_category_ids()
        from django.db.models import Q
        return BankTransaction.objects.filter(
            Q(category__isnull=True) | Q(category_id__in=junk_ids),
            erpnext_synced=False,
        )

    def auto_categorize_all(self):
        transactions = list(self._get_processable_transactions())
        if not transactions:
            return 0, 0

        good_categories = list(
            TransactionCategory.objects.filter(active=True)
            .exclude(name__in=JUNK_CATEGORY_NAMES)
        )
        categorized_count = 0

        for transaction in transactions:
            category = self._find_matching_category(transaction, good_categories)
            if category:
                transaction.category = category
                transaction.save()
                categorized_count += 1
                logger.info(f"Auto-categorized transaction {transaction.id} as {category.name}")

        return categorized_count, len(transactions)

    def auto_categorize_with_ai(self):
        """
        Two-pass categorization covering null AND junk-categorized transactions:
          Pass 1 — keyword match from DB
          Pass 2 — HF zero-shot + clue boost for leftovers
        Returns (keyword_count, ai_count, total)
        """
        transactions = list(self._get_processable_transactions())
        if not transactions:
            return 0, 0, 0

        good_categories = list(
            TransactionCategory.objects.filter(active=True)
            .exclude(name__in=JUNK_CATEGORY_NAMES)
        )
        category_name_map = {c.name.lower(): c for c in good_categories}
        keyword_count = 0
        ai_count = 0

        for transaction in transactions:
            category = self._find_matching_category(transaction, good_categories)
            if category:
                transaction.category = category
                transaction.save()
                keyword_count += 1
                continue

            result = classify_transaction(transaction.description or "")
            predicted_name = result.get("category", "").lower()
            matched_cat = category_name_map.get(predicted_name)

            if matched_cat and result.get("confidence") in ("High", "Medium"):
                transaction.category = matched_cat
                transaction.save()
                ai_count += 1
                logger.info(
                    f"AI-categorized {transaction.id} → {matched_cat.name} "
                    f"[{result.get('method')}, {result.get('confidence')}]"
                )

        return keyword_count, ai_count, len(transactions)

    def _find_matching_category(self, transaction, categories):
        if not transaction.description:
            return None
        description_lower = transaction.description.lower()
        for category in categories:
            if category.matches_description(description_lower):
                return category
        return None

    def preview_categorization(self):
        transactions = list(self._get_processable_transactions())
        good_categories = list(
            TransactionCategory.objects.filter(active=True)
            .exclude(name__in=JUNK_CATEGORY_NAMES)
        )

        matches, no_match = [], []
        for transaction in transactions:
            category = self._find_matching_category(transaction, good_categories)
            if category:
                matched_keyword = next(
                    (kw for kw in category.get_keywords_list() if kw in transaction.description.lower()),
                    None,
                )
                matches.append({'transaction': transaction, 'category': category, 'keyword': matched_keyword})
            else:
                no_match.append(transaction)

        return {'uncategorized': transactions, 'matches': matches, 'no_match': no_match}

    def suggest_category(self, description):
        if not description:
            return None

        good_categories = list(
            TransactionCategory.objects.filter(active=True)
            .exclude(name__in=JUNK_CATEGORY_NAMES)
        )

        class _FakeTxn:
            pass

        t = _FakeTxn()
        t.description = description
        db_match = self._find_matching_category(t, good_categories)
        if db_match:
            return db_match

        result = classify_transaction(description)
        if result.get("confidence") in ("High", "Medium") and result.get("category") != "Uncategorized":
            return result
        return None


# ---------------------------------------------------------------------------
# Bulk Sync Service
# ---------------------------------------------------------------------------

class BulkSyncService:
    def __init__(self, erpnext_config):
        self.config = erpnext_config
        self.service = ERPNextService(erpnext_config)

    def sync_all_ready(self):
        ready = list(BankTransaction.objects.filter(
            category__isnull=False,
            erpnext_synced=False,
        ).exclude(category__name__in=JUNK_CATEGORY_NAMES))
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
        ).exclude(category__name__in=JUNK_CATEGORY_NAMES))
        success_count, failed_count = 0, 0
        for transaction in transactions:
            try:
                self.service.create_journal_entry(transaction)
                success_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to sync transaction {transaction.id}: {e}")
        return success_count, failed_count, len(transactions)
