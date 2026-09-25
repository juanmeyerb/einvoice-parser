"""Tests for PDFParser."""
from decimal import Decimal
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from einvoice_parser.parsers.base import ParsingError
from einvoice_parser.parsers.pdf_parser import PDFParser, _detect_currency, _parse_amount

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _build_pdf(path: Path, lines: list[str]) -> None:
    """Writes a simple one-page PDF with the given lines of text, one per row."""
    c = canvas.Canvas(str(path), pagesize=(400, 500))
    y = 470
    for line in lines:
        c.drawString(30, y, line)
        y -= 20
    c.save()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_parse_valid_zugferd_pdf_returns_invoice():
    """A ZUGFeRD PDF with embedded CII XML should parse via the XML path."""
    parser = PDFParser()
    invoice = parser.parse(FIXTURES_DIR / "sample_zugferd.pdf")

    assert invoice.invoice_number == "INV-2026-XR-001"
    assert invoice.issuer.name == "ACME GmbH"
    assert invoice.net_amount == Decimal("100.00")
    assert invoice.total_amount == Decimal("119.00")
    assert len(invoice.lines) == 1
    assert invoice.source_format.value == "pdf_zugferd"


def test_parse_valid_plain_text_pdf_returns_invoice():
    """A plain PDF with no embedded XML should parse via the text-heuristic path."""
    parser = PDFParser()
    invoice = parser.parse(FIXTURES_DIR / "sample_plain_invoice.pdf")

    assert invoice.invoice_number == "INV-PLAIN-001"
    assert invoice.issuer.name == "ACME GmbH"
    assert invoice.net_amount == Decimal("200.00")
    assert invoice.tax_amount == Decimal("38.00")
    assert invoice.total_amount == Decimal("238.00")
    assert invoice.currency == "EUR"
    assert invoice.lines == []  # line items are never extracted on this path
    assert invoice.recipient is None  # recipient is never extracted on this path
    assert invoice.source_format.value == "pdf_unstructured"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

def test_parse_missing_file_raises_parsing_error():
    parser = PDFParser()
    with pytest.raises(ParsingError):
        parser.parse(FIXTURES_DIR / "does_not_exist.pdf")


def test_parse_plain_pdf_missing_total_raises_parsing_error(tmp_path):
    """A plain PDF missing the required 'Total' field should raise ParsingError,
    not silently return an incomplete Invoice."""
    path = tmp_path / "missing_total.pdf"
    _build_pdf(
        path,
        [
            "Invoice Number: INV-INCOMPLETE-001",
            "Invoice Date: 2026-09-10",
            "Issuer: ACME GmbH",
            "Net Amount: 200.00",
            "Tax Amount: 38.00",
            # Total Amount intentionally omitted
        ],
    )

    parser = PDFParser()
    with pytest.raises(ParsingError):
        parser.parse(path)


def test_parse_plain_pdf_missing_net_and_tax_raises_parsing_error(tmp_path):
    """A plain PDF with a total but no net/tax breakdown should also fail,
    since we deliberately don't infer missing amounts."""
    path = tmp_path / "totals_only.pdf"
    _build_pdf(
        path,
        [
            "Invoice Number: INV-TOTALSONLY-001",
            "Invoice Date: 2026-09-10",
            "Issuer: ACME GmbH",
            "Total Amount: 238.00",
            # Net and Tax amounts intentionally omitted
        ],
    )

    parser = PDFParser()
    with pytest.raises(ParsingError):
        parser.parse(path)


# ---------------------------------------------------------------------------
# Unit tests for the pure helper functions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("200.00", Decimal("200.00")),
        ("38,00", Decimal("38.00")),           # European decimal comma
        ("1,234.56", Decimal("1234.56")),      # US thousands + decimal
        ("1.234,56", Decimal("1234.56")),      # European thousands + decimal
        ("1,234,567.89", Decimal("1234567.89")),  # multiple US thousands separators
    ],
)
def test_parse_amount_handles_separator_conventions(raw, expected):
    assert _parse_amount(raw) == expected


@pytest.mark.parametrize(
    "text, expected_currency",
    [
        ("Total: 238.00", "EUR"),                # no signal -> default
        ("Total: $238.00", "USD"),                # symbol
        ("Total: 238.00 USD", "USD"),              # explicit ISO code
        ("Gesamtbetrag: 238,00 EUR", "EUR"),        # explicit code, German label
        ("Total: £238.00", "GBP"),                  # symbol
        ("Total Amount: 238.00 CHF", "CHF"),        # code with no symbol mapping
    ],
)
def test_detect_currency(text, expected_currency):
    assert _detect_currency(text) == expected_currency