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

// Lưới bố cục: năm cột (người dùng · agent · khe điểm móc · công cụ · khe điểm móc · dữ liệu), hàng
// công cụ cách đều; mọi đường nối vuông góc, không cắt qua thẻ, nhãn hay tiêu đề vùng.
const W = 1200;
const H = 640;

const TOP = 100; // mép trên các vùng
const ROW0 = 136; // hàng thẻ đầu tiên
const ROW_H = 48;
const ROW_GAP = 22;
const ROWS = [0, 1, 2, 3, 4].map((i) => ROW0 + i * (ROW_H + ROW_GAP));
const mid = (i: number) => ROWS[i] + ROW_H / 2;

const AGENT_X = 216;
const AGENT_W = 324;
const AGENT_R = AGENT_X + AGENT_W; // 540
const AGENT_C = AGENT_X + AGENT_W / 2; // 378
const TOOLS_Z = 652; // mép trái vùng công cụ
const TOOL_X = 668;
const TOOL_W = 184;
const TOOL_R = TOOL_X + TOOL_W; // 852
const DATA_X = 960;
const DATA_W = 208;
const GAP1 = (AGENT_R + 16 + TOOLS_Z) / 2; // tâm khe agent–công cụ (D2, D3)
const GAP2 = (TOOL_R + 16 + DATA_X - 16) / 2; // tâm khe công cụ–dữ liệu (D4)

const CTX_Y = 206;
const CTX_H = 60;
const LLM_Y = 292;
const LLM_H = 64;
const LOOP_Y = 382;
const LOOP_H = 60;
const RESULT_Y = CTX_Y + CTX_H / 2; // 236
const CALL_Y = LLM_Y + LLM_H / 2; // 324

const ZONES: { id: string; x: number; y: number; w: number; h: number; label: string; icon: LucideIcon }[] = [
  { id: "z-user", x: 16, y: TOP, w: 160, h: 380, label: "Người dùng", icon: Users },
  { id: "z-agent", x: 200, y: TOP, w: 356, h: 380, label: "Agent", icon: Bot },
  { id: "z-tools", x: TOOLS_Z, y: TOP, w: 216, h: 380, label: "Công cụ MCP", icon: Wrench },
  { id: "z-data", x: DATA_X - 16, y: TOP, w: 240, h: 380, label: "Dữ liệu & bồn chứa", icon: HardDrive },
  { id: "z-measure", x: 200, y: 508, w: 984, h: 116, label: "Hệ đo", icon: Activity },
];

export const NODES: Box[] = [
  { id: "user", x: 28, y: CTX_Y, w: 136, h: CTX_H, title: "Nhân viên", sub: "giao tác vụ", tone: "user", icon: UserRound },
  { id: "sys", x: AGENT_X, y: ROW0, w: AGENT_W, h: 48, title: "System prompt", sub: "TS1 · có canary", tone: "agent", icon: ScrollText },
  { id: "ctx", x: AGENT_X, y: CTX_Y, w: AGENT_W, h: CTX_H, title: "Ghép ngữ cảnh", sub: "câu hỏi · tài liệu · kết quả tool", tone: "agent", icon: Layers },
  { id: "llm", x: AGENT_X, y: LLM_Y, w: AGENT_W, h: LLM_H, title: "LLM", sub: "A1 · A2 · A3", tone: "brand", icon: BrainCircuit },
  { id: "loop", x: AGENT_X, y: LOOP_Y, w: AGENT_W, h: LOOP_H, title: "Vòng lặp agent", sub: "gọi tool hoặc trả lời", tone: "agent", icon: Repeat },
  { id: "search_kb", x: TOOL_X, y: ROWS[0], w: TOOL_W, h: ROW_H, title: "search_kb", sub: "tra kho tri thức", tone: "tool", icon: Search },
  { id: "query_customer_db", x: TOOL_X, y: ROWS[1], w: TOOL_W, h: ROW_H, title: "query_customer_db", sub: "đọc khách hàng", tone: "tool", icon: Database },
  { id: "http_request", x: TOOL_X, y: ROWS[2], w: TOOL_W, h: ROW_H, title: "http_request", sub: "gọi API", tone: "tool", icon: Globe },
  { id: "send_email", x: TOOL_X, y: ROWS[3], w: TOOL_W, h: ROW_H, title: "send_email", sub: "gửi ra ngoài", tone: "tool", icon: Send },
  { id: "create_ticket", x: TOOL_X, y: ROWS[4], w: TOOL_W, h: ROW_H, title: "create_ticket", sub: "ghi nội bộ", tone: "tool", icon: Ticket },
  { id: "kb", x: DATA_X, y: ROWS[0], w: DATA_W, h: ROW_H, title: "Kho tri thức", sub: "Qdrant · đích K1", tone: "store", icon: Library },
  { id: "db", x: DATA_X, y: ROWS[1], w: DATA_W, h: ROW_H, title: "customers.db", sub: "TS2 · có canary", tone: "store", icon: Database },
  { id: "canary", x: DATA_X, y: ROWS[2], w: DATA_W, h: ROW_H, title: "Canary listener", sub: "bồn G1 · HTTP", tone: "sink", icon: RadioTower },
  { id: "mail", x: DATA_X, y: ROWS[3], w: DATA_W, h: ROW_H, title: "MailHog", sub: "bồn G1/G2 · email", tone: "sink", icon: Inbox },
  { id: "tickets", x: DATA_X, y: ROWS[4], w: DATA_W, h: ROW_H, title: "Kho phiếu", sub: "bồn G2 · ghi nội bộ", tone: "sink", icon: ClipboardList },
  { id: "attacker", x: 740, y: 18, w: 300, h: 52, title: "Kẻ tấn công", sub: "cài payload T1–T8 vào dữ liệu", tone: "attack", icon: Skull },
  { id: "trace", x: AGENT_X, y: 540, w: AGENT_W, h: 54, title: "Trace store", sub: "mọi bước · blocked_by", tone: "measure", icon: History },
  { id: "scorer", x: TOOL_X, y: 540, w: TOOL_W, h: 54, title: "Scorer", sub: "chấm G1 · G2 · G3", tone: "measure", icon: ClipboardCheck },
  { id: "console", x: DATA_X, y: 540, w: DATA_W, h: 54, title: "Console", sub: "ASR · DSR · USR · FRR", tone: "measure", icon: LayoutDashboard },
];

