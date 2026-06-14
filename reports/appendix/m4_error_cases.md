# M4 Error Case Appendix

## schema_ca.pcpartpicker.com//displayport

- Stage: `schema_alignment`
- System output: `{'source_attribute_id': 'ca.pcpartpicker.com//displayport', 'predicted_target_attribute_name': 'has_displayport', 'sc...`
- Expected output: `{'gold_target_attribute_name': 'displayport_quantity'}`
- Explanation: The source attribute was mapped to the wrong mediated-schema field, which can propagate into normalization and fusion.

## fusion_1_entity_000378

- Stage: `fusion`
- System output: `{'entity_id': 'entity_000378', 'attribute': 'screen_brightness', 'predicted_value': '225'}`
- Expected output: `{'truth_entity_id': 'ENTITY#002', 'expected_value': '250'}`
- Explanation: The fused value disagrees with the curated or bootstrap fusion gold value, usually because conflicting source claims normalize to close but not identical values.

## linkage_pair_00000025

- Stage: `record_linkage`
- System output: `{'candidate_pair_id': 'pair_00000025', 'match_prediction': 0, 'match_probability': 0.3533711894020474}`
- Expected output: `{'ground_truth_label': 1}`
- Explanation: The pairwise matcher prediction disagrees with the labeled entity-resolution pair.
