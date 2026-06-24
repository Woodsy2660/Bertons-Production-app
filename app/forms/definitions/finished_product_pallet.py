from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

FINISHED_PRODUCT_PALLET_TEMPLATE = FormTemplate(
    form_type=FormType.FINISHED_PRODUCT_PALLET,
    doc_number="FOR PK 020A",
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
            key="operator",
            label="Operator",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="bottle_code",
            label="Bottle code",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="bottle_code_matches",
            label="Does bottle code match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="pallet_type",
            label="Pallet type",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="slip_sheet_required",
            label="Slip sheet required?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="layer_config_matches",
            label="Pallet layer configuration matches work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="stack_height_matches",
            label="Pallet stack height matches work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="breakages",
            label="Breakages",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="summary_note",
            label="Summary note",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
    reading_fields=[
        FieldDef(
            key="seq_no",
            label="#",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="high",
            label="High",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="captured_at",
            label="Time",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
    ],
)
