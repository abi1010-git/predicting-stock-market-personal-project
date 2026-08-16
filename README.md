# Daily Market Data Pipeline

A reproducible data and machine-learning project that tests whether information available after the SPY market close can estimate the probability that SPY will close higher five trading sessions later.

The objective is an experiment, not an assumption that prices are predictable. A model is useful only if it beats simple baselines consistently on unseen chronological periods and remains competitive after estimated transaction costs.

> **Educational-use disclaimer:** This project is provided solely for educational and research purposes. It is not financial, investment, tax, or trading advice; it does not recommend buying, selling, or holding any security. Model outputs and backtests can be inaccurate, incomplete, or affected by data errors and do not guarantee future results. Consult a qualified professional and perform your own independent research before making financial decisions. You are solely responsible for any decisions or losses arising from use of this project.

## What it does

Every weekday after the regular US market close, GitHub Actions:

1. Downloads recent daily OHLCV data from Alpha Vantage.
2. Rejects malformed dates, duplicate rows, invalid prices, and inconsistent OHLC values.
3. Generates daily returns, intraday range, 20/50-day moving averages, and 20-day volatility.
4. Writes one deterministic CSV per symbol under `data/`.
5. Updates `metadata/data_quality.json` with row counts and quality checks.
6. Commits only when the market dataset actually changed.

The default universe is `SPY`, `QQQ`, `IWM`, `AAPL`, and `NVDA`. Alpha Vantage's compact response provides the latest 100 observations; scheduled runs preserve a growing, versioned history in Git.

## Repository layout

```text
.
├── .github/workflows/daily_update.yml
├── data/                         # Created by the first successful run
├── metadata/data_quality.json    # Created by the first successful run
├── src/market_pipeline/
│   └── pipeline.py
└── tests/test_pipeline.py
```

## Setup

Requires Python 3.11 or newer and an [Alpha Vantage API key](https://www.alphavantage.co/support/#api-key).

PowerShell:

```powershell
$env:ALPHA_VANTAGE_API_KEY = "your-key"
$env:MARKET_SYMBOLS = "SPY,QQQ,IWM,AAPL,NVDA"
python -m src.market_pipeline.pipeline
```

Run the tests locally:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

For automation, create a GitHub Actions repository secret named `ALPHA_VANTAGE_API_KEY`, then run **Daily market data update** manually once from the Actions tab. Subsequent weekday runs use the schedule in the workflow.

## Dataset schema

| Column | Meaning |
| --- | --- |
| `date`, `symbol` | Trading date and ticker |
| `open`, `high`, `low`, `close`, `volume` | Daily market observations |
| `adjusted_close` | Currently equal to close because the free daily endpoint is unadjusted |
| `daily_return` | Close-to-close fractional return |
| `range_pct` | `(high - low) / close` |
| `sma_20`, `sma_50` | Trailing simple moving averages |
| `volatility_20d` | Sample standard deviation of 20 trailing daily returns |

Features use only the current and earlier rows; no future observations leak into a row.

## Five-day ML experiment

The experiment in `src/market_ml/experiment.py` constructs a binary target:

```text
target_up_5d = 1 when close[t + 5] > close[t], otherwise 0
```

It compares four classifiers under identical conditions:

- Majority-class baseline
- Scaled logistic regression
- Regularized Random Forest
- CatBoost gradient boosting

The inputs are trailing returns, price/range measurements, moving-average ratios, volatility, and volume changes. All inputs are known by the prediction date. The future five-day return is used only as the label and for out-of-sample backtesting.

Validation uses expanding `TimeSeriesSplit` folds with a five-session gap between training and testing. The gap prevents a training label whose five-day outcome overlaps the beginning of the test period. Backtesting samples one prediction every five sessions so returns are not double-counted, applies a 0.55 probability threshold, and subtracts five basis points when the position changes.

Run it locally after `data/SPY.csv` exists:

```powershell
python -m pip install -r requirements.txt
python -m src.market_ml.experiment
```

Outputs are written to:

```text
models/five_day_evaluation.json
models/five_day_predictions.csv
```

The weekly GitHub workflow will report `insufficient_data` until at least 200 complete model rows exist. This safeguard prevents a small initial API response from being presented as meaningful evidence.

Evaluation includes accuracy, balanced accuracy, ROC-AUC, log loss, model exposure, trade count, strategy return, and a same-period SPY buy-and-hold comparison. Results remain exploratory because overlapping labels, market regime changes, taxes, slippage, and unadjusted prices can materially affect conclusions.

## Scope and limitations

This repository is an educational data-engineering and machine-learning project, not financial advice or a trading system. It does not claim that historical predictive performance will continue. Alpha Vantage's daily endpoint is unadjusted, so splits can create discontinuities until an adjusted data source is added.
