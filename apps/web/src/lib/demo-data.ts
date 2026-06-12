import type {
  ConceptModule,
  ErrorCase,
  IntegratedEntityPreview,
  OperationalMetricRow,
  PipelineStage,
  ReportMetricRow,
  ToySourceRecord
} from "./types";

export const fixtureNotice =
  "Fixture demo data: replace these static snapshots with live M4 outputs after full-scale benchmark runs complete.";

export const toyRecords: ToySourceRecord[] = [
  {
    id: "alpha-a100",
    source: "source_alpha",
    sourceLabel: "Alpha Catalog",
    productTruth: "canon-eos-4000d",
    fields: {
      title: "Canon EOS 4000D DSLR Camera Kit",
      brand: "Canon",
      model: "EOS 4000D",
      price_usd: "299.00",
      megapixels: "18 MP"
    }
  },
  {
    id: "beta-b200",
    source: "source_beta",
    sourceLabel: "Beta Market",
    productTruth: "canon-eos-4000d",
    fields: {
      name: "Canon 4000D 18MP Digital SLR",
      maker: "Canon",
      model_no: "4000D",
      amount: "310 USD",
      resolution: "18.0 megapixels"
    }
  },
  {
    id: "gamma-c300",
    source: "source_gamma",
    sourceLabel: "Gamma Outlet",
    productTruth: "canon-eos-4000d",
    fields: {
      product_title: "EOS 4000D Camera from Canon",
      brand_name: "Canon",
      sku_model: "EOS4000D",
      price: "305.00",
      bundle: "camera body and starter lens"
    }
  },
  {
    id: "alpha-a101",
    source: "source_alpha",
    sourceLabel: "Alpha Catalog",
    productTruth: "sony-a6000",
    fields: {
      title: "Sony Alpha A6000 Mirrorless Camera",
      brand: "Sony",
      model: "A6000",
      price_usd: "540.00",
      megapixels: "24.3 MP"
    }
  },
  {
    id: "beta-b201",
    source: "source_beta",
    sourceLabel: "Beta Market",
    productTruth: "sony-a6000",
    fields: {
      name: "Sony A6000 Camera Body",
      maker: "Sony",
      model_no: "ILCE-6000",
      amount: "525 USD",
      resolution: "24 MP"
    }
  },
  {
    id: "gamma-c301",
    source: "source_gamma",
    sourceLabel: "Gamma Outlet",
    productTruth: "sony-a6000",
    fields: {
      product_title: "Sony Alpha 6000 mirrorless kit",
      brand_name: "Sony",
      sku_model: "A6000KIT",
      price: "560.00",
      bundle: "body plus starter lens"
    }
  },
  {
    id: "alpha-a102",
    source: "source_alpha",
    sourceLabel: "Alpha Catalog",
    productTruth: "nikon-d3500",
    fields: {
      title: "Nikon D3500 DSLR Camera",
      brand: "Nikon",
      model: "D3500",
      price_usd: "415.00",
      megapixels: "24.2 MP"
    }
  },
  {
    id: "gamma-c302",
    source: "source_gamma",
    sourceLabel: "Gamma Outlet",
    productTruth: "nikon-d3500",
    fields: {
      product_title: "Nikon D3500 Digital SLR bundle",
      brand_name: "Nikon",
      sku_model: "D3500-KIT",
      price: "invalid: call for deal",
      bundle: "camera plus bag"
    }
  }
];

