import pandas as pd

from src.employees import extract_root_id, merge_employees
from src.transform import drop_empty_columns, excel_safe_value, find_column_ending_with


def test_extract_root_id_from_slash_value() -> None:
    employee = {"/root/id": {"value": "123"}}
    assert extract_root_id(employee) == "123"


def test_merge_employees_tracks_credential_sources() -> None:
    store = {}
    merge_employees(store, [{"root": {"id": "1"}, "work": {"title": "A"}}], "first")
    merge_employees(store, [{"root": {"id": "1"}, "work": {"site": "B"}}], "second")

    employee = store["1"]

    assert employee["work"]["title"] == "A"
    assert employee["work"]["site"] == "B"
    assert employee["_credential_sources"] == ["first", "second"]


def test_drop_empty_columns_removes_only_fully_empty_columns() -> None:
    dataframe = pd.DataFrame({"a": [None, None], "b": [None, "x"]})
    result = drop_empty_columns(dataframe)
    assert list(result.columns) == ["b"]


def test_excel_safe_value_serializes_lists_and_dicts() -> None:
    assert excel_safe_value({"a": 1}) == '{"a": 1}'
    assert excel_safe_value([1, 2]) == "[1, 2]"


def test_find_column_ending_with() -> None:
    dataframe = pd.DataFrame(columns=["RAW | Root | Email | root.email"])
    assert find_column_ending_with(dataframe, "root.email", "RAW") == "RAW | Root | Email | root.email"
