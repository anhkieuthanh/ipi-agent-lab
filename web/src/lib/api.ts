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
  /** Câu nhân viên gửi agent (tra theo mã, xem /api/runs/{id}). */
  user_query?: string | null;
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
  fields: Partial<Record<"llm_reasoning" | "llm_text" | "tool_args" | "tool_result", Marked>>;
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
  /** Câu nhân viên gửi agent (tra theo carrier_task_id / benign_query_id). */
  user_query: { id: string; text: string } | null;
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
  attack: AttackBrief;
};

/** Bộ chọn kịch bản tự do: mỗi hàng [kênh, kỹ thuật, mục tiêu, payload_id, tác vụ chở] ghép được. */
export type ScenarioCatalog = {
  rows: [string, string, string, string, string][];
  payloads: Record<string, { lang: string | null; variant: string | null; source: string | null }>;
  carriers: Record<string, string>;
};

/** Mổ xẻ payload của một kịch bản — từ bản ghi corpus, xem `console.demo.payload_brief`. */
export type AttackBrief = {
  lang: string;
  technique_variant: string | null;
  technique_rationale: string | null;
  template: string | null;
  instruction: string;
  instruction_vi: string | null;
  transform: string[];
  instruction_span: [number, number] | null;
  placement: string;
  tool: string | null;
  arguments: Record<string, unknown>;
  success: string;
  source: { kind: string | null; ref: string | null; license: string | null };
};

export type Job = {
  id: string;
  scenario: string;
  target: string;
  presets: string[];
  prompt_variant: string | null;
  sandbox: SandboxModel | null;
  status: "queued" | "running" | "done" | "error";
  events: { preset: string; event: string; at: string }[];
  batch_id: string | null;
  spent_usd: number | null;
  budget_status: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  /** preset → bước của run tới hiện tại (cập nhật trong lúc chạy). */
  live: Record<string, { run_id: string; steps: Step[] }>;
};

/** Model thử ngoài bộ đo (khối `sandbox` của config/models.yaml) — chỉ cho lượt demo. */
export type SandboxModel = { channel: string; model_id: string; price_in: number; price_out: number };

export type SandboxLimits = {
  label: string;
  channels: { id: string; label: string; provider: string; env: string[]; ready: boolean }[];
  model_id_pattern: string;
  max_price: number;
};

export type ConfigSummary = {
  targets: { id: string; label: string; model_id: string; provider: string; pricing: { input: number; output: number } }[];
  aux_models: { id: string; label: string; model_id: string; provider: string; pricing: { input: number; output: number } }[];
  sandbox: SandboxLimits;
  presets: Preset[];
  payloads: { total: number; by_technique: Record<string, number> };
  carriers: { id: string; name: string; query: string; allowed_tools: string[]; channels: string[] }[];
  prompt: { active: string; variants: string[] };
};

/** Trạng thái dịch vụ hạ tầng (config/services.yaml). `kind: config` chỉ kiểm có cấu hình, không probe. */
export type ProbeState = "up" | "down" | "not_configured" | "unknown";
export type ConfigState = "configured" | "not_configured";
export type ServiceStatus = {
  id: string;
  label: string;
  short: string;
  role: string;
  kind: "probe" | "config";
  status: ProbeState | ConfigState;
  /** Độ trễ của lượt kiểm tra sức khỏe, không phải độ trễ xử lý của dịch vụ. */
  latency_ms: number | null;
  error: string | null;
  checked_at: string;
  public_url: string | null;
  port: number | null;
};
export type ServicesStatus = { checked_at: string; ttl_s: number; age_s: number; services: ServiceStatus[] };
export type DemoCheck = {
  ok: boolean;
  checked_at: string;
  deps: { id: string; label: string; need: "required" | "optional"; status: ServiceStatus["status"]; error: string | null }[];
  blocking: string[];
};
export type MailItem = {
  id: string;
  received_at: string;
  from: string;
  to: string[];
  subject: string;
  snippet: string;
  truncated: boolean;
  attachments: string[];
  run_id: string | null;
};
export type MailBox = { status: ProbeState; error?: string; total: number; items: MailItem[] };
export type CanaryHit = {
  id: number;
  run_id: string | null;
  received_at: string;
  method: string;
  original_url: string | null;
  body_preview: string;
  body_encoding: string;
  truncated: boolean;
};
export type CanaryHits = { status: ProbeState; error?: string; items: CanaryHit[] };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Tỉ lệ kèm Wilson 95%: x/n. */
export type CiRate = { x: number; n: number; p: number | null; lo: number | null; hi: number | null };
export type Outcomes = {
  success: number;
  failed: number;
  model_refusal: number;
  defense: number;
  harness: number;
  excluded: number;
};
export type ScopeProfile = {
  n_batches: number;
  roles: Record<string, number>;
  prompt_variants: Record<string, number>;
  harness_versions: Record<string, number>;
  targets: Record<string, number>;
  presets: Record<string, number>;
  mixed: ("role" | "prompt_variant" | "harness_version")[];
};
export type Headline =
  | { kind: "top_cell"; channel: string; technique: string; asr: CiRate }
  | { kind: "k1_vs_k2"; k1: CiRate; k2: CiRate; k1_delivery: CiRate; k1_cond: CiRate }
  | { kind: "worst_model"; target_id: string; asr: CiRate };
