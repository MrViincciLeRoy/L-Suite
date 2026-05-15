import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.main.models import BankTransaction, TransactionCategory

logger = logging.getLogger(__name__)

HF_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"

JUNK_NAMES = {
    'uncategorised', 'uncategorized', 'other', 'other income',
    'other expense', 'other expenses', 'fee fees', 'terminal) fees',
    '***0) fees', 'sweep transfer', 'deposit investments',
    'applied transfer', 'fnb cellphone', 'digital payments',
    '4th transfer', 'received interest',
}

# Maps deposit/withdrawal → category transaction_type values used in DB
TXN_TYPE_MAP = {
    "credit": ("credit", "income"),
    "debit":  ("debit", "expense", "transfer"),
}

CLUE_MAP = {
    "supermarket": "Groceries", "mart": "Groceries", "checkers": "Groceries",
    "woolworths": "Groceries", "pick n pay": "Groceries", "shoprite": "Groceries",
    "spar": "Groceries", "food lover": "Groceries", "usave": "Groceries",
    "caltex": "Fuel", "shell": "Fuel", "sasol": "Fuel", "engen": "Fuel",
    "petrol": "Fuel", "fuel": "Fuel",
    "uber": "Transport", "bolt": "Transport", "taxi": "Transport", "gautrain": "Transport",
    "nando": "Food & Dining", "kfc": "Food & Dining", "mcdonalds": "Food & Dining",
    "steers": "Food & Dining", "wimpy": "Food & Dining", "pizza": "Food & Dining",
    "restaurant": "Food & Dining", "cafe": "Food & Dining", "coffee": "Food & Dining",
    "netflix": "Entertainment", "showmax": "Entertainment", "dstv": "Entertainment",
    "spotify": "Entertainment", "cinema": "Entertainment",
    "dischem": "Healthcare", "pharmacy": "Healthcare", "clicks": "Healthcare",
    "clinic": "Healthcare", "hospital": "Healthcare", "doctor": "Healthcare",
    "vodacom": "Telecommunications", "mtn": "Telecommunications",
    "telkom": "Telecommunications", "airtime": "Telecommunications",
    "recharge": "Telecommunications",
    "eskom": "Utilities", "municipality": "Utilities", "electricity": "Utilities",
    "water rates": "Utilities",
    "takealot": "Shopping", "mr price": "Shopping", "pep": "Shopping",
    "ackermans": "Shopping",
    "salary": "Income", "payroll": "Income", "wages": "Income", "payshap": "Income",
    "earned interest": "Interest Income", "interest earned": "Interest Income",
    "interest": "Interest Income",
    "transfer from current": "Savings & Transfers",
    "transfer from savings": "Savings & Transfers",
    "internal transfer": "Savings & Transfers",
    "debicheck insufficient": "Bank Charges",
    "eft debit order insufficient": "Bank Charges",
    "debicheck authentication": "Bank Charges",
    "insufficient funds": "Bank Charges",
    "service fee": "Banking & Finance", "bank charge": "Banking & Finance",
    "monthly fee": "Banking & Finance", "admin fee": "Banking & Finance",
    "client care immediate payment": "Digital Payments",
    "immediate payment": "Digital Payments",
    "round-up": "Savings Round-up", "live better": "Savings Round-up",
    "ewallet": "Transfer Out", "send money": "Transfer Out", "snapscan": "Transfer Out",
}


def _get_junk_ids():
    return [
        pk for pk, name in TransactionCategory.objects.values_list('id', 'name')
        if name.strip().lower() in JUNK_NAMES
    ]


def _needs_categorizing_qs(user_id=None, include_all=False, force_all=False):
    junk_ids = _get_junk_ids()
    if force_all or include_all:
        qs = BankTransaction.objects.all()
    else:
        qs = BankTransaction.objects.filter(
            Q(category__isnull=True) | Q(category_id__in=junk_ids)
        )
    if user_id:
        qs = qs.filter(user_id=user_id)
    return qs


def _txn_type(txn):
    return "credit" if (txn.deposit and txn.deposit > 0) else "debit"


def _keyword_match(txn, categories):
    t = _txn_type(txn)
    allowed_types = TXN_TYPE_MAP.get(t, (t,))
    for cat in categories:
        if cat.transaction_type not in allowed_types:
            continue
        if cat.matches_description(txn.description):
            return cat
    return None


_classifier = None


def _get_classifier():
    global _classifier
    if _classifier is None:
        from transformers import pipeline
        import torch
        logger.info(f"Loading {HF_MODEL_ID}...")
        _classifier = pipeline(
            "zero-shot-classification",
            model=HF_MODEL_ID,
            device=0 if torch.cuda.is_available() else -1,
        )
        logger.info("Model ready.")
    return _classifier


