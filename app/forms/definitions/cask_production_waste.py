from app.forms.types import (
    FormTemplate,
    FormType,
    AccrualMode,
    FieldDef,
    FieldType,
    FieldSource,
)

# FOR CA 003 — atomic waste counts; category totals calculated in the UI/save path.
CASK_PRODUCTION_WASTE_TEMPLATE = FormTemplate(
    form_type=FormType.CASK_PRODUCTION_WASTE,
    doc_number="FOR CA 003",
    accrual_mode=AccrualMode.ATOMIC,
    orientation="portrait",
    header_fields=[
        FieldDef(key="product", label="Product", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="run_number", label="Run No.", field_type=FieldType.TEXT, source=FieldSource.INHERITED),
        FieldDef(key="date", label="Date", field_type=FieldType.DATE, source=FieldSource.INHERITED),
        # Casks — Other is count + problem on one UI/PDF row (keys kept separate for totals)
        FieldDef(key="casks_machine_jam", label="Casks — Machine Jam", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="casks_printing", label="Casks — Printing", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="casks_other_count", label="Casks — Other", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="casks_other_problem", label="Casks — Other (problem)", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        # Bladders
        FieldDef(key="bladders_split", label="Bladders — Split", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="bladders_faulty_tap", label="Bladders — Faulty Tap", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="bladders_other_count", label="Bladders — Other", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="bladders_other_problem", label="Bladders — Other (problem)", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        # Inners
        FieldDef(key="inners_machine_jam", label="Inners — Machine Jam", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="inners_printing", label="Inners — Printing", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="inners_other_count", label="Inners — Other", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="inners_other_problem", label="Inners — Other (problem)", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        # Outers
        FieldDef(key="outers_machine_jam", label="Outers — Machine Jam", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="outers_printing", label="Outers — Printing", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="outers_other_count", label="Outers — Other", field_type=FieldType.NUMBER, source=FieldSource.OPERATOR),
        FieldDef(key="outers_other_problem", label="Outers — Other (problem)", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        FieldDef(key="comments", label="Comments", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        FieldDef(key="initials", label="Signature / initials", field_type=FieldType.TEXT, source=FieldSource.OPERATOR),
        FieldDef(key="signature_date", label="Signature date", field_type=FieldType.DATE, source=FieldSource.OPERATOR),
    ],
    reading_fields=[],
)
