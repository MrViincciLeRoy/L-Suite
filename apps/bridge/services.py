import logging
from apps.main.models import TransactionCategory, BankTransaction, ERPNextConfig
from apps.erpnext.services import ERPNextService

logger = logging.getLogger(__name__)


try:
    from huggingface_hub import InferenceClient
    import os

    HF_TOKEN = os.environ.get("HUGGINGFACE_API_KEY", "") or os.environ.get("HF_TOKEN", "")
    HF_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    _hf_client = InferenceClient(token=HF_TOKEN) if HF_TOKEN else None
except ImportError:
    _hf_client = None

DEFAULT_CATEGORIES = [
    "Groceries", "Transport", "Entertainment", "Fuel",
    "Food & Dining", "Banking & Finance", "Utilities",
    "Shopping", "Healthcare", "Telecommunications",
]

JUNK_CATEGORY_NAMES = {
    'uncategorised',
    'uncategorized',
    'other',
    'other income',
    'other expense',
    'other expenses',
    'fee fees',
    'terminal) fees',
    '***0) fees',
    'sweep transfer',
    'deposit investments',
    'applied transfer',
    'fnb cellphone',
    'digital payments',
    '4th transfer',
    'received interest',
}

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
    "usave": "Groceries",
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
    "set-off": "Bank Charges",
    "setoff": "Bank Charges",
    "sms payment notification": "Bank Charges",
    "stop payment": "Bank Charges",
    "dishonour": "Bank Charges",
    "unpaid debit": "Bank Charges",
    "debicheck insufficient": "Bank Charges",
    "eft debit order insufficient": "Bank Charges",
    "debicheck authentication": "Bank Charges",
    "insufficient funds": "Bank Charges",
    "earned interest": "Interest Income",
    "interest earned": "Interest Income",
    "interest": "Interest Income",
    "transfer from current": "Savings & Transfers",
    "transfer from savings": "Savings & Transfers",
    "transfer from cheque": "Savings & Transfers",
    "internal transfer": "Savings & Transfers",
    "live better": "Savings Round-up",
    "round-up": "Savings Round-up",
    "round up": "Savings Round-up",
    "transfer to": "Transfer Out",
    "immediate payment": "Transfer Out",
    "ewallet": "Transfer Out",
    "snapscan": "Transfer Out",
    "send money": "Transfer Out",
    "payshap": "Income",
    "transfer received": "Income",
    "received from": "Income",
    "salary": "Income",
    "payroll": "Income",
    "wages": "Income",
}

MIN_ZERO_SHOT_SCORE = 0.2


def _get_junk_category_ids():
    try:
        all_cats = TransactionCategory.objects.values_list('id', 'name')
        return [pk for pk, name in all_cats if name.strip().lower() in JUNK_CATEGORY_NAMES]
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
            .values_list('name', flat=True)
        )
        names = [n for n in names if n.strip().lower() not in JUNK_CATEGORY_NAMES]
        return names if names else DEFAULT_CATEGORIES
    except Exception:
        return DEFAULT_CATEGORIES


def _append_keyword_to_cat(cat: TransactionCategory, keyword: str):
    if not keyword:
        return
    keyword = keyword.strip().lower()
    existing = [k.strip() for k in cat.keywords.split(",") if k.strip()]
    if keyword not in existing:
        existing.append(keyword)
        cat.keywords = ",".join(existing)
        cat.save(update_fields=["keywords"])


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
                "score": top_score,
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
            "score": 1.0,
            "confidence": "Medium",
            "clue_detected": detected_clue,
            "method": "clue_only",
            "top3": [(clue_category, "100.0%")],
        }

    return {
        "raw": transaction,
        "category": "Uncategorized",
        "score": 0.0,
        "confidence": "Low",
        "clue_detected": None,
        "method": "none",
        "top3": [],
    }


def _needs_categorization_qs():
    from django.db.models import Q
    junk_ids = _get_junk_category_ids()
    return BankTransaction.objects.filter(
        Q(category__isnull=True) | Q(category_id__in=junk_ids),
        erpnext_synced=False,
    )


