import json
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.main.models import BankTransaction, TransactionCategory

logger = logging.getLogger(__name__)


# ── HF call (mirrors your utils/llm.py hf_call pattern) ────────────────────
def _llm_categorize(description: str, txn_type: str, existing_categories: list) -> dict:
    import requests
    from django.conf import settings

    cats_str = "\n".join(f"- {c}" for c in existing_categories)
    prompt = f"""<s>[INST] You are a South African bank transaction categorizer.

Transaction description: "{description}"
Transaction type: {txn_type} (credit = money in, debit = money out)

Existing categories:
{cats_str}

Task:
1. Pick the BEST matching category from the list above.
2. If none fit, return "NEW" and suggest a short category name.
3. Extract a short keyword (1-3 words) from the description to save for future matching.

Respond ONLY with valid JSON, no markdown, no extra text:
{{
  "category": "<exact category name from list, or NEW>",
  "new_name": "<only if NEW, else empty string>",
  "keyword": "<short keyword>",
  "confidence": <0-100>
}} [/INST]"""

    headers = {"Authorization": f"Bearer {settings.HUGGINGFACE_API_KEY}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 200,
            "temperature": 0.1,
            "return_full_text": False,
        },
    }

    response = requests.post(
        "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2",
        headers=headers,
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    raw = response.json()

    # HF returns list of generated_text
    if isinstance(raw, list):
        text = raw[0].get("generated_text", "")
    else:
        text = raw.get("generated_text", "")

    text = text.strip().replace("```json", "").replace("```", "").strip()

    # extract JSON object in case there's trailing text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON in response: {text[:200]}")

    return json.loads(text[start:end])


# ── helpers ──────────────────────────────────────────────────────────────────
def _txn_type(txn: BankTransaction) -> str:
    return "credit" if (txn.deposit and txn.deposit > 0) else "debit"


def _keyword_match(txn: BankTransaction, categories) -> TransactionCategory | None:
    t = _txn_type(txn)
    for cat in categories:
        if cat.transaction_type != t:
            continue
        if cat.matches_description(txn.description):
            return cat
    return None


def _get_or_create_category(name: str, txn_type: str) -> TransactionCategory:
    cat, _ = TransactionCategory.objects.get_or_create(
        name=name,
        defaults={
            "transaction_type": txn_type,
            "keywords": "",
            "tags": "",
            "active": True,
        },
    )
    return cat


def _append_keyword(cat: TransactionCategory, keyword: str):
    if not keyword:
        return
    keyword = keyword.strip().lower()
    existing = [k.strip() for k in cat.keywords.split(",") if k.strip()]
    if keyword not in existing:
        existing.append(keyword)
        cat.keywords = ",".join(existing)
        cat.save(update_fields=["keywords"])


# ── command ──────────────────────────────────────────────────────────────────
class Command(BaseCommand):
    help = "Auto-categorize transactions: keyword match first, HuggingFace Mistral-7B zero-shot fallback"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Re-run on ALL transactions, not just uncategorized")
        parser.add_argument("--user", type=int, help="Limit to a specific user ID")
        parser.add_argument("--dry-run", action="store_true", help="Print decisions without saving")
        parser.add_argument("--min-confidence", type=int, default=50, help="Minimum LLM confidence to apply (default 50)")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        min_conf = options["min_confidence"]

        qs = BankTransaction.objects.all() if options["all"] else BankTransaction.objects.filter(category__isnull=True)
        if options.get("user"):
            qs = qs.filter(user_id=options["user"])

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to categorize."))
            return

        self.stdout.write(f"Processing {total} transactions...\n")

        keyword_hits = 0
        llm_hits = 0
        llm_new = 0
        llm_skipped = 0
        errors = 0

        for txn in qs.iterator():
            desc = txn.description.strip()
            t = _txn_type(txn)

            # reload categories each iteration so newly created ones are picked up immediately
            categories = list(TransactionCategory.objects.filter(active=True))

            # 1. Fast keyword match — no API call
            matched = _keyword_match(txn, categories)
            if matched:
                if not dry:
                    txn.category = matched
                    txn.save(update_fields=["category"])
                keyword_hits += 1
                self.stdout.write(f"  [KW]  {desc[:60]:<60} → {matched.name}")
                continue

            # 2. HuggingFace Mistral-7B zero-shot
            cat_names = [c.name for c in categories]
            try:
                result = _llm_categorize(desc, t, cat_names)
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  [ERR] {desc[:60]} — {e}"))
                continue

            confidence = result.get("confidence", 0)
            keyword = result.get("keyword", "").strip().lower()
            cat_name = result.get("category", "").strip()
            new_name = result.get("new_name", "").strip()

            if confidence < min_conf:
                llm_skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  [LOW] {desc[:60]:<60} → {cat_name} (conf={confidence})"
                ))
                continue

            if cat_name == "NEW" and new_name:
                if not dry:
                    with transaction.atomic():
                        cat = _get_or_create_category(new_name, t)
                        _append_keyword(cat, keyword)
                        txn.category = cat
                        txn.save(update_fields=["category"])
                llm_new += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  [NEW] {desc[:60]:<60} → {new_name!r} (kw={keyword!r})"
                ))

            elif cat_name in cat_names:
                if not dry:
                    with transaction.atomic():
                        cat = TransactionCategory.objects.get(name=cat_name)
                        _append_keyword(cat, keyword)
                        txn.category = cat
                        txn.save(update_fields=["category"])
                llm_hits += 1
                self.stdout.write(
                    f"  [LLM] {desc[:60]:<60} → {cat_name} (kw={keyword!r}, conf={confidence})"
                )

            else:
                llm_skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"  [???] {desc[:60]:<60} → unrecognized response: {result}"
                ))

        self.stdout.write("\n" + "─" * 70)
        self.stdout.write(self.style.SUCCESS(f"Keyword matches : {keyword_hits}"))
        self.stdout.write(self.style.SUCCESS(f"LLM matches     : {llm_hits}"))
        self.stdout.write(self.style.SUCCESS(f"New categories  : {llm_new}"))
        self.stdout.write(self.style.WARNING(f"Skipped (low conf / unknown): {llm_skipped}"))
        self.stdout.write(self.style.ERROR(f"Errors          : {errors}"))
        if dry:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing was saved."))
