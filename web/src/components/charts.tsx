// Biểu đồ SVG viết tay, không phụ thuộc thư viện. Màu lấy từ biến trong tokens.css nên tự đổi theo
// chế độ sáng/tối; nghĩa của mỗi điểm nằm ở nhãn chữ đặt cạnh điểm, màu chỉ hỗ trợ.

export type ScatterPoint = {
  id: string;
  /** Tỉ lệ 0–1 trên trục ngang và trục dọc. */
  x: number;
  y: number;
  /** Nhãn ngắn đặt ngay cạnh điểm. */
  label: string;
  /** Tên biến màu trong tokens.css, không kèm `--` (vd "defense-500"). */
  color: string;
  /** Nội dung chú giải khi rê chuột (thẻ <title>). */
  title: string;
  /** Khoảng tin cậy 0–1; có thì vẽ râu mảnh quanh điểm. */
  xLo?: number | null;
  xHi?: number | null;
  yLo?: number | null;
  yHi?: number | null;
};

const W = 640;
const H = 380;
const M = { top: 14, right: 18, bottom: 46, left: 54 };
const PW = W - M.left - M.right;
const PH = H - M.top - M.bottom;
const TICKS = [0, 0.25, 0.5, 0.75, 1];
const R = 4.5;
const LABEL_H = 13;
const CHAR_W = 6.3;

const sx = (v: number) => M.left + Math.min(Math.max(v, 0), 1) * PW;
const sy = (v: number) => M.top + (1 - Math.min(Math.max(v, 0), 1)) * PH;
const tok = (name: string, alpha?: number) => (alpha === undefined ? `rgb(var(--${name}))` : `rgb(var(--${name}) / ${alpha})`);

type Box = { x: number; y: number; w: number; h: number };
const hit = (a: Box, b: Box) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

type Placed = { tx: number; ty: number; anchor: "start" | "end" | "middle" };

/** Xếp nhãn tham lam: thử phải, trái, trên, dưới rồi các góc; chọn vị trí đầu tiên không đè nhãn hay điểm khác. */
function placeLabels(points: ScatterPoint[]): Map<string, Placed> {
  const dots: (Box & { id: string })[] = points.map((p) => ({ id: p.id, x: sx(p.x) - R - 1, y: sy(p.y) - R - 1, w: 2 * R + 2, h: 2 * R + 2 }));
  const taken: Box[] = [];
  const out = new Map<string, Placed>();
  const order = [...points].sort((a, b) => b.y - a.y || a.x - b.x);
  for (const p of order) {
    const cx = sx(p.x);
    const cy = sy(p.y);
    const w = p.label.length * CHAR_W + 2;
    const g = R + 4;
    const cands: (Placed & { box: Box })[] = [
      { tx: cx + g, ty: cy + 4, anchor: "start", box: { x: cx + g, y: cy - LABEL_H / 2, w, h: LABEL_H } },
      { tx: cx - g, ty: cy + 4, anchor: "end", box: { x: cx - g - w, y: cy - LABEL_H / 2, w, h: LABEL_H } },
      { tx: cx, ty: cy - g - 2, anchor: "middle", box: { x: cx - w / 2, y: cy - g - LABEL_H, w, h: LABEL_H } },
      { tx: cx, ty: cy + g + 10, anchor: "middle", box: { x: cx - w / 2, y: cy + g, w, h: LABEL_H } },
      { tx: cx + g, ty: cy - 8, anchor: "start", box: { x: cx + g, y: cy - LABEL_H - 4, w, h: LABEL_H } },
      { tx: cx + g, ty: cy + 16, anchor: "start", box: { x: cx + g, y: cy + 5, w, h: LABEL_H } },
      { tx: cx - g, ty: cy - 8, anchor: "end", box: { x: cx - g - w, y: cy - LABEL_H - 4, w, h: LABEL_H } },
      { tx: cx - g, ty: cy + 16, anchor: "end", box: { x: cx - g - w, y: cy + 5, w, h: LABEL_H } },
    ];
    const inside = (b: Box) => b.x >= M.left - 2 && b.x + b.w <= W - 2 && b.y >= 0 && b.y + b.h <= M.top + PH + 2;
    const free = (b: Box) => !taken.some((t) => hit(t, b)) && !dots.some((d) => d.id !== p.id && hit(d, b));
    const pick = cands.find((c) => inside(c.box) && free(c.box)) ?? cands.find((c) => inside(c.box)) ?? cands[0];
    taken.push(pick.box);
    out.set(p.id, { tx: pick.tx, ty: pick.ty, anchor: pick.anchor });
  }
  return out;
}

