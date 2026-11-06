import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, Crosshair, Cpu, Grid3x3, Info, Radar, Table2, Trophy, Waypoints } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Callout, Card, CardHeader, Empty, ErrorBox, Loading, PageHeader, RateBar, Segmented, Select } from "@/components/ui";
import { api, type AsrRow, type AttackSummary, type CiRate, type Outcomes, type ScopeProfile } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, ROLE_LABEL, TECHNIQUE_LABEL, ci, int, pct, presetLabel } from "@/lib/format";
import { useScope } from "@/lib/scope";

type View = "channel,technique" | "target_id,technique" | "channel,goal" | "target_id,preset" | "goal";

const VIEWS: { value: View; label: string }[] = [
  { value: "channel,technique", label: "Kênh × kỹ thuật" },
  { value: "target_id,technique", label: "Model × kỹ thuật" },
  { value: "channel,goal", label: "Kênh × mục tiêu" },
  { value: "target_id,preset", label: "Model × cấu hình phòng thủ" },
  { value: "goal", label: "Theo mục tiêu" },
];

const DIM_LABEL: Record<string, string> = {
  channel: "Kênh",
  technique: "Kỹ thuật",
  goal: "Mục tiêu",
  target_id: "Model",
  preset: "Phòng thủ",
};

function describe(dim: string, v: string): string {
  if (dim === "channel") return CHANNEL_LABEL[v] ?? v;
  if (dim === "technique") return TECHNIQUE_LABEL[v] ?? v;
  if (dim === "goal") return GOAL_LABEL[v] ?? v;
  if (dim === "preset") return presetLabel(v);
  return v;
}

/** Màu ô heatmap theo ASR: trắng → đỏ. */
function heat(p: number | null) {
  if (p === null) return { background: "#f8fafc", color: "#94a3b8" };
  const a = 0.08 + p * 0.82;
  return { background: `rgba(229,72,77,${a})`, color: p > 0.45 ? "#fff" : "#7f1d1d" };
}

