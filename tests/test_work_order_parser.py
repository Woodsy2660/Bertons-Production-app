from app.services.work_order_parser import (
    _extract_label_pick_list_lines,
    filter_label_lines,
    is_label_stock,
)


def test_is_label_stock():
    assert is_label_stock("LBRESCSA22")
    assert is_label_stock("lbrescs22")
    assert not is_label_stock("F22CSARESAI6")
    assert not is_label_stock("CRT-6x750")
    assert not is_label_stock("LABEL")


def test_extract_label_stock_from_stock_item_keyword():
    text = """
    Work Order Run 15646
    Stock Item: LBRESCSA22  Reserve Front Label  10800 THOU
    Stock Item: LBRESCSA22B Back Label 10800
    Stock Item: F22CSARESAI6  Wine product 1800
    Stock Item: CRT6x750 Carton 310
    """
    lines = _extract_label_pick_list_lines(text)
    codes = [line["stock_item"] for line in lines]
    assert "LBRESCSA22" in codes
    assert "LBRESCSA22B" in codes
    assert "F22CSARESAI6" not in codes
    assert "CRT6X750" not in codes


def test_filter_label_lines():
    mixed = [
        {"stock_item": "LBRESCSA22", "description": "Front"},
        {"stock_item": "F22CSARESAI6", "description": "Wine"},
    ]
    filtered = filter_label_lines(mixed)
    assert len(filtered) == 1
    assert filtered[0]["stock_item"] == "LBRESCSA22"