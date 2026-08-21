import type { AssessmentView, RoleId, SimEvent, StateId } from "../types";
import { useContacts, useRunControls, useRunMeta, useSelectEvent, useSelectedEvent, useStateFeed, useTimeline, ROLES } from "../store";
import { MapPanel } from "./panels/MapPanel";
import { Panel } from "./Panel";

const ROLE_LABEL: Record<RoleId, string> = {
  head_of_state: "Head of State",
  intelligence_chief: "Intel Chief",
  military_chief: "Mil Chief",
  diplomat: "Diplomat",
};

// TODO(next-round): replace with the real EventDrawer (panels/EventDrawer.tsx).
const EventDrawer = () => {
  const event = useSelectedEvent();
  if (!event) return null;
  return (
    <div className="feed-block" role="region" aria-label="Selected event detail">
      <div className="feed-turn">
        seq {event.seq} · turn {event.turn} · {event.type}
      </div>
      <pre className="payload-view">{JSON.stringify(event.payload, null, 2)}</pre>
    </div>
  );
};

function Urgency({ level }: { level: number }) {
  const clamped = Math.min(5, Math.max(0, Math.trunc(level)));
  const cls = clamped >= 4 ? "urgency-hot" : clamped === 3 ? "urgency-warm" : "";
  return (
    <span className={`urgency ${cls}`}>
      {"▮".repeat(clamped)}
      {"▯".repeat(5 - clamped)}
    </span>
  );
}

function AssessmentBlock({ assessment }: { assessment: AssessmentView }) {
  return (
    <div className="feed-block">
      <div>
        <span className="feed-role">{ROLE_LABEL[assessment.role]}</span>{" "}
        <span className="feed-turn">T{assessment.turn}</span>{" "}
        <Urgency level={assessment.urgency} />
      </div>
      <p className="feed-text">{assessment.interpretation}</p>
      <p className="claim">
        claim: <b>{assessment.claim.subject}</b> {assessment.claim.direction} ·{" "}
        {assessment.claim.magnitude.toFixed(0)} · recommends {assessment.recommendedAction}
      </p>
      {assessment.dissent && <p className="feed-dissent">{assessment.dissent}</p>}
    </div>
  );
}

function StateFeedPanel({ state }: { state: StateId }) {
  const feed = useStateFeed(state);
  const accent = feed.threat >= 60 ? "red" : feed.threat >= 35 ? "amber" : "green";
  const title = `${state} · threat ${feed.threat.toFixed(1)}`;
  return (
    <Panel
      title={title}
      accent={accent}
      className={state === "northstar" ? "ops-feed-northstar" : "ops-feed-vesper"}
    >
      <div className="threat-line">
        <span>readiness (believed)</span>
        <span>{feed.beliefs.find((b) => b.attribute === "readiness")?.value.toFixed(1) ?? "—"}</span>
      </div>
      <div className="threat-line">
        <span>resources</span>
        <span className="claim">
          {Object.entries(feed.resources)
            .map(([kind, value]) => `${kind} ${value.toFixed(0)}`)
            .join(" · ") || "—"}
        </span>
      </div>
      <div className="threat-line">
        <span>trust</span>
        <span className="claim">
          {ROLES.map((role) => `${ROLE_LABEL[role].slice(0, 4)} ${feed.trust[role].toFixed(2)}`).join(" · ")}
        </span>
      </div>
      <div className="threat-line">
        <span>latest decision</span>
        <span className="decision-line">{feed.decision?.action ?? "—"}</span>
      </div>
      {[...feed.assessments].reverse().map((assessment) => (
        <AssessmentBlock key={`${assessment.turn}-${assessment.role}`} assessment={assessment} />
      ))}
    </Panel>
  );
}

function TopBar() {
  const meta = useRunMeta();
  const { stopRun, resumeRun } = useRunControls();
  return (
    <header className="panel ops-topbar">
      <div className="topbar-item">
        <span className="topbar-label">DEFCON</span>
        <div className="defcon-meter">
          {/* Segments light from the calm (green) end toward red as DEFCON tightens. */}
          {[1, 2, 3, 4, 5].map((level) => (
            <span
              key={level}
              className={`defcon-seg on-${level}${level >= meta.defcon ? " on" : ""}`}
            />
          ))}
          <span className="topbar-value">{meta.defcon}</span>
        </div>
      </div>
      <div className="topbar-item">
        <span className="topbar-label">Turn</span>
        <span className="topbar-value">{meta.turn}</span>
      </div>
      <div className="topbar-item">
        <span className="topbar-label">Run</span>
        <span className={`topbar-value status-${meta.status}`}>{meta.runId || "—"}</span>
      </div>
      <div className="topbar-item">
        <span className="topbar-label">Status</span>
        <span className={`topbar-value status-${meta.status}`}>{meta.status}</span>
      </div>
      {meta.conflict && (
        <div className="topbar-item">
          <span className="topbar-label">Alert</span>
          <span className="conflict-flag">■ CONFLICT</span>
        </div>
      )}
      {meta.status === "running" && (
        <button type="button" className="btn-run-control" onClick={() => void stopRun()}>
          ■ stop
        </button>
      )}
      {meta.status === "stopped" && (
        <button type="button" className="btn-run-control" onClick={resumeRun}>
          ▶ resume
        </button>
      )}
      <div className="topbar-spacer" />
    </header>
  );
}

function TimelinePanel() {
  const events = useTimeline();
  const contacts = useContacts();
  const selected = useSelectedEvent();
  const selectEvent = useSelectEvent();
  return (
    <Panel title={`Event Log · ${events.length} events · ${contacts.length} contacts`} className="ops-timeline">
      {events.map((event: SimEvent) => (
        <button
          key={event.seq}
          type="button"
          className={`timeline-row${selected?.seq === event.seq ? " selected" : ""}`}
          aria-pressed={selected?.seq === event.seq}
          onClick={() => selectEvent(selected?.seq === event.seq ? null : event.seq)}
        >
          <span className="timeline-seq">{event.seq}</span>
          <span className="timeline-turn">T{event.turn}</span>
          <span className={`event-type-${event.type}`}>{event.type}</span>
        </button>
      ))}
      <EventDrawer />
    </Panel>
  );
}

export function OpsRoom() {
  const contacts = useContacts();
  return (
    <div className="ops-room">
      <TopBar />
      <StateFeedPanel state="northstar" />
      <MapPanel contacts={contacts} />
      <StateFeedPanel state="vesper" />
      <TimelinePanel />
    </div>
  );
}
