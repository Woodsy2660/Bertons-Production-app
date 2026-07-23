from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

# FOR CA 004 — atomic tank dip sheet (start/finish cm + L, multi-column dips).
CASK_TANK_DIP_TEMPLATE = FormTemplate(
    form_type=FormType.CASK_TANK_DIP,
    doc_number="FOR CA 004",
    accrual_mode=AccrualMode.ATOMIC,
    orientation="portrait",
    header_fields=[
        FieldDef(key="product", label="Product", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="run_number", label="Run No.", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="date", label="Date", field_type=FieldType.DATE, source=FieldSource.INHERITED),
        FieldDef(key="tank", label="Tank", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(
            key="volume_supplied",
            label="Volume supplied",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="starting_dip_cm",
            label="Starting dip (cm)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
            multi_value_count=4,
        ),
        FieldDef(
            key="starting_dip_l",
            label="Starting dip (L)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
            multi_value_count=4,
        ),
        FieldDef(
            key="starting_initials",
            label="Starting dip initials",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="finishing_dip_cm",
            label="Finishing dip (cm)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
            multi_value_count=4,
        ),
        FieldDef(
            key="finishing_dip_l",
            label="Finishing dip (L)",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
            multi_value_count=4,
        ),
        FieldDef(
            key="finishing_initials",
            label="Finishing dip initials",
            field_type=FieldType.TEXT,
            source=FieldSource.OPERATOR,
        ),
    ],
    reading_fields=[],
)
