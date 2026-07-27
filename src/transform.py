import json
from typing import Any

import pandas as pd

from src.employees import extract_root_id, unwrap_value
from src.fields import PRIORITY_FIELDS


def build_employees_dataframe(employees: list[dict], metadata: list[dict]) -> pd.DataFrame:
    rows = [create_employee_row(employee, metadata) for employee in employees]
    dataframe = pd.DataFrame(rows)
    dataframe = drop_empty_columns(dataframe)
    return order_priority_columns(dataframe)


def create_employee_row(employee: dict, metadata: list[dict]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "HiBob Root ID": extract_root_id(employee),
        "Credential Sources": excel_safe_value(employee.get("_credential_sources")),
    }
    human_readable = employee.get("humanReadable", {})

    for field in metadata:
        field_id = field["id"]
        raw_column = metadata_column_name(field, human_readable=False)
        hr_column = metadata_column_name(field, human_readable=True)
        row[raw_column] = excel_safe_value(get_direct_field_value(employee, field_id))
        row[hr_column] = excel_safe_value(get_nested_value(human_readable, field_id))

    return row


def metadata_to_dataframe(metadata: list[dict]) -> pd.DataFrame:
    dataframe = pd.DataFrame(metadata)
    if dataframe.empty:
        return dataframe

    preferred_columns = [
        "id",
        "name",
        "categoryDisplayName",
        "categoryId",
        "category",
        "jsonPath",
        "type",
        "historical",
        "description",
    ]
    columns = [column for column in preferred_columns if column in dataframe.columns]
    columns += [column for column in dataframe.columns if column not in columns]
    return dataframe[columns]


def build_target_dataframe(dataframe: pd.DataFrame, target_email: str | None, target_employee_id: str | None) -> pd.DataFrame:
    if dataframe.empty or (not target_email and not target_employee_id):
        return pd.DataFrame()

    email_column = find_column_ending_with(dataframe, "root.email", "RAW") or find_column_ending_with(dataframe, "root.email", "HR")
    employee_id_column = find_column_ending_with(dataframe, "work.employeeIdInCompany", "RAW") or find_column_ending_with(dataframe, "work.employeeIdInCompany", "HR")
    target_mask = pd.Series(False, index=dataframe.index)

    if target_email and email_column:
        target_mask = target_mask | dataframe[email_column].map(normalize).eq(normalize(target_email))

    if target_employee_id and employee_id_column:
        target_mask = target_mask | dataframe[employee_id_column].map(normalize).eq(normalize(target_employee_id))

    return dataframe[target_mask].copy()


def build_coverage_dataframe(dataframe: pd.DataFrame, metadata: list[dict]) -> pd.DataFrame:
    rows = []

    for field in metadata:
        field_id = field["id"]
        raw_column = find_column_ending_with(dataframe, field_id, "RAW")
        hr_column = find_column_ending_with(dataframe, field_id, "HR")
        raw_count = int(dataframe[raw_column].notna().sum()) if raw_column else 0
        hr_count = int(dataframe[hr_column].notna().sum()) if hr_column else 0

        rows.append(
            {
                "field_id": field_id,
                "field_name": field.get("name"),
                "category": field.get("categoryDisplayName"),
                "type": field.get("type"),
                "raw_values_returned": raw_count,
                "human_readable_values_returned": hr_count,
                "total_employees": len(dataframe),
                "status": "RETURNED" if max(raw_count, hr_count) > 0 else "NOT RETURNED / NO PERMISSION",
            }
        )

    coverage = pd.DataFrame(rows)
    if coverage.empty:
        return coverage

    return coverage.sort_values(
        by=["status", "category", "field_name"],
        ascending=[True, True, True],
    )


def metadata_column_name(field: dict, human_readable: bool = False) -> str:
    category = field.get("categoryDisplayName") or field.get("category") or "Other"
    visible_name = field.get("name") or field.get("id") or "Unknown"
    field_id = field.get("id", "")
    prefix = "HR" if human_readable else "RAW"
    return f"{prefix} | {category} | {visible_name} | {field_id}"


def get_direct_field_value(employee: dict, field_id: str) -> Any:
    slash_key = "/" + field_id.replace(".", "/")

    if slash_key in employee:
        return unwrap_value(employee[slash_key])

    current: Any = employee

    for part in field_id.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)

    return unwrap_value(current)


def get_nested_value(value: Any, field_id: str) -> Any:
    current = value

    for part in field_id.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)

    return unwrap_value(current)


def excel_safe_value(value: Any) -> Any:
    value = unwrap_value(value)

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)

    return str(value)


def drop_empty_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe
    return dataframe.dropna(axis=1, how="all")


def order_priority_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe

    priority_columns = ["HiBob Root ID", "Credential Sources"]

    for field_id in PRIORITY_FIELDS:
        raw_column = find_column_ending_with(dataframe, field_id, "RAW")
        hr_column = find_column_ending_with(dataframe, field_id, "HR")

        if raw_column:
            priority_columns.append(raw_column)
        if hr_column:
            priority_columns.append(hr_column)

    priority_columns = list(dict.fromkeys(column for column in priority_columns if column in dataframe.columns))
    remaining_columns = [column for column in dataframe.columns if column not in priority_columns]
    return dataframe[priority_columns + remaining_columns]


def find_column_ending_with(dataframe: pd.DataFrame, field_id: str, prefix: str) -> str | None:
    expected_ending = f"| {field_id}"

    for column in dataframe.columns:
        if column.startswith(prefix) and column.endswith(expected_ending):
            return column

    return None


def normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()
