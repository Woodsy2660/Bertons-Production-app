from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

CARTON_QC_TEMPLATE = FormTemplate(
    form_type=FormType.CARTON_QC,
    doc_number="FOR PK 018",
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
            key="carton_wastage",
            label="Carton Wastage",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="divider_wastage",
            label="Divider Wastage",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
    ],
    reading_fields=[
        # Table discriminator to separate carton_details from hourly_qc
        FieldDef(
            key="table",
            label="Table",
            field_type=FieldType.ENUM,
            source=FieldSource.OPERATOR,
            enum_values=["carton_details", "hourly_qc"],
        ),
        # Carton Details fields (table=carton_details)
        FieldDef(
            key="carton_manufacturer",
            label="Carton Manufacturer",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="carton_code",
            label="Carton code",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="qty_on_pallet",
            label="Quantity On Pallet",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="carton_code_match",
            label="Carton code match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="batch_number_pallet_tag",
            label="Batch number on pallet tag",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="dividers_match",
            label="Dividers match work order?",
            field_type=FieldType.ENUM,
            source=FieldSource.OPERATOR,
            enum_values=["Y", "N", "NA"],
        ),
        FieldDef(
            key="stickers_match",
            label="Do stickers match work order?",
            field_type=FieldType.ENUM,
            source=FieldSource.OPERATOR,
            enum_values=["Y", "N", "NA"],
        ),
        # Hourly QC fields (table=hourly_qc)
        FieldDef(
            key="captured_at",
            label="Date/Time",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="cartons_formed_glued",
            label="Cartons being formed & glued correctly?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="check_6_cartons",
            label="Check 6 consecutive cartons — belt full & weight working?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="carton_print_match",
            label="Carton Print to match work order?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="record_carton_print",
            label="Record Carton print",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="glue_shots_ok",
            label="Glue shots in correct place, no glue on bottles?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="cartons_sealed_neatly",
            label="Are cartons sealed properly and neatly?",
            field_type=FieldType.BOOL,
            source=FieldSource.OPERATOR,
        ),
        # Common field
        FieldDef(
            key="initials",
            label="Initials",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
)
