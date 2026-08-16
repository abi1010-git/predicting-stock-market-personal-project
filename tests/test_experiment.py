import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from market_ml.experiment import (
    FEATURE_COLUMNS,
    ExperimentConfig,
    backtest_non_overlapping,
    build_model_frame,
    run_experiment,
)


def sample_market_data(rows: int = 280) -> pd.DataFrame:
    index = np.arange(rows)
    close = 100 + index * 0.08 + np.sin(index / 4) * 2
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-02", periods=rows),
            "open": close * 0.998,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000 + (index % 30) * 10_000,
        }
    )


class ExperimentTests(unittest.TestCase):
    def test_target_is_exactly_five_sessions_forward(self):
        source = sample_market_data(80)
        frame = build_model_frame(source)
        first = frame.iloc[0]
        source_index = source.index[source["date"] == first["date"]][0]
        expected = source.iloc[source_index + 5]["close"] / source.iloc[source_index]["close"] - 1
        self.assertAlmostEqual(first["forward_return_5d"], expected)
        self.assertEqual(first["target_up_5d"], int(expected > 0))

    def test_feature_frame_has_no_missing_or_future_tail_labels(self):
        source = sample_market_data(80)
        frame = build_model_frame(source)
        self.assertFalse(frame[list(FEATURE_COLUMNS)].isna().any().any())
        self.assertLessEqual(frame["date"].max(), source.iloc[-6]["date"])

    def test_non_overlapping_backtest_samples_every_fifth_row(self):
        predictions = pd.DataFrame(
            {
                "date": pd.bdate_range("2025-01-02", periods=12),
                "probability_up": [0.6] * 12,
                "forward_return_5d": [0.01] * 12,
            }
        )
        result = backtest_non_overlapping(predictions, 0.55, 5)
        self.assertEqual(result["periods"], 3)
        self.assertEqual(result["trades"], 1)

    def test_insufficient_history_writes_honest_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "SPY.csv"
            output = root / "models"
            sample_market_data(100).to_csv(data_path, index=False)
            changed = run_experiment(data_path, output, ExperimentConfig(minimum_model_rows=200))
            self.assertTrue(changed)
            report = (output / "five_day_evaluation.json").read_text(encoding="utf-8")
            self.assertIn('"status": "insufficient_data"', report)


if __name__ == "__main__":
    unittest.main()

