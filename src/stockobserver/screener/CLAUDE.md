# `screener/` — declarative stock screening

Evaluates a list of `{field, operator, value}` predicates over the **snapshot table** (one row per
symbol per date, holding fundamental + technical + factor fields in canonical units). See
`docs/ARCHITECTURE.md` §5.

## Responsibilities
- Parse/validate a screen (JSON: name + predicate list + optional factor weights).
- Evaluate predicates as **vectorized DuckDB/pandas** queries — fast, no per-symbol loops.
- Persist/load screens from SQLite (`data.state`) for reproducibility.
- Support **historical replay**: "what would this screen have selected on date D" (point-in-time),
  which feeds the portfolio backtester.

## Planned files
```
model.py       # Predicate, Screen dataclasses/pydantic; operators
engine.py      # evaluate(screen, snapshot) -> ranked DataFrame
store.py       # save/load screens via data.state
```

## Notes
- A new criterion should be a **one-line config change** — if it requires code, the metric probably
  belongs in `factors/` or the snapshot builder, not here.
- Reads canonical fields only; never queries a provider directly (go through `data.cache`).
