from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from forecast.data import build_panel, prepare


class DataTests(unittest.TestCase):
    def test_rows_reconcile_and_future_sku_does_not_enter_panel(self):
        first = datetime(2020, 1, 6)
        rows = [
            (str(i), "10000", None, 2, first + timedelta(weeks=i), 1, None, None)
            for i in range(34)
        ]
        rows.extend([
            ("C99", "10000", None, 10, first + timedelta(weeks=5), 1, None, None),
            ("99", "10000", None, -3, first + timedelta(weeks=5), 1, None, None),
            ("99", "10000", None, 3, first + timedelta(weeks=5), 0, None, None),
            ("99", "POST", None, 3, first + timedelta(weeks=5), 1, None, None),
            ("99", "20000", None, 1000, first + timedelta(weeks=30), 1, None, None),
            ("99", "10000", None, 3, None, 1, None, None),
        ])

        panel, report = build_panel(rows)

        self.assertEqual(report["source_rows"], len(rows))
        self.assertEqual(report["row_disposition"]["partial_week"], 2)
        self.assertEqual(report["row_disposition"]["cancellation"], 1)
        self.assertEqual(report["row_disposition"]["accepted_complete_weeks"], 33)
        self.assertEqual(report["first_complete_week"], "2020-01-13")
        self.assertEqual(report["last_complete_week"], "2020-08-17")
        self.assertEqual(set(panel["sku"]), {"10000"})
        self.assertTrue(panel["units"].eq(2).all())

    def test_confirmation_products_are_ranked_on_selection_weeks(self):
        first = datetime(2020, 1, 6)
        rows = [
            (str(i), sku, None, units, first + timedelta(weeks=i), 1, None, None)
            for i in range(34)
            for sku, units in (("10000", 12), ("20000", 6), ("30000", 2))
        ]
        rows.append(("99", "30000", None, 10000, first + timedelta(weeks=32), 1, None, None))

        with patch("forecast.data.SKU_LIMIT", 1):
            primary, _ = build_panel(rows)
            confirmation, report = build_panel(rows, sku_offset=1)

        self.assertEqual(set(primary["sku"]), {"10000"})
        self.assertEqual(set(confirmation["sku"]), {"20000"})
        self.assertEqual(report["sku_rank_start"], 2)

    def test_digest_rejects_unexpected_archive(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            archive = Path(directory) / "source.zip"
            archive.write_bytes(b"wrong bytes")
            with self.assertRaisesRegex(ValueError, "Unexpected source SHA-256"):
                prepare(archive, Path(directory))
