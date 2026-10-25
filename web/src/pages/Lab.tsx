import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FileWarning, FlaskConical, Loader2, Map as MapIcon, Play, ShieldCheck, User } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  type DefenseCode,
  HookLegend,
  type PointStatus,
  STATUS_LABEL,
  SystemMap,
  hookStatusFromSteps,
} from "@/components/SystemMap";
import { StepTimeline, ToolActions } from "@/components/Trace";
import { TraceReplay } from "@/components/TraceReplay";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  ErrorBox,
  Loading,
  Mono,
  OutcomeBadge,
  PageHeader,
  Select,
  VerdictBanner,
} from "@/components/ui";
import { api, type Job, type Preset, type RunDetail } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, int, presetLabel, seconds, usd } from "@/lib/format";

const CODES: DefenseCode[] = ["D1", "D2", "D3", "D4"];

const STATUS_CHIP: Record<PointStatus | "off", string> = {
  off: "bg-slate-50 text-slate-400 ring-slate-200",
  idle: "bg-defense-50 text-defense-700 ring-defense-100",
  pass: "bg-defense-50 text-defense-700 ring-defense-100",
  transform: "bg-orange-50 text-orange-700 ring-orange-200",
  block: "bg-attack-50 text-attack-700 ring-attack-100",
};

/** Mã D bật trong một preset — lấy từ `config/defenses.yaml` qua /api/config. */
function codesOf(presets: Preset[], name: string): string[] {
  return presets.find((p) => p.name === name)?.codes ?? [];
}

