"""Tests for XRechnungParser."""
from decimal import Decimal
from pathlib import Path

import pytest

from einvoice_parser.parsers.base import ParsingError
from einvoice_parser.parsers.xrechnung_parser import XRechnungParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# A minimal valid CII envelope we reuse as a base and deliberately break in each test.
VALID_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">

    <rsm:ExchangedDocument>
        <ram:ID>INV-TEST-001</ram:ID>
        <ram:IssueDateTime>
            <udt:DateTimeString format="102">20260901</udt:DateTimeString>
        </ram:IssueDateTime>
    </rsm:ExchangedDocument>

    <rsm:SupplyChainTradeTransaction>
        <ram:IncludedSupplyChainTradeLineItem>
            <ram:SpecifiedTradeProduct>
                <ram:Name>Widget</ram:Name>
            </ram:SpecifiedTradeProduct>
            <ram:SpecifiedLineTradeAgreement>
                <ram:NetPriceProductTradePrice>
                    <ram:ChargeAmount>10.00</ram:ChargeAmount>
                </ram:NetPriceProductTradePrice>
            </ram:SpecifiedLineTradeAgreement>
            <ram:SpecifiedLineTradeDelivery>
                <ram:BilledQuantity>1</ram:BilledQuantity>
            </ram:SpecifiedLineTradeDelivery>
            <ram:SpecifiedLineTradeSettlement>
                <ram:SpecifiedTradeSettlementLineMonetarySummation>
                    <ram:LineTotalAmount>10.00</ram:LineTotalAmount>
                </ram:SpecifiedTradeSettlementLineMonetarySummation>
            </ram:SpecifiedLineTradeSettlement>
        </ram:IncludedSupplyChainTradeLineItem>

        <ram:ApplicableHeaderTradeAgreement>
            <ram:SellerTradeParty>
                <ram:Name>Test Seller</ram:Name>
            </ram:SellerTradeParty>
        </ram:ApplicableHeaderTradeAgreement>

        <ram:ApplicableHeaderTradeSettlement>
            <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
            <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
                <ram:TaxBasisTotalAmount>{net}</ram:TaxBasisTotalAmount>
                <ram:TaxTotalAmount>{tax}</ram:TaxTotalAmount>
                <ram:GrandTotalAmount>{total}</ram:GrandTotalAmount>
            </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        </ram:ApplicableHeaderTradeSettlement>
    </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""


def test_parse_valid_xrechnung_returns_invoice():
    """The known-good fixture should parse into a valid, correctly-populated Invoice."""
    parser = XRechnungParser()
    invoice = parser.parse(FIXTURES_DIR / "sample_xrechnung.xml")

    assert invoice.invoice_number == "INV-2026-XR-001"
    assert invoice.issuer.name == "ACME GmbH"
    assert invoice.issuer.tax_id == "DE123456789"
    assert invoice.issuer.country_code == "DE"
    assert invoice.recipient.name == "Beta Corp"
    assert invoice.net_amount == Decimal("100.00")
    assert invoice.tax_amount == Decimal("19.00")
    assert invoice.total_amount == Decimal("119.00")
    assert len(invoice.lines) == 1
    assert invoice.lines[0].description == "Consulting hours"
    assert invoice.source_format.value == "xml_xrechnung"


def test_parse_missing_file_raises_parsing_error():
    """Parsing a nonexistent path should raise ParsingError."""
    parser = XRechnungParser()
    with pytest.raises(ParsingError):
        parser.parse(FIXTURES_DIR / "does_not_exist.xml")


def test_parse_malformed_xml_raises_parsing_error(tmp_path):
    """A file that isn't well-formed XML (e.g. an unclosed tag) should raise ParsingError,
    not an unhandled lxml.etree.XMLSyntaxError."""
    broken_xml = tmp_path / "broken.xml"
    broken_xml.write_text("<rsm:CrossIndustryInvoice><rsm:ExchangedDocument>")  # unclosed tags

    parser = XRechnungParser()
    with pytest.raises(ParsingError):
        parser.parse(broken_xml)


def test_parse_missing_seller_raises_parsing_error(tmp_path):
    """An invoice with no SellerTradeParty should be rejected, since issuer is required."""
    xml_without_seller = VALID_XML_TEMPLATE.replace(
        """<ram:ApplicableHeaderTradeAgreement>
            <ram:SellerTradeParty>
                <ram:Name>Test Seller</ram:Name>
            </ram:SellerTradeParty>
        </ram:ApplicableHeaderTradeAgreement>""",
        """<ram:ApplicableHeaderTradeAgreement>
        </ram:ApplicableHeaderTradeAgreement>""",
    ).format(net="10.00", tax="1.00", total="11.00")

    path = tmp_path / "no_seller.xml"
    path.write_text(xml_without_seller)

    parser = XRechnungParser()
    with pytest.raises(ParsingError):
        parser.parse(path)


def test_parse_inconsistent_totals_raises_parsing_error(tmp_path):
    """An invoice where total_amount doesn't match net_amount + tax_amount should be rejected."""
    xml_with_bad_totals = VALID_XML_TEMPLATE.format(net="10.00", tax="1.00", total="999.00")

    path = tmp_path / "bad_totals.xml"
    path.write_text(xml_with_bad_totals)

    parser = XRechnungParser()
    with pytest.raises(ParsingError):
        parser.parse(path)