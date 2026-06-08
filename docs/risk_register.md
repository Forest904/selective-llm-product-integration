# Initial Risk Register

| Risk | Impact | M0 Mitigation |
| --- | --- | --- |
| Web scope expands before the research pipeline exists | Academic delivery slips | Keep `apps/web` as placeholders only |
| Generated outputs are committed as source | Reproducibility and repo hygiene degrade | Ignore generated artifact/data paths and document regeneration rules |
| Environment setup remains implicit | Clean-clone reproduction fails | Provide `.env.example`, Makefile targets, and README quick start |
| Dataset source is unsuitable or unavailable | Later milestone delay | Reserve data manifests, fixtures, and download documentation paths |
| LLM credentials leak into the repository | Security and grading risk | Commit config names only and ignore local env files |
