# M4 Error Case Appendix

## schema_source_alpha//price

- Stage: `schema_alignment`
- System output: `{'source_attribute_id': 'source_alpha//price', 'predicted_target_attribute_name': 'UNMAPPED', 'score_total': 1.0, 'me...`
- Expected output: `{'gold_target_attribute_name': 'price'}`
- Explanation: The source attribute was mapped to the wrong mediated-schema field, which can propagate into normalization and fusion.

## fusion_1_entity_000003

- Stage: `fusion`
- System output: `{'entity_id': 'entity_000003', 'attribute': 'price', 'predicted_value': '310.00'}`
- Expected output: `{'truth_entity_id': 'ENTITY#001', 'expected_value': 'None'}`
- Explanation: The fused value disagrees with the curated or bootstrap fusion gold value, usually because conflicting source claims normalize to close but not identical values.

## linkage_pair_00000001

- Stage: `record_linkage`
- System output: `{'candidate_pair_id': 'pair_00000001', 'match_prediction': 0, 'match_probability': 0.05}`
- Expected output: `{'ground_truth_label': 1}`
- Explanation: The pairwise matcher prediction disagrees with the labeled entity-resolution pair.
