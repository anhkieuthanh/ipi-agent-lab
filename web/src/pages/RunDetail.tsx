import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Check, Copy } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { GoalEvidenceBody } from "@/components/Evidence";
import { HighlightText, InjectedContext, ToolActions, TraceInspector, TraceLegend } from "@/components/Trace";
import { TraceReplay } from "@/components/TraceReplay";
import { Badge, Callout, Card, ErrorBox, KeyValue, Loading, Mono, Tabs, Tooltip, buttonClass } from "@/components/ui";
import { api, type PayloadSource, type RunDetail } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, int, presetLabel, seconds, sentence, when } from "@/lib/format";

type Tab = "evidence" | "trace" | "tools" | "answer" | "payload" | "replay";

function sourceNote(src: PayloadSource): string {
  if (src.kind === "commit")
    return `Nguồn: corpus ở commit ${src.commit} của run${src.dirty ? " (lúc chạy còn thay đổi chưa commit)" : ""}.`;
  if (src.kind === "batch_file")
    return `Nguồn: file payload của lô ${src.file}${src.at === "commit" ? ` ở commit ${src.commit}` : " (bản trên đĩa)"}.`;
  if (src.kind === "current")
    return `Nguồn: corpus hiện hành; ${src.commit_found ? `commit ${src.commit} của run không chứa payload này` : `không tra được commit ${src.commit ?? "của run"}`}, nội dung có thể khác bản đã chạy.`;
  return "";
}

function missingReason(src: PayloadSource): string {
  const at = src.commit ? (src.commit_found ? `corpus ở commit ${src.commit} của run` : `commit ${src.commit} (không còn trong repo)`) : "commit của run";
  return `Payload không có trong ${at}, trong file payload của lô, hay trong corpus hiện hành, thường là lô dò sinh payload riêng mà không ghi manifest.`;
}

function CopyId({ id }: { id: string }) {
  const [done, setDone] = useState(false);
  return (
    <Tooltip content={done ? "Đã chép" : "Chép mã run"}>
      <button
        aria-label="Chép mã run"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(id);
            setDone(true);
            setTimeout(() => setDone(false), 1500);
          } catch {
            /* trình duyệt chặn clipboard: mã vẫn chọn được bằng tay */
          }
        }}
        className="inline-flex items-center gap-1.5 rounded px-1 py-0.5 font-mono text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-900"
      >
        {id}
        {done ? <Check size={12} className="text-defense-600" /> : <Copy size={12} />}
      </button>
    </Tooltip>
  );
}

const TONE_BAR: Record<string, string> = {
  attack: "bg-attack-500",
  defense: "bg-defense-500",
  refusal: "bg-refusal-500",
};

function Summary({ d }: { d: RunDetail }) {
  const run = d.run;
  const attack = run.run_kind === "attack";
  const items: [string, React.ReactNode][] = [
    ["Model", <Mono>{String(run.model_id)}</Mono>],
    ["Phòng thủ", presetLabel(String(run.preset))],
    ["System prompt", <Mono>{d.prompt_variant ?? "—"}</Mono>],
    ...(attack
      ? ([
          ["Kênh", run.channel ? CHANNEL_LABEL[String(run.channel)] ?? String(run.channel) : "—"],
          ["Kỹ thuật", String(run.technique ?? "—")],
          ["Mục tiêu", run.goal ? `${run.goal} · ${GOAL_LABEL[String(run.goal)]}` : "—"],
          ["Payload", <Mono>{String(run.payload_id ?? "—")}</Mono>],
        ] as [string, React.ReactNode][])
      : ([["Câu hỏi", <Mono>{String(run.benign_query_id)}</Mono>]] as [string, React.ReactNode][])),
    ["Bước", <span className="num">{int(Number(run.n_steps))}</span>],
    ["Token", <span className="num">{int(Number(run.tokens_in) + Number(run.tokens_out))}</span>],
    ["Độ trễ", <span className="num">{seconds(Number(run.latency_ms))}</span>],
    ["Thời điểm", <span className="num">{when(String(run.created_at))}</span>],
  ];
  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 gap-3">
          <span className={clsx("w-[3px] shrink-0 rounded-sm", TONE_BAR[d.verdict?.tone ?? ""] ?? "bg-slate-300")} aria-hidden="true" />
          <div className="min-w-0">
            <h1 className="text-2xl font-medium text-slate-900">{d.verdict ? sentence(d.verdict.label) : "Lượt lành tính"}</h1>
            {d.verdict?.detail && <p className="mt-0.5 max-w-[80ch] text-sm text-slate-600">{d.verdict.detail}</p>}
          </div>
        </div>
        {attack && (
          <div className="flex flex-wrap items-center gap-1" aria-label="Mục tiêu tấn công đạt hay không">
            {(["g1", "g2", "g3"] as const).map((g) => (
              <Badge key={g} tone={run[`${g}_hit`] ? "attack" : "neutral"}>
                {g.toUpperCase()} · {run[`${g}_hit`] ? "đạt" : "không"}
              </Badge>
            ))}
            {run.g2_severity ? <Badge tone="warn">mức {String(run.g2_severity)}</Badge> : null}
          </div>
        )}
      </div>

      {d.user_query && (
        <figure className="border-l border-slate-300 pl-4">
          <figcaption className="text-xs text-slate-500">
            {attack ? `Nhân viên hỏi · tác vụ chở ${d.user_query.id}` : `Câu lành tính ${d.user_query.id}`}
          </figcaption>
          <blockquote className="mt-0.5 max-w-[88ch] text-base text-slate-800">{d.user_query.text}</blockquote>
        </figure>
      )}

      <div className="rounded-lg border border-slate-200 px-4 py-3">
        <KeyValue items={items} columns={6} />
      </div>
    </header>
  );
}

