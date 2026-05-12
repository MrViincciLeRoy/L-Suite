"""
PDF Parser - Extract transactions from bank statement PDFs
"""
import io
import os
import shutil
from pathlib import Path
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class PDFParser:
    
    def parse_pdf(self, pdf_data, bank_name, password=None):
        text = self._extract_text_from_pdf(pdf_data, password)
        logger.info(f"Extracted text length: {len(text)} characters")
        logger.debug(f"First 500 chars: {text[:500]}")
        
        if bank_name == 'tymebank':
            return self._parse_tymebank(text)
        elif bank_name == 'capitec':
            return self._parse_capitec(text)
        else:
            return self._parse_generic(text)
    
    def _extract_text_from_pdf(self, pdf_data, password=None):
        text = ""
        try:
            import PyPDF2
            pdf_file = io.BytesIO(pdf_data)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            if pdf_reader.is_encrypted:
                if not password:
                    raise ValueError("PDF is password protected but no password provided")
                decrypt_result = pdf_reader.decrypt(password)
                if decrypt_result == 0:
                    raise ValueError("Incorrect PDF password")
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            logger.info(f"Extracted {len(text)} characters using PyPDF2")
        except ImportError:
            try:
                import pdfplumber
                pdf_file = io.BytesIO(pdf_data)
                with pdfplumber.open(pdf_file, password=password) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                logger.info(f"Extracted {len(text)} characters using pdfplumber")
            except ImportError:
                raise ImportError("No PDF library available. Install PyPDF2 or pdfplumber")
        return text

    def _parse_tymebank(self, text):
        """
        Handles both GoTyme/TymeBank formats:

        Format A (old) ? 4 columns after date:
          Date  Description  Fees  MoneyOut  MoneyIn  Balance

        Format B (new GoTyme table) ? 3 columns after date:
          Date  Details  Credits(+)  Debits(-)  RunningBalance

        Detection: if "Credits (+)" or "Running Balance" appears in the text ? Format B.
        """
        if 'Credits (+)' in text or 'Running Balance' in text or 'Debits (-)' in text:
            return self._parse_gotyme_table(text)
        return self._parse_tymebank_legacy(text)

    def _parse_gotyme_table(self, text):
        """
        GoTyme Bank statement ? table format:
          Date        Details                          Credits (+)  Debits (-)  Running Balance
          15 Dec 2025 Transfer from Current account   1,000        -           1,000.37
          16 Dec 2025 Transfer to Current account     -            700         300.37
          01 Jan 2026 Earned interest                 0.28         -           0.65
        """
        transactions = []
        lines = text.split('\n')

        # Amount pattern: digits with optional commas/decimals, or a dash
        AMT = r'(?:\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)'
        DASH = r'-'
        COL = r'\s+'

        # Row pattern: date, description, credit, debit, balance
        row_re = re.compile(
            r'^(\d{1,2}\s+\w{3}\s+\d{4})\s+'   # date
            r'(.+?)\s+'                           # description (non-greedy)
            r'(' + AMT + r'|' + DASH + r')' + COL +  # credit
            r'(' + AMT + r'|' + DASH + r')' + COL +  # debit
            r'(' + AMT + r')\s*$'                # running balance
        )

        for line in lines:
            line = line.strip()
            if not line:
                continue

            m = row_re.match(line)
            if not m:
                continue

            date_str = m.group(1)
            description = m.group(2).strip()
            credit_str = m.group(3).strip()
            debit_str = m.group(4).strip()
            balance_str = m.group(5).strip()

            # Skip header rows
            if 'Details' in description or 'Description' in description:
                continue
            if len(description) < 2:
                continue

            try:
                trans_date = datetime.strptime(date_str, '%d %b %Y').date()
            except ValueError:
                continue

            def parse_amt(s):
                if not s or s == '-':
                    return 0.0
                try:
                    return float(s.replace(',', ''))
                except ValueError:
                    return 0.0

            credit = parse_amt(credit_str)
            debit = parse_amt(debit_str)
            balance = parse_amt(balance_str)

            if credit > 0:
                amount = credit
                trans_type = 'credit'
            elif debit > 0:
                amount = debit
                trans_type = 'debit'
            else:
                continue

            transactions.append({
                'date': trans_date,
                'description': description,
                'amount': amount,
                'type': trans_type,
                'reference': f"TYME-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                'balance': balance,
            })
            logger.debug(f"GoTyme: {description[:40]} = {amount} ({trans_type})")

        if not transactions:
            logger.warning("No transactions found with GoTyme table pattern")
            logger.debug(f"Text sample:\n{text[:1000]}")
        else:
            logger.info(f"Parsed {len(transactions)} GoTyme transactions")

        return transactions

    def _parse_tymebank_legacy(self, text):
        """
        Old TymeBank format:
        Date Description Fees Money Out Money In Balance
        Multi-line: description on one line, amounts on next.
        """
        transactions = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            date_match = re.match(r'^(\d{1,2}\s+\w{3}\s+\d{4})\s+(.+)', line)

            if date_match:
                try:
                    date_str = date_match.group(1)
                    rest_of_line = date_match.group(2).strip()
                    trans_date = datetime.strptime(date_str, '%d %b %Y').date()
                    description_parts = [rest_of_line]
                    j = i + 1
                    amounts_found = False
                    fees = money_out = money_in = balance = None

                    while j < len(lines) and j < i + 6:
                        next_line = lines[j].strip()
                        if re.match(r'^\d{1,2}\s+\w{3}\s+\d{4}', next_line):
                            break

                        amount_pattern = (
                            r'^(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                            r'(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                            r'(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                            r'((?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s*$'
                        )
                        amount_match = re.match(amount_pattern, next_line)

                        if amount_match:
                            fees = amount_match.group(1).strip()
                            money_out = amount_match.group(2).strip()
                            money_in = amount_match.group(3).strip()
                            balance = amount_match.group(4).strip()
                            amounts_found = True
                            i = j
                            break
                        else:
                            inline_pattern = (
                                r'(.+?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                                r'(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                                r'(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                                r'((?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s*$'
                            )
                            inline_match = re.search(inline_pattern, next_line)
                            if inline_match:
                                description_parts.append(inline_match.group(1).strip())
                                fees = inline_match.group(2).strip()
                                money_out = inline_match.group(3).strip()
                                money_in = inline_match.group(4).strip()
                                balance = inline_match.group(5).strip()
                                amounts_found = True
                                i = j
                                break
                            else:
                                if next_line and not re.match(r'^\d{10,}$', next_line):
                                    if len(next_line) > 0 and not next_line.startswith('-'):
                                        description_parts.append(next_line)
                        j += 1

                    if not amounts_found:
                        same_line_pattern = (
                            r'(.+?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                            r'(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                            r'(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+'
                            r'((?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s*$'
                        )
                        same_line_match = re.search(same_line_pattern, rest_of_line)
                        if same_line_match:
                            description_parts = [same_line_match.group(1).strip()]
                            fees = same_line_match.group(2).strip()
                            money_out = same_line_match.group(3).strip()
                            money_in = same_line_match.group(4).strip()
                            balance = same_line_match.group(5).strip()
                            amounts_found = True

                    if amounts_found:
                        description = ' '.join(description_parts)
                        description = ' '.join(description.split())

                        if len(description) < 3 or 'Description' in description or 'Money Out' in description:
                            i += 1
                            continue

                        def parse_amount_safe(amount_str):
                            if not amount_str or amount_str == '-':
                                return 0
                            try:
                                cleaned = amount_str.replace(',', '').replace(' ', '').strip()
                                val = float(cleaned)
                                if val > 10_000_000:
                                    return 0
                                return val
                            except (ValueError, AttributeError):
                                return 0

                        amount = 0
                        trans_type = 'debit'

                        money_in_val = parse_amount_safe(money_in)
                        if money_in_val > 0:
                            amount = money_in_val
                            trans_type = 'credit'

                        money_out_val = parse_amount_safe(money_out)
                        if amount == 0 and money_out_val > 0:
                            amount = money_out_val
                            trans_type = 'debit'

                        fees_val = parse_amount_safe(fees)
                        if amount == 0 and fees_val > 0:
                            amount = fees_val
                            trans_type = 'debit'
                            description = f"{description} (Fee)"

                        if amount > 0:
                            transactions.append({
                                'date': trans_date,
                                'description': description,
                                'amount': amount,
                                'type': trans_type,
                                'reference': f"TYME-{trans_date.strftime('%Y%m%d')}-{len(transactions)}"
                            })

                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse TymeBank legacy transaction: {e}")

            i += 1

        if not transactions:
            logger.warning("No transactions found with TymeBank legacy pattern")
        else:
            logger.info(f"Parsed {len(transactions)} TymeBank legacy transactions")

        return transactions

    def _parse_capitec(self, text):
        """Parse Capitec PDF format"""
        transactions = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()
            if not line or 'Transaction History' in line or 'Money In' in line or 'Money Out' in line:
                i += 1
                continue

            date_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(.+)', line)

            if date_match:
                try:
                    date_str = date_match.group(1)
                    rest_of_line = date_match.group(2).strip()
                    trans_date = datetime.strptime(date_str, '%d/%m/%Y').date()

                    amount_pattern = r'(.+?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$'
                    amount_match = re.search(amount_pattern, rest_of_line)

                    if amount_match:
                        desc_and_category = amount_match.group(1).strip()
                        amount1_str = amount_match.group(2).strip()
                        amount2_str = amount_match.group(3).strip()

                        def parse_capitec_amount(amt_str):
                            if not amt_str or amt_str == '-':
                                return 0.0
                            try:
                                return float(amt_str.replace(',', '').strip())
                            except (ValueError, AttributeError):
                                return 0.0

                        amount1 = parse_capitec_amount(amount1_str)
                        amount2 = parse_capitec_amount(amount2_str)
                        balance = amount2

                        three_amount_pattern = r'(.+?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$'
                        three_match = re.search(three_amount_pattern, rest_of_line)

                        if three_match:
                            desc_and_category = three_match.group(1).strip()
                            trans_amount = parse_capitec_amount(three_match.group(2))
                            fee = parse_capitec_amount(three_match.group(3))
                            balance = parse_capitec_amount(three_match.group(4))
                        else:
                            trans_amount = amount1
                            fee = 0.0

                        desc_parts = desc_and_category.split()
                        category = None
                        category_keywords = ['Income', 'Savings', 'Withdrawal', 'Transfer', 'Payments',
                                             'Cellphone', 'Uncategorised', 'Investments', 'Fees', 'Interest']

                        for idx in range(len(desc_parts) - 1, -1, -1):
                            if desc_parts[idx] in category_keywords:
                                if idx > 0 and desc_parts[idx - 1] not in category_keywords:
                                    category = ' '.join(desc_parts[idx - 1:idx + 1])
                                    description = ' '.join(desc_parts[:idx - 1])
                                else:
                                    category = desc_parts[idx]
                                    description = ' '.join(desc_parts[:idx])
                                break

                        if not category:
                            description = desc_and_category
                            category = 'Uncategorised'

                        desc_lower = description.lower()
                        credit_keywords = ['payment received', 'received', 'deposit', 'interest received',
                                           'transfer received', 'refund']
                        debit_keywords = ['payment:', 'sent', 'cash sent', 'withdrawal', 'purchase',
                                          'transfer to', 'prepaid', 'voucher', 'debicheck', 'insufficient funds']

                        if any(kw in desc_lower for kw in credit_keywords):
                            is_credit = True
                        elif any(kw in desc_lower for kw in debit_keywords):
                            is_credit = False
                        else:
                            if trans_amount < 0:
                                is_credit = False
                                trans_amount = abs(trans_amount)
                            elif 'income' in (category or '').lower() or 'received' in (category or '').lower():
                                is_credit = True
                            else:
                                is_credit = False

                        if trans_amount > 0 and len(description) >= 3:
                            transactions.append({
                                'date': trans_date,
                                'description': description.strip(),
                                'amount': abs(trans_amount),
                                'type': 'credit' if is_credit else 'debit',
                                'reference': f"CAP-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                                'category': category,
                                'fee': abs(fee) if fee else 0.0,
                                'balance': balance,
                            })

                    else:
                        if i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            next_amount_match = re.match(
                                r'^(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$',
                                next_line
                            )
                            if next_amount_match:
                                description = rest_of_line.strip()
                                amount1 = float(next_amount_match.group(1).replace(',', ''))
                                balance = float(next_amount_match.group(2).replace(',', ''))
                                trans_amount = abs(amount1)
                                is_credit = any(kw in description.lower() for kw in
                                                ['received', 'deposit', 'income', 'refund'])
                                if trans_amount > 0 and len(description) >= 3:
                                    transactions.append({
                                        'date': trans_date,
                                        'description': description,
                                        'amount': trans_amount,
                                        'type': 'credit' if is_credit else 'debit',
                                        'reference': f"CAP-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                                        'balance': balance,
                                    })
                                    i += 1

                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse Capitec transaction: {e} - Line: {line}")

            i += 1

        if not transactions:
            logger.warning("No transactions found with Capitec pattern")
        else:
            logger.info(f"Parsed {len(transactions)} Capitec transactions")

        return transactions

    def _parse_generic(self, text):
        transactions = []
        patterns = [
            (r'(\d{2}/\d{2}/\d{4})\s*[|\|]\s*([^|\|]+?)\s*[|\|]\s*(-?R?[\d,]+\.\d{2})', '%d/%m/%Y'),
            (r'(\d{2}/\d{2}/\d{4})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%d/%m/%Y'),
            (r'(\d{4}-\d{2}-\d{2})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%Y-%m-%d'),
            (r'(\d{2}\s+\w{3}\s+\d{4})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%d %b %Y'),
        ]
        for pattern, date_format in patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            if matches:
                for match in matches:
                    try:
                        trans_date = datetime.strptime(match[0].strip(), date_format).date()
                        description = match[1].strip()
                        amount_str = match[2].replace('R', '').replace('$', '').replace(',', '').strip()
                        amount = float(amount_str)
                        if len(description) < 3:
                            continue
                        transactions.append({
                            'date': trans_date,
                            'description': description,
                            'amount': abs(amount),
                            'type': 'debit' if amount < 0 else 'credit',
                            'reference': f"GEN-{trans_date.strftime('%Y%m%d')}-{len(transactions)}"
                        })
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Generic parse failed: {e}")
                        continue
                if transactions:
                    break
        return transactions

    def parse_html_email(self, html_content, bank_name):
        from bs4 import BeautifulSoup
        transactions = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 3:
                        try:
                            date_text = cols[0].get_text().strip()
                            description = cols[1].get_text().strip()
                            amount_text = cols[2].get_text().strip()
                            trans_date = None
                            for date_fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d %b %Y']:
                                try:
                                    trans_date = datetime.strptime(date_text, date_fmt).date()
                                    break
                                except ValueError:
                                    continue
                            if not trans_date:
                                continue
                            amount_str = re.sub(r'[^\d\.\-]', '', amount_text)
                            amount = float(amount_str)
                            transactions.append({
                                'date': trans_date,
                                'description': description,
                                'amount': abs(amount),
                                'type': 'debit' if amount < 0 else 'credit',
                                'reference': f"HTML-{trans_date.strftime('%Y%m%d')}"
                            })
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            logger.error(f"HTML parsing error: {e}")
        return transactions