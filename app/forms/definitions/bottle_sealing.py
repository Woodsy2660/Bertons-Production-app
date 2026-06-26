from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

BOTTLE_SEALING_TEMPLATE = FormTemplate(
    form_type=FormType.BOTTLE_SEALING,
    doc_number="FOR PK 016A",
    accrual_mode=AccrualMode.LOG,
    orientation="landscape",
    header_fields=[
        FieldDef(
            key="date",
            label="Date",
            field_type=FieldType.DATE,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="run_number",
            label="Run number",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="manufacturer",
            label="Manufacturer",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="part_number",
            label="Part number",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
    reading_fields=[
        FieldDef(
            key="captured_at",
            label="Time",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="batch_number",
            label="Batch number",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
            barcode_scan=True,
        ),
        FieldDef(
            key="matches_work_order",
            label="Does it match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="qty_used",
            label="Qty Used",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="initial",
            label="Initial",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
)
