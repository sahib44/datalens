import json
import pytest
from app.profiling import Config, InputError, parse_csv, profile
from app.comparison import compare


@pytest.mark.parametrize(
    "content,message",
    [
        ("", "empty"),
        ("a,a\n1,2\n", "Duplicate"),
        ("a, \n1,2\n", "empty"),
        ("a,b\n1\n", "fields"),
        ('a\n"oops\n', "Unclosed"),
        ('a\nx"y\n', "Quote"),
        ('a\n"x"y\n', "Unexpected"),
        ("a\n\x00\n", "NUL"),
    ],
)
def test_invalid_csv(tmp_path, content, message):
    p = tmp_path / "test.csv"
    p.write_text(content)
    with pytest.raises(InputError, match=message):
        parse_csv(p)


def test_encoding_and_multiline(tmp_path):
    p = tmp_path / "data.csv"
    p.write_bytes(b'\xef\xbb\xbfa,b\r\n"hello\nworld",2\r\n')
    h, r = parse_csv(p)
    assert h == ["a", "b"]
    assert r == [["hello\nworld", "2"]]
    p.write_bytes(b"a\n\xff")
    with pytest.raises(InputError, match="UTF-8"):
        parse_csv(p)


def test_limits(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("a,b\n1,2\n3,4\n")
    with pytest.raises(InputError, match="columns"):
        parse_csv(p, max_columns=1)
    with pytest.raises(InputError, match="records"):
        parse_csv(p, max_rows=1)
    with p.open("wb") as f:
        f.truncate(25 * 1024 * 1024 + 1)
    with pytest.raises(InputError, match="25 MiB"):
        parse_csv(p)


def test_missing_tokens_and_identifiers():
    r = profile(["id", "region"], [["00123", "NA"], ["00456", " "], ["00789", "NULL"]])
    assert r["columns"][0]["type"] == "text"
    assert r["columns"][0]["examples"][0]["value"] == "00123"
    assert r["columns"][1]["missing_count"] == 1
    r = profile(["a"], [["NA"], ["NULL"], [" "]], Config(missing_tokens=("NULL",)))
    assert r["summary"]["missing_cells"] == 2


def test_duplicate_count_and_raw_policy():
    r = profile(["a"], [["x"], ["x"], ["x"], [" x "], ["y"], ["y"]])
    assert r["summary"]["duplicate_rows_beyond_first"] == 3
    assert r["summary"]["rows_in_duplicate_groups"] == 5
    f = next(f for f in r["findings"] if f["check_id"] == "duplicate")
    assert f["examples"][0]["records"] == [1, 2, 3]


def test_type_failure_and_finite_values():
    r = profile(["amount"], [[str(i)] for i in range(19)] + [["oops"]])
    assert r["columns"][0]["type"] == "numeric"
    f = next(f for f in r["findings"] if f["check_id"] == "parse_failure")
    assert f["count"] == 1 and f["denominator"] == 20
    assert f["examples"] == [{"record": 20, "value": "oops"}]
    r = profile(["x"], [[str(i)] for i in range(19)] + [["Infinity"]])
    assert r["columns"][0]["stats"]["finite_count"] == 19
    json.dumps(r, allow_nan=False)


def test_outliers_hand_calculated():
    r = profile(["x"], [[str(v)] for v in [1, 2, 3, 4, 100]])
    f = next(f for f in r["findings"] if f["check_id"] == "outlier")
    assert f["rule"] == {"q1": 2.0, "q3": 4.0, "iqr": 2.0, "lower": -1.0, "upper": 7.0}
    assert f["examples"] == [{"record": 5, "value": "100"}]
    for data in [[1, 1, 1, 1, 100], [1, 2, 3]]:
        p = profile(["x"], [[str(v)] for v in data])
        assert not any(f["check_id"] == "outlier" for f in p["findings"])


def test_formatting_and_empty():
    r = profile(["region", "empty"], [[" North ", ""], ["NORTH", " "], ["North", ""]])
    f = next(f for f in r["findings"] if f["check_id"] == "formatting")
    assert f["count"] == 3
    assert r["columns"][1]["type"] == "empty"
    assert any(f["check_id"] == "empty_column" for f in r["findings"])
    p = profile(["a"], [])
    assert p["summary"]["missing_rate"] is None


def test_dates_boolean_and_ambiguous():
    r = profile(
        ["d", "b", "amb"],
        [["2025-01-01", "true", "01/02/2025"], ["2025-02-01", "false", "02/03/2025"]],
    )
    assert [c["type"] for c in r["columns"]] == ["datetime", "boolean", "text"]
    assert r["columns"][0]["stats"]["earliest"] == "2025-01-01T00:00:00"
    assert r["columns"][2]["warnings"]


def test_comparison_hand_computed():
    ah = ["category", "value", "removed"]
    bh = ["category", "value", "added"]
    ar = [["A", "1", "x"], ["A", "2", "y"]]
    br = [["B", "3", "z"], ["B", "4", "z"]]
    r = compare(ah, ar, bh, br, profile(ah, ar), profile(bh, br))
    assert r["added_columns"] == ["added"]
    assert r["removed_columns"] == ["removed"]
    assert r["columns"][0]["categorical"]["total_variation"] == 1
    assert r["columns"][1]["numeric"]["ks_statistic"] == 1
    assert sum(r["columns"][1]["numeric"]["histogram"]["baseline"]) == 2


def test_missingness_and_incompatible_comparison():
    h = ["x"]
    a = [["1"], ["2"]]
    b = [[""], ["hello"]]
    r = compare(h, a, h, b, profile(h, a), profile(h, b))["columns"][0]
    assert r["missingness_delta_pp"] == 50
    assert "numeric" not in r and "categorical" not in r
    assert any("types differ" in w for w in r["warnings"])


def test_extreme_numeric_is_valid_json():
    r = profile(["x"], [["1e308"], ["-1e308"], ["1e308"], ["-1e308"]])
    json.dumps(r, allow_nan=False)


def test_configuration_constraints():
    with pytest.raises(InputError):
        Config(dominant_threshold=1.2)
