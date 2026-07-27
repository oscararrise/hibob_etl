import json
from pathlib import Path

import pandas as pd


def write_raw_json(path: Path, employees: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "totalEmployees": len(employees),
                "employees": employees,
            },
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


def write_excel(
    path: Path,
    employees_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    target_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(
        path,
        engine="xlsxwriter",
        engine_kwargs={"options": {"strings_to_urls": False}},
    ) as writer:
        write_sheet(writer, employees_df, "Empleados")
        write_sheet(writer, metadata_df, "Metadata campos")
        write_sheet(writer, target_df, "Empleado objetivo")
        write_sheet(writer, coverage_df, "Cobertura campos")
        format_workbook(writer, [employees_df, metadata_df, target_df, coverage_df])


def write_sheet(writer: pd.ExcelWriter, dataframe: pd.DataFrame, sheet_name: str) -> None:
    dataframe.to_excel(writer, sheet_name=sheet_name, index=False)


def format_workbook(writer: pd.ExcelWriter, dataframes: list[pd.DataFrame]) -> None:
    workbook = writer.book
    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "white",
            "bg_color": "#1F4E78",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
        }
    )
    text_format = workbook.add_format({"valign": "top"})

    for sheet_name, dataframe in zip(writer.sheets.keys(), dataframes):
        worksheet = writer.sheets[sheet_name]
        worksheet.freeze_panes(1, 1)

        if not dataframe.empty and len(dataframe.columns) > 0:
            worksheet.autofilter(0, 0, max(len(dataframe), 1), len(dataframe.columns) - 1)

        worksheet.set_row(0, 45, header_format)

        for column_number, column_name in enumerate(dataframe.columns):
            worksheet.write(0, column_number, column_name, header_format)
            worksheet.set_column(column_number, column_number, get_column_width(dataframe, column_name), text_format)


def get_column_width(dataframe: pd.DataFrame, column_name: str) -> int:
    sample_lengths = dataframe[column_name].dropna().astype(str).head(100).map(len).tolist()
    maximum_length = max([len(str(column_name))] + sample_lengths)
    return min(max(maximum_length + 2, 12), 35)
