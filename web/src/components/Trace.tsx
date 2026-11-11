// Hiển thị trace một run. Nội dung trace là dữ liệu không tin cậy: React escape mọi chuỗi; đoạn
// tô màu dựng bằng phần tử <mark>, không qua innerHTML.

import clsx from "clsx";
import { ChevronRight, Loader2 } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useRef, useState } from "react";

import type { InjectedContext as InjectedCtx, Marked, Step, ToolAction } from "@/lib/api";
import { seconds } from "@/lib/format";

import { Badge, Button, Kbd } from "./ui";

export function HighlightText({ value, className }: { value: Marked; className?: string }) {
  const { text, spans } = value;
  // API offsets count Unicode code points (Python), not UTF-16 code units.
  const chars = Array.from(text);
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const [i, s] of [...spans].sort((a, b) => a.start - b.start).entries()) {
    if (s.start < cursor) continue; // chồng lấn: đoạn trước thắng
    if (s.start > cursor) parts.push(chars.slice(cursor, s.start).join(""));
    parts.push(
      <mark key={i} className={`hl-${s.kind}`}>
        {chars.slice(s.start, s.end).join("")}
      </mark>,
    );
    cursor = s.end;
  }
  if (cursor < chars.length) parts.push(chars.slice(cursor).join(""));
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

/** Loại sự kiện của một bước: quyết định màu vạch và nhãn. Chặn (phòng thủ) ≠ model tự từ chối. */
function stepKind(s: Step): { bar: string; chip: ReactNode } {
  if (s.blocking) return { bar: "bg-defense-500", chip: <Badge tone="defense">Chặn</Badge> };
  if (s.refusal) return { bar: "bg-refusal-500", chip: <Badge tone="refusal">Model từ chối</Badge> };
  if (s.transforming) return { bar: "bg-payload-500", chip: <Badge tone="payload">Biến đổi</Badge> };
  return { bar: "bg-transparent", chip: null };
}

function stepName(s: Step): ReactNode {
  if (s.kind === "tool" || s.tool_name) return <span className="font-mono text-xs text-slate-900">{s.tool_name}</span>;
  return s.kind === "defense" ? "Phòng thủ xử lý" : "Lượt suy luận";
}

function stepRole(s: Step): string {
  return s.kind === "tool" || s.tool_name ? "Tool" : s.kind === "defense" ? "Phòng thủ" : "Model";
}

function StepFlags({ step }: { step: Step }) {
  return (
    <>
      {stepKind(step).chip}
      {step.decisive && <Badge tone="defense">Quyết định</Badge>}
      {step.payload_fields.length > 0 && <Badge tone="payload">Payload</Badge>}
      {step.canary_fields.length > 0 && <Badge tone="canary">Canary</Badge>}
    </>
  );
}

function StepBody({ step }: { step: Step }) {
  const empty = !Object.keys(step.fields).length && !step.events.length;
  if (empty) return <p className="text-sm text-slate-500">Bước này không có nội dung chi tiết.</p>;
  return (
    <div className="space-y-4">
      {step.events.length > 0 && (
        <ul className="space-y-1 text-sm text-slate-600">
          {step.events.map((e, i) => (
            <li key={i} className="flex gap-2">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-400" aria-hidden="true" />
              {e}
            </li>
          ))}
        </ul>
      )}
      {Object.entries(step.fields).map(([key, marked]) => (
        <section key={key}>
          <h3 className="label mb-1.5">{FIELD_LABEL[key] ?? key}</h3>
          <HighlightText
            value={{ text: marked.spans.length ? marked.text : format(marked.text), spans: marked.spans }}
            className={clsx(key === "llm_reasoning" && "max-h-72 overflow-y-auto text-slate-500")}
          />
        </section>
      ))}
    </div>
  );
}

/** Bước dạng gập — dùng khi trace đang chạy trực tiếp (Phòng thí nghiệm). */
function StepRow({ step, initialOpen = false }: { step: Step; initialOpen?: boolean }) {
  const [open, setOpen] = useState(initialOpen || step.decisive || step.blocking || step.payload_fields.length > 0);
  const hasBody = Object.keys(step.fields).length > 0 || step.events.length > 0;
  return (
    <div className="relative">
      <span className={clsx("absolute inset-y-0 left-0 w-0.5", stepKind(step).bar)} aria-hidden="true" />
      <button
        aria-expanded={hasBody ? open : undefined}
        disabled={!hasBody}
        onClick={() => hasBody && setOpen(!open)}
        className="flex min-h-9 w-full flex-wrap items-center gap-x-2.5 gap-y-1 px-3 py-1.5 text-left hover:bg-slate-50 disabled:hover:bg-transparent"
      >
        <ChevronRight size={13} className={clsx("shrink-0 text-slate-400 transition-transform", open && "rotate-90", !hasBody && "invisible")} />
        <span className="num w-5 shrink-0 text-right font-mono text-xs text-slate-400">{step.idx}</span>
        <span className="w-16 shrink-0 text-xs text-slate-500">{stepRole(step)}</span>
        <span className="text-sm font-medium text-slate-700">{stepName(step)}</span>
        <span className="flex flex-wrap items-center gap-1">
          <StepFlags step={step} />
          {step.fields.llm_reasoning && <Badge>Có suy luận</Badge>}
        </span>
        <span className="num ml-auto flex items-center gap-3 text-xs text-slate-400">
          {step.finish_reason && <span className="font-mono">{step.finish_reason}</span>}
          {step.latency_ms ? <span>{seconds(step.latency_ms)}</span> : null}
        </span>
      </button>
      {open && hasBody && (
        <div className="px-3 pb-4 pl-[42px] pt-1">
          <StepBody step={step} />
        </div>
      )}
    </div>
  );
}

