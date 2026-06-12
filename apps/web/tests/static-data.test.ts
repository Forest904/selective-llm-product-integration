import { describe, expect, it } from "vitest";
import {
  errorCases,
  integratedEntities,
  operationalMetrics,
  pipelineStages,
  reportMetrics,
  toyRecords
} from "@/lib/demo-data";

describe("static demo data", () => {
  it("contains the planned toy data shape", () => {
    expect(new Set(toyRecords.map((record) => record.source))).toHaveLength(3);
    expect(toyRecords).toHaveLength(8);
    expect(new Set(toyRecords.map((record) => record.productTruth))).toHaveLength(3);
  });

  it("covers all required pipeline stages with evidence", () => {
    expect(pipelineStages).toHaveLength(10);
    for (const stage of pipelineStages) {
      expect(stage.evidence.deterministic.length).toBeGreaterThan(0);
      expect(stage.evidence.llm.length).toBeGreaterThan(0);
      expect(stage.evidence.uncertainty.length).toBeGreaterThan(0);
      expect(stage.evidence.provenance.length).toBeGreaterThan(0);
      expect(stage.commonError).toBeTruthy();
    }
  });

  it("includes fixture results, error cases, and integrated entities", () => {
    expect(reportMetrics.map((row) => row.reportLabel)).toEqual(["Deterministic", "LLM", "Hybrid"]);
    expect(operationalMetrics.some((row) => row.llmCallCount > 0)).toBe(true);
    expect(errorCases.length).toBeGreaterThanOrEqual(3);
    expect(integratedEntities.length).toBe(3);
  });
});
