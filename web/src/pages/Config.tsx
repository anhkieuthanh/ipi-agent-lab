import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, CircleAlert, CircleCheck, Lock, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, Callout, Card, CardHeader, ErrorBox, InfoDot, Loading, Mono, PageHeader, Question } from "@/components/ui";
import { type ConfigSummary, type SandboxLimits, type SandboxModel, api } from "@/lib/api";
import { DEFENSE_LABEL, TECHNIQUE_LABEL, usd } from "@/lib/format";
import { useSandboxModel } from "@/lib/sandbox";

type Model = ConfigSummary["targets"][number];

function channelLabel(provider: string) {
  return provider === "anthropic" ? "API trực tiếp" : "Gateway";
}

/** Nhãn phiên bản đã pin — luôn hiện ở góc tiêu đề khối, chữ mono. */
function PinTag({ tag }: { tag?: string }) {
  if (!tag) return null;
  return (
    <span className="inline-flex h-6 items-center gap-1.5 rounded-md border border-slate-200 px-2 font-mono text-xs font-medium text-slate-800">
      <Lock size={12} className="text-muted" aria-hidden="true" />
      {tag}
    </span>
  );
}

function PriceCells({ m }: { m: Model }) {
  return (
    <>
      <td className="num whitespace-nowrap text-right text-slate-700">{usd(m.pricing?.input, 2)}</td>
      <td className="num whitespace-nowrap text-right text-slate-700">{usd(m.pricing?.output, 2)}</td>
    </>
  );
}