function Heatmap({ rows, dims }: { rows: AsrRow[]; dims: [string, string] }) {
  const [r, c] = dims;
  const rowKeys = [...new Set(rows.map((x) => String(x[r])))].sort();
  const colKeys = [...new Set(rows.map((x) => String(x[c])))].sort();
  const at = (rk: string, ck: string) => rows.find((x) => String(x[r]) === rk && String(x[c]) === ck);
  return (
    <div className="overflow-x-auto px-5 py-5">
      <div className="max-w-full overflow-x-auto"><table className="border-separate border-spacing-1.5">
        <thead>
          <tr>
            <th />
            {colKeys.map((ck) => (
              <th key={ck} className="px-1 pb-1 text-center align-bottom">
                <div className="text-[12.5px] font-semibold text-slate-700">{ck}</div>
                <div className="max-w-[110px] text-[11px] font-normal leading-tight text-slate-400">
                  {describe(c, ck) !== ck ? describe(c, ck) : ""}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowKeys.map((rk) => (
            <tr key={rk}>
              <th className="pr-3 text-left align-middle">
                <div className="text-[12.5px] font-semibold text-slate-700">{rk}</div>
                <div className="text-[11px] font-normal text-slate-400">{describe(r, rk) !== rk ? describe(r, rk) : ""}</div>
              </th>
              {colKeys.map((ck) => {
                const cell = at(rk, ck);
                const p = cell?.asr_e2e ?? null;
                return (
                  <td
                    key={ck}
                    className="h-16 w-[104px] rounded-lg text-center align-middle transition hover:ring-2 hover:ring-slate-300"
                    style={cell ? heat(p) : { background: "transparent" }}
                    title={cell ? `${rk} × ${ck}: ${cell.s}/${cell.n} · CI ${ci(cell.asr_e2e_lo, cell.asr_e2e_hi)}` : "không có ô"}
                  >
                    {cell ? (
                      <>
                        <div className="num text-[15px] font-semibold">{pct(p, 0)}</div>
                        <div className="num text-[11px] opacity-80">
                          {cell.s}/{cell.n}
                        </div>
                      </>
                    ) : (
                      <span className="text-[11px] text-slate-300">—</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table></div>
      <div className="mt-4 flex items-center gap-3 text-[12px] text-slate-500">
        <span>ASR</span>
        <div className="h-2 w-40 rounded-full" style={{ background: "linear-gradient(90deg, rgba(229,72,77,.08), rgba(229,72,77,.9))" }} />
        <span>0% → 100%</span>
      </div>
    </div>
  );
}

function Explorer() {
  const { params } = useScope();
  const [view, setView] = useState<View>("channel,technique");
  const dims = view.split(",");
  const q = useQuery({ queryKey: ["asr", params, view], queryFn: () => api.asr({ ...params, by: view }) });

  return (
    <Card>
      <details className="detail-disclosure">
        <summary>Khám phá thêm — bản đồ ASR và bảng đầy đủ theo chiều tùy chọn</summary>
        <div className="flex justify-end px-5 pt-3">
          <Select value={view} onChange={setView} options={VIEWS} className="w-64" />
        </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && q.data.rows.length === 0 && (
        <Card>
          <Empty title="Chưa có run tấn công trong phạm vi này" icon={<Crosshair size={20} />}>
            Đổi <b>Phạm vi</b> ở thanh trên sang “Lượt demo” hoặc “Lô chạy thử” để xem các run đã có.
          </Empty>
        </Card>
      )}
      {q.data && q.data.rows.length > 0 && (
        <div className="space-y-6 p-4">
          {dims.length === 2 && (
            <Card>
              <CardHeader
                title={`Bản đồ ASR · ${DIM_LABEL[dims[0]]} × ${DIM_LABEL[dims[1]]}`}
                icon={<Grid3x3 size={16} />}
              />
              <Heatmap rows={q.data.rows} dims={[dims[0], dims[1]]} />
            </Card>
          )}
          <Card>
            <CardHeader title="Bảng chi tiết" icon={<Table2 size={16} />} />
            <div className="max-w-full overflow-x-auto"><table className="table-base">
              <thead>
                <tr>
                  {dims.map((d) => (
                    <th key={d}>{DIM_LABEL[d]}</th>
                  ))}
                  <th className="text-right">n</th>
                  <th className="w-64">ASR_e2e · CI 95%</th>
                  <th className="text-right">DSR</th>
                  <th className="text-right">Phòng thủ chặn</th>
                  <th className="text-right">Model từ chối</th>
                  <th className="text-right">Harness</th>
                </tr>
              </thead>
              <tbody>
                {[...q.data.rows]
                  .sort((a, b) => (b.asr_e2e ?? -1) - (a.asr_e2e ?? -1))
                  .map((r, i) => (
                    <tr key={i} className="hover:bg-slate-50/70">
                      {dims.map((d) => (
                        <td key={d}>
                          <div className="font-medium text-slate-800">{String(r[d])}</div>
                          {describe(d, String(r[d])) !== String(r[d]) && (
                            <div className="text-[12px] text-slate-500">{describe(d, String(r[d]))}</div>
                          )}
                        </td>
                      ))}
                      <td className="num text-right">{int(r.n)}</td>
                      <td>
                        <div className="mb-1 flex justify-between text-[12.5px]">
                          <span className={clsx("num font-semibold", (r.asr_e2e ?? 0) > 0 ? "text-attack-600" : "text-slate-700")}>
                            {pct(r.asr_e2e)}
                          </span>
                          <span className="num text-slate-400">{ci(r.asr_e2e_lo, r.asr_e2e_hi)}</span>
                        </div>
                        <RateBar p={r.asr_e2e} lo={r.asr_e2e_lo} hi={r.asr_e2e_hi} />
                      </td>
                      <td className="num text-right">{r.dsr === null ? "—" : <Badge tone="defense">{pct(r.dsr)}</Badge>}</td>
                      <td className="num text-right">{int(r.blocked_defense)}</td>
                      <td className="num text-right">{int(r.blocked_model_refusal)}</td>
                      <td className="num text-right">{int(r.blocked_harness)}</td>
                    </tr>
                  ))}
              </tbody>
            </table></div>
          </Card>
        </div>
      )}
      </details>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Trang theo câu hỏi nghiên cứu
// ---------------------------------------------------------------------------

const K_LABEL: Record<string, string> = { ...CHANNEL_LABEL, K2: "Kênh công cụ MCP (K2a + K2b)" };

/** Đường dẫn sang Lượt chạy, giữ phạm vi đang xem và lọc sẵn theo ô vừa bấm. */
function useRunsLink() {
  const { search } = useScope();
  return (filters: Record<string, string | string[] | undefined>) => {
    const sp = new URLSearchParams(search);
    sp.delete("page");
    sp.set("run_kind", "attack");
    for (const [k, v] of Object.entries(filters)) {
      if (v === undefined) continue;
      (Array.isArray(v) ? v : [v]).forEach((x) => sp.append(k, x));
    }
    return `/runs?${sp}`;
  };
}

const OUTCOME_SEG: { key: keyof Outcomes; label: string; cls: string }[] = [
  { key: "success", label: "Tấn công thành công", cls: "bg-attack-500" },
  { key: "defense", label: "Phòng thủ chặn", cls: "bg-defense-500" },
  { key: "model_refusal", label: "Model từ chối", cls: "bg-amber-400" },
  { key: "harness", label: "Harness chặn", cls: "bg-slate-500" },
  { key: "failed", label: "Không đạt (không ai chặn)", cls: "bg-slate-200" },
  { key: "excluded", label: "Lỗi hạ tầng (loại khỏi mẫu số)", cls: "bg-[repeating-linear-gradient(45deg,#e2e8f0_0_3px,#fff_3px_6px)]" },
];

function OutcomeBar({ o, className }: { o: Outcomes; className?: string }) {
  const total = OUTCOME_SEG.reduce((acc, s) => acc + (o[s.key] ?? 0), 0);
  if (!total) return null;
  const title = OUTCOME_SEG.filter((s) => o[s.key]).map((s) => `${s.label}: ${o[s.key]}`).join(" · ");
  return (
    <div className={clsx("flex h-2 w-full overflow-hidden rounded-full bg-slate-100", className)} title={title}>
      {OUTCOME_SEG.map((s) =>
        o[s.key] ? <div key={s.key} className={s.cls} style={{ width: `${(o[s.key] / total) * 100}%` }} /> : null,
      )}
    </div>
  );
}

function OutcomeLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-slate-500">
      {OUTCOME_SEG.map((s) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className={clsx("h-2.5 w-2.5 rounded-sm", s.cls)} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

function Rate({ r, strong = false }: { r: CiRate; strong?: boolean }) {
  return (
    <span className="whitespace-nowrap">
      <span className={clsx("num", strong ? "text-[15px] font-semibold" : "font-medium", (r.p ?? 0) > 0 ? "text-attack-600" : "text-slate-700")}>
        {pct(r.p)}
      </span>
      <span className="num ml-1.5 text-[11.5px] text-slate-400">
        {r.x}/{r.n}
        {r.n > 0 && ` · ${ci(r.lo, r.hi)}`}
      </span>
    </span>
  );
}

function ScopeNote({ s }: { s: ScopeProfile }) {
  const roles = Object.entries(s.roles).map(([k, n]) => `${ROLE_LABEL[k] ?? k} ${int(n)}`).join(" · ");
  const nHarness = Object.keys(s.harness_versions).length;
  const variants = Object.keys(s.prompt_variants).filter((v) => v !== "∅");
  const mixed = s.mixed.length > 0;
  return (
    <Callout
      tone={mixed ? "warn" : "brand"}
      icon={mixed ? <AlertTriangle size={16} /> : <Info size={16} />}
      title={mixed ? "Số liệu đang gộp nhiều điều kiện khác nhau — đọc như xu hướng, chưa phải kết quả chính thức" : "Phạm vi số liệu"}
    >
      <div className="space-y-0.5 text-[12.5px]">
        <div>
          {int(s.n_batches)} lô · run tấn công theo vai trò lô: {roles || "—"}
        </div>
        <div>
          {nHarness} phiên bản harness (commit)
          {variants.length > 0 && <> · biến thể prompt dò được: {variants.join(", ")}</>}
          {" · "}model: {Object.entries(s.targets).map(([k, n]) => `${k} ${int(n)}`).join(", ")}
          {" · "}phòng thủ: {Object.keys(s.presets).map(presetLabel).join(", ")}
        </div>
        {mixed && (
          <div className="pt-1 text-[12px] opacity-90">
            Tập so sánh được = cùng khối thí nghiệm, cùng phiên bản harness và biến thể prompt. Chọn một lô ở thanh phạm vi để xem
            một điều kiện duy nhất.
          </div>
        )}
      </div>
    </Callout>
  );
}

function Headlines({ d }: { d: AttackSummary }) {
  const link = useRunsLink();
  if (!d.headline.length) return null;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      {d.headline.map((h) => {
        if (h.kind === "top_cell")
          return (
            <Card key={h.kind}>
              <Link to={link({ channel: h.channel, technique: h.technique })} className="block p-5 hover:bg-slate-50/60">
                <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wide text-slate-500">
                  <Trophy size={14} className="text-attack-500" /> Lỗ hổng lớn nhất
                </div>
                <div className="mt-2 text-[15px] font-semibold text-slate-900">
                  {h.technique} {TECHNIQUE_LABEL[h.technique]} qua {K_LABEL[h.channel] ?? h.channel}
                </div>
                <div className="mt-1"><Rate r={h.asr} strong /></div>
                <div className="mt-2 text-[12px] text-slate-500">Xếp theo cận dưới khoảng tin cậy, chỉ ô từ 20 run. Bấm để xem các run →</div>
              </Link>
            </Card>
          );
        if (h.kind === "k1_vs_k2")
          return (
            <Card key={h.kind}>
              <div className="p-5">
                <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wide text-slate-500">
                  <Waypoints size={14} className="text-payload-500" /> RAG (K1) so với công cụ MCP (K2)
                </div>
                <div className="mt-2 text-[15px] font-semibold text-slate-900">
                  K2 {pct(h.k2.p)} · K1 {pct(h.k1.p)}
                </div>
                <div className="mt-2 text-[12.5px] leading-relaxed text-slate-600">
                  Payload K1 tới được agent ở {pct(h.k1_delivery.p, 0)} run; trong số đó tấn công thành công {pct(h.k1_cond.p)}.
                  {h.k1.p === 0 && h.k1_delivery.p && h.k1_delivery.p > 0.5
                    ? " K1 thấp không phải vì payload không được truy hồi — agent đọc được nhưng không làm theo."
                    : ""}
                </div>
              </div>
            </Card>
          );
        return (
          <Card key={h.kind}>
            <Link to={link({ target: h.target_id })} className="block p-5 hover:bg-slate-50/60">
              <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wide text-slate-500">
                <Cpu size={14} className="text-brand-600" /> Model dễ bị nhất
              </div>
              <div className="mt-2 text-[15px] font-semibold text-slate-900">{h.target_id}</div>
              <div className="mt-1"><Rate r={h.asr} strong /></div>
              <div className="mt-2 text-[12px] text-slate-500">Gộp mọi kênh và kỹ thuật trong phạm vi. Bấm để xem các run →</div>
            </Link>
          </Card>
        );
      })}
    </div>
  );
}

function RQ1({ d }: { d: AttackSummary }) {
  const link = useRunsLink();
  return (
    <Card>
      <CardHeader
        title="RQ1 · Kênh nào nguy hiểm hơn: kho tri thức RAG hay công cụ MCP?"
        icon={<Waypoints size={16} />}
      />
      <p className="px-5 pb-3 text-[12.5px] leading-relaxed text-slate-500">K1 phải được truy hồi mới tới agent; K2 luôn vào ngữ cảnh. Vì vậy đọc K1 kèm tỉ lệ tới được agent và tỉ lệ thành công khi đã tới.</p>
      <div className="max-w-full overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Kênh</th>
              <th className="w-56">Tỉ lệ tấn công thành công</th>
              <th className="w-56">Payload tới được agent</th>
              <th className="w-56">Thành công khi đã tới</th>
              <th className="w-48">Kết cục</th>
            </tr>
          </thead>
          <tbody>
            {d.rq1.map((r) => (
              <tr key={r.channel} className={clsx("hover:bg-slate-50/70", (r.channel === "K2a" || r.channel === "K2b") && "text-[13px]")}>
                <td>
                  <Link to={link({ channel: r.members })} className="hover:underline">
                    <span className={clsx("font-mono font-semibold", r.channel.length > 2 ? "pl-4 text-slate-500" : "text-slate-800")}>{r.channel}</span>
                    <span className="ml-2 text-[12.5px] text-slate-500">{K_LABEL[r.channel]}</span>
                  </Link>
                </td>
                <td>
                  <Rate r={r.asr} />
                  <RateBar p={r.asr.p} lo={r.asr.lo} hi={r.asr.hi} />
                </td>
                <td>
                  {r.channel === "K1" ? (
                    <>
                      <Rate r={r.delivery} />
                      <RateBar p={r.delivery.p} lo={r.delivery.lo} hi={r.delivery.hi} tone="brand" />
                    </>
                  ) : (
                    <span className="text-[12.5px] text-slate-400">luôn tới (100%)</span>
                  )}
                </td>
                <td>{r.channel === "K1" ? <Rate r={r.asr_cond} /> : <span className="text-[12.5px] text-slate-400">= cột đầu</span>}</td>
                <td><OutcomeBar o={r.outcomes} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-100 px-5 py-3"><OutcomeLegend /></div>
    </Card>
  );
}

function RQ2({ d }: { d: AttackSummary }) {
  const link = useRunsLink();
  const channels = [...new Set(d.rq2.map((r) => r.channel))].sort();
  const best = [...d.rq1].filter((r) => channels.includes(r.channel)).sort((a, b) => (b.asr.p ?? 0) - (a.asr.p ?? 0))[0]?.channel;
  const [ch, setCh] = useState<string>(best ?? channels[0] ?? "");
  const current = channels.includes(ch) ? ch : channels[0];
  const rows = d.rq2.filter((r) => r.channel === current).sort((a, b) => (b.asr.p ?? -1) - (a.asr.p ?? -1));
  const targets = d.targets.map((t) => t.target_id);
  return (
    <Card>
      <CardHeader
        title="RQ2 · Kỹ thuật nào mạnh nhất trên từng kênh, và có ổn định khi đổi model?"
        icon={<Radar size={16} />}
        action={
          <Segmented
            value={current}
            onChange={setCh}
            options={channels.map((c) => ({ value: c, label: c }))}
          />
        }
      />
      <p className="px-5 pb-3 text-[12.5px] leading-relaxed text-slate-500">Xếp kỹ thuật theo tỉ lệ thành công; vạch nhạt là khoảng tin cậy 95%. Cột model cho biết kết quả có giữ nguyên khi đổi model không.</p>
      <div className="max-w-full overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Kỹ thuật</th>
              <th className="w-64">Tỉ lệ thành công · CI 95%</th>
              {targets.map((t) => (
                <th key={t} className="text-center">{t}</th>
              ))}
              <th className="w-44">Kết cục</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.technique} className="hover:bg-slate-50/70">
                <td>
                  <Link to={link({ channel: r.channel, technique: r.technique })} className="hover:underline">
                    <span className="font-mono font-semibold text-slate-800">{r.technique}</span>
                    <span className="ml-2 text-[12.5px] text-slate-500">{TECHNIQUE_LABEL[r.technique]}</span>
                  </Link>
                </td>
                <td>
                  <Rate r={r.asr} />
                  <RateBar p={r.asr.p} lo={r.asr.lo} hi={r.asr.hi} />
                </td>
                {targets.map((t) => {
                  const v = r.by_target[t];
                  return (
                    <td key={t} className="text-center">
                      {v ? (
                        <Link
                          to={link({ channel: r.channel, technique: r.technique, target: t })}
                          title={`${t}: ${v.x}/${v.n} · CI ${ci(v.lo, v.hi)}`}
                          className={clsx("num inline-block min-w-12 rounded px-1.5 py-0.5 text-[12.5px]",
                            (v.p ?? 0) > 0 ? "bg-attack-50 font-semibold text-attack-700" : "text-slate-400")}
                        >
                          {pct(v.p, 0)}
                        </Link>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                  );
                })}
                <td><OutcomeBar o={r.outcomes} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Notes() {
  return (
    <Card>
      <details className="detail-disclosure">
        <summary>Lưu ý đo lường</summary>
        <ul className="list-disc space-y-1.5 px-9 pb-4 text-[12.5px] leading-relaxed text-slate-600">
          <li>Tỉ lệ tấn công thành công (ASR) = run đạt mục tiêu / run hợp lệ; run lỗi hạ tầng bị loại khỏi mẫu số.</li>
          <li>Khoảng tin cậy Wilson 95%. Ô ít run cho khoảng rộng — đừng so hai ô khi khoảng của chúng chồng nhau nhiều.</li>
          <li>“Model từ chối” là lớp an toàn của chính model, không phải thành tích của D1–D4 (quy tắc cứng #8).</li>
          <li>G2: scorer chỉ tính vi phạm trên đúng tool payload nhắm; vi phạm khác là agent tự lệch, ghi riêng (VT-16) — mở run để kiểm “tool đã gọi”.</li>
        </ul>
      </details>
    </Card>
  );
}

export function AttackPage() {
  const { params } = useScope();
  const q = useQuery({ queryKey: ["attack-summary", params], queryFn: () => api.attackSummary(params) });
  const d = q.data;
  return (
    <>
      <PageHeader
        title="Tấn công"
        info="Trả lời RQ1 (kênh nào nguy hiểm hơn) và RQ2 (kỹ thuật nào mạnh nhất, có ổn định khi đổi model). Bấm vào số liệu để mở các run tương ứng."
      />
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {d && d.n === 0 && (
        <Card>
          <Empty title="Chưa có run tấn công trong phạm vi này" icon={<Crosshair size={20} />}>
            Đổi <b>Phạm vi</b> ở thanh trên sang “Lượt demo” hoặc “Lô chạy thử” để xem các run đã có.
          </Empty>
        </Card>
      )}
      {d && d.n > 0 && (
        <div className="space-y-6">
          <ScopeNote s={d.scope} />
          <Headlines d={d} />
          <RQ1 d={d} />
          <RQ2 d={d} />
          <Explorer />
          <Notes />
        </div>
      )}
    </>
  );
}
