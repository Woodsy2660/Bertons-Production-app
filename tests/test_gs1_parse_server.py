"""Unit tests for server-side GS1 bracketed parser (Final Pallet Count)."""

from app.services.gs1_parse import (
    format_gs1_date_yymmdd,
    parse_bracketed_gs1,
    parse_final_pallet_gs1,
)

# Real Knox Capture (Parse GS1 on) output from production pallet tag
REAL_SCAN = "(02)09331288015587(11)260501(10)6121(37)504(90)16211644"


def test_real_scan_extracts_all_mapped_fields():
    result = parse_final_pallet_gs1(REAL_SCAN)
    assert result.ok is True
    assert result.format == "bracketed"
    assert result.fields["pallet_no"] == "16211644"
    assert result.fields["quantity"] == "504"
    assert result.fields["high"] == "504"
    assert result.fields["batch"] == "6121"
    assert result.fields["prn_date"] == "2026-05-01"
    assert result.fields["gtin"] == "09331288015587"
    assert result.prefill["pallet_no"] == "16211644"
    assert result.prefill["high"] == "504"
    assert result.prefill["prn_date"] == "2026-05-01"
    assert result.ais["90"] == "16211644"
    assert result.ais["37"] == "504"
    assert result.ais["10"] == "6121"
    assert result.ais["11"] == "260501"
    assert result.ais["02"] == "09331288015587"


def test_ais_in_different_order():
    reordered = "(90)16211644(37)504(10)6121(11)260501(02)09331288015587"
    result = parse_final_pallet_gs1(reordered)
    assert result.fields["pallet_no"] == "16211644"
    assert result.fields["quantity"] == "504"
    assert result.fields["batch"] == "6121"
    assert result.fields["prn_date"] == "2026-05-01"
    assert result.fields["gtin"] == "09331288015587"


def test_missing_expected_ai_leaves_blank_and_flags():
    # No AI (90) pallet number
    partial = "(02)09331288015587(11)260501(10)6121(37)504"
    result = parse_final_pallet_gs1(partial)
    assert result.ok is True  # still a valid bracketed parse
    assert result.fields["pallet_no"] is None
    assert result.fields["quantity"] == "504"
    assert "pallet_no" not in result.prefill
    missing = [f for f in result.flags if f.code == "missing_ai" and f.ai == "90"]
    assert len(missing) == 1
    assert "pallet" in missing[0].message.lower()


def test_missing_quantity_ai_flags():
    partial = "(90)16211644(10)6121"
    result = parse_final_pallet_gs1(partial)
    assert result.fields["quantity"] is None
    assert result.fields["high"] is None
    assert "high" not in result.prefill
    missing = [f for f in result.flags if f.code == "missing_ai" and f.ai == "37"]
    assert len(missing) == 1


def test_extra_unexpected_ai_ignored_gracefully():
    with_extra = REAL_SCAN + "(91)EXTRA-INTERNAL"
    result = parse_final_pallet_gs1(with_extra)
    assert result.fields["pallet_no"] == "16211644"
    assert result.fields["quantity"] == "504"
    assert result.ais.get("91") == "EXTRA-INTERNAL"
    # No error flag for the extra AI
    assert not any(f.code == "unknown_ai_error" for f in result.flags)


def test_not_bracketed_rejected_no_guess():
    result = parse_final_pallet_gs1("16211644 plain text")
    assert result.ok is False
    assert result.fields["pallet_no"] is None
    assert result.fields["quantity"] is None
    assert result.prefill == {}
    assert any(f.code == "not_bracketed" for f in result.flags)


def test_empty_scan_rejected():
    result = parse_final_pallet_gs1("   ")
    assert result.ok is False
    assert any(f.code == "empty" for f in result.flags)


def test_date_format_yymmdd():
    assert format_gs1_date_yymmdd("260501") == "2026-05-01"
    assert format_gs1_date_yymmdd("000229") == "2000-02-29"  # 2000 is a leap year
    assert format_gs1_date_yymmdd("250231") is None  # Feb 31 invalid
    assert format_gs1_date_yymmdd("abcd") is None
    assert format_gs1_date_yymmdd(None) is None


def test_no_work_order_matching_flags():
    """Parser must not flag batch/GTIN against run data — operator checks results."""
    result = parse_final_pallet_gs1(REAL_SCAN)
    assert not any(f.code in ("batch_mismatch", "gtin_mismatch") for f in result.flags)
    assert result.prefill["pallet_no"] == "16211644"
    assert result.fields["batch"] == "6121"
    assert result.fields["gtin"] == "09331288015587"


def test_parse_bracketed_raw_dict():
    ais = parse_bracketed_gs1(REAL_SCAN)
    assert ais == {
        "02": "09331288015587",
        "11": "260501",
        "10": "6121",
        "37": "504",
        "90": "16211644",
    }


def test_to_dict_shape():
    data = parse_final_pallet_gs1(REAL_SCAN).to_dict()
    assert data["ok"] is True
    assert data["fields"]["pallet_no"] == "16211644"
    assert isinstance(data["flags"], list)
    assert isinstance(data["missing"], list)
    assert "prefill" in data