/** Ngữ cảnh chở payload không nằm trong bước nào của trace (K2a: mô tả tool gửi kèm mọi lượt gọi
 * model). Hiện trước các bước, ghi rõ là bản dựng lại. */
export function InjectedContext({ ctx }: { ctx: InjectedCtx | null | undefined }) {
  const [open, setOpen] = useState(true);
  if (!ctx) return null;
  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-200">
      <span className="absolute inset-y-0 left-0 w-0.5 bg-payload-500" aria-hidden="true" />
      <button aria-expanded={open} onClick={() => setOpen(!open)} className="flex min-h-9 w-full flex-wrap items-center gap-2.5 px-3 py-1.5 text-left hover:bg-slate-50">
        <ChevronRight size={13} className={clsx("shrink-0 text-slate-400 transition-transform", open && "rotate-90")} />
        <span className="text-sm font-medium text-slate-700">
          Ngữ cảnh gửi model · mô tả tool <span className="font-mono text-xs text-slate-900">{ctx.tool}</span>
        </span>
        <Badge tone="payload">Payload</Badge>
        {ctx.reconstructed && <Badge>Dựng lại</Badge>}
      </button>
      {open && (
        <div className="space-y-2 px-3 pb-3 pl-[34px]">
          <p className="max-w-[88ch] text-xs leading-[18px] text-slate-500">
            K2a: payload nối vào mô tả tool, gửi kèm danh sách tool ở{" "}
            {ctx.rug_pull ? "các lượt gọi model sau lần liệt kê đầu (rug-pull)" : "mọi lượt gọi model"} — nên
            không hiện ở bước nào bên dưới.
            {ctx.reconstructed && " Trace không lưu danh sách tool; bản này dựng lại từ corpus và config hiện hành."}
          </p>
          {ctx.d1_wrapped && (
            <p className="text-xs text-amber-700">D1 bật: model nhận bản mô tả đã qua spotlighting, không phải nguyên văn dưới đây.</p>
          )}
          <HighlightText value={ctx.text} />
        </div>
      )}
    </div>
  );
}

