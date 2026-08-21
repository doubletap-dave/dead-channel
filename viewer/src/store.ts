import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import type {
  AssessmentView,
  BeliefView,
  ContactView,
  DecisionView,
  RoleId,
  RunConfigView,
  RunView,
  SimEvent,
  StateId,
  StateSnapshotView,
} from "./types";
import { createRun, openStream, startRun as apiStartRun, stopRun as apiStopRun } from "./api/client";
import { FIXTURE_EVENTS } from "./api/fixtures";

const STATES: readonly StateId[] = ["northstar", "vesper"] as const;
const ROLES: readonly RoleId[] = [
  "head_of_state",
  "intelligence_chief",
  "military_chief",
  "diplomat",
] as const;
const RESOURCE_ATTRIBUTES: readonly string[] = [
  "economy",
  "energy",
  "food",
  "military",
  "research",
] as const;

// TODO(T5.1): replace this derivation with a backend `verified` field when available.
const VERIFIED_THRESHOLD = 0.75;

const emptySnapshot = (state: StateId): StateSnapshotView => ({
  state,
  threat: 0,
  readinessBelieved: 0,
  beliefs: [],
  trust: {
    head_of_state: 0.5,
    intelligence_chief: 0.5,
    military_chief: 0.5,
    diplomat: 0.5,
  },
  resources: {},
});

const emptyRun = (): RunView => ({
  runId: "",
  turn: 0,
  defcon: 5,
  conflict: false,
  states: { northstar: emptySnapshot("northstar"), vesper: emptySnapshot("vesper") },
  events: [],
  decisions: [],
  assessmentsByState: { northstar: [], vesper: [] },
  latestDecisionByState: { northstar: null, vesper: null },
  contacts: [],
  status: "config",
});

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

const asString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const isStateId = (value: unknown): value is StateId =>
  value === "northstar" || value === "vesper";

const isRoleId = (value: unknown): value is RoleId =>
  typeof value === "string" && (ROLES as readonly string[]).includes(value);

const contactId = (event: SimEvent, observer: StateId, runId: string): string =>
  `${runId}-${event.seq}-${observer}`;

const contactKind = (raw: unknown): ContactView["kind"] => {
  if (raw === "exercise" || raw === "movement" || raw === "planted_suspicion") return raw;
  return "readiness_report";
};

