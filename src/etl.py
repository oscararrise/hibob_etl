import logging
import time
from uuid import uuid4

from src.config import Settings
from src.database import upsert_dataframe
from src.employees import merge_employees
from src.exporters import write_excel, write_raw_json
from src.fields import get_field_ids, split_list
from src.hibob_client import HiBobClient
from src.transform import (
    build_coverage_dataframe,
    build_employees_dataframe,
    build_target_dataframe,
    metadata_to_dataframe,
)

LOGGER = logging.getLogger(__name__)


def run_etl(settings: Settings) -> None:
    started_at = time.monotonic()
    run_id = uuid4()
    metadata_store: dict[str, dict] = {}
    employee_store: dict[str, dict] = {}

    LOGGER.info("HiBob ETL started run_id=%s", run_id)

    try:
        for credential in settings.credentials:
            LOGGER.info("HiBob extraction started credential=%s", credential.name)
            client = HiBobClient(settings, credential)
            metadata = client.get_fields_metadata()
            merge_metadata(metadata_store, metadata)
            field_ids = get_field_ids(metadata)
            batches = list(split_list(field_ids, settings.fields_per_request))

            for batch_number, field_batch in enumerate(batches, start=1):
                LOGGER.info(
                    "HiBob request credential=%s batch=%s/%s fields=%s",
                    credential.name,
                    batch_number,
                    len(batches),
                    len(field_batch),
                )
                employees = client.fetch_employee_batch(field_batch)
                merge_employees(employee_store, employees, credential.name)

                if batch_number < len(batches):
                    time.sleep(settings.seconds_between_requests)

        metadata = list(metadata_store.values())
        employees = list(employee_store.values())
        employees_df = build_employees_dataframe(employees, metadata)
        metadata_df = metadata_to_dataframe(metadata)
        target_df = build_target_dataframe(
            employees_df,
            settings.target_email,
            settings.target_employee_id,
        )
        coverage_df = build_coverage_dataframe(employees_df, metadata)

        LOGGER.info(
            "HiBob dataframe built employees=%s columns=%s",
            len(employees_df),
            len(employees_df.columns),
        )

        write_raw_json(settings.raw_json_file, employees)
        write_excel(
            settings.output_file,
            employees_df,
            metadata_df,
            target_df,
            coverage_df,
        )
        LOGGER.info("Excel export written path=%s", settings.output_file.resolve())
        LOGGER.info("Raw JSON export written path=%s", settings.raw_json_file.resolve())

        if settings.postgres.enabled:
            result = upsert_dataframe(settings.postgres, employees_df, run_id)
            LOGGER.info(
                "PostgreSQL upsert completed target=%s.%s source=%s valid=%s "
                "inserted=%s updated=%s skipped_missing_key=%s "
                "skipped_duplicate_keys=%s batches=%s",
                settings.postgres.schema,
                settings.postgres.table,
                result.source_rows,
                result.valid_rows,
                result.inserted_rows,
                result.updated_rows,
                result.skipped_missing_key,
                result.skipped_duplicate_keys,
                result.batches,
            )
        else:
            LOGGER.info("PostgreSQL load skipped POSTGRES_ENABLED=false")

        LOGGER.info(
            "HiBob ETL finished run_id=%s duration_seconds=%.2f",
            run_id,
            time.monotonic() - started_at,
        )
    except Exception:
        LOGGER.exception(
            "HiBob ETL failed run_id=%s duration_seconds=%.2f",
            run_id,
            time.monotonic() - started_at,
        )
        raise


def merge_metadata(metadata_store: dict[str, dict], metadata: list[dict]) -> None:
    for field in metadata:
        field_id = field.get("id")
        if field_id and field_id not in metadata_store:
            metadata_store[field_id] = field
