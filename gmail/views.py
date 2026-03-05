import logging
from datetime import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse
from django.core.paginator import Paginator

from main.models import (
    GoogleCredential, EmailStatement, BankTransaction, TransactionCategory
)
from .services import GmailService
from .csv_parser import CSVParser
# ── PDF Upload & Background Processing ───────────────────────────────────────

import threading
import uuid
from django.http import JsonResponse
from django.utils import timezone
from main.models import PDFImportJob

logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 20


# ── OAuth ──────────────────────────────────────────────────────────────────────

@login_required
def credentials(request):
    creds = GoogleCredential.objects.filter(user=request.user)
    return render(request, 'gmail/credentials.html', {'credentials': creds})


@login_required
def new_credential(request):
    if request.method == 'POST':
        cred = GoogleCredential.objects.create(
            user=request.user,
            name=request.POST['name'],
            client_id=request.POST['client_id'],
            client_secret=request.POST['client_secret'],
        )
        messages.success(request, 'Credential created! Now authorize access.')
        return redirect(reverse('gmail:authorize', kwargs={'pk': cred.pk}))
    return render(request, 'gmail/credential_form.html')


@login_required
def authorize(request, pk):
    credential = get_object_or_404(GoogleCredential, pk=pk, user=request.user)
    service = GmailService()
    auth_url = service.get_auth_url(credential, request)
    return redirect(auth_url)


@login_required
def oauth_callback(request):
    code = request.GET.get('code')
    state = request.GET.get('state')

    if not code or not state:
        messages.error(request, 'OAuth authorization failed.')
        return redirect(reverse('gmail:credentials'))

    credential = get_object_or_404(GoogleCredential, pk=int(state), user=request.user)
    service = GmailService()
    success = service.exchange_code_for_tokens(credential, code, request)

    if success:
        messages.success(request, 'Gmail access authorized!')
    else:
        messages.error(request, 'Authorization failed.')

    return redirect(reverse('gmail:credentials'))


@login_required
def delete_credential(request, pk):
    credential = get_object_or_404(GoogleCredential, pk=pk, user=request.user)
    if request.method == 'POST':
        credential.delete()
        messages.success(request, 'Credential deleted.')
    return redirect(reverse('gmail:credentials'))


# ── Statements ─────────────────────────────────────────────────────────────────

@login_required
def statements(request):
    stmts_qs = EmailStatement.objects.filter(user=request.user).order_by('-received_date')
    paginator = Paginator(stmts_qs, ITEMS_PER_PAGE)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'gmail/statements.html', {'statements': page})


@login_required
def import_statements(request):
    if request.method == 'POST':
        credential = GoogleCredential.objects.filter(user=request.user, is_authenticated=True).first()
        if not credential:
            messages.error(request, 'No authenticated Google credential found.')
            return redirect(reverse('gmail:credentials'))

        try:
            service = GmailService()
            imported, skipped = service.fetch_statements(credential)
            messages.success(request, f'Imported {imported} statements ({skipped} already existed).')
        except Exception as e:
            messages.error(request, f'Import failed: {e}')
            logger.error(f"Statement import error: {e}")

    return redirect(reverse('gmail:statements'))


@login_required
def statement_detail(request, pk):
    statement = get_object_or_404(EmailStatement, pk=pk, user=request.user)
    txns = BankTransaction.objects.filter(statement=statement).order_by('-date')
    return render(request, 'gmail/statement_detail.html', {
        'statement': statement,
        'transactions': txns,
    })


@login_required
def parse_statement(request, pk):
    statement = get_object_or_404(EmailStatement, pk=pk, user=request.user)

    if request.method == 'POST':
        credential = GoogleCredential.objects.filter(user=request.user, is_authenticated=True).first()
        if not credential:
            messages.error(request, 'No authenticated Google credential.')
            return redirect(reverse('gmail:statements'))

        pdf_password = request.POST.get('pdf_password', '').strip()
        save_password = request.POST.get('save_password') == 'yes'

        password_to_use = pdf_password or statement.pdf_password

        if save_password and pdf_password:
            statement.pdf_password = pdf_password
            statement.save()

        old_password = statement.pdf_password
        statement.pdf_password = password_to_use

        try:
            service = GmailService()
            count = service.download_and_parse_pdf(credential, statement)

            if not save_password and pdf_password:
                statement.pdf_password = old_password
                statement.save()

            messages.success(request, f'Extracted {count} transactions.')
        except ValueError as e:
            error_msg = str(e)
            if 'password' in error_msg.lower():
                messages.error(request, f'{error_msg}. Enter the correct PDF password.')
            else:
                messages.error(request, f'Parse failed: {error_msg}')
        except Exception as e:
            messages.error(request, f'Parse failed: {e}')
            logger.error(f"Error parsing statement {pk}: {e}", exc_info=True)

    return redirect(reverse('gmail:statement_detail', kwargs={'pk': pk}))


# ── Transactions ───────────────────────────────────────────────────────────────

