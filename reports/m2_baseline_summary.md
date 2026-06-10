# M2 Baseline Summary

## Run

- Run ID: `run_20260610T164102Z_baseline_m2_alaska_monit_2e9a3d55`
- Pipeline: `baseline_m2_alaska_monitor`
- Run artifacts: `artifacts/runs/run_20260610T164102Z_baseline_m2_alaska_monit_2e9a3d55`
- LLM decisions: `False`

## Metrics

- Schema F1: `0.4833`
- Core schema F1: `0.8980`
- Monitor detail schema F1: `0.4687`
- Candidate pairs: `588531`
- Blocking pair completeness: `0.9656`
- Linkage test F1: `0.9286`
- Agglomerative cluster F1: `0.1298`
- Connected-components cluster F1: `0.0003`
- Curated fusion accuracy: `0.7143`
- Bootstrap fusion accuracy: `0.6026`

## Known Weaknesses

- Schema alignment should be interpreted separately for core fields and detailed monitor attributes.
- Clustering is intentionally stricter than pair matching and still requires error review.
- Bootstrap fusion labels are majority-derived diagnostics; curated labels are the primary fusion check.

## Recommended M3 Routing Targets

- Ambiguous schema candidates and unmapped gold fields.
- Weak bridge merges, over-merged clusters, and under-merged truth entities.
- Low-support, high-conflict, and curated-mismatch fusion values.
