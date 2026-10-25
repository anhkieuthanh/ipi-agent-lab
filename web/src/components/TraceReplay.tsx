// Phát lại trace một run trên SystemMap: mỗi bước trace thành một khung — tô sáng nút/cạnh agent đi
// qua và đèn các điểm móc D1–D4 có hit ở bước đó. Khung cuối là tổng kết (trace → scorer, trạng thái
// toàn run). Ánh xạ bám đúng thứ tự trong src/agent/core.py: gate PRE_TOOL_EXECUTION → PRE_EGRESS →
// gọi tool → KB_RETRIEVAL/TOOL_RESULT → CONTEXT_ASSEMBLY.

import clsx from "clsx";
import {
  BrainCircuit,
  FileWarning,
  Flag,
  type LucideIcon,
  Pause,
  Play,
  RotateCcw,
  ShieldAlert,
  SkipBack,
  SkipForward,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { RunDetail, Step } from "@/lib/api";

import { type DefenseCode, HookLegend, type PointStatus, SystemMap, hookStatusFromSteps } from "./SystemMap";

type Frame = {
  title: string;
  detail?: string;
  tone: "neutral" | "payload" | "block" | "verdict";
  active: string[];
  status: Partial<Record<DefenseCode, PointStatus>>;
  notes: string[];
};

/** Bồn/nguồn dữ liệu và cạnh nối của từng tool trên sơ đồ. */
const TOOL_LINK: Record<string, [string, string]> = {
  search_kb: ["kb", "kb-io"],
  query_customer_db: ["db", "db-io"],
  http_request: ["canary", "http-out"],
  send_email: ["mail", "mail-out"],
  create_ticket: ["tickets", "ticket-out"],
};

const ACTION_LABEL: Record<string, string> = {
  block: "chặn",
  confirm: "xin xác nhận",
  transform: "biến đổi",
  flag: "gắn cờ",
};

function calledTools(step: Step): string[] {
  try {
    const calls = JSON.parse(step.fields.tool_args?.text ?? "[]");
    return Array.isArray(calls) ? calls.map((c) => String(c?.name ?? "")).filter(Boolean) : [];
  } catch {
    return [];
  }
}

/** Đèn của một bước: mã D bật mà không có hit ở bước này ⇒ "idle". */
function stepStatus(step: Step, codes: string[]) {
  const status = hookStatusFromSteps([step], codes);
  for (const c of codes) if (status[c as DefenseCode] === "pass") status[c as DefenseCode] = "idle";
  return status;
}

function hitNotes(step: Step): string[] {
  const seen = new Set<string>();
  for (const h of step.hits) {
    const code = String(h.defense ?? "").slice(0, 2).toUpperCase();
    const action = ACTION_LABEL[String(h.action ?? "")] ?? String(h.action ?? "");
    const rule = h.rule ? ` · ${h.rule}` : "";
    seen.add(`${code} ${action}${rule} — ${String(h.detail ?? "")}`);
  }
  return [...seen];
}

export function buildFrames(d: RunDetail, codes: string[]): Frame[] {
  const channel = String(d.run.channel ?? "");
  const frames: Frame[] = [];
  d.steps.forEach((s, i) => {
    const status = stepStatus(s, codes);
    const notes = [...hitNotes(s), ...s.events];
    const payload = s.payload_fields.length > 0;
    const n = `Bước ${i + 1}`;
    if (s.kind === "llm") {
      const tools = calledTools(s);
      const active = ["ctx", "llm", "loop", "ctx-llm", "llm-loop"];
      if (i === 0) active.push("user", "sys", "user-ctx", "sys-ctx");
      if (i === 0 && channel === "K2a") active.push("attacker", "k2a");
      if (tools.length) {
        active.push("call", ...tools);
        frames.push({
          title: `${n} · LLM quyết định gọi ${tools.join(", ")}`,
          detail: i === 0 ? "Ghép câu hỏi, system prompt và mô tả tool rồi gửi LLM." : "LLM đọc kết quả tool, chọn bước tiếp.",
          tone: s.refusal ? "verdict" : "neutral",
          active,
          status,
          notes,
        });
      } else {
        active.push("loop-user", "user");
        frames.push({
          title: `${n} · LLM trả lời nhân viên`,
          detail: s.refusal ? "Model từ chối thực hiện." : "Kết thúc vòng lặp — câu trả lời cuối (nơi chấm G3).",
          tone: payload ? "payload" : "neutral",
          active,
          status,
          notes,
        });
      }
      return;
    }
    const tool = s.tool_name ?? "";
    const [sink, link] = TOOL_LINK[tool] ?? ["", ""];
    if (s.kind === "defense") {
      frames.push({
        title: `${n} · Phòng thủ chặn ${tool}`,
        detail: "Lời gọi dừng ở điểm móc, tool không chạy; agent nhận thông báo bị chặn.",
        tone: "block",
        active: ["loop", "call", tool],
        status,
        notes,
      });
      return;
    }
    const active = ["call", tool, sink, link, "result", "ctx"];
    if (payload && tool === "search_kb") active.push("attacker", "k1");
    else if (payload && channel === "K2b") active.push("attacker", "k2b");
    frames.push({
      title: `${n} · Chạy ${tool}`,
      detail: payload ? "Kết quả trả về chứa payload — đi vào ngữ cảnh của LLM." : "Kết quả trả về ghép vào ngữ cảnh.",
      tone: payload ? "payload" : "neutral",
      active: active.filter(Boolean),
      status,
      notes,
    });
  });
  frames.push({
    title: "Tổng kết · ghi trace, scorer chấm",
    detail: d.verdict ? `${d.verdict.label} — ${d.verdict.detail}` : undefined,
    tone: "verdict",
    active: ["loop", "to-trace", "trace", "trace-scorer", "scorer", "scorer-console", "console"],
    status: hookStatusFromSteps(d.steps, codes),
    notes: d.run.blocked_by ? [`blocked_by = ${d.run.blocked_by}`] : [],
  });
  return frames;
}

const TONE_STYLE: Record<Frame["tone"], string> = {
  neutral: "border-brand-500 bg-brand-50/60",
  payload: "border-payload-500 bg-payload-50",
  block: "border-attack-500 bg-attack-50",
  verdict: "border-slate-400 bg-slate-50",
};

const TONE_ICON: Record<Frame["tone"], [LucideIcon, string]> = {
  neutral: [BrainCircuit, "text-brand-600"],
  payload: [FileWarning, "text-payload-600"],
  block: [ShieldAlert, "text-attack-600"],
  verdict: [Flag, "text-slate-500"],
};

const SPEEDS = [0.5, 1, 2];

export function TraceReplay({ detail, codes, autoplay = false }: { detail: RunDetail; codes: string[]; autoplay?: boolean }) {
  const frames = useMemo(() => buildFrames(detail, codes), [detail, codes]);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(autoplay);
  const [speed, setSpeed] = useState(1);
  const last = frames.length - 1;

  useEffect(() => {
    setI(0);
    setPlaying(autoplay);
  }, [detail, autoplay]);

  useEffect(() => {
    if (!playing) return;
    if (i >= last) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setI((x) => Math.min(x + 1, last)), 1800 / speed);
    return () => clearTimeout(t);
  }, [playing, i, last, speed]);

  const f = frames[i];
  const [ToneIcon, toneInk] = TONE_ICON[f.tone];
  const defenses = Object.fromEntries((["D1", "D2", "D3", "D4"] as DefenseCode[]).map((c) => [c, codes.includes(c)]));
  const btn = "flex h-8 w-8 items-center justify-center rounded-md text-slate-600 ring-1 ring-inset ring-slate-200 hover:bg-slate-50 disabled:opacity-40";

  return (
    <div>
      <div className="px-4 pb-2 pt-3">
        <SystemMap defenses={defenses} hookStatus={f.status} active={f.active} />
      </div>

      <div className="border-t border-slate-100 px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <button className={btn} onClick={() => { setPlaying(false); setI(0); }} disabled={i === 0} title="Về đầu">
            <SkipBack size={14} />
          </button>
          <button
            className={clsx(btn, "w-auto gap-1.5 px-3 text-[12.5px] font-medium text-brand-700 ring-brand-100")}
            onClick={() => {
              if (i >= last) setI(0);
              setPlaying(!playing || i >= last);
            }}
          >
            {playing ? <Pause size={14} /> : i >= last ? <RotateCcw size={14} /> : <Play size={14} />}
            {playing ? "Tạm dừng" : i >= last ? "Phát lại" : "Phát"}
          </button>
          <button className={btn} onClick={() => { setPlaying(false); setI(Math.min(i + 1, last)); }} disabled={i >= last} title="Bước sau">
            <SkipForward size={14} />
          </button>
          <input
            type="range"
            min={0}
            max={last}
            value={i}
            onChange={(e) => { setPlaying(false); setI(Number(e.target.value)); }}
            className="mx-2 min-w-[120px] flex-1 accent-brand-600"
            aria-label="Khung phát lại"
          />
          <span className="num text-[12px] text-slate-500">
            {i + 1}/{frames.length}
          </span>
          <select
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
            className="h-8 rounded-md border-slate-200 py-0 text-[12px]"
            aria-label="Tốc độ"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </div>

        <div className={clsx("mt-3 rounded-lg border-l-4 px-4 py-2.5", TONE_STYLE[f.tone])}>
          <div className="flex items-center gap-2 text-[13.5px] font-semibold text-slate-800">
            <ToneIcon size={15} className={clsx("shrink-0", toneInk)} />
            {f.title}
          </div>
          {f.detail && <div className="mt-0.5 text-[12.5px] text-slate-600">{f.detail}</div>}
          {f.notes.length > 0 && (
            <ul className="mt-1.5 space-y-0.5 text-[12px] text-slate-600">
              {f.notes.map((x) => (
                <li key={x} className="font-mono">
                  {x}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mt-3">
          <HookLegend statuses />
        </div>
      </div>
    </div>
  );
}
