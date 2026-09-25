"""Tests for CSVParser."""
from decimal import Decimal
from pathlib import Path

import pytest

from einvoice_parser.parsers.base import ParsingError
from einvoice_parser.parsers.csv_parser import CSVParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_valid_csv_returns_invoice():
    """A well-formed CSV should parse into a valid, correctly-populated Invoice."""
    parser = CSVParser()
    invoice = parser.parse(FIXTURES_DIR / "sample_invoice.csv")

    assert invoice.invoice_number == "INV-2026-001"
    assert invoice.issuer.name == "ACME GmbH"
    assert invoice.issuer.tax_id == "DE123456789"
    assert invoice.recipient.name == "Beta Corp"
    assert invoice.net_amount == Decimal("100.00")
    assert invoice.tax_amount == Decimal("19.00")
    assert invoice.total_amount == Decimal("119.00")
    assert len(invoice.lines) == 1
    assert invoice.lines[0].description == "Consulting hours"
    assert invoice.lines[0].quantity == Decimal("2")
    assert invoice.source_format.value == "csv"


def test_parse_missing_file_raises_parsing_error():
    """Parsing a nonexistent path should raise ParsingError, not a raw FileNotFoundError."""
    parser = CSVParser()
    with pytest.raises(ParsingError):
        parser.parse(FIXTURES_DIR / "does_not_exist.csv")


def test_parse_csv_missing_required_column_raises_parsing_error(tmp_path):
    """A CSV missing a required column (e.g. line_unit_price) should raise ParsingError,
    not an unhandled KeyError."""
    broken_csv = tmp_path / "broken_invoice.csv"
    broken_csv.write_text(
        "invoice_number,issue_date,issuer_name,net_amount,tax_amount,total_amount,"
        "line_description,line_quantity,line_amount\n"
        "INV-BROKEN,2026-09-01,ACME GmbH,100.00,19.00,119.00,Consulting hours,2,100.00\n"
    )
    # Note: line_unit_price column is intentionally missing above.

    parser = CSVParser()
    with pytest.raises(ParsingError):
        parser.parse(broken_csv)


def test_parse_csv_with_inconsistent_totals_raises_parsing_error(tmp_path):
    """A CSV where total_amount doesn't match net_amount + tax_amount should be rejected
    by the Invoice model's validator, wrapped as ParsingError."""
    bad_totals_csv = tmp_path / "bad_totals_invoice.csv"
    bad_totals_csv.write_text(
        "invoice_number,issue_date,issuer_name,net_amount,tax_amount,total_amount,"
        "line_description,line_quantity,line_unit_price,line_amount\n"
        "INV-BADMATH,2026-09-01,ACME GmbH,100.00,19.00,999.00,Consulting hours,2,50.00,100.00\n"
    )

    parser = CSVParser()
    with pytest.raises(ParsingError):
        parser.parse(bad_totals_csv)