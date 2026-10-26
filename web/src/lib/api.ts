// Client của API console (`src/console/app.py`). Mọi đường dẫn là tương đối: dev qua proxy Vite,
// bản build do chính FastAPI phục vụ.

export type Rate = { x: number; n: number; p: number; lo: number; hi: number } | null;

export type Kpis = {
  n_runs: number;
  n_attack: number;
  n_benign: number;
  n_parse_error: number;
  asr_off: Rate;
  asr_on: Rate;
  usr_off: Rate;
  frr: Rate;
  blocked_by: Record<"defense" | "model_refusal" | "harness", number>;
};

export type Gate = { id: string; label: string; status: "pass" | "fail" | "pending"; detail: string };

export type Manifest = {
  task?: string;
  block?: string;
  n_planned?: number;
  estimate_usd?: number;
  spent_usd?: number;
  budget_status?: string;
  started_at?: string;
  finished_at?: string;
} | null;

export type Batch = {
  batch_id: string;
  store: string;
  kind: "experiment" | "dryrun" | "demo";
  run_kinds: string[];
  targets: string[];
  presets: string[];
  channels: string[];
  n_runs: number;
  n_parse_error: number;
  n_success: number;
  n_attack: number;
  n_pass: number;
  n_benign: number;
  created_at: string;
  finished_at: string;
  tokens: number;
  manifest: Manifest;
  scenario?: Record<string, string>;
};

export type Overview = {
  kpis: Kpis;
  by_target: ({ target_id: string } & Kpis)[];
  gates: Gate[];
  budget: {
    total_usd: number | null;
    alert_pct: number;
    spent_usd: number | null;
    by_target: Record<string, number>;
    source: string;
  };
  recent_batches: Batch[];
};

export type Meta = {
  product: string;
  lab_commit: string | null;
  models: Record<string, string>;
  model_tag: string;
  attack_tag: string;
  prompt_active: string;
  live_demo: boolean;
};

export type AsrRow = Record<string, string | number | null> & {
  n: number;
  s: number;
  asr_e2e: number | null;
  asr_e2e_lo: number | null;
  asr_e2e_hi: number | null;
  dsr: number | null;
  blocked_defense: number;
  blocked_model_refusal: number;
  blocked_harness: number;
};

export type DefensePoint = {
  target_id?: string;
  preset: string;
  enabled: string;
  n_attack: number;
  asr_e2e: number | null;
  asr_lo: number | null;
  asr_hi: number | null;
  n_benign: number;
  usr: number | null;
  usr_lo: number | null;
  usr_hi: number | null;
  frr: number | null;
};

export type Preset = { name: string; codes: string[]; params: Record<string, unknown> };

export type RunRow = {
  run_id: string;
  batch_id: string;
  kind: string;
  run_kind: "attack" | "benign";
  created_at: string;
  target_id: string;
  model_id: string;
  preset: string;
  enabled: string;
  channel: string | null;
  technique: string | null;
  goal: string | null;
  carrier_task_id: string | null;
  benign_query_id: string | null;
  payload_id: string | null;
  outcome: string | null;
  blocked_by: string | null;
  delivered: number | null;
  g1_hit: boolean;
  g2_hit: boolean;
  g3_hit: boolean;
  g2_severity: string | null;
  parse_error: boolean;
  n_steps: number;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
};

export type Span = { start: number; end: number; kind: "payload" | "canary" };
export type Marked = { text: string; spans: Span[] };

export type Step = {
  idx: number;
  kind: string;
  tool_name: string | null;
  finish_reason: string | null;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  fields: Partial<Record<"llm_text" | "tool_args" | "tool_result", Marked>>;
  hits: Record<string, unknown>[];
  events: string[];
  blocking: boolean;
  refusal: boolean;
  transforming: boolean;
  decisive: boolean;
  payload_fields: string[];
  canary_fields: string[];
};

