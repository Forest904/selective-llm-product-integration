# M4 Error Case Appendix

## schema_ca.pcpartpicker.com//displayport

- Stage: `schema_alignment`
- System output: `{'source_attribute_id': 'ca.pcpartpicker.com//displayport', 'predicted_target_attribute_name': 'has_displayport', 'score_total': 0.747416, 'method': 'determinis`
- Expected output: `{'gold_target_attribute_name': 'displayport_quantity'}`
- Explanation: The source attribute was mapped to the wrong mediated-schema field, which can propagate into normalization and fusion.

## fusion_1_entity_009725

- Stage: `fusion`
- System output: `{'entity_id': 'entity_009725', 'attribute': 'contrast_ratio_static', 'predicted_value': '450:1'}`
- Expected output: `{'truth_entity_id': 'ENTITY#002', 'expected_value': '500:1'}`
- Explanation: The fused value disagrees with the curated or bootstrap fusion gold value, usually because conflicting source claims normalize to close but not identical values.

## fusion_2_entity_009725

- Stage: `fusion`
- System output: `{'entity_id': 'entity_009725', 'attribute': 'screen_brightness', 'predicted_value': '230'}`
- Expected output: `{'truth_entity_id': 'ENTITY#002', 'expected_value': '250'}`
- Explanation: The fused value disagrees with the curated or bootstrap fusion gold value, usually because conflicting source claims normalize to close but not identical values.
