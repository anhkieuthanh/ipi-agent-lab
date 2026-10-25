// Sơ đồ kiến trúc của lab: người dùng → agent → công cụ MCP → dữ liệu/bồn chứa, ba đường tiêm
// K1/K2a/K2b của kẻ tấn công, năm điểm móc phòng thủ D1–D4 (đúng `pipeline_order` của
// config/defenses.yaml) và hệ đo. Một component dùng cho cả ba mức: xem (chọn thành phần), bật/tắt
// phòng thủ trên sơ đồ, và phát lại một run (tô sáng nút/cạnh, trạng thái từng điểm móc).

import clsx from "clsx";

export type DefenseCode = "D1" | "D2" | "D3" | "D4";
export type PointStatus = "idle" | "pass" | "transform" | "block";

type Box = { id: string; x: number; y: number; w: number; h: number; title: string; sub?: string; tone?: Tone };
type Tone = "plain" | "brand" | "attack" | "sink" | "store" | "measure";

const W = 1180;
const H = 620;

const ZONES = [
  { id: "z-user", x: 16, y: 96, w: 150, h: 380, label: "Người dùng" },
  { id: "z-agent", x: 196, y: 96, w: 372, h: 380, label: "Agent" },
  { id: "z-tools", x: 620, y: 96, w: 210, h: 380, label: "Công cụ MCP" },
  { id: "z-data", x: 880, y: 96, w: 284, h: 380, label: "Dữ liệu & bồn chứa" },
  { id: "z-measure", x: 196, y: 510, w: 968, h: 96, label: "Hệ đo" },
];

const ROWS = [128, 196, 264, 332, 400];

export const NODES: Box[] = [
  { id: "user", x: 34, y: 250, w: 114, h: 70, title: "Nhân viên", sub: "giao tác vụ" },
  { id: "sys", x: 216, y: 128, w: 332, h: 50, title: "System prompt", sub: "TS1 · có canary" },
  { id: "ctx", x: 216, y: 204, w: 332, h: 62, title: "Ghép ngữ cảnh", sub: "câu hỏi · tài liệu · kết quả tool" },
  { id: "llm", x: 216, y: 292, w: 332, h: 70, title: "LLM", sub: "A1 · A2 · A3", tone: "brand" },
  { id: "loop", x: 216, y: 388, w: 332, h: 62, title: "Vòng lặp agent", sub: "gọi tool hoặc trả lời" },
  { id: "search_kb", x: 640, y: ROWS[0], w: 170, h: 48, title: "search_kb", sub: "tra kho tri thức" },
  { id: "query_customer_db", x: 640, y: ROWS[1], w: 170, h: 48, title: "query_customer_db", sub: "đọc khách hàng" },
  { id: "http_request", x: 640, y: ROWS[2], w: 170, h: 48, title: "http_request", sub: "gọi API" },
  { id: "send_email", x: 640, y: ROWS[3], w: 170, h: 48, title: "send_email", sub: "gửi ra ngoài" },
  { id: "create_ticket", x: 640, y: ROWS[4], w: 170, h: 48, title: "create_ticket", sub: "ghi nội bộ" },
  { id: "kb", x: 900, y: ROWS[0], w: 244, h: 48, title: "Kho tri thức", sub: "Qdrant · đích K1", tone: "store" },
  { id: "db", x: 900, y: ROWS[1], w: 244, h: 48, title: "customers.db", sub: "TS2 · có canary", tone: "store" },
  { id: "canary", x: 900, y: ROWS[2], w: 244, h: 48, title: "Canary listener", sub: "bồn G1 · HTTP", tone: "sink" },
  { id: "mail", x: 900, y: ROWS[3], w: 244, h: 48, title: "MailHog", sub: "bồn G1/G2 · email", tone: "sink" },
  { id: "tickets", x: 900, y: ROWS[4], w: 244, h: 48, title: "Kho phiếu", sub: "bồn G2 · ghi nội bộ", tone: "sink" },
  { id: "attacker", x: 700, y: 14, w: 300, h: 50, title: "Kẻ tấn công", sub: "cài payload T1–T8 vào dữ liệu", tone: "attack" },
  { id: "trace", x: 216, y: 534, w: 280, h: 54, title: "Trace store", sub: "mọi bước · blocked_by", tone: "measure" },
  { id: "scorer", x: 540, y: 534, w: 280, h: 54, title: "Scorer", sub: "chấm G1 · G2 · G3", tone: "measure" },
  { id: "console", x: 864, y: 534, w: 280, h: 54, title: "Console", sub: "ASR · DSR · USR · FRR", tone: "measure" },
];

type Edge = { id: string; d: string; kind?: "flow" | "inject" | "measure"; label?: string; lx?: number; ly?: number };

const mid = (i: number) => ROWS[i] + 24;

