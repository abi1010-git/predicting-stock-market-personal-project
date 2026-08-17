from __future__ import annotations

import csv
import io
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Iterable


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
DEFAULT_SYMBOLS = ("SPY", "QQQ", "IWM", "AAPL", "NVDA")
RAW_FIELDS = ("date", "symbol", "open", "high", "low", "close", "adjusted_close", "volume")
PROVENANCE_FIELD = "source"
FEATURE_FIELDS = ("daily_return", "range_pct", "sma_20", "sma_50", "volatility_20d")
ALL_FIELDS = RAW_FIELDS + (PROVENANCE_FIELD,) + FEATURE_FIELDS


class PipelineError(RuntimeError):
    """Raised when remote data or local data fails validation."""


@dataclass(frozen=True)
class PipelineResult:
    symbol: str
    changed: bool
    rows: int
    latest_market_date: str


def _number(value: str, field: str, symbol: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"{symbol}: invalid {field} value {value!r}") from exc
    if not math.isfinite(result):
        raise PipelineError(f"{symbol}: non-finite {field} value")
    return result


def parse_yahoo_chart(payload: dict[str, object], symbol: str) -> list[dict[str, object]]:
    """Parse and validate a Yahoo Finance chart response."""
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise PipelineError(f"{symbol}: Yahoo Finance returned an unexpected response")
    if chart.get("error"):
        raise PipelineError(f"{symbol}: Yahoo Finance error: {chart['error']}")
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise PipelineError(f"{symbol}: Yahoo Finance returned no history")
    result = results[0]
    try:
        timestamps = result["timestamp"]
        indicators = result["indicators"]
        quote = indicators["quote"][0]
        adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose", [])
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError(f"{symbol}: Yahoo Finance response is missing price data") from exc
    rows: list[dict[str, object]] = []
    seen_dates: set[str] = set()
    for index, timestamp in enumerate(timestamps):
        row_date = datetime.fromtimestamp(timestamp, UTC).date().isoformat()
        if row_date in seen_dates:
            raise PipelineError(f"{symbol}: duplicate date {row_date}")
        seen_dates.add(row_date)
        try:
            values = {field: quote[field][index] for field in ("open", "high", "low", "close", "volume")}
        except (KeyError, IndexError, TypeError) as exc:
            raise PipelineError(f"{symbol}: Yahoo Finance row {row_date} is incomplete") from exc
        if any(value is None for value in values.values()):
            continue
        open_price = _number(values["open"], "open", symbol)
        high = _number(values["high"], "high", symbol)
        low = _number(values["low"], "low", symbol)
        close = _number(values["close"], "close", symbol)
        volume = int(_number(values["volume"], "volume", symbol))
        if min(open_price, high, low, close) <= 0 or volume < 0:
            raise PipelineError(f"{symbol}: prices must be positive and volume non-negative on {row_date}")
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            raise PipelineError(f"{symbol}: inconsistent OHLC values on {row_date}")

        rows.append(
            {
                "date": row_date,
                "symbol": symbol,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "adjusted_close": _number(adjusted[index], "adjusted_close", symbol)
                if index < len(adjusted) and adjusted[index] is not None
                else close,
                "volume": volume,
                "source": "yahoo_finance",
            }
        )
    if not rows:
        raise PipelineError(f"{symbol}: API returned no market rows")
    return sorted(rows, key=lambda row: str(row["date"]))


