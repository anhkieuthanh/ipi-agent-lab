// Sơ đồ kiến trúc của lab: người dùng → agent → công cụ MCP → dữ liệu/bồn chứa, ba đường tiêm
// K1/K2a/K2b của kẻ tấn công, năm điểm móc phòng thủ D1–D4 (đúng `pipeline_order` của
// config/defenses.yaml) và hệ đo. Một component dùng cho cả ba mức: xem (chọn thành phần), bật/tắt
// phòng thủ trên sơ đồ, và phát lại một run (tô sáng nút/cạnh, trạng thái từng điểm móc).

import clsx from "clsx";
import {
  Activity,
  Bot,
  BrainCircuit,
  ClipboardCheck,
  ClipboardList,
  Database,
  Globe,
  HardDrive,
  History,
  Inbox,
  LayoutDashboard,
  Layers,
  Library,
  type LucideIcon,
  RadioTower,
  Repeat,
  ScrollText,
  Search,
  Send,
  Shield,
  ShieldOff,
  Skull,
  Ticket,
  UserRound,
  Users,
  Wrench,
} from "lucide-react";
import { useId } from "react";

export type DefenseCode = "D1" | "D2" | "D3" | "D4";
export type PointStatus = "idle" | "pass" | "transform" | "block";

type Tone = "user" | "agent" | "brand" | "tool" | "store" | "sink" | "attack" | "measure";
type Box = { id: string; x: number; y: number; w: number; h: number; title: string; sub?: string; tone: Tone; icon: LucideIcon };

const W = 1180;
const H = 620;

const ZONES: { id: string; x: number; y: number; w: number; h: number; label: string; icon: LucideIcon }[] = [
  { id: "z-user", x: 16, y: 96, w: 150, h: 380, label: "Người dùng", icon: Users },
  { id: "z-agent", x: 196, y: 96, w: 372, h: 380, label: "Agent", icon: Bot },
  { id: "z-tools", x: 620, y: 96, w: 210, h: 380, label: "Công cụ MCP", icon: Wrench },
  { id: "z-data", x: 880, y: 96, w: 284, h: 380, label: "Dữ liệu & bồn chứa", icon: HardDrive },
  { id: "z-measure", x: 196, y: 510, w: 968, h: 96, label: "Hệ đo", icon: Activity },
];

const ROWS = [128, 196, 264, 332, 400];
const TOOL_X = 632;
const TOOL_W = 186;

