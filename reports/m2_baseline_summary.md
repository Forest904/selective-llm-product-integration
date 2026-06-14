# M2 Baseline Summary

## Run

- Run ID: `run_20260614T103210Z_baseline_m2_alaska_noteb_b675e2fa`
- Pipeline: `baseline_m2_alaska_notebook_full`
- Run artifacts: `artifacts/runs/run_20260614T103210Z_baseline_m2_alaska_noteb_b675e2fa`
- LLM decisions: `False`

## Metrics

- Schema F1: `0.0341`
- Core schema F1: `0.8571`
- Monitor detail schema F1: `0.0000`
- Candidate pairs: `873320`
- Blocking pair completeness: `0.9142`
- Linkage test F1: `0.6934`
- Agglomerative cluster F1: `0.0109`
- Connected-components cluster F1: `0.0004`
- Curated fusion accuracy: `0.0000`
- Bootstrap fusion accuracy: `0.0000`

## Known Weaknesses

- Schema alignment should be interpreted separately for core fields and detailed monitor attributes.
- Clustering is intentionally stricter than pair matching and still requires error review.
- Bootstrap fusion labels are majority-derived diagnostics; curated labels are the
  primary fusion check.

## Recommended M3 Routing Targets

- Ambiguous schema candidates and unmapped gold fields.
- Weak bridge merges, over-merged clusters, and under-merged truth entities.
- Low-support, high-conflict, and curated-mismatch fusion values.