export const pipelineStages: PipelineStage[] = [
  {
    id: "sources",
    title: "Heterogeneous Sources",
    shortTitle: "Sources",
    story:
      "Three catalogs describe the same camera products with different field names, levels of detail, and price formats.",
    inputObjects: ["Alpha Catalog rows", "Beta Market rows", "Gamma Outlet rows"],
    decision: "Keep raw records immutable and attach source identifiers before any transformation.",
    outputObjects: ["8 source records", "3 source systems", "raw provenance anchors"],
    commonError: "Treating row position as identity makes later reruns impossible to audit.",
    baselineSummary: "Deterministic ingestion preserves raw payloads and stable record IDs.",
    llmSummary: "No LLM decision is needed; source text is only prepared for later bounded prompts.",
    evidence: {
      deterministic: [
        { label: "Record UID", value: "source_alpha:a100", detail: "Stable source plus source-local ID." },
        { label: "Checksum", value: "raw payload hash", detail: "Detects changed source content." }
      ],
      llm: [{ label: "LLM", decision: "not used", detail: "Ingestion is mechanical.", status: "not-used" }],
      uncertainty: [{ label: "Input quality", confidence: 0.88, detail: "One invalid price-like value is retained." }],
      provenance: [{ from: "raw file", to: "source record", detail: "Every later object links back here." }]
    }
  },
  {
    id: "schema",
    title: "Schema Alignment",
    shortTitle: "Schema",
    story:
      "Source attributes such as maker, brand_name, and brand must map to the mediated field brand before values can be compared.",
    inputObjects: ["maker", "brand_name", "amount", "price_usd"],
    decision: "Map source attributes to canonical fields or leave them unmapped.",
    outputObjects: ["brand", "price", "model_number", "specifications"],
    commonError: "A synonym can look obvious to a reader but weak to a name-only scorer.",
    baselineSummary: "Name and value evidence map maker to brand and amount to price.",
    llmSummary: "The LLM can help with synonyms, but unsupported target fields are rejected.",
    evidence: {
      deterministic: [
        { label: "Name match", value: "maker -> brand", detail: "High value-pattern compatibility." },
        { label: "Synonym", value: "amount -> price", detail: "Currency values support the mapping." }
      ],
      llm: [{ label: "LLM mapping", decision: "brand_name -> brand", detail: "Accepted because target is allowed.", status: "accepted" }],
      uncertainty: [{ label: "score margin", confidence: 0.64, detail: "amount had a narrow lead over description." }],
      provenance: [{ from: "source attribute", to: "mediated field", detail: "Mapping records explain downstream fields." }]
    }
  },
  {
    id: "normalization",
    title: "Normalization",
    shortTitle: "Normalize",
    story:
      "Equivalent values are standardized: EOS 4000D and EOS4000D become the same model token, while prices become comparable numbers.",
    inputObjects: ["EOS 4000D", "EOS4000D", "310 USD", "18.0 megapixels"],
    decision: "Canonicalize values while preserving raw values and units.",
    outputObjects: ["model_number=EOS4000D", "price=310.00 USD", "resolution=18 MP"],
    commonError: "Over-normalizing bundle text can erase details that matter during fusion.",
    baselineSummary: "Rules normalize model punctuation, currency, and measurement units.",
    llmSummary: "LLM assistance is withheld here in the MVP because normalization must be reproducible.",
    evidence: {
      deterministic: [
        { label: "Model rule", value: "EOS 4000D -> EOS4000D", detail: "Remove spacing and punctuation." },
        { label: "Unit rule", value: "megapixels -> MP", detail: "Known measurement alias." }
      ],
      llm: [{ label: "LLM", decision: "not used", detail: "No uncertain semantic parse in this toy stage.", status: "not-used" }],
      uncertainty: [{ label: "price parse", confidence: 0.73, detail: "Gamma Nikon price is invalid and preserved as a warning." }],
      provenance: [{ from: "raw value", to: "canonical value", detail: "Both forms remain inspectable." }]
    }
  },
  {
    id: "blocking",
    title: "Blocking",
    shortTitle: "Blocking",
    story:
      "Instead of comparing every pair, Mosaic keeps likely candidates using brand and model tokens.",
    inputObjects: ["28 possible cross-source record pairs"],
    decision: "Keep candidate pairs sharing strong identity tokens or rare title tokens.",
    outputObjects: ["9 candidate pairs", "19 skipped pairs", "blocking rule labels"],
    commonError: "Too strict a rule can miss a real match before linkage sees it.",
    baselineSummary: "Brand/model blocks keep obvious camera candidates and reduce pair volume.",
    llmSummary: "The LLM does not expand the candidate universe in this demo.",
    evidence: {
      deterministic: [
        { label: "Rule", value: "brand + model token", detail: "Canon 4000D records share enough identity evidence." },
        { label: "Reduction", value: "28 -> 9 pairs", detail: "Keeps the story inspectable." }
      ],
      llm: [{ label: "LLM", decision: "not used", detail: "Candidate generation stays deterministic.", status: "not-used" }],
      uncertainty: [{ label: "pair completeness", confidence: 0.91, detail: "Sony A6000KIT remains a borderline retained pair." }],
      provenance: [{ from: "normalized records", to: "candidate pairs", detail: "Each pair lists the rule that admitted it." }]
    }
  },
  {
    id: "linkage",
    title: "Record Linkage",
    shortTitle: "Linkage",
    story:
      "Candidate pairs become match, non-match, or uncertain decisions using title, brand, model, and specification agreement.",
    inputObjects: ["Canon alpha-a100 vs beta-b200", "Sony beta-b201 vs gamma-c301"],
    decision: "Classify each candidate pair with calibrated confidence.",
    outputObjects: ["6 matches", "3 non-matches", "1 borderline pair routed"],
    commonError: "A bundle or kit suffix can look like a different product or hide a true match.",
    baselineSummary: "The classical model accepts Canon and Sony pairs with high feature agreement.",
    llmSummary: "The LLM abstains on A6000 vs A6000KIT, so the hybrid path falls back to the deterministic decision.",
    evidence: {
      deterministic: [
        { label: "Feature", value: "brand exact + model close", detail: "Sony A6000 and A6000KIT share product family evidence." },
        { label: "Probability", value: "0.58", detail: "Borderline zone triggers routing." }
      ],
      llm: [{ label: "LLM pair review", decision: "ABSTAIN", detail: "Bundle text lacks enough support for a confident match.", status: "abstained" }],
      uncertainty: [{ label: "match confidence", confidence: 0.58, detail: "Near threshold; shown with uncertainty overlay." }],
      provenance: [{ from: "candidate pair", to: "match edge", detail: "Feature values and LLM response are preserved." }]
    }
  },
  {
    id: "clustering",
    title: "Entity Clustering",
    shortTitle: "Clusters",
    story:
      "Pairwise match edges form product clusters, while constraints prevent incompatible records from merging.",
    inputObjects: ["match edges", "same-source constraints", "model-family constraints"],
    decision: "Merge records into entity clusters only when constraints allow it.",
    outputObjects: ["Canon cluster", "Sony cluster", "Nikon cluster"],
    commonError: "One weak bridge can over-merge two products that never directly matched.",
    baselineSummary: "Constrained clustering forms three products and rejects incompatible model families.",
    llmSummary: "LLM evidence can influence pair edges, but clustering constraints remain deterministic.",
    evidence: {
      deterministic: [
        { label: "Constraint", value: "model family compatible", detail: "Canon EOS4000D records can merge." },
        { label: "Reject", value: "Canon != Nikon", detail: "Brand conflict blocks accidental bridge." }
      ],
      llm: [{ label: "LLM", decision: "indirect only", detail: "No direct cluster authority is granted to the model.", status: "not-used" }],
      uncertainty: [{ label: "cluster confidence", confidence: 0.78, detail: "Sony kit edge keeps a lower cluster confidence." }],
      provenance: [{ from: "match edge", to: "entity cluster", detail: "Cluster membership traces to accepted pair evidence." }]
    }
  },
  {
    id: "claims",
    title: "Claim Extraction",
    shortTitle: "Claims",
    story:
      "Clustered records produce attribute claims: each value says which source asserted it and how it was normalized.",
    inputObjects: ["Canon cluster records", "normalized attribute values"],
    decision: "Extract source-supported claims for each canonical attribute.",
    outputObjects: ["price claims", "model claims", "specification claims"],
    commonError: "A copied or stale value can look like independent support.",
    baselineSummary: "Claims preserve raw value, normalized value, source, and record reference.",
    llmSummary: "The LLM can later inspect conflicts, but it cannot invent unsupported claims.",
    evidence: {
      deterministic: [
        { label: "Claim", value: "price=305.00", detail: "Supported by Gamma Outlet c300." },
        { label: "Claim", value: "price=299.00", detail: "Supported by Alpha Catalog a100." }
      ],
      llm: [{ label: "LLM", decision: "not used", detail: "Claims are extracted from known fields only.", status: "not-used" }],
      uncertainty: [{ label: "support strength", confidence: 0.67, detail: "Price has multiple conflicting claims." }],
      provenance: [{ from: "cluster record", to: "attribute claim", detail: "Every claim links to a source record and raw value." }]
    }
  },
  {
    id: "fusion",
    title: "Data Fusion",
    shortTitle: "Fusion",
    story:
      "Conflicting claims become one canonical value while supporting and contradicting evidence remains visible.",
    inputObjects: ["299.00", "310.00", "305.00"],
    decision: "Choose a canonical value, abstain, or mark a value missing when support is unsafe.",
    outputObjects: ["Canon price=305.00", "supporting claim", "contradicting claims"],
    commonError: "Choosing a plausible value without claim support would be an unsupported hallucination.",
    baselineSummary: "Deterministic fusion picks the median-like supported Canon price.",
    llmSummary: "The LLM proposes 299.99 for Nikon; validation rejects it because no claim supports that value.",
    evidence: {
      deterministic: [
        { label: "Policy", value: "supported central price", detail: "Selects an observed claim, never a new value." },
        { label: "Conflict", value: "3 price claims", detail: "Contradictions stay attached." }
      ],
      llm: [{ label: "LLM fusion", decision: "invalid 299.99", detail: "Rejected: value is not in the claim set.", status: "invalid" }],
      uncertainty: [{ label: "fusion confidence", confidence: 0.65, detail: "Conflict lowers the final value confidence." }],
      provenance: [{ from: "attribute claim", to: "fused value", detail: "Supporting and contradicting claim IDs are retained." }]
    }
  },
  {
    id: "entities",
    title: "Integrated Entities",
    shortTitle: "Entities",
    story:
      "Fused values become integrated product entities with confidence and source membership.",
    inputObjects: ["fused brand", "fused model", "fused price", "cluster members"],
    decision: "Assemble an exportable product record with provenance metadata.",
    outputObjects: ["Canon EOS 4000D entity", "Sony A6000 entity", "Nikon D3500 entity"],
    commonError: "A tidy row can hide disagreements unless provenance remains inspectable.",
    baselineSummary: "Entities include canonical payloads, confidence, source count, and provenance.",
    llmSummary: "Assisted values carry the same validation and provenance requirements.",
    evidence: {
      deterministic: [
        { label: "Entity", value: "entity_000001", detail: "3 member records, confidence 0.65." },
        { label: "Payload", value: "canonical product fields", detail: "Ready for export and reporting." }
      ],
      llm: [{ label: "LLM", decision: "audited", detail: "Accepted assisted decisions remain distinguishable.", status: "accepted" }],
      uncertainty: [{ label: "overall confidence", confidence: 0.65, detail: "Aggregates linkage and fusion uncertainty." }],
      provenance: [{ from: "fused values", to: "integrated entity", detail: "Each field can be traced back to claims." }]
    }
  },
  {
    id: "metrics",
    title: "Metrics, Report, And Export",
    shortTitle: "Report",
    story:
      "The final stage compares deterministic, LLM-primary, and hybrid pipelines and packages report artifacts.",
    inputObjects: ["integrated entities", "metrics JSON", "error cases", "figures"],
    decision: "Report quality, cost, latency, invalid outputs, abstentions, and concrete errors.",
    outputObjects: ["report.pdf", "metrics tables", "error gallery", "final dataset preview"],
    commonError: "Reporting only accuracy hides cost, invalid outputs, and provenance risk.",
    baselineSummary: "Deterministic results provide the reproducible control.",
    llmSummary: "LLM and hybrid results are compared with defaults, fallbacks, and invalid outputs counted.",
    evidence: {
      deterministic: [
        { label: "Control", value: "A0", detail: "No model decisions." },
        { label: "Export", value: "JSONL entities", detail: "Static preview consumes export-shaped data." }
      ],
      llm: [{ label: "LLM accounting", decision: "calls and defaults counted", detail: "No failures are hidden.", status: "accepted" }],
      uncertainty: [{ label: "release status", confidence: 0.5, detail: "MVP uses fixture snapshots until live M4 runs land." }],
      provenance: [{ from: "run artifacts", to: "website snapshot", detail: "Pages identify fixture demo data explicitly." }]
    }
  }
];

