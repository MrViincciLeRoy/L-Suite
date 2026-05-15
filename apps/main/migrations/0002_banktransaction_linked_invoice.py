from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0001_initial'),          # adjust to your last main migration
        ('invoices', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='banktransaction',
            name='linked_invoice',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='linked_transactions',
                to='invoices.erpnextinvoice',
            ),
        ),
    ]