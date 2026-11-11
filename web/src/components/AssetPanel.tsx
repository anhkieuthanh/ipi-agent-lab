import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import { api } from "@/lib/api";
import { Badge, Button, ErrorBox, Loading, Mono } from "@/components/ui";

/** TS1–TS3: tài sản cần bảo vệ. Click thẻ ở trang Sơ đồ hệ thống mở panel này. */
export type AssetCode = "TS1" | "TS2" | "TS3";

const META: Record<AssetCode, { title: string; sub: string }> = {
  TS1: { title: "System prompt", sub: "Quy tắc nghiệp vụ và danh sách tool đưa vào mỗi run" },
  TS2: { title: "customers.db", sub: "Dữ liệu khách hàng mô phỏng — nguồn kẻ tấn công muốn rò" },
  TS3: { title: "Quyền gọi tool", sub: "Năm tool và quyền hành động của agent" },
};

function highlightCanary(text: string, placeholder: string) {
  const parts = text.split(placeholder);
  return parts.map((part, i) => (
    <span key={i}>
      {part}
      {i < parts.length - 1 && (
        <mark className="rounded-sm bg-amber-200 px-0.5 font-mono text-xs text-amber-800">{placeholder}</mark>
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <Badge tone="neutral" className="font-mono">biến thể: {d.variant}</Badge>
        <span className="num">{d.chars} ký tự</span>
        <Mono className="text-2xs">hash {d.template_hash.slice(0, 12)}</Mono>
      </div>
      <pre className="code-block">
        {highlightCanary(d.text, d.canary_placeholder)}
      </pre>
      <p className="text-xs text-slate-500">
        Vệt vàng <Mono className="text-2xs">{d.canary_placeholder}</Mono> là nơi gieo canary TS1 lúc chạy —
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <Badge tone="neutral" className="font-mono">{d.table}</Badge>
        <span className="num">{d.total} bản ghi</span>
        <span className="num">{d.seeded_rows} bản ghi mồi canary</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="table-base min-w-max">
          <thead>
            <tr>
              {d.columns.map((c) => (
                <th key={c.name}>
                  {c.name}
                  <span className="ml-1 font-mono text-2xs font-normal text-slate-400">{c.type}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.rows.map((r, i) => (
              <tr key={i} className={r._seeded ? "bg-amber-50 hover:bg-amber-50" : undefined}>
                {cols.map((c) => (
                  <td key={c} className="num whitespace-nowrap text-xs text-slate-700">
                    {String(r[c] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        {d.note} Hàng tô vàng là bản ghi mồi (id {d.canary_row_id}); cột <Mono className="text-2xs">canary_note</Mono> đã ẩn.
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
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {d.tools.map((t) => (
          <div key={t.name} className="px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Mono className="font-medium text-slate-900">{t.name}</Mono>
              {t.code && <Badge tone="neutral">{t.code}</Badge>}
              <Badge tone={t.side_effect ? "attack" : "defense"}>{t.kind}</Badge>
            </div>
            <p className="mt-1 text-xs text-slate-600">{t.description}</p>
            {t.args.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {t.args.map((a) => (
                  <span key={a.name} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-2xs text-slate-600">
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
        <h3 className="mb-2 text-sm font-semibold text-slate-900">Tool được phép theo tác vụ chở</h3>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="table-base min-w-max">
            <thead>
              <tr>
                <th>Tác vụ</th>
                {d.tools.map((t) => (
                  <th key={t.name} className="text-center font-mono text-2xs font-normal">{t.name}</th>
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
                        <span className="text-defense-600">
                          <span aria-hidden="true">●</span>
                          <span className="sr-only">được phép</span>
                        </span>
                      ) : (
                        <span className="text-slate-300">
                          <span aria-hidden="true">·</span>
                          <span className="sr-only">không được phép</span>
                        </span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">● = tool nằm trong allowlist của tác vụ; D3 chặn tool ngoài danh sách.</p>
      </div>
    </div>
  );
}

export function AssetPanel({ code, onClose }: { code: AssetCode | null; onClose: () => void }) {
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!code) return;
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const panel = panelRef.current;
    panel?.focus();
    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !panel) return;
      const nodes = Array.from(panel.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [tabindex="0"]')).filter(n => !n.hasAttribute("disabled"));
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (!first) { e.preventDefault(); panel.focus(); }
      else if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || document.activeElement === panel)) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", trap);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("keydown", trap); document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, [code, onClose]);

  if (!code) return null;
  const m = META[code];
  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-slate-900/20 dark:bg-black/50" onClick={onClose} />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={m.title}
        tabIndex={-1}
        className="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col border-l border-slate-200 bg-surface shadow-pop outline-none"
      >
        <header className="sticky top-0 z-10 flex items-start gap-3 border-b border-slate-200 bg-surface px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral" className="font-mono">{code}</Badge>
              <h2 className="min-w-0 break-words text-md font-semibold text-slate-900">{m.title}</h2>
            </div>
            <p className="mt-0.5 text-xs text-slate-500">{m.sub}</p>
          </div>
          <Button variant="ghost" size="sm" className="w-7 px-0" onClick={onClose} aria-label="Đóng" icon={<X size={15} />} />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {code === "TS1" && <SystemPromptView />}
          {code === "TS2" && <CustomersView />}
          {code === "TS3" && <ToolsView />}
        </div>
      </aside>
    </div>
  );
}
