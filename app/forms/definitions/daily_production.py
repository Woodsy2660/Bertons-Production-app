from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

DAILY_PRODUCTION_TEMPLATE = FormTemplate(
    form_type=FormType.DAILY_PRODUCTION,
    doc_number="FOR PK 013",
    accrual_mode=AccrualMode.ATOMIC,
    orientation="portrait",
    header_fields=[
        FieldDef(
            key="date",
            label="Date",
            field_type=FieldType.DATE,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="run_number",
            label="Run Number",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="product",
            label="Product",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="tank",
            label="Tank",
            field_type=FieldType.TEXT,
            source=FieldSource.INHERITED,
        ),
        FieldDef(
            key="start_time",
            label="Start time",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="finish_time",
            label="Finish time",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="cartons_produced",
            label="Cartons produced (office)",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="wine_volume",
            label="Wine Volume (Litres)",
            field_type=FieldType.NUMBER,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="dip_tank_start",
            label="Dip tank start",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="dip_tank_end",
            label="Dip tank end",
            field_type=FieldType.TIME,
            source=FieldSource.OPERATOR,
        ),
        FieldDef(
            key="filler_room_breakages",
            label="Any filler room bottle breakages?",
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
    reading_fields=[],
)