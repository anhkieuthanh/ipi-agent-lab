import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Crosshair } from "lucide-react";
import { useState } from "react";

import { Badge, Callout, Card, CardHeader, Empty, ErrorBox, Loading, PageHeader, RateBar, Select } from "@/components/ui";
import { api, type AsrRow } from "@/lib/api";
import { CHANNEL_LABEL, GOAL_LABEL, TECHNIQUE_LABEL, ci, int, pct, presetLabel } from "@/lib/format";
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
      <table className="border-separate border-spacing-1.5">
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
      </table>
      <div className="mt-4 flex items-center gap-3 text-[12px] text-slate-500">
        <span>ASR</span>
        <div className="h-2 w-40 rounded-full" style={{ background: "linear-gradient(90deg, rgba(229,72,77,.08), rgba(229,72,77,.9))" }} />
        <span>0% → 100%</span>
      </div>
    </div>
  );
}

export function AttackPage() {
  const { params } = useScope();
  const [view, setView] = useState<View>("channel,technique");
  const dims = view.split(",");
  const q = useQuery({ queryKey: ["asr", params, view], queryFn: () => api.asr({ ...params, by: view }) });

  return (
    <>
      <PageHeader
        title="Phân tích tấn công"
        description="Tỉ lệ tấn công thành công ASR_e2e theo từng ô thực nghiệm. Mẫu số loại run lỗi hạ tầng; khoảng tin cậy Wilson 95%. Ô bật phòng thủ có thêm DSR = 1 − ASR."
        actions={<Select value={view} onChange={setView} options={VIEWS} className="w-64" />}
      />
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
        <div className="space-y-6">
          <Callout tone="warn" title="Đọc kết quả G2 thận trọng">
            Scorer hiện tính cả vi phạm phạm vi tự phát của agent (không do payload) là G2 thành công — Việc
            treo VT-16. Kiểm “tool agent đã gọi” ở trang chi tiết run trước khi kết luận.
          </Callout>
          {dims.length === 2 && (
            <Card>
              <CardHeader
                title={`Bản đồ ASR · ${DIM_LABEL[dims[0]]} × ${DIM_LABEL[dims[1]]}`}
                subtitle="Mỗi ô: ASR_e2e và số run thành công / run hợp lệ"
              />
              <Heatmap rows={q.data.rows} dims={[dims[0], dims[1]]} />
            </Card>
          )}
          <Card>
            <CardHeader title="Bảng chi tiết" subtitle="Phân rã nguyên nhân chặn: phòng thủ · model từ chối · harness" />
            <table className="table-base">
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
            </table>
          </Card>
        </div>
      )}
    </>
  );
}
