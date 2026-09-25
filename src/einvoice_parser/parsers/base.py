"""Base interface for all invoice parsers."""
from abc import ABC, abstractmethod
from pathlib import Path

from einvoice_parser.models import Invoice


class ParsingError(Exception):
    """Raised when a parser cannot extract a valid Invoice from a file."""
    pass


class BaseParser(ABC):
    """Abstract base class that all specific format parsers must inherit from."""

    @abstractmethod
    def parse(self, file_path: str | Path) -> Invoice:
        """
        Parses an invoice file and returns a validated Invoice instance.

        Raises:
            ParsingError: if the file cannot be read or its content
                does not map to a valid Invoice.
        """
        pass