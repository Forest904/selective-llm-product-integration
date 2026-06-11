# Experiment Configs

Experiment manifests, ablation configurations, routing policies, budgets, and
stage toggles live here as committed, non-secret configuration.

Do not put API keys, database passwords, provider credentials, or local account
secrets in these files. Runtime credentials belong in local environment
variables or a deployment secret manager.

## M4 Academic Release

M4 release configs are committed templates. The release command materializes a
deterministic 60-entity Alaska Monitor subset and generates subset-specific
copies under ignored artifacts before running the live matrix. The committed
model settings are in `configs/models/openai_m4_gpt41mini_live.json`.

The template matrix is:

- `m4_c_llm_primary_alaska_monitor.json` for C-LLM, the bounded LLM-primary
  comparison pipeline;
- `m4_b_all_alaska_monitor.json` for B-All;
- `m4_b_schema_only_alaska_monitor.json`, `m4_b_linkage_only_alaska_monitor.json`,
  and `m4_b_fusion_only_alaska_monitor.json` for single-stage ablations;
- `m4_b_schema_linkage_alaska_monitor.json` and
  `m4_b_linkage_fusion_alaska_monitor.json` for paired-stage ablations;
- `m4_budget_cap_*_alaska_monitor.json` for routing-budget points.

Run the subset reported matrix with:

```bash
uv run mosaic experiment release --live
```

Use `--fixture` for a CI-safe reproduction bundle that does not call a live
model.

Run full vertical deterministic scale checks separately:

```bash
uv run mosaic experiment deterministic-scale
```
