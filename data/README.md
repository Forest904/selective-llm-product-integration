# Data Directory

Committed data is limited to small fixtures, manifests, schemas, and
documentation needed for reproducibility.

Do not commit raw benchmark datasets, bulky generated intermediates, or local
credentials. Users must obtain the benchmark data manually before real-data
pipeline runs. Raw inputs should be immutable once placed locally, and ingestion
must record checksums and source metadata.

Planned layout:

- `manifests/`: dataset manifests and source metadata.
- `raw/`: unmodified manually provided source files, ignored by default.
- `interim/`: generated intermediate data, ignored by default.
- `processed/`: generated processed data, ignored by default.
- `ground_truth/`: labels or cluster truth files.
- `fixtures/`: small committed test fixtures.

M1 adds a tiny committed fixture under `fixtures/m1/` and fixture labels under
`ground_truth/`. Full Alaska benchmark files must be manually placed under
`raw/alaska/<vertical>/extracted/` and remain immutable afterward. Preferred
verticals are `notebook` and `monitor`.
