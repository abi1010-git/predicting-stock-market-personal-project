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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable


API_URL = "https://www.alphavantage.co/query"
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


def parse_alpha_vantage_csv(payload: str, symbol: str) -> list[dict[str, object]]:
    """Parse and validate an Alpha Vantage TIME_SERIES_DAILY CSV response."""
    stripped = payload.lstrip()
    if not stripped:
        raise PipelineError(f"{symbol}: API returned an empty response")
    if stripped.startswith("{"):
        try:
            message = json.loads(payload)
        except json.JSONDecodeError:
            message = payload[:200]
        raise PipelineError(f"{symbol}: API returned an error response: {message}")

    reader = csv.DictReader(io.StringIO(payload))
    expected = {"timestamp", "open", "high", "low", "close", "volume"}
    if not reader.fieldnames or not expected.issubset(reader.fieldnames):
        raise PipelineError(f"{symbol}: unexpected API columns {reader.fieldnames}")

    rows: list[dict[str, object]] = []
    seen_dates: set[str] = set()
    for source in reader:
        row_date = source["timestamp"]
        try:
            date.fromisoformat(row_date)
        except (TypeError, ValueError) as exc:
            raise PipelineError(f"{symbol}: invalid date {row_date!r}") from exc
        if row_date in seen_dates:
            raise PipelineError(f"{symbol}: duplicate date {row_date}")
        seen_dates.add(row_date)

        open_price = _number(source["open"], "open", symbol)
        high = _number(source["high"], "high", symbol)
        low = _number(source["low"], "low", symbol)
        close = _number(source["close"], "close", symbol)
        volume = int(_number(source["volume"], "volume", symbol))
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
                # TIME_SERIES_DAILY is split-unadjusted; retained as an explicit
                # model-facing field so the source can be upgraded independently.
                "adjusted_close": close,
                "volume": volume,
                "source": "alpha_vantage",
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


def fetch_symbol(symbol: str, api_key: str, output_size: str = "compact") -> list[dict[str, object]]:
    query = urllib.parse.urlencode(
        {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": output_size,
            "datatype": "csv",
            "apikey": api_key,
        }
    )
    request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": "daily-market-data-pipeline/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PipelineError(f"{symbol}: request failed: {exc}") from exc
    return parse_alpha_vantage_csv(payload, symbol)


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


def update_symbol(symbol: str, api_key: str, data_dir: Path) -> PipelineResult:
    destination = data_dir / f"{symbol}.csv"
    existing = read_existing_raw(destination, symbol)
    incoming = fetch_symbol(symbol, api_key)
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


def run(symbols: Iterable[str], api_key: str, root: Path, request_delay: float = 1.0) -> bool:
    normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not normalized:
        raise PipelineError("At least one symbol is required")
    data_dir = root / "data"
    results: list[PipelineResult] = []
    for index, symbol in enumerate(normalized):
        if index:
            time.sleep(request_delay)
        results.append(update_symbol(symbol, api_key, data_dir))

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
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not api_key:
        raise PipelineError("ALPHA_VANTAGE_API_KEY is required")
    symbols = os.environ.get("MARKET_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",")
    root = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[2]))
    changed = run(symbols, api_key, root)
    print("Market dataset updated." if changed else "No new market data; repository unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