export function RunDetailPage() {
  const { runId } = useParams();
  const [sp] = useSearchParams();
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const [tab, setTab] = useState<Tab | null>(null);

  if (q.isLoading) return <Loading rows={10} />;
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
    ...(attack ? [{ value: "payload" as Tab, label: "Payload" }] : []),
    { value: "replay", label: "Phát lại" },
  ];
  const active: Tab = tab && tabs.some((t) => t.value === tab) ? tab : tabs[0].value;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-chrome>
        <Link to={`/runs${sp.toString() ? `?${sp}` : ""}`} className={buttonClass("ghost", "sm")}>
          <ArrowLeft size={13} /> Lượt chạy
        </Link>
        <span className="h-4 w-px bg-slate-200" />
        <CopyId id={run.run_id} />
      </div>

      <Summary d={d} />

      {spontaneous && (
        <Callout tone="warn" title="Cần đối chiếu hành động với payload">
          Scorer chấm đạt G2 nhưng chưa tìm thấy lời gọi tool khớp gợi ý từ payload.
          Đây là dấu hiệu cần kiểm tra trace, chưa đủ để kết luận hành vi có do payload hay không.
        </Callout>
      )}

      <Card>
        <Tabs id="run-detail" label="Các mặt của lượt chạy" value={active} onChange={setTab} options={tabs} trailing={active === "trace" ? <TraceLegend /> : undefined} />
        <div id="run-detail-panel" role="tabpanel" aria-labelledby={`run-detail-tab-${active}`} tabIndex={0} className="p-4">
          {active === "evidence" && <GoalEvidenceBody ev={d.evidence} />}
          {active === "trace" && (
            <div className="space-y-3">
              <InjectedContext ctx={d.injected_context} />
              <TraceInspector steps={d.steps} />
            </div>
          )}
          {active === "tools" && <ToolActions actions={d.tool_actions} />}
          {active === "answer" && d.final_answer && <HighlightText value={d.final_answer} />}
          {active === "payload" && (
            <div className="space-y-2">
              {d.payload_text ? (
                <>
                  <pre className="code-block border-payload-200">{d.payload_text}</pre>
                  <p className="text-xs text-slate-500">
                    Nhân viên không nhìn thấy đoạn này, nó nằm trong{" "}
                    {run.channel ? CHANNEL_LABEL[String(run.channel)] ?? String(run.channel) : "dữ liệu"} mà agent đọc.
                  </p>
                </>
              ) : (
                <Callout tone="warn" title={`Không tra được payload ${String(run.payload_id ?? "")}`}>
                  {missingReason(d.payload_source)}
                </Callout>
              )}
              <p className="text-xs text-muted">{sourceNote(d.payload_source)}</p>
            </div>
          )}
          {active === "replay" && (
            <TraceReplay detail={d} codes={config.data?.presets.find((p) => p.name === String(run.preset))?.codes ?? []} />
          )}
        </div>
      </Card>
    </div>
  );
}
