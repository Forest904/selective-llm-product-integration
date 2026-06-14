# M4 Error Case Appendix

## schema_ca.pcpartpicker.com//displayport

- Stage: `schema_alignment`
- System output: `{'source_attribute_id': 'ca.pcpartpicker.com//displayport', 'predicted_target_attribute_name': 'has_displayport', 'sc...`
- Expected output: `{'gold_target_attribute_name': 'displayport_quantity'}`
- Explanation: The source attribute was mapped to the wrong mediated-schema field, which can propagate into normalization and fusion.

## linkage_pair_00000025

- Stage: `record_linkage`
- System output: `{'candidate_pair_id': 'pair_00000025', 'match_prediction': 0, 'match_probability': 0.45589268898553187}`
- Expected output: `{'ground_truth_label': 1}`
- Explanation: The pairwise matcher prediction disagrees with the labeled entity-resolution pair.

## cluster_undermerge_ENTITY#022

- Stage: `clustering`
- System output: `{'predicted_cluster_count': 6, 'predicted_entity_ids': ['entity_000083', 'entity_000104', 'entity_000270', 'entity_00...`
- Expected output: `{'ground_truth_entity_id': 'ENTITY#022', 'expected_cluster_count': 1}`
- Explanation: Records from one labeled truth entity were split across multiple predicted clusters, so downstream fusion sees incomplete claim evidence.
