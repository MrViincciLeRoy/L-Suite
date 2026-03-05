"""
PDF Parser - Extract transactions from bank statement PDFs
LiquidSuite/lsuite/gmail/parsers.py - COMPLETE FIXED VERSION
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
    """PDF statement parser"""
    
    def parse_pdf(self, pdf_data, bank_name, password=None):
        """
        Parse PDF and extract transactions
        
        Args:
            pdf_data: Binary PDF data
            bank_name: Bank identifier (tymebank, capitec, other)
            password: PDF password if protected
            
        Returns:
            List of transaction dictionaries
        """
        text = self._extract_text_from_pdf(pdf_data, password)
        
        # Log extracted text for debugging
        logger.info(f"Extracted text length: {len(text)} characters")
        logger.debug(f"First 500 chars: {text[:500]}")
        
        if bank_name == 'tymebank':
            return self._parse_tymebank(text)
        elif bank_name == 'capitec':
            return self._parse_capitec(text)
        else:
            return self._parse_generic(text)
    
    def _extract_text_from_pdf(self, pdf_data, password=None):
        """Extract text from PDF using available library"""
        text = ""
        
        try:
            # Try PyPDF2 first
            import PyPDF2
            pdf_file = io.BytesIO(pdf_data)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            # Handle encrypted PDFs
            if pdf_reader.is_encrypted:
                if not password:
                    raise ValueError("PDF is password protected but no password provided")
                
                decrypt_result = pdf_reader.decrypt(password)
                if decrypt_result == 0:
                    raise ValueError("Incorrect PDF password")
            
            # Extract text from all pages
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            
            logger.info(f"Extracted {len(text)} characters using PyPDF2")
            
        except ImportError:
            # Fallback to pdfplumber
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
        """Parse TymeBank PDF format - FIXED VERSION
        
        TymeBank format:
        Date Description Fees Money Out Money In Balance
        04 Sep 2025 EFT for CAPITEC S SEANEGO - - 250.00 250.05
        
        Multi-line format:
        10 Sep 2025 Purchase at Boxer Spr Mabopane
        525309988959
        - 512.46 - 417.59
        """
        transactions = []
        
        # Split text into lines for processing
        lines = text.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Look for lines starting with a date pattern
            date_match = re.match(r'^(\d{1,2}\s+\w{3}\s+\d{4})\s+(.+)', line)
            
            if date_match:
                try:
                    date_str = date_match.group(1)
                    rest_of_line = date_match.group(2).strip()
                    
                    # Parse the date
                    trans_date = datetime.strptime(date_str, '%d %b %Y').date()
                    
                    # Build description starting with rest of first line
                    description_parts = [rest_of_line]
                    
                    # Look ahead for continuation lines and amounts
                    j = i + 1
                    amounts_found = False
                    fees = money_out = money_in = balance = None
                    
                    # Check next few lines (max 5 lines ahead for multi-line transactions)
                    while j < len(lines) and j < i + 6:
                        next_line = lines[j].strip()
                        
                        # Stop if we hit another date (start of next transaction)
                        if re.match(r'^\d{1,2}\s+\w{3}\s+\d{4}', next_line):
                            break
                        
                        # Better pattern that validates amounts are actually monetary values
                        amount_pattern = r'^(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+((?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s*$'
                        amount_match = re.match(amount_pattern, next_line)
                        
                        if amount_match:
                            # Found the amounts line
                            fees = amount_match.group(1).strip()
                            money_out = amount_match.group(2).strip()
                            money_in = amount_match.group(3).strip()
                            balance = amount_match.group(4).strip()
                            amounts_found = True
                            i = j  # Move main counter to this position
                            break
                        else:
                            # Check if amounts are at the end of this line
                            inline_pattern = r'(.+?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+((?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s*$'
                            inline_amount_match = re.search(inline_pattern, next_line)
                            
                            if inline_amount_match:
                                # Description continues and amounts are on same line
                                description_parts.append(inline_amount_match.group(1).strip())
                                fees = inline_amount_match.group(2).strip()
                                money_out = inline_amount_match.group(3).strip()
                                money_in = inline_amount_match.group(4).strip()
                                balance = inline_amount_match.group(5).strip()
                                amounts_found = True
                                i = j
                                break
                            else:
                                # Only add to description if it's not a random number
                                # Skip lines that are just long numbers (like card numbers: 525309988959)
                                if next_line and not re.match(r'^\d{10,}$', next_line):
                                    # Check if it's a valid description line
                                    if len(next_line) > 0 and not next_line.startswith('-'):
                                        description_parts.append(next_line)
                        
                        j += 1
                    
                    # Try to find amounts on the same line as date if not found yet
                    if not amounts_found:
                        same_line_pattern = r'(.+?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+(-|(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s+((?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{2})?)\s*$'
                        same_line_match = re.search(same_line_pattern, rest_of_line)
                        
                        if same_line_match:
                            description_parts = [same_line_match.group(1).strip()]
                            fees = same_line_match.group(2).strip()
                            money_out = same_line_match.group(3).strip()
                            money_in = same_line_match.group(4).strip()
                            balance = same_line_match.group(5).strip()
                            amounts_found = True
                    
                    # Process the transaction if amounts were found
                    if amounts_found:
                        # Build full description
                        description = ' '.join(description_parts)
                        description = ' '.join(description.split())  # Clean whitespace
                        
                        # Skip if description is too short or looks like a header
                        if len(description) < 3 or 'Description' in description or 'Money Out' in description:
                            i += 1
                            continue
                        
                        # Parse amounts with validation
                        def parse_amount_safe(amount_str):
                            """Safely parse amount with validation"""
                            if not amount_str or amount_str == '-':
                                return 0
                            try:
                                # Remove commas and spaces
                                cleaned = amount_str.replace(',', '').replace(' ', '').strip()
                                # Ensure it's not too large (max 10 million for a single transaction)
                                val = float(cleaned)
                                if val > 10_000_000:  # 10 million limit
                                    logger.warning(f"Amount too large, likely parsing error: {val} from '{amount_str}'")
                                    return 0
                                return val
                            except (ValueError, AttributeError):
                                logger.warning(f"Could not parse amount: '{amount_str}'")
                                return 0
                        
                        # Determine transaction type and amount
                        amount = 0
                        trans_type = 'debit'
                        
                        # Check Money In first (credits)
                        money_in_val = parse_amount_safe(money_in)
                        if money_in_val > 0:
                            amount = money_in_val
                            trans_type = 'credit'
                        
                        # Then check Money Out (debits)
                        money_out_val = parse_amount_safe(money_out)
                        if amount == 0 and money_out_val > 0:
                            amount = money_out_val
                            trans_type = 'debit'
                        
                        # Then check Fees (also debits)
                        fees_val = parse_amount_safe(fees)
                        if amount == 0 and fees_val > 0:
                            amount = fees_val
                            trans_type = 'debit'
                            description = f"{description} (Fee)"
                        
                        # Only add if we have a valid amount
                        if amount > 0:
                            transactions.append({
                                'date': trans_date,
                                'description': description,
                                'amount': amount,
                                'type': trans_type,
                                'reference': f"TYME-{trans_date.strftime('%Y%m%d')}-{len(transactions)}"
                            })
                            logger.debug(f"Parsed transaction: {description[:30]} = {amount}")
                        else:
                            logger.debug(f"Skipped transaction with zero amount: {description[:30]}")
                    
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse TymeBank transaction: {e}")
            
            i += 1
        
        if not transactions:
            logger.warning("No transactions found with TymeBank pattern")
            logger.debug(f"Text sample for debugging:\n{text[:1000]}")
        else:
            logger.info(f"Successfully parsed {len(transactions)} TymeBank transactions")
        
        return transactions
    
    def _parse_capitec(self, text):
        """Parse Capitec PDF format - COMPLETELY FIXED VERSION
        
        Capitec format from your PDF:
        Date | Description | Category | Money In | Money Out | Fee* | Balance
        
        Example lines:
        01/10/2024 Recurring Transfer Insufficient Funds of R1 000.00 (16916070)
        01/10/2024 DebiCheck Insufficient Funds (R66.65): Capitec/general (CF69253296)
        21/10/2024 Payment Received: 1070143456004 Vault M Other Income 88.00 73.54
        25/10/2024 Banking App Cash Sent: ******* Cash Withdrawal -50.00 -10.00 28.64
        """
        transactions = []
        
        # Split text into lines
        lines = text.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines and headers
            if not line or 'Transaction History' in line or 'Money In' in line or 'Money Out' in line:
                i += 1
                continue
            
            # Look for date at start: DD/MM/YYYY
            date_match = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(.+)', line)
            
            if date_match:
                try:
                    date_str = date_match.group(1)
                    rest_of_line = date_match.group(2).strip()
                    
                    # Parse date
                    trans_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                    
                    # Build description and look for amounts
                    description_parts = []
                    category = None
                    money_in = None
                    money_out = None
                    fee = None
                    balance = None
                    
                    # Pattern to match amounts at the end of line
                    # Capitec uses: [description] [category] [money_in OR money_out] [fee] [balance]
                    # Amounts can be negative (with -) and may have commas
                    # Pattern: optional negative amounts with optional commas and decimal
                    amount_pattern = r'(.+?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$'
                    
                    _amount_pattern = r'(.+?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.-?\d{2})?\*?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.-?\d{2})?\*?)\s*$'
                    amount_match = re.search(amount_pattern, rest_of_line)
                    _amount_match = re.search(_amount_pattern, rest_of_line)
                    #print(_amount_match)
                    if amount_match:
                        # We have amounts on the same line
                        desc_and_category = amount_match.group(1).strip()
                        amount1_str = amount_match.group(2).strip()
                        amount2_str = amount_match.group(3).strip()
                        
                        # Parse amounts
                        def parse_capitec_amount(amt_str):
                            """Parse Capitec amount - handles negative and positive"""
                            if not amt_str or amt_str == '-':
                                return 0.0
                            try:
                                cleaned = amt_str.replace(',', '').strip()
                                return float(cleaned)
                            except (ValueError, AttributeError):
                                return 0.0
                        
                        amount1 = parse_capitec_amount(amount1_str)
                        amount2 = parse_capitec_amount(amount2_str)
                        
                        # Determine which is the transaction amount and which is balance
                        # In Capitec format, the last number is usually the balance
                        # The second-to-last is the fee or transaction amount
                        balance = amount2  # Last number is balance
                        
                        # Now check if there's a third amount (for fee)
                        # Try to find 3 amounts: [transaction_amt] [fee] [balance]
                        three_amount_pattern = r'(.+?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$'
                        three_amount_match = re.search(three_amount_pattern, rest_of_line)
                        
                        if three_amount_match:
                            desc_and_category = three_amount_match.group(1).strip()
                            trans_amount_str = three_amount_match.group(2).strip()
                            fee_str = three_amount_match.group(3).strip()
                            balance_str = three_amount_match.group(4).strip()
                            
                            trans_amount = parse_capitec_amount(trans_amount_str)
                            fee = parse_capitec_amount(fee_str)
                            balance = parse_capitec_amount(balance_str)
                        else:
                            # Only 2 amounts: [transaction_amt] [balance]
                            trans_amount = amount1
                            fee = 0.0
                        
                        # Extract category from description (last word before amounts)
                        # Categories in your PDF: "Other Income", "Savings", "Cash Withdrawal", "Transfer", etc.
                        desc_parts = desc_and_category.split()
                        
                        # Try to identify category keywords
                        category_keywords = ['Income', 'Savings', 'Withdrawal', 'Transfer', 'Payments', 
                                           'Cellphone', 'Uncategorised', 'Investments', 'Fees', 'Interest']
                        
                        for idx in range(len(desc_parts)-1, -1, -1):
                            if desc_parts[idx] in category_keywords:
                                if idx > 0 and desc_parts[idx-1] not in category_keywords:
                                    # Check if previous word is also part of category
                                    category = ' '.join(desc_parts[idx-1:idx+1])
                                    description = ' '.join(desc_parts[:idx-1])
                                else:
                                    category = desc_parts[idx]
                                    description = ' '.join(desc_parts[:idx])
                                break
                        
                        if not category:
                            # No category found, entire text is description
                            description = desc_and_category
                            category = 'Uncategorised'
                        
                        # Determine if it's a debit or credit
                        # Positive amounts in "Money In" are credits
                        # Negative amounts or amounts in "Money Out" are debits
                        # Check the description for clues
                        is_credit = False
                        desc_lower = description.lower()
                        
                        # Keywords that indicate credits
                        credit_keywords = ['payment received', 'received', 'deposit', 'interest received', 
                                         'transfer received', 'refund']
                        # Keywords that indicate debits
                        debit_keywords = ['payment:', 'sent', 'cash sent', 'withdrawal', 'purchase', 
                                        'transfer to', 'prepaid', 'voucher', 'debicheck', 'insufficient funds']
                        
                        # Check for credit indicators
                        if any(keyword in desc_lower for keyword in credit_keywords):
                            is_credit = True
                        elif any(keyword in desc_lower for keyword in debit_keywords):
                            is_credit = False
                        else:
                            # Use amount sign as indicator
                            # If trans_amount is positive and large, it might be a credit
                            # If trans_amount is negative, it's a debit
                            if trans_amount < 0:
                                is_credit = False
                                trans_amount = abs(trans_amount)
                            elif trans_amount > 0:
                                # Ambiguous - check category
                                if 'income' in category.lower() or 'received' in category.lower():
                                    is_credit = True
                                else:
                                    # Default to debit for positive amounts unless explicitly income
                                    is_credit = False
                        
                        # Add transaction if amount is valid
                        if trans_amount > 0 and len(description) >= 3:
                            transactions.append({
                                'date': trans_date,
                                'description': description.strip(),
                                'amount': abs(trans_amount),
                                'type': 'credit' if is_credit else 'debit',
                                'reference': f"CAP-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                                'category': category,
                                'fee': abs(fee) if fee else 0.0,
                                'balance': balance
                            })
                            logger.debug(f"Parsed Capitec: {description[:30]} = {trans_amount} ({'CR' if is_credit else 'DR'})")
                    
                    else:
                        # No amounts on this line, might be multi-line transaction
                        # Look ahead to next line
                        if i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            # Check if next line has amounts
                            next_amount_match = re.match(r'^(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$', next_line)
                            if next_amount_match:
                                # Multi-line transaction
                                description = rest_of_line.strip()
                                amount1_str = next_amount_match.group(1)
                                amount2_str = next_amount_match.group(2)
                                
                                amount1 = parse_capitec_amount(amount1_str)
                                amount2 = parse_capitec_amount(amount2_str)
                                
                                balance = amount2
                                trans_amount = abs(amount1)
                                
                                # Determine type from description
                                is_credit = any(kw in description.lower() for kw in 
                                              ['received', 'deposit', 'income', 'refund'])
                                
                                if trans_amount > 0 and len(description) >= 3:
                                    transactions.append({
                                        'date': trans_date,
                                        'description': description,
                                        'amount': trans_amount,
                                        'type': 'credit' if is_credit else 'debit',
                                        'reference': f"CAP-{trans_date.strftime('%Y%m%d')}-{len(transactions)}",
                                        'balance': balance
                                    })
                                    logger.debug(f"Parsed multi-line Capitec: {description[:30]} = {trans_amount}")
                                    i += 1  # Skip next line as we processed it
                
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse Capitec transaction: {e} - Line: {line}")
            
            i += 1
        
        if not transactions:
            logger.warning("No transactions found with Capitec pattern")
            logger.debug(f"Text sample:\n{text[:1000]}")
        else:
            logger.info(f"Successfully parsed {len(transactions)} Capitec transactions")
        
        return transactions
    
    def _parse_generic(self, text):
        """Generic PDF parsing for unknown banks"""
        transactions = []
        
        # Generic patterns that might work for various banks
        patterns = [
            (r'(\d{2}/\d{2}/\d{4})\s*[|\|]\s*([^|\|]+?)\s*[|\|]\s*(-?R?[\d,]+\.\d{2})', '%d/%m/%Y'),
            (r'(\d{2}/\d{2}/\d{4})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%d/%m/%Y'),
            (r'(\d{4}-\d{2}-\d{2})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%Y-%m-%d'),
            (r'(\d{2}\s+\w{3}\s+\d{4})\s+([^\d\-\+\$R]+?)\s+(-?R?[\d,]+\.\d{2})', '%d %b %Y'),
        ]
        
        for pattern, date_format in patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            
            if matches:
                logger.info(f"Found {len(matches)} transactions with generic pattern")
                
                for match in matches:
                    try:
                        trans_date = datetime.strptime(match[0].strip(), date_format).date()
                        description = match[1].strip()
                        amount_str = match[2].replace('R', '').replace('$', '').replace(',', '').strip()
                        amount = float(amount_str)
                        
                        # Skip if description is too short
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
                        logger.warning(f"Failed to parse generic transaction: {e}")
                        continue
                
                if transactions:
                    break
        
        return transactions
    
    def parse_html_email(self, html_content, bank_name):
        """Parse transaction table from HTML email"""
        from bs4 import BeautifulSoup
        
        transactions = []
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            tables = soup.find_all('table')
            
            for table in tables:
                rows = table.find_all('tr')
                
                # Skip header row
                for row in rows[1:]:
                    cols = row.find_all('td')
                    
                    if len(cols) >= 3:
                        try:
                            date_text = cols[0].get_text().strip()
                            description = cols[1].get_text().strip()
                            amount_text = cols[2].get_text().strip()
                            
                            # Parse date
                            trans_date = None
                            for date_fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d %b %Y']:
                                try:
                                    trans_date = datetime.strptime(date_text, date_fmt).date()
                                    break
                                except ValueError:
                                    continue
                            
                            if not trans_date:
                                continue
                            
                            # Parse amount
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
            
            logger.info(f"Extracted {len(transactions)} transactions from HTML email")
            
        except Exception as e:
            logger.error(f"HTML parsing error: {e}")
        
        return transactions

if __name__ == "__main__":
    path = str(os.getcwd()).replace('\\','/')
    pdf = f"{path}/data/account_statement-1_032727.pdf"
    parser = PDFParser()
    #print(pdf,type(Path(pdf).read_bytes()))
    parsed_pdf = parser.parse_pdf(Path(pdf).read_bytes(),'capitec')
    transactions = {}
    for trans in parsed_pdf:
        #for key, items in parsed_pdf[0].items():
            if not trans['date'] in transactions.keys():
                transactions[trans['date']] = [trans]
            else:
                transactions[trans['date']].append(trans)
            #print(transactions[trans['date']],'\n\n\n')
