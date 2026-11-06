import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowUp, Ban, Check, ChevronDown, ChartScatter, Gauge, Info, Layers, Scale, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { Fragment, useState } from "react";
import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import { OutcomeBar, OutcomeLegend, Rate, ScopeNote, useRunsLink } from "@/components/Analysis";
import { Badge, Callout, Card, CardHeader, Empty, ErrorBox, Loading, PageHeader, RateBar } from "@/components/ui";
import { api, type DefensePoint, type DefenseSummary, type Preset } from "@/lib/api";
import { DEFENSE_LABEL, ci, pct, presetLabel } from "@/lib/format";
import { DEFENSE_ICON } from "@/lib/icons";
import { useScope } from "@/lib/scope";

const PRESET_COLOR: Record<string, string> = {
  off: "#64748b",
  d1_only: "#0ea5e9",
  d2_only: "#8b5cf6",
  d3_only: "#f59e0b",
  d4_only: "#ec4899",
  d3_no_confirm: "#14b8a6",
  all: "#16a34a",
};

const DEFENSE_DESC: Record<string, string> = {
  D1: "Bọc ranh giới dữ liệu / chỉ thị để model phân biệt nội dung ngoài.",
  D2: "Làm sạch cú pháp tất định: bỏ mệnh lệnh, ký tự ẩn, định dạng che giấu.",
  D3: "Máy trạng thái ngoài LLM: chỉ cho gọi tool đúng loại tác vụ, xin xác nhận hành động ghi.",
  D4: "Soát dữ liệu đi ra: canary, đích lạ, PII, URL mã hóa.",
};

