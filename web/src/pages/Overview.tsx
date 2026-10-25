import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowRight,
  Ban,
  CheckCircle2,
  CircleDashed,
  Coins,
  Crosshair,
  ShieldCheck,
  ThumbsUp,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import {
  Badge,
  Callout,
  Card,
  CardHeader,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  RateBar,
  Stat,
} from "@/components/ui";
import { api, type Gate, type Rate } from "@/lib/api";
import { BLOCKED_LABEL, KIND_LABEL, ci, int, pct, usd, when } from "@/lib/format";
import { SCOPE_LABEL, useScope } from "@/lib/scope";

function rateHint(r: Rate, noun: string) {
  if (!r) return `Chưa có ${noun}`;
  return (
    <span>
      {int(r.x)}/{int(r.n)} {noun} · CI 95% {ci(r.lo, r.hi)}
    </span>
  );
}

function GateRow({ gate }: { gate: Gate }) {
  const icon = {
    pass: <CheckCircle2 size={18} className="text-defense-500" />,
    fail: <XCircle size={18} className="text-attack-500" />,
    pending: <CircleDashed size={18} className="text-slate-400" />,
  }[gate.status];
  const tone = { pass: "defense", fail: "attack", pending: "neutral" } as const;
  const text = { pass: "Đạt", fail: "Chưa đạt", pending: "Chờ" };
  return (
    <div className="flex items-center gap-3 px-5 py-3.5">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-medium text-slate-800">{gate.label}</div>
        <div className="truncate text-[12.5px] text-slate-500">{gate.detail}</div>
      </div>
      <Badge tone={tone[gate.status]}>{text[gate.status]}</Badge>
    </div>
  );
}

