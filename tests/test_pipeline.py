import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_pipeline.pipeline import (
    PipelineError,
    add_features,
    parse_alpha_vantage_csv,
    read_existing_raw,
    render_csv,
    run,
)


SAMPLE = """timestamp,open,high,low,close,volume
2026-08-14,100.00,104.00,99.00,103.00,1200
2026-08-13,98.00,101.00,97.00,100.00,1000
"""


class PipelineTests(unittest.TestCase):
    def test_parse_sorts_rows_and_validates_ohlc(self):
        rows = parse_alpha_vantage_csv(SAMPLE, "TEST")
        self.assertEqual([row["date"] for row in rows], ["2026-08-13", "2026-08-14"])
        self.assertEqual(rows[-1]["adjusted_close"], 103.0)

    def test_features_are_computed_without_future_data(self):
        rows = parse_alpha_vantage_csv(SAMPLE, "TEST")
        featured = add_features(rows)
        self.assertIsNone(featured[0]["daily_return"])
        self.assertAlmostEqual(featured[1]["daily_return"], 0.03)
        self.assertAlmostEqual(featured[1]["range_pct"], 5 / 103)

    def test_rendered_csv_has_stable_schema(self):
        rendered = render_csv(add_features(parse_alpha_vantage_csv(SAMPLE, "TEST")))
        rows = list(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(rows[0]["symbol"], "TEST")
        self.assertIn("volatility_20d", rows[0])

    def test_api_error_json_is_rejected(self):
        with self.assertRaises(PipelineError):
            parse_alpha_vantage_csv('{"Note":"rate limit"}', "TEST")

    def test_compact_updates_accumulate_history_and_then_noop(self):
        older = parse_alpha_vantage_csv(
            "timestamp,open,high,low,close,volume\n2026-08-12,97,99,96,98,900\n",
            "TEST",
        )
        newer = parse_alpha_vantage_csv(SAMPLE, "TEST")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("market_pipeline.pipeline.fetch_symbol", return_value=older):
                self.assertTrue(run(["TEST"], "key", root, request_delay=0))
            with patch("market_pipeline.pipeline.fetch_symbol", return_value=newer):
                self.assertTrue(run(["TEST"], "key", root, request_delay=0))
                self.assertFalse(run(["TEST"], "key", root, request_delay=0))
            rows = read_existing_raw(root / "data" / "TEST.csv", "TEST")
            self.assertEqual([row["date"] for row in rows], ["2026-08-12", "2026-08-13", "2026-08-14"])


if __name__ == "__main__":
    unittest.main()
