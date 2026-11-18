import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge, Callout, Card, Empty, ErrorBox, Loading, PageHeader, Question, RateBar, Reading, buttonClass } from "@/components/ui";
import { api, type Rate } from "@/lib/api";
import { BLOCKED_LABEL, KIND_LABEL, ci, int, pct, when } from "@/lib/format";
import { SCOPE_LABEL, useScope } from "@/lib/scope";

/** Mẫu số và khoảng tin cậy của một tỉ lệ. Chưa có mẫu thì nói chưa đo, không bao giờ in 0%. */
function Sample({ rate, noun }: { rate: Rate; noun: string }) {
  if (!rate) return <p className="text-xs text-muted">Chưa có {noun}.</p>;
  return (
    <p className="text-xs text-slate-600">
      Gộp: <span className="num font-mono text-slate-900">{int(rate.x)}/{int(rate.n)}</span> {noun}, khoảng tin cậy 95%{" "}
      <span className="num font-mono text-slate-900">{ci(rate.lo, rate.hi)}</span>.
    </p>
  );
}

/** Ô tỉ lệ trong bảng theo model: số, thanh có dải CI, mẫu số. */
function RateCell({ r, tone, wide }: { r: Rate; tone: "attack" | "defense" | "brand"; wide?: boolean }) {
  if (!r) return <span className="text-sm text-muted">Chưa đo</span>;
  return (
    <div className={clsx("min-w-[170px]", wide ? "max-w-[480px]" : "max-w-[260px]")}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="reading text-xl">{pct(r.p)}</span>
        <span className="num font-mono text-xs text-muted">{int(r.x)}/{int(r.n)}</span>
      </div>
      <div className="mt-1.5"><RateBar p={r.p} lo={r.lo} hi={r.hi} tone={tone} /></div>
      <div className="num mt-1 font-mono text-2xs text-muted">CI {ci(r.lo, r.hi)}</div>
    </div>
  );
}

