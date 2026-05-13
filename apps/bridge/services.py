import logging
import requests
from datetime import datetime
from apps.main.models import ERPNextSyncLog

logger = logging.getLogger(__name__)


class ERPNextService:
    def __init__(self, config):
        self.config = config
        self.base_url = config.base_url.rstrip('/')

    def _get_headers(self):
        return {
            'Authorization': f'token {self.config.api_key}:{self.config.api_secret}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def test_connection(self):
        try:
            url = f"{self.base_url}/api/method/frappe.auth.get_logged_user"
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

    def _account_row(self, account, debit, credit, cost_center=None):
        row = {
            "doctype": "Journal Entry Account",
            "account": account,
            "debit_in_account_currency": debit,
            "credit_in_account_currency": credit,
        }
        if cost_center:
            row["cost_center"] = cost_center
        return row

    def create_journal_entry(self, transaction):
        if not transaction.category_id:
            raise ValueError("Transaction must be categorized before syncing")

        if not transaction.category.erpnext_account:
            raise ValueError(
                f"Category '{transaction.category.name}' has no ERPNext account configured"
            )

        posting_date = transaction.date.strftime('%Y-%m-%d')
        amount = abs(float(transaction.withdrawal or 0) or float(transaction.deposit or 0))

        if amount == 0:
            raise ValueError(f"Transaction {transaction.id} has zero amount, skipping")

        if transaction.transaction_type == 'debit':
            bank_row = self._account_row(self.config.bank_account, 0, amount)
            expense_row = self._account_row(
                transaction.category.erpnext_account,
                amount, 0,
                self.config.default_cost_center or None,
            )
        else:
            bank_row = self._account_row(self.config.bank_account, amount, 0)
            expense_row = self._account_row(
                transaction.category.erpnext_account,
                0, amount,
                self.config.default_cost_center or None,
            )

        journal_data = {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": self.config.default_company,
            "posting_date": posting_date,
            "accounts": [bank_row, expense_row],
            "user_remark": transaction.description or "",
        }

        if transaction.reference_number:
            journal_data["cheque_no"] = transaction.reference_number
            journal_data["cheque_date"] = posting_date

        url = f"{self.base_url}/api/resource/Journal Entry"

        try:
            response = requests.post(
                url, headers=self._get_headers(), json=journal_data, timeout=30,
            )
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

        except requests.exceptions.HTTPError as e:
            error_body = ''
            try:
                error_body = e.response.json().get('exception', e.response.text[:500])
            except Exception:
                error_body = e.response.text[:500]
            error_message = f"HTTP {e.response.status_code}: {error_body}"
            self._handle_sync_error(transaction, error_message)
            raise Exception(error_message) from e

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
        """
        Fetch all non-group leaf accounts. Paginates automatically if needed.
        Does NOT filter by company to avoid mismatch issues — returns all accounts
        for the instance and lets the caller/UI filter if needed.
        """
        url = f"{self.base_url}/api/resource/Account"
        all_accounts = []
        page_length = 500
        start = 0

        while True:
            params = {
                'fields': '["name", "account_name", "account_type", "root_type", "is_group", "company", "parent_account"]',
                'filters': '[["is_group", "=", 0]]',   # leaf accounts only
                'limit_page_length': page_length,
                'limit_start': start,
                'order_by': 'name asc',
            }
            try:
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
                response.raise_for_status()
                batch = response.json().get('data', [])
                all_accounts.extend(batch)
                if len(batch) < page_length:
                    break
                start += page_length
            except Exception as e:
                logger.error(f"Failed to fetch accounts (start={start}): {e}")
                break

        logger.info(f"ERPNext: fetched {len(all_accounts)} leaf accounts")
        return all_accounts

    def get_cost_centers(self):
        try:
            url = f"{self.base_url}/api/resource/Cost Center"
            params = {
                'fields': '["name", "cost_center_name", "company"]',
                'limit_page_length': 500,
                'order_by': 'name asc',
            }
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch cost centers: {e}")
            return []