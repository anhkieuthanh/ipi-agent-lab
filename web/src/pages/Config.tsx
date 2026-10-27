import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowRight,
  Boxes,
  CircleAlert,
  CircleCheck,
  Cpu,
  FileCode2,
  FlaskConical,
  Gavel,
  Lock,
  Save,
  ShieldCheck,
  Trash2,
  WandSparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, Callout, Card, CardHeader, ErrorBox, Loading, Mono, PageHeader } from "@/components/ui";
import { type ConfigSummary, type SandboxLimits, type SandboxModel, api } from "@/lib/api";
import { DEFENSE_LABEL, TECHNIQUE_LABEL, usd } from "@/lib/format";
import { DEFENSE_ICON } from "@/lib/icons";
import { useSandboxModel } from "@/lib/sandbox";

type Model = ConfigSummary["targets"][number];

const AUX_ICON: Record<string, typeof Gavel> = { judge: Gavel, attacker: WandSparkles };

function channelLabel(provider: string) {
  return provider === "anthropic" ? "API trực tiếp" : "Gateway";
}

function Price({ m }: { m: Model }) {
  return (
    <span className="num">
      {usd(m.pricing?.input, 2)} / {usd(m.pricing?.output, 2)}
    </span>
  );
}

function TargetTile({ m }: { m: Model }) {
  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-slate-50/40 p-4">
      <div className="flex items-center justify-between">
        <Badge tone="brand" className="font-mono">
          {m.id}
        </Badge>
        <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-slate-500">
          <Lock size={12} /> Đã khóa
        </span>
      </div>
      <Mono className="mt-3 block truncate text-[15px] font-semibold text-slate-900">{m.model_id}</Mono>
      <div className="mt-0.5 text-[12.5px] text-slate-500">{m.label}</div>
      <dl className="mt-4 space-y-1 border-t border-slate-200/70 pt-3 text-[12px]">
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Kênh gọi</dt>
          <dd className="text-slate-700">{channelLabel(m.provider)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Giá vào / ra</dt>
          <dd className="whitespace-nowrap text-slate-700">
            <Price m={m} />
          </dd>
        </div>
      </dl>
    </div>
  );
}