function Count({ label, value }: { label: ReactNode; value: number }) {
  return (
    <span className="whitespace-nowrap">
      {label} <span className="num font-mono font-medium text-slate-900">{int(value)}</span>
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

  const models = d.by_target;
  return (
    <div>
      <PageHeader
        title="Tổng quan"
        description={<>Ba câu hỏi về agent trên <span className="font-medium text-slate-900">{batch ? "lô đang chọn" : SCOPE_LABEL[kind].toLowerCase()}</span>: tấn công lọt bao nhiêu, phòng thủ kéo xuống bao nhiêu, agent còn làm được việc không.</>}
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
        <div className="mb-6">
          <Callout tone="brand">
            Chưa có run tấn công trong phạm vi này. Đổi phạm vi dữ liệu hoặc mở{" "}
            <Link to="/lab" className="font-medium text-slate-900 underline underline-offset-2">Phòng thí nghiệm</Link>.
          </Callout>
        </div>
      )}

      <Question
        title="Tấn công lọt qua bao nhiêu, và phòng thủ kéo xuống được bao nhiêu?"
        answer={
          <>
            <Reading label="Tắt phòng thủ (ASR)" rate={k.asr_off} tone="attack" />
            <Reading label="Bật phòng thủ" rate={k.asr_on} tone="attack" />
          </>
        }
        note={
          <>
            Tấn công thành công trên số run tấn công hợp lệ. Bị chặn:{" "}
            <Count label={BLOCKED_LABEL.defense} value={k.blocked_by.defense} />,{" "}
            <Count label={BLOCKED_LABEL.model_refusal.toLowerCase()} value={k.blocked_by.model_refusal} />,{" "}
            <Count label={BLOCKED_LABEL.harness.toLowerCase()} value={k.blocked_by.harness} />.
          </>
        }
      >
        <Card className="overflow-hidden">
          {models.length ? (
            <div className="overflow-x-auto">
              <table className="table-base">
                <caption className="sr-only">Tỉ lệ tấn công thành công theo model, kèm mẫu số và khoảng tin cậy. “Chưa đo” nghĩa là chưa có dữ liệu.</caption>
                <thead>
                  <tr>
                    <th scope="col">Model</th>
                    <th scope="col">Tắt phòng thủ</th>
                    <th scope="col">Bật phòng thủ</th>
                    <th scope="col" className="text-right">Lượt chạy</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((t) => (
                    <tr key={t.target_id}>
                      <th scope="row" className="py-4 text-left align-top font-mono text-sm font-medium text-slate-900">{t.target_id}</th>
                      <td className="py-4 align-top"><RateCell r={t.asr_off} tone="attack" /></td>
                      <td className="py-4 align-top"><RateCell r={t.asr_on} tone="defense" /></td>
                      <td className="num py-4 text-right align-top text-slate-700">{int(t.n_runs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="Chưa có dữ liệu theo model" />
          )}
        </Card>
        <Sample rate={k.asr_off} noun="run tấn công, tắt phòng thủ" />
      </Question>

      <Question
        title="Agent còn làm được việc lành tính không?"
        answer={
          <>
            <Reading label="Hoàn thành tác vụ (USR)" rate={k.usr_off} />
            <Reading label="Chặn nhầm (FRR)" rate={k.frr} size="md" />
          </>
        }
        note="Phòng thủ tốt phải giữ USR cao và FRR thấp: chặn tấn công mà không chặn việc thật của nhân viên."
      >
        <Card className="overflow-hidden">
          {models.length ? (
            <div className="overflow-x-auto">
              <table className="table-base">
                <caption className="sr-only">Tỉ lệ hoàn thành tác vụ lành tính theo model.</caption>
                <thead>
                  <tr>
                    <th scope="col">Model</th>
                    <th scope="col">Hữu dụng nền (USR)</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((t) => (
                    <tr key={t.target_id}>
                      <th scope="row" className="py-4 text-left align-top font-mono text-sm font-medium text-slate-900">{t.target_id}</th>
                      <td className="py-4 align-top"><RateCell r={t.usr_off} tone="brand" wide /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="Chưa có dữ liệu theo model" />
          )}
        </Card>
        <Sample rate={k.usr_off} noun="câu lành tính" />
      </Question>

      <Question
        title="Số liệu này lấy từ đâu?"
        answer={
          <div>
            <div className="text-sm text-slate-600">Lượt chạy hợp lệ</div>
            <div className="reading mt-1.5 text-4xl">{int(valid)}</div>
          </div>
        }
        note={
          <>
            Trên tổng <span className="num font-mono text-slate-900">{int(k.n_runs)}</span> lượt;{" "}
            <span className="num font-mono text-slate-900">{int(k.n_parse_error)}</span> lỗi hạ tầng bị loại khỏi mẫu số.
          </>
        }
        aside={<Link to="/batches" className={buttonClass("secondary", "sm")}>Tất cả lô <ArrowRight size={13} /></Link>}
      >
        <Card className="overflow-hidden">
          {d.recent_batches.length ? (
            <div className="overflow-x-auto">
              <table className="table-base">
                <caption className="sr-only">Các lô thực nghiệm gần đây.</caption>
                <thead>
                  <tr>
                    <th>Lô gần đây</th>
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
                          className="font-mono text-xs font-medium text-slate-900 hover:text-brand-700 hover:underline"
                        >
                          {b.batch_id}
                        </Link>
                      </td>
                      <td><Badge tone={b.kind === "experiment" ? "canary" : b.kind === "demo" ? "brand" : "neutral"}>{KIND_LABEL[b.kind]}</Badge></td>
                      <td className="font-mono text-xs text-slate-700">{b.targets.join(", ")}</td>
                      <td className="num text-right">{int(b.n_runs)}</td>
                      <td className="num whitespace-nowrap text-right text-slate-700">
                        {b.n_attack ? `${int(b.n_success)}/${int(b.n_attack)} thành công` : `${int(b.n_pass)}/${int(b.n_benign)} đạt`}
                      </td>
                      <td className="num whitespace-nowrap text-right text-xs text-slate-600">{when(b.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="Chưa có lô thực nghiệm" />
          )}
        </Card>
      </Question>
    </div>
  );
}
