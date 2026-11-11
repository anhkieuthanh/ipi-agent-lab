import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge, Callout, Card, CardHeader, Empty, ErrorBox, Loading, Metric, PageHeader, RateBar, buttonClass } from "@/components/ui";
import { api, type Rate } from "@/lib/api";
import { BLOCKED_LABEL, KIND_LABEL, ci, int, pct, when } from "@/lib/format";
import { SCOPE_LABEL, useScope } from "@/lib/scope";

/** Mẫu số và khoảng tin cậy của một tỉ lệ. Chưa có mẫu thì nói chưa đo, không bao giờ in 0%. */
function Sample({ rate, noun }: { rate: Rate; noun: string }) {
  if (!rate) return <>Chưa có {noun}</>;
  return (
    <>
      <span className="num">{int(rate.x)}/{int(rate.n)}</span> {noun}
      <span className="whitespace-nowrap"> · CI 95% <span className="num">{ci(rate.lo, rate.hi)}</span></span>
    </>
  );
}

/** Ô tỉ lệ trong bảng theo model: số, thanh có dải CI, mẫu số. */
function RateCell({ r, tone }: { r: Rate; tone: "attack" | "defense" | "brand" }) {
  if (!r) return <span className="text-sm text-slate-400">Chưa đo</span>;
  return (
    <div className="min-w-[150px] max-w-[220px]">
      <div className="flex items-baseline justify-between gap-3">
        <span className="num text-base font-medium text-slate-900">{pct(r.p)}</span>
        <span className="num text-xs text-slate-400">{int(r.x)}/{int(r.n)}</span>
      </div>
      <div className="mt-1.5"><RateBar p={r.p} lo={r.lo} hi={r.hi} tone={tone} /></div>
      <div className="num mt-1 text-2xs text-slate-400">CI {ci(r.lo, r.hi)}</div>
    </div>
  );
}

function Count({ label, value }: { label: ReactNode; value: number }) {
  return (
    <span className="whitespace-nowrap">
      {label} <span className="num font-medium text-slate-700">{int(value)}</span>
    </span>
  );
}

