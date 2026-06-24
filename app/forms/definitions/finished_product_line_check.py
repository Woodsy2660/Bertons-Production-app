from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

FINISHED_PRODUCT_LINE_CHECK_TEMPLATE = FormTemplate(
    form_type=FormType.FINISHED_PRODUCT_LINE_CHECK,
    doc_number="FOR PK 019",
    accrual_mode=AccrualMode.MATRIX,
    orientation="landscape",
    header_fields=[
        FieldDef(
            key="date",
            label="Date",
            field_type=FieldType.DATE,
            source=FieldSource.INHERITED,
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
            key="run_number",
            label="Run number",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="front_label_height",
            label="Front label height",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="back_label_height",
            label="Back label height",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="gap_between_labels",
            label="Gap between labels (2 readings)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
            multi_value_count=2,
        ),
        FieldDef(
            key="other_label_height",
            label="Other label height",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="label_inkjet_lot",
            label="Label Inkjet Print / Record Lot Number / Capsule PVA",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="inkjet_match",
            label="Does it match work order? / Is it shrunk correctly?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="bvs_code_match",
            label="BVS code — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="carton_barcode_match",
            label="Carton barcode number — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="carton_print_match",
            label="Carton print — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="carton_sticker_match",
            label="Carton Sticker — match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="bottles_scraped_clean",
            label="Bottles Scraped — are they clean?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="initials",
            label="Initials",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
)