export type Verdict = { label: string; tone: "attack" | "defense" | "refusal" | "neutral"; detail: string };
export type ToolAction = { tool: string; args: string; blocked: boolean; follows_payload: boolean };

export type RunDetail = {
  run: RunRow & Record<string, unknown>;
  verdict: Verdict | null;
  payload: Record<string, unknown> | null;
  payload_text: string | null;
  steps: Step[];
  final_answer: Marked | null;
  tool_actions: ToolAction[];
  prompt_variant: string | null;
};

export type Scenario = {
  key: string;
  title: string;
  story: string;
  channel: string;
  technique: string;
  goal: string;
  goal_text: string;
  payload_id: string;
  carrier_task_id: string;
  query: string;
  payload_text: string;
};

export type Job = {
  id: string;
  scenario: string;
  target: string;
  presets: string[];
  prompt_variant: string | null;
  status: "queued" | "running" | "done" | "error";
  events: { preset: string; event: string; at: string }[];
  batch_id: string | null;
  spent_usd: number | null;
  budget_status: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export type ConfigSummary = {
  targets: { id: string; label: string; model_id: string; provider: string; pricing: { input: number; output: number } }[];
  aux_models: { id: string; label: string; model_id: string; provider: string; pricing: { input: number; output: number } }[];
  presets: Preset[];
  payloads: { total: number; by_technique: Record<string, number> };
  carriers: { id: string; name: string; query: string; allowed_tools: string[]; channels: string[] }[];
  prompt: { active: string; variants: string[] };
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type Params = Record<string, string | number | string[] | undefined | null>;

export function qs(params: Params = {}): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* giữ statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export type AssetSystemPrompt = {
  variant: string;
  active: string;
  variants: string[];
  canary_placeholder: string;
  template_hash: string;
  text: string;
  chars: number;
};
export type AssetColumn = { name: string; type: string; notnull: boolean };
export type AssetCustomers = {
  table: string;
  columns: AssetColumn[];
  total: number;
  seeded_rows: number;
  canary_row_id: number;
  rows: Record<string, unknown>[];
  note: string;
};
export type AssetTool = {
  name: string;
  code: string | null;
  kind: string | null;
  side_effect: boolean;
  description: string;
  args: { name: string; type: string | null; required: boolean }[];
};
export type AssetTools = {
  tools: AssetTool[];
  carriers: { id: string; name: string | null; allowed_tools: string[] }[];
};

export const api = {
  meta: () => request<Meta>("/api/meta"),
  overview: (p: Params) => request<Overview>(`/api/overview${qs(p)}`),
  batches: (p: Params = {}) => request<Batch[]>(`/api/batches${qs(p)}`),
  asr: (p: Params) => request<{ by: string[]; rows: AsrRow[] }>(`/api/attack/asr${qs(p)}`),
  defensePoints: (p: Params) =>
    request<{ by: string; points: DefensePoint[] }>(`/api/defense/points${qs(p)}`),
  presets: () => request<Preset[]>("/api/defense/presets"),
  runs: (p: Params) => request<{ total: number; items: RunRow[] }>(`/api/runs${qs(p)}`),
  run: (id: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  config: () => request<ConfigSummary>("/api/config"),
  scenarios: () => request<Scenario[]>("/api/demo/scenarios"),
  startDemo: (body: { scenario: string; target: string; presets: string[]; prompt_variant: string | null }) =>
    request<Job>("/api/demo/jobs", { method: "POST", body: JSON.stringify(body) }),
  job: (id: string) => request<Job>(`/api/demo/jobs/${id}`),
  activeJob: () => request<Job | null>("/api/demo/active"),
  assetSystemPrompt: () => request<AssetSystemPrompt>("/api/assets/system_prompt"),
  assetCustomers: () => request<AssetCustomers>("/api/assets/customers"),
  assetTools: () => request<AssetTools>("/api/assets/tools"),
};
