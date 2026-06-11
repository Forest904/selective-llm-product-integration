# Reports

Report source files live here. The M4 academic release builder writes:

- `reports/report.md` as the report source;
- `reports/report.pdf` when Pandoc and a LaTeX PDF engine are available;
- `reports/release/` for compact release manifests, tables, figures, and the
  final integrated dataset copy;
- `reports/appendix/` for structured error cases.

Large run directories, raw data, caches, and bulky generated artifacts stay
under ignored `artifacts/` and `data/` paths and are regenerated from the CLI.

Default report generation is submission-grade: `mosaic report build` expects a
full live M4 manifest. Use `mosaic report build --fixture` or
`make report-fixture` for CI-safe fixture output. Fixture builds write
`artifacts/reports/m4/m4_fixture_manifest.json` by default and leave the
full-live manifest path untouched.