export const conceptModules: ConceptModule[] = [
  {
    id: "schema",
    title: "Schema Alignment",
    prompt: "Where should Beta Market's `maker` field map?",
    interaction: "choice",
    options: ["brand", "model_number", "description"],
    deterministicAnswer: "brand",
    llmAnswer: "brand",
    lesson: "Name evidence is weak, but value evidence strongly suggests a brand field."
  },
  {
    id: "blocking",
    title: "Blocking",
    prompt: "Move from broad token blocks to stricter brand+model blocks.",
    interaction: "slider",
    options: ["Broad: 14 candidates", "Balanced: 9 candidates", "Strict: 5 candidates"],
    deterministicAnswer: "Balanced: 9 candidates",
    llmAnswer: "No LLM call",
    lesson: "Blocking is a recall-risk step: missed pairs cannot be recovered downstream."
  },
  {
    id: "linkage",
    title: "Record Linkage",
    prompt: "Are Sony A6000 and Sony A6000KIT the same product?",
    interaction: "pair",
    options: ["Match", "Non-match", "Unsure"],
    deterministicAnswer: "Match with low confidence",
    llmAnswer: "Abstain",
    lesson: "Borderline pairs should expose uncertainty instead of becoming magic model answers."
  },
  {
    id: "clustering",
    title: "Clustering",
    prompt: "Should a weak bridge merge Canon and Nikon clusters?",
    interaction: "choice",
    options: ["Merge", "Reject by brand constraint", "Ask for export"],
    deterministicAnswer: "Reject by brand constraint",
    llmAnswer: "No direct cluster authority",
    lesson: "Clustering uses constraints to stop a single bad edge from damaging many records."
  },
  {
    id: "fusion",
    title: "Fusion",
    prompt: "Which Canon price can be exported?",
    interaction: "choice",
    options: ["299.00", "305.00", "299.99"],
    deterministicAnswer: "305.00",
    llmAnswer: "299.99 is invalid",
    lesson: "Fusion may only select supported values or abstain."
  },
  {
    id: "routing",
    title: "LLM Routing",
    prompt: "Which cases should consume model budget?",
    interaction: "slider",
    options: ["Only low-confidence cases", "Every candidate", "No cases"],
    deterministicAnswer: "No model budget",
    llmAnswer: "Only low-confidence cases",
    lesson: "Selective routing preserves cost and reproducibility while still testing where the model helps."
  },
  {
    id: "provenance",
    title: "Provenance",
    prompt: "Trace Canon price back from entity to source.",
    interaction: "trace",
    options: ["entity -> fused value -> claims -> records", "entity -> model answer", "entity -> report only"],
    deterministicAnswer: "entity -> fused value -> claims -> records",
    llmAnswer: "Same trace plus prompt response when used",
    lesson: "Every final value needs a chain of support, especially when LLM evidence appears."
  }
];

