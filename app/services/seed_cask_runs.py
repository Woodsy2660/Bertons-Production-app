"""
Seed four cask-line runs with randomised partial form data for PDF/UI testing.

Run numbers: CASK-SEED-01 … CASK-SEED-04
Does not delete bottling dashboard seeds. Replaces existing CASK-SEED-* runs only.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AccrualMode as ModelAccrualMode,
    Batch,
    BatchHeader,
    BatchStatus,
    DocumentSlot,
    FormInstance,
    FormStatus,
    FormType as ModelFormType,
    LineType,
    Reading,
    UploadedDocument,
)
from app.services.form_persistence import apply_cask_waste_totals

CASK_SEED_RUNS = [
    {
        "run_number": "CASK-SEED-01",
        "product": "Cask Red Blend 2025",
        "stock_item": "C25REDCASK1",
        "tank": "C101",
        "run_quantity": 4800,
        "run_date_offset": -3,
        "status": BatchStatus.IN_PROGRESS,
        "profile": "almost_full",  # all forms filled; waste + dip complete
    },
    {
        "run_number": "CASK-SEED-02",
        "product": "Cask Sauv Blanc 2024",
        "stock_item": "C24SBBCASK1",
        "tank": "C204",
        "run_quantity": 3200,
        "run_date_offset": -1,
        "status": BatchStatus.IN_PROGRESS,
        "profile": "missing_dip",  # no tank dip; sparse line checks
    },
    {
        "run_number": "CASK-SEED-03",
        "product": "Cask Shiraz 2023",
        "stock_item": "C23SHZCASK6",
        "tank": "C088",
        "run_quantity": 2100,
        "run_date_offset": 0,
        "status": BatchStatus.IN_PROGRESS,
        "profile": "early_run",  # only partial pallets; others empty/not started
    },
    {
        "run_number": "CASK-SEED-04",
        "product": "Cask Moscato 2025",
        "stock_item": "C25MOSCASK1",
        "tank": "C033",
        "run_quantity": 5600,
        "run_date_offset": -5,
        "status": BatchStatus.AWAITING_REVIEW,
        "profile": "mixed_gaps",  # all forms present but random fields blank
    },
]


def _rt(run_date: date, hour: int, minute: int = 0) -> datetime:
    return datetime(run_date.year, run_date.month, run_date.day, hour, minute)


def _maybe(rng: random.Random, value, blank_chance: float = 0.35):
    if rng.random() < blank_chance:
        return None
    return value


def _yn(rng: random.Random, blank_chance: float = 0.2) -> str | None:
    if rng.random() < blank_chance:
        return None
    return rng.choice(["Y", "N"])


def _mock_pdf(dest: Path, title: str, run_number: str, product: str) -> None:
    try:
        from weasyprint import HTML

        html = f"""
        <!DOCTYPE html>
        <html><body style="font-family: Arial; margin: 2cm;">
            <h1>{title}</h1>
            <p><strong>Run:</strong> {run_number}</p>
            <p><strong>Product:</strong> {product}</p>
            <p>Cask seed document for PDF/template testing.</p>
        </body></html>
        """
        HTML(string=html).write_pdf(str(dest))
    except Exception:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with open(dest, "wb") as f:
            writer.write(f)


def _fi(
    batch_id,
    form_type: ModelFormType,
    mode: ModelAccrualMode,
    payload: dict | None,
    *,
    status: FormStatus,
    by: str = "JS",
) -> FormInstance:
    return FormInstance(
        batch_id=batch_id,
        form_type=form_type,
        accrual_mode=mode,
        status=status,
        header_payload=payload or {},
        submitted_by=by if status == FormStatus.SUBMITTED else None,
        submitted_at=datetime.utcnow() if status == FormStatus.SUBMITTED else None,
        last_edited_at=datetime.utcnow(),
        last_edited_by=by,
    )


async def _delete_existing(db: AsyncSession) -> None:
    nums = [c["run_number"] for c in CASK_SEED_RUNS]
    result = await db.execute(select(Batch).where(Batch.run_number.in_(nums)))
    for batch in result.scalars().all():
        await db.delete(batch)
    await db.commit()


def _waste_payload(rng: random.Random, product: str, run_no: str, run_date: date, *, sparse: bool) -> dict:
    blank = 0.55 if sparse else 0.25

    def n(lo=0, hi=8):
        return _maybe(rng, rng.randint(lo, hi), blank)

    payload = {
        "product": product,
        "run_number": run_no,
        "date": run_date.isoformat(),
        "casks_machine_jam": n(),
        "casks_printing": n(),
        "casks_other_count": n(0, 3),
        "casks_other_problem": _maybe(rng, rng.choice(["torn handle", "crush at filler", ""]), blank),
        "bladders_split": n(),
        "bladders_faulty_tap": n(),
        "bladders_other_count": n(0, 2),
        "bladders_other_problem": _maybe(rng, "pin hole", blank),
        "inners_machine_jam": n(),
        "inners_printing": n(),
        "inners_other_count": n(0, 2),
        "inners_other_problem": _maybe(rng, "glue smear", blank),
        "outers_machine_jam": n(),
        "outers_printing": n(),
        "outers_other_count": n(0, 2),
        "outers_other_problem": _maybe(rng, "", blank),
        "comments": _maybe(
            rng,
            rng.choice(
                [
                    "Normal run, minor waste only.",
                    "Machine jam mid-morning — cleared.",
                    None,
                ]
            ),
            blank,
        ),
        "initials": _maybe(rng, rng.choice(["JS", "JD", "MB"]), 0.1),
        "signature_date": run_date.isoformat(),
    }
    return apply_cask_waste_totals({k: v for k, v in payload.items() if v is not None})


def _line_check_header(product: str, run_no: str, tank: str, run_date: date, rng: random.Random) -> dict:
    return {
        "date": run_date.isoformat(),
        "tank": tank,
        "run_number": run_no,
        "wine": product,
        "wine_sg": _maybe(rng, f"0.{rng.randint(990, 999)}", 0.3),
        "empty_bladder_weight_g": _maybe(rng, rng.randint(48, 62), 0.25),
        "best_before_date": _maybe(
            rng, (run_date + timedelta(days=365 * 2)).isoformat(), 0.3
        ),
    }


def _line_check_reading(rng: random.Random, *, sparse: bool) -> dict:
    blank = 0.45 if sparse else 0.15
    return {
        k: v
        for k, v in {
            "bladder_match": _yn(rng, blank),
            "filler_vacuum": _maybe(rng, f"-0.{rng.randint(40, 48)}", blank),
            "full_bladder_weight": [
                _maybe(rng, str(rng.randint(3000, 3200)), blank) or "",
                _maybe(rng, str(rng.randint(3000, 3200)), blank) or "",
                _maybe(rng, str(rng.randint(3000, 3200)), blank) or "",
            ],
            "inner_match": _yn(rng, blank),
            "inner_inkjet_match": _yn(rng, blank),
            "glue_dripping": _yn(rng, blank),
            "inner_flaps_glued": _yn(rng, blank),
            "best_before_match": _yn(rng, blank),
            "outer_inkjet_match": _yn(rng, blank),
            "outer_flaps_glued": _yn(rng, blank),
            "stacking_match": _yn(rng, blank),
            "pallet_type_match": _yn(rng, blank),
            "slip_sheet": _yn(rng, blank),
            "checked_by": _maybe(rng, rng.choice(["JS", "JD", "MB"]), blank),
        }.items()
        if v is not None
    }


def _dip_payload(product: str, run_no: str, tank: str, run_date: date, rng: random.Random, *, sparse: bool) -> dict:
    blank = 0.5 if sparse else 0.15

    def multi(base: float):
        vals = []
        for i in range(4):
            vals.append(_maybe(rng, f"{base + i * 0.1:.1f}", blank))
        return [v if v is not None else "" for v in vals]

    return {
        k: v
        for k, v in {
            "product": product,
            "run_number": run_no,
            "date": run_date.isoformat(),
            "tank": tank,
            "volume_supplied": _maybe(rng, str(rng.randint(8000, 12000)), blank),
            "starting_dip_cm": multi(120.0),
            "starting_dip_l": multi(9000.0),
            "starting_initials": _maybe(rng, "JS", blank),
            "finishing_dip_cm": multi(18.0),
            "finishing_dip_l": multi(400.0),
            "finishing_initials": _maybe(rng, "MB", blank),
        }.items()
        if v is not None
    }


async def create_cask_seed_runs(
    db: AsyncSession,
    upload_dir: str,
    *,
    seed: int = 42,
) -> list[Batch]:
    rng = random.Random(seed)
    upload_path = Path(upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)

    await _delete_existing(db)
    created: list[Batch] = []

    for cfg in CASK_SEED_RUNS:
        run_date = date.today() + timedelta(days=cfg["run_date_offset"])
        profile = cfg["profile"]

        batch = Batch(
            run_number=cfg["run_number"],
            line_type=LineType.CASK,
            status=cfg["status"],
            created_by="Cask Seed",
            is_locked=False,
        )
        db.add(batch)
        await db.flush()

        db.add(
            BatchHeader(
                batch_id=batch.id,
                product=cfg["product"],
                stock_item=cfg["stock_item"],
                tank=cfg["tank"],
                run_date=run_date,
                run_quantity=cfg["run_quantity"],
                packing_unit="Cask / bag-in-box",
                packaging_line="Cask line",
            )
        )

        # Work order + listing mocks
        wo_path = upload_path / f"{batch.id}_work_order_0.pdf"
        _mock_pdf(wo_path, "Mock Cask Work Order", cfg["run_number"], cfg["product"])
        db.add(
            UploadedDocument(
                batch_id=batch.id,
                slot=DocumentSlot.WORK_ORDER,
                sequence=0,
                original_filename=f"MOCK_WO_{cfg['run_number']}.pdf",
                stored_path=str(wo_path),
                uploaded_by="Cask Seed",
            )
        )
        listing_path = upload_path / f"{batch.id}_ezywine_listing_0.pdf"
        _mock_pdf(listing_path, "Mock EzyWine Listing", cfg["run_number"], cfg["product"])
        db.add(
            UploadedDocument(
                batch_id=batch.id,
                slot=DocumentSlot.EZYWINE_LISTING,
                sequence=0,
                original_filename=f"MOCK_Listing_{cfg['run_number']}.pdf",
                stored_path=str(listing_path),
                uploaded_by="Cask Seed",
            )
        )

        # --- FOR CA 001 pallet log ---
        if profile == "early_run":
            pallet_status = FormStatus.IN_PROGRESS
            pallet_count = rng.randint(2, 4)
        elif profile == "almost_full":
            pallet_status = FormStatus.SUBMITTED
            pallet_count = rng.randint(12, 18)
        elif profile == "missing_dip":
            pallet_status = FormStatus.SUBMITTED
            pallet_count = rng.randint(6, 10)
        else:  # mixed_gaps
            pallet_status = FormStatus.SUBMITTED
            pallet_count = rng.randint(5, 9)

        fi_pallets = _fi(
            batch.id,
            ModelFormType.CASK_FINAL_PALLET_COUNT,
            ModelAccrualMode.LOG,
            {
                "date": run_date.isoformat(),
                "run_number": cfg["run_number"],
                "product": cfg["product"],
            },
            status=pallet_status,
        )
        db.add(fi_pallets)
        await db.flush()
        for i in range(1, pallet_count + 1):
            hour = 7 + (i // 3)
            op = rng.choice(["JS", "JD", "MB"])
            cases = _maybe(rng, rng.choice([48, 56, 60, 64]), 0.15 if profile != "early_run" else 0.4)
            payload = {"pallet_no": i}
            if cases is not None:
                payload["cases_per_pallet"] = cases
            db.add(
                Reading(
                    form_instance_id=fi_pallets.id,
                    sequence=i,
                    captured_at=_rt(run_date, min(hour, 16), (i * 7) % 60),
                    operator_identifier=op,
                    payload=payload,
                )
            )

        # --- FOR CA 002 line check matrix ---
        if profile == "early_run":
            # leave not started
            pass
        else:
            sparse = profile in ("missing_dip", "mixed_gaps")
            n_cols = 1 if profile == "missing_dip" else (2 if profile == "mixed_gaps" else 3)
            status = FormStatus.IN_PROGRESS if profile == "mixed_gaps" else FormStatus.SUBMITTED
            fi_check = _fi(
                batch.id,
                ModelFormType.CASK_LINE_CHECK,
                ModelAccrualMode.MATRIX,
                _line_check_header(cfg["product"], cfg["run_number"], cfg["tank"], run_date, rng),
                status=status,
            )
            db.add(fi_check)
            await db.flush()
            for seq, hour in enumerate([8, 11, 14][:n_cols], 1):
                db.add(
                    Reading(
                        form_instance_id=fi_check.id,
                        sequence=seq,
                        captured_at=_rt(run_date, hour, rng.randint(0, 20)),
                        operator_identifier=rng.choice(["JS", "JD", "MB"]),
                        payload=_line_check_reading(rng, sparse=sparse),
                    )
                )

        # --- FOR CA 003 waste ---
        if profile == "early_run":
            pass  # not started
        elif profile == "missing_dip":
            db.add(
                _fi(
                    batch.id,
                    ModelFormType.CASK_PRODUCTION_WASTE,
                    ModelAccrualMode.ATOMIC,
                    _waste_payload(rng, cfg["product"], cfg["run_number"], run_date, sparse=True),
                    status=FormStatus.IN_PROGRESS,
                )
            )
        else:
            db.add(
                _fi(
                    batch.id,
                    ModelFormType.CASK_PRODUCTION_WASTE,
                    ModelAccrualMode.ATOMIC,
                    _waste_payload(
                        rng,
                        cfg["product"],
                        cfg["run_number"],
                        run_date,
                        sparse=(profile == "mixed_gaps"),
                    ),
                    status=(
                        FormStatus.SUBMITTED
                        if profile == "almost_full"
                        else FormStatus.IN_PROGRESS
                    ),
                )
            )

        # --- FOR CA 004 tank dip ---
        if profile in ("missing_dip", "early_run"):
            pass
        else:
            db.add(
                _fi(
                    batch.id,
                    ModelFormType.CASK_TANK_DIP,
                    ModelAccrualMode.ATOMIC,
                    _dip_payload(
                        cfg["product"],
                        cfg["run_number"],
                        cfg["tank"],
                        run_date,
                        rng,
                        sparse=(profile == "mixed_gaps"),
                    ),
                    status=(
                        FormStatus.SUBMITTED
                        if profile == "almost_full"
                        else FormStatus.IN_PROGRESS
                    ),
                )
            )

        created.append(batch)

    await db.commit()

    # Reload with relationships for compile
    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.form_instances).selectinload(FormInstance.readings),
            selectinload(Batch.uploaded_documents),
            selectinload(Batch.compilations),
        )
        .where(Batch.run_number.in_([c["run_number"] for c in CASK_SEED_RUNS]))
    )
    return list(result.scalars().unique().all())


async def compile_cask_seed_runs(db: AsyncSession, upload_dir: str, compiled_dir: str) -> list[str]:
    """Compile PDFs for seeded cask runs (best-effort for incomplete forms)."""
    from app.services.compilation import compile_batch

    result = await db.execute(
        select(Batch)
        .options(
            selectinload(Batch.header),
            selectinload(Batch.form_instances).selectinload(FormInstance.readings),
            selectinload(Batch.uploaded_documents),
            selectinload(Batch.compilations),
        )
        .where(Batch.run_number.in_([c["run_number"] for c in CASK_SEED_RUNS]))
    )
    batches = list(result.scalars().unique().all())
    outputs: list[str] = []
    for batch in batches:
        try:
            comp = await compile_batch(
                batch,
                db,
                upload_dir,
                compiled_output_dir=compiled_dir,
                compiled_by="Cask Seed",
            )
            # Keep run status as seeded (don't mark complete for partials)
            await db.commit()
            outputs.append(comp.output_filename or comp.stored_path)
        except Exception as exc:
            outputs.append(f"{batch.run_number}: COMPILE_FAILED {exc}")
    return outputs
