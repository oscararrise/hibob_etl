import hashlib
import json
import logging
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Sequence
from uuid import UUID

import pandas as pd

from src.config import PostgresSettings

LOGGER = logging.getLogger(__name__)
FIELD_COLUMN_PATTERN = re.compile(r"^(RAW|HR)\s*\|.*\|\s*([^|]+)\s*$", re.IGNORECASE)
POSTGRES_IDENTIFIER_LIMIT = 63
AUDIT_COLUMNS = {"created_at", "updated_at"}


@dataclass(frozen=True)
class PreparedDataframe:
    dataframe: pd.DataFrame
    source_rows: int
    skipped_missing_key: int
    skipped_duplicate_keys: int
    key_column: str
    column_mapping: dict[str, str]


@dataclass(frozen=True)
class DataLoadResult:
    source_rows: int
    valid_rows: int
    inserted_rows: int
    updated_rows: int
    skipped_missing_key: int
    skipped_duplicate_keys: int
    batches: int


def upsert_dataframe(settings: PostgresSettings, dataframe: pd.DataFrame, run_id: UUID) -> DataLoadResult:
    if not settings.enabled:
        raise ValueError("PostgreSQL loading is disabled")

    prepared = prepare_dataframe(dataframe, settings.upsert_key)
    connection = connect_with_retry(settings)
    lock_acquired = False

    try:
        ensure_schema_and_audit_table(connection, settings)
        record_run_start(connection, settings, run_id, prepared.source_rows)
        connection.commit()

        lock_acquired = acquire_advisory_lock(connection, settings)
        if not lock_acquired:
            raise RuntimeError(f"Another ETL execution is already loading {settings.schema}.{settings.table}")

        ensure_target_table(connection, settings, prepared)
        existing_keys = fetch_existing_keys(
            connection,
            settings,
            prepared.key_column,
            prepared.dataframe[prepared.key_column].tolist(),
        )
        incoming_keys = set(prepared.dataframe[prepared.key_column].tolist())
        batches = execute_upsert_batches(connection, settings, prepared)

        result = DataLoadResult(
            source_rows=prepared.source_rows,
            valid_rows=len(prepared.dataframe),
            inserted_rows=len(incoming_keys - existing_keys),
            updated_rows=len(incoming_keys & existing_keys),
            skipped_missing_key=prepared.skipped_missing_key,
            skipped_duplicate_keys=prepared.skipped_duplicate_keys,
            batches=batches,
        )
        record_run_success(connection, settings, run_id, result)
        connection.commit()
        return result
    except Exception as exc:
        connection.rollback()
        try:
            record_run_failure(connection, settings, run_id, prepared, str(exc))
            connection.commit()
        except Exception:
            connection.rollback()
            LOGGER.exception("Could not persist failed ETL run in PostgreSQL")
        raise
    finally:
        if lock_acquired:
            try:
                release_advisory_lock(connection, settings)
                connection.commit()
            except Exception:
                connection.rollback()
                LOGGER.exception("Could not release PostgreSQL advisory lock cleanly")
        connection.close()


def prepare_dataframe(dataframe: pd.DataFrame, configured_upsert_key: str) -> PreparedDataframe:
    source_rows = len(dataframe)
    if dataframe.empty and len(dataframe.columns) == 0:
        raise ValueError("The employee dataframe has no rows or columns to load")

    original_columns = [str(column) for column in dataframe.columns]
    if len(original_columns) != len(set(original_columns)):
        raise ValueError("The employee dataframe contains duplicate column names")

    column_mapping = build_column_mapping(original_columns)
    key_column = resolve_upsert_key(configured_upsert_key, column_mapping)
    prepared = dataframe.copy()
    prepared.columns = [column_mapping[column] for column in original_columns]

    for column in prepared.columns:
        prepared[column] = prepared[column].map(normalize_postgres_value)

    missing_key_mask = prepared[key_column].isna() | prepared[key_column].eq("")
    skipped_missing_key = int(missing_key_mask.sum())
    prepared = prepared.loc[~missing_key_mask].copy()

    duplicate_mask = prepared.duplicated(subset=[key_column], keep="last")
    skipped_duplicate_keys = int(duplicate_mask.sum())
    prepared = prepared.loc[~duplicate_mask].reset_index(drop=True)

    return PreparedDataframe(
        dataframe=prepared,
        source_rows=source_rows,
        skipped_missing_key=skipped_missing_key,
        skipped_duplicate_keys=skipped_duplicate_keys,
        key_column=key_column,
        column_mapping=column_mapping,
    )


