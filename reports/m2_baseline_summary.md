# M2 Baseline Summary

## Run

- Run ID: `run_20260614T141953Z_baseline_m2_alaska_monit_3f8ab8fb`
- Pipeline: `baseline_m2_alaska_monitor_subset_60`
- Run artifacts: `artifacts/runs/run_20260614T141953Z_baseline_m2_alaska_monit_3f8ab8fb`
- LLM decisions: `False`

## Metrics

- Schema F1: `0.4727`
- Core schema F1: `0.8980`
- Monitor detail schema F1: `0.4575`
- Candidate pairs: `25953`
- Blocking pair completeness: `0.9813`
- Linkage test F1: `0.8070`
- Agglomerative cluster F1: `0.2136`
- Connected-components cluster F1: `0.0372`
- Curated fusion accuracy: `0.6667`
- Bootstrap fusion accuracy: `0.4000`

## Known Weaknesses

- Schema alignment should be interpreted separately for core fields and detailed monitor attributes.
- Clustering is intentionally stricter than pair matching and still requires error review.
- Bootstrap fusion labels are majority-derived diagnostics; curated labels are the
  primary fusion check.

## Recommended M3 Routing Targets

- Ambiguous schema candidates and unmapped gold fields.
- Weak bridge merges, over-merged clusters, and under-merged truth entities.
- Low-support, high-conflict, and curated-mismatch fusion values.
