# Project guidance

- Treat this repository as an educational data-engineering and machine-learning portfolio project, not as a trading system or a way to manufacture contribution activity.
- Use Yahoo Finance as the sole market-data provider. Do not introduce Alpha Vantage credentials or dependencies.
- Preserve the stable OHLCV CSV schema and explicit source provenance so downstream experiments remain reproducible.
- Validate remote responses, dates, duplicate rows, prices, volume, and OHLC consistency before writing data.
- Keep generated CSV output deterministic and commit data only when market rows actually change.
- Keep features lag-safe: a row may use only information available on that date or earlier.
- Keep scheduled commits clearly attributed to `github-actions[bot]`.
- Maintain data-quality metadata and tests whenever ingestion behavior changes.
- Document that Yahoo Finance is an unofficial, best-effort source and that this project is for education and research only.