function HookChips({ codes, status }: { codes: string[]; status: Partial<Record<DefenseCode, PointStatus>> }) {
  return (
    <div className="grid grid-cols-4 gap-1.5">
      {CODES.map((c) => {
        const st = codes.includes(c) ? status[c] ?? "pass" : null;
        return (
          <div
            key={c}
            title={`${c} · ${st ? STATUS_LABEL[st] : "tắt"}`}
            className={clsx("rounded-md px-2 py-1 text-center ring-1 ring-inset", STATUS_CHIP[st ?? "off"])}
          >
            <div className="text-[12px] font-bold">{c}</div>
            <div className="truncate text-[10.5px]">{st ? STATUS_LABEL[st] : "tắt"}</div>
          </div>
        );
      })}
    </div>
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
  const spontaneous = d.verdict?.tone === "attack" && !d.tool_actions.some((a) => a.follows_payload);
  const codes = codesOf(presets, String(run.preset));
  return (
    <Card className={clsx("flex flex-col", showing && "ring-2 ring-brand-500")}>
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <span className="text-[13px] font-semibold text-slate-700">Phòng thủ: {presetLabel(String(run.preset))}</span>
        <OutcomeBadge outcome={run.outcome} blockedBy={run.blocked_by} />
      </div>
      <div className="space-y-3 p-4">
        {d.verdict && <VerdictBanner verdict={d.verdict} />}
        {spontaneous && (
          <Callout tone="warn">Scorer chấm thành công nhưng agent không gọi tool payload đòi (VT-16).</Callout>
        )}
        <div className="grid grid-cols-3 gap-2 text-center">
          {[
            ["Bước", int(Number(run.n_steps))],
            ["Token", int(Number(run.tokens_in) + Number(run.tokens_out))],
            ["Thời gian", seconds(Number(run.latency_ms))],
          ].map(([k, v]) => (
            <div key={k} className="rounded-lg bg-slate-50 py-2">
              <div className="num text-[16px] font-semibold text-slate-900">{v}</div>
              <div className="text-[11px] text-slate-500">{k}</div>
            </div>
          ))}
        </div>
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="label">Điểm phòng thủ</span>
            <button
              onClick={onShow}
              disabled={showing}
              className="flex items-center gap-1 text-[12px] font-medium text-brand-600 hover:text-brand-700 disabled:text-slate-400"
            >
              <MapIcon size={12} /> {showing ? "Đang phát trên sơ đồ" : "Phát lại trên sơ đồ"}
            </button>
          </div>
          <HookChips codes={codes} status={hookStatusFromSteps(d.steps, codes)} />
        </div>
        <div>
          <div className="label mb-1.5">Tool agent đã gọi</div>
          <ToolActions actions={d.tool_actions} />
        </div>
        <details className="group">
          <summary className="cursor-pointer text-[13px] font-medium text-brand-600">Xem từng bước</summary>
          <div className="mt-2">
            <StepTimeline steps={d.steps} />
          </div>
        </details>
        <Link to={`/runs/${run.run_id}`} className="text-[13px] font-medium text-brand-600 hover:text-brand-700">
          Mở chi tiết đầy đủ →
        </Link>
      </div>
    </Card>
  );
}

function Results({
  batchId,
  presets,
  viewRun,
  onShow,
}: {
  batchId: string;
  presets: Preset[];
  viewRun: string | null;
  onShow: (runId: string) => void;
}) {
  const q = useQuery({ queryKey: ["runs", "demo-batch", batchId], queryFn: () => api.runs({ batch: [batchId], limit: 10 }) });
  if (q.isLoading) return <Loading />;
  const items = q.data?.items ?? [];
  if (!items.length) return null;
  return (
    <div className="mt-6">
      <h2 className="mb-3 text-[15px] font-semibold text-slate-900">Kết quả so sánh</h2>
      <div className={clsx("grid gap-4", items.length > 1 ? "lg:grid-cols-2" : "lg:grid-cols-1")}>
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
    <Card className="xl:col-span-2">
      <CardHeader
        title={view ? `Phát lại run · ${presetLabel(view.preset)}` : "Phòng thủ trên sơ đồ"}
        icon={<ShieldCheck size={16} />}
        action={
          view ? (
            <Button onClick={onBack}>Quay lại thiết lập</Button>
          ) : (
            <span className="text-[12px] text-slate-500">Bấm D1–D4 để bật/tắt</span>
          )
        }
      />
      {view ? (
        <TraceReplay detail={view.detail} codes={view.codes} autoplay />
      ) : (
        <>
          <div className="px-4 pb-2 pt-3">
            <SystemMap defenses={enabled} onToggle={onToggle} />
          </div>
          <div className="border-t border-slate-100 px-5 py-3">
            <HookLegend />
          </div>
        </>
      )}
    </Card>
  );
}

export function LabPage() {
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });

  const [key, setKey] = useState("");
  const [target, setTarget] = useState("A3");
  const [variant, setVariant] = useState("");
  const [enabled, setEnabled] = useState<Record<DefenseCode, boolean>>({ D1: true, D2: true, D3: true, D4: true });
  const [variantPick, setVariantPick] = useState<string | null>(null);
  const [compareOff, setCompareOff] = useState(true);
  const [viewRun, setViewRun] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);

  const scenario = scenarios.data?.find((s) => s.key === key) ?? scenarios.data?.[0];
  useEffect(() => {
    if (scenario && !key) setKey(scenario.key);
  }, [scenario, key]);
  useEffect(() => {
    if (config.data && !variant) setVariant(config.data.prompt.active);
  }, [config.data, variant]);

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

  const start = useMutation({
    mutationFn: () => api.startDemo({ scenario: key, target, presets, prompt_variant: variant }),
    onSuccess: (j) => {
      setJobId(j.id);
      setBatchId(null);
      setViewRun(null);
    },
  });

  if (scenarios.isLoading || config.isLoading) return <Loading />;
  const live = meta.data?.live_demo;
  const running = job.data && ["queued", "running"].includes(job.data.status);

  return (
    <>
      <PageHeader
        title="Phòng thí nghiệm tấn công"
        info="Chọn kịch bản, chạy trên model thật, so trực tiếp khi tắt và bật phòng thủ. Mỗi lượt gọi API thật, có canh ngân sách."
      />

      {!live && (
        <div className="mb-6">
          <Callout tone="brand">
            Chế độ chỉ xem. Chạy trực tiếp cần <Mono>make console</Mono> trên máy có hạ tầng lab và <Mono>.env</Mono>.
          </Callout>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-3">
          <CardHeader title="Kịch bản" icon={<FlaskConical size={16} />} />
          <div className="p-5">
            <Select
              value={key}
              onChange={setKey}
              options={(scenarios.data ?? []).map((s) => ({ value: s.key, label: s.title }))}
              className="mb-4"
            />
            {scenario && (
              <>
                <p className="mb-4 rounded-lg border-l-4 border-payload-400 bg-payload-50/50 px-4 py-3 text-[13px] text-slate-700">
                  {scenario.story}
                </p>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <div>
                    <div className="label mb-1.5 flex items-center gap-1.5">
                      <User size={13} /> Nhân viên hỏi agent
                    </div>
                    <div className="rounded-lg bg-brand-50/60 px-3 py-2.5 text-[13px] text-slate-700">{scenario.query}</div>
                    <div className="mt-1.5 text-[12px] text-slate-500">
                      Tác vụ {scenario.carrier_task_id} · {CHANNEL_LABEL[scenario.channel] ?? scenario.channel}
                    </div>
                  </div>
                  <div>
                    <div className="label mb-1.5 flex items-center gap-1.5">
                      <FileWarning size={13} /> Payload cài vào dữ liệu
                    </div>
                    <pre className="code-block ring-payload-200">{scenario.payload_text}</pre>
                    <div className="mt-1.5 text-[12px] text-slate-500">
                      {scenario.payload_id} · {scenario.goal} · {GOAL_LABEL[scenario.goal]}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </Card>

        <DefenseMap
          enabled={enabled}
          onToggle={(c) => setEnabled({ ...enabled, [c]: !enabled[c] })}
          view={view}
          onBack={() => setViewRun(null)}
        />

        <Card>
          <CardHeader title="Thiết lập lượt chạy" />
          <div className="space-y-4 p-5">
            <Select
              label="Model đích"
              value={target}
              onChange={setTarget}
              options={(config.data?.targets ?? []).map((t) => ({ value: t.id, label: `${t.id} · ${t.model_id}` }))}
            />
            <Select
              label="System prompt"
              value={variant}
              onChange={setVariant}
              options={(config.data?.prompt.variants ?? []).map((v) => ({ value: v, label: v }))}
            />
            <div>
              <span className="label">Cấu hình phòng thủ</span>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {CODES.map((c) => (
                  <span
                    key={c}
                    className={clsx(
                      "rounded-md px-2 py-0.5 text-[12px] font-bold ring-1 ring-inset",
                      enabled[c] ? STATUS_CHIP.pass : STATUS_CHIP.off,
                    )}
                  >
                    {c}
                  </span>
                ))}
                {chosen && <span className="text-[12.5px] text-slate-600">→ {presetLabel(chosen)}</span>}
              </div>
              {matches.length > 1 && (
                <Select
                  className="mt-2"
                  value={chosen ?? ""}
                  onChange={setVariantPick}
                  options={matches.map((m) => ({ value: m, label: presetLabel(m) }))}
                />
              )}
              {!chosen && (
                <div className="mt-2">
                  <Callout tone="warn">Tổ hợp này chưa có preset trong config/defenses.yaml.</Callout>
                </div>
              )}
              <label className="mt-2.5 flex items-center gap-2 text-[12.5px] text-slate-600">
                <input
                  type="checkbox"
                  checked={compareOff}
                  onChange={(e) => setCompareOff(e.target.checked)}
                  disabled={chosen === "off"}
                  className="accent-brand-600"
                />
                Chạy kèm bản tắt phòng thủ để so sánh
              </label>
            </div>
            <Button
              variant="primary"
              className="w-full"
              disabled={!live || !presets.length || !!running || start.isPending}
              onClick={() => start.mutate()}
              icon={running || start.isPending ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            >
              {running ? "Đang chạy…" : "Chạy tấn công"}
            </Button>
            {start.error && <ErrorBox error={start.error} />}

            {job.data && (
              <div className="rounded-lg bg-slate-50 p-3">
                <div className="mb-2 flex items-center justify-between text-[12.5px]">
                  <span className="font-medium text-slate-700">Tiến độ</span>
                  <Badge tone={job.data.status === "done" ? "defense" : job.data.status === "error" ? "attack" : "brand"}>
                    {job.data.status}
                  </Badge>
                </div>
                <div className="space-y-1">
                  {job.data.presets.map((p) => {
                    const done = job.data!.events.some((e) => e.preset === p && e.event === "done");
                    const started = job.data!.events.some((e) => e.preset === p && e.event === "start");
                    return (
                      <div key={p} className="flex items-center gap-2 text-[12.5px] text-slate-600">
                        {done ? (
                          <span className="text-defense-500">✓</span>
                        ) : started ? (
                          <Loader2 size={12} className="animate-spin text-brand-500" />
                        ) : (
                          <span className="text-slate-300">○</span>
                        )}
                        {presetLabel(p)}
                      </div>
                    );
                  })}
                </div>
                {job.data.status === "done" && (
                  <div className="mt-2 text-[12px] text-slate-500">
                    Chi phí {usd(job.data.spent_usd, 4)} · ngân sách {job.data.budget_status}
                  </div>
                )}
                {job.data.error && <div className="mt-2 text-[12px] text-attack-600">{job.data.error}</div>}
              </div>
            )}
          </div>
        </Card>
      </div>

      {batchId && (
        <Results
          batchId={batchId}
          presets={allPresets}
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