def _zero_shot_classify(description, cat_names):
    desc_lower = description.lower()
    score_boost = {}
    found_clue = None
    for clue, cat_name in CLUE_MAP.items():
        if clue in desc_lower and cat_name in cat_names:
            score_boost[cat_name] = score_boost.get(cat_name, 0) + 0.5
            if not found_clue:
                found_clue = clue

    classifier = _get_classifier()
    result = classifier(description, cat_names, multi_label=False)
    score_dict = dict(zip(result["labels"], result["scores"]))
    for cat_name, boost in score_boost.items():
        if cat_name in score_dict:
            score_dict[cat_name] += boost

    sorted_items = sorted(score_dict.items(), key=lambda x: x[1], reverse=True)
    top_label, top_score = sorted_items[0]
    confidence = "high" if top_score > 0.8 else "medium" if top_score > 0.5 else "low"
    return {"category": top_label, "score": top_score, "confidence": confidence, "clue": found_clue}


def _get_or_create_category(name, txn_type):
    cat, _ = TransactionCategory.objects.get_or_create(
        name=name,
        defaults={"transaction_type": txn_type, "keywords": "", "tags": "", "active": True},
    )
    return cat


def _append_keyword(cat, keyword):
    if not keyword:
        return
    keyword = keyword.strip().lower()
    existing = [k.strip() for k in cat.keywords.split(",") if k.strip()]
    if keyword not in existing:
        existing.append(keyword)
        cat.keywords = ",".join(existing)
        cat.save(update_fields=["keywords"])


class Command(BaseCommand):
    help = "Auto-categorize transactions. Keyword match first, then mDeBERTa zero-shot fallback."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Re-run on all transactions")
        parser.add_argument("--force-all", action="store_true",
                            help="Wipe categories on ALL transactions and re-categorize everything from scratch")
        parser.add_argument("--user", type=int, help="Limit to a specific user ID")
        parser.add_argument("--dry-run", action="store_true", help="Print without saving")
        parser.add_argument("--min-score", type=float, default=0.2,
                            help="Minimum zero-shot score (default 0.2)")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        min_score = options["min_score"]
        force_all = options["force_all"]
        user_id = options.get("user")

        if force_all:
            self.stdout.write(self.style.WARNING(
                "⚠  FORCE ALL — wiping categories on ALL transactions before re-categorizing..."
            ))
            wipe_qs = BankTransaction.objects.filter(erpnext_synced=False)
            if user_id:
                wipe_qs = wipe_qs.filter(user_id=user_id)
            if not dry:
                wiped = wipe_qs.update(category=None)
                self.stdout.write(f"   Cleared category on {wiped} transaction(s).")
            else:
                self.stdout.write(f"   DRY: would clear {wipe_qs.count()} transaction(s).")

        qs = _needs_categorizing_qs(
            user_id=user_id,
            include_all=options["all"],
            force_all=force_all,
        )

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to categorize."))
            return

        self.stdout.write(f"Processing {total} transactions...\n")

        good_categories = [
            c for c in TransactionCategory.objects.filter(active=True)
            if c.name.strip().lower() not in JUNK_NAMES
        ]

        if not good_categories:
            self.stdout.write(self.style.ERROR(
                "No valid categories found. Run: python manage.py seed_categories"
            ))
            return

        cat_names = [c.name for c in good_categories]
        keyword_hits = llm_hits = llm_new = llm_skipped = errors = 0

        for txn in qs.iterator():
            desc = txn.description.strip()
            t = _txn_type(txn)

            matched = _keyword_match(txn, good_categories)
            if matched:
                if not dry:
                    txn.category = matched
                    txn.save(update_fields=["category"])
                keyword_hits += 1
                self.stdout.write(f"  [KW]  {desc[:60]:<60} → {matched.name}")
                continue

            try:
                result = _zero_shot_classify(desc, cat_names)
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  [ERR] {desc[:60]} — {e}"))
                continue

            score = result["score"]
            cat_name = result["category"]
            confidence = result["confidence"]
            clue = result["clue"] or desc.split()[0].lower()

            if score < min_score:
                llm_skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  [LOW] {desc[:60]:<60} → {cat_name} ({confidence}, {score:.2f})"
                ))
                continue

            is_new = score < 0.35 and not result["clue"]
            final_name = desc.split()[0].title() if is_new else cat_name

            if not dry:
                with transaction.atomic():
                    cat = TransactionCategory.objects.filter(name=final_name).first()
                    if not cat:
                        cat = _get_or_create_category(final_name, t)
                    _append_keyword(cat, clue)
                    txn.category = cat
                    txn.save(update_fields=["category"])

            if is_new:
                llm_new += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  [NEW] {desc[:60]:<60} → {final_name!r} (kw={clue!r})"
                ))
            else:
                llm_hits += 1
                self.stdout.write(
                    f"  [ZS]  {desc[:60]:<60} → {cat_name} ({confidence}, clue={clue!r})"
                )

        self.stdout.write("\n" + "─" * 70)
        self.stdout.write(self.style.SUCCESS(f"Keyword matches    : {keyword_hits}"))
        self.stdout.write(self.style.SUCCESS(f"Zero-shot matches  : {llm_hits}"))
        self.stdout.write(self.style.SUCCESS(f"New categories     : {llm_new}"))
        self.stdout.write(self.style.WARNING(f"Skipped (low score): {llm_skipped}"))
        self.stdout.write(self.style.ERROR(f"Errors             : {errors}"))
        if dry:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing was saved."))