import pytest
from datetime import date

from app.models import Batch, BatchStatus
from app.services.batch_lifecycle import (
    can_compile,
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


def test_manager_can_compile_partial_run():
    batch = Batch(run_number="103", created_by="Manager", status=BatchStatus.IN_PROGRESS)
    assert can_compile(batch, "manager")
    assert not can_compile(batch, "operator")


def test_complete_run_cannot_compile():
    batch = Batch(run_number="104", created_by="Manager", status=BatchStatus.COMPLETE)
    assert not can_compile(batch, "manager")


def test_operator_visibility_filter_builds():
    settings = Settings()
    clause = operator_visibility_filter(settings, today=date(2026, 6, 25))
    assert clause is not None


def test_operator_visibility_includes_all_active_runs():
    """Operators must see every non-complete run, not only today's run_date."""
    from sqlalchemy.dialects import postgresql

    settings = Settings()
    clause = operator_visibility_filter(settings, today=date(2026, 7, 2))
    sql = str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "status" in sql
    assert "complete" in sql
    assert "run_date = " not in sql