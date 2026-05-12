import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS = [
    'Income', 'Savings', 'Withdrawal', 'Transfer', 'Payments',
    'Cellphone', 'Uncategorised', 'Investments', 'Fees', 'Interest',
]
CREDIT_KW = ['payment received', 'received', 'deposit', 'interest received', 'transfer received', 'refund']
DEBIT_KW  = ['payment:', 'sent', 'cash sent', 'withdrawal', 'purchase', 'transfer to', 'prepaid', 'voucher', 'debicheck']


def _amt(s):
    if not s or s == '-':
        return 0.0
    try:
        return float(s.replace(',', '').strip())
    except (ValueError, AttributeError):
        return 0.0


class CapitecParser:

    def parse(self, text):
        transactions = []
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or any(skip in line for skip in ('Transaction History', 'Money In', 'Money Out')):
                i += 1
                continue

            date_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(.+)', line)
            if date_match:
                try:
                    trans_date = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
                    rest = date_match.group(2).strip()

                    three_re = re.search(
                        r'(.+?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$',
                        rest
                    )
                    two_re = re.search(
                        r'(.+?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$',
                        rest
                    )

                    if three_re:
                        desc_and_cat = three_re.group(1).strip()
                        trans_amount = _amt(three_re.group(2))
                        fee          = _amt(three_re.group(3))
                        balance      = _amt(three_re.group(4))
                    elif two_re:
                        desc_and_cat = two_re.group(1).strip()
                        trans_amount = _amt(two_re.group(2))
                        fee, balance = 0.0, _amt(two_re.group(3))
                    else:
                        # try next line for amounts
                        if i + 1 < len(lines):
                            nxt = lines[i + 1].strip()
                            nxt_m = re.match(
                                r'^(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$',
                                nxt
                            )
                            if nxt_m:
                                trans_amount = _amt(nxt_m.group(1))
                                balance = _amt(nxt_m.group(2))
                                fee, desc_and_cat = 0.0, rest
                                i += 1
                            else:
                                i += 1
                                continue
                        else:
                            i += 1
                            continue

                    parts = desc_and_cat.split()
                    category, description = None, desc_and_cat
                    for idx in range(len(parts) - 1, -1, -1):
                        if parts[idx] in CATEGORY_KEYWORDS:
                            prev_not_kw = idx > 0 and parts[idx - 1] not in CATEGORY_KEYWORDS
                            category    = (parts[idx - 1] + ' ' + parts[idx]) if prev_not_kw else parts[idx]
                            description = ' '.join(parts[:idx - 1] if prev_not_kw else parts[:idx])
                            break

                    desc_lower = description.lower()
                    if any(k in desc_lower for k in CREDIT_KW):
                        is_credit = True
                    elif any(k in desc_lower for k in DEBIT_KW):
                        is_credit = False
                    elif trans_amount < 0:
                        is_credit, trans_amount = False, abs(trans_amount)
                    else:
                        is_credit = 'income' in (category or '').lower() or 'received' in (category or '').lower()

                    if abs(trans_amount) > 0 and len(description) >= 3:
                        transactions.append({
                            'date':        trans_date,
                            'description': description.strip(),
                            'amount':      abs(trans_amount),
                            'type':        'credit' if is_credit else 'debit',
                            'reference':   f"CAP-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                            'category':    category,
                            'fee':         abs(fee) if fee else 0.0,
                            'balance':     balance,
                        })
                except (ValueError, IndexError) as e:
                    logger.warning(f"Capitec row error: {e}")
            i += 1

        logger.info(f"Capitec: {len(transactions)} transactions")
        return transactions
