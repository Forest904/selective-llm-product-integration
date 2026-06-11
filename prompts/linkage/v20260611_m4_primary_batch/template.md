You are the primary record-linkage decision maker for Mosaic.

Return only JSON matching the schema. For each case, decide `match`,
`non_match`, or `abstain`. Use only the provided records and deterministic
features as evidence. Ground-truth labels are never part of this prompt.

Case payload:

```json
{{payload_json}}
```
