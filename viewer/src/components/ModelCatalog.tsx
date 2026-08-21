import { useCallback, useEffect, useState } from "react";
import {
  PROVIDERS,
  fetchAllCatalogs,
  fetchCatalogs,
  fetchKeys,
  setKey,
  type CatalogResult,
  type KeysStatus,
  type ModelInfoView,
} from "../api/client";

interface ProviderCatalog {
  models: ModelInfoView[];
  error: string | null;
}

type Catalogs = Record<string, ProviderCatalog>;

function summarize(results: CatalogResult[]): { catalogs: Catalogs; loaded: number; problems: string[] } {
  const catalogs: Catalogs = {};
  const problems: string[] = [];
  let loaded = 0;
  for (const result of results) {
    catalogs[result.provider] = { models: result.models, error: result.error };
    if (result.error) {
      problems.push(`${result.provider}: ${result.error}`);
    } else if (result.models.length === 0) {
      problems.push(`${result.provider}: no key set`);
    } else {
      loaded += result.models.length;
    }
  }
  return { catalogs, loaded, problems };
}

function KeysPanel({ keys, onSaved }: { keys: KeysStatus | null; onSaved: () => void }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async (provider: string) => {
    const value = (drafts[provider] ?? "").trim();
    if (!value) return;
    setBusy(provider);
    setError(null);
    try {
      await setKey(provider, value);
      setDrafts((prev) => ({ ...prev, [provider]: "" }));
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  return (
    <details className="config-state">
      <summary>API Keys</summary>
      <div className="config-state-grid">
        {PROVIDERS.map((provider) => {
          const entry = keys?.providers[provider];
          return (
            <label className="config-field" key={provider}>
              <span className="config-field-label">
                {provider}
                {entry?.set ? ` · saved (${entry.masked})` : " · not set"}
              </span>
              <div className="config-key-row">
                <input
                  type="password"
                  autoComplete="off"
                  placeholder={entry?.set ? "replace key" : "paste key"}
                  value={drafts[provider] ?? ""}
                  onChange={(event) =>
                    setDrafts((prev) => ({ ...prev, [provider]: event.target.value }))
                  }
                />
                <button
                  type="button"
                  className="btn-theme"
                  disabled={busy === provider || !(drafts[provider] ?? "").trim()}
                  onClick={() => void save(provider)}
                >
                  {busy === provider ? "…" : "save"}
                </button>
              </div>
            </label>
          );
        })}
        {error && <span role="alert">{error}</span>}
      </div>
    </details>
  );
}

export function ModelCatalog() {
  const [catalogs, setCatalogs] = useState<Catalogs>({});
  const [keys, setKeys] = useState<KeysStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusLine, setStatusLine] = useState("no catalogs loaded yet");
  const [problems, setProblems] = useState<string[]>([]);

  const refreshKeys = useCallback(() => {
    void fetchKeys()
      .then(setKeys)
      .catch(() => setKeys(null));
  }, []);

  useEffect(() => {
    refreshKeys();
  }, [refreshKeys]);

  const loadAll = async () => {
    setLoading(true);
    setProblems([]);
    try {
      // Warm any providers whose keys were just saved but whose catalog
      // endpoint needs the fresh key in the backend process.
      await Promise.allSettled(
        PROVIDERS.filter((p) => keys?.providers[p]?.set).map((p) => fetchCatalogs(p)),
      );
      const results = await fetchAllCatalogs();
      const summary = summarize(results);
      setCatalogs(summary.catalogs);
      setProblems(summary.problems);
      setStatusLine(
        summary.loaded > 0
          ? `${summary.loaded} models loaded across ${results.filter((r) => r.models.length > 0).length} provider(s)`
          : "no models loaded — set a key below and retry",
      );
    } finally {
      setLoading(false);
    }
  };

  const totalModels = Object.values(catalogs).reduce((sum, c) => sum + c.models.length, 0);

  return (
    <>
      <div className="config-row config-catalog-row">
        <button type="button" className="btn-theme btn-load-catalogs" disabled={loading} onClick={() => void loadAll()}>
          {loading ? "loading…" : "⟳ load model catalogs"}
        </button>
        <span className="config-field-label">
          {statusLine}
          {totalModels > 0 ? "" : ""}
        </span>
      </div>
      {problems.length > 0 && (
        <ul className="config-problems">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}

      <datalist id="models-all">
        {Object.values(catalogs)
          .flatMap((catalog: ProviderCatalog) => catalog.models)
          .map((model) => (
            <option key={model.id} value={model.id}>
              {model.context ? `${model.context} ctx` : "context unknown"}
              {model.supported_parameters?.includes("temperature") ? " · temp" : " · fixed"}
            </option>
          ))}
      </datalist>

      <KeysPanel keys={keys} onSaved={refreshKeys} />
    </>
  );
}
