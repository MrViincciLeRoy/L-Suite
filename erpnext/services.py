import logging
import requests
from datetime import datetime
from main.models import ERPNextSyncLog

logger = logging.getLogger(__name__)


class ERPNextService:
    def __init__(self, config):
        self.config = config

    def _get_headers(self):
        return {
            'Authorization': f'token {self.config.api_key}:{self.config.api_secret}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def test_connection(self):
        try:
            url = f"{self.config.base_url}/api/method/frappe.auth.get_logged_user"
            response = requests.get(url, headers=self._get_headers(), timeout=10)
            response.raise_for_status()
            user = response.json().get('message', 'Unknown')
            return True, f"Connected as: {user}"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to ERPNext. Check URL."
        except requests.exceptions.Timeout:
            return False, "Connection timeout."
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return False, "Authentication failed. Check API credentials."
            return False, f"HTTP {e.response.status_code}: {e.response.text}"
        except Exception as e:
            return False, str(e)

    def create_journal_entry(self, transaction):
        if not transaction.category_id:
            raise ValueError("Transaction must be categorized before syncing")

        posting_date = transaction.date.strftime('%Y-%m-%d')
        amount = abs(float(transaction.withdrawal or 0) or float(transaction.deposit or 0))

        if transaction.transaction_type == 'debit':
            bank_credit, bank_debit = amount, 0
            expense_credit, expense_debit = 0, amount
        else:
            bank_credit, bank_debit = 0, amount
            expense_credit, expense_debit = amount, 0

        journal_data = {
            'doctype': 'Journal Entry',
            'company': self.config.default_company,
            'posting_date': posting_date,
            'accounts': [
                {
                    'account': self.config.bank_account,
                    'debit_in_account_currency': bank_debit,
                    'credit_in_account_currency': bank_credit,
                },
                {
                    'account': transaction.category.erpnext_account,
                    'debit_in_account_currency': expense_debit,
                    'credit_in_account_currency': expense_credit,
                    'cost_center': self.config.default_cost_center or None,
                },
            ],
            'user_remark': transaction.description or '',
            'reference_number': transaction.reference_number or '',
        }

        url = f"{self.config.base_url}/api/resource/Journal Entry"

        try:
            response = requests.post(url, headers=self._get_headers(), json=journal_data, timeout=30)
            response.raise_for_status()
            journal_entry_name = response.json().get('data', {}).get('name')

            transaction.erpnext_synced = True
            transaction.erpnext_journal_entry = journal_entry_name
            transaction.erpnext_sync_date = datetime.utcnow()
            transaction.erpnext_error = ''
            transaction.save()

            ERPNextSyncLog.objects.create(
                config=self.config,
                record_type='bank_transaction',
                record_id=transaction.id,
                erpnext_doctype='Journal Entry',
                erpnext_doc_name=journal_entry_name,
                status='success',
            )

            return journal_entry_name

        except Exception as e:
            self._handle_sync_error(transaction, str(e))
            raise

    def _handle_sync_error(self, transaction, error_message):
        logger.error(f"Sync failed: {error_message}")
        transaction.erpnext_error = error_message
        transaction.save()

        ERPNextSyncLog.objects.create(
            config=self.config,
            record_type='bank_transaction',
            record_id=transaction.id,
            status='failed',
            error_message=error_message,
        )

    def get_chart_of_accounts(self):
        try:
            url = f"{self.config.base_url}/api/resource/Account"
            params = {
                'fields': '["name", "account_type", "is_group"]',
                'filters': f'[["company", "=", "{self.config.default_company}"]]',
                'limit_page_length': 1000,
            }
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")
            return []

    def get_cost_centers(self):
        try:
            url = f"{self.config.base_url}/api/resource/Cost Center"
            params = {
                'fields': '["name", "cost_center_name"]',
                'filters': f'[["company", "=", "{self.config.default_company}"]]',
                'limit_page_length': 1000,
            }
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch cost centers: {e}")
            return []