export const NODES: Box[] = [
  { id: "user", x: 30, y: 246, w: 122, h: 78, title: "Nhân viên", sub: "giao tác vụ", tone: "user", icon: UserRound },
  { id: "sys", x: 216, y: 128, w: 332, h: 50, title: "System prompt", sub: "TS1 · có canary", tone: "agent", icon: ScrollText },
  { id: "ctx", x: 216, y: 204, w: 332, h: 62, title: "Ghép ngữ cảnh", sub: "câu hỏi · tài liệu · kết quả tool", tone: "agent", icon: Layers },
  { id: "llm", x: 216, y: 292, w: 332, h: 70, title: "LLM", sub: "A1 · A2 · A3", tone: "brand", icon: BrainCircuit },
  { id: "loop", x: 216, y: 388, w: 332, h: 62, title: "Vòng lặp agent", sub: "gọi tool hoặc trả lời", tone: "agent", icon: Repeat },
  { id: "search_kb", x: TOOL_X, y: ROWS[0], w: TOOL_W, h: 48, title: "search_kb", sub: "tra kho tri thức", tone: "tool", icon: Search },
  { id: "query_customer_db", x: TOOL_X, y: ROWS[1], w: TOOL_W, h: 48, title: "query_customer_db", sub: "đọc khách hàng", tone: "tool", icon: Database },
  { id: "http_request", x: TOOL_X, y: ROWS[2], w: TOOL_W, h: 48, title: "http_request", sub: "gọi API", tone: "tool", icon: Globe },
  { id: "send_email", x: TOOL_X, y: ROWS[3], w: TOOL_W, h: 48, title: "send_email", sub: "gửi ra ngoài", tone: "tool", icon: Send },
  { id: "create_ticket", x: TOOL_X, y: ROWS[4], w: TOOL_W, h: 48, title: "create_ticket", sub: "ghi nội bộ", tone: "tool", icon: Ticket },
  { id: "kb", x: 900, y: ROWS[0], w: 244, h: 48, title: "Kho tri thức", sub: "Qdrant · đích K1", tone: "store", icon: Library },
  { id: "db", x: 900, y: ROWS[1], w: 244, h: 48, title: "customers.db", sub: "TS2 · có canary", tone: "store", icon: Database },
  { id: "canary", x: 900, y: ROWS[2], w: 244, h: 48, title: "Canary listener", sub: "bồn G1 · HTTP", tone: "sink", icon: RadioTower },
  { id: "mail", x: 900, y: ROWS[3], w: 244, h: 48, title: "MailHog", sub: "bồn G1/G2 · email", tone: "sink", icon: Inbox },
  { id: "tickets", x: 900, y: ROWS[4], w: 244, h: 48, title: "Kho phiếu", sub: "bồn G2 · ghi nội bộ", tone: "sink", icon: ClipboardList },
  { id: "attacker", x: 700, y: 12, w: 300, h: 54, title: "Kẻ tấn công", sub: "cài payload T1–T8 vào dữ liệu", tone: "attack", icon: Skull },
  { id: "trace", x: 216, y: 534, w: 280, h: 54, title: "Trace store", sub: "mọi bước · blocked_by", tone: "measure", icon: History },
  { id: "scorer", x: 540, y: 534, w: 280, h: 54, title: "Scorer", sub: "chấm G1 · G2 · G3", tone: "measure", icon: ClipboardCheck },
  { id: "console", x: 864, y: 534, w: 280, h: 54, title: "Console", sub: "ASR · DSR · USR · FRR", tone: "measure", icon: LayoutDashboard },
];

type Edge = { id: string; d: string; kind?: "flow" | "inject" | "measure"; label?: string; lx?: number; ly?: number };

const mid = (i: number) => ROWS[i] + 24;
const TOOL_R = TOOL_X + TOOL_W;

export const EDGES: Edge[] = [
  { id: "user-ctx", d: "M152 272 C184 272 186 235 216 235", label: "tác vụ", lx: 176, ly: 244 },
  { id: "sys-ctx", d: "M382 178 V204" },
  { id: "ctx-llm", d: "M382 266 V292" },
  { id: "llm-loop", d: "M382 362 V388" },
  { id: "loop-user", d: "M216 430 C140 430 91 400 91 324", label: "câu trả lời · G3", lx: 112, ly: 450 },
  { id: "call", d: `M548 327 H${TOOL_X - 12}`, label: "gọi tool", lx: 584, ly: 318 },
  { id: "result", d: `M${TOOL_X - 12} 235 H548`, label: "kết quả", lx: 566, ly: 226 },
  { id: "kb-io", d: `M${TOOL_R} ${mid(0)} H900` },
  { id: "db-io", d: `M${TOOL_R} ${mid(1)} H900` },
  { id: "http-out", d: `M${TOOL_R} ${mid(2)} H900` },
  { id: "mail-out", d: `M${TOOL_R} ${mid(3)} H900` },
  { id: "ticket-out", d: `M${TOOL_R} ${mid(4)} H900` },
  { id: "k1", d: "M960 66 C960 96 1022 100 1022 128", kind: "inject", label: "K1", lx: 1000, ly: 94 },
  { id: "k2a", d: "M760 66 V128", kind: "inject", label: "K2a", lx: 778, ly: 94 },
  { id: "k2b", d: "M700 40 C604 40 604 150 604 227", kind: "inject", label: "K2b", lx: 622, ly: 94 },
  { id: "to-trace", d: "M300 450 V534", kind: "measure" },
  { id: "trace-scorer", d: "M496 561 H540", kind: "measure" },
  { id: "scorer-console", d: "M820 561 H864", kind: "measure" },
];

