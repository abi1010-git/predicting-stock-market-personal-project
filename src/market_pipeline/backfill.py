from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from market_pipeline.pipeline import (
    DEFAULT_SYMBOLS,
    PipelineError,
    PipelineResult,
    add_features,
    build_quality_report,
    read_existing_raw,
    render_csv,
)


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


def fetch_yahoo_history(symbol: str, start: str = "2010-01-01") -> list[dict[str, object]]:
    period1 = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp())
    period2 = int(datetime.now(UTC).timestamp())
    query = urllib.parse.urlencode(
        {"period1": period1, "period2": period2, "interval": "1d", "events": "history"}
    )
    request = urllib.request.Request(
        f"{YAHOO_CHART_URL}/{urllib.parse.quote(symbol)}?{query}",
        headers={"User-Agent": "Mozilla/5.0 market-research-backfill/1.0"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise PipelineError(f"{symbol}: Yahoo Finance error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise PipelineError(f"{symbol}: Yahoo Finance returned no history")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    adjusted = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose", [])
    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(timestamps):
        values = {name: quote.get(name, [None] * len(timestamps))[index] for name in ("open", "high", "low", "close", "volume")}
        if any(value is None or (isinstance(value, float) and not math.isfinite(value)) for value in values.values()):
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp, UTC).date().isoformat(),
                "symbol": symbol,
                "open": float(values["open"]),
                "high": float(values["high"]),
                "low": float(values["low"]),
                "close": float(values["close"]),
                "adjusted_close": float(adjusted[index]) if index < len(adjusted) and adjusted[index] is not None else float(values["close"]),
                "volume": int(values["volume"]),
                "source": "yahoo_finance_backfill",
            }
        )
    if not rows:
        raise PipelineError(f"{symbol}: Yahoo Finance history contained no valid rows")
    return rows


def backfill(root: Path, symbols: tuple[str, ...] = DEFAULT_SYMBOLS, start: str = "2010-01-01") -> None:
    data_dir = root / "data"
    counts: dict[str, int] = {}
    results: list[PipelineResult] = []
    for index, symbol in enumerate(symbols):
        if index:
            time.sleep(0.5)
        historical = fetch_yahoo_history(symbol, start)
        existing = read_existing_raw(data_dir / f"{symbol}.csv", symbol)
        merged = {str(row["date"]): row for row in historical}
        merged.update({str(row["date"]): row for row in existing})
        rows = add_features([merged[key] for key in sorted(merged)])
        (data_dir / f"{symbol}.csv").write_text(render_csv(rows), encoding="utf-8", newline="")
        counts[symbol] = len(rows)
        results.append(PipelineResult(symbol, True, len(rows), str(rows[-1]["date"])))
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": "Yahoo Finance chart endpoint",
        "purpose": "one-time historical research backfill",
        "start": start,
        "overlap_policy": "Alpha Vantage rows take precedence",
        "symbol_rows": counts,
    }
    metadata = root / "metadata"
    metadata.mkdir(exist_ok=True)
    (metadata / "backfill.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    quality = build_quality_report(results, data_dir)
    (metadata / "data_quality.json").write_text(json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    backfill(Path(__file__).resolve().parents[2])
