from dataclasses import dataclass, field
from enum import Enum


class FormType(str, Enum):
    DAILY_PRODUCTION = "daily_production"
    FILLER_LINE_CHECK = "filler_line_check"
    BOTTLE_SEALING = "bottle_sealing"
    LABEL_USAGE = "label_usage"
    FINISHED_PRODUCT_LINE_CHECK = "finished_product_line_check"
    PICK_LIST = "pick_list"
    CARTON_QC = "carton_qc"
    FINAL_PALLET_COUNT = "final_pallet_count"
    FINISHED_PRODUCT_PALLET = "finished_product_pallet"


class AccrualMode(str, Enum):
    ATOMIC = "atomic"
    LOG = "log"
    MATRIX = "matrix"


class FieldType(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    TIME = "time"
    DATE = "date"
    BOOL = "bool"
    ENUM = "enum"
    ARRAY = "array"  # For repeatable items like dip_tanks


class FieldSource(str, Enum):
    INHERITED = "inherited"
    OPERATOR = "operator"


@dataclass
class FieldDef:
    key: str
    label: str
    field_type: FieldType
    source: FieldSource
    multi_value_count: int | None = None  # For [×N] fields
    enum_values: list[str] | None = None  # For enum fields
    required: bool = False


@dataclass
class FormTemplate:
    form_type: FormType
    doc_number: str | None
    accrual_mode: AccrualMode
    orientation: str  # "portrait" or "landscape"
    header_fields: list[FieldDef] = field(default_factory=list)
    reading_fields: list[FieldDef] = field(default_factory=list)  # Empty for atomic forms