class CategorizationService:

    def _get_processable_transactions(self):
        return _needs_categorization_qs()

    def _find_matching_category(self, transaction, categories):
        if not transaction.description:
            return None
        description_lower = transaction.description.lower()
        for category in categories:
            if category.matches_description(description_lower):
                return category
        return None

    def auto_categorize_all(self):
        transactions = list(self._get_processable_transactions())
        if not transactions:
            return 0, 0

        good_categories = [
            c for c in TransactionCategory.objects.filter(active=True)
            if c.name.strip().lower() not in JUNK_CATEGORY_NAMES
        ]
        category_name_map = {c.name.lower(): c for c in good_categories}

        keyword_count = 0
        ai_count = 0
        no_match = []

        # pass 1: DB keyword/tag match
        for txn in transactions:
            cat = self._find_matching_category(txn, good_categories)
            if cat:
                txn.category = cat
                txn.save()
                keyword_count += 1
            else:
                no_match.append(txn)

        # pass 2: BUILTIN_CLUES fallback — works even without seed_categories
        still_no_match = []
        for txn in no_match:
            desc_lower = (txn.description or "").lower()
            matched_cat_name = None
            matched_clue = None
            for clue, cat_name in BUILTIN_CLUES.items():
                if clue in desc_lower:
                    matched_cat_name = cat_name
                    matched_clue = clue
                    break
            if matched_cat_name:
                t_type = txn.transaction_type or ('credit' if txn.deposit else 'debit')
                cat, _ = TransactionCategory.objects.get_or_create(
                    name=matched_cat_name,
                    defaults={
                        'transaction_type': t_type,
                        'keywords': matched_clue or '',
                        'active': True,
                    },
                )
                if matched_clue:
                    _append_keyword_to_cat(cat, matched_clue)
                txn.category = cat
                txn.save()
                keyword_count += 1
                # refresh good_categories so later txns benefit immediately
                if matched_cat_name.lower() not in category_name_map:
                    category_name_map[matched_cat_name.lower()] = cat
                    good_categories.append(cat)
            else:
                still_no_match.append(txn)
        no_match = still_no_match

        # pass 3: zero-shot for anything still unmatched
        if no_match and _hf_client:
            candidate_labels = [c.name for c in good_categories] or list(set(BUILTIN_CLUES.values()))

            for txn in no_match:
                desc = txn.description or ""
                result = classify_transaction(desc)
                score = result.get("score", 0)
                if score < MIN_ZERO_SHOT_SCORE:
                    logger.info(f"Zero-shot skipped (score={score:.2f}): {desc[:60]}")
                    continue

                predicted_name = result.get("category", "").lower()
                matched_cat = category_name_map.get(predicted_name)

                if matched_cat:
                    txn.category = matched_cat
                    txn.save()
                    ai_count += 1
                    clue = result.get("clue_detected")
                    if not clue:
                        words = desc.lower().split()
                        clue = next((w for w in words if len(w) > 3), words[0] if words else "")
                    if clue:
                        _append_keyword_to_cat(matched_cat, clue)
                    logger.info(f"Zero-shot: {desc[:60]} → {matched_cat.name} [score={score:.2f}, clue={clue!r}]")

        total = len(transactions)
        categorized = keyword_count + ai_count
        logger.info(f"auto_categorize_all: {keyword_count} keyword, {ai_count} zero-shot, {total - categorized} unmatched")
        return categorized, total

    def auto_categorize_with_ai(self):
        categorized, total = self.auto_categorize_all()
        return 0, categorized, total

    def preview_categorization(self):
        transactions = list(self._get_processable_transactions())
        good_categories = [
            c for c in TransactionCategory.objects.filter(active=True)
            if c.name.strip().lower() not in JUNK_CATEGORY_NAMES
        ]

        matches, no_match = [], []
        for transaction in transactions:
            category = self._find_matching_category(transaction, good_categories)
            if category:
                matched_keyword = next(
                    (kw for kw in category.get_keywords_list() if kw in (transaction.description or '').lower()),
                    None,
                )
                matches.append({'transaction': transaction, 'category': category, 'keyword': matched_keyword})
            else:
                # also check BUILTIN_CLUES in preview
                desc_lower = (transaction.description or "").lower()
                clue_hit = next(
                    ((clue, cat_name) for clue, cat_name in BUILTIN_CLUES.items() if clue in desc_lower),
                    None,
                )
                if clue_hit:
                    matches.append({
                        'transaction': transaction,
                        'category': type('_C', (), {'name': clue_hit[1]})(),
                        'keyword': clue_hit[0],
                    })
                else:
                    no_match.append(transaction)

        return {'uncategorized': transactions, 'matches': matches, 'no_match': no_match}

    def suggest_category(self, description):
        if not description:
            return None

        good_categories = [
            c for c in TransactionCategory.objects.filter(active=True)
            if c.name.strip().lower() not in JUNK_CATEGORY_NAMES
        ]

        class _FakeTxn:
            pass

        t = _FakeTxn()
        t.description = description
        db_match = self._find_matching_category(t, good_categories)
        if db_match:
            return db_match

        # BUILTIN_CLUES fallback
        desc_lower = description.lower()
        for clue, cat_name in BUILTIN_CLUES.items():
            if clue in desc_lower:
                cat = TransactionCategory.objects.filter(name=cat_name).first()
                if cat:
                    return cat

        result = classify_transaction(description)
        if result.get("score", 0) >= MIN_ZERO_SHOT_SCORE and result.get("category") != "Uncategorized":
            return result
        return None


class BulkSyncService:
    def __init__(self, erpnext_config):
        self.config = erpnext_config
        self.service = ERPNextService(erpnext_config)

    def _syncable_qs(self):
        junk_ids = _get_junk_category_ids()
        from django.db.models import Q
        return BankTransaction.objects.filter(
            category__isnull=False,
            erpnext_synced=False,
        ).exclude(category_id__in=junk_ids)

    def sync_all_ready(self):
        ready = list(self._syncable_qs())
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
        junk_ids = _get_junk_category_ids()
        transactions = list(BankTransaction.objects.filter(
            category__isnull=False,
            erpnext_synced=False,
            date__gte=start_date,
            date__lte=end_date,
        ).exclude(category_id__in=junk_ids))
        success_count, failed_count = 0, 0
        for transaction in transactions:
            try:
                self.service.create_journal_entry(transaction)
                success_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to sync transaction {transaction.id}: {e}")
        return success_count, failed_count, len(transactions)