export function ToolActions({ actions }: { actions: ToolAction[] }) {
  if (!actions.length) return <p className="text-sm text-slate-500">Agent không gọi tool nào.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="table-base">
        <thead>
          <tr>
            <th className="w-8 text-right">#</th>
            <th>Tool</th>
            <th>Tham số</th>
            <th>Trạng thái</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((a, i) => (
            <tr key={i}>
              <td className="num text-right font-mono text-xs text-slate-400">{i + 1}</td>
              <td className="whitespace-nowrap">
                <span className="font-mono text-xs font-medium text-slate-900">{a.tool}</span>
              </td>
              <td className="max-w-[560px]">
                <pre className="truncate font-mono text-xs text-slate-500" title={a.args}>{a.args}</pre>
              </td>
              <td className="whitespace-nowrap">
                <span className="flex items-center gap-1">
                  <Badge tone={a.blocked ? "defense" : "neutral"}>{a.blocked ? "Bị chặn" : "Đã chạy"}</Badge>
                  {a.follows_payload && <Badge tone="payload">Làm theo payload</Badge>}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StepTimeline({ steps, live = false }: { steps: Step[]; live?: boolean }) {
  if (!steps.length && !live) return <p className="text-sm text-slate-500">Run không có bước nào.</p>;
  return (
    <div className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200">
      {steps.map((s, i) => (
        // Đang chạy: mở sẵn lượt model mới nhất để thấy nó vừa nghĩ gì; kết quả tool dài nên để đóng.
        <StepRow key={s.idx} step={s} initialOpen={live && i === steps.length - 1 && s.kind === "llm"} />
      ))}
      {live && (
        <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500">
          <Loader2 size={13} className="animate-spin text-slate-400" />
          {steps.length ? "Đang chờ bước tiếp theo…" : "Đang chuẩn bị dữ liệu và gọi model…"}
        </div>
      )}
    </div>
  );
}

/** Điều tra trace: danh sách bước bên trái, bằng chứng của bước đang chọn bên phải.
 * Bàn phím trong danh sách: ↑/↓ hoặc J/K đổi bước. */
export function TraceInspector({ steps }: { steps: Step[] }) {
  const decisive = steps.find((s) => s.decisive);
  const [selected, setSelected] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const step = steps.find((s) => s.idx === selected) ?? decisive ?? steps[0];
  if (!step) return <p className="text-sm text-slate-500">Chưa có bước nào.</p>;

  const move = (delta: number) => {
    const at = steps.findIndex((s) => s.idx === step.idx);
    const next = steps[Math.min(steps.length - 1, Math.max(0, at + delta))];
    if (!next) return;
    setSelected(next.idx);
    listRef.current?.querySelector<HTMLElement>(`[data-step="${next.idx}"]`)?.focus();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); move(1); }
    if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); move(-1); }
  };

  return (
    <div className="grid overflow-hidden rounded-lg border border-slate-200 md:grid-cols-[280px_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col border-b border-slate-200 bg-slate-50 md:border-b-0 md:border-r">
        <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-slate-200 px-3">
          <span className="text-xs font-medium text-slate-500">{steps.length} bước</span>
          {decisive ? (
            <Button size="sm" variant="ghost" onClick={() => setSelected(decisive.idx)}>Tới bước quyết định</Button>
          ) : (
            <span className="hidden items-center gap-1 text-2xs text-slate-400 md:flex"><Kbd>↑</Kbd><Kbd>↓</Kbd></span>
          )}
        </div>
        <div ref={listRef} role="listbox" aria-label="Các bước thực thi" onKeyDown={onKey} className="max-h-60 overflow-y-auto p-1 md:max-h-[640px]">
          {steps.map((s) => {
            const on = s.idx === step.idx;
            return (
              <button
                key={s.idx}
                data-step={s.idx}
                role="option"
                aria-selected={on}
                tabIndex={on ? 0 : -1}
                onClick={() => setSelected(s.idx)}
                className={clsx(
                  "relative flex h-9 w-full items-center gap-2 overflow-hidden rounded-md pl-3 pr-2 text-left transition-colors",
                  on ? "bg-surface shadow-[0_0_0_1px_rgb(var(--n-200))]" : "hover:bg-slate-100",
                )}
              >
                <span className={clsx("absolute inset-y-1.5 left-0.5 w-0.5 rounded-full", stepKind(s).bar)} aria-hidden="true" />
                <span className="num w-5 shrink-0 text-right font-mono text-xs text-slate-400">{s.idx}</span>
                <span className="min-w-0 flex-1 truncate text-sm text-slate-700">
                  {s.tool_name ? <span className="font-mono text-xs text-slate-900">{s.tool_name}</span> : stepRole(s)}
                </span>
                <span className="flex shrink-0 items-center gap-1" aria-hidden="true">
                  {s.payload_fields.length > 0 && <span className="h-1.5 w-1.5 rounded-full bg-payload-500" title="Có payload" />}
                  {s.canary_fields.length > 0 && <span className="h-1.5 w-1.5 rounded-full bg-canary-500" title="Có canary" />}
                </span>
                <span className="shrink-0 text-2xs text-slate-400">
                  {s.decisive ? "Quyết định" : s.blocking ? "Chặn" : s.refusal ? "Từ chối" : s.latency_ms ? seconds(s.latency_ms) : ""}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-w-0 overflow-y-auto p-4 md:max-h-[676px]" aria-live="polite">
        <div className="mb-4 flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <span className="text-sm font-semibold text-slate-900">Bước {step.idx} · {stepName(step)}</span>
          <StepFlags step={step} />
          <span className="num ml-auto flex items-center gap-3 text-xs text-slate-400">
            {step.finish_reason && <span className="font-mono">{step.finish_reason}</span>}
            {step.latency_ms ? <span>{seconds(step.latency_ms)}</span> : null}
          </span>
        </div>
        <StepBody step={step} />
      </div>
    </div>
  );
}

export function TraceLegend() {
  const items: [string, string][] = [
    ["bg-defense-500", "Phòng thủ chặn"],
    ["bg-refusal-500", "Model từ chối"],
    ["bg-payload-500", "Payload"],
    ["bg-canary-500", "Canary"],
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
      {items.map(([cls, label]) => (
        <span key={label} className="flex items-center gap-1.5">
          <span className={clsx("h-2 w-2 rounded-sm", cls)} aria-hidden="true" />
          {label}
        </span>
      ))}
    </div>
  );
}
