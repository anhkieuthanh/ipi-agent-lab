import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Circle, Loader2, Map as MapIcon, Play } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  type DefenseCode,
  HookLegend,
  type PointStatus,
  STATUS_LABEL,
  SystemMap,
  hookStatusFromSteps,
} from "@/components/SystemMap";
import { AttackBrief } from "@/components/Attack";
import { ScenarioPicker } from "@/components/ScenarioPicker";
import { InjectedContext, StepTimeline, ToolActions } from "@/components/Trace";
import { DemoCheckNote, VerifyPanel } from "@/components/Services";
import { TraceReplay } from "@/components/TraceReplay";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  Disclosure,
  ErrorBox,
  Loading,
  Mono,
  OutcomeBadge,
  PageHeader,
  SectionTitle,
  Segmented,
  Select,
  VerdictBanner,
} from "@/components/ui";
import { api, type DemoCheck, type Job, type Preset, type RunDetail, type Scenario } from "@/lib/api";
import { DEFENSE_LABEL, int, presetLabel, seconds, usd } from "@/lib/format";
import { SANDBOX_ID, useSandboxModel } from "@/lib/sandbox";

const CODES: DefenseCode[] = ["D1", "D2", "D3", "D4"];

/** Màu chữ theo trạng thái điểm móc; nghĩa luôn nằm ở chữ đi kèm. */
const STATUS_INK: Record<PointStatus | "off", string> = {
  off: "text-slate-400",
  idle: "text-defense-700",
  pass: "text-defense-700",
  transform: "text-payload-600",
  block: "text-attack-700",
};

/** Mã D bật trong một preset — lấy từ `config/defenses.yaml` qua /api/config. */
function codesOf(presets: Preset[], name: string): string[] {
  return presets.find((p) => p.name === name)?.codes ?? [];
}

/** Hàng lựa chọn gọn: nền xám + dấu kiểm khi đang chọn. */
function rowClass(selected: boolean) {
  return clsx(
    "flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
    selected ? "bg-slate-100 text-slate-900" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
  );
}

function RowCheck({ on }: { on: boolean }) {
  return <Check size={14} aria-hidden="true" className={clsx("shrink-0", on ? "text-slate-900" : "invisible")} />;
}

