"""XRechnung (CII / EN16931) XML invoice parser.

The core CII-parsing logic (`parse_cii_root`) is factored out so it can be
reused by PDFParser when extracting ZUGFeRD's embedded XML, since ZUGFeRD
uses the same CII syntax under the hood.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree
from pydantic import ValidationError

from einvoice_parser.models import Invoice, InvoiceLine, Party, SourceFormat
from einvoice_parser.parsers.base import BaseParser, ParsingError

# CII namespaces used by XRechnung (and, underneath, by ZUGFeRD's embedded XML)
NSMAP = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}


def _find_text(node: etree._Element, xpath: str) -> str | None:
    """Returns the text content of the first match for xpath, or None if not found."""
    result = node.find(xpath, namespaces=NSMAP)
    return result.text if result is not None else None


def _parse_cii_date(date_str: str | None) -> date | None:
    """Parses a CII-format date string (format 102 = YYYYMMDD) into a date object."""
    if date_str is None:
        return None
    return datetime.strptime(date_str, "%Y%m%d").date()


def _parse_party(node: etree._Element | None) -> Party | None:
    """Builds a Party from a SellerTradeParty / BuyerTradeParty element."""
    if node is None:
        return None
    name = _find_text(node, "ram:Name")
    if name is None:
        return None
    return Party(
        name=name,
        tax_id=_find_text(node, "ram:SpecifiedTaxRegistration/ram:ID"),
        country_code=_find_text(node, "ram:PostalTradeAddress/ram:CountryID"),
    )


def _parse_line_item(node: etree._Element) -> InvoiceLine:
    """Builds an InvoiceLine from an IncludedSupplyChainTradeLineItem element."""
    description = _find_text(node, "ram:SpecifiedTradeProduct/ram:Name")
    quantity_str = _find_text(node, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")
    unit_price_str = _find_text(
        node, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"
    )
    line_amount_str = _find_text(
        node,
        "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
    )
    tax_rate_str = _find_text(
        node, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent"
    )

    if description is None or unit_price_str is None or line_amount_str is None:
        raise ParsingError("A line item is missing a required field (description, unit price, or line amount).")

    return InvoiceLine(
        description=description,
        quantity=Decimal(quantity_str) if quantity_str else Decimal("1"),
        unit_price=Decimal(unit_price_str),
        line_amount=Decimal(line_amount_str),
        tax_rate=Decimal(tax_rate_str) if tax_rate_str else None,
    )


def parse_cii_root(
    root: etree._Element,
    source_file: str,
    source_format: SourceFormat,
) -> Invoice:
    """
    Builds an Invoice from an already-parsed CII XML root element.

    Shared by XRechnungParser (root comes from a standalone .xml file) and
    PDFParser (root comes from XML bytes embedded inside a ZUGFeRD PDF).
    Raises ParsingError on any structural or validation problem.
    """
    invoice_number = _find_text(root, "rsm:ExchangedDocument/ram:ID")
    issue_date_str = _find_text(root, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
    if invoice_number is None or issue_date_str is None:
        raise ParsingError("Missing invoice number or issue date in ExchangedDocument.")
    issue_date = _parse_cii_date(issue_date_str)

    transaction = root.find("rsm:SupplyChainTradeTransaction", namespaces=NSMAP)
    if transaction is None:
        raise ParsingError("Missing SupplyChainTradeTransaction element.")

    agreement = transaction.find("ram:ApplicableHeaderTradeAgreement", namespaces=NSMAP)
    issuer = _parse_party(
        agreement.find("ram:SellerTradeParty", namespaces=NSMAP) if agreement is not None else None
    )
    recipient = _parse_party(
        agreement.find("ram:BuyerTradeParty", namespaces=NSMAP) if agreement is not None else None
    )
    if issuer is None:
        raise ParsingError("Missing SellerTradeParty (issuer) information.")

    settlement = transaction.find("ram:ApplicableHeaderTradeSettlement", namespaces=NSMAP)
    if settlement is None:
        raise ParsingError("Missing ApplicableHeaderTradeSettlement element.")

    currency = _find_text(settlement, "ram:InvoiceCurrencyCode") or "EUR"
    due_date = _parse_cii_date(
        _find_text(settlement, "ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString")
    )

    summation = settlement.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", namespaces=NSMAP)
    if summation is None:
        raise ParsingError("Missing SpecifiedTradeSettlementHeaderMonetarySummation element.")

    net_amount_str = _find_text(summation, "ram:TaxBasisTotalAmount")
    tax_amount_str = _find_text(summation, "ram:TaxTotalAmount")
    total_amount_str = _find_text(summation, "ram:GrandTotalAmount")
    if net_amount_str is None or tax_amount_str is None or total_amount_str is None:
        raise ParsingError("Missing one of TaxBasisTotalAmount / TaxTotalAmount / GrandTotalAmount.")

    line_items = transaction.findall("ram:IncludedSupplyChainTradeLineItem", namespaces=NSMAP)
    lines = [_parse_line_item(item) for item in line_items]

    return Invoice(
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        currency=currency,
        issuer=issuer,
        recipient=recipient,
        net_amount=Decimal(net_amount_str),
        tax_amount=Decimal(tax_amount_str),
        total_amount=Decimal(total_amount_str),
        lines=lines,
        source_format=source_format,
        source_file=source_file,
    )


class XRechnungParser(BaseParser):
    """Parses standalone XRechnung XML files (CII syntax)."""

    def parse(self, file_path: str | Path) -> Invoice:
        path = Path(file_path)
        if not path.is_file():
            raise ParsingError(f"File not found: {path}")

        try:
            tree = etree.parse(str(path))
            root = tree.getroot()
            return parse_cii_root(root, source_file=str(path.name), source_format=SourceFormat.XML_XRECHNUNG)

        except ParsingError:
            raise
        except etree.XMLSyntaxError as e:
            raise ParsingError(f"File at {path} is not well-formed XML: {e}") from e
        except (ValueError, InvalidOperation) as e:
            # bad date format, non-numeric amount, etc.
            raise ParsingError(f"Failed to parse XRechnung XML at {path}: {e}") from e
        except ValidationError as e:
            raise ParsingError(f"XML at {path} produced an invalid invoice: {e}") from e