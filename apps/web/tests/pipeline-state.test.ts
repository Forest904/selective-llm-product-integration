import { describe, expect, it } from "vitest";
import {
  advancePlayback,
  createPipelineState,
  resetPipelineState,
  setStage,
  stepStage
} from "@/lib/pipeline-state";

describe("pipeline state", () => {
  it("steps within stage boundaries", () => {
    const initial = createPipelineState();
    expect(stepStage(initial, -1, 10).stageIndex).toBe(0);
    expect(stepStage(initial, 1, 10).stageIndex).toBe(1);
    expect(setStage(initial, 99, 10).stageIndex).toBe(9);
  });

  it("wraps playback and restores the complete initial state", () => {
    const lastStage = { ...createPipelineState(), stageIndex: 9, isPlaying: true, mode: "llm" as const };
    expect(advancePlayback(lastStage, 10).stageIndex).toBe(0);
    expect(resetPipelineState()).toEqual(createPipelineState());
  });
});
