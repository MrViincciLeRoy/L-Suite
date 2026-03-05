import base64
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import pytz
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from django.conf import settings

from main.models import EmailStatement, BankTransaction
from .parsers import PDFParser

logger = logging.getLogger(__name__)


class GmailService:
    def _get_redirect_uri(self, request):
        uri = getattr(settings, 'GOOGLE_REDIRECT_URI', None)
        if not uri:
            uri = request.build_absolute_uri('/gmail/oauth/callback/')
        if 'localhost' not in uri and uri.startswith('http://'):
            uri = uri.replace('http://', 'https://', 1)
        return uri

    def get_auth_url(self, credential, request):
        redirect_uri = self._get_redirect_uri(request)
        return (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={credential.client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"response_type=code&"
            f"scope=https://www.googleapis.com/auth/gmail.readonly&"
            f"access_type=offline&"
            f"prompt=consent&"
            f"state={credential.id}"
        )

    def exchange_code_for_tokens(self, credential, code, request):
        redirect_uri = self._get_redirect_uri(request)
        data = {
            'code': code,
            'client_id': credential.client_id,
            'client_secret': credential.client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }
        try:
            response = requests.post('https://oauth2.googleapis.com/token', data=data)
            response.raise_for_status()
            tokens = response.json()

            credential.access_token = tokens.get('access_token', '')
            credential.refresh_token = tokens.get('refresh_token', '')
            credential.token_expiry = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
            credential.is_authenticated = True
            credential.save()
            return True
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return False

    def _build_service(self, credential):
        creds = Credentials(
            token=credential.access_token,
            refresh_token=credential.refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=credential.client_id,
            client_secret=credential.client_secret,
        )
        return build('gmail', 'v1', credentials=creds)

    def fetch_statements(self, credential):
        service = self._build_service(credential)

        queries = [
            'from:@tymebank.co.za subject:Statement',
            'from:@capitecbank.co.za subject:Statement',
            'subject:"bank statement"',
        ]

        all_messages = []
        for query in queries:
            try:
                results = service.users().messages().list(userId='me', q=query, maxResults=50).execute()
                all_messages.extend(results.get('messages', []))
            except Exception as e:
                logger.error(f"Gmail search error for '{query}': {e}")

        imported_count, skipped_count = 0, 0

        for msg in all_messages:
            try:
                if EmailStatement.objects.filter(gmail_id=msg['id']).exists():
                    skipped_count += 1
                    continue

                msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                headers = msg_data['payload']['headers']

                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
                date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')

                try:
                    msg_date = parsedate_to_datetime(date_str)
                    if msg_date.tzinfo:
                        msg_date = msg_date.astimezone(pytz.UTC).replace(tzinfo=None)
                except Exception:
                    msg_date = datetime.utcnow()

                body_html, body_text = '', ''
                if 'parts' in msg_data['payload']:
                    for part in msg_data['payload']['parts']:
                        try:
                            mime = part['mimeType']
                            data = part.get('body', {}).get('data')
                            if not data:
                                continue
                            decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                            if mime == 'text/html':
                                body_html = decoded
                            elif mime == 'text/plain':
                                body_text = decoded
                        except Exception:
                            continue

                sender_lower = sender.lower()
                bank_name = 'tymebank' if 'tymebank' in sender_lower else ('capitec' if 'capitec' in sender_lower else 'other')
                has_pdf = any(
                    part.get('filename', '').lower().endswith('.pdf')
                    for part in msg_data['payload'].get('parts', [])
                )

                EmailStatement.objects.create(
                    user=credential.user,
                    gmail_id=msg['id'],
                    subject=subject,
                    sender=sender,
                    received_date=msg_date,
                    bank_name=bank_name,
                    body_html=body_html,
                    body_text=body_text,
                    has_pdf=has_pdf,
                    state='new',
                )
                imported_count += 1

            except Exception as e:
                logger.error(f"Error importing message: {e}")

        return imported_count, skipped_count

    def download_and_parse_pdf(self, credential, statement):
        service = self._build_service(credential)
        BankTransaction.objects.filter(statement=statement).delete()

        try:
            msg_data = service.users().messages().get(userId='me', id=statement.gmail_id).execute()
            pdf_data = None

            for part in msg_data['payload'].get('parts', []):
                if part.get('filename', '').lower().endswith('.pdf'):
                    att_id = part['body'].get('attachmentId')
                    if att_id:
                        attachment = service.users().messages().attachments().get(
                            userId='me', messageId=statement.gmail_id, id=att_id
                        ).execute()
                        pdf_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                        break

            if not pdf_data:
                raise Exception('No PDF attachment found')

            parser = PDFParser()
            transactions = parser.parse_pdf(pdf_data, statement.bank_name, statement.pdf_password)

            for trans in transactions:
                BankTransaction.objects.create(
                    user=statement.user,
                    statement=statement,
                    date=trans['date'],
                    description=trans['description'],
                    deposit=trans['amount'] if trans['type'] == 'credit' else None,
                    withdrawal=trans['amount'] if trans['type'] == 'debit' else None,
                    reference_number=trans.get('reference', ''),
                )

            statement.state = 'parsed'
            statement.has_pdf = True
            statement.transaction_count = len(transactions)
            statement.save()

            return len(transactions)

        except Exception as e:
            statement.state = 'error'
            statement.error_message = str(e)
            statement.save()
            logger.error(f"PDF parsing error: {e}")
            raise
