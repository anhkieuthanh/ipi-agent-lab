import { useQuery } from "@tanstack/react-query";
import { Database, FileCode2, Wrench, X } from "lucide-react";
import { useEffect } from "react";

import { api } from "@/lib/api";
import { Badge, ErrorBox, Loading, Mono } from "@/components/ui";

/** TS1–TS3: tài sản cần bảo vệ. Click thẻ ở trang Sơ đồ hệ thống mở panel này. */
export type AssetCode = "TS1" | "TS2" | "TS3";

const META: Record<AssetCode, { title: string; sub: string; icon: typeof Database }> = {
  TS1: { title: "System prompt", sub: "Quy tắc nghiệp vụ và danh sách tool đưa vào mỗi run", icon: FileCode2 },
  TS2: { title: "customers.db", sub: "Dữ liệu khách hàng mô phỏng — nguồn kẻ tấn công muốn rò", icon: Database },
  TS3: { title: "Quyền gọi tool", sub: "Năm tool và quyền hành động của agent", icon: Wrench },
};

function highlightCanary(text: string, placeholder: string) {
  const parts = text.split(placeholder);
  return parts.map((part, i) => (
    <span key={i}>
      {part}
      {i < parts.length - 1 && (
        <mark className="rounded bg-amber-100 px-1 font-mono text-[12px] text-amber-800">{placeholder}</mark>
      )}
    </span>
  ));
}

function SystemPromptView() {
  const q = useQuery({ queryKey: ["asset", "system_prompt"], queryFn: api.assetSystemPrompt });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-slate-500">
        <Badge tone="neutral" className="font-mono">biến thể: {d.variant}</Badge>
        <span>{d.chars} ký tự</span>
        <Mono className="text-[11px]">hash {d.template_hash.slice(0, 12)}</Mono>
      </div>
      <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50 p-4 text-[12.5px] leading-relaxed text-slate-800">
        {highlightCanary(d.text, d.canary_placeholder)}
      </pre>
      <p className="text-[12px] text-slate-500">
        Vệt vàng <Mono className="text-[11px]">{d.canary_placeholder}</Mono> là nơi gieo canary TS1 lúc chạy —
        ở đây giữ placeholder, không lộ canary thật.
      </p>
    </div>
  );
}

function CustomersView() {
  const q = useQuery({ queryKey: ["asset", "customers"], queryFn: () => api.assetCustomers() });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const cols = d.columns.map((c) => c.name);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-slate-500">
        <Badge tone="neutral" className="font-mono">{d.table}</Badge>
        <span>{d.total} bản ghi</span>
        <span>· {d.seeded_rows} bản ghi mồi canary</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="table-base min-w-max">
          <thead>
            <tr>
              {d.columns.map((c) => (
                <th key={c.name} className="whitespace-nowrap">
                  {c.name}
                  <span className="ml-1 font-mono text-[10px] font-normal text-slate-400">{c.type}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.rows.map((r, i) => (
              <tr key={i} className={r._seeded ? "bg-amber-50" : undefined}>
                {cols.map((c) => (
                  <td key={c} className="whitespace-nowrap text-[12px] text-slate-700">
                    {String(r[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[12px] text-slate-500">
        {d.note} Hàng tô vàng là bản ghi mồi (id {d.canary_row_id}); cột <Mono className="text-[11px]">canary_note</Mono> đã ẩn.
        Hiển thị {d.rows.length}/{d.total} bản ghi đầu.
      </p>
    </div>
  );
}

function ToolsView() {
  const q = useQuery({ queryKey: ["asset", "tools"], queryFn: api.assetTools });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        {d.tools.map((t) => (
          <div key={t.name} className="rounded-lg border border-slate-200 p-3">
            <div className="flex items-center gap-2">
              <Mono className="font-semibold text-slate-800">{t.name}</Mono>
              {t.code && <Badge tone="neutral">{t.code}</Badge>}
              <Badge tone={t.side_effect ? "attack" : "defense"}>{t.kind}</Badge>
            </div>
            <p className="mt-1 text-[12.5px] text-slate-600">{t.description}</p>
            {t.args.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {t.args.map((a) => (
                  <span key={a.name} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                    {a.name}
                    {a.required && <span className="text-attack-600">*</span>}
                    <span className="text-slate-400">:{a.type}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div>
        <div className="mb-2 text-[13px] font-semibold text-slate-700">Tool được phép theo tác vụ chở</div>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="table-base min-w-max">
            <thead>
              <tr>
                <th>Tác vụ</th>
                {d.tools.map((t) => (
                  <th key={t.name} className="text-center font-mono text-[11px]">{t.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.carriers.map((c) => (
                <tr key={c.id}>
                  <td className="whitespace-nowrap"><Mono className="font-medium">{c.id}</Mono></td>
                  {d.tools.map((t) => (
                    <td key={t.name} className="text-center">
                      {c.allowed_tools.includes(t.name) ? (
                        <span className="text-defense-600">●</span>
                      ) : (
                        <span className="text-slate-200">·</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[12px] text-slate-500">● = tool nằm trong allowlist của tác vụ; D3 chặn tool ngoài danh sách.</p>
      </div>
    </div>
  );
}

export function AssetPanel({ code, onClose }: { code: AssetCode | null; onClose: () => void }) {
  useEffect(() => {
    if (!code) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [code, onClose]);

  if (!code) return null;
  const m = META[code];
  const Icon = m.icon;
  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col bg-white shadow-xl">
        <div className="flex items-start gap-3 border-b border-slate-100 px-6 py-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            <Icon size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Badge tone="neutral" className="font-mono">{code}</Badge>
              <span className="text-[15px] font-semibold text-slate-900">{m.title}</span>
            </div>
            <p className="text-[12.5px] text-slate-500">{m.sub}</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Đóng"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {code === "TS1" && <SystemPromptView />}
          {code === "TS2" && <CustomersView />}
          {code === "TS3" && <ToolsView />}
        </div>
      </aside>
    </div>
  );
}
