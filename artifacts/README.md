# Artifacts Directory

Artifacts are regenerated outputs, not source material. Large generated files
are ignored by default.

Run outputs should use:

```text
artifacts/runs/<run_id>/
```

Within each run, reserve:

- `logs/` for execution logs.
- `metrics/` for metrics tables.
- `figures/` for run-specific plots.
- `tables/` for report-ready tables.
- `errors/` for error examples and analysis.
- `exports/` for final integrated outputs.

Shared generated report outputs live in `artifacts/reports/`. Static README
files and `.gitkeep` placeholders may be committed to preserve the directory
shape.
