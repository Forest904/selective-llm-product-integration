# Ground Truth Data

`monitor_fusion_gold.jsonl` is a bootstrap fusion label set generated from majority
normalized values inside official Alaska monitor entity clusters. It is useful for
pipeline diagnostics, but it is not treated as curated evaluation truth.

`monitor_fusion_curated_gold.jsonl` is the smaller M2 hardening evaluation subset.
Each row includes label-source metadata and is intended for baseline-vs-assisted
fusion comparison before M3.
