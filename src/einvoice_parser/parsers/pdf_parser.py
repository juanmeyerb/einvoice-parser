"""PDF invoice parser.

Handles two distinct cases under one interface:
  1. ZUGFeRD/Factur-X PDFs, which have a structured CII XML file embedded
     as a PDF attachment. When found, we parse that XML using the exact
     same logic as XRechnungParser (see parse_cii_root).
  2. Plain/unstructured PDFs, with no embedded XML. We fall back to
     extracting raw text (via pdfplumber) and applying regex heuristics
     to find the fields our Invoice model needs. This path is inherently
     less reliable than structured formats, since it depends on the PDF's
     wording and layout matching the patterns below.
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber
from lxml import etree
from pydantic import ValidationError
from pypdf import PdfReader

from einvoice_parser.models import Invoice, InvoiceLine, Party, SourceFormat
from einvoice_parser.parsers.base import BaseParser, ParsingError
from einvoice_parser.parsers.xrechnung_parser import parse_cii_root

# Common filenames ZUGFeRD/Factur-X software uses for the embedded XML attachment.
ZUGFERD_ATTACHMENT_NAMES = {
    "factur-x.xml",
    "zugferd-invoice.xml",
    "xrechnung.xml",
}

# Regex patterns for the plain-text fallback. Grouping captures the value we want.
# These are heuristics, not a spec — they only match common English/German labels
# and a couple of date/number formats. Real-world PDFs will often need tuning.
_PATTERNS = {
    "invoice_number": re.compile(r"(?:Invoice\s*(?:No\.?|Number)|Rechnungsnummer)\s*[:#]?\s*(\S+)", re.IGNORECASE),
    "issue_date": re.compile(
        r"(?:Invoice\s*Date|Issue\s*Date|Rechnungsdatum)\s*[:#]?\s*(\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})",
        re.IGNORECASE,
    ),
    "issuer_name": re.compile(r"(?:Issuer|From|Verkäufer)\s*[:#]?\s*(.+)", re.IGNORECASE),
    "net_amount": re.compile(r"(?:Net\s*Amount|Subtotal|Nettobetrag)\s*[:#]?\s*€?\s*([\d.,]+)", re.IGNORECASE),
    "tax_amount": re.compile(r"(?:Tax|VAT|Steuer|MwSt)\s*(?:Amount)?\s*[:#]?\s*€?\s*([\d.,]+)", re.IGNORECASE),
    "total_amount": re.compile(r"(?:Total\s*Amount|Total|Gesamtbetrag)\s*[:#]?\s*€?\s*([\d.,]+)", re.IGNORECASE),
}

# Currency detection: try an explicit ISO 4217 code first, then fall back to a symbol.
_CURRENCY_CODE_PATTERN = re.compile(r"\b(EUR|USD|GBP|CHF|JPY|AUD|CAD)\b", re.IGNORECASE)
_CURRENCY_SYMBOL_PATTERN = re.compile(r"[€$£¥]")
_CURRENCY_SYMBOL_MAP = {"€": "EUR", "$": "USD", "£": "GBP", "¥": "JPY"}
_DEFAULT_CURRENCY = "EUR"


def _detect_currency(text: str) -> str:
    """Looks for an explicit ISO 4217 currency code, then a currency symbol, in the
    extracted text. Falls back to _DEFAULT_CURRENCY if neither is found, since a plain
    invoice may genuinely omit currency info when it's implied by context."""
    code_match = _CURRENCY_CODE_PATTERN.search(text)
    if code_match:
        return code_match.group(1).upper()

    symbol_match = _CURRENCY_SYMBOL_PATTERN.search(text)
    if symbol_match:
        return _CURRENCY_SYMBOL_MAP.get(symbol_match.group(0), _DEFAULT_CURRENCY)

    return _DEFAULT_CURRENCY


def _parse_amount(raw: str) -> Decimal:
    """Converts a matched amount string to Decimal, handling both '1,234.56' (US) and
    '1.234,56' (European) thousands/decimal separator conventions."""
    raw = raw.strip()
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            # comma is the decimal separator, dot(s) are thousands separators: "1.234,56"
            normalized = raw.replace(".", "").replace(",", ".")
        else:
            # dot is the decimal separator, comma(s) are thousands separators: "1,234.56"
            normalized = raw.replace(",", "")
    elif "," in raw:
        # only a comma present: treat as a decimal separator (European style): "38,00"
        normalized = raw.replace(",", ".")
    else:
        normalized = raw
    return Decimal(normalized)


