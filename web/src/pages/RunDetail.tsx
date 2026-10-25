import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileWarning, Mail, User } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { StepTimeline, ToolActions, TraceLegend } from "@/components/Trace";
import { HighlightText } from "@/components/Trace";
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
import { CHANNEL_LABEL, GOAL_LABEL, TECHNIQUE_LABEL, int, presetLabel, seconds, when } from "@/lib/format";

export function RunDetailPage() {
  const { runId } = useParams();
  const [sp] = useSearchParams();
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const run = d.run;
  const attack = run.run_kind === "attack";
  const spontaneous = d.verdict?.tone === "attack" && !d.tool_actions.some((a) => a.follows_payload);

  return (
    <>
      <PageHeader
        title="Chi tiết run"
        description={<Mono>{run.run_id}</Mono>}
        actions={
          <Link
            to={`/runs${sp.toString() ? `?${sp}` : ""}`}
            className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-[13.5px] font-medium text-slate-600 ring-1 ring-inset ring-slate-300 hover:bg-slate-50"
          >
            <ArrowLeft size={15} /> Danh sách run
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          {d.verdict && <VerdictBanner verdict={d.verdict} />}

          {spontaneous && (
            <Callout tone="warn" title="Thành công nhưng không do payload">
              Scorer chấm đạt mục tiêu, nhưng agent không gọi tool mà payload yêu cầu. Vi phạm có thể do hành vi tự
              phát của agent (Việc treo VT-16), không phải tấn công tiêm nhiễm thành công.
            </Callout>
          )}

          {attack && d.payload_text && (
            <Card>
              <CardHeader
                title="Payload kẻ tấn công cài vào dữ liệu"
                subtitle={`${run.payload_id} · ${run.technique ? TECHNIQUE_LABEL[String(run.technique)] : ""}`}
                icon={<FileWarning size={16} className="text-payload-500" />}
              />
              <div className="p-4">
                <pre className="code-block ring-payload-200">{d.payload_text}</pre>
                <p className="mt-2 text-[12.5px] text-slate-500">
                  Nhân viên không nhìn thấy đoạn này — nó nằm trong{" "}
                  {run.channel ? CHANNEL_LABEL[String(run.channel)] ?? String(run.channel) : "dữ liệu"} mà agent đọc.
                </p>
              </div>
            </Card>
          )}

          <Card>
            <CardHeader
              title="Agent đã làm gì — từng bước"
              subtitle="Nội dung trace đã được escape; payload và canary tô màu"
              action={<TraceLegend />}
            />
            <div className="p-4">
              <StepTimeline steps={d.steps} />
            </div>
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
            <CardHeader title="Thông tin run" />
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
              <CardHeader title="Chấm mục tiêu" subtitle="G1 rò dữ liệu · G2 hành động trái phép · G3 thông tin sai" />
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
            <CardHeader title="Tool agent đã gọi" icon={<User size={16} className="text-slate-500" />} />
            <div className="p-4">
              <ToolActions actions={d.tool_actions} />
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
