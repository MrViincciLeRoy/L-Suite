"""
LiquidSuite/lsuite/gmail/services.py - COMPLETE FIXED VERSION
Gmail Service - Gmail API integration
"""
import base64
import logging
from datetime import datetime, timedelta
import pytz
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.utils import parsedate_to_datetime

#from lsuite.extensions import db
from main.models import EmailStatement, BankTransaction
from .parsers import PDFParser

logger = logging.getLogger(__name__)


class GmailService:
    """Gmail API service"""
    
    def __init__(self, app):
        self.app = app
    
    def get_auth_url(self, credential):
        """Generate OAuth authorization URL"""
        base_url = self.app.config.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/gmail/oauth/callback')
        
        # Force HTTPS for production
        if 'localhost' not in base_url and base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://', 1)
        
        auth_url = (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={credential.client_id}&"
            f"redirect_uri={base_url}&"
            f"response_type=code&"
            f"scope=https://www.googleapis.com/auth/gmail.readonly&"
            f"access_type=offline&"
            f"prompt=consent&"
            f"state={credential.id}"
        )
        
        return auth_url
    
    def exchange_code_for_tokens(self, credential, code):
        """Exchange authorization code for access tokens"""
        base_url = self.app.config.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/gmail/oauth/callback')
        
        if 'localhost' not in base_url and base_url.startswith('http://'):
            base_url = base_url.replace('http://', 'https://', 1)
        
        token_url = 'https://oauth2.googleapis.com/token'
        data = {
            'code': code,
            'client_id': credential.client_id,
            'client_secret': credential.client_secret,
            'redirect_uri': base_url,
            'grant_type': 'authorization_code',
        }
        
        try:
            response = requests.post(token_url, data=data)
            response.raise_for_status()
            tokens = response.json()
            
            expiry = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
            
            credential.access_token = tokens.get('access_token')
            credential.refresh_token = tokens.get('refresh_token')
            credential.token_expiry = expiry
            credential.is_authenticated = True
            
            db.session.commit()
            return True
            
        except Exception as e:
            logger.error(f"Token exchange failed: {str(e)}")
            return False
    
    def build_service(self, credential):
        """Build Gmail API service"""
        creds = Credentials(
            token=credential.access_token,
            refresh_token=credential.refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=credential.client_id,
            client_secret=credential.client_secret,
        )
        
        return build('gmail', 'v1', credentials=creds)
    
    def fetch_statements(self, credential):
        """Fetch bank statements from Gmail"""
        service = self.build_service(credential)
        
        queries = [
            'from:@tymebank.co.za subject:Statement',
            'from:@capitecbank.co.za subject:Statement',
            'subject:"bank statement"',
        ]
        
        all_messages = []
        for query in queries:
            try:
                results = service.users().messages().list(
                    userId='me', 
                    q=query, 
                    maxResults=50
                ).execute()
                messages = results.get('messages', [])
                all_messages.extend(messages)
                logger.info(f"Query '{query}' returned {len(messages)} messages")
            except Exception as e:
                logger.error(f"Gmail search error for query '{query}': {str(e)}")
                continue
        
        logger.info(f"Found {len(all_messages)} messages total")
        
        imported_count = 0
        skipped_count = 0
        
        for msg in all_messages:
            try:
                # Check if already exists using gmail_id
                if EmailStatement.query.filter_by(gmail_id=msg['id']).first():
                    skipped_count += 1
                    continue
                
                # Fetch full message
                msg_data = service.users().messages().get(
                    userId='me', 
                    id=msg['id'], 
                    format='full'
                ).execute()
                
                # Extract headers
                headers = msg_data['payload']['headers']
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
                date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
                
                # Parse date
                try:
                    msg_date = parsedate_to_datetime(date_str)
                    if msg_date.tzinfo:
                        msg_date = msg_date.astimezone(pytz.UTC).replace(tzinfo=None)
                except Exception as e:
                    logger.warning(f"Date parse error: {e}")
                    msg_date = datetime.utcnow()
                
                # Extract body
                body_html = ''
                body_text = ''
                
                if 'parts' in msg_data['payload']:
                    for part in msg_data['payload']['parts']:
                        try:
                            if part['mimeType'] == 'text/html' and 'data' in part.get('body', {}):
                                body_html = base64.urlsafe_b64decode(
                                    part['body']['data']
                                ).decode('utf-8', errors='ignore')
                            elif part['mimeType'] == 'text/plain' and 'data' in part.get('body', {}):
                                body_text = base64.urlsafe_b64decode(
                                    part['body']['data']
                                ).decode('utf-8', errors='ignore')
                        except Exception as e:
                            logger.warning(f"Part decode error: {e}")
                            continue
                elif 'body' in msg_data['payload'] and msg_data['payload']['body'].get('data'):
                    try:
                        body_text = base64.urlsafe_b64decode(
                            msg_data['payload']['body']['data']
                        ).decode('utf-8', errors='ignore')
                    except Exception as e:
                        logger.warning(f"Body decode error: {e}")
                
                # Determine bank name
                bank_name = 'other'
                sender_lower = sender.lower()
                if 'tymebank' in sender_lower:
                    bank_name = 'tymebank'
                elif 'capitec' in sender_lower:
                    bank_name = 'capitec'
                
                # Check if has PDF attachment
                has_pdf = False
                if 'parts' in msg_data['payload']:
                    for part in msg_data['payload']['parts']:
                        filename = part.get('filename', '').lower()
                        if filename.endswith('.pdf'):
                            has_pdf = True
                            break
                
                # Create statement with correct field names
                statement = EmailStatement(
                    user_id=credential.user_id,
                    gmail_id=msg['id'],
                    subject=subject,
                    sender=sender,
                    received_date=msg_date,
                    bank_name=bank_name,
                    body_html=body_html,
                    body_text=body_text,
                    has_pdf=has_pdf,
                    state='new'
                )
                
                db.session.add(statement)
                imported_count += 1
                
                logger.info(f"Imported: {subject[:50]}")
                
            except Exception as e:
                logger.error(f"Error importing message: {str(e)}")
                continue
        
        try:
            db.session.commit()
            logger.info(f"Successfully imported {imported_count} statements, skipped {skipped_count}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Commit error: {str(e)}")
            raise
        
        return imported_count, skipped_count
    
    def download_and_parse_pdf(self, credential, statement):
        """Download PDF attachment and parse transactions"""
        service = self.build_service(credential)
        
        # Delete existing transactions
        BankTransaction.query.filter_by(statement_id=statement.id).delete()
        
        try:
            # Get message with attachments
            msg_data = service.users().messages().get(
                userId='me',
                id=statement.gmail_id
            ).execute()
            
            pdf_data = None
            
            if 'parts' in msg_data['payload']:
                for part in msg_data['payload']['parts']:
                    filename = part.get('filename', '')
                    
                    if filename.lower().endswith('.pdf'):
                        if 'body' in part and 'attachmentId' in part['body']:
                            att_id = part['body']['attachmentId']
                            attachment = service.users().messages().attachments().get(
                                userId='me',
                                messageId=statement.gmail_id,
                                id=att_id
                            ).execute()
                            
                            pdf_data = base64.urlsafe_b64decode(
                                attachment['data'].encode('UTF-8')
                            )
                            logger.info(f"Downloaded PDF: {filename} ({len(pdf_data)} bytes)")
                            break
            
            if not pdf_data:
                raise Exception('No PDF attachment found')
            
            # Parse PDF
            parser = PDFParser()
            transactions = parser.parse_pdf(
                pdf_data,
                statement.bank_name,
                statement.pdf_password
            )
            
            logger.info(f"Parsed {len(transactions)} transactions from PDF")
            
            # Create transaction records
            for trans in transactions:
                transaction = BankTransaction(
                    user_id=statement.user_id,
                    statement_id=statement.id,
                    date=trans['date'],
                    description=trans['description'],
                    deposit=trans['amount'] if trans['type'] == 'credit' else None,
                    withdrawal=trans['amount'] if trans['type'] == 'debit' else None,
                    reference_number=trans.get('reference', '')
                )
                db.session.add(transaction)
            
            statement.state = 'parsed'
            statement.has_pdf = True
            statement.transaction_count = len(transactions)
            
            db.session.commit()
            
            logger.info(f"Successfully created {len(transactions)} transactions")
            
            return len(transactions)
            
        except Exception as e:
            db.session.rollback()
            statement.state = 'error'
            statement.error_message = str(e)
            db.session.commit()
            logger.error(f"PDF parsing error: {str(e)}")
            raise
