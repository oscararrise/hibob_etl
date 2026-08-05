import pandas as pd

from src.database import (
    build_column_mapping,
    normalize_postgres_value,
    prepare_dataframe,
    sanitize_identifier,
)


def test_build_column_mapping_uses_stable_hibob_field_ids() -> None:
    mapping = build_column_mapping(
        [
            "HiBob Root ID",
            "Credential Sources",
            "RAW | Root | Email | root.email",
            "HR | Work | Department | work.department",
        ]
    )

    assert mapping["HiBob Root ID"] == "hibob_root_id"
    assert mapping["Credential Sources"] == "credential_sources"
    assert mapping["RAW | Root | Email | root.email"] == "raw_root_email"
    assert mapping["HR | Work | Department | work.department"] == "hr_work_department"


def test_prepare_dataframe_removes_missing_and_duplicate_keys() -> None:
    dataframe = pd.DataFrame(
        {
            "HiBob Root ID": ["1", None, "1", "2"],
            "RAW | Root | Email | root.email": [
                "old@example.com",
                "x",
                "new@example.com",
                "two@example.com",
            ],
        }
    )

    result = prepare_dataframe(dataframe, "HiBob Root ID")

    assert result.source_rows == 4
    assert result.skipped_missing_key == 1
    assert result.skipped_duplicate_keys == 1
    assert result.dataframe["hibob_root_id"].tolist() == ["1", "2"]
    assert result.dataframe["raw_root_email"].tolist() == [
        "new@example.com",
        "two@example.com",
    ]


def test_prepare_dataframe_accepts_sanitized_upsert_key() -> None:
    dataframe = pd.DataFrame({"HiBob Root ID": ["1"]})
    result = prepare_dataframe(dataframe, "hibob_root_id")
    assert result.key_column == "hibob_root_id"


def test_normalize_postgres_value_removes_null_bytes_and_serializes_json() -> None:
    assert normalize_postgres_value("a\x00b") == "ab"
    assert normalize_postgres_value({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'
    assert normalize_postgres_value(float("nan")) is None


def test_sanitize_identifier_respects_postgresql_limit() -> None:
    result = sanitize_identifier("A" * 100)
    assert len(result) <= 63
