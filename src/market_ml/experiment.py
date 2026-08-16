from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.base import ClassifierMixin
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


HORIZON = 5
MIN_MODEL_ROWS = 200
FEATURE_COLUMNS = (
    "return_1d",
    "return_2d",
    "return_5d",
    "return_10d",
    "return_20d",
    "range_pct",
    "price_vs_sma20",
    "price_vs_sma50",
    "sma_ratio",
    "volatility_20d",
    "volume_change_1d",
    "volume_zscore_20d",
)


class ExperimentError(RuntimeError):
    """Raised when a trustworthy experiment cannot be constructed."""


@dataclass(frozen=True)
class ExperimentConfig:
    horizon: int = HORIZON
    minimum_model_rows: int = MIN_MODEL_ROWS
    splits: int = 5
    transaction_cost_bps: float = 5.0
    probability_threshold: float = 0.55
    random_seed: int = 42


def build_model_frame(source: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """Create lag-safe features and a forward five-session classification target."""
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(source.columns)
    if missing:
        raise ExperimentError(f"SPY dataset is missing columns: {sorted(missing)}")

    frame = source.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)

    frame["return_1d"] = close.pct_change(1, fill_method=None)
    for window in (2, 5, 10, 20):
        frame[f"return_{window}d"] = close.pct_change(window, fill_method=None)
    frame["range_pct"] = (frame["high"].astype(float) - frame["low"].astype(float)) / close
    sma20 = close.rolling(20, min_periods=20).mean()
    sma50 = close.rolling(50, min_periods=50).mean()
    frame["price_vs_sma20"] = close / sma20 - 1
    frame["price_vs_sma50"] = close / sma50 - 1
    frame["sma_ratio"] = sma20 / sma50 - 1
    frame["volatility_20d"] = frame["return_1d"].rolling(20, min_periods=20).std()
    frame["volume_change_1d"] = volume.pct_change(1, fill_method=None)
    volume_mean = volume.rolling(20, min_periods=20).mean()
    volume_std = volume.rolling(20, min_periods=20).std()
    frame["volume_zscore_20d"] = (volume - volume_mean) / volume_std.replace(0, np.nan)

    frame["forward_return_5d"] = close.shift(-horizon) / close - 1
    frame["target_up_5d"] = np.where(
        frame["forward_return_5d"].notna(),
        (frame["forward_return_5d"] > 0).astype(int),
        np.nan,
    )
    selected = ["date", *FEATURE_COLUMNS, "forward_return_5d", "target_up_5d"]
    result = frame[selected].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    result["target_up_5d"] = result["target_up_5d"].astype(int)
    return result


def model_factories(seed: int) -> dict[str, Callable[[], ClassifierMixin]]:
    return {
        "majority_baseline": lambda: DummyClassifier(strategy="prior"),
        "logistic_regression": lambda: Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", LogisticRegression(C=0.25, max_iter=2_000, random_state=seed)),
            ]
        ),
        "random_forest": lambda: RandomForestClassifier(
            n_estimators=400,
            max_depth=5,
            min_samples_leaf=15,
            max_features="sqrt",
            class_weight="balanced",
            n_jobs=-1,
            random_state=seed,
        ),
        "catboost": lambda: CatBoostClassifier(
            iterations=400,
            depth=5,
            learning_rate=0.03,
            loss_function="Logloss",
            eval_metric="AUC",
            random_seed=seed,
            thread_count=-1,
            verbose=False,
            allow_writing_files=False,
        ),
    }


def _positive_probability(model: ClassifierMixin, features: pd.DataFrame) -> np.ndarray:
    probabilities = model.predict_proba(features)
    classes = list(model.classes_)
    if 1 not in classes:
        return np.full(len(features), float(classes[0] == 1))
    return probabilities[:, classes.index(1)]


