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
}


def get_form_template(form_type: FormType) -> FormTemplate:
    return FORM_TEMPLATES[form_type]
