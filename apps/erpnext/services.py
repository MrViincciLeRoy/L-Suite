import logging
import requests
from django.utils import timezone
from apps.main.models import ERPNextSyncLog

logger = logging.getLogger(__name__)


class ERPNextService:
    def __init__(self, config):
        self.config = config
        self.base_url = config.base_url.rstrip('/')
        self._resolved_company = None

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

    def _resolve_company_name(self):
        if self._resolved_company:
            return self._resolved_company

        stored = (self.config.default_company or '').strip()
        if not stored:
            raise ValueError("No company configured. Set default_company in your ERPNext config.")

        companies = self.get_companies()
        if not companies:
            self._resolved_company = stored
            return stored

        for c in companies:
            if c.get('name', '') == stored:
                self._resolved_company = stored
                return stored

        for c in companies:
            if c.get('abbr', '').strip().upper() == stored.upper():
                full_name = c['name']
                logger.warning(f"Resolved company abbreviation '{stored}' -> '{full_name}'.")
                self._resolved_company = full_name
                return full_name

        stored_lower = stored.lower()
        for c in companies:
            if stored_lower in c.get('name', '').lower():
                full_name = c['name']
                logger.warning(f"Partial company match '{stored}' -> '{full_name}'.")
                self._resolved_company = full_name
                return full_name

        self._resolved_company = stored
        return stored

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

    def _extract_amount(self, transaction):
        def to_float(val):
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        withdrawal = to_float(getattr(transaction, 'withdrawal', None))
        deposit    = to_float(getattr(transaction, 'deposit', None))
        amount     = to_float(getattr(transaction, 'amount', None))

        if withdrawal != 0.0:
            return abs(withdrawal)
        if deposit != 0.0:
            return abs(deposit)
        if amount != 0.0:
            return abs(amount)
        return 0.0

    def _resolve_account(self, search_term):
        if not search_term:
            return search_term
        if ' - ' in search_term:
            return search_term
        url = f"{self.base_url}/api/resource/Account"
        params = {
            "filters": f'[["name","like","%{search_term}%"]]',
            "limit_page_length": 1,
        }
        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get('data', [])
            if data:
                resolved = data[0]['name']
                if resolved != search_term:
                    logger.info(f"Resolved account '{search_term}' -> '{resolved}'")
                return resolved
        except Exception as e:
            logger.error(f"Account resolution failed for '{search_term}': {e}")
        return search_term

    def _get_bank_account_for_transaction(self, transaction):
        if transaction.bank_account_id and transaction.bank_account:
            acct = (transaction.bank_account.erpnext_account or '').strip()
            if acct:
                return acct
        return (self.config.bank_account or '').strip()

    def fetch_journal_entries(self, from_date, to_date):
        url = f"{self.base_url}/api/resource/Journal Entry"
        params = {
            'fields': '["name","posting_date","total_debit","total_credit","remark","cheque_no","user_remark"]',
            'filters': f'[["posting_date",">=","{from_date}"],["posting_date","<=","{to_date}"],["docstatus","=","1"]]',
            'limit_page_length': 500,
        }
        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"fetch_journal_entries failed: {e}")
            raise

    def create_journal_entry(self, transaction):
        if not transaction.category_id:
            raise ValueError("Transaction must be categorized before syncing")

        erpnext_account = (transaction.category.erpnext_account or '').strip()
        if not erpnext_account:
            raise ValueError(
                f"Category '{transaction.category.name}' has no ERPNext account configured"
            )

        company      = self._resolve_company_name()
        posting_date = transaction.date.strftime('%Y-%m-%d')
        amount       = self._extract_amount(transaction)

        if amount == 0.0:
            raise ValueError(f"Transaction {transaction.id} has zero amount")

        raw_bank_account = self._get_bank_account_for_transaction(transaction)
        if not raw_bank_account:
            raise ValueError(
                f"No ERPNext bank account configured for transaction {transaction.id}. "
                "Set erpnext_account on the linked BankAccount, or open Sync Preflight to assign one."
            )

        bank_account    = self._resolve_account(raw_bank_account)
        expense_account = self._resolve_account(erpnext_account)

        if transaction.transaction_type == 'debit':
            bank_row    = self._account_row(bank_account, 0, amount)
            expense_row = self._account_row(
                expense_account, amount, 0,
                self.config.default_cost_center or None,
            )
        else:
            bank_row    = self._account_row(bank_account, amount, 0)
            expense_row = self._account_row(
                expense_account, 0, amount,
                self.config.default_cost_center or None,
            )

        journal_data = {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": company,
            "posting_date": posting_date,
            "accounts": [bank_row, expense_row],
            "user_remark": transaction.description or "",
        }

        if transaction.reference_number:
            journal_data["cheque_no"]   = transaction.reference_number
            journal_data["cheque_date"] = posting_date

        url = f"{self.base_url}/api/resource/Journal Entry"

        try:
            response = requests.post(
                url, headers=self._get_headers(), json=journal_data, timeout=30,
            )
            response.raise_for_status()
            journal_entry_name = response.json().get('data', {}).get('name')

            transaction.erpnext_synced        = True
            transaction.erpnext_journal_entry = journal_entry_name
            transaction.erpnext_sync_date     = timezone.now()
            transaction.erpnext_error         = ''
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
        logger.error(f"Sync failed for transaction {transaction.id}: {error_message}")
        transaction.erpnext_error = error_message
        transaction.save()
        ERPNextSyncLog.objects.create(
            config=self.config,
            record_type='bank_transaction',
            record_id=transaction.id,
            status='failed',
            error_message=error_message,
        )

    def get_companies(self):
        url = f"{self.base_url}/api/resource/Company"
        params = {
            'fields': '["name","company_name","abbr","default_currency"]',
            'limit_page_length': 200,
        }
        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=15)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch companies: {e}")
            return []

    def get_chart_of_accounts(self):
        url          = f"{self.base_url}/api/resource/Account"
        all_accounts = []
        page_start   = 0
        page_length  = 500

        while True:
            params = {
                'fields': '["name","account_name","account_type","root_type","is_group","company"]',
                'limit_start': page_start,
                'limit_page_length': page_length,
            }
            try:
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
                response.raise_for_status()
                batch = response.json().get('data', [])
            except Exception as e:
                logger.error(f"Failed to fetch accounts (offset={page_start}): {e}")
                break

            if not batch:
                break
            all_accounts.extend(batch)
            if len(batch) < page_length:
                break
            page_start += page_length

        company = (self.config.default_company or '').strip()
        if company and all_accounts and all_accounts[0].get('company') is not None:
            filtered = [a for a in all_accounts if a.get('company') == company]
            if not filtered:
                companies = self.get_companies()
                resolved = company
                for c in companies:
                    if c.get('abbr', '').strip().upper() == company.upper():
                        resolved = c['name']
                        break
                if resolved != company:
                    filtered = [a for a in all_accounts if a.get('company') == resolved]
            all_accounts = filtered if filtered else all_accounts

        return all_accounts

    def get_cost_centers(self):
        url = f"{self.base_url}/api/resource/Cost Center"
        params = {
            'fields': '["name","cost_center_name","company"]',
            'limit_page_length': 500,
        }
        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch cost centers: {e}")
            return []