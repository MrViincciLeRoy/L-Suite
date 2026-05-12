import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _safe_amt(s):
    if not s or s == '-':
        return 0
    try:
        v = float(s.replace(',', '').strip())
        return v if v <= 10_000_000 else 0
    except (ValueError, AttributeError):
        return 0


class TymeBankLegacyParser:

    def parse(self, text):
        transactions = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            date_match = re.match(r'^(\d{1,2}\s+\w{3}\s+\d{4})\s+(.+)', line)

            if date_match:
                try:
                    trans_date = datetime.strptime(date_match.group(1), '%d %b %Y').date()
                    rest = date_match.group(2).strip()
                    description_parts = [rest]
                    j = i + 1
                    amounts_found = False
                    fees = money_out = money_in = None

                    AMT  = r'(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?'
                    DASH = r'-'
                    SLOT = f'({DASH}|{AMT})'
                    LAST = f'({AMT})'

                    four_col = re.compile(rf'^{SLOT}\s+{SLOT}\s+{SLOT}\s+{LAST}\s*$')
                    full_inline = re.compile(rf'^(.+?)\s+{SLOT}\s+{SLOT}\s+{SLOT}\s+{LAST}\s*$')

                    while j < len(lines) and j < i + 6:
                        nxt = lines[j].strip()
                        if re.match(r'^\d{1,2}\s+\w{3}\s+\d{4}', nxt):
                            break

                        m4 = four_col.match(nxt)
                        if m4:
                            fees, money_out, money_in = m4.group(1), m4.group(2), m4.group(3)
                            amounts_found = True
                            i = j
                            break

                        mi = full_inline.search(nxt)
                        if mi:
                            description_parts.append(mi.group(1).strip())
                            fees, money_out, money_in = mi.group(2), mi.group(3), mi.group(4)
                            amounts_found = True
                            i = j
                            break

                        if nxt and not re.match(r'^\d{10,}$', nxt) and not nxt.startswith('-'):
                            description_parts.append(nxt)
                        j += 1

                    if not amounts_found:
                        mi = full_inline.search(rest)
                        if mi:
                            description_parts = [mi.group(1).strip()]
                            fees, money_out, money_in = mi.group(2), mi.group(3), mi.group(4)
                            amounts_found = True

                    if amounts_found:
                        description = ' '.join(' '.join(description_parts).split())
                        if len(description) < 3 or 'Description' in description or 'Money Out' in description:
                            i += 1
                            continue

                        amount, trans_type = 0, 'debit'
                        mi_val = _safe_amt(money_in)
                        if mi_val > 0:
                            amount, trans_type = mi_val, 'credit'
                        mo_val = _safe_amt(money_out)
                        if amount == 0 and mo_val > 0:
                            amount, trans_type = mo_val, 'debit'
                        fe_val = _safe_amt(fees)
                        if amount == 0 and fe_val > 0:
                            amount, trans_type = fe_val, 'debit'
                            description += ' (Fee)'

                        if amount > 0:
                            transactions.append({
                                'date':        trans_date,
                                'description': description,
                                'amount':      amount,
                                'type':        trans_type,
                                'reference':   f"TYME-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                            })
                except (ValueError, IndexError) as e:
                    logger.warning(f"TymeBank legacy row error: {e}")
            i += 1

        logger.info(f"TymeBank legacy: {len(transactions)} transactions")
        return transactions
