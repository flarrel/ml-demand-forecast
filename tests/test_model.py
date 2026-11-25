import unittest

import numpy as np
import pandas as pd

from forecast.model import FEATURES, ROBUST, make_features, scores, use_candidate, validate_confirmation


class ModelTests(unittest.TestCase):
    def test_forecast_features_exclude_current_and_future_target(self):
        weeks = pd.date_range("2020-01-06", periods=16, freq="W-MON")
        panel = pd.DataFrame({
            "week": list(weeks) * 2,
            "sku": ["10000"] * 16 + ["20000"] * 16,
            "units": list(range(16)) + list(range(100, 116)),
        })
        cutoff = weeks[12]
        original = make_features(panel).query("week == @cutoff")
        panel.loc[panel["week"] >= cutoff, "units"] = 9999
        changed = make_features(panel).query("week == @cutoff")
        pd.testing.assert_frame_equal(original[[*FEATURES, ROBUST]], changed[[*FEATURES, ROBUST]])
        self.assertEqual(original["lag_1"].tolist(), [11, 111])
        self.assertEqual(original["mean_4"].tolist(), [9.5, 109.5])

    def test_confirmation_requires_disjoint_products_and_matching_dates(self):
        week = pd.Timestamp("2020-01-06")
        primary = pd.DataFrame({"week": [week], "sku": ["10000"]})
        with self.assertRaisesRegex(ValueError, "must be disjoint"):
            validate_confirmation(primary, primary)
        with self.assertRaisesRegex(ValueError, "must span the same weeks"):
            validate_confirmation(primary, primary.assign(
                week=week + pd.Timedelta(weeks=1), sku="20000"
            ))

    def test_release_gate(self):
        self.assertTrue(use_candidate(100, 95))
        self.assertFalse(use_candidate(100, 95.01))
        self.assertFalse(use_candidate(0, 0))

    def test_zero_volume_uses_mae_and_undefined_wape(self):
        frame = pd.DataFrame({
            "units": [0, 0],
            "last_week": [2, 0],
            "four_week_mean": [0, 2],
            "gradient_boosting": [0, 1],
            ROBUST: [0, 1],
        })
        result = scores(frame)
        self.assertIsNone(result["gradient_boosting"]["wape"])
        np.testing.assert_equal(result["gradient_boosting"]["mae"], 0.5)
