export type PipelineMode = "baseline" | "llm";

export interface PipelineDemoState {
  stageIndex: number;
  isPlaying: boolean;
  mode: PipelineMode;
  showUncertainty: boolean;
  showProvenance: boolean;
}

export function createPipelineState(): PipelineDemoState {
  return {
    stageIndex: 0,
    isPlaying: false,
    mode: "baseline",
    showUncertainty: true,
    showProvenance: true
  };
}

export function setStage(state: PipelineDemoState, stageIndex: number, stageCount: number): PipelineDemoState {
  return { ...state, stageIndex: clampStage(stageIndex, stageCount) };
}

export function stepStage(state: PipelineDemoState, direction: -1 | 1, stageCount: number): PipelineDemoState {
  return setStage(state, state.stageIndex + direction, stageCount);
}

export function advancePlayback(state: PipelineDemoState, stageCount: number): PipelineDemoState {
  if (stageCount <= 0) return state;
  return { ...state, stageIndex: (state.stageIndex + 1) % stageCount };
}

export function resetPipelineState(): PipelineDemoState {
  return createPipelineState();
}

function clampStage(stageIndex: number, stageCount: number): number {
  if (stageCount <= 0) return 0;
  return Math.min(Math.max(stageIndex, 0), stageCount - 1);
}
