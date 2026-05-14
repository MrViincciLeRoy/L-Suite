from decimal import Decimal
from datetime import timedelta
from .models import ERPNextJournalEntry, ReconciliationMatch
from apps.main.models import BankTransaction

DATE_TOLERANCE = 2   # days
AMOUNT_TOLERANCE = Decimal('0.05')  # slightly wider than R0.01 — bank rounding


def _amounts_match(a, b):
    return abs(a - b) <= AMOUNT_TOLERANCE


def _dates_close(d1, d2):
    return abs((d1 - d2).days) <= DATE_TOLERANCE


def run_matching(user, year, month):
    from calendar import monthrange

    if ReconciliationPeriod_is_closed(user, year, month):
        return {'matched': 0, 'flagged': 0, 'skipped': 0, 'error': 'Period is closed'}

    transactions = BankTransaction.objects.filter(
        user=user,
        date__year=year,
        date__month=month,
        recon_status='unreconciled',
    )
    journal_entries = ERPNextJournalEntry.objects.filter(
        user=user,
        posting_date__year=year,
        posting_date__month=month,
    )

    je_pool = list(journal_entries)
    used_je_ids = set()
    results = {'matched': 0, 'flagged': 0, 'skipped': 0}

    for txn in transactions:
        best = None
        best_score = 0

        for je in je_pool:
            if je.id in used_je_ids:
                continue

            score = 0
            if _amounts_match(abs(txn.amount or 0), abs(je.amount)):
                score += 3
            if _dates_close(txn.date, je.posting_date):
                score += 2
            if txn.reference_number and txn.reference_number == je.reference_number:
                score += 5

            if score > best_score:
                best_score = score
                best = je

        if best and best_score >= 3:
            ReconciliationMatch.objects.update_or_create(
                transaction=txn,
                defaults={
                    'user': user,
                    'journal_entry': best,
                    'status': 'matched',
                    'flag_reason': '',
                    'matched_by': 'auto',
                },
            )
            txn.recon_status = 'matched'
            txn.save(update_fields=['recon_status'])
            used_je_ids.add(best.id)
            results['matched'] += 1
        else:
            flag_reason = _determine_flag_reason(txn, je_pool, used_je_ids)
            ReconciliationMatch.objects.update_or_create(
                transaction=txn,
                defaults={
                    'user': user,
                    'journal_entry': None,
                    'status': 'flagged',
                    'flag_reason': flag_reason,
                    'matched_by': 'auto',
                },
            )
            txn.recon_status = 'flagged'
            txn.save(update_fields=['recon_status'])
            results['flagged'] += 1

    return results


def _determine_flag_reason(txn, je_pool, used_je_ids):
    available = [je for je in je_pool if je.id not in used_je_ids]
    if not available:
        return "No journal entries found for this period."
    txn_amount = abs(txn.amount or 0)
    amount_match = [je for je in available if _amounts_match(txn_amount, abs(je.amount))]
    if not amount_match:
        return f"No journal entry found with matching amount (R {txn_amount})."
    return "Amount found but date or reference mismatch — review manually."


def ReconciliationPeriod_is_closed(user, year, month):
    from .models import ReconciliationPeriod
    return ReconciliationPeriod.objects.filter(
        user=user, year=year, month=month, status='closed'
    ).exists()