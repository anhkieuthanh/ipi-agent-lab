import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowUp, Check, ChevronDown } from "lucide-react";
import { Link } from "react-router-dom";
import { Fragment, useState } from "react";

import { OutcomeBar, OutcomeLegend, Rate, ScopeNote, useRunsLink } from "@/components/Analysis";
import { ScatterPlot, type ScatterPoint } from "@/components/charts";
import { Button, Card, CardHeader, Disclosure, Empty, ErrorBox, Loading, PageHeader, RateBar } from "@/components/ui";
import { api, type DefensePoint, type DefenseSummary, type Preset } from "@/lib/api";
import { DEFENSE_LABEL, ci, pct, presetLabel } from "@/lib/format";
import { useScope } from "@/lib/scope";

/** Màu của từng cấu hình — tên biến trong tokens.css. Màu chỉ hỗ trợ; tên cấu hình luôn đi kèm. */
const PRESET_TOKEN: Record<string, string> = {
  off: "n-500",
  d1_only: "canary-500",
  d2_only: "refusal-500",
  d3_only: "amber-400",
  d4_only: "payload-500",
  d3_no_confirm: "brand-500",
  all: "defense-500",
};
const presetToken = (p: string) => PRESET_TOKEN[p] ?? "n-700";

/** Tên ngắn đặt cạnh điểm trên biểu đồ. */
function presetShort(p: string): string {
  if (p === "off") return "Tắt";
  if (p === "all") return "D1–D4";
  const m = /^d(\d)_only$/.exec(p);
  if (m) return `D${m[1]}`;
  if (p === "d3_no_confirm") return "D3 không XN";
  return p;
}

function PresetName({ name, code }: { name: string; code?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: `rgb(var(--${presetToken(name)}))` }} aria-hidden="true" />
      <span className="text-slate-800">{presetLabel(name)}</span>
      {code && <span className="font-mono text-xs text-slate-400">{name}</span>}
    </span>
  );
}

const Unmeasured = () => <span className="text-xs text-slate-400">chưa đo</span>;

const DEFENSE_DESC: Record<string, string> = {
  D1: "Bọc ranh giới dữ liệu / chỉ thị để model phân biệt nội dung ngoài.",
  D2: "Làm sạch cú pháp tất định: bỏ mệnh lệnh, ký tự ẩn, định dạng che giấu.",
  D3: "Máy trạng thái ngoài LLM: chỉ cho gọi tool đúng loại tác vụ, xin xác nhận hành động ghi.",
  D4: "Soát dữ liệu đi ra: canary, đích lạ, PII, URL mã hóa.",
};

function Delta({ v, better }: { v: number | null; better: "down" | "up" }) {
  if (v === null || v === undefined) return <span className="text-slate-300">—</span>;
  if (Math.abs(v) < 0.0005) return <span className="num text-xs text-slate-400">±0</span>;
  const good = better === "down" ? v < 0 : v > 0;
  const Icon = v < 0 ? ArrowDown : ArrowUp;
  return (
    <span className={clsx("num inline-flex items-center gap-0.5 whitespace-nowrap text-xs font-medium", good ? "text-defense-600" : "text-attack-600")}>
      <Icon size={11} aria-hidden="true" />
      <span className="sr-only">{v < 0 ? "giảm" : "tăng"}</span>
      {pct(Math.abs(v))}
    </span>
  );
}

function NotMeasuredNote() {
  return (
    <p className="text-sm text-slate-600">
      <span className="font-medium text-slate-900">Chưa có lô đo phòng thủ (khối B2) trong phạm vi này.</span>{" "}
      Hiện chỉ có run tắt phòng thủ — dùng làm mốc so sánh bên dưới.
    </p>
  );
}

