from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

# FOR CA 001 — accrual log of completed pallets (not a fixed 80-row grid).
CASK_FINAL_PALLET_COUNT_TEMPLATE = FormTemplate(
    form_type=FormType.CASK_FINAL_PALLET_COUNT,
    doc_number="FOR CA 001",
    accrual_mode=AccrualMode.LOG,
    orientation="portrait",
    header_fields=[
        FieldDef(key="date", label="Date", field_type=FieldType.DATE, source=FieldSource.INHERITED),
        FieldDef(key="run_number", label="Run number", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="product", label="Product", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
    ],
    reading_fields=[
        FieldDef(key="pallet_no", label="Pallet #", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="captured_at", label="Time", field_type=FieldType.TIME, source=FieldSource.OPERATOR),
        FieldDef(key="cases_per_pallet", label="Cases per pallet", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
    ],
)