function ModelsCard({ d, tag }: { d: ConfigSummary; tag?: string }) {
  const pin = tag ?? "—";
  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Mô hình đích"
        subtitle={
          <>
            Bộ model đã chốt theo phụ lục GVHD, khóa bằng <Mono>{pin}</Mono>. Đơn giá USD/Mtok (vào / ra).
          </>
        }
        action={<PinTag tag={pin} />}
      />
      <div className="max-w-full overflow-x-auto border-t border-slate-100">
        <table className="table-base">
          <thead>
            <tr>
              <th>Mã</th>
              <th>Model ID</th>
              <th>Kênh gọi</th>
              <th className="text-right">Giá vào</th>
              <th className="text-right">Giá ra</th>
              <th>Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {d.targets.map((m) => (
              <tr key={m.id}>
                <td>
                  <Badge tone="brand" className="font-mono">
                    {m.id}
                  </Badge>
                </td>
                <td>
                  <Mono className="whitespace-nowrap font-medium text-slate-900">{m.model_id}</Mono>
                </td>
                <td className="whitespace-nowrap text-slate-700">{channelLabel(m.provider)}</td>
                <PriceCells m={m} />
                <td>
                  <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs text-slate-500">
                    <Lock size={12} aria-hidden="true" /> Đã khóa
                  </span>
                </td>
              </tr>
            ))}
            <tr>
              <th colSpan={6} scope="colgroup" className="bg-slate-50 text-xs font-medium text-slate-500">
                Model phụ trợ, không phải model đích
              </th>
            </tr>
            {d.aux_models.map((m) => (
              <tr key={m.id}>
                <td>
                  <Badge className="font-mono">{m.id}</Badge>
                </td>
                <td>
                  <Mono className="block whitespace-nowrap font-medium text-slate-900">{m.model_id}</Mono>
                  <div className="text-xs text-slate-500">{m.label}</div>
                </td>
                <td className="whitespace-nowrap text-slate-700">{channelLabel(m.provider)}</td>
                <PriceCells m={m} />
                <td>
                  <span className="text-xs text-muted">Không có</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

type Draft = { channel: string; model_id: string; price_in: string; price_out: string };

function toDraft(m: SandboxModel | null, limits: SandboxLimits): Draft {
  if (m) return { channel: m.channel, model_id: m.model_id, price_in: String(m.price_in), price_out: String(m.price_out) };
  const first = limits.channels.find((c) => c.ready) ?? limits.channels[0];
  return { channel: first?.id ?? "", model_id: "", price_in: "", price_out: "" };
}

/** Kiểm như API (`_sandbox` ở src/console/app.py) để báo lỗi ngay khi gõ. */
function validate(d: Draft, limits: SandboxLimits): { errors: Partial<Record<keyof Draft, string>>; model: SandboxModel | null } {
  const errors: Partial<Record<keyof Draft, string>> = {};
  if (!limits.channels.some((c) => c.id === d.channel)) errors.channel = "Chọn kênh gọi.";
  const id = d.model_id.trim();
  if (!id) errors.model_id = "Nhập model_id.";
  else if (!new RegExp(limits.model_id_pattern).test(id))
    errors.model_id = "Chỉ chữ, số và . _ : / @ -; tối đa 80 ký tự, không dấu cách.";
  const price = (s: string) => (s.trim() === "" ? NaN : Number(s));
  const pin = price(d.price_in);
  const pout = price(d.price_out);
  const bad = (v: number) => !Number.isFinite(v) || v < 0 || v > limits.max_price;
  const msg = `Số từ 0 đến ${limits.max_price}.`;
  if (bad(pin)) errors.price_in = msg;
  if (bad(pout)) errors.price_out = msg;
  const ok = Object.keys(errors).length === 0;
  return { errors, model: ok ? { channel: d.channel, model_id: id, price_in: pin, price_out: pout } : null };
}

function Field({ label, error, hint, children }: { label: React.ReactNode; error?: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="label">{label}</span>
      {children}
      {error ? (
        <span className="text-xs text-attack-600">{error}</span>
      ) : (
        hint && <span className="text-xs text-slate-500">{hint}</span>
      )}
    </label>
  );
}

function SandboxCard({ limits }: { limits: SandboxLimits }) {
  const [saved, setSaved] = useSandboxModel();
  const [draft, setDraft] = useState<Draft>(() => toDraft(saved, limits));
  const [touched, setTouched] = useState(false);
  useEffect(() => setDraft(toDraft(saved, limits)), [saved, limits]);

  const { errors, model } = validate(draft, limits);
  const show = (k: keyof Draft) => (touched ? errors[k] : undefined);
  const channel = limits.channels.find((c) => c.id === draft.channel);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(saved, limits));
  const set = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [k]: e.target.value });

  return (
    <Card>
      <CardHeader
        title={limits.label ?? "Model thử ngoài bộ đo"}
        subtitle="Thay model đích cho lượt demo ở Phòng thí nghiệm, không đổi A1–A3."
        action={
          saved ? (
            <Badge tone="warn" dot>
              Đang dùng
            </Badge>
          ) : (
            <Badge>Chưa đặt</Badge>
          )
        }
      />
      <div className="space-y-4 border-t border-slate-100 p-4">
        <Callout tone="warn" title="Chỉ dùng cho demo, không vào số liệu báo cáo">
          Run ghi <Mono>target_id = sandbox</Mono>, lô tiền tố <Mono>demo-sandbox-</Mono> trong store demo riêng. Không ghi gì
          vào <Mono>config/</Mono> hay <Mono>.env</Mono>; model chỉ lưu trong trình duyệt này.
        </Callout>

        <div>
          <span className="label">Kênh gọi</span>
          <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {limits.channels.map((c) => (
              <button
                key={c.id}
                type="button"
                aria-pressed={draft.channel === c.id}
                onClick={() => setDraft({ ...draft, channel: c.id })}
                className={clsx(
                  "flex items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors",
                  draft.channel === c.id ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:border-slate-300 hover:bg-slate-50",
                )}
              >
                <span
                  className={clsx(
                    "mt-1 h-3 w-3 shrink-0 rounded-full border",
                    draft.channel === c.id ? "border-brand-500 bg-brand-500 ring-2 ring-inset ring-surface" : "border-slate-300",
                  )}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-slate-900">{c.label}</span>
                  <span
                    className={clsx(
                      "mt-0.5 inline-flex items-center gap-1 text-xs",
                      c.ready ? "text-defense-600" : "text-amber-700",
                    )}
                  >
                    {c.ready ? <CircleCheck size={12} /> : <CircleAlert size={12} />}
                    {c.ready ? "Đã có khóa trong .env" : `Thiếu ${c.env.join(", ")} trong .env`}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <Field label="Model ID" error={show("model_id")} hint="Đúng tên model mà kênh gọi chấp nhận, vd qwen-4-plus.">
          <input
            className={clsx("input font-mono", show("model_id") && "border-attack-500")}
            value={draft.model_id}
            onChange={set("model_id")}
            placeholder="tên model"
            spellCheck={false}
            autoComplete="off"
          />
        </Field>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Giá vào (USD/Mtok)" error={show("price_in")}>
            <input className="input num" inputMode="decimal" value={draft.price_in} onChange={set("price_in")} placeholder="0.50" />
          </Field>
          <Field label={<span className="inline-flex items-center gap-1">Giá ra (USD/Mtok)<InfoDot>Đơn giá dùng để canh ngân sách lượt demo (BudgetGuard), nhập theo bảng giá của nhà cung cấp.</InfoDot></span>} error={show("price_out")}>
            <input className="input num" inputMode="decimal" value={draft.price_out} onChange={set("price_out")} placeholder="1.50" />
          </Field>
        </div>

        {channel && !channel.ready && (
          <Callout tone="warn">Kênh này chưa có khóa: lượt demo sẽ báo lỗi cho tới khi bạn thêm biến vào .env.</Callout>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <Button
            variant="primary"
            icon={<Save size={15} />}
            disabled={!dirty}
            onClick={() => {
              setTouched(true);
              if (model) setSaved(model);
            }}
          >
            {saved ? "Lưu thay đổi" : "Lưu model thử"}
          </Button>
          {saved && (
            <Button variant="ghost" icon={<Trash2 size={15} />} onClick={() => setSaved(null)}>
              Bỏ model thử
            </Button>
          )}
          {saved && !dirty && (
            <Link
              to="/lab"
              className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline"
            >
              Chạy ở Phòng thí nghiệm <ArrowRight size={14} />
            </Link>
          )}
        </div>
      </div>
    </Card>
  );
}

export function ConfigPage() {
  const q = useQuery({ queryKey: ["config"], queryFn: api.config });
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;

  return (
    <>
      <PageHeader
        title="Cấu hình"
        description="Hợp đồng thực nghiệm đã chốt, chỉ đọc. Thay đổi đi qua config/ và tài liệu. Riêng model thử ngoài bộ đo đặt được ở đây, chỉ cho demo."
      />

      <div>
        <Question title="Model đích" note="Ba model A1–A3 đã ghim phiên bản; mọi số liệu báo cáo đo trên ba model này.">
          <ModelsCard d={d} tag={meta.data?.model_tag} />
        </Question>

        <Question title="Model thử cho demo" note="Thay model đích cho lượt demo ở trang Thí nghiệm. Lượt dùng model thử không vào số liệu báo cáo.">
          <SandboxCard limits={d.sandbox} />
        </Question>

        <Question title="Phòng thủ và payload" note="Tham số phòng thủ nằm ở config/defenses.yaml; kho payload khóa theo phiên bản bộ tấn công.">
          <div className="grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader
                title="Cơ chế phòng thủ"
                subtitle={
                  <>
                    <span className="num">{d.presets.length}</span> preset · tham số ở <Mono>config/defenses.yaml</Mono>
                  </>
                }
                action={
                  <Link to="/defense" className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
                    Xem tham số ở trang Phòng thủ <ArrowRight size={12} />
                  </Link>
                }
              />
              <ul className="divide-y divide-slate-100 border-t border-slate-100">
                {d.presets
                  .find((p) => p.name === "all")
                  ?.codes.map((code) => (
                    <li key={code} className="flex items-center gap-3 px-4 py-2">
                      <span className="w-12 shrink-0">
                        <Badge tone="defense" className="font-mono">
                          {code}
                        </Badge>
                      </span>
                      <span className="text-sm text-slate-800">{DEFENSE_LABEL[code]}</span>
                    </li>
                  ))}
              </ul>
            </Card>

            <Card className="overflow-hidden">
              <CardHeader
                title="Kho payload"
                subtitle={
                  <>
                    <b className="num font-semibold text-slate-800">{d.payloads.total}</b> payload · khóa bằng <Mono>{meta.data?.attack_tag}</Mono>
                  </>
                }
                action={<PinTag tag={meta.data?.attack_tag} />}
              />
              <div className="max-w-full overflow-x-auto border-t border-slate-100">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th>Kỹ thuật</th>
                      <th>Tên</th>
                      <th className="text-right">Số payload</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(d.payloads.by_technique).map(([t, n]) => (
                      <tr key={t}>
                        <td className="w-20">
                          <Mono className="font-medium text-slate-800">{t}</Mono>
                        </td>
                        <td className="text-slate-700">{TECHNIQUE_LABEL[t] ?? ""}</td>
                        <td className="num text-right font-medium text-slate-900">{n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </Question>
      </div>
    </>
  );
}