def _metrics(actual: pd.Series, probability: pd.Series) -> dict[str, float | None]:
    predicted = (probability >= 0.5).astype(int)
    auc = roc_auc_score(actual, probability) if actual.nunique() == 2 else None
    return {
        "accuracy": float(accuracy_score(actual, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "roc_auc": float(auc) if auc is not None else None,
        "log_loss": float(log_loss(actual, probability.clip(1e-6, 1 - 1e-6), labels=[0, 1])),
    }


def backtest_non_overlapping(
    predictions: pd.DataFrame, probability_threshold: float, transaction_cost_bps: float
) -> dict[str, float | int]:
    """Backtest one long-or-cash decision every five trading sessions."""
    ordered = predictions.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    sampled = ordered.iloc[::HORIZON].copy()
    sampled["position"] = (sampled["probability_up"] >= probability_threshold).astype(int)
    sampled["turnover"] = sampled["position"].diff().abs().fillna(sampled["position"])
    cost = transaction_cost_bps / 10_000
    sampled["strategy_return"] = sampled["position"] * sampled["forward_return_5d"] - sampled["turnover"] * cost
    sampled["buy_hold_return"] = sampled["forward_return_5d"]

    strategy_growth = float((1 + sampled["strategy_return"]).prod())
    benchmark_growth = float((1 + sampled["buy_hold_return"]).prod())
    return {
        "periods": int(len(sampled)),
        "trades": int(sampled["turnover"].sum()),
        "exposure": float(sampled["position"].mean()),
        "strategy_total_return": strategy_growth - 1,
        "buy_hold_total_return": benchmark_growth - 1,
    }


def evaluate(frame: pd.DataFrame, config: ExperimentConfig) -> tuple[dict[str, object], pd.DataFrame]:
    if len(frame) < config.minimum_model_rows:
        raise ExperimentError(
            f"Need at least {config.minimum_model_rows} complete model rows; found {len(frame)}. "
            "Continue collecting data before interpreting model performance."
        )
    features = frame.loc[:, FEATURE_COLUMNS]
    target = frame["target_up_5d"]
    splitter = TimeSeriesSplit(n_splits=config.splits, gap=config.horizon)
    prediction_parts: list[pd.DataFrame] = []

    for fold, (train_index, test_index) in enumerate(splitter.split(features), start=1):
        x_train, x_test = features.iloc[train_index], features.iloc[test_index]
        y_train = target.iloc[train_index]
        if y_train.nunique() < 2:
            raise ExperimentError(f"Fold {fold} training data contains only one target class")
        for model_name, factory in model_factories(config.random_seed).items():
            model = factory()
            model.fit(x_train, y_train)
            probability = _positive_probability(model, x_test)
            prediction_parts.append(
                pd.DataFrame(
                    {
                        "date": frame.iloc[test_index]["date"].to_numpy(),
                        "fold": fold,
                        "model": model_name,
                        "actual": target.iloc[test_index].to_numpy(),
                        "probability_up": probability,
                        "forward_return_5d": frame.iloc[test_index]["forward_return_5d"].to_numpy(),
                    }
                )
            )

    predictions = pd.concat(prediction_parts, ignore_index=True)
    model_reports: dict[str, object] = {}
    for model_name, group in predictions.groupby("model", sort=True):
        model_reports[model_name] = {
            "classification": _metrics(group["actual"], group["probability_up"]),
            "backtest": backtest_non_overlapping(
                group, config.probability_threshold, config.transaction_cost_bps
            ),
        }
    return {
        "status": "complete",
        "objective": "Predict whether SPY's close will be higher five trading sessions later.",
        "config": asdict(config),
        "model_rows": len(frame),
        "first_model_date": frame["date"].min().date().isoformat(),
        "last_model_date": frame["date"].max().date().isoformat(),
        "features": list(FEATURE_COLUMNS),
        "models": model_reports,
    }, predictions


def run_experiment(data_path: Path, output_dir: Path, config: ExperimentConfig) -> bool:
    source = pd.read_csv(data_path)
    frame = build_model_frame(source, config.horizon)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "five_day_evaluation.json"
    predictions_path = output_dir / "five_day_predictions.csv"
    try:
        report, predictions = evaluate(frame, config)
        predictions = predictions.sort_values(["date", "model"])
        predictions["date"] = pd.to_datetime(predictions["date"]).dt.date.astype(str)
        predictions.to_csv(predictions_path, index=False, float_format="%.10g", lineterminator="\n")
    except ExperimentError as exc:
        report = {
            "status": "insufficient_data",
            "objective": "Predict whether SPY's close will be higher five trading sessions later.",
            "config": asdict(config),
            "model_rows": len(frame),
            "reason": str(exc),
        }
        if predictions_path.exists():
            predictions_path.unlink()
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    previous = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    if rendered != previous:
        report_path.write_text(rendered, encoding="utf-8")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate five-day SPY direction models")
    parser.add_argument("--data", type=Path, default=Path("data/SPY.csv"))
    parser.add_argument("--output", type=Path, default=Path("models"))
    parser.add_argument("--minimum-rows", type=int, default=MIN_MODEL_ROWS)
    arguments = parser.parse_args()
    changed = run_experiment(
        arguments.data,
        arguments.output,
        ExperimentConfig(minimum_model_rows=arguments.minimum_rows),
    )
    print("ML evaluation updated." if changed else "ML evaluation unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

