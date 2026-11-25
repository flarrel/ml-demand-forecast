"""Convert the UCI Online Retail archive into a weekly unit-sales panel."""

import argparse
from collections import Counter
from datetime import datetime, timedelta
from hashlib import file_digest
from io import BytesIO
import json
import math
from pathlib import Path
import re
from zipfile import ZipFile

import pandas as pd
from openpyxl import load_workbook

SOURCE_SHA256 = "f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b"
HEADERS = ("InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
           "UnitPrice", "CustomerID", "Country")
SKU_PATTERN = re.compile(r"[0-9]{5}[A-Z]{0,2}")
SELECTION_WEEKS = 26
SKU_LIMIT = 25


def monday(day):
    return day - timedelta(days=day.weekday())


def positive_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def build_panel(rows):
    counts = Counter()
    totals = Counter()
    accepted_by_week = Counter()
    first_day = last_day = None

    for invoice, code, _, quantity, timestamp, price, _, _ in rows:
        if not isinstance(timestamp, datetime):
            counts["invalid_date"] += 1
            continue

        day = timestamp.date()
        first_day = min(first_day, day) if first_day else day
        last_day = max(last_day, day) if last_day else day
        sku = str(code).strip().upper()
        invoice = str(invoice).strip().upper() if invoice is not None else ""

        if invoice.startswith("C"):
            counts["cancellation"] += 1
        elif not invoice or not SKU_PATTERN.fullmatch(sku):
            counts["invalid_invoice_or_non_merchandise"] += 1
        elif not positive_number(quantity) or int(quantity) != quantity:
            counts["invalid_or_nonpositive_quantity"] += 1
        elif not positive_number(price):
            counts["invalid_or_nonpositive_price"] += 1
        else:
            week = monday(day)
            totals[week, sku] += int(quantity)
            accepted_by_week[week] += 1

    if first_day is None:
        raise ValueError("Dataset has no valid transaction dates")

    # Drop both boundary weeks because the source may start or end intraweek.
    first_week = monday(first_day) + timedelta(days=7)
    last_week = monday(last_day) - timedelta(days=7)
    weeks = list(pd.date_range(first_week, last_week, freq="W-MON").date)
    if len(weeks) <= SELECTION_WEEKS:
        raise ValueError("Dataset lacks a complete SKU selection and evaluation period")
    selection_end = weeks[SELECTION_WEEKS - 1]

    eligible = Counter()
    for (week, sku), units in totals.items():
        if first_week <= week <= selection_end:
            eligible[sku] += units
    skus = sorted(eligible, key=lambda sku: (-eligible[sku], sku))[:SKU_LIMIT]
    if not skus:
        raise ValueError("No eligible merchandise during SKU selection")

    panel = pd.DataFrame(
        [(week, sku, totals[week, sku]) for week in weeks for sku in skus],
        columns=["week", "sku", "units"],
    )
    complete = set(weeks)
    # Count input rows by disposition, separate from aggregated sales units.
    counts["accepted_complete_weeks"] = sum(accepted_by_week[week] for week in weeks)
    counts["partial_week"] = sum(total for week, total in accepted_by_week.items()
                                 if week not in complete)
    report = {
        "source_rows": sum(counts.values()),
        "row_disposition": dict(sorted(counts.items())),
        "first_complete_week": first_week.isoformat(),
        "last_complete_week": last_week.isoformat(),
        "sku_selection_through": selection_end.isoformat(),
        "weeks": len(weeks),
        "skus": len(skus),
        "panel_rows": len(panel),
        "panel_units": int(panel["units"].sum()),
        "zero_sales_weeks_by_sku": int(panel["units"].eq(0).sum()),
    }
    return panel, report


def prepare(archive, output):
    with archive.open("rb") as source:
        observed_sha256 = file_digest(source, "sha256").hexdigest()
    if observed_sha256 != SOURCE_SHA256:
        raise ValueError(f"Unexpected source SHA-256: {observed_sha256}")

    with ZipFile(archive) as source:
        workbook = load_workbook(
            BytesIO(source.read("Online Retail.xlsx")), read_only=True, data_only=True
        )
        try:
            rows = workbook.worksheets[0].iter_rows(values_only=True)
            if next(rows, None) != HEADERS:
                raise ValueError("Unexpected Online Retail column schema")
            panel, report = build_panel(rows)
        finally:
            workbook.close()

    output.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output / "weekly.csv", index=False)
    (output / "data-report.json").write_text(
        json.dumps({"source_sha256": observed_sha256, **report}, indent=2) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("work/online-retail.zip"))
    parser.add_argument("--output", type=Path, default=Path("work"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive, args.output), indent=2))


if __name__ == "__main__":
    main()
