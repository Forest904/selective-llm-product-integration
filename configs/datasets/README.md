# Dataset Configs

Dataset discovery, selection, and ingestion configs live here.

- `alaska_candidates.json` records the published Camera, Monitor, and Notebook
  candidate metadata from the Alaska benchmark repository.
- `fixture_dataset.json` drives committed M1 fixture ingestion and profiling
  tests.

Full Alaska raw data is not committed and is not downloaded by Mosaic. Obtain the
benchmark manually from the professor, benchmark owner, or another approved
source before running real-data M1 commands.

Expected local layouts:

```text
data/raw/alaska/notebook/extracted/
data/raw/alaska/monitor/extracted/
```

Notebook and Monitor are preferred candidates because Camera has only 103
published entities and misses the 200-entity assignment gate. After placing the
files locally, run `mosaic dataset select` to generate the selection score table,
candidate report, and `selected_dataset.json` when the selected local directory
is present.