/** Biểu đồ phân tán hai tỉ lệ 0–100%. Co giãn theo bề rộng khung chứa qua viewBox. */
export function ScatterPlot({
  points,
  xTitle,
  yTitle,
  ariaLabel,
  onPointClick,
  className,
}: {
  points: ScatterPoint[];
  xTitle: string;
  yTitle: string;
  ariaLabel: string;
  onPointClick?: (p: ScatterPoint) => void;
  className?: string;
}) {
  const labels = placeLabels(points);
  const has = (v: number | null | undefined): v is number => v !== null && v !== undefined;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={ariaLabel}
      className={className}
      style={{ display: "block", minWidth: 440, maxWidth: 760, fontFamily: "var(--font-sans)" }}
    >
      {TICKS.map((t) => (
        <g key={t}>
          <line x1={sx(t)} x2={sx(t)} y1={M.top} y2={M.top + PH} stroke={tok("n-200")} strokeWidth={1} />
          <line x1={M.left} x2={M.left + PW} y1={sy(t)} y2={sy(t)} stroke={tok("n-200")} strokeWidth={1} />
          <text x={sx(t)} y={M.top + PH + 15} textAnchor="middle" fontSize={11} fill={tok("n-500")} style={{ fontVariantNumeric: "tabular-nums" }}>
            {t * 100}%
          </text>
          <text x={M.left - 7} y={sy(t) + 4} textAnchor="end" fontSize={11} fill={tok("n-500")} style={{ fontVariantNumeric: "tabular-nums" }}>
            {t * 100}%
          </text>
        </g>
      ))}
      <text x={M.left + PW / 2} y={H - 8} textAnchor="middle" fontSize={11} fill={tok("n-600")}>
        {xTitle}
      </text>
      <text transform={`translate(13 ${M.top + PH / 2}) rotate(-90)`} textAnchor="middle" fontSize={11} fill={tok("n-600")}>
        {yTitle}
      </text>

      {points.map((p) =>
        (has(p.xLo) && has(p.xHi)) || (has(p.yLo) && has(p.yHi)) ? (
          <g key={`ci-${p.id}`} stroke={tok(p.color, 0.4)} strokeWidth={1} aria-hidden="true">
            {has(p.xLo) && has(p.xHi) && <line x1={sx(p.xLo)} x2={sx(p.xHi)} y1={sy(p.y)} y2={sy(p.y)} />}
            {has(p.yLo) && has(p.yHi) && <line x1={sx(p.x)} x2={sx(p.x)} y1={sy(p.yLo)} y2={sy(p.yHi)} />}
          </g>
        ) : null,
      )}

      {points.map((p) => {
        const l = labels.get(p.id)!;
        const interactive = !!onPointClick;
        return (
          <g
            key={p.id}
            onClick={interactive ? () => onPointClick(p) : undefined}
            onKeyDown={
              interactive
                ? (e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onPointClick(p);
                    }
                  }
                : undefined
            }
            tabIndex={interactive ? 0 : undefined}
            role={interactive ? "button" : undefined}
            style={interactive ? { cursor: "pointer" } : undefined}
          >
            <title>{p.title}</title>
            <circle cx={sx(p.x)} cy={sy(p.y)} r={R} fill={tok(p.color)} stroke={tok("surface")} strokeWidth={1.5} />
            <text
              x={l.tx}
              y={l.ty}
              textAnchor={l.anchor}
              fontSize={11}
              fontWeight={500}
              fill={tok("n-700")}
              stroke={tok("surface")}
              strokeWidth={3}
              strokeLinejoin="round"
              style={{ paintOrder: "stroke" }}
            >
              {p.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
