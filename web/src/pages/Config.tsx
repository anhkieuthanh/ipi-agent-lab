import { useQuery } from "@tanstack/react-query";
import { Boxes, Cpu, FileCode2, ShieldCheck } from "lucide-react";

import { Badge, Card, CardHeader, ErrorBox, Loading, Mono, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { DEFENSE_LABEL, TECHNIQUE_LABEL, usd } from "@/lib/format";

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
        description="Hợp đồng thực nghiệm đã chốt: bộ model, cơ chế phòng thủ, kho payload, tác vụ chở. Chỉ đọc — mọi thay đổi đi qua config/ và tài liệu, không sửa ở đây."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Mô hình đích"
            subtitle={<>Khóa bằng <Mono>{meta.data?.model_tag}</Mono></>}
            icon={<Cpu size={16} />}
          />
          <table className="table-base">
            <thead>
              <tr>
                <th>Mã</th>
                <th>Model</th>
                <th>Kênh gọi</th>
                <th className="text-right">Giá (vào/ra, USD/Mtok)</th>
              </tr>
            </thead>
            <tbody>
              {[...d.targets, ...d.aux_models].map((t) => (
                <tr key={t.id}>
                  <td>
                    <Badge tone={t.id.startsWith("A") ? "brand" : "neutral"}>{t.id}</Badge>
                  </td>
                  <td>
                    <Mono className="font-medium text-slate-800">{t.model_id}</Mono>
                    <div className="text-[12px] text-slate-500">{t.label}</div>
                  </td>
                  <td className="text-[13px] text-slate-600">{t.provider === "anthropic" ? "API trực tiếp" : "Gateway"}</td>
                  <td className="num text-right text-[13px] text-slate-600">
                    {usd(t.pricing?.input, 2)} / {usd(t.pricing?.output, 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card>
          <CardHeader title="Cơ chế phòng thủ" subtitle="Bốn cơ chế D1–D4" icon={<ShieldCheck size={16} />} />
          <div className="divide-y divide-slate-100">
            {d.presets
              .find((p) => p.name === "all")
              ?.codes.map((code) => (
                <div key={code} className="flex items-center gap-3 px-5 py-3">
                  <Badge tone="defense">{code}</Badge>
                  <span className="text-[13.5px] text-slate-700">{DEFENSE_LABEL[code]}</span>
                </div>
              ))}
            <div className="px-5 py-3 text-[12.5px] text-slate-500">
              {d.presets.length} preset cấu hình · xem tham số ở trang Phòng thủ
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Kho payload"
            subtitle={<>Khóa bằng <Mono>{meta.data?.attack_tag}</Mono></>}
            icon={<FileCode2 size={16} />}
          />
          <div className="p-5">
            <div className="mb-3 text-[13px] text-slate-600">
              Tổng <b className="num text-slate-900">{d.payloads.total}</b> payload, theo kỹ thuật:
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(d.payloads.by_technique).map(([t, n]) => (
                <div key={t} className="rounded-lg bg-slate-50 px-3 py-2">
                  <div className="text-[12px] font-semibold text-slate-700">
                    {t} · <span className="num">{n}</span>
                  </div>
                  <div className="text-[11px] text-slate-500">{TECHNIQUE_LABEL[t] ?? ""}</div>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Tác vụ chở" subtitle="Việc nghiệp vụ thật mà agent đang làm khi bị tấn công" icon={<Boxes size={16} />} />
          <table className="table-base">
            <thead>
              <tr>
                <th>Mã</th>
                <th>Tác vụ</th>
                <th>Tool được phép</th>
              </tr>
            </thead>
            <tbody>
              {d.carriers.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Mono className="font-medium">{c.id}</Mono>
                  </td>
                  <td className="max-w-[320px] text-[13px] text-slate-600">
                    <div className="truncate" title={c.query}>
                      {c.name || c.query}
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
        </Card>
      </div>
    </>
  );
}