function NotMeasuredDetail({ d }: { d: DefenseSummary }) {
  const pending = d.presets.filter((p) => !d.measured.includes(p.name));
  return (
    <Disclosure summary="Trang này sẽ hiện gì sau khi chạy khối B2">
      <div className="max-w-[88ch] space-y-1 text-sm text-slate-600">
        <p>
          Mỗi cấu hình giảm bao nhiêu tấn công và mất bao nhiêu hữu dụng (RQ4), tổ hợp D1–D4 so với cơ chế đơn lẻ tốt
          nhất (RQ3), và chặn nhầm theo tác vụ.
        </p>
        {pending.length > 0 && <p>Cấu hình chờ đo: {pending.map((p) => presetLabel(p.name)).join(" · ")}.</p>}
      </div>
    </Disclosure>
  );
}

function Baseline({ d }: { d: DefenseSummary }) {
  const link = useRunsLink();
  return (
    <Card>
      <CardHeader title="Mốc so sánh · tắt phòng thủ" subtitle="Mọi cấu hình phòng thủ được so với mốc này của cùng model." />
      <div className="max-w-full overflow-x-auto border-t border-slate-200">
        <table className="table-base">
          <thead>
            <tr>
              <th>Model</th>
              <th className="min-w-52">Tấn công thành công (ASR)</th>
              <th className="min-w-52">Câu lành tính đạt (USR)</th>
              <th className="min-w-36">Chặn nhầm (FRR)</th>
              <th className="min-w-44">Kết cục run tấn công</th>
            </tr>
          </thead>
          <tbody>
            {d.baseline.map((b) => (
              <tr key={b.target_id}>
                <td>
                  <Link to={link({ target: b.target_id })} className="font-mono font-medium text-slate-900 hover:underline">
                    {b.target_id}
                  </Link>
                </td>
                <td>
                  <div className="space-y-1.5">
                    <Rate r={b.asr} />
                    <RateBar p={b.asr.p} lo={b.asr.lo} hi={b.asr.hi} />
                  </div>
                </td>
                <td>
                  {b.usr.n ? (
                    <div className="space-y-1.5">
                      <Rate r={b.usr} good />
                      <RateBar p={b.usr.p} lo={b.usr.lo} hi={b.usr.hi} tone="brand" />
                    </div>
                  ) : (
                    <Unmeasured />
                  )}
                </td>
                <td>{b.frr.n ? <Rate r={b.frr} good /> : <Unmeasured />}</td>
                <td>{b.outcomes && <OutcomeBar o={b.outcomes} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-2 border-t border-slate-200 px-4 py-3">
        <OutcomeLegend />
        <p className="max-w-[88ch] text-xs text-slate-500">
          Phần “Model từ chối” là lớp an toàn sẵn có của model — phòng thủ D1–D4 không được tính công cho phần đó.
        </p>
      </div>
    </Card>
  );
}

function Effects({ d }: { d: DefenseSummary }) {
  const targets = [...new Set(d.effects.map((e) => e.target_id))];
  return (
    <Card>
      <CardHeader
        title="RQ4 · Mỗi cấu hình giảm bao nhiêu tấn công, mất bao nhiêu hữu dụng?"
        subtitle="Δ so với lúc tắt phòng thủ của cùng model: ASR giảm là tốt, USR giảm là cái giá phải trả."
      />
      <div className="max-w-full overflow-x-auto border-t border-slate-200">
        <table className="table-base">
          <thead>
            <tr>
              <th>Model</th>
              <th>Cấu hình</th>
              <th>Tấn công thành công (ASR)</th>
              <th className="text-right">Δ ASR</th>
              <th className="text-right">Cắt được</th>
              <th>Câu lành tính đạt (USR)</th>
              <th className="text-right">Δ USR</th>
              <th>Chặn nhầm (FRR)</th>
              <th className="min-w-40">Kết cục</th>
            </tr>
          </thead>
          <tbody>
            {targets.flatMap((t) =>
              d.effects
                .filter((e) => e.target_id === t)
                .sort((a, b) => (a.asr.p ?? 1) - (b.asr.p ?? 1))
                .map((e, i) => (
                  <tr key={`${t}-${e.preset}`}>
                    <td className="font-mono font-medium text-slate-900">
                      {i === 0 ? t : <span className="sr-only">{t}</span>}
                    </td>
                    <td>
                      <PresetName name={e.preset} />
                    </td>
                    <td>
                      <Rate r={e.asr} />
                    </td>
                    <td className="text-right">
                      <Delta v={e.d_asr} better="down" />
                    </td>
                    <td className="num text-right">{e.asr_cut === null ? <span className="text-slate-300">—</span> : pct(e.asr_cut, 0)}</td>
                    <td>{e.usr.n ? <Rate r={e.usr} good /> : <Unmeasured />}</td>
                    <td className="text-right">{e.usr.n ? <Delta v={e.d_usr} better="up" /> : <span className="text-slate-300">—</span>}</td>
                    <td>{e.frr.n ? <Rate r={e.frr} good /> : <Unmeasured />}</td>
                    <td>{e.outcomes && <OutcomeBar o={e.outcomes} />}</td>
                  </tr>
                )),
            )}
          </tbody>
        </table>
      </div>
      <div className="space-y-2 border-t border-slate-200 px-4 py-3">
        <OutcomeLegend />
        <Disclosure summary="Cách đọc bảng">
          <p className="max-w-[88ch] text-sm text-slate-600">
            Mũi tên so với lúc tắt phòng thủ của cùng model: ASR giảm (xanh) là tốt, USR giảm (đỏ) là cái giá phải trả.
            “Cắt được” = phần tấn công thành công bị loại bỏ.
          </p>
        </Disclosure>
      </div>
    </Card>
  );
}

function Rq3({ d }: { d: DefenseSummary }) {
  if (!d.rq3.length) return null;
  return (
    <Card>
      <CardHeader title="RQ3 · Bật cả D1–D4 có hơn cơ chế đơn lẻ tốt nhất không?" />
      <div className="max-w-full overflow-x-auto border-t border-slate-200">
        <table className="table-base">
          <thead>
            <tr>
              <th>Model</th>
              <th>ASR khi bật D1–D4</th>
              <th>Tốt nhất đơn lẻ</th>
              <th>ASR đơn lẻ tốt nhất</th>
              <th className="text-right">Tổ hợp giảm thêm ASR</th>
              <th className="text-right">Chênh USR</th>
            </tr>
          </thead>
          <tbody>
            {d.rq3.map((r) => (
              <tr key={r.target_id}>
                <td className="font-mono font-medium text-slate-900">{r.target_id}</td>
                <td>
                  <Rate r={r.all.asr} />
                </td>
                <td>
                  <PresetName name={r.best_single} />
                </td>
                <td>
                  <Rate r={r.single.asr} />
                </td>
                <td className={clsx("text-right", r.gain > 0 ? "font-medium text-defense-700" : "text-slate-500")}>
                  {r.gain > 0 ? <span className="num">{pct(r.gain)}</span> : "không giảm thêm"}
                </td>
                <td className="text-right">
                  {r.usr_cost === null ? (
                    <Unmeasured />
                  ) : (
                    <span className="num text-slate-700">
                      {r.usr_cost >= 0 ? "+" : "−"}
                      {pct(Math.abs(r.usr_cost))}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Tradeoff({ points }: { points: DefensePoint[] }) {
  const usable = points.filter((p) => p.asr_e2e !== null && p.usr !== null);
  const multiTarget = new Set(points.map((p) => p.target_id ?? "")).size > 1;
  const name = (p: DefensePoint) => `${presetLabel(p.preset)}${p.target_id ? ` · ${p.target_id}` : ""}`;
  if (!usable.length) {
    return (
      <Empty title="Chưa đủ dữ liệu để vẽ đường đánh đổi">
        Mỗi điểm cần cả ASR (run tấn công) và USR (run lành tính) của cùng cấu hình phòng thủ và model. Dữ liệu có sau
        khối B2 và B3.
      </Empty>
    );
  }
  const data: ScatterPoint[] = usable.map((p) => ({
    id: `${p.target_id ?? ""}|${p.preset}`,
    x: p.asr_e2e!,
    y: p.usr!,
    xLo: p.asr_lo,
    xHi: p.asr_hi,
    yLo: p.usr_lo,
    yHi: p.usr_hi,
    color: presetToken(p.preset),
    label: `${presetShort(p.preset)}${multiTarget && p.target_id ? ` · ${p.target_id}` : ""}`,
    title: `${name(p)}\nASR ${pct(p.asr_e2e)} (${ci(p.asr_lo, p.asr_hi)}) · n=${p.n_attack}\nUSR ${pct(p.usr)} (${ci(p.usr_lo, p.usr_hi)}) · n=${p.n_benign}`,
  }));
  const skipped = points.length - usable.length;
  return (
    <>
      <div className="max-w-full overflow-x-auto px-4 pb-2">
        <ScatterPlot
          points={data}
          xTitle="Tấn công thành công (ASR) — thấp hơn là an toàn hơn"
          yTitle="Câu lành tính đạt (USR) — cao hơn là hữu dụng hơn"
          ariaLabel={`Biểu đồ phân tán ASR – USR của ${data.length} cấu hình phòng thủ theo model. Số liệu đầy đủ ở bảng bên dưới biểu đồ.`}
        />
      </div>
      <div className="space-y-2 border-t border-slate-200 px-4 py-3">
        <p className="text-xs text-slate-500">
          Râu mảnh quanh mỗi điểm là khoảng tin cậy 95%.
          {skipped > 0 && ` ${skipped} cấu hình chưa đo đủ cả ASR và USR nên không có điểm trên biểu đồ.`}
        </p>
        <Disclosure summary="Bảng số liệu của biểu đồ">
          <div className="max-w-full overflow-x-auto rounded-md border border-slate-200">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Cấu hình</th>
                  <th className="text-right">ASR</th>
                  <th className="text-right">KTC 95%</th>
                  <th className="text-right">n tấn công</th>
                  <th className="text-right">USR</th>
                  <th className="text-right">KTC 95%</th>
                  <th className="text-right">n lành tính</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={`${p.target_id ?? ""}|${p.preset}`}>
                    <td className="font-mono font-medium text-slate-900">{p.target_id ?? "—"}</td>
                    <td>
                      <PresetName name={p.preset} />
                    </td>
                    <td className="num text-right">{p.asr_e2e === null ? <Unmeasured /> : pct(p.asr_e2e)}</td>
                    <td className="num text-right text-slate-500">{ci(p.asr_lo, p.asr_hi) || "—"}</td>
                    <td className="num text-right text-slate-500">{p.n_attack}</td>
                    <td className="num text-right">{p.usr === null ? <Unmeasured /> : pct(p.usr)}</td>
                    <td className="num text-right text-slate-500">{ci(p.usr_lo, p.usr_hi) || "—"}</td>
                    <td className="num text-right text-slate-500">{p.n_benign}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      </div>
    </>
  );
}

function FrrByTask({ d }: { d: DefenseSummary }) {
  if (!d.frr_by_task.length) return null;
  const presetsOn = [...new Set(d.frr_by_task.map((r) => r.preset))];
  const tasks = [...new Set(d.frr_by_task.map((r) => r.carrier_task_id ?? "?"))].sort();
  return (
    <Card>
      <CardHeader
        title="Chặn nhầm theo tác vụ"
        subtitle="Tỉ lệ câu lành tính bị phòng thủ chặn, theo tác vụ chở (giả thuyết H4: D3 chặn nhầm ở CT-05, CT-06)."
      />
      <div className="max-w-full overflow-x-auto border-t border-slate-200">
        <table className="table-base">
          <thead>
            <tr>
              <th>Tác vụ</th>
              {presetsOn.map((p) => (
                <th key={p} className="text-right">
                  {presetLabel(p)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t}>
                <td className="font-mono font-medium text-slate-900">{t}</td>
                {presetsOn.map((p) => {
                  const v = d.frr_by_task.find((r) => r.preset === p && (r.carrier_task_id ?? "?") === t);
                  return (
                    <td key={p} className="text-right">
                      {!v ? <span className="text-slate-300">—</span> : v.frr.n ? <Rate r={v.frr} /> : <Unmeasured />}
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

const CODES = ["D1", "D2", "D3", "D4"] as const;

function Mechanisms({ presets }: { presets: Preset[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader title="Cơ chế D1–D4 và tham số của từng cấu hình" />
      <dl className="divide-y divide-slate-100 border-t border-slate-200">
        {CODES.map((code) => (
          <div key={code} className="grid grid-cols-[2.5rem_1fr] gap-x-3 gap-y-0.5 px-4 py-2 sm:grid-cols-[2.5rem_10rem_1fr]">
            <dt className="contents">
              <span className="font-mono text-xs font-medium leading-5 text-defense-700">{code}</span>
              <span className="font-medium text-slate-900">{DEFENSE_LABEL[code]}</span>
            </dt>
            <dd className="col-start-2 text-slate-600 sm:col-start-3">{DEFENSE_DESC[code]}</dd>
          </div>
        ))}
      </dl>
      <div className="max-w-full overflow-x-auto border-t border-slate-200">
        <table className="table-base">
          <thead>
            <tr>
              <th>Cấu hình</th>
              {CODES.map((c) => (
                <th key={c} className="w-14 text-center">
                  {c}
                </th>
              ))}
              <th className="w-28 text-right">Tham số</th>
            </tr>
          </thead>
          <tbody>
            {presets.map((p) => {
              const isOpen = open === p.name;
              const panelId = `preset-params-${p.name}`;
              return (
                <Fragment key={p.name}>
                  <tr>
                    <td>
                      <PresetName name={p.name} code />
                    </td>
                    {CODES.map((c) => (
                      <td key={c} className="text-center">
                        {p.codes.includes(c) ? (
                          <>
                            <Check size={14} className="mx-auto text-defense-600" aria-hidden="true" />
                            <span className="sr-only">bật</span>
                          </>
                        ) : (
                          <>
                            <span className="text-slate-300" aria-hidden="true">
                              ·
                            </span>
                            <span className="sr-only">tắt</span>
                          </>
                        )}
                      </td>
                    ))}
                    <td className="text-right">
                      {p.codes.length > 0 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setOpen(isOpen ? null : p.name)}
                          aria-expanded={isOpen}
                          aria-controls={panelId}
                          title="Tham số hiệu lực"
                        >
                          {isOpen ? "Ẩn" : "Xem"}
                          <ChevronDown size={12} className={clsx("transition-transform", isOpen && "rotate-180")} aria-hidden="true" />
                        </Button>
                      )}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr id={panelId}>
                      <td colSpan={6} className="bg-slate-50">
                        <div className="grid grid-cols-1 gap-3 py-1 lg:grid-cols-2">
                          {Object.entries(p.params).map(([code, params]) => (
                            <div key={code} className="min-w-0">
                              <div className="mb-1 flex items-baseline gap-2">
                                <span className="font-mono text-xs font-medium text-defense-700">{code}</span>
                                <span className="text-xs font-medium text-slate-700">{DEFENSE_LABEL[code]}</span>
                              </div>
                              <pre className="code-block max-h-64 overflow-auto bg-surface">{JSON.stringify(params, null, 2)}</pre>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
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
        <div className="space-y-4">
          <ScopeNote s={d.scope} />
          {!d.has_defense_runs && <NotMeasuredNote />}
          {d.baseline.length > 0 && <Baseline d={d} />}
          {!d.has_defense_runs && <NotMeasuredDetail d={d} />}
          {d.has_defense_runs && (
            <>
              <Effects d={d} />
              <Rq3 d={d} />
              <Card>
                <CardHeader
                  title="Bản đồ đánh đổi an toàn – hữu dụng"
                  subtitle="Mỗi điểm là một cấu hình trên một model. Điểm tốt nằm góc trên bên trái: ít tấn công thành công, nhiều câu lành tính đạt."
                />
                {points.isLoading && <Loading rows={4} />}
                {points.error && (
                  <div className="px-4 pb-3">
                    <ErrorBox error={points.error} />
                  </div>
                )}
                {points.data && <Tradeoff points={points.data.points} />}
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
