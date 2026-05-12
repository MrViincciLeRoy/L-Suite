import csv
import io
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


class CSVParser:

    def parse_csv(self, csv_data, encoding='utf-8'):
        transactions = []
        try:
            if isinstance(csv_data, bytes):
                csv_text = csv_data.decode(encoding, errors='ignore')
            else:
                csv_text = csv_data

            reader = csv.DictReader(io.StringIO(csv_text))
            for row in reader:
                try:
                    txn = self._parse_row(row)
                    if txn:
                        transactions.append(txn)
                except Exception as e:
                    logger.warning(f"Failed to parse CSV row: {e}")
        except Exception as e:
            logger.error(f"CSV parsing error: {e}")
            raise

        logger.info(f"CSV: parsed {len(transactions)} transactions")
        return transactions

    def parse_csv_file(self, file_path):
        with open(file_path, 'rb') as f:
            return self.parse_csv(f.read())

    def _parse_row(self, row):
        row = {k.strip(): v.strip() if v else None for k, v in row.items()}

        transaction_date = self._parse_date(row.get('Transaction Date'))
        if not transaction_date:
            return None

        description = (row.get('Description') or '').strip()
        if len(description) < 2:
            return None
        if 'Transaction Date' in description or 'Description' in description:
            return None

        return {
            'transaction_date': transaction_date,
            'posting_date':     self._parse_date(row.get('Posting Date')),
            'description':      description,
            'debits':           self._parse_amount(row.get('Debits')),
            'credits':          self._parse_amount(row.get('Credits')),
            'balance':          self._parse_amount(row.get('Balance')),
            'bank_account':     (row.get('Bank account') or '').strip(),
            'reference':        self._make_ref(description, transaction_date),
        }

    def _parse_date(self, date_str):
        if not date_str:
            return None
        for fmt in ('%Y/%m/%d', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        logger.warning(f"Could not parse date: {date_str}")
        return None

    def _parse_amount(self, amount_str):
        if not amount_str:
            return None
        try:
            cleaned = amount_str.replace('R', '').replace(',', '').replace(' ', '').strip()
            return Decimal(cleaned) if cleaned and cleaned != '-' else None
        except Exception as e:
            logger.warning(f"Could not parse amount '{amount_str}': {e}")
            return None

    def _make_ref(self, description, date):
        first_word = description.split()[0][:10] if description else 'TXN'
        date_str   = date.strftime('%Y%m%d') if date else 'NODATE'
        return f"{first_word}-{date_str}"