export const EDGES: Edge[] = [
  { id: "user-ctx", d: "M148 272 C182 272 184 235 216 235", label: "tác vụ", lx: 168, ly: 240 },
  { id: "sys-ctx", d: "M382 178 V204" },
  { id: "ctx-llm", d: "M382 266 V292" },
  { id: "llm-loop", d: "M382 362 V388" },
  { id: "loop-user", d: "M216 430 C140 430 91 400 91 322", label: "câu trả lời · G3", lx: 104, ly: 446 },
  { id: "call", d: "M548 327 H620", label: "gọi tool", lx: 584, ly: 318 },
  { id: "result", d: "M620 235 H548", label: "kết quả", lx: 568, ly: 226 },
  { id: "kb-io", d: `M810 ${mid(0)} H900` },
  { id: "db-io", d: `M810 ${mid(1)} H900` },
  { id: "http-out", d: `M810 ${mid(2)} H900` },
  { id: "mail-out", d: `M810 ${mid(3)} H900` },
  { id: "ticket-out", d: `M810 ${mid(4)} H900` },
  { id: "k1", d: "M960 64 C960 96 1022 100 1022 128", kind: "inject", label: "K1", lx: 1000, ly: 92 },
  { id: "k2a", d: "M760 64 V112", kind: "inject", label: "K2a", lx: 774, ly: 88 },
  { id: "k2b", d: "M700 40 C606 40 606 150 606 227", kind: "inject", label: "K2b", lx: 622, ly: 92 },
  { id: "to-trace", d: "M300 450 V534", kind: "measure" },
  { id: "trace-scorer", d: "M496 561 H540", kind: "measure" },
  { id: "scorer-console", d: "M820 561 H864", kind: "measure" },
];

/** Điểm móc phòng thủ — `stage` trùng `pipeline_order` của config/defenses.yaml. */
export const HOOKS: { id: string; code: DefenseCode; x: number; y: number; stage: string }[] = [
  { id: "h-d1", code: "D1", x: 516, y: 204, stage: "context_assembly" },
  { id: "h-d2", code: "D2", x: 584, y: 248, stage: "kb_retrieval · tool_result" },
  { id: "h-d3", code: "D3", x: 584, y: 340, stage: "pre_tool_execution" },
  { id: "h-d4a", code: "D4", x: 855, y: mid(2), stage: "pre_egress" },
  { id: "h-d4b", code: "D4", x: 855, y: mid(3), stage: "pre_egress" },
];

const TONE: Record<Tone, { fill: string; stroke: string; title: string }> = {
  plain: { fill: "#ffffff", stroke: "#cbd5e1", title: "#0f172a" },
  brand: { fill: "#eef4ff", stroke: "#93b0fb", title: "#1e3a8a" },
  attack: { fill: "#fef2f2", stroke: "#f19a9d", title: "#a8262b" },
  sink: { fill: "#fff7ed", stroke: "#fdba74", title: "#9a3412" },
  store: { fill: "#f8fafc", stroke: "#cbd5e1", title: "#0f172a" },
  measure: { fill: "#f8fafc", stroke: "#cbd5e1", title: "#334155" },
};

const HOOK_STYLE: Record<PointStatus | "off" | "on", { fill: string; stroke: string; text: string }> = {
  off: { fill: "#ffffff", stroke: "#cbd5e1", text: "#94a3b8" },
  on: { fill: "#16a34a", stroke: "#15803d", text: "#ffffff" },
  idle: { fill: "#16a34a", stroke: "#15803d", text: "#ffffff" },
  pass: { fill: "#16a34a", stroke: "#15803d", text: "#ffffff" },
  transform: { fill: "#f97316", stroke: "#ea580c", text: "#ffffff" },
  block: { fill: "#dc2626", stroke: "#991b1b", text: "#ffffff" },
};

export type SystemMapProps = {
  selected?: string | null;
  onSelect?: (id: string) => void;
  /** Có giá trị ⇒ điểm móc hiển thị bật/tắt; thiếu ⇒ hiển thị trung tính (bật). */
  defenses?: Partial<Record<DefenseCode, boolean>>;
  onToggle?: (code: DefenseCode) => void;
  /** Trạng thái từng điểm móc khi phát lại một run. */
  hookStatus?: Partial<Record<DefenseCode, PointStatus>>;
  /** Nút/cạnh đang tô sáng (phát lại run). Rỗng ⇒ không làm mờ phần còn lại. */
  active?: string[];
  className?: string;
};

