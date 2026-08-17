from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from market_pipeline.pipeline import (
    DEFAULT_SYMBOLS,
    PipelineError,
    PipelineResult,
    add_features,
    build_quality_report,
    fetch_symbol,
    read_existing_raw,
    render_csv,
)


def fetch_yahoo_history(symbol: str, start: str = "2010-01-01") -> list[dict[str, object]]:
    rows = fetch_symbol(symbol, start)
    for row in rows:
        row["source"] = "yahoo_finance_backfill"
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
        "overlap_policy": "Existing rows take precedence during the one-time backfill",
        "symbol_rows": counts,
    }
    metadata = root / "metadata"
    metadata.mkdir(exist_ok=True)
    (metadata / "backfill.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    quality = build_quality_report(results, data_dir)
    (metadata / "data_quality.json").write_text(json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    backfill(Path(__file__).resolve().parents[2])
