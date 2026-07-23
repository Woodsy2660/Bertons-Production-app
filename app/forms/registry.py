from app.forms.types import (
    FormType,
    AccrualMode,
    FieldType,
    FieldSource,
    FieldDef,
    FormTemplate,
)

# Import form definitions
from app.forms.definitions.daily_production import DAILY_PRODUCTION_TEMPLATE
from app.forms.definitions.filler_line_check import FILLER_LINE_CHECK_TEMPLATE
from app.forms.definitions.bottle_sealing import BOTTLE_SEALING_TEMPLATE
from app.forms.definitions.label_usage import LABEL_USAGE_TEMPLATE
from app.forms.definitions.finished_product_line_check import FINISHED_PRODUCT_LINE_CHECK_TEMPLATE
from app.forms.definitions.pick_list import PICK_LIST_TEMPLATE
from app.forms.definitions.carton_qc import CARTON_QC_TEMPLATE
from app.forms.definitions.final_pallet_count import FINAL_PALLET_COUNT_TEMPLATE
from app.forms.definitions.finished_product_pallet import FINISHED_PRODUCT_PALLET_TEMPLATE
from app.forms.definitions.cask_final_pallet_count import CASK_FINAL_PALLET_COUNT_TEMPLATE
from app.forms.definitions.cask_line_check import CASK_LINE_CHECK_TEMPLATE
from app.forms.definitions.cask_production_waste import CASK_PRODUCTION_WASTE_TEMPLATE
from app.forms.definitions.cask_tank_dip import CASK_TANK_DIP_TEMPLATE


FORM_TEMPLATES: dict[FormType, FormTemplate] = {
    FormType.DAILY_PRODUCTION: DAILY_PRODUCTION_TEMPLATE,
    FormType.FILLER_LINE_CHECK: FILLER_LINE_CHECK_TEMPLATE,
    FormType.BOTTLE_SEALING: BOTTLE_SEALING_TEMPLATE,
    FormType.LABEL_USAGE: LABEL_USAGE_TEMPLATE,
    FormType.FINISHED_PRODUCT_LINE_CHECK: FINISHED_PRODUCT_LINE_CHECK_TEMPLATE,
    FormType.PICK_LIST: PICK_LIST_TEMPLATE,
    FormType.CARTON_QC: CARTON_QC_TEMPLATE,
    FormType.FINAL_PALLET_COUNT: FINAL_PALLET_COUNT_TEMPLATE,
    FormType.FINISHED_PRODUCT_PALLET: FINISHED_PRODUCT_PALLET_TEMPLATE,
    FormType.CASK_FINAL_PALLET_COUNT: CASK_FINAL_PALLET_COUNT_TEMPLATE,
    FormType.CASK_LINE_CHECK: CASK_LINE_CHECK_TEMPLATE,
    FormType.CASK_PRODUCTION_WASTE: CASK_PRODUCTION_WASTE_TEMPLATE,
    FormType.CASK_TANK_DIP: CASK_TANK_DIP_TEMPLATE,
}

BOTTLING_FORM_TYPES: set[FormType] = {
    FormType.DAILY_PRODUCTION,
    FormType.FILLER_LINE_CHECK,
    FormType.BOTTLE_SEALING,
    FormType.LABEL_USAGE,
    FormType.FINISHED_PRODUCT_LINE_CHECK,
    FormType.PICK_LIST,
    FormType.CARTON_QC,
    FormType.FINAL_PALLET_COUNT,
    FormType.FINISHED_PRODUCT_PALLET,
}

CASK_FORM_TYPES: set[FormType] = {
    FormType.CASK_FINAL_PALLET_COUNT,
    FormType.CASK_LINE_CHECK,
    FormType.CASK_PRODUCTION_WASTE,
    FormType.CASK_TANK_DIP,
}


def forms_for_line_type(line_type: str | None) -> list[FormType]:
    """Ordered form list for a run's production line."""
    if (line_type or "bottling").lower() == "cask":
        return [
            FormType.CASK_FINAL_PALLET_COUNT,
            FormType.CASK_LINE_CHECK,
            FormType.CASK_PRODUCTION_WASTE,
            FormType.CASK_TANK_DIP,
        ]
    return [
        FormType.DAILY_PRODUCTION,
        FormType.FILLER_LINE_CHECK,
        FormType.BOTTLE_SEALING,
        FormType.LABEL_USAGE,
        FormType.FINISHED_PRODUCT_LINE_CHECK,
        FormType.PICK_LIST,
        FormType.CARTON_QC,
        FormType.FINAL_PALLET_COUNT,
        FormType.FINISHED_PRODUCT_PALLET,
    ]


def get_form_template(form_type: FormType) -> FormTemplate:
    return FORM_TEMPLATES[form_type]
