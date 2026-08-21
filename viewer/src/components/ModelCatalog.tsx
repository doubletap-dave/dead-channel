import { useCallback, useEffect, useState } from "react";
import {
  PROVIDERS,
  fetchCatalogs,
  fetchKeys,
  setKey,
  type KeysStatus,
  type ModelInfoView,
  type ProviderId,
} from "../api/client";

interface CatalogState {
  models: ModelInfoView[];
  error: string | null;
  loading: boolean;
}

const initialCatalog: Record<ProviderId, CatalogState> = {
  openrouter: { models: [], error: null, loading: false },
  openai: { models: [], error: null, loading: false },
  perplexity: { models: [], error: null, loading: false },
};

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
                disabled={busy === provider || !(drafts[provider] ?? "").trim()}
                onClick={() => void save(provider)}
              >
                {busy === provider ? "saving…" : "save"}
              </button>
            </label>
          );
        })}
        {error && <span role="alert">{error}</span>}
      </div>
    </details>
  );
}

export function ModelCatalog() {
  const [catalogs, setCatalogs] = useState(initialCatalog);
  const [keys, setKeys] = useState<KeysStatus | null>(null);

  const refreshKeys = useCallback(() => {
    void fetchKeys()
      .then(setKeys)
      .catch(() => setKeys(null));
  }, []);

  useEffect(() => {
    refreshKeys();
  }, [refreshKeys]);

  const loadProvider = async (provider: ProviderId) => {
    setCatalogs((prev) => ({
      ...prev,
      [provider]: { ...prev[provider], loading: true, error: null },
    }));
    try {
      const models = await fetchCatalogs(provider);
      setCatalogs((prev) => ({
        ...prev,
        [provider]: { models, error: models.length === 0 ? "no key set or empty catalog" : null, loading: false },
      }));
    } catch (cause) {
      setCatalogs((prev) => ({
        ...prev,
        [provider]: {
          models: [],
          error: cause instanceof Error ? cause.message : String(cause),
          loading: false,
        },
      }));
    }
  };

  const totalModels = PROVIDERS.reduce((sum, p) => sum + catalogs[p].models.length, 0);

  return (
    <>
      <div className="config-row">
        {PROVIDERS.map((provider) => (
          <button
            key={provider}
            type="button"
            className="btn-catalog"
            disabled={catalogs[provider].loading}
            onClick={() => void loadProvider(provider)}
          >
            {catalogs[provider].loading ? "…" : `load ${provider} models`}
          </button>
        ))}
        <span className="config-field-label">
          {totalModels > 0 ? `${totalModels} models loaded` : "no catalogs loaded yet"}
        </span>
      </div>

      <datalist id="models-all">
        {PROVIDERS.flatMap((provider) => catalogs[provider].models).map((model) => (
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
