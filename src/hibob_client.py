import time
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from src.config import Credential, Settings


class HiBobClient:
    def __init__(self, settings: Settings, credential: Credential) -> None:
        self.settings = settings
        self.credential = credential
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(
            credential.service_user_id,
            credential.service_user_token,
        )
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def get_fields_metadata(self) -> list[dict]:
        response = self.request_json("GET", f"{self.settings.base_url}/company/people/fields")

        if isinstance(response, list):
            fields = response
        elif isinstance(response, dict):
            fields = response.get("fields", [])
        else:
            raise RuntimeError("HiBob returned unexpected fields metadata")

        return [field for field in fields if isinstance(field, dict) and field.get("id")]

    def fetch_employee_batch(self, fields: list[str]) -> list[dict]:
        payload = {
            "showInactive": self.settings.show_inactive,
            "humanReadable": self.settings.human_readable,
            "fields": fields,
        }
        response = self.request_json("POST", f"{self.settings.base_url}/people/search", payload=payload)
        employees = response.get("employees", [])

        if not isinstance(employees, list):
            raise RuntimeError("HiBob did not return a valid employees list")

        return employees

    def request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        max_retries: int = 5,
    ) -> Any:
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=payload,
                    timeout=self.settings.request_timeout,
                )
            except requests.RequestException as error:
                if attempt == max_retries:
                    raise RuntimeError(f"Could not connect to HiBob: {error}") from error
                time.sleep(attempt * 5)
                continue

            if response.status_code == 429:
                time.sleep(self.get_retry_delay(response, attempt))
                continue

            if response.status_code >= 500:
                if attempt == max_retries:
                    raise RuntimeError(f"HiBob HTTP {response.status_code}: {response.text[:2000]}")
                time.sleep(attempt * 10)
                continue

            if not response.ok:
                raise RuntimeError(f"HiBob HTTP {response.status_code}: {response.text[:5000]}")

            try:
                return response.json()
            except ValueError as error:
                raise RuntimeError(f"HiBob returned invalid JSON: {response.text[:2000]}") from error

        raise RuntimeError("Request could not be completed")

    @staticmethod
    def get_retry_delay(response: requests.Response, attempt: int) -> int:
        retry_after = response.headers.get("Retry-After")
        try:
            return int(retry_after) if retry_after else attempt * 15
        except ValueError:
            return attempt * 15
