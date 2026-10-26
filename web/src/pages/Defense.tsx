import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, ChevronDown, ChartScatter, ShieldCheck, SlidersHorizontal } from "lucide-react";
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

import { Badge, Card, CardHeader, Empty, ErrorBox, Loading, PageHeader, RateBar } from "@/components/ui";
import { api, type DefensePoint } from "@/lib/api";
import { DEFENSE_LABEL, ci, int, pct, presetLabel } from "@/lib/format";
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
            label={{ value: "ASR — thấp hơn là an toàn hơn", position: "insideBottom", offset: -8, fontSize: 12, fill: "#64748b" }}
            tick={{ fontSize: 12, fill: "#94a3b8" }}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            name="USR"
            label={{ value: "USR — cao hơn là hữu dụng hơn", angle: -90, position: "insideLeft", fontSize: 12, fill: "#64748b" }}
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

export function DefensePage() {
  const { params } = useScope();
  const points = useQuery({ queryKey: ["defense", params], queryFn: () => api.defensePoints({ ...params }) });
  const presets = useQuery({ queryKey: ["presets"], queryFn: api.presets, staleTime: 300_000 });
  const [open, setOpen] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        title="Phân tích phòng thủ"
        info="Mỗi cơ chế đánh giá theo cặp: giảm tấn công (ASR) đổi lấy mất hữu dụng (USR, FRR). Điểm tốt ở góc trên bên trái."
      />
      {(points.isLoading || presets.isLoading) && <Loading />}
      {points.error && <ErrorBox error={points.error} />}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title="Đường đánh đổi an toàn – hữu dụng" icon={<ChartScatter size={16} />} />
          {points.data && <ParetoChart points={points.data.points} />}
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader title="Bốn cơ chế phòng thủ" icon={<ShieldCheck size={16} />} />
          <div className="divide-y divide-slate-100">
            {(["D1", "D2", "D3", "D4"] as const).map((code) => {
              const Icon = DEFENSE_ICON[code];
              return (
                <div key={code} className="flex items-start gap-3 px-5 py-3.5">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-defense-50 text-defense-600">
                    <Icon size={17} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2 text-[13.5px] font-semibold text-slate-800">
                      <Badge tone="defense" className="font-mono">
                        {code}
                      </Badge>
                      {DEFENSE_LABEL[code]}
                    </div>
                    <div className="mt-0.5 text-[12.5px] text-slate-500">{DEFENSE_DESC[code]}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader title="Cấu hình phòng thủ (preset)" icon={<SlidersHorizontal size={16} />} />
        <table className="table-base">
          <thead>
            <tr>
              <th>Preset</th>
              {["D1", "D2", "D3", "D4"].map((c) => (
                <th key={c} className="text-center">
                  {c}
                </th>
              ))}
              <th>Model</th>
              <th className="w-48">ASR</th>
              <th className="w-48">USR</th>
              <th className="text-right">FRR</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(presets.data ?? []).map((p) => {
              const pts = (points.data?.points ?? []).filter((x) => x.preset === p.name);
              const rows = pts.length ? pts : [null];
              return rows.map((pt, i) => (
                <Fragment key={`${p.name}-${i}`}>
                  <tr className="hover:bg-slate-50/70">
                    {i === 0 && (
                      <td rowSpan={rows.length} className="align-top">
                        <div className="flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ background: PRESET_COLOR[p.name] ?? "#334155" }} />
                          <span className="font-medium text-slate-800">{presetLabel(p.name)}</span>
                        </div>
                        <div className="ml-[18px] font-mono text-[11.5px] text-slate-400">{p.name}</div>
                      </td>
                    )}
                    {i === 0 &&
                      ["D1", "D2", "D3", "D4"].map((c) => (
                        <td key={c} rowSpan={rows.length} className="text-center align-top">
                          {p.codes.includes(c) ? (
                            <Check size={16} className="mx-auto text-defense-600" />
                          ) : (
                            <span className="text-slate-300">·</span>
                          )}
                        </td>
                      ))}
                    <td className="text-slate-600">{pt?.target_id ?? "—"}</td>
                    <td>
                      {pt && pt.asr_e2e !== null ? (
                        <>
                          <div className="num mb-1 text-[12.5px] font-medium">
                            {pct(pt.asr_e2e)} <span className="text-slate-400">n={int(pt.n_attack)}</span>
                          </div>
                          <RateBar p={pt.asr_e2e} lo={pt.asr_lo} hi={pt.asr_hi} />
                        </>
                      ) : (
                        <span className="text-[12.5px] text-slate-400">chưa đo</span>
                      )}
                    </td>
                    <td>
                      {pt && pt.usr !== null ? (
                        <>
                          <div className="num mb-1 text-[12.5px] font-medium">
                            {pct(pt.usr)} <span className="text-slate-400">n={int(pt.n_benign)}</span>
                          </div>
                          <RateBar p={pt.usr} lo={pt.usr_lo} hi={pt.usr_hi} tone="brand" />
                        </>
                      ) : (
                        <span className="text-[12.5px] text-slate-400">chưa đo</span>
                      )}
                    </td>
                    <td className="num text-right">{pt ? pct(pt.frr) : "—"}</td>
                    {i === 0 && (
                      <td rowSpan={rows.length} className="w-10 align-top">
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
                    )}
                  </tr>
                  {open === p.name && i === rows.length - 1 && (
                    <tr>
                      <td colSpan={11} className="bg-slate-50/60">
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
              ));
            })}
          </tbody>
        </table>
      </Card>
    </>
  );
}