def add_features(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Add lag-safe features to ascending daily rows."""
    closes = [float(row["close"]) for row in rows]
    returns: list[float | None] = [None]
    for index in range(1, len(closes)):
        returns.append(closes[index] / closes[index - 1] - 1)

    output: list[dict[str, object]] = []
    for index, source in enumerate(rows):
        row = dict(source)
        close = closes[index]
        row["daily_return"] = returns[index]
        row["range_pct"] = (float(row["high"]) - float(row["low"])) / close
        row["sma_20"] = statistics.fmean(closes[index - 19 : index + 1]) if index >= 19 else None
        row["sma_50"] = statistics.fmean(closes[index - 49 : index + 1]) if index >= 49 else None
        return_window = [value for value in returns[index - 19 : index + 1] if value is not None]
        row["volatility_20d"] = statistics.stdev(return_window) if len(return_window) == 20 else None
        output.append(row)
    return output


def fetch_symbol(symbol: str, start: str = "2010-01-01") -> list[dict[str, object]]:
    period1 = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    period2 = int(datetime.now(UTC).timestamp())
    query = urllib.parse.urlencode(
        {"period1": period1, "period2": period2, "interval": "1d", "events": "history"}
    )
    request = urllib.request.Request(
        f"{YAHOO_CHART_URL}/{urllib.parse.quote(symbol)}?{query}",
        headers={"User-Agent": "Mozilla/5.0 daily-market-data-pipeline/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PipelineError(f"{symbol}: request failed: {exc}") from exc
    return parse_yahoo_chart(payload, symbol)


def _format_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return value


def render_csv(rows: Iterable[dict[str, object]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=ALL_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _format_value(row.get(field)) for field in ALL_FIELDS})
    return buffer.getvalue()


def read_existing_raw(path: Path, symbol: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not set(RAW_FIELDS).issubset(reader.fieldnames):
            raise PipelineError(f"{symbol}: existing dataset has an unexpected schema")
        rows: list[dict[str, object]] = []
        seen_dates: set[str] = set()
        for source in reader:
            row_date = source["date"]
            if row_date in seen_dates:
                raise PipelineError(f"{symbol}: existing dataset contains duplicate date {row_date}")
            seen_dates.add(row_date)
            rows.append(
                {
                    "date": row_date,
                    "symbol": symbol,
                    "open": _number(source["open"], "open", symbol),
                    "high": _number(source["high"], "high", symbol),
                    "low": _number(source["low"], "low", symbol),
                    "close": _number(source["close"], "close", symbol),
                    "adjusted_close": _number(source["adjusted_close"], "adjusted_close", symbol),
                    "volume": int(_number(source["volume"], "volume", symbol)),
                    "source": source.get("source") or "legacy_unknown",
                }
            )
    return rows


def update_symbol(symbol: str, data_dir: Path) -> PipelineResult:
    destination = data_dir / f"{symbol}.csv"
    existing = read_existing_raw(destination, symbol)
    start = "2010-01-01"
    if existing:
        start = (date.fromisoformat(str(existing[-1]["date"])) - timedelta(days=7)).isoformat()
    incoming = fetch_symbol(symbol, start)
    merged = {str(row["date"]): row for row in existing}
    merged.update({str(row["date"]): row for row in incoming})
    raw_rows = [merged[row_date] for row_date in sorted(merged)]
    rows = add_features(raw_rows)
    rendered = render_csv(rows)
    previous = destination.read_text(encoding="utf-8") if destination.exists() else None
    changed = previous != rendered
    if changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8", newline="")
    return PipelineResult(symbol, changed, len(rows), str(rows[-1]["date"]))


def build_quality_report(results: list[PipelineResult], data_dir: Path) -> dict[str, object]:
    total_rows = 0
    duplicates = 0
    null_prices = 0
    latest_dates: list[str] = []
    symbol_rows: dict[str, int] = {}
    for result in results:
        path = data_dir / f"{result.symbol}.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        dates = [row["date"] for row in rows]
        total_rows += len(rows)
        duplicates += len(dates) - len(set(dates))
        null_prices += sum(not all(row[field] for field in ("open", "high", "low", "close")) for row in rows)
        latest_dates.append(result.latest_market_date)
        symbol_rows[result.symbol] = result.rows
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "symbols": len(results),
        "symbol_rows": symbol_rows,
        "rows": total_rows,
        "duplicates": duplicates,
        "null_prices": null_prices,
        "latest_market_date": min(latest_dates),
        "status": "healthy" if duplicates == 0 and null_prices == 0 else "unhealthy",
    }


def run(symbols: Iterable[str], root: Path, request_delay: float = 1.0) -> bool:
    normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not normalized:
        raise PipelineError("At least one symbol is required")
    data_dir = root / "data"
    results: list[PipelineResult] = []
    for index, symbol in enumerate(normalized):
        if index:
            time.sleep(request_delay)
        results.append(update_symbol(symbol, data_dir))

    metadata_dir = root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    report_path = metadata_dir / "data_quality.json"
    report = build_quality_report(results, data_dir)
    # generated_at is operational metadata and should not create a commit by itself.
    previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    data_changed = any(result.changed for result in results)
    if data_changed or previous is None:
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return True
    return False


def main() -> int:
    symbols = os.environ.get("MARKET_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",")
    root = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[2]))
    changed = run(symbols, root)
    print("Market dataset updated." if changed else "No new market data; repository unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