def build_column_mapping(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used = set(AUDIT_COLUMNS)

    for original in columns:
        candidate = sanitize_identifier(derive_stable_column_name(original))
        if candidate in used:
            candidate = with_identifier_suffix(candidate, hashlib.sha1(original.encode("utf-8")).hexdigest()[:8])
        counter = 2
        while candidate in used:
            candidate = with_identifier_suffix(candidate, str(counter))
            counter += 1
        mapping[original] = candidate
        used.add(candidate)

    return mapping


def derive_stable_column_name(column_name: str) -> str:
    normalized = column_name.strip()
    special_names = {
        "HiBob Root ID": "hibob_root_id",
        "Credential Sources": "credential_sources",
    }
    if normalized in special_names:
        return special_names[normalized]

    match = FIELD_COLUMN_PATTERN.match(normalized)
    if match:
        return f"{match.group(1).lower()}_{match.group(2).strip()}"
    return normalized


def sanitize_identifier(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    identifier = re.sub(r"[^a-z0-9_]+", "_", ascii_value)
    identifier = re.sub(r"_+", "_", identifier).strip("_") or "column"
    if identifier[0].isdigit():
        identifier = f"column_{identifier}"
    if len(identifier) > POSTGRES_IDENTIFIER_LIMIT:
        identifier = with_identifier_suffix(identifier, hashlib.sha1(value.encode("utf-8")).hexdigest()[:8])
    return identifier


def with_identifier_suffix(identifier: str, suffix: str) -> str:
    maximum_base_length = POSTGRES_IDENTIFIER_LIMIT - len(suffix) - 1
    return f"{identifier[:maximum_base_length].rstrip('_')}_{suffix}"


def resolve_upsert_key(configured_key: str, mapping: dict[str, str]) -> str:
    configured_key = configured_key.strip()
    if configured_key in mapping:
        return mapping[configured_key]
    if configured_key in mapping.values():
        return configured_key

    derived = sanitize_identifier(derive_stable_column_name(configured_key))
    if derived in mapping.values():
        return derived

    available = ", ".join(list(mapping.keys())[:10])
    raise ValueError(
        f"POSTGRES_UPSERT_KEY '{configured_key}' was not found in the dataframe. "
        f"Available columns include: {available}"
    )


def normalize_postgres_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dict, list, tuple, set)):
        serializable = list(value) if isinstance(value, set) else value
        return json.dumps(serializable, ensure_ascii=False, default=str, sort_keys=True)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    normalized = str(value).replace("\x00", "").strip()
    return normalized or None


def connect_with_retry(settings: PostgresSettings):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError('Install requirements.txt to enable PostgreSQL support') from exc

    last_error: Exception | None = None
    for attempt in range(1, settings.max_retries + 1):
        try:
            connection = psycopg.connect(
                host=settings.host,
                port=settings.port,
                dbname=settings.database,
                user=settings.user,
                password=settings.password,
                connect_timeout=settings.connect_timeout,
                sslmode=settings.sslmode,
                application_name=settings.application_name,
            )
            LOGGER.info(
                "PostgreSQL connection established host=%s port=%s database=%s",
                settings.host,
                settings.port,
                settings.database,
            )
            return connection
        except psycopg.OperationalError as exc:
            last_error = exc
            LOGGER.warning(
                "PostgreSQL connection attempt %s/%s failed: %s",
                attempt,
                settings.max_retries,
                exc,
            )
            if attempt < settings.max_retries and settings.retry_seconds > 0:
                time.sleep(settings.retry_seconds * attempt)

    raise RuntimeError(f"Could not connect to PostgreSQL after {settings.max_retries} attempts") from last_error


