// Mổ xẻ một kịch bản tấn công cho người xem, theo đúng đường đi của tấn công: nhân viên hỏi → payload
// chen vào dữ liệu agent đọc → agent bị đòi làm việc ngoài ý người dùng.

import clsx from "clsx";
import { ChevronRight, Flag, Info } from "lucide-react";
import type { ReactNode } from "react";

import type { Scenario } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, TECHNIQUE_LABEL } from "@/lib/format";

import { HighlightText } from "./Trace";

const SOURCE_LABEL: Record<string, string> = {
  original: "tự soạn",
  adapted: "chuyển thể",
  verbatim: "nguyên văn",
};

/** Chỗ payload chen vào, viết thường để ghép sau "Payload chen vào". */
const CHANNEL_INTO: Record<string, string> = {
  K1: "tài liệu kho tri thức",
  K2a: "mô tả tool MCP",
  K2b: "kết quả tool MCP",
};

function Chip({ code, label, title }: { code: string; label: string; title?: string }) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-1 text-[12.5px] text-slate-700 ring-1 ring-inset ring-slate-200",
        title && "cursor-help",
      )}
    >
      <span className="font-mono text-[11.5px] font-bold text-payload-600">{code}</span>
      {label}
      {title && <Info size={12} className="text-slate-400" />}
    </span>
  );
}

function Stage({
  n,
  title,
  foot,
  tone = "neutral",
  children,
}: {
  n: number;
  title: string;
  foot?: ReactNode;
  tone?: "neutral" | "payload" | "attack";
  children: ReactNode;
}) {
  return (
    <div
      className={clsx(
        "flex min-w-0 flex-col rounded-lg border bg-white",
        tone === "payload" && "border-payload-200",
        tone === "attack" && "border-attack-100",
        tone === "neutral" && "border-slate-200",
      )}
    >
      <div className="flex items-center gap-2 px-3.5 pt-3">
        <span
          className={clsx(
            "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
            tone === "payload" && "bg-payload-100 text-payload-700",
            tone === "attack" && "bg-attack-50 text-attack-700",
            tone === "neutral" && "bg-slate-100 text-slate-600",
          )}
        >
          {n}
        </span>
        <span className="text-[12.5px] font-semibold text-slate-700">{title}</span>
      </div>
      <div className="flex-1 px-3.5 py-2.5">{children}</div>
      {foot && <div className="border-t border-slate-100 px-3.5 py-2 text-[11.5px] text-slate-500">{foot}</div>}
    </div>
  );
}

function argText(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

export function AttackBrief({ scenario }: { scenario: Scenario }) {
  const a = scenario.attack;
  const span = a.instruction_span;
  const args = Object.entries(a.arguments).filter(([, v]) => !(Array.isArray(v) && v.length === 0));
  const meaning = a.instruction_vi && a.instruction_vi !== a.instruction ? a.instruction_vi : null;
  const meta = [scenario.payload_id, a.lang.toUpperCase(), a.source.kind ? SOURCE_LABEL[a.source.kind] ?? a.source.kind : null]
    .filter(Boolean)
    .join(" · ");
  const sourceTitle = [a.source.ref, a.source.license].filter(Boolean).join(" · ") || undefined;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          <Chip code={scenario.goal} label={GOAL_LABEL[scenario.goal] ?? ""} />
          <Chip code={scenario.channel} label={CHANNEL_LABEL[scenario.channel] ?? ""} title={a.placement} />
          <Chip
            code={scenario.technique}
            label={TECHNIQUE_LABEL[scenario.technique] ?? ""}
            title={a.technique_rationale ?? undefined}
          />
        </div>
        <p className="text-[13px] leading-relaxed text-slate-500">{scenario.story}</p>
      </div>

      <div className="grid grid-cols-1 items-stretch gap-2 lg:grid-cols-[1fr_auto_1.5fr_auto_1fr]">
        <Stage n={1} title="Nhân viên hỏi" foot={`Tác vụ ${scenario.carrier_task_id} · yêu cầu hợp lệ`}>
          <p className="text-[13px] leading-relaxed text-slate-700">{scenario.query}</p>
        </Stage>

        <ChevronRight size={16} className="hidden self-center text-slate-300 lg:block" />

        <Stage
          n={2}
          tone="payload"
          title={`Payload chen vào ${CHANNEL_INTO[scenario.channel] ?? scenario.channel}`}
          foot={<span title={sourceTitle}>{meta}</span>}
        >
          <HighlightText
            value={{ text: scenario.payload_text, spans: span ? [{ start: span[0], end: span[1], kind: "payload" }] : [] }}
            className="!bg-payload-50/40 !text-[12px] !ring-0"
          />
          {meaning && (
            <p className="mt-2 text-[12px] text-slate-500">
              <span className="font-medium text-slate-600">{a.transform.length ? "Nghĩa gốc: " : "Nghĩa: "}</span>
              {meaning}
            </p>
          )}
        </Stage>

        <ChevronRight size={16} className="hidden self-center text-slate-300 lg:block" />

        <Stage
          n={3}
          tone="attack"
          title={a.tool ? "Agent bị đòi gọi tool" : "Agent bị đòi nhắc lại"}
          foot={
            <span className="flex items-start gap-1.5">
              <Flag size={12} className="mt-0.5 shrink-0 text-attack-500" />
              {a.success}
            </span>
          }
        >
          {a.tool ? (
            <>
              <div className="font-mono text-[13px] font-semibold text-attack-700">{a.tool}()</div>
              {args.length > 0 && (
                <dl className="mt-1.5 space-y-1 text-[12px]">
                  {args.map(([k, v]) => (
                    <div key={k} className="flex gap-2">
                      <dt className="w-16 shrink-0 font-mono text-slate-400">{k}</dt>
                      <dd className="min-w-0 break-words text-slate-700">{argText(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </>
          ) : (
            <p className="text-[13px] text-slate-700">Không gọi tool — nhắc lại thông tin sai như sự thật.</p>
          )}
        </Stage>
      </div>
    </div>
  );
}
