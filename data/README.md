# Data Directory

Committed data is limited to small fixtures, manifests, schemas, and
documentation needed for reproducibility.

Do not commit raw downloaded datasets, bulky generated intermediates, or local
credentials. Raw inputs should be immutable once downloaded, and ingestion must
record checksums and source metadata.

Planned layout:

- `manifests/`: dataset manifests and source metadata.
- `raw/`: unmodified downloaded source files, ignored by default.
- `interim/`: generated intermediate data, ignored by default.
- `processed/`: generated processed data, ignored by default.
- `ground_truth/`: labels or cluster truth files.
- `fixtures/`: small committed test fixtures.
