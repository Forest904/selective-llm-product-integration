# Security

Do not commit secrets, raw credentials, private API keys, or local `.env` files.
Use `.env.example` only for credential names and deployment-specific connection
URLs. Prompt files, model behavior, routing settings, budgets, and artifact paths
belong in committed non-secret configuration under `configs/`.

Source product text and LLM responses must be treated as untrusted data. Future
LLM prompts should delimit source content, validate structured outputs, reject
unknown identifiers, and record failures as measurable artifacts.

Security issues should be documented privately until a fix is available.