/** Một phần của bảng thiết lập: nhãn + nội dung, ngăn với phần trước bằng đường kẻ mảnh. */
function FormSection({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <section className="min-w-0 border-t border-slate-100 px-4 py-4 first:border-t-0">
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {hint && <span className="min-w-0 truncate text-xs text-slate-500">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

function HookChips({ codes, status }: { codes: string[]; status: Partial<Record<DefenseCode, PointStatus>> }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
      {CODES.map((c) => {
        const st = codes.includes(c) ? status[c] ?? "pass" : null;
        return (
          <div key={c} title={`${c} · ${st ? STATUS_LABEL[st] : "tắt"}`} className="min-w-0">
            <dt className="font-mono text-xs font-medium text-slate-900">{c}</dt>
            <dd className={clsx("text-xs", STATUS_INK[st ?? "off"])}>{st ? STATUS_LABEL[st] : "tắt"}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function ResultColumn({
  runId,
  presets,
  showing,
  onShow,
}: {
  runId: string;
  presets: Preset[];
  showing: boolean;
  onShow: () => void;
}) {
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });
  if (q.isLoading) return <Loading label="Đang tải kết quả…" />;
  if (q.error || !q.data) return <ErrorBox error={q.error ?? "lỗi"} />;
  const d: RunDetail = q.data;
  const run = d.run;
  const spontaneous = d.run.goal === "G2" && d.verdict?.tone === "attack" && !d.tool_actions.some((a) => a.follows_payload);
  const codes = codesOf(presets, String(run.preset));
  return (
    <Card className={clsx("flex flex-col", showing && "border-brand-500")}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-slate-100 px-4 py-2.5">
        <span className="min-w-0 text-sm font-semibold text-slate-900">Phòng thủ: {presetLabel(String(run.preset))}</span>
        <OutcomeBadge outcome={run.outcome} blockedBy={run.blocked_by} />
      </div>
      <div className="space-y-4 p-4">
        {d.verdict && <VerdictBanner verdict={d.verdict} />}
        {spontaneous && (
          <Callout tone="warn">Scorer chấm đạt G2 nhưng chưa thấy tool khớp gợi ý payload. Cần đối chiếu trace trước khi kết luận nguyên nhân.</Callout>
        )}
        <dl className="grid grid-cols-3 divide-x divide-slate-100 rounded-md border border-slate-100">
          {[
            ["Bước", int(Number(run.n_steps))],
            ["Token", int(Number(run.tokens_in) + Number(run.tokens_out))],
            ["Thời gian", seconds(Number(run.latency_ms))],
          ].map(([k, v]) => (
            <div key={k} className="min-w-0 px-3 py-2">
              <dt className="text-xs text-slate-500">{k}</dt>
              <dd className="num mt-0.5 text-md font-semibold text-slate-900">{v}</dd>
            </div>
          ))}
        </dl>
        <div>
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
            <span className="label">Điểm phòng thủ</span>
            <Button size="sm" variant="ghost" onClick={onShow} disabled={showing} icon={<MapIcon size={12} />}>
              {showing ? "Đang phát trên sơ đồ" : "Phát lại trên sơ đồ"}
            </Button>
          </div>
          <HookChips codes={codes} status={hookStatusFromSteps(d.steps, codes)} />
        </div>
        <div>
          <div className="label mb-1.5">Tool agent đã gọi</div>
          <ToolActions actions={d.tool_actions} />
        </div>
        <Disclosure summary="Xem từng bước">
          <div className="space-y-2">
            <InjectedContext ctx={d.injected_context} />
            <StepTimeline steps={d.steps} />
          </div>
        </Disclosure>
        <div className="border-t border-slate-100 pt-3">
          <Link to={`/runs/${run.run_id}`} className="text-sm font-medium text-brand-600 hover:text-brand-700">
            Mở chi tiết đầy đủ →
          </Link>
        </div>
      </div>
    </Card>
  );
}

function Results({
  batchId,
  presets,
  viewRun,
  onShow,
  scenario,
}: {
  batchId: string;
  presets: Preset[];
  viewRun: string | null;
  onShow: (runId: string) => void;
  scenario?: Scenario;
}) {
  const q = useQuery({ queryKey: ["runs", "demo-batch", batchId], queryFn: () => api.runs({ batch: [batchId], limit: 10 }) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const items = q.data?.items ?? [];
  if (!items.length) return null;
  return (
    <div className="mt-6">
      <SectionTitle>Kết quả so sánh</SectionTitle>
      <div className={clsx("grid grid-cols-1 gap-4", items.length > 1 && "lg:grid-cols-2")}>
        {items.map((r) => (
          <ResultColumn
            key={r.run_id}
            runId={r.run_id}
            presets={presets}
            showing={viewRun === r.run_id}
            onShow={() => onShow(r.run_id)}
          />
        ))}
      </div>
      {scenario && <VerifyPanel runIds={items.map((r) => r.run_id)} channel={scenario.channel} goal={scenario.goal} />}
    </div>
  );
}

/** Sơ đồ ở trang Lab: bật/tắt D1–D4 tại đúng điểm móc; khi đang xem một run thì hiện trạng thái
 *  từng điểm của run đó và khóa bật/tắt. */
function DefenseMap({
  enabled,
  onToggle,
  view,
  onBack,
}: {
  enabled: Record<DefenseCode, boolean>;
  onToggle: (c: DefenseCode) => void;
  view: { preset: string; codes: string[]; detail: RunDetail } | null;
  onBack: () => void;
}) {
  return (
    <Card>
      <CardHeader
        title={view ? `Phát lại run · ${presetLabel(view.preset)}` : "Sơ đồ điểm phòng thủ"}
        subtitle={view ? undefined : "Bấm D1–D4 để bật/tắt"}
        action={view ? <Button size="sm" onClick={onBack}>Quay lại thiết lập</Button> : undefined}
      />
      {view ? (
        <TraceReplay detail={view.detail} codes={view.codes} autoplay />
      ) : (
        <>
          <div className="px-4 pb-2">
            <SystemMap defenses={enabled} onToggle={onToggle} />
          </div>
          <div className="border-t border-slate-100 px-4 py-3">
            <HookLegend />
          </div>
        </>
      )}
    </Card>
  );
}

/** Diễn biến từng bước của lượt đang chạy — mỗi preset một run, chọn bằng tab. */
function LivePanel({ job, attack }: { job: Job; attack?: string }) {
  const running = ["queued", "running"].includes(job.status);
  const started = job.presets.filter((p) => job.events.some((e) => e.preset === p && e.event === "start"));
  const current = started[started.length - 1] ?? job.presets[0];
  const [pick, setPick] = useState<string | null>(null);
  const preset = pick ?? current;
  const done = job.events.some((e) => e.preset === preset && e.event === "done");
  const steps = job.live?.[preset]?.steps ?? [];
  const isLive = running && preset === current && !done;
  if (!started.length) return null;
  return (
    <Card>
      <CardHeader
        title="Diễn biến trực tiếp"
        subtitle={`${attack ? `${attack} — ` : ""}từng bước agent làm, cập nhật trong lúc chạy.`}
        action={
          isLive ? (
            <Badge tone="brand" dot>
              Đang chạy
            </Badge>
          ) : null
        }
      />
      <div className="space-y-4 border-t border-slate-100 p-4">
        <Disclosure summary="Cách đọc diễn biến">
          <p className="max-w-[80ch] text-xs leading-[18px] text-slate-500">
            Mỗi bước gồm suy luận của model (nếu model trả về), lời model, tool được gọi, phòng thủ xử lý. Đoạn tô màu là payload.
          </p>
        </Disclosure>
        {job.presets.length > 1 && (
          <Segmented
            value={preset}
            onChange={setPick}
            options={job.presets.map((p) => ({
              value: p,
              label: presetLabel(p),
              count: job.live?.[p]?.steps.length ?? 0,
            }))}
          />
        )}
        {steps.length || isLive ? (
          <StepTimeline steps={steps} live={isLive} />
        ) : (
          <p className="text-sm text-slate-500">Preset này chưa chạy.</p>
        )}
      </div>
    </Card>
  );
}

export function LabPage() {
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });

  const [mode, setMode] = useState<"preset" | "custom">("preset");
  const [presetKey, setPresetKey] = useState("");
  const [customKey, setCustomKey] = useState("");
  const key = mode === "preset" ? presetKey : customKey;
  const [target, setTarget] = useState("A3");
  const [sandbox] = useSandboxModel();
  const [variant, setVariant] = useState("");
  const [enabled, setEnabled] = useState<Record<DefenseCode, boolean>>({ D1: true, D2: true, D3: true, D4: true });
  const [variantPick, setVariantPick] = useState<string | null>(null);
  const [compareOff, setCompareOff] = useState(true);
  const [viewRun, setViewRun] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [check, setCheck] = useState<DemoCheck | null>(null);

  // Kịch bản tự chọn không có trong danh sách chọn sẵn — lấy chi tiết theo khóa `custom:…`.
  const custom = useQuery({
    queryKey: ["scenario", customKey],
    queryFn: () => api.scenario(customKey),
    enabled: mode === "custom" && !!customKey,
    placeholderData: (prev) => prev,
  });
  const presetScenario = scenarios.data?.find((s) => s.key === presetKey) ?? scenarios.data?.[0];
  const scenario = mode === "preset" ? presetScenario : custom.data?.key === customKey ? custom.data : undefined;
  useEffect(() => {
    if (presetScenario && !presetKey) setPresetKey(presetScenario.key);
  }, [presetScenario, presetKey]);
  // Đổi kịch bản thì kết quả kiểm tra dịch vụ cũ không còn đúng.
  useEffect(() => { setCheck(null); }, [key]);
  useEffect(() => {
    if (config.data && !variant) setVariant(config.data.prompt.active);
  }, [config.data, variant]);
  // Bỏ model thử trên trang Cấu hình thì quay về model đích mặc định.
  useEffect(() => {
    if (target === SANDBOX_ID && !sandbox) setTarget("A3");
  }, [target, sandbox]);

  // Tải lại trang giữa lượt chạy: nối lại vào lượt đang chạy để tiếp tục xem diễn biến.
  const active = useQuery({ queryKey: ["activeJob"], queryFn: api.activeJob, enabled: !jobId });
  useEffect(() => {
    const a = active.data;
    if (!jobId && a && ["queued", "running"].includes(a.status)) setJobId(a.id);
  }, [active.data, jobId]);

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (["done", "error"].includes((q.state.data as Job | undefined)?.status ?? "") ? false : 1200),
  });
  useEffect(() => {
    const j = job.data;
    if (j?.status === "done" && j.batch_id) {
      setBatchId(j.batch_id);
      qc.invalidateQueries({ queryKey: ["batches"] });
    }
  }, [job.data, qc]);

  // Kịch bản của lượt đang xem (có thể là kịch bản tự chọn, kể cả sau khi tải lại trang).
  const jobKey = job.data?.scenario;
  const jobScenario = useQuery({
    queryKey: ["scenario", jobKey],
    queryFn: () => api.scenario(jobKey!),
    enabled: !!jobKey,
    initialData: () => scenarios.data?.find((s) => s.key === jobKey),
  });

  const allPresets = useMemo(() => config.data?.presets ?? [], [config.data]);
  const onCodes = CODES.filter((c) => enabled[c]);
  // Preset có đúng tập D đang bật — có thể nhiều (d3_only / d3_no_confirm khác nhau ở preset_overrides).
  const matches = allPresets
    .filter((p) => p.codes.length === onCodes.length && onCodes.every((c) => p.codes.includes(c)))
    .map((p) => p.name);
  const chosen = matches.length === 0 ? null : matches.includes(variantPick ?? "") ? variantPick! : matches[0];
  const presets = !chosen ? [] : compareOff && chosen !== "off" ? ["off", chosen] : [chosen];

  const viewDetail = useQuery({ queryKey: ["run", viewRun], queryFn: () => api.run(viewRun!), enabled: !!viewRun });
  const view = useMemo(() => {
    if (!viewRun || !viewDetail.data) return null;
    const preset = String(viewDetail.data.run.preset);
    return { preset, codes: codesOf(allPresets, preset), detail: viewDetail.data };
  }, [viewRun, viewDetail.data, allPresets]);

  // Kiểm tra lại các dịch vụ kịch bản cần ngay trước khi chạy (backend probe lại nếu kết quả đã cũ).
  // Dịch vụ bắt buộc lỗi thì dừng và hỏi; `force` = người dùng chọn vẫn chạy.
  const start = useMutation({
    mutationFn: async (force: boolean) => {
      const c = await api.demoCheck(key);
      setCheck(c);
      if (!c.ok && !force) return null;
      return api.startDemo({
        scenario: key,
        target,
        presets,
        prompt_variant: variant,
        sandbox: target === SANDBOX_ID ? sandbox : null,
      });
    },
    onSuccess: (j) => {
      if (!j) return;
      setJobId(j.id);
      setBatchId(null);
      setViewRun(null);
    },
  });

  if (scenarios.isLoading || config.isLoading || meta.isLoading) return <Loading />;
  if (scenarios.error || config.error || meta.error) return <ErrorBox error={scenarios.error ?? config.error ?? meta.error} />;
  const live = meta.data?.live_demo;
  const running = job.data && ["queued", "running"].includes(job.data.status);

  const runCount = compareOff && chosen !== "off" ? "2 lượt · so sánh bật/tắt" : "1 lượt chạy";

  return (
    <>
      <PageHeader
        title="Thí nghiệm"
        info="Chọn kịch bản, chạy trên model thật, so trực tiếp khi tắt và bật phòng thủ. Mỗi lượt gọi API thật, có canh ngân sách."
      />

      {!live && (
        <div className="mb-5">
          <Callout tone="brand">
            Chế độ chỉ xem. Chạy trực tiếp cần <Mono>make console</Mono> trên máy có hạ tầng lab và <Mono>.env</Mono>.
          </Callout>
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
        {/* Trái: một bảng thiết lập duy nhất */}
        <Card>
          <FormSection title="1. Kịch bản">
            <Segmented
              value={mode}
              onChange={setMode}
              label="Nguồn kịch bản"
              options={[
                { value: "preset", label: "Chọn sẵn" },
                { value: "custom", label: "Tự chọn từ corpus" },
              ]}
            />
            <div className="mt-3">
              {mode === "preset" ? (
                <div role="radiogroup" aria-label="Kịch bản" className="-mx-2 max-h-72 space-y-px overflow-y-auto">
                  {(scenarios.data ?? []).map((s) => {
                    const on = s.key === presetKey;
                    return (
                      <button key={s.key} type="button" role="radio" aria-checked={on} onClick={() => setPresetKey(s.key)} className={rowClass(on)}>
                        <span className="w-6 shrink-0 font-mono text-xs text-slate-500">{s.goal}</span>
                        <span className="line-clamp-2 min-w-0 flex-1" title={s.title}>
                          {s.title.replace(/^G\d\s*·\s*/, "").replace(/\s*\([^)]*\)\s*$/, "")}
                        </span>
                        <span className="shrink-0 font-mono text-2xs text-slate-400">
                          {s.channel} · {s.technique}
                        </span>
                        <RowCheck on={on} />
                      </button>
                    );
                  })}
                </div>
              ) : (
                <>
                  <ScenarioPicker value={customKey} onChange={setCustomKey} />
                  {custom.error && <div className="mt-3"><ErrorBox error={custom.error} /></div>}
                </>
              )}
            </div>
          </FormSection>

          <FormSection title="2. Phòng thủ" hint={chosen ? `→ ${presetLabel(chosen)}` : undefined}>
            <div role="group" aria-label="Cấu hình phòng thủ" className="-mx-2 space-y-px">
              {CODES.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-pressed={enabled[c]}
                  onClick={() => setEnabled({ ...enabled, [c]: !enabled[c] })}
                  className={rowClass(enabled[c])}
                >
                  <span className="w-6 shrink-0 font-mono text-xs font-medium">{c}</span>
                  <span className="min-w-0 flex-1 truncate">{DEFENSE_LABEL[c] ?? c}</span>
                  <span className="shrink-0 text-xs text-slate-500">{enabled[c] ? "bật" : "tắt"}</span>
                  <RowCheck on={enabled[c]} />
                </button>
              ))}
            </div>
            {matches.length > 1 && (
              <div className="mt-3">
                <div className="label mb-1">Preset khớp tổ hợp này</div>
                <div role="radiogroup" aria-label="Preset khớp tổ hợp này" className="-mx-2 space-y-px">
                  {matches.map((m) => (
                    <button key={m} type="button" role="radio" aria-checked={m === chosen} onClick={() => setVariantPick(m)} className={rowClass(m === chosen)}>
                      <span className="min-w-0 flex-1 break-words">{presetLabel(m)}</span>
                      <RowCheck on={m === chosen} />
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!chosen && (
              <div className="mt-3">
                <Callout tone="warn">Tổ hợp này chưa có preset trong config/defenses.yaml.</Callout>
              </div>
            )}
            <label className="mt-3 flex items-start gap-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={compareOff}
                onChange={(e) => setCompareOff(e.target.checked)}
                disabled={chosen === "off"}
                className="mt-px accent-brand-600"
              />
              Chạy kèm bản tắt phòng thủ để so sánh
            </label>
          </FormSection>

          <FormSection title="3. Thiết lập">
            <div className="space-y-3">
              <div>
                <Select
                  label="Model đích"
                  className="min-w-0"
                  value={target}
                  onChange={setTarget}
                  options={[
                    ...(config.data?.targets ?? []).map((t) => ({ value: t.id, label: `${t.id} · ${t.model_id}` })),
                    ...(sandbox ? [{ value: SANDBOX_ID, label: `Thử · ${sandbox.model_id}` }] : []),
                  ]}
                />
                {target === SANDBOX_ID ? (
                  <div className="mt-1.5 text-xs text-amber-700">
                    Model ngoài bộ đo — lượt này chỉ là demo, không vào số liệu báo cáo.
                  </div>
                ) : (
                  <Link to="/config" className="mt-1.5 inline-block text-xs text-slate-500 hover:text-brand-700">
                    {sandbox ? "Đổi model thử ở trang Cấu hình" : "Thử model khác ở trang Cấu hình"}
                  </Link>
                )}
              </div>
              <Select
                label="System prompt"
                className="min-w-0"
                value={variant}
                onChange={setVariant}
                options={(config.data?.prompt.variants ?? []).map((v) => ({ value: v, label: v }))}
              />
            </div>
          </FormSection>

          <section className="space-y-3 border-t border-slate-100 px-4 py-4">
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
              <span>{target}</span>
              <span>{chosen ? presetLabel(chosen) : "Chưa chọn cấu hình"}</span>
              <span>{runCount}</span>
            </div>
            <Button
              variant="primary"
              className="w-full"
              disabled={!live || !scenario || !presets.length || !!running || active.isFetching || !!active.error || !!job.error || start.isPending}
              onClick={() => start.mutate(false)}
              icon={running || start.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            >
              {running ? "Đang chạy…" : "Chạy thí nghiệm"}
            </Button>
            {check && <DemoCheckNote check={check} />}
            {check && !check.ok && !running && (
              <Button variant="danger" className="h-auto min-h-8 w-full whitespace-normal py-1.5" disabled={!live || start.isPending} onClick={() => start.mutate(true)} icon={<Play size={14} />}>
                Vẫn chạy dù dịch vụ bắt buộc đang lỗi
              </Button>
            )}
            {start.error && <ErrorBox error={start.error} />}
            {active.error && <ErrorBox error={active.error} />}
            {job.error && <Callout tone="warn" title="Mất kết nối cập nhật tiến độ">Dữ liệu bên dưới có thể đã cũ. Hệ thống đang thử kết nối lại.</Callout>}

            {job.data && (
              <div className="border-t border-slate-100 pt-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="label">Tiến độ</span>
                  <Badge tone={job.data.status === "done" ? "defense" : job.data.status === "error" ? "attack" : "brand"}>
                    {job.data.status}
                  </Badge>
                </div>
                <ul className="space-y-1">
                  {job.data.presets.map((p) => {
                    const done = job.data!.events.some((e) => e.preset === p && e.event === "done");
                    const started = job.data!.events.some((e) => e.preset === p && e.event === "start");
                    return (
                      <li key={p} className="flex items-center gap-2 text-xs text-slate-600">
                        {done ? (
                          <Check size={12} className="shrink-0 text-defense-600" aria-hidden="true" />
                        ) : started ? (
                          <Loader2 size={12} className="shrink-0 animate-spin text-brand-500" aria-hidden="true" />
                        ) : (
                          <Circle size={12} className="shrink-0 text-slate-300" aria-hidden="true" />
                        )}
                        <span className="min-w-0 flex-1 break-words">{presetLabel(p)}</span>
                        <span className="shrink-0 text-slate-400">{done ? "xong" : started ? "đang chạy" : "chờ"}</span>
                      </li>
                    );
                  })}
                </ul>
                {job.data.status === "done" && (
                  <div className="num mt-2 text-xs text-slate-500">
                    Chi phí {usd(job.data.spent_usd, 4)} · ngân sách {job.data.budget_status}
                  </div>
                )}
                {job.data.error && <div className="mt-2 break-words text-xs text-attack-600">{job.data.error}</div>}
              </div>
            )}
          </section>
        </Card>

        {/* Phải: kịch bản đang chọn, sơ đồ / phát lại, diễn biến trực tiếp */}
        <div className="min-w-0 space-y-5">
          {scenario && (
            <Card className="px-4 py-3">
              <Disclosure
                summary={
                  <span className="min-w-0 break-words">
                    Nội dung kịch bản <span className="font-normal text-slate-500">· {scenario.title}</span>
                  </span>
                }
              >
                <AttackBrief scenario={scenario} />
              </Disclosure>
            </Card>
          )}

          <DefenseMap
            enabled={enabled}
            onToggle={(c) => setEnabled({ ...enabled, [c]: !enabled[c] })}
            view={view}
            onBack={() => setViewRun(null)}
          />

          {job.data && (
            <LivePanel
              key={job.data.id}
              job={job.data}
              attack={jobScenario.data?.title}
            />
          )}
        </div>
      </div>

      {batchId && (
        <Results
          batchId={batchId}
          presets={allPresets}
          scenario={jobScenario.data}
          viewRun={viewRun}
          onShow={(id) => {
            setViewRun(id);
            window.scrollTo({ top: 0, behavior: "smooth" });
          }}
        />
      )}
    </>
  );
}
