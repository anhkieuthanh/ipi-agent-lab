// Bảng lệnh (⌘K / Ctrl+K): nhảy tới trang, lô, hoặc run theo mã — không cần chuột.

import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { CornerDownLeft, Layers, ListTree, Monitor, Moon, RefreshCw, Search, Sun } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Kbd } from "@/components/ui";
import { api } from "@/lib/api";
import { KIND_LABEL, when } from "@/lib/format";
import { NAV } from "@/lib/nav";

const ITEM =
  "flex h-9 cursor-pointer select-none items-center gap-2.5 rounded-md px-2.5 text-sm text-slate-700 " +
  "data-[selected=true]:bg-slate-100 data-[selected=true]:text-slate-900";
const GROUP =
  "[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2 " +
  "[&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-slate-400";

function Row({ icon, children, hint }: { icon: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <>
      <span className="shrink-0 text-slate-400">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {hint && <span className="flex shrink-0 items-center gap-1 text-xs text-slate-400">{hint}</span>}
    </>
  );
}

export function CommandPalette({
  open,
  onOpenChange,
  scopeSearch,
  dark,
  onToggleTheme,
  onTogglePresent,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Chuỗi `?scope=…&batch=…` hiện hành để giữ phạm vi khi đổi trang. */
  scopeSearch: string;
  dark: boolean;
  onToggleTheme: () => void;
  onTogglePresent: () => void;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api.batches(), enabled: open, staleTime: 15_000 });

  const run = (fn: () => void) => () => {
    onOpenChange(false);
    setQuery("");
    fn();
  };
  const q = query.trim();
  const looksLikeRunId = /^[0-9a-f]{32}$/i.test(q);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Bảng lệnh"
      overlayClassName="fixed inset-0 z-50 bg-slate-900/20 backdrop-blur-[1px] dark:bg-black/50"
      contentClassName="fixed left-1/2 top-[14vh] z-50 w-[min(92vw,560px)] -translate-x-1/2 overflow-hidden rounded-xl bg-surface shadow-pop"
    >
      <div className="flex items-center gap-2.5 border-b border-slate-200 px-3.5">
        <Search size={15} className="shrink-0 text-slate-400" />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Tìm trang, lô, mã run, mã payload…"
          className="h-11 w-full bg-transparent text-base text-slate-900 outline-none placeholder:text-slate-400"
        />
        <Kbd>Esc</Kbd>
      </div>
      <Command.List className="max-h-[min(60vh,420px)] overflow-y-auto p-1.5">
        <Command.Empty className="px-3 py-8 text-center text-sm text-slate-500">Không có kết quả khớp.</Command.Empty>

        {q && (
          <Command.Group heading="Tìm trong lượt chạy" className={GROUP}>
            {looksLikeRunId && (
              <Command.Item value={`run ${q}`} className={ITEM} onSelect={run(() => navigate(`/runs/${q}`))}>
                <Row icon={<ListTree size={15} />} hint={<CornerDownLeft size={12} />}>
                  Mở run <span className="font-mono text-xs">{q}</span>
                </Row>
              </Command.Item>
            )}
            <Command.Item
              value={`search ${q}`}
              className={ITEM}
              onSelect={run(() => navigate(`/runs?scope=all&q=${encodeURIComponent(q)}`))}
            >
              <Row icon={<Search size={15} />}>
                Tìm “{q}” trong mọi lượt chạy
              </Row>
            </Command.Item>
          </Command.Group>
        )}

        {NAV.map((g, i) => (
          <Command.Group key={i} heading={g.label ?? "Điều hướng"} className={GROUP}>
            {g.items.map((it) => (
              <Command.Item
                key={it.to}
                value={`${it.label} ${g.label ?? ""}`}
                className={ITEM}
                onSelect={run(() => navigate({ pathname: it.to, search: it.scoped ? scopeSearch : "" }))}
              >
                <Row icon={<it.icon size={15} />} hint={<><Kbd>G</Kbd><Kbd>{it.key.toUpperCase()}</Kbd></>}>
                  {it.label}
                </Row>
              </Command.Item>
            ))}
          </Command.Group>
        ))}

        <Command.Group heading="Thao tác" className={GROUP}>
          <Command.Item value="làm mới dữ liệu refresh" className={ITEM} onSelect={run(onRefresh)}>
            <Row icon={<RefreshCw size={15} />}>Làm mới dữ liệu</Row>
          </Command.Item>
          <Command.Item value="giao diện sáng tối theme dark light" className={ITEM} onSelect={run(onToggleTheme)}>
            <Row icon={dark ? <Sun size={15} /> : <Moon size={15} />}>{dark ? "Chuyển sang nền sáng" : "Chuyển sang nền tối"}</Row>
          </Command.Item>
          <Command.Item value="trình bày presentation" className={ITEM} onSelect={run(onTogglePresent)}>
            <Row icon={<Monitor size={15} />}>Bật / tắt chế độ trình bày</Row>
          </Command.Item>
        </Command.Group>

        {(batches.data?.length ?? 0) > 0 && (
          <Command.Group heading="Lô" className={GROUP}>
            {batches.data!.slice(0, 60).map((b) => (
              <Command.Item
                key={b.batch_id}
                value={`lô ${b.batch_id} ${KIND_LABEL[b.kind]} ${b.targets.join(" ")}`}
                className={ITEM}
                onSelect={run(() => navigate(`/runs?scope=${b.kind}&batch=${encodeURIComponent(b.batch_id)}`))}
              >
                <Row icon={<Layers size={15} />} hint={<>{KIND_LABEL[b.kind]} · {when(b.created_at)}</>}>
                  <span className="font-mono text-xs">{b.batch_id}</span>
                </Row>
              </Command.Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  );
}
