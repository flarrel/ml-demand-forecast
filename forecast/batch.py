"""Fetch the forecasts required by a local replenishment batch."""

import argparse
from datetime import date
import json
import math
import sys

import httpx


def request_forecasts(base_url, forecast_week, skus):
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/v1/forecasts",
            json={"forecast_week": forecast_week.isoformat(), "skus": skus},
            timeout=5,
            trust_env=False,
        )
    except httpx.RequestError as error:
        raise RuntimeError(f"Forecast service unavailable: {error}") from error
    if response.is_error:
        raise RuntimeError(f"Forecast service returned HTTP {response.status_code}: {response.text}")
    try:
        body = response.json()
        forecast_items = body["forecasts"]
        if (
            body["forecast_week"] != forecast_week.isoformat()
            or not body["model_version"]
            or [item["sku"] for item in forecast_items] != skus
            or any(not math.isfinite(item["units"]) or item["units"] < 0
                   for item in forecast_items)
        ):
            raise ValueError("Unexpected forecast result")
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Forecast service returned an invalid response") from error
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--week", required=True, type=date.fromisoformat)
    parser.add_argument("skus", nargs="+")
    args = parser.parse_args()
    try:
        body = request_forecasts(args.base_url, args.week, args.skus)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
