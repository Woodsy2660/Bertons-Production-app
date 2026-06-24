from typing import Protocol
from dataclasses import dataclass
from datetime import date


@dataclass
class ResolvedBatchHeader:
    """Header data that could be auto-filled from EzyWine."""
    product: str | None = None
    stock_item: str | None = None
    tank: str | None = None
    run_date: date | None = None
    packing_unit: str | None = None
    packaging_line: str | None = None
    run_quantity: int | None = None


class RunDataProvider(Protocol):
    """
    Interface for run data resolution.

    In the prototype, this is stubbed to return None (manual entry).
    In later iterations, this will integrate with EzyWine to:
    - Auto-fill batch header data from the run number
    - Resolve scanned barcodes/QR codes to run numbers
    """

    def resolve_run_header(self, run_number: str) -> ResolvedBatchHeader | None:
        """
        Attempt to resolve header data for a run number.

        Args:
            run_number: The bottling run number (e.g., "15646")

        Returns:
            ResolvedBatchHeader if found, None if not found or manual entry required
        """
        ...

    def resolve_barcode(self, scanned_code: str) -> str | None:
        """
        Resolve a scanned barcode/QR code to a run number.

        Args:
            scanned_code: The scanned barcode or QR code value

        Returns:
            Run number if found, None if not recognized
        """
        ...


class ManualRunDataProvider:
    """
    Stub implementation - always returns None (manual entry required).

    This is the prototype implementation. The interface is preserved so
    later iterations can swap in a real EzyWine integration without
    changing the rest of the application.
    """

    def resolve_run_header(self, run_number: str) -> None:
        """
        Stub: Always returns None, requiring manual header entry.

        Future implementation would query EzyWine for:
        - Product name
        - Stock item code
        - Tank number
        - Run date
        - Packing unit
        - Packaging line
        - Run quantity
        """
        return None

    def resolve_barcode(self, scanned_code: str) -> None:
        """
        Stub: Always returns None (scanner disabled in prototype).

        Future implementation would:
        - Parse the barcode format
        - Query EzyWine for the associated run number
        - Return the run number for batch lookup/creation
        """
        return None


# Default provider for dependency injection
def get_run_data_provider() -> RunDataProvider:
    """
    Get the run data provider instance.

    In the prototype, returns the manual stub.
    Can be swapped for a real implementation via config.
    """
    return ManualRunDataProvider()
