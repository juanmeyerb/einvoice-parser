# E-Invoicing Parser

[![Tests](https://github.com/juanmeyerb/einvoice-parser/actions/workflows/tests.yml/badge.svg)](https://github.com/juanmeyerb/einvoice-parser/actions/workflows/tests.yml)

A Python pipeline that parses and validates electronic invoices from mixed formats (CSV, structured PDF, XML) into a single, validated data model. Built as a portfolio project to work through real e-invoicing standards (EN 16931, ZUGFeRD, XRechnung) and multi-format data extraction in Python with pydantic.

## Setup

Requires Python 3.12 and [Poetry](https://python-poetry.org/).

```bash
git clone https://github.com/juanmeyerb/einvoice-parser.git
cd einvoice-parser
poetry env use python3.12
poetry install
```

This project is developed and tested against Python 3.12. Some dependencies, `lxml` in particular, may not yet have precompiled wheels for the newest Python releases, so 3.12 is recommended even if a newer version is installed system-wide.

## Usage

### Command line

```bash
einvoice-parser examples/invoice.csv               # single file, human-readable summary
einvoice-parser examples/invoice_zugferd.pdf --json # single file, full JSON output
einvoice-parser examples/                            # a whole directory, batch mode
```

### Python API

Parse a single file:

```python
from einvoice_parser.pipeline import InvoicePipeline

pipeline = InvoicePipeline()
invoice = pipeline.process_file("path/to/invoice.csv")  # .csv, .xml, or .pdf

print(invoice.invoice_number, invoice.total_amount, invoice.source_format)
```

Process a folder of mixed invoices:

```python
from einvoice_parser.pipeline import InvoicePipeline

pipeline = InvoicePipeline()
result = pipeline.process_directory("path/to/invoices/")

print(f"{len(result.successes)} succeeded, {len(result.failures)} failed")

for invoice in result.successes:
    print(f"  OK: {invoice.invoice_number} ({invoice.source_format.value})")

for file_path, error_message in result.failures:
    print(f"  FAILED: {file_path.name} — {error_message}")
```

## What it does

Every invoice, regardless of source format, is converted into the same `Invoice` schema, defined with pydantic v2. The model checks its own consistency on construction; a total that doesn't match net plus tax is rejected at parse time rather than passed downstream.

CSV input is read as a tabular export, one row per line item. XRechnung input is parsed as CII-syntax XML, the format used for B2G e-invoicing in Germany. PDF input is handled two ways: a ZUGFeRD or Factur-X file has its structured XML attachment extracted and parsed with the same logic as XRechnung, while a plain PDF with no embedded XML falls back to text extraction and regex-based field matching.

The pipeline can also process a whole folder of mixed-format invoices at once. Each file is routed by extension; a file that fails to parse is recorded with its error message rather than stopping the batch, so one bad invoice doesn't block the rest. All parsers raise the same `ParsingError` on failure, whatever the underlying cause: a missing CSV column, malformed XML, a PDF field the regex patterns couldn't find.

35 automated tests cover the happy path, malformed input, and edge cases for each parser.

## Project structure

```
src/einvoice_parser/
├── models.py              # Common Invoice / Party / InvoiceLine schema (pydantic)
├── pipeline.py             # Orchestrator: routes files to the correct parser
└── parsers/
    ├── base.py              # Shared BaseParser interface + ParsingError
    ├── csv_parser.py         # CSV parser
    ├── xrechnung_parser.py    # XRechnung (CII/XML) parser
    └── pdf_parser.py           # PDF parser (ZUGFeRD + plain-text fallback)

tests/
├── fixtures/                # Sample invoices used by the test suite
├── test_csv_parser.py
├── test_xrechnung_parser.py
├── test_pdf_parser.py
└── test_pipeline.py
```

## Running tests

```bash
poetry run pytest -v
```

## Known limitations

This project favors clear parsing architecture and error handling over full legal compliance, and scopes out several things EN 16931 compliance would require. XRechnung support covers CII syntax only; the UBL variant is not handled. The data model holds a single VAT rate per invoice, with no breakdown across multiple rates for invoices that mix, for example, 19% and 7% line items. Header- or line-level allowances and charges are not modeled; totals are trusted as given rather than reconstructed from a breakdown.

ZUGFeRD detection depends on a small set of known attachment filenames (`factur-x.xml`, `zugferd-invoice.xml`, `xrechnung.xml`). A ZUGFeRD PDF using a different attachment name will not be detected, and falls through to the plain-text path instead.

The plain-text PDF fallback is a heuristic, not a general solution. It has no OCR, so scanned or image-only PDFs cannot be parsed. Its regex patterns recognize a limited set of English and German invoice labels. It works best on simple label-value layouts; PDFs with table or column-based layouts may not extract correctly, since `pdfplumber`'s linear text extraction doesn't preserve visual column structure. Line items and recipient information are never extracted on this path, only invoice-level totals and issuer information.

## Tech stack

Python 3.12, pydantic v2 for validation and the common schema, lxml for XML parsing, pdfplumber for PDF text extraction, pypdf for reading PDF attachments, pytest for testing.

## License

MIT