/** Điểm móc phòng thủ — `stage` trùng `pipeline_order` của config/defenses.yaml. */
export const HOOKS: { id: string; code: DefenseCode; x: number; y: number; stage: string }[] = [
  { id: "h-d1", code: "D1", x: 512, y: 204, stage: "context_assembly" },
  { id: "h-d2", code: "D2", x: 584, y: 250, stage: "kb_retrieval · tool_result" },
  { id: "h-d3", code: "D3", x: 584, y: 342, stage: "pre_tool_execution" },
  { id: "h-d4a", code: "D4", x: 859, y: mid(2), stage: "pre_egress" },
  { id: "h-d4b", code: "D4", x: 859, y: mid(3), stage: "pre_egress" },
];

/** Bảng màu theo nhóm thành phần: nền thẻ, viền, nền ô icon, màu icon/tiêu đề. */
const TONE: Record<Tone, { fill: string; stroke: string; tile: string; ink: string; title: string }> = {
  user: { fill: "#ffffff", stroke: "#cbd5e1", tile: "#ecfeff", ink: "#0e7490", title: "#0f172a" },
  agent: { fill: "#ffffff", stroke: "#cbd5e1", tile: "#eef4ff", ink: "#2a55e0", title: "#0f172a" },
  brand: { fill: "#f5f8ff", stroke: "#93b0fb", tile: "#2a55e0", ink: "#ffffff", title: "#1e3a8a" },
  tool: { fill: "#ffffff", stroke: "#cbd5e1", tile: "#f1f5f9", ink: "#334155", title: "#0f172a" },
  store: { fill: "#ffffff", stroke: "#cbd5e1", tile: "#f1f5f9", ink: "#475569", title: "#0f172a" },
  sink: { fill: "#fffbf5", stroke: "#fdba74", tile: "#ffedd5", ink: "#c2410c", title: "#9a3412" },
  attack: { fill: "#fff5f5", stroke: "#f19a9d", tile: "#fee2e2", ink: "#dc2626", title: "#a8262b" },
  measure: { fill: "#ffffff", stroke: "#d4d4f7", tile: "#f5f3ff", ink: "#7c3aed", title: "#334155" },
};

const HOOK_STYLE: Record<PointStatus | "off" | "on", { fill: string; stroke: string; text: string }> = {
  off: { fill: "#ffffff", stroke: "#cbd5e1", text: "#94a3b8" },
  on: { fill: "#16a34a", stroke: "#15803d", text: "#ffffff" },
  idle: { fill: "#16a34a", stroke: "#15803d", text: "#ffffff" },
  pass: { fill: "#16a34a", stroke: "#15803d", text: "#ffffff" },
  transform: { fill: "#f97316", stroke: "#ea580c", text: "#ffffff" },
  block: { fill: "#dc2626", stroke: "#991b1b", text: "#ffffff" },
};

