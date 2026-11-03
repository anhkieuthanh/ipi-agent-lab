import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Crosshair, CircleCheck, Layers, ChartColumn } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, LabelList, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge, Callout, Card, CardHeader, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api, type Rate } from "@/lib/api";
import { KIND_LABEL, ci, int, pct, when } from "@/lib/format";
import { SCOPE_LABEL, useScope } from "@/lib/scope";

function Sample({ rate, noun }: { rate: Rate; noun: string }) {
  if (!rate) return <>Chưa có {noun}</>;
  return <>{int(rate.x)}/{int(rate.n)} {noun} <span className="whitespace-nowrap">· CI 95% {ci(rate.lo, rate.hi)}</span></>;
}

export function OverviewPage() {
  const { params, kind, batch } = useScope();
  const [showTable, setShowTable] = useState(false);
  const q = useQuery({ queryKey: ["overview", params], refetchInterval: 15_000, queryFn: () => api.overview(params) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const k = d.kpis;
  const chart = d.by_target.map((t) => ({
    target: t.target_id,
    "ASR · tắt phòng thủ": t.asr_off ? +(t.asr_off.p * 100).toFixed(1) : null,
    "ASR · bật phòng thủ": t.asr_on ? +(t.asr_on.p * 100).toFixed(1) : null,
    "USR · hữu dụng nền": t.usr_off ? +(t.usr_off.p * 100).toFixed(1) : null,
  }));
  const valid = Math.max(0, k.n_runs - k.n_parse_error);
  const series = [
    { key: "ASR · tắt phòng thủ", color: "var(--color-danger)", available: d.by_target.some((t) => t.asr_off !== null) },
    { key: "ASR · bật phòng thủ", color: "var(--color-success)", available: d.by_target.some((t) => t.asr_on !== null) },
    { key: "USR · hữu dụng nền", color: "var(--color-accent)", available: d.by_target.some((t) => t.usr_off !== null) },
  ].filter((s) => s.available);
  return (
    <>
      <PageHeader title="Tổng quan" actions={batch ? <Link className="filter-clear" to={{ pathname: "/runs", search: `?scope=${kind}&batch=${encodeURIComponent(batch)}` }}>Điều tra lô <ArrowRight size={14} /></Link> : undefined} info="ASR: tỷ lệ tấn công đạt mục tiêu. USR: tỷ lệ hoàn thành tác vụ lành tính. Mẫu số loại run lỗi hạ tầng; khoảng tin cậy Wilson 95%." />
      <p className="overview-intro">Mức độ an toàn và hữu dụng của agent trên <strong className="font-medium text-slate-800">{batch ? "lô đang chọn" : SCOPE_LABEL[kind].toLowerCase()}</strong>.</p>
      {k.n_attack === 0 && <div className="mb-6"><Callout tone="brand">Chưa có run tấn công trong phạm vi này. Đổi phạm vi dữ liệu hoặc mở <Link to="/lab" className="font-medium underline">Phòng thí nghiệm</Link>.</Callout></div>}

      <section className="metric-strip" aria-label="Chỉ số đánh giá chính">
        <div className="metric">
          <span className="block-icon" aria-hidden="true"><Crosshair size={22} /></span><div className="metric-label">Tấn công thành công · ASR</div>
          <strong className={`metric-value num${k.asr_off ? "" : " is-unmeasured"}`}>{k.asr_off ? pct(k.asr_off.p) : "Chưa đo"}</strong>
          <div className="metric-detail"><Sample rate={k.asr_off} noun="run tấn công" /><br />Bật phòng thủ: <strong>{pct(k.asr_on?.p)}</strong>{k.asr_on ? ` · n=${int(k.asr_on.n)}` : " · chưa đo"}</div>
        </div>
        <div className="metric">
          <span className="block-icon" aria-hidden="true"><CircleCheck size={22} /></span><div className="metric-label">Hoàn thành tác vụ · USR</div>
          <strong className={`metric-value num${k.usr_off ? "" : " is-unmeasured"}`}>{k.usr_off ? pct(k.usr_off.p) : "Chưa đo"}</strong>
          <div className="metric-detail"><Sample rate={k.usr_off} noun="câu lành tính" /><br />Chặn nhầm · FRR: <strong>{pct(k.frr?.p)}</strong></div>
        </div>
        <div className="metric">
          <span className="block-icon" aria-hidden="true"><Layers size={22} /></span><div className="metric-label">Lượt chạy hợp lệ</div>
          <strong className="metric-value num">{int(valid)}</strong>
          <div className="metric-detail">Trên tổng {int(k.n_runs)} lượt chạy<br /><strong>{int(k.n_parse_error)}</strong> lỗi hạ tầng đã loại khỏi mẫu số</div>
        </div>
      </section>

      <Card>
        <CardHeader icon={<ChartColumn size={22} />} title="Kết quả theo model" subtitle="ASR thấp hơn là an toàn hơn · USR cao hơn là hữu dụng hơn" action={<button className="table-toggle" aria-expanded={showTable} aria-controls="model-data-table" onClick={() => setShowTable(!showTable)}>{showTable ? "Ẩn bảng số liệu" : "Bảng số liệu"}</button>} />
        <div className="overview-chart">
          {series.length ? <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} barGap={6} accessibilityLayer margin={{ left: -14, right: 12, top: 24, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--color-rule)" strokeDasharray="3 5" />
              <XAxis dataKey="target" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "var(--color-muted)" }} dy={8} />
              <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--color-muted)" }} />
              <Tooltip position={{ x: 36, y: 8 }} formatter={(v: number) => `${v.toLocaleString("vi-VN")}%`} contentStyle={{ borderRadius: 4, border: "1px solid var(--color-rule)", fontSize: 12, boxShadow: "none" }} cursor={{ fill: "var(--color-accent-soft)" }} />
              <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 20 }} />
              {series.map((s) => <Bar key={s.key} dataKey={s.key} name={s.key} fill={s.color} radius={[2, 2, 0, 0]} maxBarSize={30} isAnimationActive={false}>
                <LabelList dataKey={s.key} position="top" fill="var(--color-ink)" fontSize={11} formatter={(v: unknown) => typeof v === "number" ? `${v.toLocaleString("vi-VN")}%` : ""} />
              </Bar>)}
            </BarChart>
          </ResponsiveContainer> : <Empty title="Chưa có dữ liệu theo model" />}
        </div>
        <div className="chart-reading-note">Chỉ hiển thị chỉ số đã đo. <strong>0% là kết quả đo được</strong>; “—” trong bảng là chưa có dữ liệu.</div>
        {showTable && <div id="model-data-table" className="max-w-full overflow-x-auto"><table className="table-base">
          <caption className="sr-only">Số liệu chính xác theo model. Dấu gạch ngang nghĩa là chưa đo.</caption>
          <thead><tr><th scope="col">Model</th><th scope="col">ASR tắt phòng thủ</th><th scope="col">ASR bật phòng thủ</th><th scope="col">USR nền</th></tr></thead>
          <tbody>{d.by_target.map((t) => <tr key={t.target_id}><th scope="row" className="px-4 py-3 text-sm font-medium">{t.target_id}</th>{[t.asr_off, t.asr_on, t.usr_off].map((r, i) => <td key={i}><span className="num">{pct(r?.p)}</span><span className="sample-size">{r ? `n=${int(r.n)} · CI ${ci(r.lo, r.hi)}` : "Chưa đo"}</span></td>)}</tr>)}</tbody>
        </table></div>}
      </Card>
      <div className="measurement-note">
        <span>Phòng thủ chặn: {int(k.blocked_by.defense)}</span>
        <span>Model tự từ chối: {int(k.blocked_by.model_refusal)}</span>
        <span>Harness chặn: {int(k.blocked_by.harness)}</span>
        <span>Số liệu cập nhật {new Date(q.dataUpdatedAt).toLocaleTimeString("vi-VN")}</span>
      </div>

      <section className="overview-results">
        <div className="overview-results-head">
          <div><div className="section-kicker">Truy tới bằng chứng</div><h2>Lô gần đây</h2></div>
          <Link to="/batches">Tất cả lô <ArrowRight size={14} /></Link>
        </div>
        <Card>
          {d.recent_batches.length ? <div className="max-w-full overflow-x-auto"><table className="table-base">
            <thead><tr><th>Lô thực nghiệm</th><th>Loại</th><th>Model</th><th className="text-right">Run</th><th className="text-right">Kết quả</th><th className="text-right">Bắt đầu</th></tr></thead>
            <tbody>{d.recent_batches.map((b) => <tr key={b.batch_id} className="hover:bg-slate-50">
              <td><Link to={{ pathname: "/runs", search: `?batch=${encodeURIComponent(b.batch_id)}&scope=${b.kind}` }} className="font-mono text-[12px] font-medium text-brand-600 hover:underline">{b.batch_id}</Link></td>
              <td><Badge>{KIND_LABEL[b.kind]}</Badge></td>
              <td className="text-[13px] text-slate-600">{b.targets.join(", ")}</td>
              <td className="num text-right">{int(b.n_runs)}</td>
              <td className="num whitespace-nowrap text-right text-[13px] text-slate-600">{b.n_attack ? `${b.n_success}/${b.n_attack} thành công` : `${b.n_pass}/${b.n_benign} đạt`}</td>
              <td className="whitespace-nowrap text-right text-[12px] text-slate-500">{when(b.created_at)}</td>
            </tr>)}</tbody>
          </table></div> : <Empty title="Chưa có lô thực nghiệm" />}
        </Card>
      </section>
    </>
  );
}
