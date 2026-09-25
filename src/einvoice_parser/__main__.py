"""Command-line entry point.

Usage:
    python -m einvoice_parser <file_or_directory>
    python -m einvoice_parser <file_or_directory> --json
"""
import argparse
import json
import sys
from pathlib import Path

from einvoice_parser.models import Invoice
from einvoice_parser.parsers.base import ParsingError
from einvoice_parser.pipeline import BatchResult, InvoicePipeline


def _format_invoice_summary(invoice: Invoice) -> str:
    """Human-readable summary of a single parsed invoice."""
    issuer_line = invoice.issuer.name
    if invoice.issuer.tax_id:
        issuer_line += f" ({invoice.issuer.tax_id})"

    lines = [
        f"Invoice: {invoice.invoice_number}",
        f"Issuer: {issuer_line}",
        f"Net: {invoice.net_amount} {invoice.currency} | "
        f"Tax: {invoice.tax_amount} {invoice.currency} | "
        f"Total: {invoice.total_amount} {invoice.currency}",
        f"Format: {invoice.source_format.value}",
        f"Lines: {len(invoice.lines)}",
    ]
    return "\n".join(lines)


def _print_batch_result(result: BatchResult) -> None:
    """Human-readable summary of a batch (directory) run."""
    name_width = max(
        (len(path.name) for path, _ in result.failures),
        default=0,
    )
    name_width = max(
        name_width,
        max((len(inv.source_file or "") for inv in result.successes), default=0),
    )

    for invoice in result.successes:
        filename = (invoice.source_file or "").ljust(name_width)
        print(f"\u2713 {filename}  {invoice.invoice_number}  ({invoice.source_format.value})")

    for path, message in result.failures:
        filename = path.name.ljust(name_width)
        print(f"\u2717 {filename}  {message}")

    print()
    print(f"{len(result.successes)} succeeded, {len(result.failures)} failed")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="einvoice-parser",
        description="Parse and validate an invoice file, or a directory of mixed-format invoices.",
    )
    parser.add_argument(
        "path",
        help="Path to an invoice file (.csv, .xml, .pdf) or a directory containing invoice files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the full parsed invoice as JSON instead of a human-readable summary "
        "(single-file mode only).",
    )
    args = parser.parse_args()

    target = Path(args.path)
    pipeline = InvoicePipeline()

    if target.is_dir():
        print(f"Processing directory: {target}\n")
        result = pipeline.process_directory(target)
        _print_batch_result(result)
        return 1 if result.failures else 0

    try:
        invoice = pipeline.process_file(target)
    except ParsingError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(invoice.model_dump_json(indent=2))
    else:
        print(_format_invoice_summary(invoice))
    return 0


if __name__ == "__main__":
    sys.exit(main())