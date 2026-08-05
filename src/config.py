import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Credential:
    name: str
    service_user_id: str
    service_user_token: str


@dataclass(frozen=True)
class PostgresSettings:
    enabled: bool
    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str
    table: str
    upsert_key: str
    batch_size: int
    connect_timeout: int
    max_retries: int
    retry_seconds: int
    sslmode: str
    application_name: str


@dataclass(frozen=True)
class Settings:
    base_url: str
    credentials: list[Credential]
    output_file: Path
    raw_json_file: Path
    fields_per_request: int
    show_inactive: bool
    human_readable: str
    request_timeout: int
    seconds_between_requests: int
    target_email: str | None
    target_employee_id: str | None
    run_timestamp: str
    log_dir: Path
    log_level: str
    postgres: PostgresSettings


def load_settings() -> Settings:
    load_dotenv()

    credentials = load_credentials()
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    postgres = load_postgres_settings()

    return Settings(
        base_url=get_env("HIBOB_BASE_URL", "https://api.hibob.com/v1"),
        credentials=credentials,
        output_file=add_timestamp(Path(get_env("OUTPUT_FILE", "output/hibob_employees.xlsx")), run_timestamp),
        raw_json_file=add_timestamp(Path(get_env("RAW_JSON_FILE", "output/hibob_employees_raw.json")), run_timestamp),
        fields_per_request=get_positive_int("FIELDS_PER_REQUEST", 100),
        show_inactive=get_bool("SHOW_INACTIVE", True),
        human_readable=get_env("HUMAN_READABLE", "APPEND"),
        request_timeout=get_positive_int("REQUEST_TIMEOUT", 300),
        seconds_between_requests=get_non_negative_int("SECONDS_BETWEEN_REQUESTS", 2),
        target_email=get_optional_env("TARGET_EMAIL"),
        target_employee_id=get_optional_env("TARGET_EMPLOYEE_ID"),
        run_timestamp=run_timestamp,
        log_dir=Path(get_env("LOG_DIR", "logs")),
        log_level=get_env("LOG_LEVEL", "INFO").upper(),
        postgres=postgres,
    )


def load_postgres_settings() -> PostgresSettings:
    enabled = get_bool("POSTGRES_ENABLED", False)

    settings = PostgresSettings(
        enabled=enabled,
        host=get_env("POSTGRES_HOST", "127.0.0.1"),
        port=get_positive_int("POSTGRES_PORT", 5432),
        database=get_env("POSTGRES_DB", "arrise_vm_db"),
        user=get_optional_env("POSTGRES_USER") or "",
        password=get_optional_env("POSTGRES_PASSWORD") or "",
        schema=get_env("POSTGRES_SCHEMA", "hibob_etl_daily_scheduled_report"),
        table=get_env("POSTGRES_TABLE", "hibob_employees"),
        upsert_key=get_env("POSTGRES_UPSERT_KEY", "HiBob Root ID"),
        batch_size=get_positive_int("POSTGRES_BATCH_SIZE", 1000),
        connect_timeout=get_positive_int("POSTGRES_CONNECT_TIMEOUT", 15),
        max_retries=get_positive_int("POSTGRES_MAX_RETRIES", 3),
        retry_seconds=get_non_negative_int("POSTGRES_RETRY_SECONDS", 5),
        sslmode=get_env("POSTGRES_SSLMODE", "prefer"),
        application_name=get_env("POSTGRES_APPLICATION_NAME", "hibob_etl"),
    )

    if settings.enabled:
        missing = [
            name
            for name, value in {
                "POSTGRES_USER": settings.user,
                "POSTGRES_PASSWORD": settings.password,
                "POSTGRES_DB": settings.database,
                "POSTGRES_SCHEMA": settings.schema,
                "POSTGRES_TABLE": settings.table,
                "POSTGRES_UPSERT_KEY": settings.upsert_key,
            }.items()
            if not value.strip()
        ]
        if missing:
            raise ValueError(f"Missing required PostgreSQL settings: {', '.join(missing)}")

    return settings


def load_credentials() -> list[Credential]:
    names = get_env("HIBOB_CREDENTIAL_NAMES", "default")
    credentials: list[Credential] = []

    for raw_name in split_csv(names):
        prefix = raw_name.upper().replace("-", "_")
        user_id = os.getenv(f"HIBOB_{prefix}_SERVICE_USER_ID")
        token = os.getenv(f"HIBOB_{prefix}_SERVICE_USER_TOKEN")

        if not user_id or not token:
            if raw_name == "default":
                user_id = os.getenv("HIBOB_SERVICE_USER_ID")
                token = os.getenv("HIBOB_SERVICE_USER_TOKEN")

        if not user_id or not token:
            raise ValueError(f"Missing HiBob credentials for {raw_name}")

        credentials.append(
            Credential(
                name=raw_name,
                service_user_id=user_id,
                service_user_token=token,
            )
        )

    return credentials


def get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def get_optional_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value and value.strip() else default


def get_positive_int(name: str, default: int) -> int:
    value = get_int(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def get_non_negative_int(name: str, default: int) -> int:
    value = get_int(name, default)
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def add_timestamp(path: Path, timestamp: str) -> Path:
    return path.with_name(f"{path.stem}_{timestamp}{path.suffix}")