export function OverviewPage() {
  const { params, kind, batch } = useScope();
  const q = useQuery({ queryKey: ["overview", params], refetchInterval: 15_000, queryFn: () => api.overview(params) });
  if (q.isLoading) return <Loading rows={8} />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const k = d.kpis;
  const valid = Math.max(0, k.n_runs - k.n_parse_error);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tổng quan"
        description={<>Mức độ an toàn và hữu dụng của agent trên <span className="font-medium text-slate-700">{batch ? "lô đang chọn" : SCOPE_LABEL[kind].toLowerCase()}</span>.</>}
        info="ASR: tỷ lệ tấn công đạt mục tiêu. USR: tỷ lệ hoàn thành tác vụ lành tính. Mẫu số loại run lỗi hạ tầng; khoảng tin cậy Wilson 95%."
        actions={
          batch ? (
            <Link className={buttonClass("secondary")} to={{ pathname: "/runs", search: `?scope=${kind}&batch=${encodeURIComponent(batch)}` }}>
              Điều tra lô <ArrowRight size={14} />
            </Link>
          ) : undefined
        }
      />

      {k.n_attack === 0 && (
        <Callout tone="brand">
          Chưa có run tấn công trong phạm vi này. Đổi phạm vi dữ liệu hoặc mở{" "}
          <Link to="/lab" className="font-medium text-slate-900 underline underline-offset-2">Phòng thí nghiệm</Link>.
        </Callout>
      )}

      <section aria-label="Chỉ số đánh giá chính">
        <Card className="grid grid-cols-1 divide-y divide-slate-200 sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x [&>*:nth-child(n+3)]:sm:border-t [&>*:nth-child(n+3)]:sm:border-slate-200 lg:[&>*:nth-child(n+3)]:border-t-0 [&>*:nth-child(2)]:sm:border-l [&>*:nth-child(4)]:sm:border-l [&>*]:border-slate-200">
          <Metric label="Tấn công thành công · ASR" value={k.asr_off ? pct(k.asr_off.p) : "Chưa đo"} unmeasured={!k.asr_off}>
            Tắt phòng thủ · <Sample rate={k.asr_off} noun="run tấn công" />
          </Metric>
          <Metric label="ASR khi bật phòng thủ" value={k.asr_on ? pct(k.asr_on.p) : "Chưa đo"} unmeasured={!k.asr_on}>
            <Sample rate={k.asr_on} noun="run tấn công" />
          </Metric>
          <Metric label="Hoàn thành tác vụ · USR" value={k.usr_off ? pct(k.usr_off.p) : "Chưa đo"} unmeasured={!k.usr_off}>
            <Sample rate={k.usr_off} noun="câu lành tính" /> · chặn nhầm (FRR) <span className="num font-medium text-slate-700">{k.frr ? pct(k.frr.p) : "chưa đo"}</span>
          </Metric>
          <Metric label="Lượt chạy hợp lệ" value={int(valid)}>
            Trên tổng <span className="num">{int(k.n_runs)}</span> · <span className="num">{int(k.n_parse_error)}</span> lỗi hạ tầng loại khỏi mẫu số
          </Metric>
        </Card>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
          <span>Kết cục bị chặn:</span>
          <Count label={BLOCKED_LABEL.defense} value={k.blocked_by.defense} />
          <Count label={BLOCKED_LABEL.model_refusal} value={k.blocked_by.model_refusal} />
          <Count label={BLOCKED_LABEL.harness} value={k.blocked_by.harness} />
          <span className="ml-auto text-slate-400">Cập nhật {new Date(q.dataUpdatedAt).toLocaleTimeString("vi-VN")}</span>
        </div>
      </section>

      <Card>
        <CardHeader
          title="Kết quả theo model"
          subtitle="ASR thấp hơn là an toàn hơn · USR cao hơn là hữu dụng hơn. Dải nhạt trên thanh là khoảng tin cậy 95%."
        />
        {d.by_target.length ? (
          <div className="overflow-x-auto border-t border-slate-200">
            <table className="table-base">
              <caption className="sr-only">Tỉ lệ theo model kèm mẫu số và khoảng tin cậy. “Chưa đo” nghĩa là chưa có dữ liệu.</caption>
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">ASR · tắt phòng thủ</th>
                  <th scope="col">ASR · bật phòng thủ</th>
                  <th scope="col">USR · hữu dụng nền</th>
                  <th scope="col" className="text-right">Lượt chạy</th>
                </tr>
              </thead>
              <tbody>
                {d.by_target.map((t) => (
                  <tr key={t.target_id}>
                    <th scope="row" className="py-3 text-left align-top font-mono text-sm font-medium text-slate-900">{t.target_id}</th>
                    <td className="py-3 align-top"><RateCell r={t.asr_off} tone="attack" /></td>
                    <td className="py-3 align-top"><RateCell r={t.asr_on} tone="defense" /></td>
                    <td className="py-3 align-top"><RateCell r={t.usr_off} tone="brand" /></td>
                    <td className="num py-3 text-right align-top text-slate-600">{int(t.n_runs)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Chưa có dữ liệu theo model" />
        )}
      </Card>

      <Card>
        <CardHeader
          title="Lô gần đây"
          action={<Link to="/batches" className={buttonClass("ghost", "sm")}>Tất cả lô <ArrowRight size={13} /></Link>}
        />
        {d.recent_batches.length ? (
          <div className="overflow-x-auto border-t border-slate-200">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Lô thực nghiệm</th>
                  <th>Loại</th>
                  <th>Model</th>
                  <th className="text-right">Run</th>
                  <th className="text-right">Kết quả</th>
                  <th className="text-right">Bắt đầu</th>
                </tr>
              </thead>
              <tbody>
                {d.recent_batches.map((b) => (
                  <tr key={b.batch_id}>
                    <td>
                      <Link
                        to={{ pathname: "/runs", search: `?batch=${encodeURIComponent(b.batch_id)}&scope=${b.kind}` }}
                        className="font-mono text-xs font-medium text-slate-900 hover:text-brand-600 hover:underline"
                      >
                        {b.batch_id}
                      </Link>
                    </td>
                    <td><Badge>{KIND_LABEL[b.kind]}</Badge></td>
                    <td className="font-mono text-xs text-slate-600">{b.targets.join(", ")}</td>
                    <td className="num text-right">{int(b.n_runs)}</td>
                    <td className="num whitespace-nowrap text-right text-slate-600">
                      {b.n_attack ? `${int(b.n_success)}/${int(b.n_attack)} thành công` : `${int(b.n_pass)}/${int(b.n_benign)} đạt`}
                    </td>
                    <td className="num whitespace-nowrap text-right text-xs text-slate-500">{when(b.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Chưa có lô thực nghiệm" />
        )}
      </Card>
    </div>
  );
}
