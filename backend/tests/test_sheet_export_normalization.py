from app.services.export_normalization import normalize_export_cell, normalize_export_row


def test_normalize_export_cell_removes_newlines_tabs_and_collapses_ws():
    raw = "Hello,\n\nthis\tis  a   reply.\r\nQuoted \"text\", commas, etc."
    out = normalize_export_cell(raw)
    assert "\n" not in out
    assert "\r" not in out
    assert "\t" not in out
    # collapsed
    assert "  " not in out
    assert "Hello," in out
    assert "Quoted" in out


def test_normalize_export_row_is_fixed_length_and_stringy():
    row = normalize_export_row([None, "a\nb", 123], expected_len=5)
    assert isinstance(row, list)
    assert len(row) == 5
    assert row[0] == ""
    assert row[1] == "a b"
    assert row[2] == "123"
    assert row[3] == ""
    assert row[4] == ""

