from app.forms import forms_for_line_type, FormType, get_form_template
from app.services.compilation import CASK_COMPILE_SLOTS, compile_slots_for_batch
from app.services.form_persistence import apply_cask_waste_totals


def test_forms_for_line_type_partitions():
    bottling = {ft.value for ft in forms_for_line_type("bottling")}
    cask = {ft.value for ft in forms_for_line_type("cask")}
    assert "daily_production" in bottling
    assert "cask_line_check" not in bottling
    assert cask == {
        "cask_final_pallet_count",
        "cask_line_check",
        "cask_production_waste",
        "cask_tank_dip",
    }
    assert bottling.isdisjoint(cask)


def test_cask_templates_registered():
    for ft in forms_for_line_type("cask"):
        tpl = get_form_template(ft)
        assert tpl.doc_number.startswith("FOR CA")
        assert tpl.form_type is ft


def test_cask_compile_slots_separate_from_bottling():
    class _Line:
        value = "cask"

    class _Batch:
        line_type = _Line()

    slots = compile_slots_for_batch(_Batch())
    assert slots is CASK_COMPILE_SLOTS
    form_types = [s["form_type"] for s in slots if s["source"] == "app_form"]
    assert form_types == [
        "cask_final_pallet_count",
        "cask_line_check",
        "cask_production_waste",
        "cask_tank_dip",
    ]
    assert not any(s.get("form_type") == "daily_production" for s in slots)


def test_cask_waste_totals_auto_sum():
    out = apply_cask_waste_totals(
        {
            "casks_machine_jam": "1",
            "casks_printing": "2",
            "casks_other_count": "3",
            "bladders_split": "4",
            "bladders_faulty_tap": "",
            "bladders_other_count": "1",
        }
    )
    assert out["casks_total"] == 6
    assert out["bladders_total"] == 5
    assert out["inners_total"] == 0
