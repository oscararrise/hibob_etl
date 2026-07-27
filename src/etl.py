import time

from src.config import Settings
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


def run_etl(settings: Settings) -> None:
    metadata_store: dict[str, dict] = {}
    employee_store: dict[str, dict] = {}

    for credential in settings.credentials:
        print(f"Running HiBob extraction with credential: {credential.name}")
        client = HiBobClient(settings, credential)
        metadata = client.get_fields_metadata()
        merge_metadata(metadata_store, metadata)
        field_ids = get_field_ids(metadata)
        batches = list(split_list(field_ids, settings.fields_per_request))

        for batch_number, field_batch in enumerate(batches, start=1):
            print(f"Request {batch_number}/{len(batches)}: {len(field_batch)} fields")
            employees = client.fetch_employee_batch(field_batch)
            merge_employees(employee_store, employees, credential.name)

            if batch_number < len(batches):
                time.sleep(settings.seconds_between_requests)

    metadata = list(metadata_store.values())
    employees = list(employee_store.values())
    employees_df = build_employees_dataframe(employees, metadata)
    metadata_df = metadata_to_dataframe(metadata)
    target_df = build_target_dataframe(employees_df, settings.target_email, settings.target_employee_id)
    coverage_df = build_coverage_dataframe(employees_df, metadata)

    write_raw_json(settings.raw_json_file, employees)
    write_excel(settings.output_file, employees_df, metadata_df, target_df, coverage_df)

    print("ETL finished")
    print(f"Employees: {len(employees_df)}")
    print(f"Columns: {len(employees_df.columns)}")
    print(f"Excel: {settings.output_file.resolve()}")
    print(f"Raw JSON: {settings.raw_json_file.resolve()}")


def merge_metadata(metadata_store: dict[str, dict], metadata: list[dict]) -> None:
    for field in metadata:
        field_id = field.get("id")
        if field_id and field_id not in metadata_store:
            metadata_store[field_id] = field
