from typing import Any

from app.forms.registry import (
    FormType,
    FormTemplate,
    FieldDef,
    FieldType,
    FORM_TEMPLATES,
)


class PayloadValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Validation errors: {', '.join(errors)}")


def validate_payload(
    form_type: FormType,
    payload: dict[str, Any],
    is_reading: bool = False,
) -> list[str]:
    """
    Validate a payload against a form template.

    Args:
        form_type: The type of form being validated
        payload: The payload to validate
        is_reading: True if validating a reading payload, False for header payload

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []
    template = FORM_TEMPLATES.get(form_type)

    if not template:
        errors.append(f"Unknown form type: {form_type}")
        return errors

    fields = template.reading_fields if is_reading else template.header_fields

    for field_def in fields:
        value = payload.get(field_def.key)
        field_errors = _validate_field(field_def, value)
        errors.extend(field_errors)

    return errors


def _validate_field(field_def: FieldDef, value: Any) -> list[str]:
    """Validate a single field value against its definition."""
    errors: list[str] = []

    # Skip validation for None/missing optional fields
    if value is None:
        if field_def.required:
            errors.append(f"Field '{field_def.key}' is required")
        return errors

    # Multi-value field validation
    if field_def.multi_value_count is not None:
        if not isinstance(value, list):
            errors.append(
                f"Field '{field_def.key}' must be an array with "
                f"{field_def.multi_value_count} values"
            )
        elif len(value) != field_def.multi_value_count:
            errors.append(
                f"Field '{field_def.key}' must have exactly "
                f"{field_def.multi_value_count} values, got {len(value)}"
            )
        else:
            # Validate each value in the array
            for i, v in enumerate(value):
                v_errors = _validate_single_value(field_def, v, index=i)
                errors.extend(v_errors)
        return errors

    # Single value validation
    errors.extend(_validate_single_value(field_def, value))
    return errors


def _validate_single_value(
    field_def: FieldDef,
    value: Any,
    index: int | None = None
) -> list[str]:
    """Validate a single value (scalar) against field type."""
    errors: list[str] = []
    field_key = field_def.key
    if index is not None:
        field_key = f"{field_def.key}[{index}]"

    if field_def.field_type == FieldType.NUMBER:
        if not isinstance(value, (int, float, str)):
            errors.append(f"Field '{field_key}' must be a number")
        elif isinstance(value, str):
            try:
                float(value)
            except ValueError:
                errors.append(f"Field '{field_key}' must be a valid number")

    elif field_def.field_type == FieldType.BOOL:
        valid_bool_values = {True, False, "Y", "N", "y", "n", "yes", "no", "Yes", "No"}
        if value not in valid_bool_values and not isinstance(value, bool):
            errors.append(
                f"Field '{field_key}' must be a boolean or Y/N"
            )

    elif field_def.field_type == FieldType.ENUM:
        if field_def.enum_values and value not in field_def.enum_values:
            errors.append(
                f"Field '{field_key}' must be one of: "
                f"{', '.join(field_def.enum_values)}"
            )

    elif field_def.field_type == FieldType.ARRAY:
        if not isinstance(value, list):
            errors.append(f"Field '{field_key}' must be an array")

    elif field_def.field_type in (FieldType.TEXT, FieldType.TIME, FieldType.DATE):
        if not isinstance(value, str):
            errors.append(f"Field '{field_key}' must be a string")

    return errors


def validate_reading_payload(form_type: FormType, payload: dict[str, Any]) -> list[str]:
    """Convenience function for validating reading payloads."""
    return validate_payload(form_type, payload, is_reading=True)


def validate_header_payload(form_type: FormType, payload: dict[str, Any]) -> list[str]:
    """Convenience function for validating header payloads."""
    return validate_payload(form_type, payload, is_reading=False)
