import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Credential:
    name: str
    service_user_id: str
    service_user_token: str


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


def load_settings() -> Settings:
    load_dotenv()

    credentials = load_credentials()

    return Settings(
        base_url=get_env("HIBOB_BASE_URL", "https://api.hibob.com/v1"),
        credentials=credentials,
        output_file=Path(get_env("OUTPUT_FILE", "output/hibob_employees.xlsx")),
        raw_json_file=Path(get_env("RAW_JSON_FILE", "output/hibob_employees_raw.json")),
        fields_per_request=get_int("FIELDS_PER_REQUEST", 100),
        show_inactive=get_bool("SHOW_INACTIVE", True),
        human_readable=get_env("HUMAN_READABLE", "APPEND"),
        request_timeout=get_int("REQUEST_TIMEOUT", 300),
        seconds_between_requests=get_int("SECONDS_BETWEEN_REQUESTS", 2),
        target_email=get_optional_env("TARGET_EMAIL"),
        target_employee_id=get_optional_env("TARGET_EMPLOYEE_ID"),
    )


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


def get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if not value or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
