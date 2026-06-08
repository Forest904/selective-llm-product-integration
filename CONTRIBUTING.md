# Contributing

Mosaic is pipeline-first. Start with the governing documents before making
substantive changes:

- `Mosaic_PRD.md`
- `Mosaic_Roadmap.md`
- `Project_Blueprint_Mosaic.md`
- `AGENT.md`

## Development Workflow

1. Install dependencies with `make install`.
2. Run `make lint` and `make test` before proposing changes.
3. Keep generated data and artifacts out of git unless a milestone explicitly
   requires a small committed fixture.
4. Prefer versioned configs, prompts, and typed code over one-off manual steps.
5. Do not commit secrets, API keys, raw credentials, or local environment files.

## Milestone Discipline

Build the deterministic baseline before LLM-assisted behavior. The website and
workbench must consume shared pipeline services and artifacts rather than
duplicating integration logic.
