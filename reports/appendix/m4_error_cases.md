# M4 Error Case Appendix

## schema_source_alpha//price

- Stage: `schema_alignment`
- System output: `{'source_attribute_id': 'source_alpha//price', 'predicted_target_attribute_name': 'UNMAPPED', 'score_total': 1.0, 'method': 'deterministic_schema_v1'}`
- Expected output: `{'gold_target_attribute_name': 'price'}`
- Explanation: The source attribute was mapped to the wrong mediated-schema field, which can propagate into normalization and fusion.

## fusion_1_entity_000001

- Stage: `fusion`
- System output: `{'entity_id': 'entity_000001', 'attribute': 'price', 'predicted_value': '305.00'}`
- Expected output: `{'truth_entity_id': 'ENTITY#001', 'expected_value': 'None'}`
- Explanation: The fused value disagrees with the curated or bootstrap fusion gold value, usually because conflicting source claims normalize to close but not identical values.

## fixture_placeholder_3

- Stage: `fixture_only`
- System output: `No additional labeled error was available.`
- Expected output: `N/A`
- Explanation: Fixture-only placeholder. This cannot satisfy the M4 submission gate.
