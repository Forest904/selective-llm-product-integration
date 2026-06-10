# Linkage Output

Required JSON fields:

- `decision`: `match`, `non_match`, or `abstain`.
- `confidence`: number from 0 to 1.
- `supporting_evidence`: list of short evidence statements.
- `contradicting_evidence`: list of short evidence statements.
- `abstain`: boolean.

Invalid or low-confidence outputs fall back to deterministic M2 predictions.
