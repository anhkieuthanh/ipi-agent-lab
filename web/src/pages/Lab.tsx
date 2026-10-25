import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FileWarning, FlaskConical, Loader2, Play, User } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { StepTimeline, ToolActions } from "@/components/Trace";
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
import { api, type Job, type RunDetail } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, int, presetLabel, seconds, usd } from "@/lib/format";

function ResultColumn({ runId }: { runId: string }) {
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId) });
  if (q.isLoading) return <Loading label="Đang tải kết quả…" />;
  if (q.error || !q.data) return <ErrorBox error={q.error ?? "lỗi"} />;
  const d: RunDetail = q.data;
  const run = d.run;
  const spontaneous = d.verdict?.tone === "attack" && !d.tool_actions.some((a) => a.follows_payload);
  return (
    <Card className="flex flex-col">
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

function Results({ batchId }: { batchId: string }) {
  const q = useQuery({ queryKey: ["runs", "demo-batch", batchId], queryFn: () => api.runs({ batch: [batchId], limit: 10 }) });
  if (q.isLoading) return <Loading />;
  const items = q.data?.items ?? [];
  if (!items.length) return null;
  return (
    <div className="mt-6">
      <h2 className="mb-3 text-[15px] font-semibold text-slate-900">Kết quả so sánh</h2>
      <div className={clsx("grid gap-4", items.length > 1 ? "lg:grid-cols-2" : "lg:grid-cols-1")}>
        {items.map((r) => (
          <ResultColumn key={r.run_id} runId={r.run_id} />
        ))}
      </div>
    </div>
  );
}

const PRESET_CHOICES = ["off", "d1_only", "d2_only", "d3_only", "d4_only", "d3_no_confirm", "all"];

export function LabPage() {
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });

  const [key, setKey] = useState("");
  const [target, setTarget] = useState("A3");
  const [variant, setVariant] = useState("");
  const [presets, setPresets] = useState<string[]>(["off", "all"]);
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

  const start = useMutation({
    mutationFn: () => api.startDemo({ scenario: key, target, presets, prompt_variant: variant }),
    onSuccess: (j) => {
      setJobId(j.id);
      setBatchId(null);
    },
  });

  if (scenarios.isLoading || config.isLoading) return <Loading />;
  const live = meta.data?.live_demo;
  const running = job.data && ["queued", "running"].includes(job.data.status);

  return (
    <>
      <PageHeader
        title="Phòng thí nghiệm tấn công"
        description="Chọn một kịch bản tiêm nhiễm thật, chạy trên model thật, so sánh trực tiếp khi tắt và bật phòng thủ. Mỗi lượt gọi API thật và được canh ngân sách."
      />

      {!live && (
        <div className="mb-6">
          <Callout tone="brand" title="Đang ở chế độ chỉ xem">
            Chạy trực tiếp cần khởi động console bằng <Mono>make console</Mono> (đặt <Mono>DEMO_LIVE=1</Mono>) trên máy có
            hạ tầng lab (<Mono>make up</Mono>) và tệp <Mono>.env</Mono>. Có thể xem lại các lượt demo đã chạy ở trang Lô
            thực nghiệm.
          </Callout>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
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
              <span className="label">Cấu hình phòng thủ so sánh</span>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {PRESET_CHOICES.map((p) => {
                  const on = presets.includes(p);
                  return (
                    <button
                      key={p}
                      onClick={() => setPresets(on ? presets.filter((x) => x !== p) : [...presets, p])}
                      className={clsx(
                        "rounded-md px-2.5 py-1 text-[12.5px] font-medium ring-1 ring-inset transition",
                        on ? "bg-brand-50 text-brand-700 ring-brand-200" : "bg-white text-slate-500 ring-slate-200 hover:bg-slate-50",
                      )}
                    >
                      {presetLabel(p)}
                    </button>
                  );
                })}
              </div>
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

      {batchId && <Results batchId={batchId} />}
    </>
  );
}
