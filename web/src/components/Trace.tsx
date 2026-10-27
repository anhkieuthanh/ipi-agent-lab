// Hiển thị trace một run. Nội dung trace là dữ liệu không tin cậy: React escape mọi chuỗi; đoạn
// tô màu dựng bằng phần tử <mark>, không qua innerHTML.

import clsx from "clsx";
import { Brain, ChevronDown, Cpu, Loader2, ShieldAlert, Sparkles, Wrench } from "lucide-react";
import { type ReactNode, useState } from "react";

import type { Marked, Step, ToolAction } from "@/lib/api";
import { seconds } from "@/lib/format";

import { Badge } from "./ui";

export function HighlightText({ value, className }: { value: Marked; className?: string }) {
  const { text, spans } = value;
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const [i, s] of [...spans].sort((a, b) => a.start - b.start).entries()) {
    if (s.start < cursor) continue; // chồng lấn: đoạn trước thắng
    if (s.start > cursor) parts.push(text.slice(cursor, s.start));
    parts.push(
      <mark key={i} className={`hl-${s.kind}`}>
        {text.slice(s.start, s.end)}
      </mark>,
    );
    cursor = s.end;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <pre className={clsx("code-block", className)}>{parts}</pre>;
}

const FIELD_LABEL: Record<string, string> = {
  llm_reasoning: "Suy luận của model",
  llm_text: "Model nói",
  tool_args: "Tham số gọi tool",
  tool_result: "Kết quả tool",
};

function format(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function stepTone(s: Step): { ring: string; icon: ReactNode; chip: ReactNode } {
  if (s.blocking)
    return {
      ring: "border-defense-200 bg-defense-50/40",
      icon: <ShieldAlert size={15} className="text-defense-600" />,
      chip: <Badge tone="defense">Chặn</Badge>,
    };
  if (s.refusal)
    return {
      ring: "border-refusal-200 bg-refusal-50/40",
      icon: <ShieldAlert size={15} className="text-refusal-600" />,
      chip: <Badge tone="refusal">Model từ chối</Badge>,
    };
  if (s.transforming)
    return {
      ring: "border-payload-200 bg-payload-50/30",
      icon: <Sparkles size={15} className="text-payload-600" />,
      chip: <Badge tone="payload">Biến đổi</Badge>,
    };
  if (s.kind === "tool")
    return { ring: "border-slate-200", icon: <Wrench size={15} className="text-slate-500" />, chip: null };
  return { ring: "border-slate-200", icon: <Cpu size={15} className="text-slate-500" />, chip: null };
}

function StepCard({ step, initialOpen = false }: { step: Step; initialOpen?: boolean }) {
  const [open, setOpen] = useState(
    initialOpen || step.decisive || step.blocking || step.payload_fields.length > 0,
  );
  const tone = stepTone(step);
  const hasBody = Object.keys(step.fields).length > 0 || step.events.length > 0;
  return (
    <div className={clsx("rounded-lg border", tone.ring, step.decisive && "ring-2 ring-defense-400")}>
      <button
        onClick={() => hasBody && setOpen(!open)}
        className={clsx("flex w-full items-center gap-3 px-4 py-2.5 text-left", hasBody && "cursor-pointer")}
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white text-[11px] font-semibold text-slate-500 ring-1 ring-slate-200">
          {step.idx}
        </span>
        {tone.icon}
        <span className="text-[13px] font-medium text-slate-700">
          {step.kind === "tool" || step.tool_name ? (
            <>
              Gọi tool <span className="font-mono text-slate-900">{step.tool_name}</span>
            </>
          ) : step.kind === "defense" ? (
            "Phòng thủ xử lý"
          ) : (
            "Lượt suy luận"
          )}
        </span>
        <div className="flex items-center gap-1.5">
          {tone.chip}
          {step.decisive && <Badge tone="defense">Quyết định</Badge>}
          {step.payload_fields.length > 0 && <Badge tone="payload">Có payload</Badge>}
          {step.canary_fields.length > 0 && <Badge tone="canary">Có canary</Badge>}
          {step.fields.llm_reasoning && (
            <Badge>
              <Brain size={12} /> Có suy luận
            </Badge>
          )}
        </div>
        <span className="ml-auto flex items-center gap-3 text-[11.5px] text-slate-400">
          {step.finish_reason && <span className="font-mono">{step.finish_reason}</span>}
          {step.latency_ms ? <span>{seconds(step.latency_ms)}</span> : null}
          {hasBody && <ChevronDown size={14} className={clsx("transition", open && "rotate-180")} />}
        </span>
      </button>
      {open && hasBody && (
        <div className="space-y-3 border-t border-slate-100 px-4 py-3">
          {step.events.map((e, i) => (
            <div key={i} className="rounded-md bg-slate-50 px-3 py-2 text-[12.5px] text-slate-600">
              {e}
            </div>
          ))}
          {Object.entries(step.fields).map(([key, marked]) => (
            <div key={key}>
              <div className="label mb-1 flex items-center gap-1.5">
                {key === "llm_reasoning" && <Brain size={12} />}
                {FIELD_LABEL[key] ?? key}
              </div>
              <HighlightText
                value={{ text: format(marked.text), spans: marked.spans }}
                className={clsx(
                  key === "llm_reasoning" && "max-h-72 overflow-y-auto italic text-slate-500",
                )}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ToolActions({ actions }: { actions: ToolAction[] }) {
  if (!actions.length) return <p className="text-[13px] text-slate-500">Agent không gọi tool nào.</p>;
  return (
    <div className="space-y-2">
      {actions.map((a, i) => (
        <div key={i} className="flex items-start gap-3 rounded-lg border border-slate-200 px-3 py-2">
          <Badge tone={a.blocked ? "defense" : "neutral"}>{a.blocked ? "Bị chặn" : "Đã chạy"}</Badge>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[12.5px] font-medium text-slate-800">{a.tool}</span>
              {a.follows_payload && <Badge tone="payload">Làm theo payload</Badge>}
            </div>
            <pre className="mt-1 truncate font-mono text-[11.5px] text-slate-500">{a.args}</pre>
          </div>
        </div>
      ))}
    </div>
  );
}

export function StepTimeline({ steps, live = false }: { steps: Step[]; live?: boolean }) {
  if (!steps.length && !live) return <p className="text-[13px] text-slate-500">Run không có bước nào.</p>;
  return (
    <div className="space-y-2">
      {steps.map((s, i) => (
        // Đang chạy: mở sẵn lượt model mới nhất để thấy nó vừa nghĩ gì; kết quả tool dài nên để đóng.
        <StepCard key={s.idx} step={s} initialOpen={live && i === steps.length - 1 && s.kind === "llm"} />
      ))}
      {live && (
        <div className="flex items-center gap-2 rounded-lg border border-dashed border-slate-200 px-4 py-2.5 text-[12.5px] text-slate-500">
          <Loader2 size={13} className="animate-spin text-brand-500" />
          {steps.length ? "Đang chờ bước tiếp theo…" : "Đang chuẩn bị dữ liệu và gọi model…"}
        </div>
      )}
    </div>
  );
}

export function TraceLegend() {
  return (
    <div className="flex flex-wrap items-center gap-3 text-[12px] text-slate-500">
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-defense-500" /> Chặn
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-refusal-500" /> Model từ chối
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-payload-500" /> Payload
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-canary-500" /> Canary
      </span>
      <span className="text-slate-400">· viền đậm = bước quyết định blocked_by</span>
    </div>
  );
}