type Edge = {
  id: string;
  d: string;
  kind?: "flow" | "inject" | "measure";
  label?: string;
  lx?: number;
  ly?: number;
  anchor?: "start" | "middle" | "end";
};

const R = 8; // bán kính bo góc đường gấp khúc

export const EDGES: Edge[] = [
  { id: "user-ctx", d: `M164 ${RESULT_Y} H${AGENT_X}`, label: "tác vụ", lx: 190, ly: RESULT_Y - 8 },
  { id: "sys-ctx", d: `M${AGENT_C} ${ROW0 + 48} V${CTX_Y}` },
  { id: "ctx-llm", d: `M${AGENT_C} ${CTX_Y + CTX_H} V${LLM_Y}` },
  { id: "llm-loop", d: `M${AGENT_C} ${LLM_Y + LLM_H} V${LOOP_Y}` },
  {
    id: "loop-user",
    d: `M${AGENT_X} ${LOOP_Y + LOOP_H / 2} H${96 + R} Q96 ${LOOP_Y + LOOP_H / 2} 96 ${LOOP_Y + LOOP_H / 2 - R} V${CTX_Y + CTX_H}`,
    label: "trả lời · G3",
    lx: 88,
    ly: 344,
    anchor: "end",
  },
  { id: "call", d: `M${AGENT_R} ${CALL_Y} H${TOOLS_Z}`, label: "gọi tool", lx: GAP1, ly: CALL_Y - 20 },
  { id: "result", d: `M${TOOLS_Z} ${RESULT_Y} H${AGENT_R}`, label: "kết quả", lx: GAP1, ly: RESULT_Y - 20 },
  // Dữ liệu chảy về tool khi đọc; chảy từ tool ra bồn chứa khi ghi/gửi.
  { id: "kb-io", d: `M${DATA_X} ${mid(0)} H${TOOL_R}` },
  { id: "db-io", d: `M${DATA_X} ${mid(1)} H${TOOL_R}` },
  { id: "http-out", d: `M${TOOL_R} ${mid(2)} H${DATA_X}` },
  { id: "mail-out", d: `M${TOOL_R} ${mid(3)} H${DATA_X}` },
  { id: "ticket-out", d: `M${TOOL_R} ${mid(4)} H${DATA_X}` },
  { id: "k1", d: `M1040 44 H${1150 - R} Q1150 44 1150 ${44 + R} V${ROWS[0]}`, kind: "inject", label: "K1", lx: 1142, ly: 92, anchor: "end" },
  { id: "k2a", d: `M800 70 V${ROWS[0]}`, kind: "inject", label: "K2a", lx: 808, ly: 92, anchor: "start" },
  { id: "k2b", d: `M740 44 H${640 + R} Q640 44 640 ${44 + R} V${RESULT_Y - 4}`, kind: "inject", label: "K2b", lx: 632, ly: 92, anchor: "end" },
  { id: "to-trace", d: `M${AGENT_C} ${LOOP_Y + LOOP_H} V540`, kind: "measure" },
  { id: "trace-scorer", d: `M${AGENT_R} 567 H${TOOL_X}`, kind: "measure" },
  { id: "scorer-console", d: `M${TOOL_R} 567 H${DATA_X}`, kind: "measure" },
];

/** Điểm móc phòng thủ — `stage` trùng `pipeline_order` của config/defenses.yaml. D1 nằm trong thẻ
 *  "Ghép ngữ cảnh"; D2/D3 ở khe agent–công cụ trên đường kết quả/lời gọi; D4 ở khe công cụ–bồn chứa. */
export const HOOKS: { id: string; code: DefenseCode; x: number; y: number; stage: string }[] = [
  { id: "h-d1", code: "D1", x: AGENT_R - 36, y: RESULT_Y, stage: "context_assembly" },
  { id: "h-d2", code: "D2", x: GAP1, y: RESULT_Y, stage: "kb_retrieval · tool_result" },
  { id: "h-d3", code: "D3", x: GAP1, y: CALL_Y, stage: "pre_tool_execution" },
  { id: "h-d4a", code: "D4", x: GAP2, y: mid(2), stage: "pre_egress" },
  { id: "h-d4b", code: "D4", x: GAP2, y: mid(3), stage: "pre_egress" },
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
      </defs>

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
              stroke="#eef2f6"
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
              className={clsx(on && "animate-[dash_1s_linear_infinite]")}
            />
            {e.label && (
              <text
                x={e.lx}
                y={e.ly}
                fontSize={10.5}
                textAnchor={e.anchor ?? "middle"}
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
              x={-23}
              y={-11}
              width={46}
              height={22}
              rx={11}
              fill={s.fill}
              stroke={selected === h.code ? "#2a55e0" : s.stroke}
              strokeWidth={selected === h.code ? 2.4 : 1.2}
              strokeDasharray={enabled ? undefined : "3 2"}
              filter={ref("shadow")}
            />
            <Icon x={-17} y={-6} width={12} height={12} color={s.text} strokeWidth={2.4} />
            <text x={6} y={4} textAnchor="middle" fontSize={11} fontWeight={700} fill={s.text}>
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