export const reportMetrics: ReportMetricRow[] = [
  {
    reportLabel: "Deterministic",
    configurationId: "fixture-A0",
    schemaF1: 0.9697,
    blockingPairCompleteness: 1,
    blockingReductionRatio: 0.4667,
    candidatePairs: 8,
    clusterF1: 1,
    endToEndQuality: 0.4924
  },
  {
    reportLabel: "LLM",
    configurationId: "fixture-C-LLM",
    schemaF1: 1,
    blockingPairCompleteness: 1,
    blockingReductionRatio: 0.4667,
    candidatePairs: 8,
    clusterF1: 1,
    endToEndQuality: 0.5
  },
  {
    reportLabel: "Hybrid",
    configurationId: "fixture-B-All",
    schemaF1: 1,
    blockingPairCompleteness: 1,
    blockingReductionRatio: 0.4667,
    candidatePairs: 8,
    clusterF1: 1,
    endToEndQuality: 0.5
  }
];

export const operationalMetrics: OperationalMetricRow[] = [
  {
    reportLabel: "Deterministic",
    configurationId: "fixture-A0",
    eligibleCount: 0,
    selectedCount: 0,
    llmCallCount: 0,
    acceptedCount: 0,
    defaultedCount: 0,
    fallbackRate: 0,
    invalidOutputRate: 0,
    inputTokens: 0,
    outputTokens: 0
  },
  {
    reportLabel: "LLM",
    configurationId: "fixture-C-LLM",
    eligibleCount: 47,
    selectedCount: 47,
    llmCallCount: 24,
    acceptedCount: 47,
    defaultedCount: 0,
    fallbackRate: 0,
    invalidOutputRate: 0,
    inputTokens: 28161,
    outputTokens: 2770
  },
  {
    reportLabel: "Hybrid",
    configurationId: "fixture-B-All",
    eligibleCount: 23,
    selectedCount: 23,
    llmCallCount: 23,
    acceptedCount: 7,
    defaultedCount: 16,
    fallbackRate: 0.6957,
    invalidOutputRate: 0,
    inputTokens: 13792,
    outputTokens: 1418
  }
];

