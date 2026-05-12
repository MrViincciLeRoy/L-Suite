# bank_parsers

Django app that owns all bank statement parsing and file upload logic.

## Structure

```
apps/bank_parsers/
├── apps.py
├── banks/              # reserved — bank account configs/models go here later
├── parsers/
│   ├── main.py         # PDFParser — routes to the right bank parser
│   ├── gotyme.py       # GoTyme char-level parser (pdfplumber, stamp-safe)
│   ├── tymebank.py     # Legacy TymeBank regex parser
│   ├── capitec.py      # Capitec parser
│   └── generic.py      # Fallback regex parser for unknown banks
└── uploads/
    ├── csv_parser.py   # CSVParser — Capitec/generic CSV import
    └── pdf_upload.py   # run_pdf_job() — background thread worker for PDF uploads
```

## Usage

```python
from apps.bank_parsers.parsers import PDFParser
from apps.bank_parsers.uploads import CSVParser, run_pdf_job

# Parse a PDF
transactions = PDFParser().parse_pdf(pdf_bytes, bank_name='tymebank', password=None)

# Parse a CSV
rows = CSVParser().parse_csv(csv_bytes)

# Run a background PDF import job (call from a thread)
import threading
t = threading.Thread(target=run_pdf_job, args=(job.pk, pdf_bytes_list, filenames), daemon=True)
t.start()
```

## Adding a new bank

1. Create `apps/bank_parsers/parsers/mybank.py` with a class that has a `.parse(text_or_bytes)` method returning a list of dicts with keys: `date, description, amount, type, reference`.
2. Import it in `main.py` and add a routing condition in `PDFParser.parse_pdf`.

## Register the app

Add `'apps.bank_parsers'` to `INSTALLED_APPS` in `settings.py`.

## Import updates in apps/gmail

| Old import | New import |
|---|---|
| `from .parsers import PDFParser` | `from apps.bank_parsers.parsers import PDFParser` |
| `from .csv_parser import CSVParser` | `from apps.bank_parsers.uploads import CSVParser` |
| `_run_pdf_job(...)` in views.py | `from apps.bank_parsers.uploads import run_pdf_job` |
