import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileWarning, Info, Mail, Map as MapIcon, MessageSquare, Target, Wrench } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { TraceInspector, ToolActions, TraceLegend } from "@/components/Trace";
import { HighlightText } from "@/components/Trace";
import { TraceReplay } from "@/components/TraceReplay";
import {
  Badge,
  Callout,
  Card,
  CardHeader,
  ErrorBox,
  KeyValue,
  Loading,
  Mono,
  PageHeader,
  VerdictBanner,
} from "@/components/ui";
import { api } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, int, presetLabel, seconds, when } from "@/lib/format";

export function RunDetailPage() {
  const { runId } = useParams();
  const [sp] = useSearchParams();
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const run = d.run;
  const attack = run.run_kind === "attack";
  const spontaneous = d.run.goal === "G2" && d.verdict?.tone === "attack" && !d.tool_actions.some((a) => a.follows_payload);

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

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          {d.verdict && <VerdictBanner verdict={d.verdict} />}

          {spontaneous && (
            <Callout tone="warn" title="Cần đối chiếu hành động với payload">
              Scorer chấm đạt G2 nhưng chưa tìm thấy lời gọi tool khớp gợi ý từ payload.
              Đây là dấu hiệu cần kiểm tra trace, chưa đủ để kết luận hành vi có do payload hay không.
            </Callout>
          )}

          {d.user_query && (
            <Card>
              <CardHeader
                title="Câu hỏi của nhân viên"
                subtitle={
                  attack
                    ? `Tác vụ chở ${d.user_query.id} — yêu cầu hợp lệ; nhân viên không thấy payload`
                    : `Câu lành tính ${d.user_query.id}`
                }
                icon={<MessageSquare size={16} className="text-brand-600" />}
              />
              <div className="px-5 pb-4">
                <blockquote className="rounded-lg border-l-4 border-brand-300 bg-slate-50 px-4 py-3 text-[14px] leading-relaxed text-slate-800">
                  {d.user_query.text}
                </blockquote>
              </div>
            </Card>
          )}

          <Card>
            <CardHeader
              title="Diễn biến"
              subtitle={<TraceLegend />}
            />
            <div className="p-4">
              <TraceInspector steps={d.steps} />
            </div>
          </Card>

          {attack && d.payload_text && (
            <Card>
              <details className="detail-disclosure"><summary>Payload</summary>
              <CardHeader
                title="Payload kẻ tấn công cài vào dữ liệu"
                subtitle={String(run.payload_id)}
                icon={<FileWarning size={16} className="text-payload-500" />}
              />
              <div className="p-4">
                <pre className="code-block ring-payload-200">{d.payload_text}</pre>
                <p className="mt-2 text-[12.5px] text-slate-500">
                  Nhân viên không nhìn thấy đoạn này — nó nằm trong{" "}
                  {run.channel ? CHANNEL_LABEL[String(run.channel)] ?? String(run.channel) : "dữ liệu"} mà agent đọc.
                </p>
              </div>
              </details>
            </Card>
          )}

          <Card>
            <details className="detail-disclosure"><summary>Phát lại trên sơ đồ</summary>
            <CardHeader title="Phát lại" icon={<MapIcon size={16} className="text-slate-500" />} />
            <TraceReplay
              detail={d}
              codes={config.data?.presets.find((p) => p.name === String(run.preset))?.codes ?? []}
            />
            </details>
          </Card>

          {d.final_answer && (
            <Card>
              <CardHeader title="Câu trả lời cuối" icon={<Mail size={16} className="text-slate-500" />} />
              <div className="p-4">
                <HighlightText value={d.final_answer} />
              </div>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Thông tin" icon={<Info size={16} className="text-slate-500" />} />
            <div className="p-5">
              <KeyValue
                items={[
                  ["Loại", attack ? "Tấn công" : "Lành tính"],
                  ["Model", <Mono key="m">{String(run.model_id)}</Mono>],
                  ["Phòng thủ", presetLabel(String(run.preset))],
                  ["System prompt", <Mono key="p">{d.prompt_variant ?? "—"}</Mono>],
                  ...(attack
                    ? ([
                        ["Kênh", run.channel ? CHANNEL_LABEL[String(run.channel)] ?? String(run.channel) : "—"],
                        ["Kỹ thuật", String(run.technique ?? "—")],
                        ["Mục tiêu", run.goal ? `${run.goal} · ${GOAL_LABEL[String(run.goal)]}` : "—"],
                        ["Tác vụ chở", String(run.carrier_task_id ?? "—")],
                      ] as [string, React.ReactNode][])
                    : ([["Câu hỏi", <Mono key="q">{String(run.benign_query_id)}</Mono>]] as [string, React.ReactNode][])),
                  ["Bước", int(Number(run.n_steps))],
                  ["Token", int(Number(run.tokens_in) + Number(run.tokens_out))],
                  ["Độ trễ", seconds(Number(run.latency_ms))],
                  ["Thời điểm", when(String(run.created_at))],
                ]}
              />
            </div>
          </Card>

          {attack && (
            <Card>
              <CardHeader title="Chấm mục tiêu" icon={<Target size={16} className="text-slate-500" />} />
              <div className="flex gap-2 p-5">
                {(["g1", "g2", "g3"] as const).map((g) => (
                  <Badge key={g} tone={run[`${g}_hit`] ? "attack" : "neutral"} dot={!!run[`${g}_hit`]}>
                    {g.toUpperCase()} {run[`${g}_hit`] ? "✓" : "✗"}
                  </Badge>
                ))}
                {run.g2_severity ? <Badge tone="warn">mức {String(run.g2_severity)}</Badge> : null}
              </div>
            </Card>
          )}

          <Card>
            <CardHeader title="Tool agent đã gọi" icon={<Wrench size={16} className="text-slate-500" />} />
            <div className="p-4">
              <ToolActions actions={d.tool_actions} />
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
