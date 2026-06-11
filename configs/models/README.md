# Model Configs

Classical model and LLM provider/model settings live here as committed,
non-secret configuration.

Do not put API keys, database passwords, provider credentials, or local account
secrets in these files. Runtime credentials belong in local environment
variables or a deployment secret manager.

`openai_m4_gpt41mini_live.json` is the M4 reported-release model config. It
uses `gpt-4.1-mini`, temperature `0`, strict structured outputs, cache-or-live
execution, and the current committed token-pricing assumptions used for cost
estimation.