// The single event → RunView reducer. The live SSE feed (next round) feeds this
// same function; loadFixture is just applyEvent over an array.
function reduceEvent(run: RunView, event: SimEvent): RunView {
  const next: RunView = {
    ...run,
    events: [...run.events, event],
    turn: Math.max(run.turn, event.turn),
  };
  const payload = event.payload;

  switch (event.type) {
    case "run.started": {
      next.status = "running";
      next.runId = asString(payload.runId, `fixture-${asString(payload.seed, "0")}`);
      next.states = {
        northstar: emptySnapshot("northstar"),
        vesper: emptySnapshot("vesper"),
      };
      next.assessmentsByState = { northstar: [], vesper: [] };
      next.latestDecisionByState = { northstar: null, vesper: null };
      break;
    }
    case "run.ended": {
      next.status = "complete";
      break;
    }
    case "run.stopped": {
      next.status = "stopped";
      break;
    }
    case "threat.updated": {
      if (!isStateId(payload.state)) break;
      const snapshot = next.states[payload.state];
      next.states = {
        ...next.states,
        [payload.state]: {
          ...snapshot,
          threat: asNumber(payload.threat, snapshot.threat),
        },
      };
      const defcon = asNumber(payload.defcon, next.defcon);
      next.defcon = defcon;
      next.conflict = next.conflict || defcon === 1;
      break;
    }
    case "conflict.threshold_crossed": {
      next.conflict = true;
      break;
    }
    case "assessment.made": {
      if (!isStateId(payload.state) || !isRoleId(payload.role)) break;
      const claim = (payload.claim ?? {}) as Record<string, unknown>;
      const action = (payload.recommended_action ?? {}) as Record<string, unknown>;
      const assessment: AssessmentView = {
        state: payload.state,
        role: payload.role,
        turn: event.turn,
        interpretation: asString(payload.interpretation),
        claim: {
          subject: asString(claim.subject),
          direction: asString(claim.direction),
          magnitude: asNumber(claim.magnitude),
        },
        recommendedAction: asString(action.kind),
        urgency: asNumber(payload.urgency),
        dissent: typeof payload.dissent === "string" ? payload.dissent : null,
      };
      next.assessmentsByState = {
        ...next.assessmentsByState,
        [payload.state]: [...next.assessmentsByState[payload.state], assessment],
      };
      break;
    }
    case "claim.scored": {
      if (!isStateId(payload.state) || !isRoleId(payload.role)) break;
      const outcome = asNumber(payload.outcome, 0.5);
      const snapshot = next.states[payload.state];
      const prior = snapshot.trust[payload.role];
      const blended = prior + (outcome - prior) * 0.5;
      next.states = {
        ...next.states,
        [payload.state]: {
          ...snapshot,
          trust: { ...snapshot.trust, [payload.role]: blended },
        },
      };
      break;
    }
    case "decision.made": {
      if (!isStateId(payload.state)) break;
      const action = (payload.action ?? {}) as Record<string, unknown>;
      const decision: DecisionView = {
        state: payload.state,
        turn: event.turn,
        action: asString(action.kind),
        rationale: asString(payload.rationale),
      };
      next.decisions = [...next.decisions, decision];
      next.latestDecisionByState = { ...next.latestDecisionByState, [payload.state]: decision };
      break;
    }
    case "contact.detected": {
      if (!isStateId(payload.observer)) break;
      const contact: ContactView = {
        id: contactId(event, payload.observer, run.runId),
        turn: event.turn,
        observer: payload.observer,
        kind: contactKind(payload.kind),
        lat: asNumber(payload.lat),
        lon: asNumber(payload.lon),
        confidence: asNumber(payload.confidence),
        verified: asNumber(payload.confidence) >= VERIFIED_THRESHOLD,
        label: asString(payload.detail, asString(payload.kind, "contact")),
      };
      next.contacts = [...next.contacts, contact];
      break;
    }
    case "report.rendered": {
      if (!isStateId(payload.observer)) break;
      const snapshot = next.states[payload.observer];
      const attribute = asString(payload.attribute);
      if (!attribute) break;
      const value = asNumber(payload.value);
      const confidence = asNumber(payload.confidence);
      const beliefs: BeliefView[] = [
        ...snapshot.beliefs.filter((belief) => belief.attribute !== attribute),
        { attribute, value, confidence },
      ].sort((a, b) => a.attribute.localeCompare(b.attribute));
      const resources = RESOURCE_ATTRIBUTES.includes(attribute)
        ? { ...snapshot.resources, [attribute]: value }
        : snapshot.resources;
      next.states = {
        ...next.states,
        [payload.observer]: {
          ...snapshot,
          beliefs,
          resources,
          readinessBelieved:
            attribute === "readiness"
              ? value
              : snapshot.readinessBelieved,
        },
      };
      break;
    }
    default:
      break;
  }
  return next;
}

interface RunStore {
  run: RunView;
  selectedEventSeq: number | null;
  applyEvent: (event: SimEvent) => void;
  loadFixture: (events: SimEvent[]) => void;
  startRun: (config: RunConfigView) => void;
  stopRun: () => Promise<void>;
  resumeRun: () => void;
  selectEvent: (seq: number | null) => void;
}

let activeStream: EventSource | null = null;

const closeStream = (): void => {
  activeStream?.close();
  activeStream = null;
};

const follow = (runId: string): void => {
  closeStream();
  activeStream = openStream(
    runId,
    (event) => useRunStore.getState().applyEvent(event),
    () => {
      activeStream = null;
    },
  );
};

