from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

PICK_LIST_TEMPLATE = FormTemplate(
    form_type=FormType.PICK_LIST,
    doc_number=None,
    accrual_mode=AccrualMode.ATOMIC,
    orientation="portrait",
    header_fields=[
        FieldDef(
            key="run_number",
            label="Run Number",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="packing_unit",
            label="Packing Unit",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="packaging_line",
            label="Packaging Line",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="run_date",
            label="Run Date",
            field_type=FieldType.DATE,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="run_quantity",
            label="Run Quantity",
            field_type=FieldType.NUMBER,
            source=FieldSource.INHERITED,
        ),
        # Label lines from work order (L-prefix stock items); operator fills qty only
        FieldDef(
            key="lines",
            label="Label Pick List Lines",
            field_type=FieldType.ARRAY,
            source=FieldSource.OPERATOR,
        ),
    ],
    reading_fields=[],
)