export type AttackSummary = {
  scope: ScopeProfile;
  n: number;
  outcomes?: Outcomes;
  rq1: { channel: string; members: string[]; asr: CiRate; delivery: CiRate; asr_cond: CiRate; outcomes: Outcomes }[];
  rq2: { channel: string; technique: string; asr: CiRate; by_target: Record<string, CiRate>; outcomes: Outcomes }[];
  targets: { target_id: string; asr: CiRate; outcomes: Outcomes }[];
  headline: Headline[];
};

export type DefenseCell = { asr: CiRate; usr: CiRate; frr: CiRate; outcomes: Outcomes | null };
export type DefenseSummary = {
  scope: ScopeProfile;
  presets: Preset[];
  measured: string[];
  has_defense_runs: boolean;
  baseline: ({ target_id: string } & DefenseCell)[];
  effects: ({ target_id: string; preset: string; d_asr: number | null; d_usr: number | null; asr_cut: number | null } & DefenseCell)[];
  rq3: { target_id: string; all: DefenseCell; best_single: string; single: DefenseCell; gain: number; usr_cost: number | null }[];
  frr_by_task: { preset: string; carrier_task_id: string | null; frr: CiRate }[];
};

export type PayloadGroups = {
  total: number;
  targets: string[];
  items: {
    payload_id: string;
    channels: string[];
    technique: string | null;
    goal: string | null;
    lang: string | null;
    asr: CiRate;
    by_target: Record<string, { x: number; n: number }>;
    outcomes: Outcomes;
  }[];
};

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
  gates: () => request<Gate[]>("/api/gates"),
  batches: (p: Params = {}) => request<Batch[]>(`/api/batches${qs(p)}`),
  asr: (p: Params) => request<{ by: string[]; rows: AsrRow[] }>(`/api/attack/asr${qs(p)}`),
  defenseSummary: (p: Params) => request<DefenseSummary>(`/api/defense/summary${qs(p)}`),
  attackSummary: (p: Params) => request<AttackSummary>(`/api/attack/summary${qs(p)}`),
  defensePoints: (p: Params) =>
    request<{ by: string; points: DefensePoint[] }>(`/api/defense/points${qs(p)}`),
  presets: () => request<Preset[]>("/api/defense/presets"),
  runs: (p: Params) => request<{ total: number; items: RunRow[] }>(`/api/runs${qs(p)}`),
  runsByPayload: (p: Params) => request<PayloadGroups>(`/api/runs/by-payload${qs(p)}`),
  run: (id: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  config: () => request<ConfigSummary>("/api/config"),
  scenarios: () => request<Scenario[]>("/api/demo/scenarios"),
  scenarioCatalog: () => request<ScenarioCatalog>("/api/demo/catalog"),
  scenario: (key: string) => request<Scenario>(`/api/demo/scenario${qs({ key })}`),
  startDemo: (body: {
    scenario: string;
    target: string;
    presets: string[];
    prompt_variant: string | null;
    sandbox?: SandboxModel | null;
  }) =>
    request<Job>("/api/demo/jobs", { method: "POST", body: JSON.stringify(body) }),
  job: (id: string) => request<Job>(`/api/demo/jobs/${id}`),
  activeJob: () => request<Job | null>("/api/demo/active"),
  assetSystemPrompt: () => request<AssetSystemPrompt>("/api/assets/system_prompt"),
  assetCustomers: () => request<AssetCustomers>("/api/assets/customers"),
  assetTools: () => request<AssetTools>("/api/assets/tools"),
  services: (refresh = false) => request<ServicesStatus>(`/api/services${refresh ? "?refresh=1" : ""}`),
  demoCheck: (scenario: string) => request<DemoCheck>(`/api/services/demo-check${qs({ scenario })}`),
  mail: (runs: string[], limit = 20) => request<MailBox>(`/api/services/mail${qs({ run: runs, limit })}`),
  canaryHits: (runs: string[]) => request<CanaryHits>(`/api/services/canary-hits${qs({ run: runs })}`),
};
