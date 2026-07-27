ESSENTIAL_FIELDS = [
    "root.id",
    "root.email",
    "root.firstName",
    "root.surname",
    "root.fullName",
    "root.displayName",
    "work.employeeIdInCompany",
]

PRIORITY_FIELDS = [
    "root.id",
    "root.email",
    "root.firstName",
    "root.surname",
    "root.fullName",
    "root.displayName",
    "work.employeeIdInCompany",
    "work.title",
    "work.department",
    "work.site",
    "work.reportsTo.email",
]


def get_field_ids(metadata: list[dict]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for field_id in ESSENTIAL_FIELDS:
        add_field_id(result, seen, field_id)

    for field in metadata:
        add_field_id(result, seen, str(field["id"]))

    return result


def add_field_id(result: list[str], seen: set[str], field_id: str) -> None:
    if field_id not in seen:
        seen.add(field_id)
        result.append(field_id)


def split_list(items: list[str], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
