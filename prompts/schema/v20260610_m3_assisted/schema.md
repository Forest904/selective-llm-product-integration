# Schema Output

Required JSON fields:

- `source_attribute`: source attribute name.
- `target_attribute`: one allowed mediated attribute, `UNMAPPED`, or `ABSTAIN`.
- `decision`: `match`, `unmapped`, or `abstain`.
- `confidence`: number from 0 to 1.
- `supporting_evidence`: list of short evidence statements.
- `abstain`: boolean.

Ground-truth targets must not be included in prompt payloads.
