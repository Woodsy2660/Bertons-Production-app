from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

LABEL_USAGE_TEMPLATE = FormTemplate(
    form_type=FormType.LABEL_USAGE,
    doc_number="FOR PK 023",
    accrual_mode=AccrualMode.LOG,
    orientation="portrait",
    header_fields=[
        FieldDef(
            key="date",
            label="Date",
            field_type=FieldType.DATE,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="product",
            label="Product",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="run_number",
            label="Run no.",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="totals_note",
            label="Totals (manual)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
    reading_fields=[
        FieldDef(
            key="section",
            label="Section",
            field_type=FieldType.ENUM,
            source=FieldSource.OPERATOR,
            enum_values=["fronts", "backs", "other"],
        ),
        FieldDef(
            key="captured_at",
            label="Time",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="counter",
            label="Counter",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="gms",
            label="gms",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="matches_work_order",
            label="Match Work Order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="po_no",
            label="P.O. no.",
            field_type=FieldType.TEXT,
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