def _parse_flexible_date(raw: str):
    """Parses either YYYY-MM-DD or DD.MM.YYYY / DD/MM/YYYY into a date object."""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {raw!r}")


class PDFParser(BaseParser):
    """Parses PDF invoices: ZUGFeRD (embedded XML) or plain/unstructured text."""

    def parse(self, file_path: str | Path) -> Invoice:
        path = Path(file_path)
        if not path.is_file():
            raise ParsingError(f"File not found: {path}")

        embedded_xml = self._extract_embedded_xml(path)
        if embedded_xml is not None:
            return self._parse_zugferd(embedded_xml, path)
        return self._parse_plain_text(path)

    def _extract_embedded_xml(self, path: Path) -> bytes | None:
        """Looks for a ZUGFeRD-style embedded XML attachment inside the PDF.
        Returns its raw bytes, or None if no matching attachment is found."""
        try:
            reader = PdfReader(str(path))
        except Exception as e:
            raise ParsingError(f"Could not open {path} as a PDF: {e}") from e

        attachments = getattr(reader, "attachments", {}) or {}
        for filename, contents in attachments.items():
            if filename.lower() in ZUGFERD_ATTACHMENT_NAMES:
                # pypdf may return a list of byte-strings per filename (multiple versions);
                # take the first one.
                return contents[0] if isinstance(contents, list) else contents
        return None

    def _parse_zugferd(self, xml_bytes: bytes, path: Path) -> Invoice:
        try:
            root = etree.fromstring(xml_bytes)
            return parse_cii_root(root, source_file=str(path.name), source_format=SourceFormat.PDF_ZUGFERD)
        except ParsingError:
            raise
        except etree.XMLSyntaxError as e:
            raise ParsingError(f"Embedded ZUGFeRD XML in {path} is not well-formed: {e}") from e
        except (ValueError, InvalidOperation) as e:
            raise ParsingError(f"Failed to parse embedded ZUGFeRD XML in {path}: {e}") from e
        except ValidationError as e:
            raise ParsingError(f"Embedded ZUGFeRD XML in {path} produced an invalid invoice: {e}") from e

    def _parse_plain_text(self, path: Path) -> Invoice:
        """Fallback for PDFs with no embedded structured data. Extracts text and applies
        regex heuristics. Line items are NOT extracted in this path — table layouts in
        plain PDFs vary too much for reliable generic extraction, so `lines` is left empty."""
        try:
            with pdfplumber.open(str(path)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:
            raise ParsingError(f"Could not read text from PDF {path}: {e}") from e

        try:
            matches = {
                key: (pattern.search(text).group(1).strip() if pattern.search(text) else None)
                for key, pattern in _PATTERNS.items()
            }

            missing = [key for key in ("invoice_number", "issue_date", "issuer_name", "total_amount") if not matches[key]]
            if missing:
                raise ParsingError(
                    f"Could not find required field(s) {missing} in the plain-text PDF at {path}. "
                    "This PDF's layout may not match the expected label patterns."
                )

            net_amount = _parse_amount(matches["net_amount"]) if matches["net_amount"] else None
            tax_amount = _parse_amount(matches["tax_amount"]) if matches["tax_amount"] else None
            total_amount = _parse_amount(matches["total_amount"])

            # If net/tax are missing but total isn't, we can't safely infer them — required
            # by the model, so this is a hard failure rather than a silent guess.
            if net_amount is None or tax_amount is None:
                raise ParsingError(
                    f"Could not find net amount and/or tax amount in the plain-text PDF at {path}."
                )

            return Invoice(
                invoice_number=matches["invoice_number"],
                issue_date=_parse_flexible_date(matches["issue_date"]),
                currency=_detect_currency(text),
                issuer=Party(name=matches["issuer_name"]),
                recipient=None,
                net_amount=net_amount,
                tax_amount=tax_amount,
                total_amount=total_amount,
                lines=[],
                source_format=SourceFormat.PDF_UNSTRUCTURED,
                source_file=str(path.name),
            )

        except ParsingError:
            raise
        except (ValueError, InvalidOperation) as e:
            raise ParsingError(f"Failed to parse extracted text from PDF {path}: {e}") from e
        except ValidationError as e:
            raise ParsingError(f"Extracted data from PDF {path} produced an invalid invoice: {e}") from e