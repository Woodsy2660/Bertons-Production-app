from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

# FOR CA 002 — accrual matrix (hourly columns), same pattern as Filler Line Check.
CASK_LINE_CHECK_TEMPLATE = FormTemplate(
    form_type=FormType.CASK_LINE_CHECK,
    doc_number="FOR CA 002",
    accrual_mode=AccrualMode.MATRIX,
    orientation="landscape",
    header_fields=[
        FieldDef(key="date", label="Date", field_type=FieldType.DATE, source=FieldSource.INHERITED),
        FieldDef(key="tank", label="Tank", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="run_number", label="Run number", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="wine", label="Wine", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="wine_sg", label="Wine S.G.", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        FieldDef(
            key="empty_bladder_weight_g",
            label="Empty bladder weight (g)",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="best_before_date",
            label="Best Before Date",
            field_type=FieldType.DATE,
            source=FieldSource.OPERATOR,
        ),
    ],
    reading_fields=[
        FieldDef(key="captured_at", label="Time", field_type=FieldType.TIME, source=FieldSource.OPERATOR),
        FieldDef(
            key="bladder_match",
            label="Bladder — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(key="filler_vacuum", label="Filler Vacuum", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        FieldDef(
            key="full_bladder_weight",
            label="Full bladder weight (3 bags)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
            multi_value_count=3,
        ),
        FieldDef(
            key="inner_match",
            label="Inner — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="inner_inkjet_match",
            label="Inner Inkjet Code — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="glue_dripping",
            label="Glue — dripping onto bladders?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="inner_flaps_glued",
            label="Inner flaps — glued together?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="best_before_match",
            label="Best Before Date — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="outer_inkjet_match",
            label="Outer Inkjet Code — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="outer_flaps_glued",
            label="Outer flaps — glued together?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="stacking_match",
            label="Stacking — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="pallet_type_match",
            label="Pallet Type — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(key="slip_sheet", label="Slip Sheet", field_type=FieldType.BOOL, source=FieldSource.OPERATOR),
        FieldDef(
            key="checked_by",
            label="Checked By (initials)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
)
