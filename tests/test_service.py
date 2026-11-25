from datetime import date
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
import joblib
import numpy as np
import pandas as pd

from forecast.model import MODEL, ROBUST, fit_tree, make_features, panel_digest
from forecast.service import create_app


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=".")
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.path = self.directory / "weekly.csv"
        weeks = pd.date_range("2020-01-06", periods=36, freq="W-MON")
        self.panel = pd.DataFrame({
            "week": list(weeks) * 2,
            "sku": ["10000"] * 36 + ["20000"] * 36,
            "units": list(range(36)) + list(range(100, 136)),
        })
        self.panel.to_csv(self.path, index=False)
        self.week = date(2020, 9, 14).isoformat()

    def write_artifact(self, method, model=None):
        joblib.dump(
            {"schema": 1, "method": method, "model": model, "panel_sha256": panel_digest(self.path)},
            self.directory / "forecaster.joblib",
        )

    def test_active_baseline_contract(self):
        self.write_artifact("four_week_mean")
        with TestClient(create_app(self.directory)) as client:
            self.assertEqual(client.get("/health").json()["status"], "ready")
            catalog = client.get("/v1/catalog").json()
            self.assertEqual(catalog["forecast_week"], self.week)
            self.assertEqual(catalog["skus"], ["10000", "20000"])
            result = client.post("/v1/forecasts", json={
                "forecast_week": self.week, "skus": ["20000", "10000"],
            })
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["model_version"], catalog["model_version"])
            self.assertEqual(result.json()["forecasts"], [
                {"sku": "20000", "units": 133.5},
                {"sku": "10000", "units": 33.5},
            ])

    def test_robust_forecast_uses_the_same_formula_as_evaluation(self):
        self.write_artifact(ROBUST)
        with TestClient(create_app(self.directory)) as client:
            result = client.post("/v1/forecasts", json={
                "forecast_week": self.week, "skus": ["10000", "20000"],
            })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["method"], ROBUST)
        np.testing.assert_allclose(
            [item["units"] for item in result.json()["forecasts"]], [29.675, 129.675]
        )

    def test_validation_rejects_stale_week_duplicate_and_unknown_sku(self):
        self.write_artifact("four_week_mean")
        with TestClient(create_app(self.directory)) as client:
            for week, skus in (("2020-09-07", ["10000"]),
                               (self.week, ["10000", "10000"]),
                               (self.week, ["99999"]),
                               (self.week, ["POST"])):
                with self.subTest(week=week, skus=skus):
                    response = client.post("/v1/forecasts", json={"forecast_week": week, "skus": skus})
                    self.assertEqual(response.status_code, 422)

    def test_mismatched_panel_prevents_startup(self):
        self.write_artifact("four_week_mean")
        with self.path.open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "do not match"):
            with TestClient(create_app(self.directory)):
                self.fail("Service should refuse mismatched inputs")

    def test_serialized_boosted_forecaster_is_usable(self):
        model = fit_tree(make_features(self.panel))
        self.write_artifact(MODEL, model)
        with TestClient(create_app(self.directory)) as client:
            payload = {"forecast_week": self.week, "skus": ["10000", "20000"]}
            first = client.post("/v1/forecasts", json=payload)
            second = client.post("/v1/forecasts", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["method"], MODEL)
        self.assertTrue(all(np.isfinite(row["units"]) and row["units"] >= 0
                            for row in first.json()["forecasts"]))