export function SystemMap({ selected, onSelect, defenses, onToggle, hookStatus, active = [], className }: SystemMapProps) {
  const dim = active.length > 0;
  const lit = (id: string) => !dim || active.includes(id);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={clsx("h-auto w-full select-none", className)} role="img" aria-label="Sơ đồ hệ thống">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="#64748b" />
        </marker>
        <marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="#e5484d" />
        </marker>
        <marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="#2a55e0" />
        </marker>
      </defs>

      {ZONES.map((z) => (
        <g key={z.id}>
          <rect x={z.x} y={z.y} width={z.w} height={z.h} rx={14} fill="#f8fafc" stroke="#e2e8f0" strokeDasharray={z.id === "z-measure" ? "4 4" : undefined} />
          <text x={z.x + 14} y={z.y + 20} fontSize={11} fontWeight={600} letterSpacing="0.08em" fill="#94a3b8">
            {z.label.toUpperCase()}
          </text>
        </g>
      ))}

      {EDGES.map((e) => {
        const on = lit(e.id) && dim;
        const color = e.kind === "inject" ? "#e5484d" : on ? "#2a55e0" : e.kind === "measure" ? "#cbd5e1" : "#94a3b8";
        const marker = e.kind === "inject" ? "url(#arrow-red)" : on ? "url(#arrow-blue)" : "url(#arrow)";
        const both = ["kb-io", "db-io"].includes(e.id);
        return (
          <g key={e.id} opacity={lit(e.id) ? 1 : 0.18} className="transition-opacity duration-300">
            <path
              d={e.d}
              fill="none"
              stroke={color}
              strokeWidth={on ? 2.6 : e.kind === "inject" ? 1.8 : 1.6}
              strokeDasharray={on ? "9 5" : e.kind === "inject" ? "6 5" : e.kind === "measure" ? "3 4" : undefined}
              markerEnd={marker}
              markerStart={both ? marker : undefined}
              className={clsx(on && "animate-[dash_1s_linear_infinite]")}
            />
            {e.label && (
              <text x={e.lx} y={e.ly} fontSize={11} textAnchor="middle" fill={e.kind === "inject" ? "#c5221f" : "#64748b"} fontWeight={e.kind === "inject" ? 700 : 500}>
                {e.label}
              </text>
            )}
          </g>
        );
      })}

      {NODES.map((n) => {
        const t = TONE[n.tone ?? "plain"];
        const isSel = selected === n.id;
        const isLit = lit(n.id);
        return (
          <g
            key={n.id}
            onClick={() => onSelect?.(n.id)}
            className={clsx(onSelect && "cursor-pointer")}
            opacity={isLit ? 1 : 0.25}
            style={{ transition: "opacity .3s" }}
          >
            <rect
              x={n.x}
              y={n.y}
              width={n.w}
              height={n.h}
              rx={10}
              fill={t.fill}
              stroke={isSel ? "#2a55e0" : dim && isLit ? "#2a55e0" : t.stroke}
              strokeWidth={isSel || (dim && isLit) ? 2.4 : 1.2}
            />
            <text x={n.x + n.w / 2} y={n.y + (n.sub ? n.h / 2 - 3 : n.h / 2 + 5)} textAnchor="middle" fontSize={n.id.includes("_") ? 13 : 14} fontWeight={600} fill={t.title} fontFamily={n.id.includes("_") ? "JetBrains Mono, monospace" : undefined}>
              {n.title}
            </text>
            {n.sub && (
              <text x={n.x + n.w / 2} y={n.y + n.h / 2 + 14} textAnchor="middle" fontSize={11.5} fill="#64748b">
                {n.sub}
              </text>
            )}
          </g>
        );
      })}

      {HOOKS.map((h) => {
        const enabled = defenses ? defenses[h.code] !== false : true;
        const status = hookStatus?.[h.code];
        const key = !enabled ? "off" : status ?? "on";
        const s = HOOK_STYLE[key];
        const interactive = !!onToggle || !!onSelect;
        return (
          <g
            key={h.id}
            transform={`translate(${h.x}, ${h.y})`}
            onClick={(ev) => {
              ev.stopPropagation();
              if (onToggle) onToggle(h.code);
              else onSelect?.(h.code);
            }}
            className={clsx(interactive && "cursor-pointer")}
          >
            {status === "block" && <circle r={22} fill="#dc2626" opacity={0.18} className="animate-ping" style={{ transformOrigin: "center" }} />}
            <rect x={-22} y={-12} width={44} height={24} rx={12} fill={s.fill} stroke={selected === h.code ? "#2a55e0" : s.stroke} strokeWidth={selected === h.code ? 2.4 : 1.4} />
            <text y={4.5} textAnchor="middle" fontSize={12} fontWeight={700} fill={s.text}>
              {h.code}
            </text>
            <circle cx={18} cy={-10} r={4.5} fill={enabled ? (status === "block" ? "#dc2626" : status === "transform" ? "#f97316" : "#22c55e") : "#cbd5e1"} stroke="#fff" strokeWidth={1.5} />
          </g>
        );
      })}
    </svg>
  );
}

export function MapLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[12px] text-slate-500">
      <span className="flex items-center gap-2">
        <svg width="28" height="8"><path d="M0 4 H28" stroke="#94a3b8" strokeWidth="1.6" /></svg>Dữ liệu / lời gọi
      </span>
      <span className="flex items-center gap-2">
        <svg width="28" height="8"><path d="M0 4 H28" stroke="#e5484d" strokeWidth="1.8" strokeDasharray="6 5" /></svg>Đường tiêm nhiễm
      </span>
      <span className="flex items-center gap-2">
        <span className="rounded-full bg-defense-600 px-2 text-[10px] font-bold text-white">D</span>Điểm phòng thủ
      </span>
      <span className="flex items-center gap-2">
        <span className="h-3 w-3 rounded border border-orange-300 bg-orange-50" />Bồn chứa (nơi đo G1/G2)
      </span>
    </div>
  );
}
