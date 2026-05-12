import uuid
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def run_pdf_job(job_id, pdf_bytes_list, filenames):
    from apps.main.models import BankTransaction, EmailStatement, PDFImportJob, TransactionCategory
    from apps.bank_parsers.parsers import PDFParser

    try:
        job = PDFImportJob.objects.get(pk=job_id)
        job.status = PDFImportJob.STATUS_PROCESSING
        job.total_files = len(pdf_bytes_list)
        job.save(update_fields=['status', 'total_files'])

        parser = PDFParser()
        total_saved = total_skipped = total_found = 0

        for idx, (pdf_bytes, filename) in enumerate(zip(pdf_bytes_list, filenames), start=1):
            statement = EmailStatement.objects.create(
                user=job.user,
                gmail_id=f'pdf-upload-{uuid.uuid4().hex}',
                subject=filename,
                sender='PDF Upload',
                bank_name=job.bank_name,
                has_pdf=True,
                pdf_password=job.pdf_password,
                state='imported',
            )
            if idx == 1:
                job.statement = statement
                job.save(update_fields=['statement'])

            try:
                transactions = parser.parse_pdf(pdf_bytes, job.bank_name, job.pdf_password or None)
                total_found += len(transactions)
                saved = skipped = 0

                for t in transactions:
                    exists = BankTransaction.objects.filter(
                        user=job.user,
                        date=t['date'],
                        description=t['description'],
                        amount=t['amount'],
                    ).exists()
                    if exists:
                        skipped += 1
                        continue

                    category_obj = None
                    category_name = t.get('category')
                    if category_name:
                        category_obj, _ = TransactionCategory.objects.get_or_create(
                            name=category_name,
                            defaults={
                                'transaction_type': t.get('type', 'debit'),
                                'active': True,
                            },
                        )

                    BankTransaction.objects.create(
                        user=job.user,
                        statement=statement,
                        date=t['date'],
                        description=t['description'],
                        amount=t['amount'],
                        transaction_type=t['type'],
                        reference_number=t['reference'],
                        balance=t.get('balance'),
                        category=category_obj,
                        fee=t.get('fee'),
                    )
                    saved += 1

                statement.transaction_count = saved
                statement.state = 'parsed'
                statement.is_processed = True
                statement.processed_date = timezone.now()
                statement.save(update_fields=['transaction_count', 'state', 'is_processed', 'processed_date'])

                total_saved   += saved
                total_skipped += skipped

            except Exception as e:
                statement.state = 'error'
                statement.error_message = str(e)
                statement.save(update_fields=['state', 'error_message'])
                logger.error(f"Error parsing {filename}: {e}")

            job.processed_files       = idx
            job.progress              = int((idx / len(pdf_bytes_list)) * 100)
            job.transactions_found    = total_found
            job.transactions_saved    = total_saved
            job.transactions_skipped  = total_skipped
            job.save(update_fields=[
                'processed_files', 'progress',
                'transactions_found', 'transactions_saved', 'transactions_skipped',
            ])

        job.status   = PDFImportJob.STATUS_DONE
        job.progress = 100
        job.save(update_fields=['status', 'progress'])

    except Exception as e:
        try:
            job = PDFImportJob.objects.get(pk=job_id)
            job.status        = PDFImportJob.STATUS_FAILED
            job.error_message = str(e)
            job.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
        logger.error(f"PDF job {job_id} failed: {e}")
