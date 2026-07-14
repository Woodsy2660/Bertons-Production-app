"""Pluggable pallet tag print dispatch (spec 11 §6)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PrintResult:
    success: bool
    dispatch_method: str
    message: str
    pdf_url: str | None = None


class TagPrinter:
    def print_pdf(self, pdf_bytes: bytes, copies: int) -> PrintResult:
        raise NotImplementedError


class BrowserTagPrinter(TagPrinter):
    """Serve PDF for OS print dialog — working path."""

    def __init__(self, pdf_url: str):
        self.pdf_url = pdf_url

    def print_pdf(self, pdf_bytes: bytes, copies: int) -> PrintResult:
        return PrintResult(
            success=True,
            dispatch_method="browser",
            message="Open the tag PDF and print from your browser.",
            pdf_url=self.pdf_url,
        )


class NetworkTagPrinter(TagPrinter):
    """TODO: wire once printer IP / port 9100 or IPP is confirmed (spec 11 §6)."""

    def print_pdf(self, pdf_bytes: bytes, copies: int) -> PrintResult:
        return PrintResult(
            success=False,
            dispatch_method="network",
            message="Network printer dispatch is not configured yet.",
        )