const useRunStore = create<RunStore>((set) => ({
  run: emptyRun(),
  selectedEventSeq: null,
  applyEvent: (event) =>
    set((state) => ({ run: reduceEvent(state.run, event) })),
  loadFixture: (events) =>
    set(() => ({ run: events.reduce(reduceEvent, emptyRun()), selectedEventSeq: null })),
  startRun: (config) => {
    closeStream();
    set(() => ({ run: { ...emptyRun(), status: "running" }, selectedEventSeq: null }));
    void (async () => {
      try {
        const { runId } = await createRun(config);
        await apiStartRun(runId);
        follow(runId);
      } catch (error) {
        // Backend unreachable: fall back to the built-in fixture so the
        // ops-room remains demoable without the stack running.
        console.warn("live backend unavailable, falling back to fixture", error);
        set(() => ({ run: FIXTURE_EVENTS.reduce(reduceEvent, emptyRun()) }));
      }
    })();
  },
  stopRun: async () => {
    const runId = useRunStore.getState().run.runId;
    if (!runId) return;
    // The stream stays open until the backend logs run.stopped, which flips
    // status via reduceEvent — no optimistic status flip here.
    await apiStopRun(runId).catch((error) => console.warn("stop failed", error));
  },
  resumeRun: () => {
    const { runId } = useRunStore.getState().run;
    if (!runId) return;
    set(() => ({ run: { ...useRunStore.getState().run, status: "running" } }));
    void (async () => {
      try {
        await apiStartRun(runId);
        follow(runId);
      } catch (error) {
        console.warn("resume failed", error);
        set(() => ({ run: { ...useRunStore.getState().run, status: "stopped" } }));
      }
    })();
  },
  selectEvent: (seq) => set(() => ({ selectedEventSeq: seq })),
}));

export interface RunMeta {
  runId: string;
  turn: number;
  status: RunView["status"];
  defcon: number;
  conflict: boolean;
}

export function useRunMeta(): RunMeta {
  return useRunStore(
    useShallow((state) => ({
      runId: state.run.runId,
      turn: state.run.turn,
      status: state.run.status,
      defcon: state.run.defcon,
      conflict: state.run.conflict,
    })),
  );
}

export function useRunStatus(): RunView["status"] {
  return useRunStore((state) => state.run.status);
}

export interface StateFeed {
  assessments: AssessmentView[];
  decision: DecisionView | null;
  trust: Record<RoleId, number>;
  threat: number;
  beliefs: BeliefView[];
  resources: Record<string, number>;
}

export function useStateFeed(state: StateId): StateFeed {
  return useRunStore(
    useShallow(({ run }) => {
      const snapshot = run.states[state];
      return {
        assessments: run.assessmentsByState[state],
        decision: run.latestDecisionByState[state],
        trust: snapshot.trust,
        threat: snapshot.threat,
        beliefs: snapshot.beliefs,
        resources: snapshot.resources,
      };
    }),
  );
}

export function useContacts(): ContactView[] {
  return useRunStore((state) => state.run.contacts);
}

export function useTimeline(): SimEvent[] {
  return useRunStore((state) => state.run.events);
}

export function useSelectedEvent(): SimEvent | null {
  return useRunStore((state) =>
    state.selectedEventSeq === null
      ? null
      : (state.run.events.find((event) => event.seq === state.selectedEventSeq) ?? null),
  );
}

export function useSelectEvent(): (seq: number | null) => void {
  return useRunStore((state) => state.selectEvent);
}

export function useStartRun(): (config: RunConfigView) => void {
  return useRunStore((state) => state.startRun);
}

export function useRunControls(): { stopRun: () => Promise<void>; resumeRun: () => void } {
  return useRunStore(useShallow((state) => ({ stopRun: state.stopRun, resumeRun: state.resumeRun })));
}

const dispatch = <K extends keyof RunStore>(key: K): RunStore[K] =>
  useRunStore.getState()[key];

export const applyEvent = (event: SimEvent): void => dispatch("applyEvent")(event);
export const loadFixture = (events: SimEvent[]): void => dispatch("loadFixture")(events);
export const startRun = (config: RunConfigView): void => dispatch("startRun")(config);
export const selectEvent = (seq: number | null): void => dispatch("selectEvent")(seq);

export { STATES, ROLES };