function ModelsCard({ d, tag }: { d: ConfigSummary; tag?: string }) {
  return (
    <Card>
      <CardHeader
        title="Mô hình đích"
        subtitle={
          <>
            Bộ model đã chốt theo phụ lục GVHD, khóa bằng <Mono>{tag ?? "v-models-1.0"}</Mono>. Đơn giá USD/Mtok (vào / ra).
          </>
        }
        icon={<Cpu size={16} />}
      />
      <div className="grid grid-cols-1 gap-3 p-5 md:grid-cols-3">
        {d.targets.map((m) => (
          <TargetTile key={m.id} m={m} />
        ))}
      </div>
      <div className="border-t border-slate-100 px-5 py-3">
        <div className="label mb-2">Model phụ trợ — không phải model đích</div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {d.aux_models.map((m) => {
            const Icon = AUX_ICON[m.id] ?? Cpu;
            return (
              <div key={m.id} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white text-slate-500 ring-1 ring-slate-200">
                  <Icon size={14} />
                </span>
                <div className="min-w-0 flex-1">
                  <Mono className="block truncate font-medium text-slate-800">{m.model_id}</Mono>
                  <div className="truncate text-[12px] text-slate-500">
                    {m.label} · {channelLabel(m.provider)}
                  </div>
                </div>
                <span className="shrink-0 whitespace-nowrap text-[12px] text-slate-600">
                  <Price m={m} />
                </span>
              </div>
            );
          })}
        </div>
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

function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="label">{label}</span>
      {children}
      {error ? (
        <span className="text-[12px] text-attack-600">{error}</span>
      ) : (
        hint && <span className="text-[12px] text-slate-500">{hint}</span>
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
    <Card className="overflow-hidden">
      <CardHeader
        title={limits.label ?? "Model thử ngoài bộ đo"}
        subtitle="Thay model đích cho lượt demo ở Phòng thí nghiệm — không đổi A1–A3."
        icon={<FlaskConical size={16} />}
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
      <div className="space-y-5 p-5">
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
                onClick={() => setDraft({ ...draft, channel: c.id })}
                className={clsx(
                  "flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition",
                  draft.channel === c.id
                    ? "border-brand-500 bg-brand-50/60 ring-2 ring-brand-100"
                    : "border-slate-200 hover:border-slate-300 hover:bg-slate-50",
                )}
              >
                <span
                  className={clsx(
                    "mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2",
                    draft.channel === c.id ? "border-brand-600 bg-brand-600 shadow-[inset_0_0_0_2px_white]" : "border-slate-300",
                  )}
                />
                <span className="min-w-0">
                  <span className="block text-[13.5px] font-medium text-slate-800">{c.label}</span>
                  <span
                    className={clsx(
                      "mt-0.5 inline-flex items-center gap-1 text-[12px]",
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
            className={clsx("input font-mono", show("model_id") && "border-attack-400")}
            value={draft.model_id}
            onChange={set("model_id")}
            placeholder="tên model"
            spellCheck={false}
            autoComplete="off"
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Giá vào (USD/Mtok)" error={show("price_in")}>
            <input className="input num" inputMode="decimal" value={draft.price_in} onChange={set("price_in")} placeholder="0.50" />
          </Field>
          <Field label="Giá ra (USD/Mtok)" error={show("price_out")}>
            <input className="input num" inputMode="decimal" value={draft.price_out} onChange={set("price_out")} placeholder="1.50" />
          </Field>
        </div>
        <p className="-mt-2 text-[12px] text-slate-500">
          Đơn giá dùng để canh ngân sách lượt demo (BudgetGuard) — nhập theo bảng giá của nhà cung cấp.
        </p>

        {channel && !channel.ready && (
          <Callout tone="warn">Kênh này chưa có khóa: lượt demo sẽ báo lỗi cho tới khi bạn thêm biến vào .env.</Callout>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
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
              className="ml-auto inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-700 hover:text-brand-800"
            >
              Chạy ở Phòng thí nghiệm <ArrowRight size={14} />
            </Link>
          )}
        </div>
      </div>
    </Card>
  );
}

function DefenseTile({ code }: { code: string }) {
  const Icon = DEFENSE_ICON[code] ?? ShieldCheck;
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-defense-50 text-defense-600">
      <Icon size={15} />
    </span>
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
        info="Hợp đồng thực nghiệm đã chốt, chỉ đọc — thay đổi đi qua config/ và tài liệu. Riêng model thử ngoài bộ đo đặt được ở đây, chỉ cho demo."
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <div className="xl:col-span-5">
          <ModelsCard d={d} tag={meta.data?.model_tag} />
        </div>
        <div className="xl:col-span-2">
          <SandboxCard limits={d.sandbox} />
        </div>

        <div className="flex flex-col gap-6 xl:col-span-3">
          <Card>
            <CardHeader
              title="Cơ chế phòng thủ"
              subtitle={`${d.presets.length} preset · tham số ở config/defenses.yaml`}
              icon={<ShieldCheck size={16} />}
            />
            <div className="divide-y divide-slate-100">
              {d.presets
                .find((p) => p.name === "all")
                ?.codes.map((code) => (
                  <div key={code} className="flex items-center gap-3 px-5 py-3">
                    <DefenseTile code={code} />
                    <Badge tone="defense" className="font-mono">
                      {code}
                    </Badge>
                    <span className="text-[13.5px] text-slate-700">{DEFENSE_LABEL[code]}</span>
                  </div>
                ))}
            </div>
            <div className="border-t border-slate-100 px-5 py-3">
              <Link to="/defense" className="inline-flex items-center gap-1.5 text-[13px] font-medium text-brand-700 hover:text-brand-800">
                Xem tham số ở trang Phòng thủ <ArrowRight size={14} />
              </Link>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Kho payload"
              subtitle={
                <>
                  <b className="num text-slate-700">{d.payloads.total}</b> payload · khóa bằng <Mono>{meta.data?.attack_tag}</Mono>
                </>
              }
              icon={<FileCode2 size={16} />}
            />
            <div className="grid grid-cols-2 gap-2 p-5 sm:grid-cols-4">
              {Object.entries(d.payloads.by_technique).map(([t, n]) => (
                <div key={t} className="rounded-lg bg-slate-50 px-3 py-2.5">
                  <div className="flex items-baseline justify-between">
                    <span className="font-mono text-[12.5px] font-semibold text-slate-700">{t}</span>
                    <span className="num text-[15px] font-semibold text-slate-900">{n}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[11.5px] text-slate-500" title={TECHNIQUE_LABEL[t]}>
                    {TECHNIQUE_LABEL[t] ?? ""}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <Card className="xl:col-span-5">
          <CardHeader title="Tác vụ chở" subtitle="Tác vụ nhân viên giao cho agent; payload cài vào dữ liệu tác vụ này đọc." icon={<Boxes size={16} />} />
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Mã</th>
                  <th>Tác vụ</th>
                  <th>Kênh tiêm</th>
                  <th>Tool được phép</th>
                </tr>
              </thead>
              <tbody>
                {d.carriers.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Mono className="font-medium">{c.id}</Mono>
                    </td>
                    <td className="max-w-[420px] text-[13px] text-slate-600">
                      <div className="truncate" title={c.query}>
                        {c.name || c.query}
                      </div>
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {c.channels?.map((k) => (
                          <Badge key={k} tone="payload" className="font-mono">
                            {k}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {c.allowed_tools?.map((t) => (
                          <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
