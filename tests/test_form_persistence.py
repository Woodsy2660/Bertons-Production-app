from app.services.form_persistence import (
    build_form_payload_from_mapping,
    build_pick_list_lines,
    reading_summary,
)


def test_build_form_payload_handles_arrays():
    payload = build_form_payload_from_mapping({
        "fill_height": ["62.1", "62.0"],
        "filler_vacuum": "-0.42",
        "empty": "",
    })
    assert payload["fill_height"] == ["62.1", "62.0"]
    assert payload["filler_vacuum"] == "-0.42"
    assert payload["empty"] is None


def test_build_pick_list_lines():
    data = {
        "lines_0_stock_item": "LFPRESSB25",
        "lines_0_description": "Label",
        "lines_0_required": "126000",
        "lines_0_supplied_qty": "126200",
        "lines_0_returned_qty": "145",
    }
    lines = build_pick_list_lines(data)
    assert len(lines) == 1
    assert lines[0]["stock_item"] == "LFPRESSB25"
    assert lines[0]["supplied_qty"] == "126200"


def test_reading_summary_carton_qc():
    assert reading_summary(
        "carton_qc",
        {"table": "carton_details", "carton_code": "CNPRESSB400"},
    ) == "CNPRESSB400"

    assert reading_summary(
        "carton_qc",
        {"table": "hourly_qc", "record_carton_print": "2025 F25SSBPREAU1"},
    ) == "2025 F25SSBPREAU1"


def test_reading_summary_final_pallet_count():
    assert reading_summary(
        "final_pallet_count",
        {"region": "bottles", "pallet_no": "B-001"},
    ) == "Pallet B-001"