@login_required
def transactions(request):
    qs = BankTransaction.objects.filter(user=request.user)

    if request.GET.get('uncategorized'):
        qs = qs.filter(category__isnull=True)
    if request.GET.get('not_synced'):
        qs = qs.filter(erpnext_synced=False)
    if request.GET.get('category_id'):
        qs = qs.filter(category_id=request.GET['category_id'])
    if request.GET.get('statement_id'):
        qs = qs.filter(statement_id=request.GET['statement_id'])

    qs = qs.order_by('-date')
    paginator = Paginator(qs, ITEMS_PER_PAGE)
    page = paginator.get_page(request.GET.get('page', 1))

    categories = TransactionCategory.objects.filter(active=True)
    return render(request, 'gmail/transactions.html', {
        'transactions': page,
        'categories': categories,
    })


@login_required
def transaction_detail(request, pk):
    transaction = get_object_or_404(BankTransaction, pk=pk, user=request.user)
    return render(request, 'gmail/transaction_detail.html', {'transaction': transaction})


# ── CSV Upload ─────────────────────────────────────────────────────────────────

@login_required
def upload_csv(request):
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')

        if not csv_file:
            messages.warning(request, 'No file selected.')
            return redirect(request.path)

        if not csv_file.name.endswith('.csv'):
            messages.warning(request, 'Please upload a CSV file.')
            return redirect(request.path)

        try:
            csv_data = csv_file.read()
            create_statement = request.POST.get('create_statement') == 'on'

            parser = CSVParser()
            parsed = parser.parse_csv(csv_data)

            if not parsed:
                messages.warning(request, 'No valid transactions found in CSV.')
                return redirect(request.path)

            statement = None
            if create_statement:
                statement = EmailStatement.objects.create(
                    user=request.user,
                    gmail_id=f"CSV-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
                    subject=f"CSV Import: {csv_file.name}",
                    sender='CSV Upload',
                    received_date=datetime.utcnow(),
                    bank_name='capitec',
                    is_processed=True,
                    has_pdf=False,
                )

            imported, skipped = 0, 0
            for td in parsed:
                exists = BankTransaction.objects.filter(
                    user=request.user,
                    date=td['transaction_date'],
                    description=td['description'],
                ).filter(
                    withdrawal=td['debits']
                ).exists() or BankTransaction.objects.filter(
                    user=request.user,
                    date=td['transaction_date'],
                    description=td['description'],
                    deposit=td['credits'],
                ).exists()

                if exists:
                    skipped += 1
                    continue

                BankTransaction.objects.create(
                    user=request.user,
                    statement=statement,
                    date=td['transaction_date'],
                    posting_date=td['posting_date'],
                    description=td['description'],
                    withdrawal=td['debits'],
                    deposit=td['credits'],
                    balance=td['balance'],
                    reference_number=td['reference'],
                )
                imported += 1

            messages.success(request, f'Imported {imported} transactions ({skipped} skipped).')
            return redirect(reverse('gmail:transactions'))

        except Exception as e:
            messages.error(request, f'Error importing CSV: {e}')
            logger.error(f"CSV import error: {e}", exc_info=True)
            return redirect(request.path)

    return render(request, 'gmail/upload_csv.html')


