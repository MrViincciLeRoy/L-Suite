"""
CSV Parser for Bank Transactions
Add this to lsuite/gmail/parsers.py or create lsuite/gmail/csv_parser.py
"""
import csv
import io
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)


class CSVParser:
    """Parse bank transaction CSV files"""
    
    def parse_csv(self, csv_data, encoding='utf-8'):
        """
        Parse CSV data and extract transactions
        
        Args:
            csv_data: Binary or string CSV data
            encoding: CSV file encoding (default: utf-8)
            
        Returns:
            List of transaction dictionaries
        """
        transactions = []
        
        try:
            # Convert bytes to string if needed
            if isinstance(csv_data, bytes):
                csv_text = csv_data.decode(encoding, errors='ignore')
            else:
                csv_text = csv_data
            
            # Parse CSV
            csv_file = io.StringIO(csv_text)
            reader = csv.DictReader(csv_file)
            
            for row in reader:
                try:
                    transaction = self._parse_row(row)
                    if transaction:
                        transactions.append(transaction)
                except Exception as e:
                    logger.warning(f"Failed to parse CSV row: {e}")
                    continue
            
            logger.info(f"Successfully parsed {len(transactions)} transactions from CSV")
            
        except Exception as e:
            logger.error(f"CSV parsing error: {e}")
            raise
        
        return transactions
    
    def _parse_row(self, row):
        """Parse a single CSV row into transaction dictionary"""
        
        # Clean up column names (remove whitespace)
        row = {k.strip(): v.strip() if v else None for k, v in row.items()}
        
        # Parse transaction date
        transaction_date = self._parse_date(row.get('Transaction Date'))
        if not transaction_date:
            return None
        
        # Parse posting date (optional)
        posting_date = self._parse_date(row.get('Posting Date'))
        
        # Get description
        description = row.get('Description', '').strip()
        if not description or len(description) < 2:
            return None
        
        # Skip header rows that might be in the data
        if 'Transaction Date' in description or 'Description' in description:
            return None
        
        # Parse debits and credits
        debits = self._parse_amount(row.get('Debits'))
        credits = self._parse_amount(row.get('Credits'))
        balance = self._parse_amount(row.get('Balance'))
        
        # Get bank account
        bank_account = row.get('Bank account', '').strip()
        
        # Generate reference
        reference = self._generate_reference(description, transaction_date)
        
        return {
            'transaction_date': transaction_date,
            'posting_date': posting_date,
            'description': description,
            'debits': debits,
            'credits': credits,
            'balance': balance,
            'bank_account': bank_account,
            'reference': reference
        }
    
    def _parse_date(self, date_str):
        """Parse date string to date object"""
        if not date_str:
            return None
        
        date_formats = [
            '%Y/%m/%d',  # 2025/09/23
            '%d/%m/%Y',  # 23/09/2025
            '%Y-%m-%d',  # 2025-09-23
            '%d-%m-%Y',  # 23-09-2025
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {date_str}")
        return None
    
    def _parse_amount(self, amount_str):
        """Parse amount string to Decimal"""
        if not amount_str:
            return None
        
        try:
            # Remove any currency symbols and whitespace
            cleaned = amount_str.replace('R', '').replace(',', '').replace(' ', '').strip()
            
            if not cleaned or cleaned == '-':
                return None
            
            return Decimal(cleaned)
        except Exception as e:
            logger.warning(f"Could not parse amount: {amount_str} - {e}")
            return None
    
    def _generate_reference(self, description, date):
        """Generate a reference number for the transaction"""
        # Take first word of description and date
        first_word = description.split()[0] if description else 'TXN'
        date_str = date.strftime('%Y%m%d') if date else 'NODATE'
        return f"{first_word[:10]}-{date_str}"
    
    def parse_csv_file(self, file_path):
        """Parse CSV file from file path"""
        with open(file_path, 'rb') as f:
            csv_data = f.read()
        return self.parse_csv(csv_data)
