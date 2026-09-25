"""CSV invoice parser implementation."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from einvoice_parser.models import Invoice, InvoiceLine, Party, SourceFormat
from einvoice_parser.parsers.base import BaseParser, ParsingError


class CSVParser(BaseParser):
    """Parses tabular invoice data exported as CSV.

    Expected layout: one row per line item, with invoice-level fields
    (invoice_number, issue_date, issuer_name, totals, etc.) repeated
    identically on every row. Only the first row's invoice-level fields
    are used to build the Invoice header.
    """

    def parse(self, file_path: str | Path) -> Invoice:
        path = Path(file_path)
        if not path.is_file():
            raise ParsingError(f"File not found: {path}")

        try:
            lines: list[InvoiceLine] = []
            header_data: dict | None = None

            with open(path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Capture common header metadata from the first row encountered
                    if header_data is None:
                        header_data = row

                    # Parse the item line
                    line = InvoiceLine(
                        description=row["line_description"],
                        quantity=Decimal(row["line_quantity"]),
                        unit_price=Decimal(row["line_unit_price"]),
                        line_amount=Decimal(row["line_amount"]),
                        tax_rate=Decimal(row["line_tax_rate"]) if row.get("line_tax_rate") else None,
                    )
                    lines.append(line)

            if header_data is None:
                raise ParsingError(f"The CSV file at {path} is empty or missing headers.")

            # Construct Party objects
            issuer = Party(
                name=header_data["issuer_name"],
                tax_id=header_data.get("issuer_tax_id"),
                country_code=header_data.get("issuer_country"),
            )

            recipient = None
            if header_data.get("recipient_name"):
                recipient = Party(
                    name=header_data["recipient_name"],
                    tax_id=header_data.get("recipient_tax_id"),
                )

            # Assemble and validate the complete Invoice
            return Invoice(
                invoice_number=header_data["invoice_number"],
                issue_date=datetime.strptime(header_data["issue_date"], "%Y-%m-%d").date(),
                due_date=(
                    datetime.strptime(header_data["due_date"], "%Y-%m-%d").date()
                    if header_data.get("due_date")
                    else None
                ),
                currency=header_data.get("currency", "EUR"),
                issuer=issuer,
                recipient=recipient,
                net_amount=Decimal(header_data["net_amount"]),
                tax_amount=Decimal(header_data["tax_amount"]),
                total_amount=Decimal(header_data["total_amount"]),
                lines=lines,
                source_format=SourceFormat.CSV,
                source_file=str(path.name),
            )

        except ParsingError:
            raise
        except (KeyError, ValueError, InvalidOperation) as e:
            # KeyError: a required column is missing from the CSV
            # ValueError / InvalidOperation: a value couldn't be parsed as expected
            #   (bad date format, non-numeric amount, etc.)
            raise ParsingError(f"Failed to parse CSV at {path}: {e}") from e
        except ValidationError as e:
            # The row data was readable but doesn't form a valid Invoice
            # (e.g. total_amount doesn't match net_amount + tax_amount)
            raise ParsingError(f"CSV at {path} produced an invalid invoice: {e}") from e