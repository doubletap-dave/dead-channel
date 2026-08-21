import type { RunConfigView } from "../types";

const API_BASE = "http://localhost:8000";

export interface CreateRunResult {
  runId: string;
}

export interface ModelInfoView {
  id: string;
  provider: string;
  context: number | null;
  supported_parameters?: string[] | null;
}

export interface KeysStatus {
  providers: Record<string, { set: boolean; masked: string | null }>;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function createRun(config: RunConfigView): Promise<CreateRunResult> {
  const response = await fetch(`${API_BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      seed: config.seed,
      turns: config.turns,
      model: config.modelMatrix.default || null,
      runId: null,
    }),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as CreateRunResult;
}

export async function startRun(runId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE}/runs/${encodeURIComponent(runId)}/start`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(await errorMessage(response));
}

export interface StopRunResult {
  status: "stopped" | "stopping" | "not-running" | "finished";
  turn?: number;
}

export async function stopRun(runId: string): Promise<StopRunResult> {
  const response = await fetch(
    `${API_BASE}/runs/${encodeURIComponent(runId)}/stop`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as StopRunResult;
}

export const PROVIDERS = ["openrouter", "openai", "perplexity"] as const;
export type ProviderId = (typeof PROVIDERS)[number];

export interface CatalogResult {
  provider: ProviderId;
  models: ModelInfoView[];
  error: string | null;
}

// Fetch every provider's catalog in parallel; per-provider errors are reported,
// not thrown — one missing key shouldn't hide the catalogs you *can* load.
export async function fetchAllCatalogs(): Promise<CatalogResult[]> {
  const results = await Promise.all(
    PROVIDERS.map(async (provider): Promise<CatalogResult> => {
      try {
        return { provider, models: await fetchCatalogs(provider), error: null };
      } catch (cause) {
        return {
          provider,
          models: [],
          error: cause instanceof Error ? cause.message : String(cause),
        };
      }
    }),
  );
  return results;
}

export async function fetchCatalogs(provider: ProviderId): Promise<ModelInfoView[]> {
  const response = await fetch(
    `${API_BASE}/providers/catalogs?provider=${encodeURIComponent(provider)}`,
  );
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as ModelInfoView[];
}

export async function fetchKeys(): Promise<KeysStatus> {
  const response = await fetch(`${API_BASE}/providers/keys`);
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as KeysStatus;
}

export async function setKey(provider: string, value: string): Promise<KeysStatus> {
  const response = await fetch(`${API_BASE}/providers/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, value }),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as KeysStatus;
}

// Wraps EventSource with seq-dedup insurance against browser auto-reconnects.
export function openStream(
  runId: string,
  onEvent: (event: import("../types").SimEvent) => void,
  onClose: () => void,
): EventSource {
  let lastSeq = 0;
  const source = new EventSource(`${API_BASE}/runs/${encodeURIComponent(runId)}/stream`);
  source.onmessage = (message) => {
    let event: import("../types").SimEvent;
    try {
      event = JSON.parse(message.data);
    } catch {
      return;
    }
    if (typeof event.seq !== "number" || event.seq <= lastSeq) return;
    lastSeq = event.seq;
    onEvent(event);
    if (event.type === "run.ended" || event.type === "run.stopped") {
      source.close();
      onClose();
    }
  };
  source.onerror = () => {
    // Browser retries automatically; permanent failures surface via createRun/startRun.
  };
  return source;
}
