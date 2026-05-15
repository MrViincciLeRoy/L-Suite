from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ERPNextInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invoice_type', models.CharField(choices=[('sales', 'Sales Invoice'), ('purchase', 'Purchase Invoice')], max_length=20)),
                ('erp_name', models.CharField(max_length=100)),
                ('erp_status', models.CharField(
                    choices=[
                        ('Draft', 'Draft'), ('Submitted', 'Submitted'), ('Unpaid', 'Unpaid'),
                        ('Partly Paid', 'Partly Paid'), ('Paid', 'Paid'),
                        ('Overdue', 'Overdue'), ('Cancelled', 'Cancelled'),
                    ],
                    default='Unpaid',
                    max_length=50,
                )),
                ('party_id', models.CharField(blank=True, max_length=200)),
                ('party_name', models.CharField(blank=True, max_length=255)),
                ('currency', models.CharField(default='ZAR', max_length=10)),
                ('grand_total', models.DecimalField(decimal_places=2, max_digits=14)),
                ('outstanding_amount', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('posting_date', models.DateField()),
                ('due_date', models.DateField(blank=True, null=True)),
                ('bill_no', models.CharField(blank=True, max_length=100)),
                ('bill_date', models.DateField(blank=True, null=True)),
                ('fetched_at', models.DateTimeField(auto_now=True)),
                ('raw_data', models.JSONField(blank=True, default=dict)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-posting_date'],
            },
        ),
        migrations.AddIndex(
            model_name='erpnextinvoice',
            index=models.Index(fields=['user', 'invoice_type', 'erp_status'], name='inv_user_type_status_idx'),
        ),
        migrations.AddIndex(
            model_name='erpnextinvoice',
            index=models.Index(fields=['user', 'posting_date'], name='inv_user_date_idx'),
        ),
        migrations.AddIndex(
            model_name='erpnextinvoice',
            index=models.Index(fields=['user', 'party_name'], name='inv_user_party_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='erpnextinvoice',
            unique_together={('user', 'erp_name')},
        ),
    ]