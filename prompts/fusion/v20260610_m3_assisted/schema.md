# Fusion Output

Required JSON fields:

- `selected_value`: one value from `allowed_outputs`, or `ABSTAIN`.
- `confidence`: number from 0 to 1.
- `supporting_claim_ids`: known claim IDs supporting the selected value.
- `contradicting_claim_ids`: known claim IDs contradicted by the selected value.
- `reason`: short explanation grounded in the supplied claims.
- `abstain`: boolean.

Invented values, unsupported values, incompatible units, unknown claim IDs, and missing
fields are rejected and counted.