export function OverviewPage() {
  const { params, kind, batch } = useScope();
  const q = useQuery({ queryKey: ["overview", params], queryFn: () => api.overview(params) });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const k = d.kpis;
  const b = d.budget;
  const budgetRatio = b.total_usd && b.spent_usd !== null ? b.spent_usd / b.total_usd : null;

  const chart = d.by_target.map((t) => ({
    target: t.target_id,
    "ASR (tắt phòng thủ)": t.asr_off ? +(t.asr_off.p * 100).toFixed(1) : null,
    "ASR (bật phòng thủ)": t.asr_on ? +(t.asr_on.p * 100).toFixed(1) : null,
    "USR nền": t.usr_off ? +(t.usr_off.p * 100).toFixed(1) : null,
  }));
  const blockedTotal = Object.values(k.blocked_by).reduce((a, x) => a + x, 0);

  return (
    <>
      <PageHeader
        title="Tổng quan"
        description={
          <>
            Sức chống chịu của agent trước tấn công tiêm nhiễm gián tiếp, trên{" "}
            <b className="font-medium text-slate-700">{batch ? `lô ${batch}` : SCOPE_LABEL[kind].toLowerCase()}</b>.
            Run lỗi hạ tầng (<span className="font-mono">parse_error</span>) bị loại khỏi mẫu số.
          </>
        }
      />

      {k.n_attack === 0 && (
        <div className="mb-6">
          <Callout tone="brand" title="Chưa có run tấn công trong phạm vi này">
            Số liệu tấn công sẽ xuất hiện sau lô pilot (STT-60). Có thể xem các lượt chạy thử hoặc demo bằng
            bộ chọn <b>Phạm vi</b> ở góc trên, hoặc chạy một kịch bản trong{" "}
            <Link to="/lab" className="font-semibold underline">
              Phòng thí nghiệm
            </Link>
            .
          </Callout>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Stat
          label="ASR · tắt phòng thủ"
          value={pct(k.asr_off?.p)}
          tone="attack"
          icon={<Crosshair size={16} />}
          hint={rateHint(k.asr_off, "run tấn công")}
        />
        <Stat
          label="ASR · bật phòng thủ"
          value={pct(k.asr_on?.p)}
          tone="defense"
          icon={<ShieldCheck size={16} />}
          hint={rateHint(k.asr_on, "run tấn công")}
        />
        <Stat
          label="USR nền (hữu dụng)"
          value={pct(k.usr_off?.p)}
          tone="brand"
          icon={<ThumbsUp size={16} />}
          hint={rateHint(k.usr_off, "câu lành tính")}
        />
        <Stat
          label="FRR (chặn nhầm)"
          value={pct(k.frr?.p)}
          tone="warn"
          icon={<Ban size={16} />}
          hint={rateHint(k.frr, "câu lành tính")}
        />
        <Stat
          label="Chi phí API"
          value={usd(b.spent_usd)}
          tone="neutral"
          icon={<Coins size={16} />}
          hint={b.total_usd ? `Trần ${usd(b.total_usd, 0)} · ${pct(budgetRatio, 0)} đã dùng` : "Chưa đặt trần trong .env"}
          footer={
            budgetRatio !== null ? (
              <RateBar p={Math.min(budgetRatio, 1)} tone={budgetRatio > b.alert_pct / 100 ? "attack" : "brand"} />
            ) : undefined
          }
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="So sánh theo model đích"
            subtitle="Tỉ lệ tấn công thành công (ASR) và tỉ lệ hữu dụng (USR), % trên run hợp lệ"
          />
          <div className="h-[290px] px-3 pb-3 pt-4">
            {chart.length ? (
              <ResponsiveContainer>
                <BarChart data={chart} barGap={4} margin={{ left: -10, right: 10 }}>
                  <CartesianGrid vertical={false} stroke="#eef0f4" />
                  <XAxis dataKey="target" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                  <YAxis
                    domain={[0, 100]}
                    tickFormatter={(v) => `${v}%`}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 12, fill: "#94a3b8" }}
                  />
                  <Tooltip
                    formatter={(v: number) => `${v.toLocaleString("vi-VN")}%`}
                    contentStyle={{ borderRadius: 10, border: "1px solid #e2e8f0", fontSize: 12.5 }}
                  />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12.5 }} />
                  <Bar dataKey="ASR (tắt phòng thủ)" fill="#e5484d" radius={[4, 4, 0, 0]} maxBarSize={34} />
                  <Bar dataKey="ASR (bật phòng thủ)" fill="#16a34a" radius={[4, 4, 0, 0]} maxBarSize={34} />
                  <Bar dataKey="USR nền" fill="#3b6cf6" radius={[4, 4, 0, 0]} maxBarSize={34} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <Empty title="Chưa có dữ liệu" />
            )}
          </div>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader title="Cổng nghiệm thu" subtitle="Điều kiện trước khi chạy ma trận đầy đủ" />
            <div className="divide-y divide-slate-100">
              {d.gates.map((g) => (
                <GateRow key={g.id} gate={g} />
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title="Ai đã chặn" subtitle="Tách phòng thủ khỏi model tự từ chối" />
            <div className="space-y-3 px-5 py-4">
              {(Object.keys(k.blocked_by) as (keyof typeof k.blocked_by)[]).map((key) => {
                const n = k.blocked_by[key];
                const tone = key === "defense" ? "defense" : key === "model_refusal" ? "refusal" : "neutral";
                return (
                  <div key={key}>
                    <div className="mb-1 flex items-center justify-between text-[13px]">
                      <span className="flex items-center gap-2 text-slate-700">
                        <span
                          className={clsx(
                            "h-2 w-2 rounded-full",
                            tone === "defense" ? "bg-defense-500" : tone === "refusal" ? "bg-refusal-500" : "bg-slate-400",
                          )}
                        />
                        {BLOCKED_LABEL[key]}
                      </span>
                      <span className="num font-medium text-slate-900">{int(n)}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-slate-100">
                      <div
                        className={clsx(
                          "h-1.5 rounded-full",
                          tone === "defense" ? "bg-defense-500" : tone === "refusal" ? "bg-refusal-500" : "bg-slate-400",
                        )}
                        style={{ width: blockedTotal ? `${(n / blockedTotal) * 100}%` : 0 }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>
      </div>

      <Card className="mt-6">
        <CardHeader
          title="Lô gần đây"
          subtitle="Mọi loại lô — bấm để xem các run"
          action={
            <Link to="/batches" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-600 hover:text-brand-700">
              Xem tất cả <ArrowRight size={14} />
            </Link>
          }
        />
        <table className="table-base">
          <thead>
            <tr>
              <th>Lô</th>
              <th>Loại</th>
              <th>Model</th>
              <th className="text-right">Run</th>
              <th className="text-right">Kết quả</th>
              <th className="text-right">Bắt đầu</th>
            </tr>
          </thead>
          <tbody>
            {d.recent_batches.map((bt) => (
              <tr key={bt.batch_id} className="hover:bg-slate-50/70">
                <td>
                  <Link
                    to={{ pathname: "/runs", search: `?batch=${encodeURIComponent(bt.batch_id)}` }}
                    className="font-mono text-[12.5px] font-medium text-slate-800 hover:text-brand-600"
                  >
                    {bt.batch_id}
                  </Link>
                </td>
                <td>
                  <Badge tone={bt.kind === "experiment" ? "brand" : bt.kind === "demo" ? "payload" : "neutral"}>
                    {KIND_LABEL[bt.kind]}
                  </Badge>
                </td>
                <td className="text-slate-600">{bt.targets.join(", ")}</td>
                <td className="num text-right">{int(bt.n_runs)}</td>
                <td className="num text-right text-slate-600">
                  {bt.n_attack ? `${bt.n_success}/${bt.n_attack} thành công` : `${bt.n_pass}/${bt.n_benign} đạt`}
                </td>
                <td className="text-right text-slate-500">{when(bt.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <p className="mt-3 text-[12px] text-slate-400">
        Chi phí đọc từ <span className="font-mono">{b.source}</span>. ASR · DSR · USR · FRR theo định nghĩa của
        scorer; khoảng tin cậy Wilson 95%.
      </p>
    </>
  );
}