@login_required
def download_csv_template(request):
    template = (
        "Transaction Date,Posting Date,Description,Debits,Credits,Balance,Bank account\n"
        "2025/09/23,2025/09/23,Sample Transaction,,1000.00,5000.00,Capitec Savings\n"
        "2025/09/24,2025/09/24,Sample Payment,500.00,,4500.00,Capitec Savings\n"
    )
    response = HttpResponse(template, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=transaction_template.csv'
    return response


@login_required
def bulk_csv_import(request):
    if request.method == 'POST':
        files = request.FILES.getlist('csv_files')
        if not files:
            messages.warning(request, 'No files selected.')
            return redirect(request.path)

        parser = CSVParser()
        total_imported, total_skipped, files_processed = 0, 0, 0

        for f in files:
            if not f.name.endswith('.csv'):
                continue
            try:
                statement = EmailStatement.objects.create(
                    user=request.user,
                    gmail_id=f"CSV-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{files_processed}",
                    subject=f"CSV Import: {f.name}",
                    sender='Bulk CSV Upload',
                    received_date=datetime.utcnow(),
                    bank_name='capitec',
                    is_processed=True,
                    has_pdf=False,
                )

                parsed = parser.parse_csv(f.read())
                imported, skipped = 0, 0

                for td in parsed:
                    exists = BankTransaction.objects.filter(
                        user=request.user,
                        date=td['transaction_date'],
                        description=td['description'],
                        withdrawal=td['debits'],
                    ).exists()

                    if exists:
                        skipped += 1
                        continue

                    BankTransaction.objects.create(
                        user=request.user,
                        statement=statement,
                        date=td['transaction_date'],
                        posting_date=td['posting_date'],
                        description=td['description'],
                        withdrawal=td['debits'],
                        deposit=td['credits'],
                        balance=td['balance'],
                        reference_number=td['reference'],
                    )
                    imported += 1

                total_imported += imported
                total_skipped += skipped
                files_processed += 1

            except Exception as e:
                logger.error(f"Error processing {f.name}: {e}")
                continue

        messages.success(request, f'Processed {files_processed} files: {total_imported} imported, {total_skipped} skipped.')
        return redirect(reverse('gmail:transactions'))

    return render(request, 'gmail/bulk_csv_import.html')





def _run_pdf_job(job_id, pdf_bytes_list, filenames):
    """Background thread: parse PDFs and save transactions."""
    from main.models import PDFImportJob, EmailStatement, BankTransaction
    from gmail.parsers import PDFParser

    try:
        job = PDFImportJob.objects.get(pk=job_id)
        job.status = PDFImportJob.STATUS_PROCESSING
        job.total_files = len(pdf_bytes_list)
        job.save(update_fields=['status', 'total_files'])

        parser = PDFParser()
        total_saved = 0
        total_skipped = 0
        total_found = 0

        for idx, (pdf_bytes, filename) in enumerate(zip(pdf_bytes_list, filenames), start=1):
            # Create a statement record for each file
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

                saved = 0
                skipped = 0
                for t in transactions:
                    category = t['category'].split(' ')[-1]
                    exists = BankTransaction.objects.filter(
                        user=job.user,
                        date=t['date'],
                        description=t['description'],
                        amount=t['amount'],
                    ).exists()
                    
                    
                            
                        
                    if exists:
                        skipped += 1
                        continue

                        #skipped += 1
                        #continue
                    BankTransaction.objects.create(
                        user=job.user,
                        statement=statement,
                        date=t['date'],
                        description=t['description'],
                        amount=t['amount'],
                        transaction_type= t['type'] ,
                        reference_number= t['reference'],
                        balance= t['balance'],
                        #category = cat,
                        fee= t['fee'],
                    )
                    saved += 1

                statement.transaction_count = saved
                statement.state = 'parsed'
                statement.is_processed = True
                statement.processed_date = timezone.now()
                statement.save(update_fields=['transaction_count', 'state', 'is_processed', 'processed_date'])

                total_saved += saved
                total_skipped += skipped

            except Exception as e:
                statement.state = 'error'
                statement.error_message = str(e)
                statement.save(update_fields=['state', 'error_message'])

            # Update progress
            job.processed_files = idx
            job.progress = int((idx / len(pdf_bytes_list)) * 100)
            job.transactions_found = total_found
            job.transactions_saved = total_saved
            job.transactions_skipped = total_skipped
            job.save(update_fields=['processed_files', 'progress', 'transactions_found',
                                    'transactions_saved', 'transactions_skipped'])

        job.status = PDFImportJob.STATUS_DONE
        job.progress = 100
        job.save(update_fields=['status', 'progress'])

    except Exception as e:
        try:
            job = PDFImportJob.objects.get(pk=job_id)
            job.status = PDFImportJob.STATUS_FAILED
            job.error_message = str(e)
            job.save(update_fields=['status', 'error_message'])
        except Exception:
            pass


@login_required
def upload_pdf(request):
    if request.method == 'POST':
        pdf_files = request.FILES.getlist('pdf_files')
        bank_name = request.POST.get('bank_name', 'capitec')
        pdf_password = request.POST.get('pdf_password', '')

        if not pdf_files:
            messages.error(request, 'Please select at least one PDF file.')
            return redirect('gmail:upload_pdf')

        # Read all file bytes before the thread takes over
        pdf_bytes_list = [f.read() for f in pdf_files]
        filenames = [f.name for f in pdf_files]

        job = PDFImportJob.objects.create(
            user=request.user,
            filename=', '.join(filenames) if len(filenames) > 1 else filenames[0],
            bank_name=bank_name,
            pdf_password=pdf_password,
            status=PDFImportJob.STATUS_PENDING,
            total_files=len(pdf_files),
        )

        thread = threading.Thread(
            target=_run_pdf_job,
            args=(job.pk, pdf_bytes_list, filenames),
            daemon=True,
        )
        thread.start()

        return redirect('gmail:pdf_import_progress', pk=job.pk)

    # GET — show recent jobs too
    recent_jobs = PDFImportJob.objects.filter(user=request.user)[:10]
    return render(request, 'gmail/upload_pdf.html', {'recent_jobs': recent_jobs})


@login_required
def pdf_import_progress(request, pk):
    job = get_object_or_404(PDFImportJob, pk=pk, user=request.user)
    return render(request, 'gmail/pdf_import_progress.html', {'job': job})


@login_required
def pdf_import_status(request, pk):
    """JSON endpoint polled by the progress page."""
    job = get_object_or_404(PDFImportJob, pk=pk, user=request.user)
    return JsonResponse({
        'status': job.status,
        'progress': job.progress,
        'total_files': job.total_files,
        'processed_files': job.processed_files,
        'transactions_found': job.transactions_found,
        'transactions_saved': job.transactions_saved,
        'transactions_skipped': job.transactions_skipped,
        'error_message': job.error_message,
        'statement_id': job.statement_id,
    })


@login_required
def pdf_import_history(request):
    jobs = PDFImportJob.objects.filter(user=request.user)
    return render(request, 'gmail/pdf_import_history.html', {'jobs': jobs})
