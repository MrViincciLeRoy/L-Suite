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

CLUE_MAP = {
    "supermarket": "Groceries",
    "mart": "Groceries",
    "checkers": "Groceries",
    "woolworths": "Groceries",
    "pick n pay": "Groceries",
    "shoprite": "Groceries",
    "spar": "Groceries",
    "food lover": "Groceries",
    "usave": "Groceries",
    "caltex": "Fuel",
    "shell": "Fuel",
    "sasol": "Fuel",
    "engen": "Fuel",
    "petrol": "Fuel",
    "fuel": "Fuel",
    "uber": "Transport",
    "bolt": "Transport",
    "taxi": "Transport",
    "gautrain": "Transport",
    "nando": "Food & Dining",
    "kfc": "Food & Dining",
    "mcdonalds": "Food & Dining",
    "steers": "Food & Dining",
    "wimpy": "Food & Dining",
    "pizza": "Food & Dining",
    "restaurant": "Food & Dining",
    "cafe": "Food & Dining",
    "coffee": "Food & Dining",
    "netflix": "Entertainment",
    "showmax": "Entertainment",
    "dstv": "Entertainment",
    "spotify": "Entertainment",
    "cinema": "Entertainment",
    "dischem": "Healthcare",
    "pharmacy": "Healthcare",
    "clicks": "Healthcare",
    "clinic": "Healthcare",
    "hospital": "Healthcare",
    "doctor": "Healthcare",
    "vodacom": "Telecommunications",
    "mtn": "Telecommunications",
    "telkom": "Telecommunications",
    "airtime": "Telecommunications",
    "recharge": "Telecommunications",
    "eskom": "Utilities",
    "municipality": "Utilities",
    "electricity": "Utilities",
    "water rates": "Utilities",
    "takealot": "Shopping",
    "mr price": "Shopping",
    "pep": "Shopping",
    "ackermans": "Shopping",
    "salary": "Income",
    "payroll": "Income",
    "wages": "Income",
    "payshap": "Income",
    "earned interest": "Interest Income",
    "interest earned": "Interest Income",
    "interest": "Interest Income",
    "transfer from current": "Savings & Transfers",
    "transfer from savings": "Savings & Transfers",
    "internal transfer": "Savings & Transfers",
    "debicheck insufficient": "Bank Charges",
    "eft debit order insufficient": "Bank Charges",
    "debicheck authentication": "Bank Charges",
    "insufficient funds": "Bank Charges",
    "service fee": "Banking & Finance",
    "bank charge": "Banking & Finance",
    "monthly fee": "Banking & Finance",
    "admin fee": "Banking & Finance",
    "client care immediate payment": "Digital Payments",
    "immediate payment": "Digital Payments",
    "round-up": "Savings Round-up",
    "live better": "Savings Round-up",
    "ewallet": "Transfer Out",
    "send money": "Transfer Out",
    "snapscan": "Transfer Out",
}


def _get_junk_ids():
    return [
        pk for pk, name in TransactionCategory.objects.values_list('id', 'name')
        if name.strip().lower() in JUNK_NAMES
    ]


def _needs_categorizing_qs(user_id=None, include_all=False):
    junk_ids = _get_junk_ids()
    if include_all:
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
    for cat in categories:
        if cat.transaction_type != t:
            continue
        if cat.matches_description(txn.description):
            return cat
    return None


def _zero_shot_classify(description, cat_names, hf_token):
    from huggingface_hub import InferenceClient

    client = InferenceClient(token=hf_token)
    desc_lower = description.lower()

    score_boost = {}
    found_clue = None
    for clue, cat_name in CLUE_MAP.items():
        if clue in desc_lower and cat_name in cat_names:
            score_boost[cat_name] = score_boost.get(cat_name, 0) + 0.5
            if not found_clue:
                found_clue = clue

    results = client.zero_shot_classification(
        text=description,
        labels=cat_names,
        model=HF_MODEL_ID,
    )

    score_dict = {r["label"]: r["score"] for r in results}
    for cat_name, boost in score_boost.items():
        if cat_name in score_dict:
            score_dict[cat_name] += boost

    sorted_items = sorted(score_dict.items(), key=lambda x: x[1], reverse=True)
    top_label, top_score = sorted_items[0]
    confidence = "high" if top_score > 0.8 else "medium" if top_score > 0.5 else "low"

    return {
        "category": top_label,
        "score": top_score,
        "confidence": confidence,
        "clue": found_clue,
    }


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


def run_auto_categorize(user_id=None, min_score=0.5):
    from django.conf import settings
    hf_token = settings.HUGGINGFACE_API_KEY

    qs = _needs_categorizing_qs(user_id=user_id)

    for txn in qs.iterator():
        desc = txn.description.strip()
        t = _txn_type(txn)
        good_categories = [
            c for c in TransactionCategory.objects.filter(active=True)
            if c.name.strip().lower() not in JUNK_NAMES
        ]

        matched = _keyword_match(txn, good_categories)
        if matched:
            txn.category = matched
            txn.save(update_fields=["category"])
            continue

        cat_names = [c.name for c in good_categories]
        try:
            result = _zero_shot_classify(desc, cat_names, hf_token)
        except Exception as e:
            logger.error(f"zero-shot failed for '{desc}': {e}")
            continue

        if result["score"] < min_score:
            continue

        clue = result["clue"] or desc.split()[0].lower()
        with transaction.atomic():
            cat = TransactionCategory.objects.filter(name=result["category"]).first()
            if not cat:
                cat = _get_or_create_category(result["category"], t)
            _append_keyword(cat, clue)
            txn.category = cat
            txn.save(update_fields=["category"])


class Command(BaseCommand):
    help = "Auto-categorize: DB keyword match first, then mDeBERTa zero-shot fallback. Includes transactions stuck in placeholder categories."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Re-run on ALL transactions")
        parser.add_argument("--user", type=int, help="Limit to a specific user ID")
        parser.add_argument("--dry-run", action="store_true", help="Print without saving")
        parser.add_argument("--min-score", type=float, default=0.5, help="Minimum zero-shot score (default 0.5)")

    def handle(self, *args, **options):
        from django.conf import settings

        dry = options["dry_run"]
        min_score = options["min_score"]
        hf_token = settings.HUGGINGFACE_API_KEY

        qs = _needs_categorizing_qs(
            user_id=options.get("user"),
            include_all=options["all"],
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
                result = _zero_shot_classify(desc, cat_names, hf_token)
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