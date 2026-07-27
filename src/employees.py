from typing import Any


def extract_root_id(employee: dict) -> str | None:
    slash_value = employee.get("/root/id")

    if isinstance(slash_value, dict):
        slash_value = slash_value.get("value")

    if slash_value not in (None, ""):
        return str(slash_value)

    if employee.get("id") not in (None, ""):
        return str(employee["id"])

    root = employee.get("root")

    if isinstance(root, dict) and root.get("id") not in (None, ""):
        return str(root["id"])

    return None


def merge_employees(employee_store: dict[str, dict], employees: list[dict], credential_name: str) -> None:
    for position, employee in enumerate(employees):
        root_id = extract_root_id(employee)

        if root_id is None:
            root_id = f"unknown_{credential_name}_{position}_{len(employee_store)}"

        if root_id not in employee_store:
            employee_store[root_id] = {"_credential_sources": []}

        sources = employee_store[root_id].setdefault("_credential_sources", [])
        if credential_name not in sources:
            sources.append(credential_name)

        merge_nested_dict(employee_store[root_id], employee)


def merge_nested_dict(destination: dict, source: dict) -> dict:
    for key, value in source.items():
        if key in destination and isinstance(destination[key], dict) and isinstance(value, dict):
            merge_nested_dict(destination[key], value)
        else:
            destination[key] = value

    return destination


def unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value and len(value) == 1:
        return value["value"]
    return value