export const errorCases: ErrorCase[] = [
  {
    caseId: "schema_source_alpha//price",
    stage: "schema_alignment",
    explanation:
      "The source attribute was left unmapped, which can propagate into normalization and fusion.",
    systemOutput: {
      method: "deterministic_schema_v1",
      predicted_target_attribute_name: "UNMAPPED",
      score_total: 1,
      source_attribute_id: "source_alpha//price"
    },
    expectedOutput: { gold_target_attribute_name: "price" },
    sourceRecords: [toyRecords[0]],
    artifactLinks: {
      schema_errors: "artifacts/runs/.../schema/schema_false_positives.parquet",
      schema_metrics: "artifacts/runs/.../schema/assisted_schema_metrics.json"
    }
  },
  {
    caseId: "fusion_1_entity_000001",
    stage: "fusion",
    explanation:
      "The fused value disagrees with a curated or bootstrap fusion gold value because source claims conflict.",
    systemOutput: { attribute: "price", entity_id: "entity_000001", predicted_value: "305.00" },
    expectedOutput: { expected_value: "None", truth_entity_id: "ENTITY#001" },
    sourceRecords: [toyRecords[0], toyRecords[1], toyRecords[2]],
    artifactLinks: {
      fused_values: "artifacts/runs/.../fusion/assisted_fused_values.parquet",
      fusion_metrics: "artifacts/runs/.../fusion/assisted_fusion_metrics.json"
    }
  },
  {
    caseId: "llm_invalid_nikon_price",
    stage: "fusion",
    explanation:
      "The LLM proposed a plausible price that was not supported by any extracted source claim, so validation rejected it.",
    systemOutput: { attribute: "price", proposed_value: "299.99", validation_status: "unsupported" },
    expectedOutput: { allowed_outcome: "supported claim or abstain" },
    sourceRecords: [toyRecords[6], toyRecords[7]],
    artifactLinks: {
      call_log: "artifacts/llm_calls/fixture-demo/nikon-price.json",
      fused_values: "artifacts/runs/.../fusion/assisted_fused_values.parquet"
    }
  }
];

