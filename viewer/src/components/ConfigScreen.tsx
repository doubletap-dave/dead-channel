import { useState } from "react";
import type { RunConfigView, StateId } from "../types";
import { STATES, useStartRun } from "../store";
import { ModelCatalog } from "./ModelCatalog";
import { Panel } from "./Panel";

const ROLE_OPTIONS: readonly { id: string; label: string }[] = [
  { id: "head_of_state", label: "Head of State" },
  { id: "intelligence_chief", label: "Intelligence Chief" },
  { id: "military_chief", label: "Military Chief" },
  { id: "diplomat", label: "Diplomat" },
] as const;

type Matrix = RunConfigView["modelMatrix"]["states"];

interface MatrixStateProps {
  stateId: StateId;
  matrix: Matrix;
  onChange: (stateId: StateId, role: string, model: string) => void;
}

function MatrixState({ stateId, matrix, onChange }: MatrixStateProps) {
  const overrides = matrix[stateId] ?? {};
  return (
    <details className="config-state">
      <summary>
        {stateId} · {Object.keys(overrides).length} override(s)
      </summary>
      <div className="config-state-grid">
        {ROLE_OPTIONS.map(({ id, label }) => (
          <label className="config-field" key={id}>
            <span className="config-field-label">{label}</span>
            <input
              type="text"
              list="models-all"
              placeholder="(global default)"
              value={overrides[id] ?? ""}
              onChange={(event) => onChange(stateId, id, event.target.value)}
            />
          </label>
        ))}
      </div>
    </details>
  );
}

function pruneEmpty(matrix: Matrix): Matrix {
  const pruned: Matrix = {};
  for (const [stateId, roles] of Object.entries(matrix)) {
    const kept = Object.fromEntries(Object.entries(roles).filter(([, m]) => m !== ""));
    if (Object.keys(kept).length > 0) pruned[stateId] = kept;
  }
  return pruned;
}

export function ConfigScreen() {
  const startRun = useStartRun();
  const [seed, setSeed] = useState(1);
  const [turns, setTurns] = useState(40);
  const [defaultModel, setDefaultModel] = useState<string>("");
  const [matrix, setMatrix] = useState<Matrix>({});

  const handleStateChange = (stateId: StateId, role: string, model: string) => {
    setMatrix((prev) => ({
      ...prev,
      [stateId]: { ...(prev[stateId] ?? {}), [role]: model },
    }));
  };

  const handleSubmit = () => {
    if (!Number.isFinite(seed) || !Number.isFinite(turns)) return;
    if (!defaultModel.trim()) return;
    const config: RunConfigView = {
      seed,
      turns,
      modelMatrix: { default: defaultModel.trim(), states: pruneEmpty(matrix) },
    };
    startRun(config);
  };

  return (
    <div className="config-screen">
      <Panel title="Dead Channel · Run Configuration" className="config-panel">
        <form
          className="config-form"
          onSubmit={(event) => {
            event.preventDefault();
            handleSubmit();
          }}
        >
          <div className="config-row">
            <label className="config-field">
              <span className="config-field-label">Seed</span>
              <input
                type="number"
                value={Number.isNaN(seed) ? "" : seed}
                min={0}
                required
                onChange={(event) => setSeed(event.target.valueAsNumber)}
              />
            </label>
            <label className="config-field">
              <span className="config-field-label">Turns</span>
              <input
                type="number"
                value={Number.isNaN(turns) ? "" : turns}
                min={1}
                max={200}
                required
                onChange={(event) => setTurns(event.target.valueAsNumber)}
              />
            </label>
          </div>

          <label className="config-field">
            <span className="config-field-label">Global Default Model (provider:model)</span>
            <input
              type="text"
              list="models-all"
              required
              placeholder="load a catalog below, then pick or type e.g. openrouter:stealth/ox-alpha"
              value={defaultModel}
              onChange={(event) => setDefaultModel(event.target.value)}
            />
          </label>

          <ModelCatalog />

          {STATES.map((stateId) => (
            <MatrixState
              key={stateId}
              stateId={stateId}
              matrix={matrix}
              onChange={handleStateChange}
            />
          ))}

          <button
            className="btn-start"
            type="submit"
            disabled={!defaultModel.trim()}
            title="set the global default model to enable"
          >
            ▶ Start Run
          </button>
        </form>
      </Panel>
    </div>
  );
}
