"""Tests for InvoicePipeline."""
import shutil
from pathlib import Path

import pytest

from einvoice_parser.parsers.base import ParsingError
from einvoice_parser.pipeline import BatchResult, InvoicePipeline, UnsupportedFormatError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# process_file: routing
# ---------------------------------------------------------------------------

def test_process_file_routes_csv_to_csv_parser():
    pipeline = InvoicePipeline()
    invoice = pipeline.process_file(FIXTURES_DIR / "sample_invoice.csv")
    assert invoice.source_format.value == "csv"


def test_process_file_routes_xml_to_xrechnung_parser():
    pipeline = InvoicePipeline()
    invoice = pipeline.process_file(FIXTURES_DIR / "sample_xrechnung.xml")
    assert invoice.source_format.value == "xml_xrechnung"


def test_process_file_routes_zugferd_pdf_correctly():
    pipeline = InvoicePipeline()
    invoice = pipeline.process_file(FIXTURES_DIR / "sample_zugferd.pdf")
    assert invoice.source_format.value == "pdf_zugferd"


def test_process_file_routes_plain_pdf_correctly():
    pipeline = InvoicePipeline()
    invoice = pipeline.process_file(FIXTURES_DIR / "sample_plain_invoice.pdf")
    assert invoice.source_format.value == "pdf_unstructured"


def test_process_file_unsupported_extension_raises_error(tmp_path):
    """A file with an extension no parser handles (e.g. .txt) should raise
    UnsupportedFormatError, which is a ParsingError subclass."""
    unsupported_file = tmp_path / "notes.txt"
    unsupported_file.write_text("this is not an invoice")

    pipeline = InvoicePipeline()
    with pytest.raises(UnsupportedFormatError):
        pipeline.process_file(unsupported_file)

    # It should also be catchable as a plain ParsingError, since it's a subclass.
    with pytest.raises(ParsingError):
        pipeline.process_file(unsupported_file)


def test_process_file_missing_file_raises_parsing_error(tmp_path):
    """A recognized extension but a nonexistent file should still fail cleanly
    (propagated from the underlying parser, e.g. CSVParser)."""
    pipeline = InvoicePipeline()
    with pytest.raises(ParsingError):
        pipeline.process_file(tmp_path / "does_not_exist.csv")


# ---------------------------------------------------------------------------
# process_directory: batch behavior
# ---------------------------------------------------------------------------

def test_process_directory_skips_unrelated_files_and_subdirectories(tmp_path):
    """A README-like file and a subdirectory sitting next to invoices should be
    ignored, not counted as failures."""
    shutil.copy(FIXTURES_DIR / "sample_invoice.csv", tmp_path / "a.csv")
    (tmp_path / "README.md").write_text("not an invoice")
    (tmp_path / "some_subdir").mkdir()

    pipeline = InvoicePipeline()
    result = pipeline.process_directory(tmp_path)

    assert isinstance(result, BatchResult)
    assert len(result.successes) == 1
    assert len(result.failures) == 0
    assert result.total == 1  # README.md and some_subdir must NOT be counted


def test_process_directory_collects_failures_without_stopping(tmp_path):
    """One broken invoice in a batch should be recorded as a failure, while the
    rest of the batch still processes successfully."""
    shutil.copy(FIXTURES_DIR / "sample_invoice.csv", tmp_path / "good.csv")

    # A CSV missing a required column ('line_unit_price'), same technique as in
    # test_csv_parser.py.
    broken_csv = tmp_path / "broken.csv"
    broken_csv.write_text(
        "invoice_number,issue_date,issuer_name,net_amount,tax_amount,total_amount,"
        "line_description,line_quantity,line_amount\n"
        "INV-BROKEN,2026-09-01,ACME GmbH,100.00,19.00,119.00,Consulting hours,2,100.00\n"
    )

    pipeline = InvoicePipeline()
    result = pipeline.process_directory(tmp_path)

    assert len(result.successes) == 1
    assert len(result.failures) == 1
    assert result.total == 2

    failed_path, failed_message = result.failures[0]
    assert failed_path.name == "broken.csv"
    assert len(failed_message) > 0  # some explanatory message was captured


def test_process_directory_handles_mixed_formats(tmp_path):
    """A directory with all three supported formats should process all of them,
    correctly tagging each with its own source_format."""
    shutil.copy(FIXTURES_DIR / "sample_invoice.csv", tmp_path / "a.csv")
    shutil.copy(FIXTURES_DIR / "sample_xrechnung.xml", tmp_path / "b.xml")
    shutil.copy(FIXTURES_DIR / "sample_zugferd.pdf", tmp_path / "c.pdf")

    pipeline = InvoicePipeline()
    result = pipeline.process_directory(tmp_path)

    assert len(result.successes) == 3
    assert len(result.failures) == 0
    formats = {inv.source_format.value for inv in result.successes}
    assert formats == {"csv", "xml_xrechnung", "pdf_zugferd"}


def test_process_directory_empty_directory_returns_empty_result(tmp_path):
    pipeline = InvoicePipeline()
    result = pipeline.process_directory(tmp_path)
    assert result.successes == []
    assert result.failures == []
    assert result.total == 0