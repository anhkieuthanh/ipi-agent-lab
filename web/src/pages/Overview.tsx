import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

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
  return (
    <>
      <PageHeader title="Tổng quan đánh giá" info="ASR: tỷ lệ tấn công đạt mục tiêu. USR: tỷ lệ hoàn thành tác vụ lành tính. Mẫu số loại run lỗi hạ tầng; khoảng tin cậy Wilson 95%." />
      <p className="overview-intro">Mức độ an toàn và hữu dụng của agent trên <strong className="font-medium text-slate-800">{batch || SCOPE_LABEL[kind].toLowerCase()}</strong>.</p>
      {k.n_attack === 0 && <div className="mb-6"><Callout tone="brand">Chưa có run tấn công trong phạm vi này. Đổi phạm vi dữ liệu hoặc mở <Link to="/lab" className="font-medium underline">Phòng thí nghiệm</Link>.</Callout></div>}

      <section className="metric-strip" aria-label="Chỉ số đánh giá chính">
        <div className="metric">
          <div className="metric-label">Tấn công đạt mục tiêu · ASR nền</div>
          <strong className="metric-value num">{pct(k.asr_off?.p)}</strong>
          <div className="metric-detail"><Sample rate={k.asr_off} noun="run tấn công" /><br />Bật phòng thủ: <strong>{pct(k.asr_on?.p)}</strong>{k.asr_on ? ` · n=${int(k.asr_on.n)}` : " · chưa đo"}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Hoàn thành tác vụ · USR nền</div>
          <strong className="metric-value num">{pct(k.usr_off?.p)}</strong>
          <div className="metric-detail"><Sample rate={k.usr_off} noun="câu lành tính" /><br />Chặn nhầm · FRR: <strong>{pct(k.frr?.p)}</strong></div>
        </div>
        <div className="metric">
          <div className="metric-label">Lượt chạy hợp lệ</div>
          <strong className="metric-value num">{int(valid)}</strong>
          <div className="metric-detail">Trên tổng {int(k.n_runs)} lượt chạy<br /><strong>{int(k.n_parse_error)}</strong> lỗi hạ tầng đã loại khỏi mẫu số</div>
        </div>
      </section>

      <Card>
        <CardHeader title="An toàn và hữu dụng theo model" subtitle="ASR thấp hơn là an toàn hơn · USR cao hơn là hữu dụng hơn" />
        <div className="overview-chart">
          {chart.length ? <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} barGap={6} margin={{ left: -14, right: 12, top: 12, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--color-rule)" strokeDasharray="3 5" />
              <XAxis dataKey="target" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "var(--color-muted)" }} dy={8} />
              <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--color-muted)" }} />
              <Tooltip formatter={(v: number) => `${v.toLocaleString("vi-VN")}%`} contentStyle={{ borderRadius: 4, border: "1px solid var(--color-rule)", fontSize: 12, boxShadow: "none" }} cursor={{ fill: "var(--color-accent-soft)" }} />
              <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 20 }} />
              <Bar dataKey="ASR · tắt phòng thủ" fill="var(--color-danger)" radius={[2, 2, 0, 0]} maxBarSize={28} />
              <Bar dataKey="ASR · bật phòng thủ" fill="var(--color-success)" radius={[2, 2, 0, 0]} maxBarSize={28} />
              <Bar dataKey="USR · hữu dụng nền" fill="var(--color-accent)" radius={[2, 2, 0, 0]} maxBarSize={28} />
            </BarChart>
          </ResponsiveContainer> : <Empty title="Chưa có dữ liệu theo model" />}
        </div>
      </Card>
      <div className="measurement-note">
        <span>Phòng thủ chặn: {int(k.blocked_by.defense)}</span>
        <span>Model tự từ chối: {int(k.blocked_by.model_refusal)}</span>
        <span>Harness chặn: {int(k.blocked_by.harness)}</span>
        <span>Số liệu cập nhật {new Date(q.dataUpdatedAt).toLocaleTimeString("vi-VN")}</span>
      </div>

      <section className="overview-results">
        <div className="overview-results-head">
          <div><div className="section-kicker">Truy tới bằng chứng</div><h2>Lô thực nghiệm gần đây</h2></div>
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
