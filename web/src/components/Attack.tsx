// Mổ xẻ một kịch bản tấn công cho người xem, theo đúng đường đi của tấn công: nhân viên hỏi → payload
// chen vào dữ liệu agent đọc → agent bị đòi làm việc ngoài ý người dùng.

import clsx from "clsx";
import type { ReactNode } from "react";

import { Tooltip } from "@/components/ui";
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

/** Mã phân loại + nhãn. Có `hint` thì gạch chấm dưới và mở chú giải khi rê chuột hoặc focus. */
function Chip({ code, label, hint }: { code: string; label: string; hint?: string }) {
  const body = (
    <span
      tabIndex={hint ? 0 : undefined}
      className={clsx(
        "inline-flex h-6 items-center gap-1.5 rounded border border-slate-200 px-1.5 text-xs text-slate-700",
        hint && "cursor-help",
      )}
    >
      <span className="font-mono font-medium text-payload-600">{code}</span>
      <span className={clsx(hint && "underline decoration-slate-300 decoration-dotted underline-offset-4")}>{label}</span>
    </span>
  );
  return hint ? <Tooltip content={hint} side="bottom">{body}</Tooltip> : body;
}

const STAGE_INK = { neutral: "text-slate-500", payload: "text-payload-600", attack: "text-attack-600" } as const;

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
  tone?: keyof typeof STAGE_INK;
  children: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col">
      <div className="flex items-baseline gap-2 px-4 pt-3">
        <span className={clsx("num font-mono text-xs font-medium", STAGE_INK[tone])}>{n}</span>
        <span className="text-xs font-medium text-slate-700">{title}</span>
      </div>
      <div className="flex-1 px-4 py-2.5">{children}</div>
      {foot && <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">{foot}</div>}
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
    <div className="space-y-3">
      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          <Chip code={scenario.goal} label={GOAL_LABEL[scenario.goal] ?? ""} />
          <Chip code={scenario.channel} label={CHANNEL_LABEL[scenario.channel] ?? ""} hint={a.placement} />
          <Chip
            code={scenario.technique}
            label={TECHNIQUE_LABEL[scenario.technique] ?? ""}
            hint={a.technique_rationale ?? undefined}
          />
        </div>
        <p className="max-w-[88ch] text-sm text-slate-500">{scenario.story}</p>
      </div>

      <div className="grid grid-cols-1 divide-y divide-slate-200 rounded-lg border border-slate-200 lg:grid-cols-[1fr_1.5fr_1fr] lg:divide-x lg:divide-y-0">
        <Stage n={1} title="Nhân viên hỏi" foot={`Tác vụ ${scenario.carrier_task_id} · yêu cầu hợp lệ`}>
          <p className="text-sm text-slate-700">{scenario.query}</p>
        </Stage>

        <Stage
          n={2}
          tone="payload"
          title={`Payload chen vào ${CHANNEL_INTO[scenario.channel] ?? scenario.channel}`}
          foot={
            sourceTitle ? (
              <Tooltip content={sourceTitle}>
                <span tabIndex={0} className="cursor-help underline decoration-slate-300 decoration-dotted underline-offset-4">
                  {meta}
                </span>
              </Tooltip>
            ) : (
              meta
            )
          }
        >
          <HighlightText
            value={{ text: scenario.payload_text, spans: span ? [{ start: span[0], end: span[1], kind: "payload" }] : [] }}
            className="!p-2.5"
          />
          {meaning && (
            <p className="mt-2 text-xs text-slate-500">
              <span className="font-medium text-slate-700">{a.transform.length ? "Nghĩa gốc: " : "Nghĩa: "}</span>
              {meaning}
            </p>
          )}
        </Stage>

        <Stage
          n={3}
          tone="attack"
          title={a.tool ? "Agent bị đòi gọi tool" : "Agent bị đòi nhắc lại"}
          foot={
            <>
              <span className="font-medium text-attack-600">Tính là thành công khi: </span>
              {a.success}
            </>
          }
        >
          {a.tool ? (
            <>
              <div className="font-mono text-sm font-medium text-attack-700">{a.tool}()</div>
              {args.length > 0 && (
                <dl className="mt-1.5 space-y-1 text-xs">
                  {args.map(([k, v]) => (
                    <div key={k} className="flex gap-2">
                      <dt className="w-16 shrink-0 font-mono text-slate-500">{k}</dt>
                      <dd className="min-w-0 break-words text-slate-700">{argText(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-700">Không gọi tool — nhắc lại thông tin sai như sự thật.</p>
          )}
        </Stage>
      </div>
    </div>
  );
}
