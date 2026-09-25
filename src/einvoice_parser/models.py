"""
Common data model that all invoices converge to,
regardless of the source format (PDF, XML/ZUGFeRD-XRechnung, CSV).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SourceFormat(str, Enum):
    """Which format the document originally came from."""
    PDF_UNSTRUCTURED = "pdf_unstructured"   # plain/scanned PDF, text-extraction only
    PDF_ZUGFERD = "pdf_zugferd"             # PDF with embedded XML (ZUGFeRD/Factur-X)
    XML_XRECHNUNG = "xml_xrechnung"
    CSV = "csv"


class Party(BaseModel):
    """Issuer or recipient of the invoice."""
    name: str
    tax_id: str | None = None          # VAT ID / NIF / USt-IdNr, etc.
    address: str | None = None
    country_code: str | None = None    # ISO 3166-1 alpha-2, e.g. "DE", "ES"


class InvoiceLine(BaseModel):
    """A single line item on the invoice."""
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    line_amount: Decimal               # quantity * unit_price (before tax)
    tax_rate: Decimal | None = None    # e.g. Decimal("19.00") for 19%
    tax_amount: Decimal | None = None

    @field_validator("quantity", "unit_price", "line_amount", "tax_rate", "tax_amount", mode="before")
    @classmethod
    def _coerce_decimal(cls, v):
        """Allows passing strings or floats and safely converts them to Decimal."""
        if v is None:
            return v
        return Decimal(str(v))


class Invoice(BaseModel):
    """Normalized invoice: the pipeline's common output schema."""
    invoice_number: str
    issue_date: date
    due_date: date | None = None
    currency: str = "EUR"              # ISO 4217

    issuer: Party
    recipient: Party | None = None

    net_amount: Decimal                # subtotal before tax
    tax_amount: Decimal                # total tax amount
    total_amount: Decimal              # net_amount + tax_amount

    lines: list[InvoiceLine] = Field(default_factory=list)

    source_format: SourceFormat
    source_file: str | None = None     # path or name of the original file

    @field_validator("net_amount", "tax_amount", "total_amount", mode="before")
    @classmethod
    def _coerce_decimal(cls, v):
        if v is None:
            return v
        return Decimal(str(v))

    @field_validator("total_amount")
    @classmethod
    def _check_total_consistency(cls, v: Decimal, info) -> Decimal:
        """Validates that total = net + tax, with a 0.01 rounding tolerance."""
        net = info.data.get("net_amount")
        tax = info.data.get("tax_amount")
        if net is not None and tax is not None:
            expected = net + tax
            if abs(expected - v) > Decimal("0.01"):
                raise ValueError(
                    f"total_amount ({v}) does not match net_amount + tax_amount "
                    f"({expected}). Difference: {abs(expected - v)}"
                )
        return v