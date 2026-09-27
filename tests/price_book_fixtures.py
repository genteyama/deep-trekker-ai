from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "excel"


def build_workbook(sheets: dict) -> BytesIO:
    workbook = Workbook()
    first = True
    for sheet_name, rows in sheets.items():
        if first:
            worksheet = workbook.active
            worksheet.title = sheet_name
            first = False
        else:
            worksheet = workbook.create_sheet(sheet_name)
        for row in rows:
            worksheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def valid_price_book() -> BytesIO:
    return build_workbook(
        {
            "MAG": [
                ["Part Number", "Description", "MSRP", "Dealer Price", "Notes"],
                ["9701-MAG-4K", "MAG Utility Crawler 4K", 25000, 15000, "Bare steel surface"],
                ["9735", "MAG accessory", 800, 480, None],
            ],
            "PHOTON": [
                ["SKU", "Description", "MSRP", "Dealer Price", "Notes"],
                ["7851-PHOTON", "PHOTON ROV", 8000, 4800, None],
            ],
            "PipeTrekker": [
                ["Part #", "Description", "MSRP", "Dealer Price", "Notes"],
                ["9680-BASE", "PipeTrekker Base", 40000, 28000, None],
            ],
            "Cygnus": [
                ["Part Number", "Description", "MSRP", "Dealer Price", "Notes"],
                ["5608", "Cygnus Thickness Gauge", 5000, 5000, "NO DEALER DISCOUNT"],
            ],
            "Bundle Pack": [
                ["Part Number", "Description", "MSRP", "Dealer Price", "Notes"],
                ["8459", "Unknown bundle item", 100, 90, None],
            ],
        }
    )


def shifted_columns_price_book() -> BytesIO:
    return build_workbook(
        {
            "MAG": [
                [None, None, None, None, None],
                [None, None, None, None, None],
                [None, None, "Ignore", "Part Number", "Description", "MSRP", "Dealer Price", "Notes"],
                [None, None, "skip", "9701-MAG-4K", "MAG Utility Crawler 4K", 25000, 15000, "Bare steel surface"],
                [None, None, "skip", "9735", "MAG accessory", 800, 480, None],
            ]
        }
    )


def validation_price_book() -> BytesIO:
    return build_workbook(
        {
            "MAG": [
                ["Part Number", "Description", "MSRP", "Dealer Price", "Notes"],
                [None, "Missing SKU crawler", 1000, 600, None],
                ["9701-MAG-4K", "MAG first", 25000, 15000, None],
                ["9701-MAG-4K", "MAG duplicate", 25000, 15000, None],
                ["BAD-MSRP", "Invalid MSRP", "TBD", 100, None],
                ["BAD-DEALER", "Invalid dealer", 200, "ASK", None],
                ["HIGH-DEALER", "Dealer above MSRP", 100, 150, None],
                ["5608", "Cygnus Thickness Gauge", 5000, 5000, "NO DEALER DISCOUNT"],
            ]
        }
    )


def missing_columns_price_book() -> BytesIO:
    return build_workbook(
        {
            "MAG": [
                ["Item Name", "List Amount", "Comment"],
                ["MAG Utility Crawler", 25000, "No SKU column"],
            ]
        }
    )


def previous_master_book() -> BytesIO:
    return build_workbook(
        {
            "MAG": [
                ["Part Number", "Description", "MSRP", "Dealer Price", "Notes"],
                ["9701-MAG-4K", "MAG Utility Crawler old name", 24000, 14400, "Old note"],
                ["9735", "MAG accessory", 800, 480, None],
                ["RETIRED-1", "Removed later", 10, 6, None],
            ],
            "PHOTON": [
                ["SKU", "Description", "MSRP", "Dealer Price", "Notes"],
                ["7851-PHOTON", "PHOTON ROV", 8000, 4800, None],
            ],
        }
    )


def write_fixture_files(directory: Path = FIXTURE_DIR) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "valid_dt40.xlsx": valid_price_book(),
        "shifted_columns.xlsx": shifted_columns_price_book(),
        "validation.xlsx": validation_price_book(),
        "missing_columns.xlsx": missing_columns_price_book(),
        "previous_master.xlsx": previous_master_book(),
    }
    paths = {}
    for name, buffer in files.items():
        path = directory / name
        path.write_bytes(buffer.getvalue())
        paths[name] = path
    return paths
