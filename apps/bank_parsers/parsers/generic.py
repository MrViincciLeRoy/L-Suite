import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class GenericParser:

    def parse(self, text):
        transactions = []
        patterns = [
            (r'(\d{2}/\d{2}/\d{4})\s*[|]\s*([^|]+?)\s*[|]\s*(-?R?[\d,]+\.\d{2})', '%d/%m/%Y'),
            (r'(\d{2}/\d{2}/\d{4})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%d/%m/%Y'),
            (r'(\d{4}-\d{2}-\d{2})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%Y-%m-%d'),
            (r'(\d{2}\s+\w{3}\s+\d{4})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%d %b %Y'),
        ]
        for pattern, date_fmt in patterns:
            for m in re.findall(pattern, text, re.MULTILINE):
                try:
                    trans_date = datetime.strptime(m[0].strip(), date_fmt).date()
                    description = m[1].strip()
                    amount = float(m[2].replace('R', '').replace('$', '').replace(',', '').strip())
                    if len(description) < 3:
                        continue
                    transactions.append({
                        'date': trans_date,
                        'description': description,
                        'amount': abs(amount),
                        'type': 'debit' if amount < 0 else 'credit',
                        'reference': f"GEN-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                    })
                except (ValueError, IndexError):
                    continue
            if transactions:
                break

        logger.info(f"Generic parser: {len(transactions)} transactions")
        return transactions