export const integratedEntities: IntegratedEntityPreview[] = [
  {
    entityId: "entity_000001",
    title: "Canon EOS 4000D DSLR Camera Kit",
    brand: "Canon",
    modelNumber: "EOS4000D",
    category: "camera",
    price: "305.00 USD",
    confidence: 0.65,
    sourceCount: 3,
    memberRecords: ["alpha-a100", "beta-b200", "gamma-c300"],
    provenance: {
      price: {
        supportingClaimIds: ["claim_gamma_price_305"],
        contradictingClaimIds: ["claim_alpha_price_299", "claim_beta_price_310"]
      },
      model_number: {
        supportingClaimIds: ["claim_alpha_eos4000d", "claim_gamma_eos4000d"],
        contradictingClaimIds: ["claim_beta_4000d"]
      }
    }
  },
  {
    entityId: "entity_000002",
    title: "Sony Alpha A6000 Mirrorless Camera",
    brand: "Sony",
    modelNumber: "A6000",
    category: "mirrorless camera",
    price: "540.00 USD",
    confidence: 0.62,
    sourceCount: 3,
    memberRecords: ["alpha-a101", "beta-b201", "gamma-c301"],
    provenance: {
      price: {
        supportingClaimIds: ["claim_alpha_price_540"],
        contradictingClaimIds: ["claim_beta_price_525", "claim_gamma_price_560"]
      },
      model_number: {
        supportingClaimIds: ["claim_alpha_a6000", "claim_beta_ilce6000"],
        contradictingClaimIds: ["claim_gamma_a6000kit"]
      }
    }
  },
  {
    entityId: "entity_000003",
    title: "Nikon D3500 DSLR Camera",
    brand: "Nikon",
    modelNumber: "D3500",
    category: "camera",
    price: "missing",
    confidence: 0.54,
    sourceCount: 2,
    memberRecords: ["alpha-a102", "gamma-c302"],
    provenance: {
      price: {
        supportingClaimIds: ["claim_alpha_price_415"],
        contradictingClaimIds: ["claim_gamma_invalid_price"]
      },
      model_number: {
        supportingClaimIds: ["claim_alpha_d3500"],
        contradictingClaimIds: ["claim_gamma_d3500kit"]
      }
    }
  }
];