function ParetoChart({ points }: { points: DefensePoint[] }) {
  const usable = points.filter((p) => p.asr_e2e !== null && p.usr !== null);
  if (!usable.length) {
    return (
      <Empty title="Chưa đủ dữ liệu để vẽ đường đánh đổi" icon={<ShieldCheck size={20} />}>
        Mỗi điểm cần cả ASR (run tấn công) và USR (run lành tính) của cùng cấu hình phòng thủ và model. Dữ liệu
        có sau khối B2 và B3.
      </Empty>
    );
  }
  const groups = [...new Set(usable.map((p) => p.preset))];
  return (
    <div className="h-[380px] px-2 pb-2 pt-4">
      <ResponsiveContainer>
        <ScatterChart margin={{ left: 0, right: 24, top: 8, bottom: 16 }}>
          <CartesianGrid stroke="#eef0f4" />
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            name="ASR"
            label={{ value: "Tấn công thành công (ASR) — thấp hơn là an toàn hơn", position: "insideBottom", offset: -8, fontSize: 12, fill: "#64748b" }}
            tick={{ fontSize: 12, fill: "#94a3b8" }}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            name="USR"
            label={{ value: "Câu lành tính đạt (USR) — cao hơn là hữu dụng hơn", angle: -90, position: "insideLeft", fontSize: 12, fill: "#64748b" }}
            tick={{ fontSize: 12, fill: "#94a3b8" }}
          />
          <ZAxis range={[120, 120]} />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={({ payload }) => {
              const p = payload?.[0]?.payload as (DefensePoint & { x: number; y: number }) | undefined;
              if (!p) return null;
              return (
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-[12.5px] shadow-pop">
                  <div className="font-semibold text-slate-900">
                    {presetLabel(p.preset)} · {p.target_id}
                  </div>
                  <div className="mt-1 text-slate-600">
                    ASR {pct(p.asr_e2e)} ({ci(p.asr_lo, p.asr_hi)}) · n={p.n_attack}
                  </div>
                  <div className="text-slate-600">
                    USR {pct(p.usr)} ({ci(p.usr_lo, p.usr_hi)}) · n={p.n_benign}
                  </div>
                </div>
              );
            }}
          />
          <Legend verticalAlign="top" height={30} iconType="circle" wrapperStyle={{ fontSize: 12.5 }} />
          {groups.map((g) => (
            <Scatter
              key={g}
              name={presetLabel(g)}
              fill={PRESET_COLOR[g] ?? "#334155"}
              data={usable
                .filter((p) => p.preset === g)
                .map((p) => ({ ...p, x: +(p.asr_e2e! * 100).toFixed(1), y: +(p.usr! * 100).toFixed(1) }))}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function Delta({ v, better }: { v: number | null; better: "down" | "up" }) {
  if (v === null || v === undefined) return null;
  const good = better === "down" ? v < 0 : v > 0;
  const Icon = v < 0 ? ArrowDown : ArrowUp;
  if (Math.abs(v) < 0.0005) return <span className="ml-1.5 text-[11.5px] text-slate-400">±0</span>;
  return (
    <span className={clsx("num ml-1.5 inline-flex items-center text-[11.5px] font-medium", good ? "text-defense-600" : "text-attack-600")}>
      <Icon size={11} />
      {pct(Math.abs(v))}
    </span>
  );
}

function Baseline({ d }: { d: DefenseSummary }) {
  const link = useRunsLink();
  return (
    <Card>
      <CardHeader title="Mốc so sánh · tắt phòng thủ" icon={<Gauge size={16} />} />
      <p className="px-5 pb-3 text-[12.5px] leading-relaxed text-slate-500">
        Mọi cấu hình phòng thủ được so với mốc này của CÙNG model. Phần “Model từ chối” là lớp an toàn sẵn có của
        model — phòng thủ D1–D4 không được tính công cho phần đó.
      </p>
      <div className="max-w-full overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Model</th>
              <th className="w-56">Tấn công thành công (ASR)</th>
              <th className="w-56">Câu lành tính đạt (USR)</th>
              <th className="w-40">Chặn nhầm (FRR)</th>
              <th className="w-48">Kết cục run tấn công</th>
            </tr>
          </thead>
          <tbody>
            {d.baseline.map((b) => (
              <tr key={b.target_id} className="hover:bg-slate-50/70">
                <td>
                  <Link to={link({ target: b.target_id })} className="font-mono font-semibold text-slate-800 hover:underline">{b.target_id}</Link>
                </td>
                <td>
                  <Rate r={b.asr} />
                  <RateBar p={b.asr.p} lo={b.asr.lo} hi={b.asr.hi} />
                </td>
                <td>
                  {b.usr.n ? (
                    <>
                      <Rate r={b.usr} good />
                      <RateBar p={b.usr.p} lo={b.usr.lo} hi={b.usr.hi} tone="brand" />
                    </>
                  ) : <span className="text-[12.5px] text-slate-400">chưa đo</span>}
                </td>
                <td>{b.frr.n ? <Rate r={b.frr} good /> : <span className="text-[12.5px] text-slate-400">—</span>}</td>
                <td>{b.outcomes && <OutcomeBar o={b.outcomes} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-100 px-5 py-3"><OutcomeLegend /></div>
    </Card>
  );
}

function Effects({ d }: { d: DefenseSummary }) {
  const targets = [...new Set(d.effects.map((e) => e.target_id))];
  return (
    <Card>
      <CardHeader title="RQ4 · Mỗi cấu hình giảm bao nhiêu tấn công, mất bao nhiêu hữu dụng?" icon={<Scale size={16} />} />
      <p className="px-5 pb-3 text-[12.5px] leading-relaxed text-slate-500">
        Mũi tên so với lúc tắt phòng thủ của cùng model: ASR giảm (xanh) là tốt, USR giảm (đỏ) là cái giá phải trả.
        “Cắt được” = phần tấn công thành công bị loại bỏ.
      </p>
      <div className="max-w-full overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Model</th>
              <th>Cấu hình</th>
              <th className="w-56">Tấn công thành công (ASR)</th>
              <th className="text-right">Cắt được</th>
              <th className="w-56">Câu lành tính đạt (USR)</th>
              <th className="text-right">Chặn nhầm</th>
              <th className="w-44">Kết cục</th>
            </tr>
          </thead>
          <tbody>
            {targets.flatMap((t) =>
              d.effects
                .filter((e) => e.target_id === t)
                .sort((a, b) => (a.asr.p ?? 1) - (b.asr.p ?? 1))
                .map((e, i) => (
                  <tr key={`${t}-${e.preset}`} className="hover:bg-slate-50/70">
                    <td className="font-mono font-semibold text-slate-800">{i === 0 ? t : ""}</td>
                    <td>
                      <span className="inline-flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ background: PRESET_COLOR[e.preset] ?? "#334155" }} />
                        {presetLabel(e.preset)}
                      </span>
                    </td>
                    <td>
                      <Rate r={e.asr} />
                      <Delta v={e.d_asr} better="down" />
                    </td>
                    <td className="num text-right">{e.asr_cut === null ? "—" : pct(e.asr_cut, 0)}</td>
                    <td>
                      {e.usr.n ? (<><Rate r={e.usr} good /><Delta v={e.d_usr} better="up" /></>) : <span className="text-[12.5px] text-slate-400">chưa đo</span>}
                    </td>
                    <td className="num text-right">{e.frr.n ? pct(e.frr.p) : "—"}</td>
                    <td>{e.outcomes && <OutcomeBar o={e.outcomes} />}</td>
                  </tr>
                )),
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Rq3({ d }: { d: DefenseSummary }) {
  if (!d.rq3.length) return null;
  return (
    <Card>
      <CardHeader title="RQ3 · Bật cả D1–D4 có hơn cơ chế đơn lẻ tốt nhất không?" icon={<Layers size={16} />} />
      <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
        {d.rq3.map((r) => (
          <div key={r.target_id} className="rounded-lg border border-slate-200 p-4">
            <div className="font-mono text-[13px] font-semibold text-slate-800">{r.target_id}</div>
            <div className="mt-2 text-[12.5px] text-slate-600">
              Bật D1–D4: <Rate r={r.all.asr} />
            </div>
            <div className="text-[12.5px] text-slate-600">
              Tốt nhất đơn lẻ ({presetLabel(r.best_single)}): <Rate r={r.single.asr} />
            </div>
            <div className={clsx("mt-2 text-[13px] font-medium", r.gain > 0 ? "text-defense-700" : "text-slate-600")}>
              {r.gain > 0 ? `Tổ hợp giảm thêm ${pct(r.gain)} ASR` : "Tổ hợp không giảm thêm ASR"}
              {r.usr_cost !== null && `, USR ${r.usr_cost >= 0 ? "+" : "−"}${pct(Math.abs(r.usr_cost))}`}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function FrrByTask({ d }: { d: DefenseSummary }) {
  if (!d.frr_by_task.length) return null;
  const presetsOn = [...new Set(d.frr_by_task.map((r) => r.preset))];
  const tasks = [...new Set(d.frr_by_task.map((r) => r.carrier_task_id ?? "?"))].sort();
  return (
    <Card>
      <CardHeader title="Chặn nhầm theo tác vụ" icon={<Ban size={16} />} />
      <p className="px-5 pb-3 text-[12.5px] text-slate-500">Tỉ lệ câu lành tính bị phòng thủ chặn, theo tác vụ chở (giả thuyết H4: D3 chặn nhầm ở CT-05, CT-06).</p>
      <div className="max-w-full overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Tác vụ</th>
              {presetsOn.map((p) => <th key={p} className="text-center">{presetLabel(p)}</th>)}
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t}>
                <td className="font-mono font-medium">{t}</td>
                {presetsOn.map((p) => {
                  const v = d.frr_by_task.find((r) => r.preset === p && (r.carrier_task_id ?? "?") === t);
                  return (
                    <td key={p} className="text-center">
                      {v ? (
                        <span title={`${v.frr.x}/${v.frr.n}`} className={clsx("num rounded px-1.5 py-0.5 text-[12.5px]", (v.frr.p ?? 0) > 0 ? "bg-attack-50 font-semibold text-attack-700" : "text-slate-400")}>
                          {pct(v.frr.p, 0)}
                        </span>
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function NotMeasured({ d }: { d: DefenseSummary }) {
  const pending = d.presets.filter((p) => !d.measured.includes(p.name));
  return (
    <Callout tone="brand" icon={<Info size={16} />} title="Chưa có lô đo phòng thủ (khối B2) trong phạm vi này">
      <div className="text-[12.5px] leading-relaxed">
        Hiện chỉ có run tắt phòng thủ — dùng làm mốc so sánh bên dưới. Khi chạy khối B2, trang này sẽ hiện: mỗi cấu hình
        giảm bao nhiêu tấn công và mất bao nhiêu hữu dụng (RQ4), tổ hợp D1–D4 so với cơ chế đơn lẻ tốt nhất (RQ3),
        và chặn nhầm theo tác vụ.
        {pending.length > 0 && (
          <div className="mt-1">Cấu hình chờ đo: {pending.map((p) => presetLabel(p.name)).join(" · ")}.</div>
        )}
      </div>
    </Callout>
  );
}

function Mechanisms({ presets }: { presets: Preset[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card>
      <details className="detail-disclosure">
        <summary>Cơ chế D1–D4 và tham số của từng cấu hình</summary>
        <div className="defense-grid">
          {(["D1", "D2", "D3", "D4"] as const).map((code) => {
            const Icon = DEFENSE_ICON[code];
            return (
              <div key={code} className="defense-tile">
                <span className="block-icon" aria-hidden="true"><Icon size={22} /></span>
                <Badge tone="defense">{code}</Badge>
                <h3>{DEFENSE_LABEL[code]}</h3>
                <p className="text-[12.5px] text-slate-500">{DEFENSE_DESC[code]}</p>
              </div>
            );
          })}
        </div>
        <div className="max-w-full overflow-x-auto px-1 pb-3">
          <table className="table-base">
            <thead>
              <tr>
                <th>Cấu hình</th>
                {["D1", "D2", "D3", "D4"].map((c) => <th key={c} className="text-center">{c}</th>)}
                <th />
              </tr>
            </thead>
            <tbody>
              {presets.map((p) => (
                <Fragment key={p.name}>
                  <tr>
                    <td>
                      <span className="inline-flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ background: PRESET_COLOR[p.name] ?? "#334155" }} />
                        <span className="font-medium text-slate-800">{presetLabel(p.name)}</span>
                        <span className="font-mono text-[11.5px] text-slate-400">{p.name}</span>
                      </span>
                    </td>
                    {["D1", "D2", "D3", "D4"].map((c) => (
                      <td key={c} className="text-center">
                        {p.codes.includes(c) ? <Check size={16} className="mx-auto text-defense-600" /> : <span className="text-slate-300">·</span>}
                      </td>
                    ))}
                    <td className="w-10">
                      {p.codes.length > 0 && (
                        <button
                          onClick={() => setOpen(open === p.name ? null : p.name)}
                          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100"
                          title="Tham số hiệu lực"
                        >
                          <ChevronDown size={16} className={clsx("transition", open === p.name && "rotate-180")} />
                        </button>
                      )}
                    </td>
                  </tr>
                  {open === p.name && (
                    <tr>
                      <td colSpan={6} className="bg-slate-50/60">
                        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                          {Object.entries(p.params).map(([code, params]) => (
                            <div key={code}>
                              <div className="mb-1 flex items-center gap-2">
                                <Badge tone="defense">{code}</Badge>
                                <span className="text-[12.5px] font-medium text-slate-700">{DEFENSE_LABEL[code]}</span>
                              </div>
                              <pre className="code-block max-h-64 overflow-auto">{JSON.stringify(params, null, 2)}</pre>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}

export function DefensePage() {
  const { params } = useScope();
  const q = useQuery({ queryKey: ["defense-summary", params], queryFn: () => api.defenseSummary(params) });
  const points = useQuery({
    queryKey: ["defense", params],
    queryFn: () => api.defensePoints({ ...params }),
    enabled: !!q.data?.has_defense_runs,
  });
  const d = q.data;
  return (
    <>
      <PageHeader
        title="Phòng thủ"
        info="Trả lời RQ3 (tổ hợp D1–D4 có hơn cơ chế đơn lẻ) và RQ4 (cái giá về hữu dụng). Mọi so sánh đều với lúc tắt phòng thủ của cùng model."
      />
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {d && (
        <div className="space-y-6">
          <ScopeNote s={d.scope} />
          {!d.has_defense_runs && <NotMeasured d={d} />}
          {d.baseline.length > 0 && <Baseline d={d} />}
          {d.has_defense_runs && (
            <>
              <Effects d={d} />
              <Rq3 d={d} />
              <Card>
                <CardHeader title="Bản đồ đánh đổi an toàn – hữu dụng" icon={<ChartScatter size={16} />} />
                <p className="px-5 text-[12.5px] text-slate-500">Mỗi điểm là một cấu hình trên một model. Điểm tốt nằm góc trên bên trái: ít tấn công thành công, nhiều câu lành tính đạt.</p>
                {points.data && <ParetoChart points={points.data.points} />}
              </Card>
              <FrrByTask d={d} />
            </>
          )}
          <Mechanisms presets={d.presets} />
        </div>
      )}
    </>
  );
}