def ensure_schema_and_audit_table(connection, settings: PostgresSettings) -> None:
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(settings.schema)))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.etl_run_history (
                    run_id UUID PRIMARY KEY,
                    target_table TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMPTZ,
                    status TEXT NOT NULL,
                    source_rows INTEGER NOT NULL DEFAULT 0,
                    valid_rows INTEGER NOT NULL DEFAULT 0,
                    inserted_rows INTEGER NOT NULL DEFAULT 0,
                    updated_rows INTEGER NOT NULL DEFAULT 0,
                    skipped_missing_key INTEGER NOT NULL DEFAULT 0,
                    skipped_duplicate_keys INTEGER NOT NULL DEFAULT 0,
                    batches INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT
                )
                """
            ).format(sql.Identifier(settings.schema))
        )
    LOGGER.info("PostgreSQL schema and audit table verified schema=%s", settings.schema)


def ensure_target_table(connection, settings: PostgresSettings, prepared: PreparedDataframe) -> None:
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {}.{} ({} TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            ).format(
                sql.Identifier(settings.schema),
                sql.Identifier(settings.table),
                sql.Identifier(prepared.key_column),
            )
        )
        for column in prepared.dataframe.columns:
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS {} TEXT").format(
                    sql.Identifier(settings.schema),
                    sql.Identifier(settings.table),
                    sql.Identifier(column),
                )
            )

        cursor.execute(
            sql.SQL(
                "SELECT {}, COUNT(*) FROM {}.{} WHERE {} IS NOT NULL GROUP BY {} HAVING COUNT(*) > 1 LIMIT 5"
            ).format(
                sql.Identifier(prepared.key_column),
                sql.Identifier(settings.schema),
                sql.Identifier(settings.table),
                sql.Identifier(prepared.key_column),
                sql.Identifier(prepared.key_column),
            )
        )
        duplicates = cursor.fetchall()
        if duplicates:
            sample = ", ".join(str(row[0]) for row in duplicates)
            raise RuntimeError(
                f"Existing table contains duplicate values for {prepared.key_column}. Sample keys: {sample}"
            )

        index_name = sanitize_identifier(f"ux_{settings.table}_{prepared.key_column}")
        cursor.execute(
            sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                sql.Identifier(index_name),
                sql.Identifier(settings.schema),
                sql.Identifier(settings.table),
                sql.Identifier(prepared.key_column),
            )
        )
    LOGGER.info(
        "PostgreSQL target table verified target=%s.%s columns=%s",
        settings.schema,
        settings.table,
        len(prepared.dataframe.columns),
    )


def fetch_existing_keys(
    connection,
    settings: PostgresSettings,
    key_column: str,
    keys: list[str],
) -> set[str]:
    from psycopg import sql

    existing: set[str] = set()
    query = sql.SQL("SELECT {} FROM {}.{} WHERE {} = ANY(%s::text[])").format(
        sql.Identifier(key_column),
        sql.Identifier(settings.schema),
        sql.Identifier(settings.table),
        sql.Identifier(key_column),
    )
    with connection.cursor() as cursor:
        for batch in chunked(keys, settings.batch_size):
            cursor.execute(query, (batch,))
            existing.update(str(row[0]) for row in cursor.fetchall())
    return existing


def execute_upsert_batches(connection, settings: PostgresSettings, prepared: PreparedDataframe) -> int:
    from psycopg import sql

    columns = list(prepared.dataframe.columns)
    assignments = [
        sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
        for column in columns
        if column != prepared.key_column
    ]
    assignments.append(sql.SQL("updated_at = NOW()"))
    query = sql.SQL(
        "INSERT INTO {}.{} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}"
    ).format(
        sql.Identifier(settings.schema),
        sql.Identifier(settings.table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        sql.Identifier(prepared.key_column),
        sql.SQL(", ").join(assignments),
    )

    rows = list(prepared.dataframe.itertuples(index=False, name=None))
    batches = list(chunked(rows, settings.batch_size))
    with connection.cursor() as cursor:
        for batch_number, batch in enumerate(batches, start=1):
            cursor.executemany(query, batch)
            LOGGER.info(
                "PostgreSQL upsert batch completed batch=%s/%s rows=%s",
                batch_number,
                len(batches),
                len(batch),
            )
    return len(batches)


def acquire_advisory_lock(connection, settings: PostgresSettings) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"{settings.schema}.{settings.table}",))
        return bool(cursor.fetchone()[0])


def release_advisory_lock(connection, settings: PostgresSettings) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"{settings.schema}.{settings.table}",))


def record_run_start(connection, settings: PostgresSettings, run_id: UUID, source_rows: int) -> None:
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {}.etl_run_history (run_id, target_table, status, source_rows)
                VALUES (%s, %s, 'RUNNING', %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    target_table = EXCLUDED.target_table,
                    status = 'RUNNING',
                    source_rows = EXCLUDED.source_rows,
                    started_at = NOW(),
                    finished_at = NULL,
                    error_message = NULL
                """
            ).format(sql.Identifier(settings.schema)),
            (run_id, f"{settings.schema}.{settings.table}", source_rows),
        )


def record_run_success(connection, settings: PostgresSettings, run_id: UUID, result: DataLoadResult) -> None:
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                UPDATE {}.etl_run_history SET
                    finished_at = NOW(), status = 'SUCCESS', source_rows = %s,
                    valid_rows = %s, inserted_rows = %s, updated_rows = %s,
                    skipped_missing_key = %s, skipped_duplicate_keys = %s,
                    batches = %s, error_message = NULL
                WHERE run_id = %s
                """
            ).format(sql.Identifier(settings.schema)),
            (
                result.source_rows,
                result.valid_rows,
                result.inserted_rows,
                result.updated_rows,
                result.skipped_missing_key,
                result.skipped_duplicate_keys,
                result.batches,
                run_id,
            ),
        )


def record_run_failure(
    connection,
    settings: PostgresSettings,
    run_id: UUID,
    prepared: PreparedDataframe,
    error_message: str,
) -> None:
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                UPDATE {}.etl_run_history SET
                    finished_at = NOW(), status = 'FAILED', valid_rows = %s,
                    skipped_missing_key = %s, skipped_duplicate_keys = %s,
                    error_message = %s
                WHERE run_id = %s
                """
            ).format(sql.Identifier(settings.schema)),
            (
                len(prepared.dataframe),
                prepared.skipped_missing_key,
                prepared.skipped_duplicate_keys,
                error_message[:4000],
                run_id,
            ),
        )


def chunked(items: Sequence[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(items), size):
        yield list(items[index : index + size])
