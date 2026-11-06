import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { GoalEvidenceBody } from "@/components/Evidence";
import { HighlightText, InjectedContext, ToolActions, TraceInspector, TraceLegend } from "@/components/Trace";
import { TraceReplay } from "@/components/TraceReplay";
import { Badge, Callout, Card, ErrorBox, Loading, Mono, PageHeader, Segmented } from "@/components/ui";
import { api, type RunDetail } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, int, presetLabel, seconds, when } from "@/lib/format";

type Tab = "evidence" | "trace" | "tools" | "answer" | "payload" | "replay";

/** Một ô thông tin trong dải tóm tắt: nhãn nhỏ trên, giá trị dưới. */
function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="break-words text-[13px] text-slate-800">{children}</div>
    </div>
  );
}

function Summary({ d }: { d: RunDetail }) {
  const run = d.run;
  const attack = run.run_kind === "attack";
  const tone = d.verdict?.tone;
  const edge = tone === "attack" ? "border-l-attack-500" : tone === "defense" ? "border-l-defense-500" : tone === "refusal" ? "border-l-refusal-500" : "border-l-slate-300";
  return (
    <Card className={`border-l-4 ${edge}`}>
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold text-slate-900">{d.verdict?.label ?? "Lượt lành tính"}</div>
            {d.verdict?.detail && <div className="mt-0.5 text-[13px] text-slate-600">{d.verdict.detail}</div>}
          </div>
          {attack && (
            <div className="flex flex-wrap items-center gap-1.5">
              {(["g1", "g2", "g3"] as const).map((g) => (
                <Badge key={g} tone={run[`${g}_hit`] ? "attack" : "neutral"} dot={!!run[`${g}_hit`]}>
                  {g.toUpperCase()} {run[`${g}_hit`] ? "✓" : "✗"}
                </Badge>
              ))}
              {run.g2_severity ? <Badge tone="warn">mức {String(run.g2_severity)}</Badge> : null}
            </div>
          )}
        </div>

        {d.user_query && (
          <div className="rounded-lg bg-slate-50 px-4 py-2.5">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">
              {attack ? `Nhân viên hỏi · tác vụ chở ${d.user_query.id}` : `Câu lành tính ${d.user_query.id}`}
            </div>
            <div className="mt-0.5 text-[13.5px] leading-relaxed text-slate-800">{d.user_query.text}</div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
          <Meta label="Model"><Mono>{String(run.model_id)}</Mono></Meta>
          <Meta label="Phòng thủ">{presetLabel(String(run.preset))}</Meta>
          <Meta label="System prompt"><Mono>{d.prompt_variant ?? "—"}</Mono></Meta>
          {attack ? (
            <>
              <Meta label="Kênh">{run.channel ? CHANNEL_LABEL[String(run.channel)] ?? String(run.channel) : "—"}</Meta>
              <Meta label="Kỹ thuật">{String(run.technique ?? "—")}</Meta>
              <Meta label="Mục tiêu">{run.goal ? `${run.goal} · ${GOAL_LABEL[String(run.goal)]}` : "—"}</Meta>
              <Meta label="Payload"><Mono>{String(run.payload_id ?? "—")}</Mono></Meta>
            </>
          ) : (
            <Meta label="Câu hỏi"><Mono>{String(run.benign_query_id)}</Mono></Meta>
          )}
          <Meta label="Bước">{int(Number(run.n_steps))}</Meta>
          <Meta label="Token">{int(Number(run.tokens_in) + Number(run.tokens_out))}</Meta>
          <Meta label="Độ trễ">{seconds(Number(run.latency_ms))}</Meta>
          <Meta label="Thời điểm">{when(String(run.created_at))}</Meta>
        </div>
      </div>
    </Card>
  );
}

export function RunDetailPage() {
  const { runId } = useParams();
  const [sp] = useSearchParams();
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const [tab, setTab] = useState<Tab | null>(null);

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const run = d.run;
  const attack = run.run_kind === "attack";
  const spontaneous = d.run.goal === "G2" && d.verdict?.tone === "attack" && !d.tool_actions.some((a) => a.follows_payload);

  const tabs: { value: Tab; label: string; count?: number }[] = [
    ...(attack ? [{ value: "evidence" as Tab, label: "Bằng chứng chấm" }] : []),
    { value: "trace", label: "Diễn biến", count: d.steps.length },
    { value: "tools", label: "Tool đã gọi", count: d.tool_actions.length },
    ...(d.final_answer ? [{ value: "answer" as Tab, label: "Trả lời cuối" }] : []),
    ...(attack && d.payload_text ? [{ value: "payload" as Tab, label: "Payload" }] : []),
    { value: "replay", label: "Phát lại" },
  ];
  const active: Tab = tab && tabs.some((t) => t.value === tab) ? tab : tabs[0].value;

  return (
    <>
      <PageHeader
        title="Chi tiết lượt chạy"
        info={<Mono>{run.run_id}</Mono>}
        actions={
          <Link
            to={`/runs${sp.toString() ? `?${sp}` : ""}`}
            className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-[13.5px] font-medium text-slate-600 ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
          >
            <ArrowLeft size={15} /> Lượt chạy
          </Link>
        }
      />

      <div className="space-y-4">
        <Summary d={d} />

        {spontaneous && (
          <Callout tone="warn" title="Cần đối chiếu hành động với payload">
            Scorer chấm đạt G2 nhưng chưa tìm thấy lời gọi tool khớp gợi ý từ payload.
            Đây là dấu hiệu cần kiểm tra trace, chưa đủ để kết luận hành vi có do payload hay không.
          </Callout>
        )}

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <Segmented value={active} onChange={setTab} options={tabs} />
            {active === "trace" && <TraceLegend />}
          </div>
          <div className="p-4">
            {active === "evidence" && <GoalEvidenceBody ev={d.evidence} />}
            {active === "trace" && (
              <div className="space-y-4">
                <InjectedContext ctx={d.injected_context} />
                <TraceInspector steps={d.steps} />
              </div>
            )}
            {active === "tools" && <ToolActions actions={d.tool_actions} />}
            {active === "answer" && d.final_answer && <HighlightText value={d.final_answer} />}
            {active === "payload" && d.payload_text && (
              <div>
                <pre className="code-block ring-payload-200">{d.payload_text}</pre>
                <p className="mt-2 text-[12.5px] text-slate-500">
                  Nhân viên không nhìn thấy đoạn này — nó nằm trong{" "}
                  {run.channel ? CHANNEL_LABEL[String(run.channel)] ?? String(run.channel) : "dữ liệu"} mà agent đọc.
                </p>
              </div>
            )}
            {active === "replay" && (
              <TraceReplay
                detail={d}
                codes={config.data?.presets.find((p) => p.name === String(run.preset))?.codes ?? []}
              />
            )}
          </div>
        </Card>
      </div>
    </>
  );
}
