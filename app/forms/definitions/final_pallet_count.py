from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

FINAL_PALLET_COUNT_TEMPLATE = FormTemplate(
    form_type=FormType.FINAL_PALLET_COUNT,
    doc_number="FOR PK 012A",
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
            key="run_number",
            label="Run #",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="bottle_code",
            label="Bottle Code",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="bottle_code_matches",
            label="Bottle code matches work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="product",
            label="Product",
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
            key="manufacturer",
            label="Manufacturer",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="pallet_tag_matches",
            label="Pallet tag(s) matches work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="bottle_breakages",
            label="Bottle Breakages",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="carton_breakages",
            label="Carton Breakages",
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
        # Region discriminator
        FieldDef(
            key="region",
            label="Region",
            field_type=FieldType.ENUM,
            source=FieldSource.OPERATOR,
            enum_values=["bottles", "finished"],
        ),
        # Bottles region fields
        FieldDef(
            key="seq_no",
            label="#",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="prn_date",
            label="PRN date",
            field_type=FieldType.DATE,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="pallet_no",
            label="Pallet #",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="colour",
            label="Colour",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="foreign_objects_checked",
            label="Checked for foreign objects?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="captured_at",
            label="Time",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        # Finished region fields
        FieldDef(
            key="high",
            label="High",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
    ],
)