const HALO = { stroke: "#ffffff", strokeWidth: 4, paintOrder: "stroke" as const, strokeLinejoin: "round" as const };

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
  const uid = useId().replace(/:/g, "");
  const ref = (name: string) => `url(#${name}-${uid})`;
  const dim = active.length > 0;
  const lit = (id: string) => !dim || active.includes(id);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={clsx("h-auto w-full select-none", className)} role="img" aria-label="Sơ đồ hệ thống">
      <defs>
        {[
          ["arrow", "#94a3b8"],
          ["arrow-red", "#e5484d"],
          ["arrow-blue", "#2a55e0"],
          ["arrow-violet", "#a78bfa"],
        ].map(([name, color]) => (
          <marker key={name} id={`${name}-${uid}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
            <path d="M0 1 L9 5 L0 9 z" fill={color} />
          </marker>
        ))}
        <filter id={`shadow-${uid}`} x="-10%" y="-20%" width="120%" height="150%">
          <feDropShadow dx="0" dy="1" stdDeviation="1.6" floodColor="#0f172a" floodOpacity="0.08" />
        </filter>
        <filter id={`glow-${uid}`} x="-20%" y="-40%" width="140%" height="180%">
          <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#2a55e0" floodOpacity="0.35" />
        </filter>
        <pattern id={`grid-${uid}`} width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.9" fill="#e2e8f0" />
        </pattern>
      </defs>

      <rect x={0} y={0} width={W} height={H} fill={ref("grid")} />

      {ZONES.map((z) => {
        const Icon = z.icon;
        return (
          <g key={z.id}>
            <rect
              x={z.x}
              y={z.y}
              width={z.w}
              height={z.h}
              rx={16}
              fill="#f8fafc"
              fillOpacity={0.92}
              stroke="#e2e8f0"
              strokeDasharray={z.id === "z-measure" ? "5 4" : undefined}
            />
            <Icon x={z.x + 14} y={z.y + 10} width={14} height={14} color="#94a3b8" strokeWidth={2} />
            <text x={z.x + 34} y={z.y + 21.5} fontSize={10.5} fontWeight={700} letterSpacing="0.09em" fill="#94a3b8">
              {z.label.toUpperCase()}
            </text>
          </g>
        );
      })}

      {EDGES.map((e) => {
        const on = lit(e.id) && dim;
        const inject = e.kind === "inject";
        const measure = e.kind === "measure";
        const color = inject ? "#e5484d" : on ? "#2a55e0" : measure ? "#c4b5fd" : "#94a3b8";
        const marker = inject ? ref("arrow-red") : on ? ref("arrow-blue") : measure ? ref("arrow-violet") : ref("arrow");
        const both = ["kb-io", "db-io"].includes(e.id);
        return (
          <g key={e.id} opacity={lit(e.id) ? 1 : 0.15} style={{ transition: "opacity .3s" }}>
            <path
              d={e.d}
              fill="none"
              stroke={color}
              strokeWidth={on ? 2.6 : inject ? 1.8 : 1.5}
              strokeLinecap="round"
              strokeDasharray={on ? "9 5" : inject ? "6 5" : measure ? "3 4" : undefined}
              markerEnd={marker}
              markerStart={both ? marker : undefined}
              className={clsx(on && "animate-[dash_1s_linear_infinite]")}
            />
            {e.label && (
              <text
                x={e.lx}
                y={e.ly}
                fontSize={10.5}
                textAnchor="middle"
                fill={inject ? "#c5221f" : on ? "#2a55e0" : "#64748b"}
                fontWeight={inject ? 700 : 600}
                {...HALO}
              >
                {e.label}
              </text>
            )}
          </g>
        );
      })}

      {NODES.map((n) => {
        const t = TONE[n.tone];
        const Icon = n.icon;
        const isSel = selected === n.id;
        const isLit = lit(n.id);
        const hot = isSel || (dim && isLit);
        const mono = n.id.includes("_");
        const tile = n.h >= 60 ? 34 : 30;
        const cy = n.y + n.h / 2;
        return (
          <g
            key={n.id}
            onClick={() => onSelect?.(n.id)}
            className={clsx(onSelect && "cursor-pointer")}
            opacity={isLit ? 1 : 0.28}
            style={{ transition: "opacity .3s" }}
          >
            <rect
              x={n.x}
              y={n.y}
              width={n.w}
              height={n.h}
              rx={12}
              fill={t.fill}
              stroke={hot ? "#2a55e0" : t.stroke}
              strokeWidth={hot ? 2 : 1}
              filter={hot ? ref("glow") : ref("shadow")}
            />
            <rect x={n.x + 10} y={cy - tile / 2} width={tile} height={tile} rx={8} fill={t.tile} />
            <Icon
              x={n.x + 10 + (tile - 18) / 2}
              y={cy - 9}
              width={18}
              height={18}
              color={t.ink}
              strokeWidth={2}
            />
            <text
              x={n.x + 20 + tile}
              y={n.sub ? cy - 3 : cy + 5}
              fontSize={mono ? 12.5 : 13.5}
              fontWeight={600}
              fill={t.title}
              fontFamily={mono ? "JetBrains Mono, monospace" : undefined}
            >
              {n.title}
            </text>
            {n.sub && (
              <text x={n.x + 20 + tile} y={cy + 13} fontSize={11} fill="#64748b">
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
        const Icon = enabled ? Shield : ShieldOff;
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
            <title>
              {`${h.code} · ${!enabled ? "tắt" : status ? STATUS_LABEL[status] : "bật"}${onToggle ? " — bấm để " + (enabled ? "tắt" : "bật") : ""}`}
            </title>
            {status === "block" && (
              <circle r={22} fill="#dc2626" opacity={0.18} className="animate-ping" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
            )}
            <rect
              x={-25}
              y={-12}
              width={50}
              height={24}
              rx={12}
              fill={s.fill}
              stroke={selected === h.code ? "#2a55e0" : s.stroke}
              strokeWidth={selected === h.code ? 2.4 : 1.2}
              strokeDasharray={enabled ? undefined : "3 2"}
              filter={ref("shadow")}
            />
            <Icon x={-19} y={-6.5} width={13} height={13} color={s.text} strokeWidth={2.4} />
            <text x={6} y={4.5} textAnchor="middle" fontSize={11.5} fontWeight={700} fill={s.text}>
              {h.code}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export const STATUS_LABEL: Record<PointStatus, string> = {
  idle: "bật",
  pass: "không can thiệp",
  transform: "biến đổi / gắn cờ",
  block: "chặn / xin xác nhận",
};

type Hit = Record<string, unknown>;

/** Trạng thái từng điểm móc của một run: chặn (block/confirm) > biến đổi (transform/flag) > cho qua.
 *  `codes` là các mã D bật trong preset của run; mã không bật thì không có trạng thái. */
export function hookStatusFromSteps(steps: { hits: Hit[] }[], codes: string[]): Partial<Record<DefenseCode, PointStatus>> {
  const out: Partial<Record<DefenseCode, PointStatus>> = {};
  for (const c of codes) out[c as DefenseCode] = "pass";
  for (const h of steps.flatMap((s) => s.hits)) {
    const code = String(h.defense ?? "").slice(0, 2).toUpperCase() as DefenseCode;
    if (!(code in out)) continue;
    const action = String(h.action ?? "");
    if (action === "block" || action === "confirm") out[code] = "block";
    else if ((action === "transform" || action === "flag") && out[code] !== "block") out[code] = "transform";
  }
  return out;
}

function Pill({ color, off, children }: { color: string; off?: boolean; children: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-bold",
        off ? "border border-dashed border-slate-300 bg-white text-slate-400" : "text-white",
      )}
      style={off ? undefined : { background: color }}
    >
      {off ? <ShieldOff size={10} strokeWidth={2.6} /> : <Shield size={10} strokeWidth={2.6} />}
      {children}
    </span>
  );
}

export function HookLegend({ statuses = false }: { statuses?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-slate-500">
      <span className="flex items-center gap-1.5">
        <Pill color="" off>D</Pill>Tắt
      </span>
      <span className="flex items-center gap-1.5">
        <Pill color="#16a34a">D</Pill>
        {statuses ? "Bật, không can thiệp" : "Bật"}
      </span>
      {statuses && (
        <>
          <span className="flex items-center gap-1.5">
            <Pill color="#f97316">D</Pill>Biến đổi / gắn cờ
          </span>
          <span className="flex items-center gap-1.5">
            <Pill color="#dc2626">D</Pill>Chặn / xin xác nhận
          </span>
        </>
      )}
    </div>
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
        <svg width="28" height="8"><path d="M0 4 H28" stroke="#c4b5fd" strokeWidth="1.6" strokeDasharray="3 4" /></svg>Ghi trace / chấm điểm
      </span>
      <span className="flex items-center gap-2">
        <Pill color="#16a34a">D</Pill>Điểm phòng thủ
      </span>
      <span className="flex items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-orange-100 text-orange-700">
          <Inbox size={12} />
        </span>
        Bồn chứa (nơi đo G1/G2)
      </span>
    </div>
  );
}
