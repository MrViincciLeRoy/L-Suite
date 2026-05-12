import io
import logging

from .capitec import CapitecParser
from .tymebank import TymeBankLegacyParser
from .gotyme import GoTymeParser, is_gotyme
from .generic import GenericParser

logger = logging.getLogger(__name__)


class PDFParser:

    def parse_pdf(self, pdf_data, bank_name, password=None):
        if bank_name == 'tymebank':
            return self._route_tymebank(pdf_data, password)
        text = self._extract_text(pdf_data, password)
        if bank_name == 'capitec':
            return CapitecParser().parse(text)
        return GenericParser().parse(text)

    def _route_tymebank(self, pdf_data, password=None):
        text = self._extract_text(pdf_data, password)
        if is_gotyme(text):
            logger.info("GoTyme statement detected — using char-level parser")
            return GoTymeParser().parse(pdf_data, password)
        logger.info("Legacy TymeBank statement — using regex parser")
        return TymeBankLegacyParser().parse(text)

    def _extract_text(self, pdf_data, password=None):
        text = ""
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
            if reader.is_encrypted:
                if not password:
                    raise ValueError("PDF is password protected but no password provided")
                if reader.decrypt(password) == 0:
                    raise ValueError("Incorrect PDF password")
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
        except ImportError:
            pass

        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_data), password=password) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text
        except ImportError:
            raise ImportError("No PDF library found. Install PyPDF2 or pdfplumber.")

    def parse_html_email(self, html_content, bank_name):
        from bs4 import BeautifulSoup
        import re
        from datetime import datetime
        transactions = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for table in soup.find_all('table'):
                for row in table.find_all('tr')[1:]:
                    cols = row.find_all('td')
                    if len(cols) < 3:
                        continue
                    try:
                        date_text   = cols[0].get_text().strip()
                        description = cols[1].get_text().strip()
                        amount_text = cols[2].get_text().strip()
                        trans_date = None
                        for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d %b %Y']:
                            try:
                                trans_date = datetime.strptime(date_text, fmt).date()
                                break
                            except ValueError:
                                continue
                        if not trans_date:
                            continue
                        amount = float(re.sub(r'[^\d\.\-]', '', amount_text))
                        transactions.append({
                            'date':        trans_date,
                            'description': description,
                            'amount':      abs(amount),
                            'type':        'debit' if amount < 0 else 'credit',
                            'reference':   f"HTML-{trans_date.strftime('%Y%m%d')}",
                        })
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.error(f"HTML parsing error: {e}")
        return transactions
