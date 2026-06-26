import pytest
from datetime import date

from app.models import Batch, BatchStatus
from app.services.batch_lifecycle import (
    can_write_forms,
    is_complete,
    is_greyed_out,
    operator_may_edit,
    operator_visibility_filter,
)
from app.config import Settings


def test_complete_run_is_greyed_and_locked():
    batch = Batch(run_number="100", created_by="Manager", status=BatchStatus.COMPLETE)
    assert is_complete(batch)
    assert is_greyed_out(batch)
    assert not can_write_forms(batch, "operator")
    assert not can_write_forms(batch, "manager")
    assert not operator_may_edit(batch)


def test_reopened_run_manager_only():
    batch = Batch(run_number="101", created_by="Manager", status=BatchStatus.REOPENED)
    assert can_write_forms(batch, "manager")
    assert not can_write_forms(batch, "operator")
    assert not operator_may_edit(batch)


def test_in_progress_editable_by_both_roles():
    batch = Batch(run_number="102", created_by="Manager", status=BatchStatus.IN_PROGRESS)
    assert can_write_forms(batch, "operator")
    assert can_write_forms(batch, "manager")
    assert operator_may_edit(batch)


def test_operator_visibility_filter_builds():
    settings = Settings()
    clause = operator_visibility_filter(settings, today=date(2026, 6, 25))
    assert clause is not None