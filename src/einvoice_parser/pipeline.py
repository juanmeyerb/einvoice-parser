"""Pipeline orchestrator: routes invoice files to the correct parser by extension.

For .pdf files, PDFParser itself handles the ZUGFeRD-vs-plain-text distinction
internally (see pdf_parser.py), so the pipeline only needs to route by extension.
"""
from dataclasses import dataclass, field
from pathlib import Path

from einvoice_parser.models import Invoice
from einvoice_parser.parsers.base import BaseParser, ParsingError
from einvoice_parser.parsers.csv_parser import CSVParser
from einvoice_parser.parsers.pdf_parser import PDFParser
from einvoice_parser.parsers.xrechnung_parser import XRechnungParser

# Maps file extensions to the parser class responsible for them.
EXTENSION_TO_PARSER: dict[str, type[BaseParser]] = {
    ".csv": CSVParser,
    ".xml": XRechnungParser,
    ".pdf": PDFParser,
}


class UnsupportedFormatError(ParsingError):
    """Raised when a file's extension doesn't match any known parser."""
    pass


@dataclass
class BatchResult:
    """Outcome of processing a directory of invoice files."""
    successes: list[Invoice] = field(default_factory=list)
    failures: list[tuple[Path, str]] = field(default_factory=list)  # (file_path, error_message)

    @property
    def total(self) -> int:
        return len(self.successes) + len(self.failures)


class InvoicePipeline:
    """Routes invoice files to the correct parser based on file extension."""

    def __init__(self) -> None:
        # Each parser is stateless, so we instantiate one of each and reuse them.
        self._parsers: dict[str, BaseParser] = {
            ext: parser_cls() for ext, parser_cls in EXTENSION_TO_PARSER.items()
        }

    def process_file(self, file_path: str | Path) -> Invoice:
        """Parses a single invoice file, routing to the correct parser by extension.
        Raises UnsupportedFormatError if the extension isn't recognized, or ParsingError
        (propagated from the underlying parser) if the file itself is invalid."""
        path = Path(file_path)
        extension = path.suffix.lower()
        parser = self._parsers.get(extension)
        if parser is None:
            raise UnsupportedFormatError(
                f"No parser available for extension '{extension}' (file: {path}). "
                f"Supported extensions: {sorted(self._parsers.keys())}"
            )
        return parser.parse(path)

    def process_directory(self, directory: str | Path) -> BatchResult:
        """Processes every recognized invoice file directly inside a directory
        (non-recursive). Files with an unrecognized extension are silently skipped
        (e.g. a README or .gitkeep sitting alongside invoices). Every recognized
        file that fails to parse is recorded in failures rather than raising,
        so one bad file doesn't stop the rest of the batch."""
        directory = Path(directory)
        result = BatchResult()

        for file_path in sorted(directory.iterdir()):
            if file_path.is_dir():
                continue
            if file_path.suffix.lower() not in self._parsers:
                continue
            try:
                result.successes.append(self.process_file(file_path))
            except ParsingError as e:
                result.failures.append((file_path, str(e)))

        return result