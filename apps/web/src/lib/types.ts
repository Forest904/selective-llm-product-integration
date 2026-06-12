export type EvidenceKind = "deterministic" | "llm" | "uncertainty" | "provenance";

export interface ToySourceRecord {
  id: string;
  source: string;
  sourceLabel: string;
  productTruth: string;
  fields: Record<string, string>;
}

export interface DeterministicEvidence {
  label: string;
  value: string;
  detail: string;
}

export interface LlmEvidence {
  label: string;
  decision: string;
  detail: string;
  status: "accepted" | "abstained" | "invalid" | "not-used";
}

export interface UncertaintySignal {
  label: string;
  confidence: number;
  detail: string;
}

export interface ProvenanceLink {
  from: string;
  to: string;
  detail: string;
}

export interface StageEvidence {
  deterministic: DeterministicEvidence[];
  llm: LlmEvidence[];
  uncertainty: UncertaintySignal[];
  provenance: ProvenanceLink[];
}

export interface PipelineStage {
  id: string;
  title: string;
  shortTitle: string;
  story: string;
  inputObjects: string[];
  decision: string;
  outputObjects: string[];
  commonError: string;
  baselineSummary: string;
  llmSummary: string;
  evidence: StageEvidence;
}

export interface ConceptModule {
  id: string;
  title: string;
  prompt: string;
  interaction: "choice" | "slider" | "pair" | "trace";
  options: string[];
  deterministicAnswer: string;
  llmAnswer: string;
  lesson: string;
}

export interface ReportMetricRow {
  reportLabel: string;
  configurationId: string;
  schemaF1: number;
  blockingPairCompleteness: number;
  blockingReductionRatio: number;
  candidatePairs: number;
  clusterF1: number;
  endToEndQuality: number;
}

export interface OperationalMetricRow {
  reportLabel: string;
  configurationId: string;
  eligibleCount: number;
  selectedCount: number;
  llmCallCount: number;
  acceptedCount: number;
  defaultedCount: number;
  fallbackRate: number;
  invalidOutputRate: number;
  inputTokens: number;
  outputTokens: number;
}

export interface ErrorCase {
  caseId: string;
  stage: string;
  explanation: string;
  systemOutput: unknown;
  expectedOutput: unknown;
  sourceRecords: ToySourceRecord[];
  artifactLinks: Record<string, string>;
}

export interface IntegratedEntityPreview {
  entityId: string;
  title: string;
  brand: string;
  modelNumber: string;
  category: string;
  price: string;
  confidence: number;
  sourceCount: number;
  memberRecords: string[];
  provenance: Record<
    string,
    {
      supportingClaimIds: string[];
      contradictingClaimIds: string[];
    }
  >;
}
