export type StateId = "northstar" | "vesper";
export type RoleId = "head_of_state" | "intelligence_chief" | "military_chief" | "diplomat";

export interface SimEvent {
  seq: number;
  turn: number;
  type: string;
  payload: Record<string, unknown>;
}

export interface AssessmentView {
  state: StateId;
  role: RoleId;
  turn: number;
  interpretation: string;
  claim: { subject: string; direction: string; magnitude: number };
  recommendedAction: string;
  urgency: number;
  dissent?: string | null;
}

export interface DecisionView {
  state: StateId;
  turn: number;
  action: string;
  rationale: string;
}

export interface ContactView {
  id: string;
  turn: number;
  observer: StateId;
  kind: "exercise" | "movement" | "readiness_report" | "planted_suspicion";
  lat: number;
  lon: number;
  confidence: number;
  verified: boolean;
  label: string;
}

export interface BeliefView {
  attribute: string;
  value: number;
  confidence: number;
}

export interface StateSnapshotView {
  state: StateId;
  threat: number;
  readinessBelieved: number;
  beliefs: BeliefView[];
  trust: Record<RoleId, number>;
  resources: Record<string, number>;
}

export interface RunView {
  runId: string;
  turn: number;
  defcon: number;
  conflict: boolean;
  states: Record<StateId, StateSnapshotView>;
  events: SimEvent[];
  decisions: DecisionView[];
  assessmentsByState: Record<StateId, AssessmentView[]>;
  latestDecisionByState: Record<StateId, DecisionView | null>;
  contacts: ContactView[];
  status: "config" | "running" | "stopped" | "complete";
}

export interface RunConfigView {
  seed: number;
  turns: number;
  modelMatrix: { default: string; states: Record<string, Record<string, string>> };
}
