import pytest

from app.models import Batch, BatchStatus
from app.services.batch_lifecycle import can_upload_documents
from app.services.document_management import validate_pdf_upload


def test_validate_pdf_upload_rejects_non_pdf():
    class FakeUpload:
        filename = "notes.txt"

    with pytest.raises(ValueError, match="PDF"):
        validate_pdf_upload(FakeUpload())


def test_validate_pdf_upload_accepts_pdf():
    class FakeUpload:
        filename = "work-order.pdf"

    validate_pdf_upload(FakeUpload())


def test_manager_can_manage_documents_before_complete():
    batch = Batch(run_number="100", created_by="Manager", status=BatchStatus.IN_PROGRESS)
    assert can_upload_documents(batch, "manager")
    assert not can_upload_documents(batch, "operator")

    complete = Batch(run_number="101", created_by="Manager", status=BatchStatus.COMPLETE)
    assert not can_upload_documents(complete, "manager")


def test_reopened_run_allows_document_management():
    batch = Batch(run_number="102", created_by="Manager", status=BatchStatus.REOPENED)
    assert can_upload_documents(batch, "manager")