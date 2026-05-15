from calendar import monthrange

from apps.erpnext.models import ERPNextConfig
from apps.erpnext.services import ERPNextService
from .models import ERPNextInvoice


class InvoiceSyncService:

    def __init__(self, user):
        self.user = user
        self.config = ERPNextConfig.objects.filter(user=user, is_active=True).first()
        if not self.config:
            raise ValueError("No active ERPNext config found.")
        self.client = ERPNextService(self.config)

    def sync_period(self, year, month):
        """
        Pull Sales + Purchase Invoices from ERPNext for a given month.
        Returns a dict with counts.
        """
        _, last_day = monthrange(year, month)
        from_date = f"{year}-{month:02d}-01"
        to_date = f"{year}-{month:02d}-{last_day:02d}"

        results = {
            'sales_fetched': 0, 'sales_created': 0, 'sales_updated': 0,
            'purchase_fetched': 0, 'purchase_created': 0, 'purchase_updated': 0,
        }

        sales_data = self.client.fetch_sales_invoices(from_date, to_date)
        results['sales_fetched'] = len(sales_data)
        for entry in sales_data:
            created = self._upsert_invoice(entry, 'sales')
            if created:
                results['sales_created'] += 1
            else:
                results['sales_updated'] += 1

        purchase_data = self.client.fetch_purchase_invoices(from_date, to_date)
        results['purchase_fetched'] = len(purchase_data)
        for entry in purchase_data:
            created = self._upsert_invoice(entry, 'purchase')
            if created:
                results['purchase_created'] += 1
            else:
                results['purchase_updated'] += 1

        return results

    def _upsert_invoice(self, data, invoice_type):
        """Create or update a local ERPNextInvoice from raw API data. Returns True if created."""
        if invoice_type == 'sales':
            party_id = data.get('customer', '')
            party_name = data.get('customer_name', '') or data.get('customer', '')
        else:
            party_id = data.get('supplier', '')
            party_name = data.get('supplier_name', '') or data.get('supplier', '')

        defaults = {
            'invoice_type': invoice_type,
            'erp_status': data.get('status', 'Unpaid'),
            'party_id': party_id,
            'party_name': party_name,
            'currency': data.get('currency', 'ZAR'),
            'grand_total': data.get('grand_total', 0),
            'outstanding_amount': data.get('outstanding_amount', 0),
            'posting_date': data['posting_date'],
            'due_date': data.get('due_date') or None,
            'bill_no': data.get('bill_no', ''),
            'bill_date': data.get('bill_date') or None,
            'raw_data': data,
        }

        obj, created = ERPNextInvoice.objects.update_or_create(
            user=self.user,
            erp_name=data['name'],
            defaults=defaults,
        )
        return created